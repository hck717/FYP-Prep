import json
import traceback
import streamlit as st
from src.graphrag.retrieve import RetrieveConfig
from src.orchestrator.agent import run_orchestrator
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool

st.set_page_config(page_title="FYP-Prep: Agentic ER Note", layout="wide")

st.title("FYP-Prep: Agentic Equity Research")
st.markdown("""
**POC Demo**: Generates a 1-click Equity Research note using:
1. **MCP SQLite** (Internal Fundamentals)
2. **GraphRAG** (Internal Text Evidence)
3. **Agentic Orchestrator** (Planning & Verification)
""")

# --- Sidebar ---
with st.sidebar:
    st.header("Configuration")
    ticker = st.text_input("Ticker", value="AAPL")
    
    st.subheader("GraphRAG Config")
    qdrant_path = st.text_input("Qdrant Path", "artifacts/qdrant_local")
    neo4j_uri = st.text_input("Neo4j URI", "bolt://localhost:7687")
    
    st.subheader("MCP Config")
    db_path = st.text_input("DB Path", "research.db")

    st.subheader("LLM Config")
    pplx_api_key = st.text_input("Perplexity API Key", type="password", help="Optional. Required for synthesis/reasoning.")

    if st.button("Reset Session"):
        st.session_state.result = None
        st.rerun()

# --- Main Logic ---

if "result" not in st.session_state:
    st.session_state.result = None

def run_analysis():
    # 1. Setup Tools
    sql_tool = McpSqliteReadOnlyTool(db_path=db_path)
    
    # Mock config for demo purposes - in real run, ensure services are up
    graph_cfg = RetrieveConfig(
        qdrant_path=qdrant_path,
        collection="filings_chunks",
        neo4j_uri=neo4j_uri,
        neo4j_user="neo4j",
        neo4j_password="password",
        embed_model="sentence-transformers/all-MiniLM-L6-v2",
        top_k=5,
        hop_k=2,
        mapping_path="artifacts/chunkid_to_pointid.json",
        out_json_path="artifacts/graphrag_result.json",
    )
    
    with st.spinner(f"Running Agentic Workflow for {ticker}..."):
        # 2. Run Orchestrator
        try:
            res = run_orchestrator(ticker, sql_tool, graph_cfg, api_key=pplx_api_key)
            st.session_state.result = res
            st.success("Analysis Complete!")
        except Exception as e:
            st.error(f"Error running analysis: {e}")
            with st.expander("Detailed Traceback", expanded=True):
                st.code(traceback.format_exc())

# --- UI Layout ---

if st.button("Generate ER Note", type="primary"):
    run_analysis()

res = st.session_state.result

if res:
    # Two columns: Report vs Evidence
    col1, col2 = st.columns([1.2, 1])
    
    with col1:
        st.subheader("📝 Generated ER Note")
        st.markdown(res.er_note)
        
        st.divider()
        st.caption("Verification Report:")
        if res.evidence_check["passed"]:
            st.success(f"✅ PASSED ({res.evidence_check['evidence_count']} citations)")
        else:
            st.error("❌ FAILED")
            for issue in res.evidence_check["issues"]:
                st.write(f"- {issue}")

    with col2:
        st.subheader("🔍 Evidence & Logs")
        
        with st.expander("Structured Data (JSON)", expanded=True):
            st.json(res.structured_data)
        
        with st.expander("Orchestrator Logs"):
            st.write("Plan executed:")
            st.code("""
[
  {"step": "Business & Fundamentals", "skill": "fundamentals"},
  {"step": "Valuation Analysis", "skill": "valuation"}
]
            """, language="json")
