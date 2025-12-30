# src/skills/fundamentals_skill.py
from __future__ import annotations

import json
import pandas as pd
from pathlib import Path
from typing import Any, Dict, Optional, List

from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve

_EXEMPLAR_PATH = Path("artifacts/exemplars_fundamentals.jsonl")

def _load_exemplars(focus: str, max_n: int = 2) -> str:
    """Return a short few-shot block from artifacts/exemplars_fundamentals.jsonl if present."""
    if not _EXEMPLAR_PATH.exists():
        return ""
    # (Existing exemplar loading logic kept brief for clarity)
    return ""

def _compute_financial_metrics(rows: List[Any], periods: List[str]) -> Dict[str, Any]:
    """
    Convert raw SQL rows into a pandas DataFrame and compute:
    - TTM (Trailing Twelve Months) aggregates
    - YoY Growth Rates
    - Margins
    """
    if not rows:
        return {}
    
    # Columns: period_end, line_item, value, ingested_at
    df = pd.DataFrame(rows, columns=["period_end", "line_item", "value", "ingested_at"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    df["period_end"] = pd.to_datetime(df["period_end"])
    
    # Pivot to: Index=Date, Cols=Line Items
    pivot = df.pivot_table(index="period_end", columns="line_item", values="value", aggfunc="sum").sort_index(ascending=False)
    
    # Ensure we have essential columns
    required = ["Total Revenue", "Net Income", "Diluted EPS", "Free Cash Flow"]
    for c in required:
        if c not in pivot.columns:
            pivot[c] = 0.0

    # --- Calculations ---
    latest = pivot.iloc[0] if not pivot.empty else pd.Series()
    
    # 1. TTM Aggregates (Sum of last 4 qtrs)
    if len(pivot) >= 4:
        ttm = pivot.iloc[:4].sum()
        ttm_revenue = ttm.get("Total Revenue", 0)
        ttm_ni = ttm.get("Net Income", 0)
        ttm_fcf = ttm.get("Free Cash Flow", 0)
        ttm_eps = ttm.get("Diluted EPS", 0) # Summing EPS is a proxy approximation
    else:
        # Fallback if <4 qtrs: annualized latest
        ttm_revenue = latest.get("Total Revenue", 0) * 4
        ttm_ni = latest.get("Net Income", 0) * 4
        ttm_fcf = latest.get("Free Cash Flow", 0) * 4
        ttm_eps = latest.get("Diluted EPS", 0) * 4

    # 2. Margins (on TTM basis)
    net_margin = (ttm_ni / ttm_revenue) if ttm_revenue else 0.0
    fcf_margin = (ttm_fcf / ttm_revenue) if ttm_revenue else 0.0

    # 3. Growth (YoY of Latest Quarter)
    # Compare Q_current vs Q_current-4
    rev_growth_yoy = 0.0
    eps_growth_yoy = 0.0
    
    if len(pivot) >= 5:
        curr = pivot.iloc[0]
        prev_yr = pivot.iloc[4] # 4 quarters ago
        
        r1, r0 = curr.get("Total Revenue", 0), prev_yr.get("Total Revenue", 0)
        e1, e0 = curr.get("Diluted EPS", 0), prev_yr.get("Diluted EPS", 0)
        
        if r0 != 0:
            rev_growth_yoy = (r1 - r0) / abs(r0)
        if e0 != 0:
            eps_growth_yoy = (e1 - e0) / abs(e0)

    # Convert pivot to pure dict with string keys for JSON serialization
    # 1. Reset index to make 'period_end' a column
    pivot_reset = pivot.reset_index()
    # 2. Convert timestamp to string
    pivot_reset["period_end"] = pivot_reset["period_end"].dt.strftime("%Y-%m-%d")
    # 3. Set index back for to_dict(orient='index')
    pivot_reset.set_index("period_end", inplace=True)
    raw_pivot_dict = pivot_reset.head(8).to_dict(orient="index")

    return {
        "ttm": {
            "revenue": float(ttm_revenue),
            "net_income": float(ttm_ni),
            "fcf": float(ttm_fcf),
            "eps": float(ttm_eps)
        },
        "margins": {
            "net_margin": float(net_margin),
            "fcf_margin": float(fcf_margin)
        },
        "growth": {
            "revenue_yoy": float(rev_growth_yoy),
            "eps_yoy": float(eps_growth_yoy)
        },
        "latest_quarter_date": pivot.index[0].strftime("%Y-%m-%d") if not pivot.empty else None,
        "raw_pivot": raw_pivot_dict
    }

def fundamentals_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    focus: str = "services",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    
    # 1. Fetch Data
    items_res = sql_tool.read_query(
        f"""
        SELECT period_end, line_item, value, ingested_at
        FROM fundamentals
        WHERE ticker='{ticker}'
        AND line_item IN ('Total Revenue','Net Income','Diluted EPS','Basic EPS','Free Cash Flow')
        ORDER BY period_end DESC
        LIMIT 200
    """
    )
    
    # 2. Compute Advanced Metrics
    metrics = _compute_financial_metrics(items_res.rows, [])
    
    # Re-structure for the UI table
    # Convert dataframe-like dict back to the "periods/panel" format agent.py expects
    raw_pivot = metrics.get("raw_pivot", {})
    # periods keys are already strings now
    periods_str = list(raw_pivot.keys())
    panel = raw_pivot # already in correct format {date: {col: val}}

    financials_summary = {
        "periods": periods_str,
        "panel": panel,
        "metrics": metrics, # The new rich data
        "sql_evidence_ids": [items_res.sql_evidence_id],
    }

    # 3. Advanced RAG (Drivers + Guidance)
    ep = graphrag_retrieve(f"{ticker} {focus} growth drivers revenue guidance", graphrag_cfg)
    seed_chunks = ep.get("seed_chunks", [])[:8]
    
    drivers = []
    guidance_extracted = []

    if api_key and seed_chunks:
        try:
            from src.llm.perplexity_client import call_perplexity
            
            context_str = "\n\n".join([
                f"Chunk {i+1} (ID: {c.get('evidence_id')}): {c.get('text', '')}"
                for i, c in enumerate(seed_chunks) if isinstance(c, dict)
            ])

            system_msg = {
                "role": "system",
                "content": (
                    "You are a Lead Equity Research Analyst. Extract two things:\n"
                    "1. GROWTH DRIVERS: Strategic factors driving revenue/margin.\n"
                    "2. GUIDANCE: Specific numeric forward-looking targets (e.g. 'expect revenue to grow 5%').\n"
                    "Be skeptical and data-driven."
                )
            }
            
            user_msg = {
                "role": "user",
                "content": f"""
Based on these chunks, output JSON:
{{
  "drivers": [
    {{
      "text": "Impactful driver description...",
      "evidence_ids": ["..."],
      "evidence_quality": "Strong|Medium|Weak",
      "disconfirming_check": "What metric would disprove this?"
    }}
  ],
  "guidance": [
    {{
      "metric": "Revenue/Margin/EPS",
      "period": "Next Q / FY25",
      "value_text": "e.g. low-single digits",
      "evidence_ids": ["..."]
    }}
  ]
}}

Context:
{context_str}
"""
            }

            resp = call_perplexity(api_key, [system_msg, user_msg])
            parsed = json.loads(resp)
            
            if isinstance(parsed, dict):
                drivers = parsed.get("drivers", [])
                guidance_extracted = parsed.get("guidance", [])
                
        except Exception as e:
            print(f"Perplexity triangulation failed: {e}")

    # Fallback / formatting
    final_drivers = []
    for d in drivers:
        if isinstance(d, dict):
            final_drivers.append(d)
    
    # If no drivers found by LLM, fallback to simple chunk text
    if not final_drivers:
        final_drivers = [
            {"text": c.get("text", "")[:200], "evidence_ids": [c.get("evidence_id")]}
            for c in seed_chunks if isinstance(c, dict)
        ]

    return {
        "ticker": ticker,
        "financials_summary": financials_summary,
        "drivers": final_drivers,
        "guidance": guidance_extracted,
        "computed_metrics": metrics, # Pass this explicit dict for Valuation to use
        "evidence_pack_meta": ep.get("provenance", {})
    }
