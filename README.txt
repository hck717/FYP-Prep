README:

## Install MCP: 

cd ~/fyp-prep
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-mcp.txt


## install UVX

brew install uv
uvx --version


# check SQLite DB 
ls -lh research.db
sqlite3 research.db ".tables"

# Run the MCP SQLite Server

uvx mcp-server-sqlite --db-path research.db

# run the clint
cd ~/fyp-prep
source .venv/bin/activate
python src/scripts/mcp_sqlite_readonly_client.py

# run the schema for MCP 
source .venv/bin/activate
python -m src.scripts.test_sql_tool_wrapper









# install packages for GraphRAG -- Neo4j
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements-graphrag.txt

# start Neo4j (Docker) -- http://localhost:7474 (login: neo4j / password)
docker run -d --name neo4j-graphrag \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
 


# run Neo4j and Qdrant
source .venv/bin/activate
python src/graphrag/build_graphrag_index.py

# run graph rag checkpoint query 
source .venv/bin/activate
python src/graphrag/retrieve.py --query "Apple services growth drivers"



# run the 2 skills of the agent 
source .venv/bin/activate
python -m src.scripts.step4_run_skills_poc
