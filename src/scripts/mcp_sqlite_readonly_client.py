import asyncio
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


MAX_LIMIT = 200
ALLOWED_TABLES = {"prices_daily", "fundamentals", "snapshot_kv", "dim_company"}

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|pragma)\b",
    re.IGNORECASE,
)


def guard_sql(sql: str) -> str:
    s = sql.strip().rstrip(";")
    low = s.lower()

    if ";" in s:
        raise ValueError("Multi-statement SQL is not allowed.")
    
    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")

    if FORBIDDEN.search(low):
        raise ValueError("Forbidden keyword detected (write/admin SQL).")

    # POC allowlist check (simple + effective)
    if not any(tbl in low for tbl in ALLOWED_TABLES):
        raise ValueError(f"Query must reference allowed tables: {sorted(ALLOWED_TABLES)}")
    
    if ("prices_daily" in low or "fundamentals" in low) and "ticker=" not in low:
        raise ValueError("Queries on large tables must filter by ticker=...")
    
    # enforce LIMIT
    if re.search(r"\blimit\b", low) is None:
        s = f"{s} LIMIT {MAX_LIMIT}"
    else:
        m = re.search(r"\blimit\s+(\d+)\b", low)
        if m and int(m.group(1)) > MAX_LIMIT:
            s = re.sub(r"\blimit\s+\d+\b", f"LIMIT {MAX_LIMIT}", s, flags=re.IGNORECASE)

    return s


async def main() -> None:
    # Spawn the official SQLite MCP server via uvx (stdio)
    server = StdioServerParameters(
        command="uvx",
        args=["mcp-server-sqlite", "--db-path", "research.db"],
        env=None,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()  # required in MCP client flow [web:191]

            # Discover tools (matches MCP client tutorial pattern)
            tool_list = await session.list_tools()
            print("TOOLS:", [t.name for t in tool_list.tools])

            # 1) list tables
            tables = await session.call_tool("list_tables", {})
            print("TABLES:", tables)

            # 2) describe_table (optional but recommended for schema grounding)
            schema = await session.call_tool("describe_table", {"table_name": "prices_daily"})
            print("SCHEMA prices_daily:", schema)

            # 3) read_query checkpoint with timestamps
            q1 = guard_sql("""
                SELECT date, close, volume, ingested_at
                FROM prices_daily
                WHERE ticker='AAPL'
                ORDER BY date DESC
                LIMIT 5
            """)
            r1 = await session.call_tool("read_query", {"query": q1})
            print("RESULT q1:", r1)

            # 4) fundamentals checkpoint (income statement items)
            q2 = guard_sql("""
                SELECT period_type, statement_type, period_end, line_item, value, ingested_at
                FROM fundamentals
                WHERE ticker='AAPL'
                  AND period_type='quarterly'
                  AND statement_type='is'
                  AND line_item IN ('Total Revenue', 'Net Income')
                ORDER BY period_end DESC
                LIMIT 12
            """)
            r2 = await session.call_tool("read_query", {"query": q2})
            print("RESULT q2:", r2)


if __name__ == "__main__":
    asyncio.run(main())
