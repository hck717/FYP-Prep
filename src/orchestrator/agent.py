import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.graphrag.retrieve import RetrieveConfig
from src.skills.fundamentals_skill import fundamentals_skill
from src.skills.valuation_skill import valuation_skill
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool


# --- Data Structures ---

@dataclass
class PlanSection:
    title: str
    skill: str  # "fundamentals" or "valuation"
    focus: Optional[str] = None


@dataclass
class OrchestratorResult:
    ticker: str
    er_note: str  # Markdown content
    structured_data: Dict[str, Any]  # The JSON data from skills
    evidence_check: Dict[str, Any]  # Verifier output


# --- 1. Planner (Mock/Lite) ---

def planner_lite(ticker: str) -> List[PlanSection]:
    """
    Returns a fixed plan for the POC.
    In a full agent, this would use an LLM to decide sections based on user query.
    """
    return [
        PlanSection(title="Business & Fundamentals", skill="fundamentals", focus="growth drivers"),
        PlanSection(title="Valuation Analysis", skill="valuation"),
    ]


# --- 2. Executor ---

def executor(
    ticker: str,
    plan: List[PlanSection],
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the plan by calling the respective skills.
    Returns a consolidated dictionary of skill outputs.
    """
    results: Dict[str, Any] = {}

    for step in plan:
        print(f"Executing step: {step.title} using {step.skill}")

        if step.skill == "fundamentals":
            out = fundamentals_skill(
                ticker,
                sql_tool,
                graphrag_cfg,
                focus=step.focus or "general",
                api_key=api_key,
            )
            results["fundamentals"] = out

        elif step.skill == "valuation":
            # Pass the already-computed fundamentals data into valuation
            # so it can access TTM metrics and extracted guidance
            fund_data = results.get("fundamentals")
            out = valuation_skill(ticker, sql_tool, graphrag_cfg, fundamentals_data=fund_data)
            results["valuation"] = out

    return results


# --- 3. Verifier ---

def verifier(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if the structured data contains evidence IDs.
    Returns a pass/fail report.
    """
    issues: List[str] = []
    evidence_count = 0

    # Check Fundamentals
    fund = data.get("fundamentals", {})
    if isinstance(fund, dict):
        sql_ids = fund.get("financials_summary", {}).get("sql_evidence_ids", [])
        if not sql_ids:
            issues.append("Fundamentals: Missing SQL evidence IDs for financials.")
        else:
            evidence_count += len(sql_ids)

        drivers = fund.get("drivers", [])
        for i, d in enumerate(drivers):
            if not isinstance(d, dict) or not d.get("evidence_ids"):
                issues.append(f"Fundamentals: Driver #{i+1} has no evidence IDs.")
            else:
                evidence_count += len(d["evidence_ids"])

    # Check Valuation
    val = data.get("valuation", {})
    if isinstance(val, dict):
        inp_ids = val.get("inputs", {}).get("sql_evidence_ids", [])
        if not inp_ids:
            issues.append("Valuation: Missing SQL evidence IDs for inputs.")
        else:
            evidence_count += len(inp_ids)

        assumps = val.get("assumptions", [])
        for i, a in enumerate(assumps):
            if not isinstance(a, dict) or not a.get("evidence_ids"):
                issues.append(f"Valuation: Assumption '{a.get('name') if isinstance(a, dict) else ''}' has no evidence IDs.")
            else:
                evidence_count += len(a["evidence_ids"])

    passed = len(issues) == 0
    return {"passed": passed, "issues": issues, "evidence_count": evidence_count}


# --- Markdown helpers ---

def _fmt_num(x: Any, decimals: int = 2) -> str:
    if x is None:
        return "-"
    try:
        v = float(x)
    except Exception:
        return str(x)

    if abs(v) >= 1_000_000_000:
        return f"{v/1_000_000_000:,.{decimals}f}B"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:,.{decimals}f}M"
    if abs(v) >= 1_000:
        return f"{v:,.{decimals}f}"
    return f"{v:.{decimals}f}"


def _fmt_pct(x: Any, decimals: int = 1) -> str:
    if x is None:
        return "-"
    try:
        return f"{100*float(x):.{decimals}f}%"
    except Exception:
        return "-"


