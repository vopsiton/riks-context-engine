# Sprint Backlog — 2026-04-20

## Prioritized Issues

| # | Title | Priority | Size | Owner |
|---|-------|----------|------|-------|
| 50 | P1: ContextWindowManager token estimation ignores model-specific encoding | P1 | M | — |
| 59 | P3: OllamaEmbedder client never reused — new connection per request | P3 | S | — |
| 57 | P3: TaskDecomposer lacks LLM integration — only pattern matching available | P3 | M | — |
| 64 | fix: RateLimitMiddleware should inherit BaseHTTPMiddleware | P3 | XS | — |
| 63 | chore: remove :memory: test artifact from git tracking | P3 | XS | — |
| 34 | feat: MCP Server Integration — Expose context engine as MCP server | P2 | L | — |
| 35 | feat: Tool Calling Abstraction Layer — Cross-model tool schemas | P2 | L | — |
| 36 | feat: JSON/YAML Memory Export — Cross-model memory portability | P2 | M | — |
| 39 | 🔍 Project Review: riks-context-engine — Technical Debt & Gap Analysis | P2 | M | — |
| 19 | Documentation: User Guide, API Reference, Developer Guide, Architecture Overview | P2 | L | — |
| 16 | Test Environment: Deployed environment testing for testers | P3 | M | — |
| 21 | 📊 2026 Feature Backlog: AI Context/Memory Trends Analysis | P3 | L | — |
| 22 | 📊 2026 AI Agent Infrastructure Trend Raporu — Geniş Araştırma | P3 | L | — |

## This Sprint (Max 5)

1. **#50** — P1 — `ContextWindowManager token estimation ignores model-specific encoding`
   - Token hesaplaması model-specific encoding'i dikkate almıyor. Farklı modelar için tik_token vs sentencepiece vs cl100k_base ayrımı yapılmalı.
   - **Size: M** — Mevcut token counter'ı refactor + encoding aware abstraction eklemek gerekiyor.

2. **#64** — P3 — `RateLimitMiddleware should inherit BaseHTTPMiddleware`
   - Küçük inheritance fix. Starlette'in BaseHTTPMiddleware'ini miras almak isterlerse yapılacak.
   - **Size: XS** — Tek class değişikliği.

3. **#63** — P3 — `remove :memory: test artifact from git tracking`
   - Gitignore'a eklemek + cleanup. 5 dakikalık iş.
   - **Size: XS** — .gitignore düzenlemesi.

4. **#59** — P3 — `OllamaEmbedder client never reused — new connection per request`
   - Ollama client her istekte yeniden oluşturuluyor, connection pool lazım.
   - **Size: S** — Client singleton veya connection reuse pattern eklemek.

5. **#57** — P3 — `TaskDecomposer lacks LLM integration — only pattern matching available`
   - TaskDecomposer sadece pattern matching yapıyor, gerçek LLM entegrasyonu eksik.
   - **Size: M** — LLM client soyutlaması + decompose prompt'u eklemek.

## Icebox (Next Sprint)

- **#34** — feat: MCP Server Integration (L)
- **#35** — feat: Tool Calling Abstraction Layer (L)
- **#36** — feat: JSON/YAML Memory Export (M)
- **#39** — 🔍 Project Review: Technical Debt & Gap Analysis (M)
- **#19** — Documentation: User Guide, API Reference, Architecture (L)
- **#16** — Test Environment: Deployed environment testing (M)
- **#21** — 📊 2026 Feature Backlog: AI Context/Memory Trends Analysis (L)
- **#22** — 📊 2026 AI Agent Infrastructure Trend Raporu (L)

---

> **Toplam issue:** 13 açık issue. Bu sprint 5 tanesi hedeflendi. Geri kalanlar icebox'a alındı.
> **Öncelik notu:** P1 (#50) kesinlikle bu sprint'te yapılmalı — token estimation hataları diğer her şeyi etkiler.
