# Rik Context Engine — Product Landing Page

---

## Hero Section

# AI That Actually Remembers

**Rik Context Engine** gives your AI agents a persistent, hierarchical memory — so they stop forgetting everything between sessions and start getting smarter over time.

```
pip install riks-context-engine
```

**[View on GitHub](https://github.com/vopsiton/riks-context-engine)** · **[Documentation](docs/API.md)** · **[Blog Post](docs/BLOG-WHY-AI-CONTEXT-MEMORY-MATTERS.md)**

---

## The Problem

### AI Assistants Have Amnesia

Every AI session starts from scratch. Chat today, forget tomorrow. Your AI has no idea:

- 🔴 **Who you are** — preferences, communication style, project context
- 🔴 **What you were working on** — past decisions, errors made, solutions found
- 🔴 **What matters** — important vs. noise in any conversation
- 🔴 **How to do things** — workflows it figured out once but forgot

The industry keeps building bigger context windows. But bigger windows aren't memory — they're just more RAM.

---

## The Solution

### 3-Tier Memory Architecture (Like Human Cognition)

```
┌─────────────────────────────────────────────┐
│          E P I S O D I C                    │
│   Session-level, short-term, high-fidelity  │
│   "What happened in our last session?"       │
└─────────────────────────────────────────────┘
                  ↓ consolidate
┌─────────────────────────────────────────────┐
│          S E M A N T I C                    │
│   Long-term structured knowledge            │
│   "What do I know about your project?"      │
└─────────────────────────────────────────────┘
                  ↓ proceduralize
┌─────────────────────────────────────────────┐
│        P R O C E D U R A L                  │
│   Skills, workflows, how-to knowledge        │
│   "How do you deploy to production?"         │
└─────────────────────────────────────────────┘
```

### + Intelligent Context Window Management

**Importance Scoring** — Automatically scores every message across 4 dimensions:
- User mentions & preferences (35%)
- Decisions & commitments (25%)
- New information & discoveries (25%)
- Tool outputs & results (15%)

**Smart Pruning** — When context fills up, remove low-importance messages *first*. Never lose a decision or a user preference.

**Coherence Validation** — Ensures pruned conversations remain logically intact. No orphaned assistant responses.

---

## Features

### 🧠 Intelligent Memory Hierarchy
Three distinct memory tiers that mirror human cognition. Episodic captures session moments, Semantic stores persistent facts, Procedural captures reusable skills.

### ⚡ Auto-Scoring Context Window
Every message automatically scored for importance. The system knows what's worth keeping and what's noise — without manual prompts.

### 🔗 Knowledge Graph
Entity relationships with semantic vector search. Ask "What does the auth service depend on?" and get a full dependency traversal.

### 📋 Task Decomposition
Natural language goals → dependency-respecting task graphs. Includes cycle detection, parallel execution groups, and success criteria.

### 🔄 Self-Improvement Loop
Post-interaction reflection that learns from mistakes. Before starting a risky task, checks past failures and warns proactively.

### 🛡️ Priority Tiers
TIER_0 (protected) → TIER_3 (low priority). Critical system instructions are never pruned. Low-importance old messages are first to go.

---

## Architecture at a Glance

```
User Prompt
    │
    ▼
ContextWindowManager
  → ImportanceScorer: auto-score every message
  → Prunes when window fills (preserves coherence)
    │
    ├──→ EpisodicMemory  (session JSON store)
    │       │
    │       └──→ TierManager: promote frequently-accessed → Semantic
    │
    ├──→ SemanticMemory  (SQLite + ChromaDB)
    │
    ├──→ ProceduralMemory  (skills/workflows + success rates)
    │
    ├──→ KnowledgeGraph  (entity relationships)
    │
    └──→ ReflectionAnalyzer  (learn from mistakes)
    │
    ▼
LLM Response
```

---

## Storage Backends

| Tier | Storage | Why |
|------|---------|-----|
| Episodic | JSON file | Fast writes, simple, session-scoped |
| Semantic | SQLite + ChromaDB | Relational queries + vector similarity |
| Procedural | JSON file | Human-readable, easy to edit manually |
| Knowledge Graph | SQLite | Graph queries with FK constraints |
| Context Window | In-memory | Transient, not persisted by design |

**No external services required** (except optional Ollama for embeddings).

---

## Quick Start

```bash
pip install riks-context-engine
```

```python
from riks_context_engine import *
from riks_context_engine.memory import EpisodicMemory, SemanticMemory
from riks_context_engine.context import ContextWindowManager

# Store a user preference
mem = EpisodicMemory()
mem.add("Vahit prefers technical discussions in English", importance=0.9)

# Use intelligent context window
ctx = ContextWindowManager(max_tokens=50_000)
ctx.auto_score_and_add("user", "Deploy to production", is_grounding=True)
ctx.auto_score_and_add("assistant", "Running deployment script...")
ctx.auto_score_and_add("tool", "Deployment complete. 0 errors.")

print(ctx.get_summary())
# {'current_tokens': 42, 'usage_percent': 0.08, 'pruning_events': 0, ...}
```

---

## Why Rik Context Engine?

| | Basic Vector Store | Typical Agent Framework | Rik Context Engine |
|--|--|--|--|
| Memory tiers | Flat | 1-2 layers | 3 distinct tiers |
| Auto-importance scoring | ❌ | ❌ | ✅ 4 dimensions |
| Coherence-aware pruning | N/A | ❌ | ✅ |
| Knowledge graph | ❌ | Optional | ✅ Built-in |
| Task decomposition | ❌ | Sometimes | ✅ Dependency graph |
| Self-reflection | ❌ | ❌ | ✅ |
| Local-first (no external DB) | ❌ | ❌ | ✅ |

---

## Built For

- **AI Developers** — Building agents that need real memory
- **DevOps Teams** — Maintaining context across long debugging sessions
- **Researchers** — Tracking findings across multi-session investigations
- **Power Users** — AI assistants that actually learn your preferences

---

## Open Source

**AGPL-3.0 License** — Share the source if you build on it.

Built with 🗿 by [opsiton](https://github.com/vopsiton) for the Rik AI ecosystem.

---

## Get Started

```bash
pip install riks-context-engine
```

📖 **[Documentation](docs/API.md)** · 🐛 **[Report an Issue](https://github.com/vopsiton/riks-context-engine/issues)** · 💬 **[Discussions](https://github.com/vopsiton/riks-context-engine/discussions)**
