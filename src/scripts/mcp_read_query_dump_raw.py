import asyncio
import json
from pprint import pprint

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server = StdioServerParameters(
        command="uvx",
        args=["mcp-server-sqlite", "--db-path", "research.db"],
        env=None,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            sql = """
            SELECT date, close, volume, ingested_at
            FROM prices_daily
            WHERE ticker='AAPL'
            ORDER BY date DESC
            LIMIT 5
            """.strip()

            raw = await session.call_tool("read_query", {"query": sql})

            print("\n=== RAW TYPE ===")
            print(type(raw))

            print("\n=== RAW (pprint) ===")
            pprint(raw)

            # Try common serializations for inspection
            print("\n=== RAW as dict (best-effort) ===")
            try:
                d = raw.model_dump()  # pydantic-style objects often support this
                pprint(d)
            except Exception as e:
                print("model_dump() not available:", repr(e))

            print("\n=== RAW JSON (best-effort) ===")
            try:
                print(json.dumps(d, indent=2, ensure_ascii=False))
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
