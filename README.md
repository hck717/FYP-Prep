# FYP-Prep: Agentic Equity Research with MCP & GraphRAG

This project implements an **Agentic RAG system** for Equity Research (ER). It mimics the workflow of a professional analyst by orchestrating specialized "skills" to gather evidence, perform reasoning, and generate verified investment insights.

It leverages **Model Context Protocol (MCP)** for secure access to structured financial data (SQLite) and **GraphRAG** (Neo4j + Qdrant) for retrieving connected textual evidence.

---

## 🧠 System Architecture

The system is designed as a modular **Agentic Orchestrator** that manages two specialized skills, powered by distinct data pipelines.

### 1. The Orchestrator (The "Analyst Brain")
- **Role**: Project Manager & Editor.
- **Responsibility**: 
  - Receives the user request (e.g., "Analyze AAPL").
  - **Plans** the report structure (e.g., "Step 1: Fundamentals", "Step 2: Valuation").
  - **Delegates** tasks to specific Skills.
  - **Verifies** quality (checks that every claim cites valid Evidence IDs).
  - **Synthesizes** final output using **Perplexity API** with a "Senior Analyst" persona.

### 2. The Skills (The "Specialists")
The Orchestrator calls these Python modules to perform domain-specific work:
- **Skill A: Fundamentals**: 
  - *Task:* Analyze growth drivers, revenue mix, and risks.
  - *Logic:* Triangulates quantitative trends (SQL) with qualitative context (Text).
  - *Advanced:* Uses "Chain-of-Thought" prompting to perform sanity checks (e.g., "Do numbers match the narrative?").
- **Skill B: Valuation**:
  - *Task:* Construct valuation ranges (Base/Bear/Bull).
  - *Logic:* Pulls latest price/EPS data and applies multiple valuation methods (PE, DCF proxy).

### 3. The Data Plane (The "Fact Checkers")
We strictly separate **Structured** vs. **Unstructured** data to eliminate hallucinations.

| Component | Technology | Role | Example Query |
| :--- | :--- | :--- | :--- |
| **Structured Data** | **MCP + SQLite** | The source of truth for **Numbers**. Read-only access ensures data integrity. | "Get AAPL 2024 Q3 Revenue" |
| **Unstructured Data** | **GraphRAG** (Neo4j + Qdrant) | The source of truth for **Narrative**. Combines **Vector Search** (semantic meaning) with **Graph Search** (relationships). | "Find 'Service Revenue' and its connected 'Risk Factors'" |

---

## 🚀 Key Technologies Explained

### What is "Agentic RAG"?
Standard RAG just "retrieves and summarizes." **Agentic RAG** adds a reasoning layer:
1. **Planning**: It doesn't just answer; it creates a multi-step plan.
2. **Tool Use**: It actively selects which tool (SQL vs. Vector DB) to use for which sub-problem.
3. **Verification**: It critiques its own output ("Did I cite my sources?") before showing it to you.

### What is "GraphRAG"?
Traditional RAG retrieves text based on keyword similarity. **GraphRAG** enhances this by understanding connections:
- *Vector*: Finds paragraphs talking about "Chips."
- *Graph*: Knows that "Chips" are connected to "TSMC" (Supplier) and "Taiwan" (Geopolitical Risk).
- *Benefit*: It retrieves **context**, not just keywords, leading to deeper insights.

### What is "MCP"?
The **Model Context Protocol (MCP)** is an open standard that allows AI agents to connect to data sources safely.
- Instead of hard-coding SQL credentials into the AI, we run a secure **MCP Server**.
- The AI uses a standardized API to ask for data, and the Server ensures it only sees what it's allowed to see (Read-Only).

---

## Prerequisites

- Python 3.12+
- Docker (for Neo4j)
- `uv` (for running MCP servers)
- **Perplexity API Key** (for the reasoning/generation layer)

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

### Refine "Senior Analyst" Behavior
To improve the quality of insights, you can save good outputs as "exemplars." The system will use these to fine-tune its future responses via few-shot prompting.
```bash
# Example: Save your best output to a file, then run:
python -m src.scripts.add_fundamentals_exemplar --focus "services" --ticker "AAPL" --drivers-file artifacts/good_drivers.json
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
- `src/llm/`: Perplexity client & Exemplar management
- `streamlit_app_v2.py`: Main UI entry point

---

## Acknowledgements

This architecture is inspired by Neo4j's developer guide on **GraphRAG and Agentic Architecture**.  
Reference: [GraphRAG and Agentic Architecture with NeoConverse](https://neo4j.com/blog/developer/graphrag-and-agentic-architecture-with-neoconverse/)
