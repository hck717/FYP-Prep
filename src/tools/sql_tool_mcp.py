# src/tools/sql_tool_mcp.py
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.contracts.types import SqlMeta, SqlResult


FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma)\b", re.IGNORECASE)

ALLOWED_TABLES = {
  "prices_daily",
  "fundamentals_quarterly",
  "ratios_ttm",
  "events",
  "ticker_meta",   # optional
}
MAX_LIMIT = 200


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def guard_sql(sql: str, allowed_tables: set[str], max_limit: int) -> str:
    s = sql.strip().rstrip(";")
    low = s.lower()

    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")

    if FORBIDDEN.search(low):
        raise ValueError("Forbidden keyword detected (write/admin SQL).")

    if not any(tbl in low for tbl in allowed_tables):
        raise ValueError(f"Query must reference allowed tables: {sorted(allowed_tables)}")

    # enforce LIMIT
    if re.search(r"\blimit\b", low) is None:
        s = f"{s} LIMIT {max_limit}"
    else:
        m = re.search(r"\blimit\s+(\d+)\b", low)
        if m and int(m.group(1)) > max_limit:
            s = re.sub(r"\blimit\s+\d+\b", f"LIMIT {max_limit}", s, flags=re.IGNORECASE)

    return s


import ast
import json
from typing import Any, List, Tuple


def _records_to_table(records: List[dict]) -> tuple[List[str], List[List[Any]]]:
    if not records:
        return [], []
    # preserve key order from the first row
    cols = list(records[0].keys())
    rows = [[r.get(c) for c in cols] for r in records]
    return cols, rows


def _extract_rows_columns(call_tool_result: Any) -> Tuple[List[str], List[List[Any]]]:
    """
    Supports:
    - structuredContent: {"columns":[...],"rows":[...]} or {"records":[{...},...]}
    - content: [TextContent(text="...")] containing JSON or Python-literal list-of-dicts
    """
    # 1) structuredContent (preferred)
    sc = getattr(call_tool_result, "structuredContent", None)
    if isinstance(sc, dict):
        if "columns" in sc and "rows" in sc:
            return list(sc["columns"]), list(sc["rows"])
        if "records" in sc and isinstance(sc["records"], list):
            return _records_to_table(sc["records"])

    # 2) content blocks
    content = getattr(call_tool_result, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str) and text.strip():
            s = text.strip()

            # 2a) Try strict JSON first
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and "columns" in obj and "rows" in obj:
                    return list(obj["columns"]), list(obj["rows"])
                if isinstance(obj, list) and (len(obj) == 0 or isinstance(obj[0], dict)):
                    return _records_to_table(obj)
            except Exception:
                pass

            # 2b) Fallback: Python literal (your current server output)
            try:
                obj = ast.literal_eval(s)
                if isinstance(obj, list) and (len(obj) == 0 or isinstance(obj[0], dict)):
                    return _records_to_table(obj)
            except Exception:
                pass

    return [], []


@dataclass
class McpSqliteReadOnlyTool:
    db_path: str = "research.db"
    max_limit: int = 200
    allowed_tables: set[str] = None

    def __post_init__(self) -> None:
        if self.allowed_tables is None:
            # keep aligned with your existing POC allowlist (update later)
            self.allowed_tables = {"prices_daily", "fundamentals", "snapshot_kv", "dim_company"}

    async def _read_query_async(self, sql: str) -> SqlResult:
        safe_sql = guard_sql(sql, self.allowed_tables, self.max_limit)

        server = StdioServerParameters(
            command="uvx",
            args=["mcp-server-sqlite", "--db-path", self.db_path],
            env=None,
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                raw = await session.call_tool("read_query", {"query": safe_sql})

        raw_preview = ""
        try:
            if raw.content and getattr(raw.content[0], "text", None):
                raw_preview = raw.content[0].text[:300]
        except Exception:
            pass
        columns, rows = _extract_rows_columns(raw)

        meta = SqlMeta(
            tool="mcp-server-sqlite.read_query",
            db_path=self.db_path,
            max_limit=self.max_limit,
            allowlisted_tables=sorted(self.allowed_tables),
        )
        evidence_id = f"sql:{_hash(safe_sql)}"
        return SqlResult(query=safe_sql, columns=columns, rows=rows, meta=meta, sql_evidence_id=evidence_id)

    def read_query(self, sql: str) -> SqlResult:
        # Sync-friendly wrapper so Streamlit/skills can call it normally.
        return asyncio.run(self._read_query_async(sql))
