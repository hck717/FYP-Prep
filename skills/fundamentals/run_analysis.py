#!/usr/bin/env python3
"""Fundamentals Analysis Skill - Executable wrapper for Agent Skills framework."""
import argparse
import sys
import json
import os

# Ensure we can import from src/ even if running from subfolder
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.contracts.types import FundamentalsInputs
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.tools.graphrag_tool import GraphRagTool
from src.graphrag.retrieve import RetrieveConfig
from src.skills.fundamentals import fundamentals_skill


def main():
    parser = argparse.ArgumentParser(
        description="Run Fundamentals Analysis Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python skills/fundamentals/run_analysis.py --ticker AAPL
  python skills/fundamentals/run_analysis.py --ticker MSFT --focus "cloud revenue" --horizon "2 years"
        """
    )
    parser.add_argument("--ticker", required=True, help="Stock Ticker (e.g. AAPL)")
    parser.add_argument(
        "--focus", 
        default="growth drivers", 
        help="Analysis focus area (e.g., 'services revenue', 'China risks')"
    )
    parser.add_argument(
        "--horizon", 
        default="1 year", 
        help="Investment horizon (e.g., '1 year', 'short term')"
    )
    
    args = parser.parse_args()

    # 1. Instantiate Tools
    # Note: Ensure 'research.db' path is correct relative to execution context
    db_path = os.path.join(os.getcwd(), "research.db")
    if not os.path.exists(db_path):
        print(json.dumps({
            "error": f"Database not found at {db_path}",
            "suggestion": "Run this script from the FYP-Prep project root directory"
        }), file=sys.stderr)
        sys.exit(1)
    
    sql_tool = McpSqliteReadOnlyTool(db_path=db_path)
    
    graph_tool = GraphRagTool(cfg=RetrieveConfig(
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password")
    ))

    # 2. Prepare Inputs
    inputs = FundamentalsInputs(
        ticker=args.ticker.upper(),
        focus=args.focus,
        horizon=args.horizon
    )

    # 3. Run Skill Logic
    try:
        result = fundamentals_skill(inputs, sql_tool, graph_tool)
        
        # 4. Output JSON for the Agent to read
        print(json.dumps(result.__dict__, default=str, indent=2))
    except Exception as e:
        print(json.dumps({
            "error": str(e),
            "ticker": args.ticker,
            "type": type(e).__name__
        }), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
