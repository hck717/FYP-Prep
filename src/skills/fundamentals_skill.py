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
    return ""


def _clean_chunk_text(t: str, max_len: int = 220) -> str:
    """Lightweight cleanup for fallback driver text (POC-safe, non-LLM)."""
    if not t:
        return ""
    s = " ".join(str(t).split())
    # Remove common retrieval boilerplate that sometimes leaks into chunks
    s = s.replace("SOURCE:", "")
    s = s.replace("GOAL:", "")
    # Trim
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s


def _compute_financial_metrics(rows: List[Any]) -> Dict[str, Any]:
    """
    Convert raw SQL rows into a pandas DataFrame and compute:
    - TTM (Trailing Twelve Months) aggregates
    - YoY Growth Rates
    - Margins

    IMPORTANT: Only quarterly fundamentals should be passed in.
    """
    if not rows:
        return {}

    # Columns: period_end, line_item, value, ingested_at
    df = pd.DataFrame(rows, columns=["period_end", "line_item", "value", "ingested_at"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0.0)
    df["period_end"] = pd.to_datetime(df["period_end"], errors="coerce")

    # FIX: Deduplicate before pivoting to avoid inflated quarters when multiple ingests exist
    df = df.sort_values("ingested_at", ascending=False).drop_duplicates(subset=["period_end", "line_item"])

    pivot = (
        df.pivot_table(index="period_end", columns="line_item", values="value", aggfunc="max")
        .sort_index(ascending=False)
        .copy()
    )

    # Ensure essential columns exist
    required = ["Total Revenue", "Net Income", "Diluted EPS", "Free Cash Flow"]
    for c in required:
        if c not in pivot.columns:
            pivot[c] = 0.0

    latest = pivot.iloc[0] if not pivot.empty else pd.Series()

    # 1) TTM aggregates: sum last 4 quarters
    if len(pivot) >= 4:
        ttm = pivot.iloc[:4].sum()
        ttm_revenue = float(ttm.get("Total Revenue", 0.0))
        ttm_ni = float(ttm.get("Net Income", 0.0))
        ttm_fcf = float(ttm.get("Free Cash Flow", 0.0))
        # EPS summation is a proxy; kept for POC but should be replaced with true TTM EPS if available
        ttm_eps = float(ttm.get("Diluted EPS", 0.0))
    else:
        ttm_revenue = float(latest.get("Total Revenue", 0.0)) * 4
        ttm_ni = float(latest.get("Net Income", 0.0)) * 4
        ttm_fcf = float(latest.get("Free Cash Flow", 0.0)) * 4
        ttm_eps = float(latest.get("Diluted EPS", 0.0)) * 4

    # 2) Margins
    net_margin = (ttm_ni / ttm_revenue) if ttm_revenue else 0.0
    fcf_margin = (ttm_fcf / ttm_revenue) if ttm_revenue else 0.0

    # 3) YoY growth (latest quarter vs same quarter prior year)
    rev_growth_yoy = 0.0
    eps_growth_yoy = 0.0
    if len(pivot) >= 5:
        curr = pivot.iloc[0]
        prev_yr = pivot.iloc[4]
        r1, r0 = float(curr.get("Total Revenue", 0.0)), float(prev_yr.get("Total Revenue", 0.0))
        e1, e0 = float(curr.get("Diluted EPS", 0.0)), float(prev_yr.get("Diluted EPS", 0.0))
        if r0 != 0:
            rev_growth_yoy = (r1 - r0) / abs(r0)
        if e0 != 0:
            eps_growth_yoy = (e1 - e0) / abs(e0)

    # JSON-safe pivot dict (string keys)
    pivot_reset = pivot.reset_index()
    pivot_reset["period_end"] = pivot_reset["period_end"].dt.strftime("%Y-%m-%d")
    pivot_reset.set_index("period_end", inplace=True)
    raw_pivot_dict = pivot_reset.head(8).to_dict(orient="index")

    return {
        "ttm": {"revenue": ttm_revenue, "net_income": ttm_ni, "fcf": ttm_fcf, "eps": ttm_eps},
        "margins": {"net_margin": float(net_margin), "fcf_margin": float(fcf_margin)},
        "growth": {"revenue_yoy": float(rev_growth_yoy), "eps_yoy": float(eps_growth_yoy)},
        "latest_quarter_date": pivot.index[0].strftime("%Y-%m-%d") if not pivot.empty else None,
        "raw_pivot": raw_pivot_dict,
    }


def fundamentals_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    focus: str = "services",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:

    # --- 1) Fetch quarter list (CRITICAL FIX)
    # Your DB has period_type; without filtering, annual/TTM records can pollute the latest "quarter".
    periods_res = sql_tool.read_query(
        f"""
        SELECT DISTINCT period_end
        FROM fundamentals
        WHERE ticker='{ticker}'
          AND period_type='quarterly'
        ORDER BY period_end DESC
        LIMIT 8
        """
    )
    periods = [r[0] for r in (periods_res.rows or []) if r and r[0]]

    # --- 2) Fetch line items for those quarters only
    wanted_items = ["Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow"]
    items_in = ", ".join([f"'{x}'" for x in wanted_items])

    periods_clause = ""
    if periods:
        periods_in = ", ".join([f"'{p}'" for p in periods])
        periods_clause = f"AND period_end IN ({periods_in})"

    items_res = sql_tool.read_query(
        f"""
        SELECT period_end, line_item, value, ingested_at
        FROM fundamentals
        WHERE ticker='{ticker}'
          AND period_type='quarterly'
          {periods_clause}
          AND line_item IN ({items_in})
        ORDER BY period_end DESC, ingested_at DESC
        LIMIT 500
        """
    )

    # --- 3) Compute metrics
    metrics = _compute_financial_metrics(items_res.rows)

    raw_pivot = metrics.get("raw_pivot", {})
    periods_str = list(raw_pivot.keys())
    panel = raw_pivot

    financials_summary = {
        "periods": periods_str,
        "panel": panel,
        "metrics": metrics,
        "sql_evidence_ids": [items_res.sql_evidence_id],
    }

    # --- 4) RAG for drivers/guidance
    ep = graphrag_retrieve(f"{ticker} {focus} growth drivers revenue guidance", graphrag_cfg)
    seed_chunks = ep.get("seed_chunks", [])[:8]

    drivers = []
    guidance_extracted = []

    if api_key and seed_chunks:
        try:
            from src.llm.perplexity_client import call_perplexity

            context_str = "\n\n".join(
                [
                    f"Chunk {i+1} (ID: {c.get('evidence_id')}): {c.get('text', '')}"
                    for i, c in enumerate(seed_chunks)
                    if isinstance(c, dict)
                ]
            )

            system_msg = {
                "role": "system",
                "content": (
                    "You are a Lead Equity Research Analyst. Extract two things:\n"
                    "1. GROWTH DRIVERS: Strategic factors driving revenue/margin.\n"
                    "2. GUIDANCE: Specific numeric forward-looking targets (e.g. 'expect revenue to grow 5%').\n"
                    "Return ONLY valid JSON following the schema." 
                ),
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
""",
            }

            resp = call_perplexity(api_key, [system_msg, user_msg])
            parsed = json.loads(resp)
            if isinstance(parsed, dict):
                drivers = parsed.get("drivers", [])
                guidance_extracted = parsed.get("guidance", [])

        except Exception as e:
            print(f"Perplexity triangulation failed: {e}")

    # --- 5) Fallback formatting (POC-safe)
    final_drivers: List[Dict[str, Any]] = []
    for d in drivers:
        if isinstance(d, dict) and (d.get("text") or "").strip():
            final_drivers.append(d)

    if not final_drivers:
        # Create "good enough" driver bullets from chunks without leaking boilerplate
        for c in seed_chunks[:4]:
            if not isinstance(c, dict):
                continue
            eid = c.get("evidence_id")
            txt = _clean_chunk_text(c.get("text", ""))
            if not txt:
                continue
            final_drivers.append(
                {
                    "text": txt,
                    "evidence_ids": [eid] if eid else [],
                    "evidence_quality": "Medium",
                    "disconfirming_check": "Monitor demand, pricing/mix, and Services growth in subsequent quarters.",
                }
            )

    return {
        "ticker": ticker,
        "financials_summary": financials_summary,
        "drivers": final_drivers,
        "guidance": guidance_extracted,
        "computed_metrics": metrics,
        "evidence_pack_meta": ep.get("provenance", {}),
    }
