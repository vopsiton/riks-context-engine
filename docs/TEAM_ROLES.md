# TEAM_ROLES.md — Rik's Context Engine

**Proje:** Rik's Context Engine — AI Agent Memory & Context Management
**GitHub:** `riks-context-engine`
**Team Lead:** Rik (chief agent)
**Report to:** Vahit

---

## Team Structure

```
Vahit (Human / Product Owner)
  │
  └── Rik (Chief Agent / Team Lead)
        │
        ├── opsiton-lead (Ops Team — infra, deployment, CI/CD)
        │     └── opsiton dev team
        │
        └── ai-lead (AI Team — ML, memory systems, context)
              └── ai engineering team
```

---

## Rollere Göre Dağılım

| Rol | Agent | Sorumluluk Alanı |
|-----|-------|-------------------|
| **Chief Agent / Team Lead** | Rik | Proje koordinasyonu, karar alma, Vahit'e raporlama, PR review |
| **Backend / API Dev** | opsiton-lead → opsiton dev | FastAPI server, endpoints, DB integration |
| **Memory Systems** | ai-lead | EpisodicMemory, SemanticMemory, ProceduralMemory, TierManager |
| **Context Management** | ai-lead | ContextWindowManager, pruning, coherence |
| **Knowledge Graph** | ai-lead | KnowledgeGraph, entity/relationship management |
| **Self-Reflection** | ai-lead | ReflectionAnalyzer, lesson tracking |
| **Task Decomposition** | ai-lead | TaskDecomposer |
| **Tool Calling** | ai-lead | ToolCalling abstraction, MCP integration |
| **Export/Import** | ai-lead | Memory export/import (JSON/YAML) |
| **CI/CD Pipeline** | opsiton-lead | GitHub Actions, Docker, pre-commit |
| **Security** | opsiton-lead + ai-lead | SQL injection, CORS, rate limiting |
| **Testing** | Tüm agentlar | Unit tests, integration tests, UAT |
| **Documentation** | Rik + relevant agent | API docs, architecture, user guides |

---

## Açıkta Roller (Gap Analysis)

### ⚠️ Boş Roller — Atanması Gerek

