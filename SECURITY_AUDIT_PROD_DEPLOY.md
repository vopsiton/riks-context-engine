# Security Audit - feat/production-deployment-fixes

**Date:** 2026-05-30  
**Branch:** `feat/production-deployment-fixes`  
**Reviewer:** Security Tester Subagent  
**Changes:** Dockerfile (uvicorn + UI), docker-compose.prod.yml (host networking + LMS_URL), server.py (max_tokens removed)

---

## Security Findings

### 🔴 BLOCKER-1 | `network_mode: host` — Docker Network Isolation Bypassed

**File:** `docker-compose.prod.yml`, line 28

```yaml
network_mode: host
```

**Risk:** With `network_mode: host`, the container shares the host's network namespace directly. Docker's network isolation is completely disabled.

**Specific consequences:**
- **Port 8000** is exposed directly on the host machine, no Docker port remapping
- The container's processes are bound directly to host ports (as if running natively)
- `extra_hosts: host.docker.internal:host-gateway` becomes redundant (already on host network)
- Any other service listening on the host (e.g., LM-Studio on :1234) becomes directly accessible from within the container **without any network restriction**
- Docker's `--link` and internal DNS resolution (`chroma` hostname) are also bypassed — the `CHROMA_HOST` env var will resolve in the host's DNS context

**Recommendation:** If you need host network for a specific reason (e.g., LM-Studio on host is bound to 127.0.0.1 and Docker can't reach it otherwise), isolate with firewall rules or use a custom `network_mode: bridge` with explicit host access via `extra_hosts`. **Never expose port 8000 publicly without a reverse proxy (nginx) with authentication in front.**

---

### 🔴 BLOCKER-2 | No Authentication on HTTP API Server

**File:** `src/riks_context_engine/api/server.py`

**Risk:** The FastAPI server has **zero authentication middleware**. Endpoints are:

| Endpoint | Method | Impact |
|----------|--------|--------|
| `/api/chat` | POST | Arbitrary AI inference via LM-Studio — SSRF potential, cost abuse |
| `/api/v1/memory/export` | GET | Full memory dump (could contain sensitive context) |
| `/api/v1/memory/import` | POST | Memory injection — could poison context |
| `/` | GET | Serves `ui/index.html` — no auth |
| `/health` | GET | Exposes system info |
| `/models` | GET | Lists available models |

**No auth token, no API key, no session.** Anyone who can reach port 8000 can:
- Query the AI model and abuse LM-Studio compute
- Exfiltrate all memory data (episodic + semantic + procedural)
- Inject manipulated memory entries

**Recommendation:** Add at minimum an API key check:
```python
from fastapi import Header
API_KEY = os.environ.get("API_KEY", "")

@app.middleware
async def auth_middleware(request: Request, call_next):
    if request.url.path not in ["/health", "/docs", "/openapi.json"]:
        if API_KEY and request.headers.get("X-API-Key") != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
```

---

### 🟡 WARNING-1 | `LMS_URL=http://127.0.0.1:1234/v1` — Internal Endpoint Exposed in Container Env

**File:** `docker-compose.prod.yml`, line 14

```yaml
LMS_URL=http://127.0.0.1:1234/v1
```

**Risk:** `127.0.0.1` inside the container refers to the **container's own localhost**, NOT the host's LM-Studio. With `network_mode: host`, this happens to work (same network namespace), but:

- This is **misleading configuration** — the intent is clearly to reach the host's LM-Studio
- If the container is ever run without `network_mode: host`, `127.0.0.1:1234` inside the container will not reach the host's LM-Studio
- Hardcoded `127.0.0.1` prevents LM-Studio from being on a different host in future deployments

**Recommendation:** Use `host.docker.internal` for the host LM-Studio:
```yaml
LMS_URL=http://host.docker.internal:1234/v1
```
And remove `network_mode: host` to keep proper container isolation.

---

### 🟡 WARNING-2 | Port 8000 Publicly Exposed via Docker Port Mapping

**File:** `docker-compose.prod.yml`, line 22

```yaml
ports:
  - "8000:8000"
```

**Risk:** Combined with `network_mode: host`, this maps host port 8000 directly to the container. Since there's no authentication (BLOCKER-2), **anyone on the network can access the full API.**

**Recommendation:** 
- Bind to `127.0.0.1:8000` only (not `0.0.0.0`) if accessible only locally
- Put behind nginx with auth
- Use firewall to restrict access

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

---

### 🟡 WARNING-3 | No TLS/HTTPS in Production

**File:** `Dockerfile` + `server.py`

**Risk:** API server runs plain HTTP. All data (including memory exports) travels unencrypted over the network. CORS is configured with `allow_credentials: True` — without HTTPS, this is a security risk in production (cookies/tokens vulnerable to interception).

**Recommendation:** 
- Add TLS termination in nginx or use a cloud load balancer
- Alternatively, use `uvicorn` with SSL certs:
  ```yaml
  CMD ["python", "-m", "uvicorn", "riks_context_engine.api.server:app", 
       "--host", "0.0.0.0", "--port", "8000", 
       "--ssl-keyfile", "/app/certs/key.pem", 
       "--ssl-certfile", "/app/certs/cert.pem"]
  ```

---

### 🟢 INFO-1 | `max_tokens` Removed from LM-Studio Call — Not a Security Issue

**File:** `src/riks_context_engine/api/server.py`, line 52

The `max_tokens: 2048` was removed from the LM-Studio API payload. This is **not a security issue** — it actually allows full model context to be used. The original cap was arbitrary and could cause truncated responses. No security concern here.

---

## Security Findings Summary

| ID | Severity | Issue | File |
|----|----------|-------|------|
| BLOCKER-1 | 🔴 CRITICAL | `network_mode: host` bypasses Docker isolation | `docker-compose.prod.yml` |
| BLOCKER-2 | 🔴 CRITICAL | No authentication on API server | `server.py` |
| WARNING-1 | 🟡 MEDIUM | Hardcoded `127.0.0.1:1234` won't work without host networking | `docker-compose.prod.yml` |
| WARNING-2 | 🟡 MEDIUM | Port 8000 publicly exposed without auth | `docker-compose.prod.yml` |
| WARNING-3 | 🟡 MEDIUM | No TLS — all traffic unencrypted | `Dockerfile` / `server.py` |
| INFO-1 | 🟢 LOW | `max_tokens` removal — no security concern | `server.py` |

---

## Recommended Fix Priority

1. **Add API key authentication** (BLOCKER-2) — at minimum `X-API-Key` header check
2. **Revert `network_mode: host`** or document why it's required (BLOCKER-1)
3. **Fix `LMS_URL`** to use `host.docker.internal:1234` instead of `127.0.0.1` (WARNING-1)
4. **Bind port 8000 to localhost only** (`127.0.0.1:8000:8000`) (WARNING-2)
5. **Add TLS** in production (WARNING-3)

---

## Positive Observations

- No hardcoded secrets or API keys found
- Rate limiting middleware present (100 req/min per IP)
- CORS properly configured with explicit origins from `ALLOWED_ORIGINS`
- Health endpoint excluded from rate limiting
- Memory import validates input with `parse_manifest`
- No SQL injection risk (parameterized queries)