def _build_evidence_index(data: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (text_evidence_id -> label), (sql_evidence_id -> label)."""
    text_ids: List[str] = []
    sql_ids: List[str] = []

    fund = data.get("fundamentals", {})
    if isinstance(fund, dict):
        sql_ids += list(fund.get("financials_summary", {}).get("sql_evidence_ids", []) or [])
        for d in fund.get("drivers", []) or []:
            if isinstance(d, dict):
                text_ids += list(d.get("evidence_ids", []) or [])

    val = data.get("valuation", {})
    if isinstance(val, dict):
        sql_ids += list(val.get("inputs", {}).get("sql_evidence_ids", []) or [])
        for a in val.get("assumptions", []) or []:
            if isinstance(a, dict):
                text_ids += list(a.get("evidence_ids", []) or [])

    # Unique preserve order
    text_ids = list(dict.fromkeys([t for t in text_ids if isinstance(t, str) and t]))
    sql_ids = list(dict.fromkeys([s for s in sql_ids if isinstance(s, str) and s]))

    text_map = {eid: f"E{i}" for i, eid in enumerate(text_ids, start=1)}
    sql_map = {sid: f"S{i}" for i, sid in enumerate(sql_ids, start=1)}
    return text_map, sql_map


def _recommendation_from_valuation(last_close: Any, base_value: Any, threshold: float = 0.15) -> Tuple[str, Optional[float]]:
    """Return (rating, upside). rating in {Bullish, Hold, Bearish}."""
    try:
        if last_close is None or base_value is None:
            return "Hold", None
        px = float(last_close)
        iv = float(base_value)
        if px <= 0:
            return "Hold", None
        upside = (iv / px) - 1.0
        if upside >= threshold:
            return "Bullish", upside
        if upside <= -threshold:
            return "Bearish", upside
        return "Hold", upside
    except Exception:
        return "Hold", None


def _extract_source_name(eid: str) -> str:
    """Attempt to parse a readable source name from the evidence ID."""
    # Pattern: seed:doc_id:chunk_idx:hash -> doc_id
    # Pattern: sql:hash:timestamp -> Internal DB (timestamp)
    
    # Handle brackets or quotes around ID if they exist (common with some extractors)
    clean_eid = eid.strip("[]'\"")
    
    if clean_eid.startswith("seed:") or clean_eid.startswith("exp:"):
        parts = clean_eid.split(":")
        if len(parts) >= 2:
            # Extract doc_id (e.g., aapl_q3_2025_transcript_excerpt)
            raw_doc = parts[1]
            # Make it cleaner: replace underscores, title case
            clean_doc = raw_doc.replace("_", " ").title()
            # If we have a chunk index, append it
            if len(parts) >= 3 and parts[2].isdigit():
                return f"{clean_doc} (Chunk {parts[2]})"
            return clean_doc
    elif clean_eid.startswith("sql:"):
        return "Internal Financial DB"
    
    return "Unknown Source"

def _extract_link(eid: str) -> Optional[str]:
    """If the ID implies a linkable source (e.g. EDGAR), return URL. (Mock for now)."""
    # In a real app, this would look up the doc_id in a metadata table to find the source URL
    return None

# --- 4. Orchestrator Main ---

def generate_markdown(ticker: str, data: Dict[str, Any]) -> str:
    """Compose a more professional Markdown ER note with clearer citations."""

    fund = data.get("fundamentals", {})
    val = data.get("valuation", {})
    if not isinstance(fund, dict):
        fund = {}
    if not isinstance(val, dict):
        val = {}

    text_map, sql_map = _build_evidence_index(data)

    # Pull key valuation fields for decision layer
    inputs = val.get("inputs", {}) if isinstance(val.get("inputs", {}), dict) else {}
    v_range = val.get("valuation_range", {}) if isinstance(val.get("valuation_range", {}), dict) else {}

    last_close = inputs.get("last_close")
    base_iv = v_range.get("base")
    rating, upside = _recommendation_from_valuation(last_close, base_iv)

    md = ""
    md += f"# Equity Research Note — {ticker}\n\n"

    # --- Executive Summary ---
    md += "## Executive Summary\n"
    md += f"- **Rating**: {rating}\n"
    if last_close is not None:
        md += f"- Last close: {_fmt_num(last_close, 2)}\n"
    if base_iv is not None and upside is not None:
        md += f"- Implied value (base DCF): {_fmt_num(base_iv, 2)} (implied upside: {_fmt_pct(upside)})\n"
    md += "- Note: Valuation now uses a 2-Stage DCF model based on TTM Free Cash Flow.\n\n"

    # --- Fundamentals ---
    md += "## Business & Fundamentals\n\n"

    summary = fund.get("financials_summary", {})
    periods = summary.get("periods", []) if isinstance(summary.get("periods", []), list) else []
    panel = summary.get("panel", {}) if isinstance(summary.get("panel", {}), dict) else {}

    if periods:
        md += "### Financial Snapshot (Quarterly)\n"
        # Fix column headers to be dates only
        md += "| Metric | " + " | ".join(periods[:4]) + " |\n"
        md += "|---| " + " | ".join(["---"] * len(periods[:4])) + " |\n"

        items = ["Total Revenue", "Net Income", "Diluted EPS", "Free Cash Flow"]
        for item in items:
            row_vals: List[str] = []
            for p in periods[:4]:
                val_num = panel.get(p, {}).get(item, None) if isinstance(panel.get(p, {}), dict) else None
                # EPS should not be abbreviated to B/M
                if item in ("Diluted EPS", "Basic EPS"):
                    row_vals.append(_fmt_num(val_num, 2))
                else:
                    row_vals.append(_fmt_num(val_num, 2))
            md += f"| {item} | " + " | ".join(row_vals) + " |\n"

        raw_sql_ids = summary.get("sql_evidence_ids", []) if isinstance(summary.get("sql_evidence_ids", []), list) else []
        if raw_sql_ids:
            labels = [sql_map.get(s, s) for s in raw_sql_ids]
            # Link to anchor in Appendix
            linked_labels = [f"[{lbl}](#sql-{lbl.lower()})" for lbl in labels]
            md += f"\n*Data source: Internal DB [{', '.join(linked_labels)}]*\n\n"
    
    # --- Advanced Fundamentals Metrics (New Section) ---
    metrics = fund.get("computed_metrics", {}) if isinstance(fund.get("computed_metrics"), dict) else {}
    margins = metrics.get("margins", {})
    growth = metrics.get("growth", {})
    
    md += "### Key Performance Metrics (TTM/YoY)\n"
    md += f"- **Net Margin (TTM)**: {_fmt_pct(margins.get('net_margin'))}\n"
    md += f"- **FCF Margin (TTM)**: {_fmt_pct(margins.get('fcf_margin'))}\n"
    md += f"- **Revenue Growth (YoY)**: {_fmt_pct(growth.get('revenue_yoy'))}\n"
    md += f"- **EPS Growth (YoY)**: {_fmt_pct(growth.get('eps_yoy'))}\n\n"

    md += "### Key Growth Drivers\n"
    drivers = fund.get("drivers", []) if isinstance(fund.get("drivers", []), list) else []

    if drivers:
        md += "| # | Driver | Evidence | Quality | Disconfirming check |\n"
        md += "|---:|---|---|---|---|\n"
        for i, d in enumerate(drivers, start=1):
            if not isinstance(d, dict):
                continue
            txt = (d.get("text", "") or "").strip()
            ev_ids = d.get("evidence_ids", []) or []
            # Link to anchor in Appendix
            ev_labels = [f"[{text_map.get(e, e)}](#text-{text_map.get(e,e).lower()})" for e in ev_ids if isinstance(e, str)]
            quality = d.get("evidence_quality", "-") or "-"
            disconfirm = (d.get("disconfirming_check", "-") or "-").strip()
            md += f"| {i} | {txt} | {', '.join(ev_labels) if ev_labels else '-'} | {quality} | {disconfirm} |\n"
        md += "\n"
    else:
        md += "- No drivers generated.\n\n"

    # --- Valuation ---
    md += "## Valuation\n\n"

    md += "### Inputs (DCF Model)\n"
    inp_sql_ids = inputs.get("sql_evidence_ids", []) if isinstance(inputs.get("sql_evidence_ids", []), list) else []
    inp_sql_labels = [f"[{sql_map.get(s, s)}](#sql-{sql_map.get(s,s).lower()})" for s in inp_sql_ids]
    
    md += f"- Last close: {_fmt_num(last_close, 2)}\n"
    md += f"- Shares Outstanding (Proxy): {_fmt_num(inputs.get('shares_outstanding_proxy'), 2)}\n"
    md += f"- TTM Free Cash Flow: {_fmt_num(inputs.get('fcf_ttm'), 2)}\n"
    if inp_sql_labels:
        md += f"- Evidence: {', '.join(inp_sql_labels)}\n"
    md += "\n"

    md += "### Implied Valuation (DCF Range)\n"
    md += "| Scenario | Implied value | Upside vs. last close |\n"
    md += "|---|---:|---:|\n"

    def _up(v: Any) -> Any:
        try:
            if v is None or last_close is None:
                return None
            return (float(v) / float(last_close)) - 1.0
        except Exception:
            return None

    low_v, base_v, high_v = v_range.get("low"), v_range.get("base"), v_range.get("high")
    md += f"| Bear | {_fmt_num(low_v, 2)} | {_fmt_pct(_up(low_v))} |\n"
    md += f"| Base | {_fmt_num(base_v, 2)} | {_fmt_pct(_up(base_v))} |\n"
    md += f"| Bull | {_fmt_num(high_v, 2)} | {_fmt_pct(_up(high_v))} |\n\n"
    
    # Sensitivity Matrix
    sens_matrix = val.get("sensitivity_matrix", [])
    if sens_matrix:
        md += "### DCF Sensitivity (WACC vs Growth)\n"
        # Get dynamic headers (growth rates)
        if len(sens_matrix) > 0:
            keys = [k for k in sens_matrix[0].keys() if k != "wacc"]
            headers = [f"g={k.split('_')[1]}" for k in keys]
            md += f"| WACC | {' | '.join(headers)} |\n"
            md += f"|---|{'---|' * len(headers)}\n"
            for row in sens_matrix:
                wacc_val = row.get("wacc")
                vals = [f"{_fmt_num(row.get(k), 2)}" for k in keys]
                md += f"| {wacc_val:.1%} | {' | '.join(vals)} |\n"
        md += "\n"

    assumps = val.get("assumptions", []) if isinstance(val.get("assumptions", []), list) else []
    if assumps:
        md += "### Key Assumptions\n"
        md += "| Assumption | Value | Evidence |\n"
        md += "|---|---|---|\n"
        for a in assumps:
            if not isinstance(a, dict):
                continue
            name = a.get("name", "-")
            value = a.get("value")
            ev_ids = a.get("evidence_ids", []) or []
            ev_labels = [f"[{text_map.get(e, e)}](#text-{text_map.get(e,e).lower()})" for e in ev_ids if isinstance(e, str)]
            md += f"| {name} | {value} | {', '.join(ev_labels) if ev_labels else '-'} |\n"
        md += "\n"

    notes = val.get("notes") if isinstance(val, dict) else None
    if notes:
        md += f"*Valuation note: {notes}*\n\n"

    # --- Final decision layer (agent-like synthesis) ---
    md += "## Decision\n"
    md += f"**{rating}** based on the model base-case implied upside (threshold ±15% for Buy/Sell) and the current evidence-backed drivers.\n\n"

    # Give a short rationale that is actually grounded in existing outputs
    md += "### Rationale (evidence-led)\n"
    if drivers:
        # pick top 2 drivers (already ranked by model ordering)
        top = [d for d in drivers if isinstance(d, dict) and (d.get("text") or "").strip()][:2]
        for d in top:
            ev_ids = d.get("evidence_ids", []) or []
            ev_labels = [f"[{text_map.get(e, e)}](#text-{text_map.get(e,e).lower()})" for e in ev_ids if isinstance(e, str)]
            md += f"- {d.get('text','').strip()} ({', '.join(ev_labels) if ev_labels else 'Uncited'})\n"
    else:
        md += "- Fundamentals drivers not available; defaulting to neutral stance.\n"

    md += "\n### Key risks / what to monitor\n"
    if drivers:
        # include up to 2 disconfirming checks
        checks = []
        for d in drivers:
            if isinstance(d, dict) and d.get("disconfirming_check"):
                checks.append(d.get("disconfirming_check"))
            if len(checks) >= 2:
                break
        if checks:
            for c in checks:
                md += f"- {str(c).strip()}\n"
        else:
            md += "- Monitor demand, pricing/mix, and Services growth; disconfirming checks not provided in this run.\n"
    else:
        md += "- Monitor demand, pricing/mix, and margin trajectory.\n"

    # --- Evidence appendix ---
    md += "\n## Evidence Appendix\n"
    md += "### Text Evidence\n"
    if text_map:
        for eid, lbl in text_map.items():
            source_name = _extract_source_name(eid)
            # Create an anchor for each item
            md += f"- <a id='text-{lbl.lower()}'></a>**{lbl}**: {source_name} (`{eid}`)\n"
    else:
        md += "- (None)\n"

    md += "\n### SQL Evidence\n"
    if sql_map:
        for sid, lbl in sql_map.items():
            source_name = _extract_source_name(sid)
            md += f"- <a id='sql-{lbl.lower()}'></a>**{lbl}**: {source_name} (`{sid}`)\n"
    else:
        md += "- (None)\n"

    return md


def run_orchestrator(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    api_key: Optional[str] = None,
) -> OrchestratorResult:

    plan = planner_lite(ticker)
    data = executor(ticker, plan, sql_tool, graphrag_cfg, api_key=api_key)
    verification = verifier(data)

    md = generate_markdown(ticker, data)

    if not verification["passed"]:
        md += "\n\n---\n**⚠️ Verification Warning**: Some claims are missing evidence IDs. See logs."

    return OrchestratorResult(ticker=ticker, er_note=md, structured_data=data, evidence_check=verification)
