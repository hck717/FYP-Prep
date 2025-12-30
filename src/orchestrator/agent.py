
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    graphrag_cfg: RetrieveConfig
) -> Dict[str, Any]:
    """
    Executes the plan by calling the respective skills.
    Returns a consolidated dictionary of skill outputs.
    """
    results = {}

    for step in plan:
        print(f"Executing step: {step.title} using {step.skill}")
        
        if step.skill == "fundamentals":
            out = fundamentals_skill(ticker, sql_tool, graphrag_cfg, focus=step.focus or "general")
            results["fundamentals"] = out
        
        elif step.skill == "valuation":
            out = valuation_skill(ticker, sql_tool, graphrag_cfg)
            results["valuation"] = out

    return results


# --- 3. Verifier ---

def verifier(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if the structured data contains evidence IDs.
    Returns a pass/fail report.
    """
    issues = []
    evidence_count = 0

    # Check Fundamentals
    fund = data.get("fundamentals", {})
    if fund:
        # Check SQL evidence
        sql_ids = fund.get("financials_summary", {}).get("sql_evidence_ids", [])
        if not sql_ids:
            issues.append("Fundamentals: Missing SQL evidence IDs for financials.")
        else:
            evidence_count += len(sql_ids)

        # Check Text evidence
        drivers = fund.get("drivers", [])
        for i, d in enumerate(drivers):
            if not d.get("evidence_ids"):
                issues.append(f"Fundamentals: Driver #{i+1} has no evidence IDs.")
            else:
                evidence_count += len(d["evidence_ids"])

    # Check Valuation
    val = data.get("valuation", {})
    if val:
        # Check inputs evidence
        inp_ids = val.get("inputs", {}).get("sql_evidence_ids", [])
        if not inp_ids:
            issues.append("Valuation: Missing SQL evidence IDs for inputs.")
        else:
            evidence_count += len(inp_ids)

        # Check assumptions evidence
        assumps = val.get("assumptions", [])
        for i, a in enumerate(assumps):
            if not a.get("evidence_ids"):
                issues.append(f"Valuation: Assumption '{a.get('name')}' has no evidence IDs.")
            else:
                evidence_count += len(a["evidence_ids"])

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "evidence_count": evidence_count
    }


# --- 4. Orchestrator Main ---

def generate_markdown(ticker: str, data: Dict[str, Any]) -> str:
    """
    Composes the final Markdown report from the structured data.
    """
    fund = data.get("fundamentals", {})
    val = data.get("valuation", {})
    
    md = f"# Equity Research Note: {ticker}\n\n"
    
    # Fundamentals Section
    md += "## 1. Business & Fundamentals\n\n"
    
    # Financial Table
    summary = fund.get("financials_summary", {})
    periods = summary.get("periods", [])
    panel = summary.get("panel", {})
    
    if periods:
        md += "### Financial Snapshot (Quarterly)\n"
        # Header
        md += "| Line Item | " + " | ".join(periods[:4]) + " |\n"
        md += "|---| " + " | ".join(["---"] * len(periods[:4])) + " |\n"
        
        # Rows
        items = ["Total Revenue", "Net Income", "Diluted EPS"]
        for item in items:
            row_vals = []
            for p in periods[:4]:
                val = panel.get(p, {}).get(item, "-")
                row_vals.append(str(val))
            md += f"| {item} | " + " | ".join(row_vals) + " |\n"
        
        sql_ids = summary.get("sql_evidence_ids", [])
        if sql_ids:
            md += f"\n*Source: Internal DB (IDs: {', '.join(sql_ids)})*\n\n"

    # Drivers
    md += "### Key Growth Drivers\n"
    for d in fund.get("drivers", []):
        txt = d.get("text", "").strip()
        ev_ids = d.get("evidence_ids", [])
        cite = f" [Ids: {', '.join(ev_ids)}]" if ev_ids else " [Uncited]"
        md += f"- {txt}{cite}\n"
    md += "\n"

    # Valuation Section
    md += "## 2. Valuation Analysis\n\n"
    v_range = val.get("valuation_range", {})
    inputs = val.get("inputs", {})
    
    md += f"- **Last Close**: {inputs.get('last_close')}\n"
    md += f"- **EPS Proxy (Annualized)**: {inputs.get('eps_ttm_proxy')}\n"
    
    if v_range.get("base"):
        md += f"\n**Implied Valuation Range**:\n"
        md += f"- Low: {v_range.get('low')}\n"
        md += f"- Base: {v_range.get('base')}\n"
        md += f"- High: {v_range.get('high')}\n"
    
    assumps = val.get("assumptions", [])
    if assumps:
        md += "\n**Key Assumptions**:\n"
        for a in assumps:
            name = a.get("name")
            vals = a.get("value")
            ev_ids = a.get("evidence_ids", [])
            cite = f" [Ids: {', '.join(ev_ids)}]" if ev_ids else ""
            md += f"- {name}: {vals}{cite}\n"

    return md


def run_orchestrator(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig
) -> OrchestratorResult:
    
    # 1. Plan
    plan = planner_lite(ticker)
    
    # 2. Execute
    data = executor(ticker, plan, sql_tool, graphrag_cfg)
    
    # 3. Verify
    verification = verifier(data)
    
    # 4. Compose
    md = generate_markdown(ticker, data)
    
    if not verification["passed"]:
        md += "\n\n---\n**⚠️ Verification Warning**: Some claims are missing evidence IDs. See logs."

    return OrchestratorResult(
        ticker=ticker,
        er_note=md,
        structured_data=data,
        evidence_check=verification
    )
