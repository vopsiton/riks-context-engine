# Sprint Backlog - Rik's Context Engine

## Sprint Goal
Build the core cognitive engine for an AI agent that learns from interactions.

## Completed Issues ✅

| # | Issue | PR | Status |
|---|-------|-----|--------|
| #1 | Memory Hierarchy (3-tier: Episodic, Semantic, Procedural) | #10 | Merged |
| #2 | Context Window Manager (intelligent pruning) | #11 | Merged |
| #3 | Task Decomposition (goal → steps) | #14 | Merged |
| #4 | Self-Reflection (learn from mistakes) | #14 | Merged |
| #6 | Project Bootstrap (README, CI, structure) | #7 | Merged |

### Sprint 2 Fixes (inline)

| # | Fix | Notes |
|---|-----|-------|
| F1 | SemanticMemory.query/recall stubs → implemented with SQLite persistence | 88+ tests |
| F2 | EpisodicMemory.query/prune stubs → implemented with JSON persistence | 88+ tests |
| F3 | ProceduralMemory.recall/find stubs → implemented with JSON persistence | 88+ tests |
| F4 | TierManager API mismatches (missing .get/.delete methods) → fixed | 88+ tests |
| F5 | datetime.utcnow() deprecation → datetime.now(timezone.utc) | All tests pass |

## Remaining Issues 🎯

### Sprint 3 - MCP & Tool Calling

> **Source**: Issue #22 — 2026 AI Agent Infrastructure Trend Report (MoSCoW Prioritization)

#### MUST HAVE (P1) — Sprint 3

| # | Feature | Priority | Rationale | Complexity |
|---|---------|----------|-----------|------------|
| #21-M1 | **MCP Server Integration** — Expose riks-context-engine as an MCP server so AI agents can connect and query memory via the Model Context Protocol standard. | P1 | MCP is the emerging standard for agent-to-tool communication; without it, riks-context-engine becomes a siloed brick. | High |
| #21-M2 | **Tool Calling Abstraction Layer** — Define cross-model tool schemas (JSON/YAML) so the context engine works uniformly across OpenAI, Anthropic, Gemini, Ollama, and local models. | P1 | Tool calling is the dominant agent interaction pattern; abstraction enables true cross-model portability. | Medium |
| #21-M3 | **JSON/YAML Memory Export** — Export episodic, semantic, and procedural memory in portable formats for backup, transfer, or ingestion by other agents. | P1 | Cross-model memory portability is a 2026 MUST HAVE for agent interoperability and backup. | Low |

#### SHOULD HAVE (P2)

| # | Feature | Priority | Rationale | Complexity |
|---|---------|----------|-----------|------------|
| #21-S1 | **A2A Protocol Support** — Implement the Agent-to-Agent protocol so riks-context-engine can communicate with other agentic services natively. | P2 | A2A is positioned to become the inter-agent communication standard alongside MCP. | Medium |
| #21-S2 | **Background Memory Subagent** — Spawn a lightweight subagent that asynchronously indexes, consolidates, and prunes memory in the background without blocking the main context pipeline. | P2 | Background processing decouples memory maintenance from latency-sensitive inference calls. | Medium |
| #21-S3 | **Qdrant Vector DB Integration** — Add Qdrant as an optional vector store backend for semantic memory, replacing/augmenting the JSON persistence layer. | P2 | Qdrant provides production-grade vector search with filtering and distributed deployment options. | High |

#### COULD HAVE (P3)

| # | Feature | Priority | Rationale | Complexity |
|---|---------|----------|-----------|------------|
| #21-C1 | **Memory Block Abstraction** — Define a `MemoryBlock` interface so different memory types (episodes, facts, procedures, KB entities) can be treated uniformly by consumers. | P3 | Provides a clean extension point for future memory types and third-party plugins. | Low |
| #21-C2 | **Agent Serialization (.af format)** — Define an `.af` (Agent Format) spec for serializing agent state (memory + config + tool bindings) to a single file for snapshotting, transfer, or cloning. | P3 | Enables agent immortality scenarios — pause, migrate, resume on a different runtime. | Medium |
| #21-C3 | **Edge Deployment Config** — Package riks-context-engine with Ollama + local MCP server for fully offline, privacy-preserving edge deployment. | P3 | Completes the offline story for privacy-sensitive or air-gapped environments. | Medium |

### Sprint 3 - Knowledge Graph (P2)

| # | Issue | Priority | Notes |
|---|-------|----------|-------|
| #5 | Knowledge Graph: Entities and relationships | P2 | Next focus area after MCP/Tool Calling |

## Definition of Done

- [x] Code implemented
- [x] Tests pass
- [x] Security review clean (deprecation fixes applied)
- [x] Documentation updated

## Metrics

- **Total Issues**: 6 + 9 backlog items
- **Completed**: 5 (83% of core)
- **Remaining**: 1 core + 9 backlog items
- **Test Coverage**: 90 tests passing
- **Fixes Applied**: 5 (Sprint 2 cleanup)

## Notes

- Context Window Manager already handles intelligent pruning
- Self-Reflection and Task Decomposition shipped together in PR #14
- Sprint 2 cleanup: all stub methods implemented, deprecations fixed
- Next focus: MCP Server Integration + Tool Calling Abstraction (Sprint 3 MUST HAVE)
- Backlog items sourced from Issue #22 — 2026 AI Agent Infrastructure Trend Report
