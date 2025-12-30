# src/skills/fundamentals_skill.py
from __future__ import annotations

from typing import Any, Dict, List

from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve


def fundamentals_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    focus: str = "services",
) -> Dict[str, Any]:
    # --- Numbers (MCP) ---
    # Keep it minimal: reuse your Step 1 idea (period list + line items)
    periods_res = sql_tool.read_query(f"""
        SELECT DISTINCT period_end
        FROM fundamentals
        WHERE ticker='{ticker}'
          AND period_type='quarterly'
        ORDER BY period_end DESC
        LIMIT 8
    """)
    periods = [r[0] for r in periods_res.rows]  # one column: period_end

    wanted = ["Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow"]
    periods_in = ", ".join([f"'{p}'" for p in periods])
    items_in = ", ".join([f"'{x}'" for x in wanted])

    items_res = sql_tool.read_query(f"""
        SELECT period_end, line_item, value, ingested_at
        FROM fundamentals
        WHERE ticker='{ticker}'
        AND period_type='quarterly'
        AND line_item IN ('Total Revenue','Net Income','Diluted EPS','Basic EPS','Free Cash Flow')
        ORDER BY period_end DESC
        LIMIT 200
    """)

    # Pivot
    panel: Dict[str, Dict[str, Any]] = {p: {} for p in periods}
    ing: Dict[str, str] = {}
    for pe, li, val, ingested_at in items_res.rows:
        panel.setdefault(pe, {})[li] = val
        ing[pe] = max(ing.get(pe, ""), ingested_at or "")

    financials_summary = {
        "periods": periods,
        "panel": panel,
        "ingested_at_by_period": ing,
        "sql_evidence_ids": [periods_res.sql_evidence_id, items_res.sql_evidence_id],
    }

    # --- Text evidence (GraphRAG) ---
    ep = graphrag_retrieve(f"{ticker} {focus} growth drivers", graphrag_cfg)

    # Simple POC: take top seed chunks as drivers, expanded chunks as risks/extra
    drivers = [
        {"text": c.get("text", "")[:220], "evidence_ids": [c["evidence_id"]]}
        for c in ep.get("seed_chunks", [])[:4]
    ]
    related_evidence = [
        {"text": c.get("text", "")[:220], "evidence_ids": [c["evidence_id"]]}
        for c in ep.get("expanded_chunks", [])[:3]
    ]

    return {
        "ticker": ticker,
        "financials_summary": financials_summary,
        "drivers": drivers,
        "related_evidence": related_evidence,
        "evidence_pack_meta": ep.get("provenance", {}),
    }
