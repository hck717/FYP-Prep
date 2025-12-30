# src/skills/fundamentals_skill.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve


def fundamentals_skill(
    ticker: str,
    sql_tool: McpSqliteReadOnlyTool,
    graphrag_cfg: RetrieveConfig,
    focus: str = "services",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    # --- Numbers (MCP) ---
    # Keep it minimal: reuse your Step 1 idea (period list + line items)
    periods_res = sql_tool.read_query(f"""
        SELECT DISTINCT period_end
        FROM fundamentals
        WHERE ticker='{ticker}'
          AND period_type='quarterly'
        ORDER BY period_end DESC
        LIMIT 8
    """)
    periods = [r[0] for r in periods_res.rows]  # one column: period_end

    wanted = ["Total Revenue", "Net Income", "Diluted EPS", "Basic EPS", "Free Cash Flow"]

    items_res = sql_tool.read_query(f"""
        SELECT period_end, line_item, value, ingested_at
        FROM fundamentals
        WHERE ticker='{ticker}'
        AND period_type='quarterly'
        AND line_item IN ('Total Revenue','Net Income','Diluted EPS','Basic EPS','Free Cash Flow')
        ORDER BY period_end DESC
        LIMIT 200
    """)

    # Pivot
    panel: Dict[str, Dict[str, Any]] = {p: {} for p in periods}
    ing: Dict[str, str] = {}
    for pe, li, val, ingested_at in items_res.rows:
        panel.setdefault(pe, {})[li] = val
        ing[pe] = max(ing.get(pe, ""), ingested_at or "")

    financials_summary = {
        "periods": periods,
        "panel": panel,
        "ingested_at_by_period": ing,
        "sql_evidence_ids": [periods_res.sql_evidence_id, items_res.sql_evidence_id],
    }

    # --- Text evidence (GraphRAG) ---
    ep = graphrag_retrieve(f"{ticker} {focus} growth drivers", graphrag_cfg)
    seed_chunks = ep.get("seed_chunks", [])[:5]

    drivers = []
    
    # Try Perplexity Generation if key provided
    if api_key and seed_chunks:
        try:
            from src.llm.perplexity_client import call_perplexity
            
            context_str = "\n\n".join([f"Chunk {i+1} (ID: {c['evidence_id']}): {c['text']}" for i, c in enumerate(seed_chunks)])
            
            # --- PROFESSIONAL PROMPT ---
            system_msg = {
                "role": "system", 
                "content": (
                    "You are a Senior Equity Research Analyst at a top-tier investment bank. "
                    "Your job is to synthesize raw filing excerpts into professional, concise investment insights. "
                    "Focus on identifying structural growth drivers, margin implications, and strategic shifts. "
                    "Avoid generic summary language; use financial terminology (e.g., 'operating leverage', 'ARR growth', 'cyclical headwinds')."
                )
            }
            
            user_msg = {
                "role": "user",
                "content": f"""
                Based ONLY on the provided text chunks from {ticker}'s filings, identify 3-5 key growth drivers or strategic priorities.
                
                Guidelines:
                - Output ONLY a bulleted list.
                - Each bullet must be self-contained and high-impact.
                - Highlight specific segments, products, or geographies mentioned in the text.
                - If the text mentions risks or headwinds, frame them professionally as 'Key Risks'.
                
                Context:
                {context_str}
                """
            }
            
            resp = call_perplexity(api_key, [system_msg, user_msg])
            
            # Parse lines
            driver_lines = [line.strip().lstrip("- ").lstrip("* ") for line in resp.split("\n") if line.strip()]
            
            # Attribute all used chunks to each driver (Section Citation pattern)
            all_ids = [c["evidence_id"] for c in seed_chunks]
            drivers = [{"text": d, "evidence_ids": all_ids} for d in driver_lines]
            
        except Exception as e:
            print(f"Perplexity API failed: {e}")
            # Fallback will happen below if drivers is empty
            pass

    # Fallback to truncation if no key or failure
    if not drivers:
        drivers = [
            {"text": c.get("text", "")[:220], "evidence_ids": [c["evidence_id"]]}
            for c in seed_chunks
        ]

    related_evidence = [
        {"text": c.get("text", "")[:220], "evidence_ids": [c["evidence_id"]]}
        for c in ep.get("expanded_chunks", [])[:3]
    ]

    return {
        "ticker": ticker,
        "financials_summary": financials_summary,
        "drivers": drivers,
        "related_evidence": related_evidence,
        "evidence_pack_meta": ep.get("provenance", {}),
    }