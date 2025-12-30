from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool

sql_tool = McpSqliteReadOnlyTool(db_path="research.db")

res = sql_tool.read_query("""
    SELECT date, close, volume, ingested_at
    FROM prices_daily
    WHERE ticker='AAPL'
    ORDER BY date DESC
    LIMIT 5
""")

print("columns:", res.columns)
print("nrows:", len(res.rows))
print("first_row:", res.rows[0] if res.rows else None)
print("evidence:", res.sql_evidence_id)
print("meta:", res.meta)

