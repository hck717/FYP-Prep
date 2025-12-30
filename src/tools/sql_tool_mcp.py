# src/tools/sql_tool_mcp.py
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.contracts.types import SqlMeta, SqlResult


# Security patterns
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|pragma|exec)\b",
    re.IGNORECASE
)

# Default allowlisted tables (matching your schema)
ALLOWED_TABLES = {
    "prices_daily",
    "fundamentals_quarterly",
    "ratios_ttm",
    "events",
    "ticker_meta",
}

MAX_LIMIT = 200


def _hash(s: str) -> str:
    """Generate deterministic hash for SQL queries"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def guard_sql(sql: str, allowed_tables: set[str], max_limit: int) -> str:
    """
    Enforce read-only guardrails on SQL queries:
    - Only SELECT allowed
    - No write/admin operations
    - Must reference allowed tables
    - Enforce LIMIT cap
    """
    s = sql.strip().rstrip(";")
    low = s.lower()

    # 1) Only SELECT
    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")

    # 2) No forbidden keywords
    if FORBIDDEN.search(low):
        raise ValueError("Forbidden keyword detected (write/admin SQL).")

    # 3) Must reference at least one allowed table
    if not any(tbl in low for tbl in allowed_tables):
        raise ValueError(
            f"Query must reference allowed tables: {sorted(allowed_tables)}"
        )

    # 4) Enforce LIMIT
    if "limit" not in low:
        s = f"{s} LIMIT {max_limit}"
    else:
        # Cap existing LIMIT if too high
        match = re.search(r"\blimit\s+(\d+)\b", low)
        if match and int(match.group(1)) > max_limit:
            s = re.sub(
                r"\blimit\s+\d+\b",
                f"LIMIT {max_limit}",
                s,
                flags=re.IGNORECASE
            )

    return s


def _records_to_table(records: List[dict]) -> Tuple[List[str], List[List[Any]]]:
    """Convert list of dicts to columns + rows format"""
    if not records:
        return [], []
    cols = list(records[0].keys())
    rows = [[r.get(c) for c in cols] for r in records]
    return cols, rows


def _extract_rows_columns(call_tool_result: Any) -> Tuple[List[str], List[List[Any]]]:
    """
    Extract tabular data from MCP tool result.
    Supports:
    - structuredContent: {"columns":[...],"rows":[...]}
    - structuredContent: {"records":[{...},...]"}
    - content: [TextContent(text="...")] with JSON or Python literal
    """
    # Try structuredContent first
    sc = getattr(call_tool_result, "structuredContent", None)
    if isinstance(sc, dict):
        if "columns" in sc and "rows" in sc:
            return list(sc["columns"]), list(sc["rows"])
        if "records" in sc:
            return _records_to_table(sc["records"])

    # Fallback to content blocks
    content = getattr(call_tool_result, "content", None)
    if isinstance(content, list) and content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str) and text.strip():
            s = text.strip()
            
            # Try JSON
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    if "columns" in obj and "rows" in obj:
                        return list(obj["columns"]), list(obj["rows"])
                    if "records" in obj:
                        return _records_to_table(obj["records"])
                if isinstance(obj, list):
                    return _records_to_table(obj)
            except Exception:
                pass
            
            # Try Python literal (fallback)
            try:
                import ast
                obj = ast.literal_eval(s)
                if isinstance(obj, list):
                    return _records_to_table(obj)
            except Exception:
                pass

    return [], []


@dataclass
class McpSqliteReadOnlyTool:
    """
    Read-only SQL tool wrapper for MCP SQLite server.
    Enforces security guardrails and provides evidence IDs.
    """
    db_path: str = "research.db"
    max_limit: int = 200
    allowed_tables: set[str] = None

    def __post_init__(self):
        if self.allowed_tables is None:
            self.allowed_tables = ALLOWED_TABLES

    async def _read_query_async(self, sql: str) -> SqlResult:
        """Execute read-only query via MCP (async)"""
        # Apply guardrails
        safe_sql = guard_sql(sql, self.allowed_tables, self.max_limit)
        
        # Setup MCP server connection
        server = StdioServerParameters(
            command="uvx",
            args=["mcp-server-sqlite", "--db-path", self.db_path],
            env=None,
        )

        # Execute query
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                raw = await session.call_tool("read_query", {"query": safe_sql})

        # Extract data
        columns, rows = _extract_rows_columns(raw)

        # Build metadata
        raw_preview = ""
        try:
            if raw.content and hasattr(raw.content[0], "text"):
                raw_preview = raw.content[0].text[:300]
        except Exception:
            pass

        meta = SqlMeta(
            tool="mcp-server-sqlite.read_query",
            db_path=self.db_path,
            max_limit=self.max_limit,
            allowlisted_tables=sorted(self.allowed_tables),
            raw_preview=raw_preview,
        )

        # Generate evidence ID
        timestamp = datetime.now().isoformat()
        evidence_id = f"sql:{_hash(safe_sql)}:{timestamp}"

        return SqlResult(
            query=safe_sql,
            columns=columns,
            rows=rows,
            meta=meta,
            sql_evidence_id=evidence_id,
        )

    def read_query(self, sql: str) -> SqlResult:
        """Sync wrapper for async query execution"""
        return asyncio.run(self._read_query_async(sql))


# Convenience function for quick testing
def test_sql_tool():
    """Quick test of SQL tool"""
    tool = McpSqliteReadOnlyTool()
    
    # Test 1: List tables
    result = tool.read_query("""
        SELECT name FROM sqlite_master 
        WHERE type='table' 
        ORDER BY name
    """)
    print(f"✅ Tables query: {len(result.rows)} results")
    print(f"   Evidence ID: {result.sql_evidence_id}")
    
    # Test 2: Query AAPL fundamentals
    result2 = tool.read_query("""
        SELECT period_end, line_item, value
        FROM fundamentals_quarterly
        WHERE ticker='AAPL'
        ORDER BY period_end DESC
        LIMIT 10
    """)
    print(f"✅ AAPL fundamentals: {len(result2.rows)} rows")
    print(f"   Columns: {result2.columns}")
    print(f"   Evidence ID: {result2.sql_evidence_id}")


if __name__ == "__main__":
    test_sql_tool()
