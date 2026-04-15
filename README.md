# Rik's Context Engine 🗿

**Status:** In development | **Owner:** @vopsiton (for @riks-ai)

AI context and memory management framework - because context windows have limits, but problems don't.

## The Problem

AI assistants are stuck in a loop - every session starts fresh, forgets everything, and we're back to explaining basics. The industry focuses on bigger models instead of smarter context management.

## The Vision

Build an AI-native memory system that:
- Never forgets user preferences or project context
- Learns from mistakes and improves over time
- Breaks complex tasks into executable steps
- Maintains coherence even at 1M+ token conversations
- Actually gets better the more you use it

## Architecture

```
riks-context-engine/
├── memory/           # 3-tier: Episodic, Semantic, Procedural
├── context/          # Intelligent window management
├── tasks/           # Goal decomposition & execution
├── reflection/       # Self-improvement loop
├── graph/            # Entity relationships
└── cli/              # Terminal interface
```

## Quick Start

### Local Development (Python)

```bash
# Clone
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine

# Virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .\.venv\Scripts\activate  # Windows

# Install
pip install -e ".[dev]"

# Run CLI
riks --help

# Or import directly
python -c "from riks_context_engine import *; print('OK')"
```

### Docker (Local Sandbox)

```bash
# Build
docker build -t riks-context-engine:dev .

# Run with docker-compose
docker-compose up dev

# Test inside container
docker-compose exec dev python -c "from riks_context_engine import *; print('OK')"
```

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your settings
```

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server endpoint |
| `OLLAMA_MODEL` | `gemma4-31b-q4` | Default LLM model |
| `CHROMA_HOST` | `localhost` | ChromaDB host |
| `DATA_DIR` | `/app/data` | Data storage directory |

## Stack

- **Language:** Python (fast iteration, rich ML ecosystem)
- **Vector DB:** ChromaDB (embedded, no external DB needed)
- **LLM Integration:** Ollama (local) + OpenAI/Anthropic (cloud)
- **Storage:** SQLite (semantic), JSON files (episodic)

## Development

```bash
# Run tests
pytest

# Lint
ruff check src/

# Type check
mypy src/

# Pre-commit hooks
pre-commit run --all-files
```

## Deployment

See [Deployment Guide](./docs/DEPLOYMENT.md) for CI/CD setup and production deployment.

## License

AGPL - share the source if you build on it.