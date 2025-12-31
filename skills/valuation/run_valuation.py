#!/usr/bin/env python3
"""Valuation Analysis Skill - Executable wrapper for Agent Skills framework."""
import argparse
import sys
import json
import os

# Ensure we can import from src/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.contracts.types import ValuationInputs
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.tools.graphrag_tool import GraphRagTool
from src.graphrag.retrieve import RetrieveConfig
from src.skills.valuation import valuation_skill


def main():
    parser = argparse.ArgumentParser(
        description="Run Valuation Analysis Skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python skills/valuation/run_valuation.py --ticker AAPL
  python skills/valuation/run_valuation.py --ticker MSFT --horizon "18 months"
        """
    )
    parser.add_argument("--ticker", required=True, help="Stock Ticker (e.g. AAPL)")
    parser.add_argument(
        "--horizon", 
        default="1 year", 
        help="Investment horizon (e.g., '1 year', '18 months')"
    )
    
    args = parser.parse_args()

    # 1. Instantiate Tools
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

    # 2. Run Skill Logic
    inputs = ValuationInputs(
        ticker=args.ticker.upper(), 
        horizon=args.horizon
    )
    
    try:
        result = valuation_skill(inputs, sql_tool, graph_tool)
        
        # 3. Output JSON
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
