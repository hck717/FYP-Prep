# src/skills/fundamentals.py
from __future__ import annotations

from typing import Any, Dict

from src.contracts.types import EvidencePack, FundamentalsInputs, FundamentalsJSON
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.tools.graphrag_tool import GraphRagTool


def fundamentals_skill(
    inputs: FundamentalsInputs,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_tool: GraphRagTool,
) -> FundamentalsJSON:
    # Minimal “shape-locking” queries (replace later with your 8Q checkpoint)
    prices = sql_tool.read_query(f"""
        SELECT date, close, volume, ingested_at
        FROM prices_daily
        WHERE ticker='{inputs.ticker}'
        ORDER BY date DESC
        LIMIT 5
    """)

    ep: EvidencePack = graphrag_tool.retrieve(f"{inputs.ticker} {inputs.focus} drivers")

    financials_summary: Dict[str, Any] = {
        "price_sample": {
            "sql_evidence_id": prices.sql_evidence_id,
            "columns": prices.columns,
            "rows": prices.rows,
        }
    }

    # Stub drivers/risks with evidence references (shape only)
    drivers = []
    for c in ep.seed_chunks[:3]:
        drivers.append({"text": "Driver supported by internal text evidence.", "evidence_ids": [c.evidence_id]})

    risks = []
    for c in ep.expanded_chunks[:2]:
        risks.append({"text": "Risk supported by internal text evidence.", "evidence_ids": [c.evidence_id]})

    return FundamentalsJSON(
        ticker=inputs.ticker,
        horizon=inputs.horizon,
        financials_summary=financials_summary,
        drivers=drivers,
        risks=risks,
    )
