# src/orchestrator/step0_smoke_test.py
from __future__ import annotations

from src.contracts.types import FundamentalsInputs, ValuationInputs
from src.graphrag.retrieve import RetrieveConfig
from src.tools.graphrag_tool import GraphRagTool
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.skills.fundamentals import fundamentals_skill
from src.skills.valuation import valuation_skill


def main() -> None:
    sql_tool = McpSqliteReadOnlyTool(db_path="research.db")

    cfg = RetrieveConfig(
        qdrant_path="artifacts/qdrant_local",
        collection="filings_chunks",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        embed_model="sentence-transformers/all-MiniLM-L6-v2",
        top_k=5,
        hop_k=2,
        mapping_path="artifacts/chunkid_to_pointid.json",
        out_json_path="artifacts/graphrag_result.json",
    )
    graphrag_tool = GraphRagTool(cfg=cfg)

    f = fundamentals_skill(FundamentalsInputs(ticker="AAPL", horizon="8q", focus="services"), sql_tool, graphrag_tool)
    v = valuation_skill(ValuationInputs(ticker="AAPL", horizon="12m"), sql_tool, graphrag_tool)

    print("FundamentalsJSON:", f)
    print("ValuationJSON:", v)


if __name__ == "__main__":
    main()
