# Agent Skills for FYP-Prep

This directory contains **Agent Skills** that enable AI agents (Claude, your custom orchestrators, etc.) to perform specialized equity research tasks.

## What are Agent Skills?

Agent Skills are self-contained folders that package:
1. **SKILL.md**: Metadata (name, description) + instructions in Markdown
2. **Executable scripts**: Python scripts that perform the actual work
3. **Resources**: Any additional files needed (templates, configs, etc.)

The Agent Skills format is based on [Anthropic's Agent Skills specification](https://www.anthropic.com/blog/skills).

## Available Skills

### 1. Fundamentals Analysis
**Location:** `skills/fundamentals/`

**Purpose:** Analyzes a company's fundamental performance, growth drivers, and risks using verified financial data (SQL) and text evidence (GraphRAG).

**Usage:**
```bash
python skills/fundamentals/run_analysis.py --ticker AAPL --focus "services revenue" --horizon "1 year"
```

**When to use:** Stock research, business model analysis, quarterly performance reviews.

---

### 2. Valuation Analysis
**Location:** `skills/valuation/`

**Purpose:** Constructs valuation models and price targets using DCF, multiples, and scenario analysis.

**Usage:**
```bash
python skills/valuation/run_valuation.py --ticker AAPL --horizon "1 year"
```

**When to use:** Fair value estimation, target price calculations, investment decision support.

---

## How Agent Skills Work

### Discovery
AI agents scan the `skills/` directory for folders containing `SKILL.md` files. The YAML frontmatter tells the agent:
- **name**: Unique identifier
- **description**: When to use this skill
- **allowed-tools**: What tools the skill needs (e.g., `execute_python`)

### Execution
When the agent determines a skill is relevant:
1. It reads the instructions from `SKILL.md`
2. It executes the command specified (e.g., `python skills/fundamentals/run_analysis.py ...`)
3. It parses the JSON output and incorporates it into its reasoning

### Composability
Multiple skills can be used together. For example:
- Use **Fundamentals** to understand the business
- Use **Valuation** to determine fair value
- Combine insights to make an investment recommendation

---

## Requirements

All skills require:
- Python 3.12+
- Access to `research.db` (SQLite database in project root)
- Neo4j GraphRAG instance (default: `bolt://localhost:7687`)

### Environment Variables
```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
```

---

## Testing Skills Manually

You can test any skill directly from the command line:

```bash
# From the project root (FYP-Prep/)
cd ~/fyp-prep/FYP-Prep
source .venv/bin/activate

# Test Fundamentals
python skills/fundamentals/run_analysis.py --ticker AAPL

# Test Valuation
python skills/valuation/run_valuation.py --ticker MSFT --horizon "18 months"
```

---

## Integration with Your Orchestrator

Your existing `src/orchestrator/agent.py` can be updated to discover and use these skills dynamically:

```python
import subprocess
import json

def run_skill(skill_name: str, **kwargs) -> dict:
    """Execute an Agent Skill and return its JSON output."""
    cmd = ["python", f"skills/{skill_name}/run_analysis.py"]
    for key, val in kwargs.items():
        cmd.extend([f"--{key}", str(val)])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)

# Usage in orchestrator
fundamentals_data = run_skill("fundamentals", ticker="AAPL", focus="services")
valuation_data = run_skill("valuation", ticker="AAPL")
```

---

## Adding New Skills

To create a new skill:

1. Create a new directory: `skills/my-new-skill/`
2. Add `SKILL.md` with frontmatter and instructions
3. Add executable script (e.g., `run_my_skill.py`)
4. Test manually
5. Commit to repository

For guidance, use the `skill-creator` skill from Anthropic:
```bash
# In Claude apps, just say: "Create a new skill for [task description]"
```

---

## References

- [Anthropic Agent Skills Blog Post](https://www.anthropic.com/blog/skills)
- [Anthropic Skills GitHub Repository](https://github.com/anthropics/skills)
- [Neo4j GraphRAG & Agentic Architecture](https://neo4j.com/blog/developer/graphrag-and-agentic-architecture-with-neoconverse/)
- [Claude Platform Docs - Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
