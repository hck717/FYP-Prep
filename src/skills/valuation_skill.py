# src/skills/valuation_skill.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import pandas as pd

from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve

def _calculate_dcf(
    fcf_ttm: float,
    shares: float,
    growth_rate: float,
    wacc: float,
    terminal_growth: float,
    years: int = 5
) -> Dict[str, Any]:
    """
    Perform a simple 2-stage DCF.
    """
    if shares <= 0 or wacc <= terminal_growth:
        return {}

    # 1. Project FCF
    projected_fcf = []
    current_fcf = fcf_ttm
    for i in range(1, years + 1):
        # Decay growth linearly to terminal rate? No, keep simple flat growth for Stage 1
        current_fcf *= (1 + growth_rate)
        projected_fcf.append(current_fcf)

    # 2. Terminal Value
    last_fcf = projected_fcf[-1]
    tv = last_fcf * (1 + terminal_growth) / (wacc - terminal_growth)

    # 3. Discount to Present
    pv_fcf = 0.0
    for i, fcf in enumerate(projected_fcf, start=1):
        pv_fcf += fcf / ((1 + wacc) ** i)
    
    pv_tv = tv / ((1 + wacc) ** years)
    
    enterprise_value = pv_fcf + pv_tv
    # (Simplified: assume Net Debt = 0 or implicit in EV/Equity bridge for this POC)
    equity_value = enterprise_value 
    
    implied_price = equity_value / shares

    return {
        "implied_price": implied_price,
        "enterprise_value": enterprise_value,
        "pv_fcf": pv_fcf,
        "pv_tv": pv_tv,
        "projection_years": years
    }

def valuation_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    fundamentals_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    
    # --- 1. Gather Inputs ---
    # Try to get TTM metrics from the passed fundamentals data first
    fcf_ttm = 0.0
    ni_ttm = 0.0
    eps_ttm = 0.0
    
    if fundamentals_data:
        metrics = fundamentals_data.get("computed_metrics", {})
        ttm = metrics.get("ttm", {})
        fcf_ttm = ttm.get("fcf", 0.0)
        ni_ttm = ttm.get("net_income", 0.0)
        eps_ttm = ttm.get("eps", 0.0)
    
    # If missing (e.g. standalone run), fetch via SQL fallback
    # (Skipping robust fallback code for brevity in this step, assuming linked run)
    
    # Get latest price for "Upside" calc
    px = sql_tool.read_query(f"SELECT close FROM prices_daily WHERE ticker='{ticker}' ORDER BY date DESC LIMIT 1")
    last_close = px.rows[0][0] if px.rows else 1.0

    # Calculate Shares Outstanding Proxy
    # Shares = Net Income / EPS
    shares_proxy = (ni_ttm / eps_ttm) if eps_ttm != 0 else 0
    if shares_proxy == 0 and last_close > 0:
        # Fallback: if we can't calc shares, we can't do per-share DCF easily.
        # But let's assume a dummy count or fail gracefully.
        shares_proxy = 1_000_000_000 # 1B placeholder if data broken

    # --- 2. Determine Assumptions ---
    # Growth Rate: Look at extracted guidance or historical growth
    base_growth = 0.05 # Default 5%
    
    if fundamentals_data:
        guidance = fundamentals_data.get("guidance", [])
        # Simple heuristic: if any guidance mentions "revenue" and "double digit", bump growth
        # Real impl would parse numbers.
        for g in guidance:
            val = str(g.get("value_text", "")).lower()
            if "double" in val:
                base_growth = 0.10
            elif "high single" in val:
                base_growth = 0.08
    
    wacc = 0.09 # 9%
    terminal_g = 0.03 # 3%

    # --- 3. Run Models ---
    
    # Model A: DCF
    dcf_base = _calculate_dcf(fcf_ttm, shares_proxy, base_growth, wacc, terminal_g)
    dcf_bear = _calculate_dcf(fcf_ttm, shares_proxy, base_growth * 0.5, wacc + 0.01, terminal_g - 0.01)
    dcf_bull = _calculate_dcf(fcf_ttm, shares_proxy, base_growth * 1.5, wacc - 0.01, terminal_g + 0.01)

    # Model B: Relative (P/E)
    # Use historical P/E or standard 25x
    pe_base = 25.0
    pe_val = eps_ttm * pe_base

    # Sensitivity Table (Price vs WACC & Growth)
    sensitivity = []
    wacc_range = [0.08, 0.09, 0.10]
    g_range = [base_growth - 0.02, base_growth, base_growth + 0.02]
    
    for w in wacc_range:
        row = {"wacc": w}
        for g in g_range:
            res = _calculate_dcf(fcf_ttm, shares_proxy, g, w, terminal_g)
            row[f"g_{int(g*100)}%"] = res.get("implied_price", 0.0)
        sensitivity.append(row)

    return {
        "ticker": ticker,
        "inputs": {
            "last_close": last_close,
            "fcf_ttm": fcf_ttm,
            "shares_outstanding_proxy": shares_proxy,
            "eps_ttm": eps_ttm,
            "sql_evidence_ids": fundamentals_data.get("financials_summary", {}).get("sql_evidence_ids", []) if fundamentals_data else []
        },
        "assumptions": [
            {"name": "WACC", "value": f"{wacc:.1%}", "evidence_ids": []},
            {"name": "Terminal Growth", "value": f"{terminal_g:.1%}", "evidence_ids": []},
            {"name": "Base Growth (Stage 1)", "value": f"{base_growth:.1%}", "evidence_ids": []}
        ],
        "valuation_range": {
            "low": dcf_bear.get("implied_price", 0),
            "base": dcf_base.get("implied_price", 0),
            "high": dcf_bull.get("implied_price", 0)
        },
        "dcf_details": dcf_base,
        "sensitivity_matrix": sensitivity,
        "notes": f"DCF based on TTM FCF of ${fcf_ttm/1e9:.2f}B and projected growth."
    }
