import asyncio
import ast
import json
from pathlib import Path
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


DB_PATH = "research.db"
OUT_MD = Path("artifacts/schema_context.md")
OUT_JSON = Path("artifacts/schema_context.json")


def _parse_mcp_text_payload(result) -> Any:
    """
    Your server returns content like:
      content=[TextContent(... text="[...]")]
    We parse that text into Python objects.
    """
    if result.isError:
        raise RuntimeError(f"MCP tool error: {result.content}")

    if not result.content:
        return None

    text = result.content[0].text
    # The sqlite MCP server returns Python-literal-like lists/dicts in text.
    # ast.literal_eval is safer than eval.
    return ast.literal_eval(text)


def format_schema_md(schema: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    schema = {table_name: [ {cid,name,type,notnull,dflt_value,pk}, ... ]}
    """
    lines = []
    lines.append("# SQLite schema context\n")
    lines.append("Use only these tables/columns. Prefer explicit column names.\n")

    for table, cols in schema.items():
        lines.append(f"## {table}\n")
        for c in cols:
            nn = "NOT NULL" if c.get("notnull") else ""
            pk = "PK" if c.get("pk") else ""
            meta = " ".join(x for x in [c.get("type", ""), nn, pk] if x).strip()
            lines.append(f"- {c['name']}: {meta}".rstrip())
        lines.append("")  # blank line

    return "\n".join(lines).strip() + "\n"


async def main() -> None:
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    server = StdioServerParameters(
        command="uvx",
        args=["mcp-server-sqlite", "--db-path", DB_PATH],
        env=None,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()  # MCP client init pattern [web:191]

            # 1) list_tables
            tables_res = await session.call_tool("list_tables", {})
            tables_payload = _parse_mcp_text_payload(tables_res)
            # tables_payload looks like: [{'name': 'dim_company'}, ...]
            table_names = [t["name"] for t in tables_payload]

            # 2) describe_table for each
            schema: Dict[str, List[Dict[str, Any]]] = {}
            for name in table_names:
                desc_res = await session.call_tool("describe_table", {"table_name": name})
                schema[name] = _parse_mcp_text_payload(desc_res)

    # 3) write outputs
    OUT_JSON.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    OUT_MD.write_text(format_schema_md(schema), encoding="utf-8")

    print(f"Wrote: {OUT_MD}")
    print(f"Wrote: {OUT_JSON}")


if __name__ == "__main__":
    asyncio.run(main())
