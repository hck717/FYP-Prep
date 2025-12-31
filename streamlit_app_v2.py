import json
import traceback
import streamlit as st
from src.graphrag.retrieve import RetrieveConfig
from src.orchestrator.agent import run_orchestrator
from src.tools.sql_tool_mcp import McpSqliteReadOnlyTool
from src.llm.perplexity_client import call_perplexity  # Added import

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
        st.session_state.messages = []  # Clear chat history too
        st.rerun()

# --- Main Logic ---

if "result" not in st.session_state:
    st.session_state.result = None

# Helper to get graph config (used by both main report and chat)
def get_graph_config():
    return RetrieveConfig(
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

def run_analysis():
    # 1. Setup Tools
    sql_tool = McpSqliteReadOnlyTool(db_path=db_path)
    graph_cfg = get_graph_config()
    
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

# --- Chat Interface (Appended Below) ---

st.markdown("---")
st.subheader("💬 Chat with Analyst")
st.caption(f"Ask specific questions about **{ticker}**. Examples: 'What is the valuation?', 'Should I buy?', 'How much is it now?'")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat Input Processing
if prompt := st.chat_input(f"Ask a question about {ticker}..."):
    # 1. Display User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Generate Response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # Ensure we have data. If not, run the orchestrator quietly.
        data_source = None
        if st.session_state.result:
            data_source = st.session_state.result.structured_data
        else:
            with st.spinner("Fetching data for first-time analysis..."):
                try:
                    sql_tool = McpSqliteReadOnlyTool(db_path=db_path)
                    graph_cfg = get_graph_config()
                    res = run_orchestrator(ticker, sql_tool, graph_cfg, api_key=pplx_api_key)
                    # We DON'T set st.session_state.result here to avoid popping open the main report 
                    # if the user just wanted to chat. But we use the data.
                    data_source = res.structured_data
                except Exception as e:
                    st.error(f"Failed to fetch data: {e}")
        
        if data_source:
            # Construct a context-aware prompt
            # We extract key fields to keep the prompt focused
            val = data_source.get("valuation", {})
            fund = data_source.get("fundamentals", {})
            
            context_str = json.dumps({
                "valuation_summary": val.get("valuation_range", "N/A"),
                "dcf_inputs": val.get("inputs", "N/A"),
                "fundamentals_metrics": fund.get("computed_metrics", "N/A"),
                "growth_drivers": [d.get("text") for d in fund.get("drivers", [])][:3],
                "risks": [r.get("text") for r in fund.get("risks", [])][:3]
            }, indent=2)

            qa_prompt = f"""
            You are an expert financial analyst. Answer the user's question based ONLY on the provided data context.
            
            Ticker: {ticker}
            User Question: "{prompt}"
            
            Data Context:
            {context_str}
            
            Guidelines:
            - If asked for "Price" or "How much", use 'last_close' from dcf_inputs.
            - If asked for "Valuation", cite the Base Case from valuation_summary.
            - If asked "Buy/Sell/Hold", compare the Base Case value to the Last Close price.
            - Keep answer concise (under 4 sentences).
            """
            
            if pplx_api_key:
                try:
                    full_response = call_perplexity(
                        api_key=pplx_api_key, 
                        messages=[{"role": "user", "content": qa_prompt}],
                        temperature=0.0
                    )
                except Exception as e:
                    full_response = f"⚠️ Error calling LLM: {e}"
            else:
                full_response = "⚠️ Please provide a Perplexity API Key in the sidebar to enable chat responses."
                
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
