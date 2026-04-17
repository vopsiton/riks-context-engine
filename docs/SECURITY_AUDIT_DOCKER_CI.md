# Security Audit Report - vopsiton/riks-context-engine

Date: 2026-04-16
Auditor: Security Tester

---

## Docker / docker-compose.yml

### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | **HIGH** | Container runs as root (no `USER` directive in Dockerfile) | Dockerfile |
| 2 | **HIGH** | Service port bound to `0.0.0.0:8000` instead of `127.0.0.1:8000` | docker-compose.yml |
| 3 | **MEDIUM** | No `HEALTHCHECK` defined in Dockerfile | Dockerfile |

### Recommendations

1. **Add a non-root user in Dockerfile:**
   ```dockerfile
   # Create non-root user
   RUN groupadd --gid 1000 appgroup && \
       useradd --uid 1000 --gid appgroup --shell /bin/bash appuser

   # Switch to non-root before copying code
   USER appuser

   # Copy code and set ownership
   COPY --chown=appuser:appgroup src/ ./src/
   COPY --chown=appuser:appgroup tests/ ./tests/
   ```

2. **Bind to localhost only in docker-compose.yml:**
   ```yaml
   ports:
     - "127.0.0.1:8000:8000"
   ```
   This prevents the service from being exposed on all network interfaces.

3. **Add HEALTHCHECK to Dockerfile:**
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
     CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
   ```
   *(Note: requires a `/health` endpoint in the application, or use `curl`/`wget` if installed)*

---

## GitHub Actions CI

### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | **LOW** | `pre-commit/action@v3.0.1` — pinning to a specific patch version is excessive and makes updates harder; `v3.0` or `v3` is preferred | ci.yml |

### Recommendations

1. Change `pre-commit/action@v3.0.1` → `pre-commit/action@v3.0.1` is acceptable but `pre-commit/action@v3` is more maintainable. The action itself is not a third-party repo — it's the official pre-commit org action, so minor-version drift is acceptable.

**Positive observations:**
- All actions properly pinned: `checkout@v4`, `setup-python@v5`, `codecov@v4` ✅
- `codecov-action@v4` does NOT expose the token in logs — it uses the token only for authenticated upload ✅
- `write` permission is not set on any job (minimal permissions principle) ✅
- Matrix strategy for Python versions is appropriate ✅

---

## Environment Variables

### Issues Found

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | **LOW** | `OLLAMA_MODEL` has a concrete value (`gemma4-31b-it`) — could be mistaken for a real deployed model name | .env.example |
| 2 | **LOW** | `LOG_LEVEL` is present but not explained in comments | .env.example |

### Recommendations

1. Use a placeholder for `OLLAMA_MODEL`:
   ```
   OLLAMA_MODEL=<your-model>  # e.g. gemma4-31b-it
   ```

2. Add a comment for `LOG_LEVEL`:
   ```
   LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
   ```

**Positive observations:**
- Real credentials are NOT present (API keys are commented and use `sk-...` / `sk-ant-...` format as obvious placeholders) ✅
- All required environment variables are documented ✅
- Provider-specific keys are grouped and clearly labeled ✅

---

## Summary

| Category | CRITICAL | HIGH | MEDIUM | LOW |
|----------|----------|------|--------|-----|
| Docker | 0 | 2 | 1 | 0 |
| GitHub Actions CI | 0 | 0 | 0 | 1 |
| Environment Variables | 0 | 0 | 0 | 2 |
| **Total** | **0** | **2** | **1** | **3** |

**Priority actions:**
1. 🔴 **Add non-root USER to Dockerfile** — containers should not run as root
2. 🔴 **Bind port to 127.0.0.1** — prevent public exposure of development service
3. 🟡 **Add HEALTHCHECK** — enables Docker to properly detect and restart crashed containers

CI workflow is well-configured. No secret leakage detected.
