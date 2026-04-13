# Rik's Context Engine 🗿

**Status:** Just started | **Owner:** @vopsiton (for @riks-ai)

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

## Sprint Roadmap

### Sprint 1 - Foundation
- [Issue #6] Project Bootstrap (README, CI, structure)
- [Issue #1] Memory Hierarchy (3-tier architecture)
- [Issue #2] Context Window Manager (intelligent pruning)

### Sprint 2 - Core Intelligence
- [Issue #3] Task Decomposition (goal → steps)
- [Issue #4] Self-Reflection (learn from mistakes)

### Sprint 3 - Advanced
- [Issue #5] Knowledge Graph (entities & relationships)

## Stack

- **Language:** Python (fast iteration, rich ML ecosystem)
- **Vector DB:** Qdrant (for semantic search) or in-process with Chroma
- **LLM Integration:** Ollama (local) + OpenAI/Anthropic (cloud)
- **Storage:** SQLite (semantic), JSON files (episodic)

## Why 2026?

Context engineering is the next frontier. While everyone chases AGI, we build memory.

## License

AGPL - share the source if you build on it.
