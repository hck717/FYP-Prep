import asyncio
import re
from collections import defaultdict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


MAX_LIMIT = 200
ALLOWED_TABLES = {"prices_daily", "fundamentals"}
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma)\b", re.IGNORECASE)


def guard_sql(sql: str) -> str:
    s = sql.strip().rstrip(";")
    low = s.lower()

    if ";" in s:
        raise ValueError("Multi-statement SQL is not allowed.")
    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(low):
        raise ValueError("Forbidden keyword detected (write/admin SQL).")
    if not any(tbl in low for tbl in ALLOWED_TABLES):
        raise ValueError(f"Query must reference allowed tables: {sorted(ALLOWED_TABLES)}")
    if ("prices_daily" in low or "fundamentals" in low) and "ticker=" not in low:
        raise ValueError("Queries on large tables must filter by ticker=...")
    if "limit" not in low:
        s = f"{s} LIMIT {MAX_LIMIT}"
    return s


def parse_records_from_calltool(result):
    if result.isError:
        raise RuntimeError(result.content)
    text = result.content[0].text
    import ast
    return ast.literal_eval(text)


async def main():
    ticker = "AAPL"

    server = StdioServerParameters(
        command="uvx",
        args=["mcp-server-sqlite", "--db-path", "research.db"],
        env=None,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) Pull last up-to-8 quarter_end values
            q_periods = guard_sql(f"""
                SELECT DISTINCT period_end, ingested_at
                FROM fundamentals
                WHERE ticker='{ticker}'
                  AND period_type='quarterly'
                ORDER BY period_end DESC
                LIMIT 8
            """)
            periods_res = await session.call_tool("read_query", {"query": q_periods})
            period_rows = parse_records_from_calltool(periods_res)
            periods = [r["period_end"] for r in period_rows]

            if len(periods) < 8:
                print(f"WARNING: only {len(periods)} quarters available in DB for {ticker} (showing all available up to 8).")

            # 2) Pull needed line items for those periods
            wanted_items = ["Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow"]
            items_in = ", ".join([f"'{x}'" for x in wanted_items])
            periods_in = ", ".join([f"'{p}'" for p in periods])

            q_items = guard_sql(f"""
                SELECT period_end, statement_type, line_item, value, ingested_at
                FROM fundamentals
                WHERE ticker='{ticker}'
                  AND period_type='quarterly'
                  AND period_end IN ({periods_in})
                  AND line_item IN ({items_in})
                ORDER BY period_end DESC
                LIMIT 200
            """)
            items_res = await session.call_tool("read_query", {"query": q_items})
            rows = parse_records_from_calltool(items_res)

            # 2b) Coverage debug table
            q_cov = guard_sql(f"""
                SELECT period_end, line_item, COUNT(*) AS n
                FROM fundamentals
                WHERE ticker='{ticker}'
                  AND period_type='quarterly'
                  AND line_item IN ('Total Revenue','Net Income','Diluted EPS','Basic EPS','Free Cash Flow')
                GROUP BY period_end, line_item
                ORDER BY period_end DESC
                LIMIT 200
            """)
            cov_res = await session.call_tool("read_query", {"query": q_cov})
            cov_rows = parse_records_from_calltool(cov_res)

    print("\n=== Coverage (period_end x line_item) ===")
    for r in cov_rows:
        print([r["period_end"], r["line_item"], r["n"]])

    # 3) Pivot FIRST
    panel = defaultdict(dict)
    latest_ingested = {}

    for r in rows:
        pe = r["period_end"]
        li = (r["line_item"] or "").strip()
        panel[pe][li] = r["value"]
        latest_ingested[pe] = max(latest_ingested.get(pe, ""), r.get("ingested_at", "") or "")

    # 3b) Coverage summary AFTER pivot
    required = ["Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow"]

    cov_map = defaultdict(set)
    for r in cov_rows:
        cov_map[r["period_end"]].add((r["line_item"] or "").strip())

    print("\n=== Coverage summary ===")
    for pe in periods:
        have = [k for k in required if k in cov_map.get(pe, set())]
        missing = [k for k in required if k not in cov_map.get(pe, set())]
        print(pe, "have=", have, "missing=", missing)


    # 4) Print checkpoint output
    print("\n=== Step1 Checkpoint: up to last 8 quarters fundamentals panel ===")
    print("ticker:", ticker)
    print("periods:", periods)

    cols = ["period_end", "Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow", "ingested_at"]
    print("columns:", cols)

    for pe in periods:
        out = [
            pe,
            panel.get(pe, {}).get("Total Revenue"),
            panel.get(pe, {}).get("Net Income"),
            panel.get(pe, {}).get("Diluted EPS"),
            panel.get(pe, {}).get("Basic EPS"),
            panel.get(pe, {}).get("Free Cash Flow"),
            latest_ingested.get(pe),
        ]
        print(out)


if __name__ == "__main__":
    asyncio.run(main())
