
# FYP-Prep: Agentic Equity Research with MCP & GraphRAG

This project implements an Agentic RAG system for Equity Research (ER). It uses **Model Context Protocol (MCP)** to securely access internal financial data (SQLite) and **GraphRAG** (Neo4j + Qdrant) to retrieve structural text evidence. A central **Orchestrator** plans, executes, and verifies the research note generation.

## Prerequisites

- Python 3.12+
- Docker (for Neo4j)
- `uv` (for running MCP servers)

---

## 1. Environment Setup

### Install `uv` (for MCP)
```bash
brew install uv
uvx --version
```

### Create Python Virtual Environment
```bash
cd ~/fyp-prep/FYP-Prep
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-mcp.txt
python -m pip install -r requirements-graphrag.txt
```

---

## 2. Data Plane: MCP SQLite (Financials)

This layer provides read-only access to structured financial data (`research.db`).

### Verify Database
Ensure your SQLite database exists and has tables:
```bash
ls -lh research.db
sqlite3 research.db ".tables"
# Expected: events, fundamentals, prices_daily, ratios_ttm, ...
```

### Start MCP Server
Start the official SQLite MCP server using `uvx`. Keep this terminal window **open** in the background, or ensure your client scripts spawn it automatically (the provided tools use `stdio_client` which spawns `uvx` internally, so explicit server startup is mainly for testing connectivity).

```bash
# Manual test to see if it starts (Type Ctrl+C to exit)
uvx mcp-server-sqlite --db-path research.db
```

### Test Internal MCP Client Wrapper
Run the strict wrapper that enforces read-only access and limits.
```bash
source .venv/bin/activate
python -m src.scripts.test_sql_tool_wrapper
```

---

## 3. Data Plane: GraphRAG (Text Evidence)

This layer provides graph-based retrieval of text chunks from Qdrant (vectors) and Neo4j (relationships).

### Start Neo4j (Docker)
Starts a local Neo4j instance for the Knowledge Graph.
- **URL**: http://localhost:7474
- **Auth**: neo4j / password

```bash
docker run -d --name neo4j-graphrag \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

### Build GraphRAG Index
Ingests data into Qdrant and Neo4j.
```bash
source .venv/bin/activate
python src/graphrag/build_graphrag_index.py
```

### Test Retrieval
Run a sample query to verify `EvidencePack` generation (Seed Chunks + Graph Paths).
```bash
source .venv/bin/activate
python src/graphrag/retrieve.py --query "Apple services growth drivers"
```

---

## 4. Control Plane: Agentic Skills

### Test Skills (Fundamentals & Valuation)
Run the isolated skills to ensure they produce valid JSON with evidence IDs.
```bash
source .venv/bin/activate
python -m src.scripts.step4_run_skills_poc
```

---

## 5. Application Layer: 1-Click Demo

### Run Streamlit App
Launch the full agentic workflow UI.
```bash
source .venv/bin/activate
streamlit run streamlit_app_v2.py
```
Access the app at `http://localhost:8501`.

---

## Project Structure
- `src/tools/`: MCP Client wrappers (`sql_tool_mcp.py`)
- `src/graphrag/`: Retrieval logic (`retrieve.py`)
- `src/skills/`: Domain logic (`fundamentals.py`, `valuation.py`)
- `src/orchestrator/`: Agent logic (`agent.py`)
- `streamlit_app_v2.py`: Main UI entry point
