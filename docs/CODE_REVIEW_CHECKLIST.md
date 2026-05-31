# Code Review Checklist

Use this checklist when reviewing any PR in Rik Context Engine.

## 🔴 Blocker (Must Fix Before Merge)

### Logic & Correctness
- [ ] Code does what the description claims
- [ ] Edge cases handled (empty input, null, large data)
- [ ] No obvious infinite loops or recursion
- [ ] Return values and exceptions handled

### Security
- [ ] **Injection attacks** — SQL, command, prompt injection: user input sanitized before DB/shell/LLM calls
- [ ] **Authentication/Authorization** — Endpoints check permissions correctly
- [ ] **Secrets** — No hardcoded credentials, tokens, API keys in code
- [ ] **Rate limiting** — API endpoints protected against abuse
- [ ] **Input validation** — Schema validation on all external input (JSON schemas, tool params)
- [ ] **Memory exports** — Sensitive context is stripped from logs/exports (see `SECURITY.md`)

### Testing
- [ ] Core logic covered by unit tests
- [ ] Tests actually assert behavior (not just "no exception")
- [ ] New features don't break existing tests

## 🟡 Should Fix (Before Merge, Non-Blocking if Justified)

### Code Quality
- [ ] No redundant code or dead paths
- [ ] Functions are small and single-purpose
- [ ] Types used correctly (mypy passes)
- [ ] No `TODO:` or `FIXME:` left in code without issue ref
- [ ] Logs are descriptive but not verbose (no secrets)

### Style
- [ ] Follows project conventions (see `CONTRIBUTING.md`)
- [ ] Conventional commit format
- [ ] Consistent naming

### Documentation
- [ ] Complex logic explained in comments
- [ ] Public API has docstrings
- [ ] README/ARCHITECTURE updated if architecture changed

## 🟢 Nitpick (Optional — Leave as Comment, Don't Block)

- [ ] Minor style nits (can auto-fix with ruff)
- [ ] Slightly verbose variable names
- [ ] Alternative implementation suggestions

## Reviewer Actions

| Action | When to Use |
|--------|-------------|
| **Approve** | All 🔴 blockers pass, 🟡 items acknowledged or justified |
| **Request Changes** | Any 🔴 blocker unaddressed |
| **Comment** | 🟢 nicks or suggestions, no blocking |

## Security-First Review

For changes touching these areas, assign `security-tester` or run manual checks:

| Area | Risk |
|------|------|
| `src/riks_context_engine/memory/` | Data exposure, injection |
| `src/riks_context_engine/mcp/` | Tool schema injection, execution context |
| `src/riks_context_engine/api/` | Authentication, rate limiting |
| `src/riks_context_engine/context/` | Memory export sanitization |
| `src/riks_context_engine/graph/` | Graph traversal edge cases |

## PR Size Guide

| Size | Lines Changed | Suggestion |
|------|-------------|------------|
| XS | < 50 | Rush review OK |
| S | 50-200 | Standard review |
| M | 200-500 | Take your time, async comments |
| L | 500-1000 | Consider splitting |
| XL | > 1000 | **Must split** into logical PRs |

---

_Last updated: 2026-05-31 — AI Team Lead workflow_