| Rol | Açıklama | Öncelik |
|-----|----------|---------|
| **Performance / Benchmarking** | Recall O(n) optimization (#60), token estimation, memory profiling | P2 |
| **Security Reviewer** | SQL injection (#48), CORS (#49), input validation audit | P0 |
| **UAT Coordinator** | UAT sheet'leri yönetimi, test sonuçları toplama, report to Rik | P1 |
| **MCP Integration Owner** | MCP server implementation (#21-M1), cross-agent protocol | P1 |

### ✅ Atanmış Rollere Göre Eksiklikler

| Rol | Şu Ankimde | Gereken |
|-----|-----------|---------|
| **Reflection Persistence** | Belirsiz (issue #58) | ai-lead veya opsiton-lead |
| **Rate Limiting** | Belirsiz (issue #56) | opsiton-lead |
| **Test Coverage Lead** | Belirsiz (issue #55) | opsiton-lead |
| **Async Context Manager** | Belirsiz (issue #54) | ai-lead |

---

## Agent Detayları

### Rik — Chief Agent / Team Lead

- **Type:** Personal AI assistant (Vahit's right hand)
- **Model:** minimax/MiniMax-M2.7
- **Emoji:** 🗿
- **Responsibilities:**
  - Sprint planning ve backlog management
  - PR review ve merge authorization (UAT pass zorunlu!)
  - Ekip koordinasyonu (opsiton-lead, ai-lead spawn etme)
  - Vahit'e progress raporları
  - Karar alma (architecture, priority, trade-offs)
- **Location:** `~/.openclaw/workspace/SOUL.md`

---

### opsiton-lead — Ops / Infrastructure Lead

- **Purpose:** opsiton şirketi ekip lideri — sprint koordinasyonu, operasyonel işler
- **Spawned by:** Rik
- **Responsibilities:**
  - CI/CD pipeline management
  - Docker & deployment configs
  - Security fixes (SQL injection #48, CORS #49)
  - Rate limiting implementation (#56)
  - Test coverage improvement (#55)
  - Infrastructure documentation
- **Key Issues:**
  - #48 (SQL Injection) — P0, critical
  - #49 (CORS PATCH/HEAD) — P1
  - #55 (Test Coverage) — P2
  - #56 (Rate Limiting) — P2

---

### ai-lead — AI / Engineering Lead

- **Purpose:** AI model eğitim ekibi lideri — RLHF, MLOps, context engineering
- **Spawned by:** Rik
- **Responsibilities:**
  - Memory systems (Episodic, Semantic, Procedural)
  - Context window management
  - Knowledge Graph
  - Self-reflection and task decomposition
  - Tool calling abstraction & MCP
  - Memory export/import
  - Async improvements
- **Key Issues:**
  - #51 (Thread-safe SQLite) — P0
  - #52 (KnowledgeGraph silent fallback) — P1
  - #53 (Memory import schema validation) — P1
  - #54 (ContextWindowManager async) — P2
  - #58 (ReflectionAnalyzer persistence) — P2
  - #60 (SemanticMemory recall O(n)) — P2

---

## Issue Assignment Matrix

| Issue | Priority | Owner | Status | Notes |
|-------|----------|-------|--------|-------|
| #48 SQL Injection | P0 | opsiton-lead | TODO | Security fix |
| #51 Thread-safe SQLite | P0 | ai-lead | TODO | DB concurrency |
| #49 CORS PATCH/HEAD | P1 | opsiton-lead | TODO | FastAPI fix |
| #50 Token Estimation | P1 | ai-lead | TODO | Context window |
| #52 KG Silent Fallback | P1 | ai-lead | TODO | Graceful degradation |
| #53 Memory Import Schema | P1 | ai-lead | TODO | Validation |
| #54 CWM Async | P2 | ai-lead | TODO | Async support |
| #55 Test Coverage | P2 | opsiton-lead | TODO | 85%+ target |
| #56 Rate Limiting | P2 | opsiton-lead | TODO | API middleware |
| #58 Reflection Persistence | P2 | ai-lead | TODO | Lesson storage |
| #60 Semantic Recall O(n) | P2 | ai-lead | TODO | Performance |

---

## Rol Açıklamaları — Detaylı

### Chief Agent (Rik)
```
Sorumluluklar:
- Sprint planlama ve öncelik belirleme
- UAT pass kontrolü (merge authorization)
- Alt agent'ları spawn etme (opsiton-lead, ai-lead)
- Vahit'e haftalık progress raporu
- Architecture kararları

Kendini spawn etmez:
- Direct alt-agent spawn → ilgili lead çağrılır
- opsiton işleri → opsiton-lead
- AI işleri → ai-lead

Karar Alma:
- Basit → tek başına
- Karmaşık → ai-lead + opsiton-lead consulta
```

### Ops Lead (opsiton-lead)
```
Sorumluluklar:
- GitHub Actions CI/CD pipeline
- Docker configuration
- Security fixes
- Performance benchmarking
- Rate limiting

Sorumlu Olduğu Issue'lar:
- #48 (P0), #49 (P1), #55 (P2), #56 (P2)

Çalışma Şekli:
- Rik spawn eder
- Kendi ekibini yönetir
- Rik'e raporlar
```

### AI Lead (ai-lead)
```
Sorumluluklar:
- Memory systems design
- Context management
- Knowledge Graph
- Tool calling / MCP
- Semantic search
- Reflection systems

Sorumlu Olduğu Issue'lar:
- #51 (P0), #52 (P1), #53 (P1), #54 (P2), #58 (P2), #60 (P2)

Çalışma Şekli:
- Rik spawn eder
- AI/ML kararlarını alır
- Rik'e raporlar
```

---

## Boş Rol: UAT Coordinator

**Şu An:** Atanmamış — Rik üstüne almalı veya ai-lead/opsiton-lead'e delege edilmeli

**Sorumluluklar:**
- Her feature için UAT sheet hazırlanması
- Test sonuçlarının toplanması
- Rik'e consolidated report sunulması
- Fail durumlarının track edilmesi

**Öneri:** Rik, UATCoordinator rolünü üstüne alır ve her sub-agent'tan direct report ister.

---

## Boş Rol: MCP Integration Owner

**Şu An:** Atanmamış — issue #21-M1 için gerekli

**Sorumluluklar:**
- MCP server implementation
- Cross-agent protocol design
- Tool schema standardization

**Öneri:** ai-lead bu işi üstüne alır (tool calling ile related)

---

## Notes

- Rik direkt olarak kod yazmaz — lead'leri koordine eder
- Her lead kendi alanındaki kararları alır, Rik'e raporlar
- UAT pass olmadan PR merge YASAK — bu kural Rik tarafından uygulanır
- Sprint goal belirleme: Rik, Vahit ile birlikte karar verir

---

**Last Updated:** 2026-04-19
**Next Review:** Sprint sonu