import os
import json 


from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig
from src.skills.fundamentals_skill import fundamentals_skill
from src.skills.valuation_skill import valuation_skill


def main():
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

    f = fundamentals_skill("AAPL", sql_tool, cfg, focus="services")
    v = valuation_skill("AAPL", sql_tool, cfg)

    print("=== Fundamentals skill ===")
    print(json.dumps(f, indent=2))

    print("\n=== Valuation skill ===")
    print(json.dumps(v, indent=2))


if __name__ == "__main__":
    main()
