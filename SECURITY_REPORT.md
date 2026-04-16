# Security Review Report - riks-context-engine

## Date: 2026-04-16
## Reviewer: Security Tester

---

## Findings

### MEDIUM | Ollama HTTP Client Does Not Enforce SSL Certificate Verification

- **Description:** `OllamaEmbedder` in `src/riks_context_engine/memory/embedding.py` creates an `httpx.Client` without explicit TLS verification configuration. When the `base_url` is set to an HTTPS endpoint (e.g., a remote Ollama server), SSL certificate verification is not explicitly enabled. The default behavior of httpx does verify HTTPS connections, but without explicit configuration, environments with custom CA bundles or proxy interceptors may silently bypass certificate checks.

- **Location:** `src/riks_context_engine/memory/embedding.py`, lines 50–53 (`OllamaEmbedder.__init__`)

- **Recommendation:** Explicitly configure the HTTP client with certificate verification:
  ```python
  self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout, verify=True)
  ```
  Or make verification configurable via environment variable:
  ```python
  verify = os.environ.get("OLLAMA_VERIFY_SSL", "true").lower() == "true"
  self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout, verify=verify)
  ```

---

### MEDIUM | Silent Exception Swallowing in Embedding Operations Masks Failures

- **Description:** In `KnowledgeGraph.add_entity()` (`src/riks_context_engine/graph/knowledge_graph.py`, lines 176–181) and `KnowledgeGraph.reembed_entity()` (lines 208–211), embedding failures are caught with a bare `except Exception: pass`. This silently swallows all errors from the Ollama embedding service, including network errors, API authentication failures, and malformed responses. An attacker controlling the Ollama endpoint (e.g., via a redirected `OLLAMA_BASE_URL`) could cause the system to operate without embeddings while appearing healthy, leading to degraded security decisions that rely on semantic search results.

- **Location:** `src/riks_context_engine/graph/knowledge_graph.py`, lines 176–181 and 208–211

- **Recommendation:** At minimum, log the exception at WARNING level. Consider raising a custom `EmbeddingError` so callers can handle failures explicitly:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  try:
      result = self._embedder.embed(name)
      entity.embedding = result.embedding
  except Exception as exc:
      logger.warning("Embedding failed for entity %s: %s", name, exc)
      # entity will have no embedding — callers should handle this
  ```

---

### LOW | Predictable Task IDs Based on Monotonic Counter

- **Description:** `TaskDecomposer._create_task()` (`src/riks_context_engine/tasks/decomposer.py`, line 140) generates task IDs using a simple incrementing counter (`self._task_counter`). While not directly exploitable in a CLI tool, predictable IDs can aid attackers in crafting targeted dependency-tampering attacks if task graphs are ever serialized or transmitted over a network.

- **Location:** `src/riks_context_engine/tasks/decomposer.py`, line 140

- **Recommendation:** Use a UUID-based ID scheme:
  ```python
  import uuid
  id=f"task_{uuid.uuid4().hex[:8]}",
  ```

---

### LOW | No Path Traversal Validation on Storage Paths

- **Description:** `ProceduralMemory`, `EpisodicMemory`, and `SemanticMemory` accept a `storage_path` parameter that is used directly to open files without validating that the resolved path is within the intended directory. A malicious caller could pass `storage_path="/etc/passwd"` or `"../../../etc/passwd"` to overwrite sensitive system files (injection via file writes).

- **Location:** 
  - `src/riks_context_engine/memory/procedural.py`, `__init__`
  - `src/riks_context_engine/memory/episodic.py`, `__init__`
  - `src/riks_context_engine/memory/semantic.py`, `__init__`

- **Recommendation:** Validate storage paths using `pathlib.Path.resolve()` and a known-safe base directory:
  ```python
  from pathlib import Path
  SAFE_BASE = Path("data").resolve()
  resolved = Path(storage_path).resolve()
  if not resolved.is_relative_to(SAFE_BASE):
      raise ValueError(f"Storage path {storage_path} escapes safe directory")
  ```

---

### LOW | Bandit: Bare `except Exception: pass` (2 occurrences)

- **Description:** Two instances of silently swallowing all exceptions detected by Bandit security linter. While these are LOW severity (the intent is to make embedding failures non-fatal), they also fall under the MEDIUM issue above regarding silent exception handling.

- **Location:**
  - `src/riks_context_engine/graph/knowledge_graph.py:179`
  - `src/riks_context_engine/graph/knowledge_graph.py:210`

- **Recommendation:** See MEDIUM recommendation above — add logging instead of bare `pass`.

---

## Dependencies Audit

| Package | Version | Status | Notes |
|---------|---------|--------|-------|
| sqlalchemy | >=2.0 | ✅ OK | Parameterized SQL — no injection risk |
| chromadb | >=0.4.0 | ⚠️ Review | No direct usage found in source; included as dependency |
| ollama | >=0.1.0 | ⚠️ Review | No direct usage found in source; included as dependency |
| httpx | (transitive) | ✅ OK | Used for Ollama API calls |

**safety check results:** 3 vulnerabilities reported — all in `pip` itself (versions < 25.0, < 26.0, < 25.2), **not in project code**. These are in the test environment's pip installation and are not a supply-chain risk to the project itself. Remediate by upgrading pip in the test/CI environment: `pip install --upgrade pip`.

---

## Recommendations

1. **Fix Ollama SSL verification** (MEDIUM) — Explicitly configure TLS certificate verification in `OllamaEmbedder`
2. **Replace silent exception handling** (MEDIUM) — Log embedding failures instead of silently swallowing them in `KnowledgeGraph`
3. **Add path traversal protection** (LOW) — Validate all file storage paths against the intended `data/` directory
4. **Use UUIDs for task IDs** (LOW) — Replace monotonic counter with `uuid.uuid4()` for unpredictable IDs
5. **Remediate pip in CI environment** (INFO) — Upgrade pip to >= 26.0 in test/CI to eliminate environment vulnerabilities

---

## Positive Note

**No critical security issues found.** Codebase follows good security practices in key areas:

- **No SQL injection** — All SQL queries in `semantic.py` and `knowledge_graph.py` use parameterized queries with `?` placeholders. No string concatenation into SQL.
- **No unsafe deserialization** — JSON is used throughout (`json.load`/`json.dump`); no `pickle`, `yaml` with unsafe loaders, or `eval`/`exec`.
- **No hardcoded secrets** — No API keys, passwords, or credentials found in source code.
- **No network-exposed API endpoints** — This is a CLI/library tool with no HTTP server. There is no attack surface for authentication bypass, CORS misconfiguration, or rate-limit exhaustion.
- **Authentication/authorization N/A** — As a local CLI tool, no auth layer is expected or required.
