# src/skills/valuation_skill.py
from __future__ import annotations

from typing import Any, Dict, List

from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve


def valuation_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
) -> Dict[str, Any]:
    # Minimal inputs: latest close + latest diluted EPS (if available)
    px = sql_tool.read_query(f"""
        SELECT date, close, ingested_at
        FROM prices_daily
        WHERE ticker='{ticker}'
        ORDER BY date DESC
        LIMIT 1
    """)

    eps = sql_tool.read_query(f"""
        SELECT period_end, value, ingested_at
        FROM fundamentals
        WHERE ticker='{ticker}'
          AND line_item='Diluted EPS'
        ORDER BY period_end DESC
        LIMIT 1
    """)

    last_close = px.rows[0][1] if px.rows else None
    last_eps_q = eps.rows[0][1] if eps.rows else None

    # Toy “annualize” EPS (POC only)
    eps_ttm_proxy = (last_eps_q * 4) if (last_eps_q is not None) else None

    # Toy comps: P/E range
    pe_low, pe_base, pe_high = 20, 25, 30
    val_low = eps_ttm_proxy * pe_low if eps_ttm_proxy else None
    val_base = eps_ttm_proxy * pe_base if eps_ttm_proxy else None
    val_high = eps_ttm_proxy * pe_high if eps_ttm_proxy else None

    ep = graphrag_retrieve(f"{ticker} margin outlook guidance", graphrag_cfg)
    support_ids: List[str] = []
    if ep.get("seed_chunks"):
        support_ids.append(ep["seed_chunks"][0]["evidence_id"])

    return {
        "ticker": ticker,
        "inputs": {
            "last_close": last_close,
            "eps_ttm_proxy": eps_ttm_proxy,
            "sql_evidence_ids": [px.sql_evidence_id, eps.sql_evidence_id],
        },
        "assumptions": [
            {"name": "P/E low/base/high", "value": [pe_low, pe_base, pe_high], "evidence_ids": support_ids}
        ],
        "valuation_range": {"low": val_low, "base": val_base, "high": val_high},
        "notes": "Toy valuation for POC; replace with DCF/comps later.",
    }
