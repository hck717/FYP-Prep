# src/skills/valuation.py
from __future__ import annotations

from typing import Any, Dict, List

from src.contracts.types import EvidencePack, ValuationInputs, ValuationJSON
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.tools.graphrag_tool import GraphRagTool


def valuation_skill(
    inputs: ValuationInputs,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_tool: GraphRagTool,
) -> ValuationJSON:
    # Minimal shape-locking query (replace later with ratios_ttm/price/EV comps logic)
    snap = sql_tool.read_query(f"""
        SELECT *
        FROM snapshot_kv
        WHERE ticker='{inputs.ticker}'
        LIMIT 50
    """)

    ep: EvidencePack = graphrag_tool.retrieve(f"{inputs.ticker} valuation assumptions support")

    assumptions: List[Dict[str, Any]] = []
    if ep.seed_chunks:
        assumptions.append(
            {"name": "Revenue growth (base)", "value": "placeholder", "evidence_ids": [ep.seed_chunks[0].evidence_id]}
        )

    return ValuationJSON(
        ticker=inputs.ticker,
        horizon=inputs.horizon,
        valuation_range={"low": None, "base": None, "high": None, "notes": "stub"},
        assumptions=assumptions,
        sensitivity={"table": [], "notes": "stub"},
    )
