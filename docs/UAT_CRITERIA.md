# UAT Criteria — Rik's Context Engine

**Report to:** Rik (chief agent)
**Rule:** UAT pass olmadan PR merge YASAK
**Last Updated:** 2026-04-19

---

## Genel Kurallar

1. Her feature/fix için UAT sheet zorunlu
2. Tüm AC'ler PASS olmadan PR merge **YASAK**
3. Raporlama: Rik (chief agent) tarafından yapılır
4. Fail senaryoları da test edilmeli — happy path tek başına yeterli değil
5. Rollback plan her feature için hazır olmalı

---

## P0 — Kritik (Blocker Fixes)

### Issue #48 — SQL Injection Fix

**Priority:** P0
**Branch:** `fix/sql-injection-48`
**Status:** TODO

#### Scope
- **Yapılıyor:** Tüm DB query'leri parameterized statements ile yeniden yazılacak
- **Yapılmıyor:** DB schema değişikliği, yeni endpoint ekleme

#### Pre-conditions
- [ ] DB migration çalıştırılmış olmalı
- [ ] Unit test'ler + integration test'ler hazır olmalı
- [ ] Security review tamamlanmış olmalı

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-48-01 | Tüm DB query'leri parameterized | Code review + grep `SELECT.*\+\|` | 0 raw string concatenation |
| AC-48-02 | LIKE clause'da injection önlenmiş | Unit test | `'; DROP TABLE users; --` → sanitize edilir |
| AC-48-03 | Input validation tüm endpoints | Fuzz test | 400 Bad Request + body okunmaz |
| AC-48-04 | Mevcut test'ler geçiyor | `pytest` | 100% pass |

#### Test Scenarios

```python
# Scenario 1: Safe LIKE clause injection
def test_sql_injection_safe_like():
    """
    Fail senaryosu: Kötü niyetli LIKE input'u DB'yi okuyabilir.
    
    Input: "'; SELECT * FROM sqlite_master; --"
    Expected: Parametre olarak gönderilir, SQL çalışmaz
    """
    memory = SemanticMemory(db_path=":memory:")
    # Normal input
    result = memory.query(subject="test", predicate="is")
    assert isinstance(result, list)
    
    # Injection attempt — should be treated as literal string
    result = memory.query(subject="'; DROP TABLE users; --", predicate="test")
    # Should NOT raise, should return empty list
    assert isinstance(result, list)


# Scenario 2: Unsafe string interpolation (REJECT THIS PATTERN)
def test_sql_injection_unsafe_pattern_rejected():
    """
    Code review ile yakalanmalı:
    
    KÖTÜ (reject):
        cursor.execute(f"SELECT * FROM table WHERE id = {user_input}")
    
    İYİ (accept):
        cursor.execute("SELECT * FROM table WHERE id = ?", (user_input,))
    """
    # Grep pattern: fail if found
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "execute.*f\"", "src/"],
        capture_output=True
    )
    assert result.returncode != 0, "f-string in execute() found — SQL injection risk!"


# Scenario 3: Existing tests still pass
def test_sql_injection_regression():
    """Mevcut testler kopmamalı."""
    from tests.test_memory import *
    # Run all existing memory tests
    # Expected: 100% pass
```

#### Rollback Plan
- [ ] `git revert` ile son commit'e dön
- [ ] Yeni branch aç: `fix/sql-injection-safe-v2`
- [ ] Alternatif: ORM (SQLAlchemy) kullanımına geç

#### Dependencies
- SemanticMemory.query()
- KnowledgeGraph.query()
- Tüm API endpoints

---

### Issue #51 — Thread-safe SQLite

**Priority:** P0
**Branch:** `fix/thread-safe-sqlite-51`
**Status:** TODO

#### Scope
- **Yapılıyor:** SemanticMemory ve KnowledgeGraph'te SQLite race condition'lar giderilecek
- **Yapılmıyor:** ContextWindowManager veya EpisodicMemory (zaten single-threaded JSON)

#### Pre-conditions
- [ ] `concurrent.futures.ThreadPoolExecutor` ile multi-thread test hazır
- [ ] `stress_test.py` scripti mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-51-01 | 10 thread eşzamanlı write | Stress test | 0 `Database is locked` hatası |
| AC-51-02 | Reader/writer ayrımı | Thread test | WAL mode veya lock timeout |
| AC-51-03 | Context manager kullanımı | Code review | `with` statement, explicit close |
| AC-51-04 | Mevcut test'ler geçiyor | `pytest` | 100% pass |

#### Test Scenarios

```python
# Scenario 1: Concurrent writes (FAIL CASE)
import threading
import sqlite3

def test_concurrent_writes_locked():
    """
    FAIL: 10 thread aynı anda write yapıyor.
    
    Hata: sqlite3.OperationalError: database is locked
    """
    errors = []
    def writer(thread_id):
        try:
            conn = sqlite3.connect("data/semantic.db")
            conn.execute("INSERT INTO semantic_entries ...")
            conn.commit()
        except sqlite3.OperationalError as e:
            errors.append((thread_id, str(e)))
        finally:
            conn.close()
    
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    # Expected: 0 errors with proper locking
    assert len(errors) == 0, f"Got errors: {errors}"


# Scenario 2: WAL mode enables concurrent reads
def test_wal_concurrent_reads():
    """
    WAL mode açıkken read'ler write'ları block etmemeli.
    """
    memory = SemanticMemory(db_path=":memory:")
    # Enable WAL
    with memory._conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    
    results = []
    def reader(i):
        r = memory.query(subject="test")
        results.append(r)
    
    threads = [threading.Thread(target=reader, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    
    assert len(results) == 5


# Scenario 3: Context manager prevents leaked connections
def test_connection_cleanup():
    """
    Her query sonrası connection kapatılmalı.
    """
    import gc
    memory = SemanticMemory(db_path=":memory:")
    
    for _ in range(100):
        memory.query(subject="test")
    
    gc.collect()
    # Check for unclosed connections
    # Expected: 0 leaked connections
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Fallback: `check_same_thread=False` + `timeout=30` config
- [ ] Test: aynı DB'ye sequential access

#### Dependencies
- SemanticMemory (P0)
- KnowledgeGraph (P1)

---

## P1 — High Priority

### Issue #49 — CORS PATCH/HEAD Methods

**Priority:** P1
**Branch:** `fix/cors-patch-head-49`
**Status:** TODO

#### Scope
- **Yapılıyor:** CORS middleware'ine PATCH ve HEAD method'ları eklenecek
- **Yapılmıyor:** Preflight request handling, authentication

#### Pre-conditions
- [ ] Test client hazır (`httpx` veya `requests`)
- [ ] CORS preflight log'ları görülebilir

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-49-01 | PATCH method allowed | HTTP test | 200 OK, `Access-Control-Allow-Methods` contains PATCH |
| AC-49-02 | HEAD method allowed | HTTP test | 200 OK |
| AC-49-03 | Preflight OPTIONS 204 | HTTP test | 204 No Content |
| AC-49-04 | Credentials header allowed | Unit test | `Access-Control-Allow-Credentials: true` |

#### Test Scenarios

```python
# Scenario 1: PATCH preflight (FAIL CASE)
def test_cors_patch_preflight_fails():
    """
    FAIL: PATCH method CORS'da yok.
    
    Browser: OPTIONS /api/v1/memory/export
    Response: 405 Method Not Allowed
    
    Expected: 204 + PATCH in allowed methods
    """
    import httpx
    
    response = httpx.options(
        "http://localhost:8080/api/v1/memory/export",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PATCH",
        }
    )
    
    assert response.status_code == 204, f"Got {response.status_code}"
    assert "PATCH" in response.headers.get("Access-Control-Allow-Methods", "")


# Scenario 2: HEAD method allowed
def test_cors_head_method():
    """HEAD request CORS'da allowed olmalı."""
    response = httpx.head("http://localhost:8080/api/v1/memory/export")
    assert response.status_code in (200, 204)


# Scenario 3: Credentials in cross-origin
def test_cors_credentials():
    """
    withCredentials = true yapıldığında credential'lar gitmeli.
    """
    response = httpx.get(
        "http://localhost:8080/api/v1/memory/export",
        headers={"Origin": "http://example.com"},
    )
    assert response.headers.get("Access-Control-Allow-Credentials") == "true"
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Hardcode: `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` → önceki hal

#### Dependencies
- FastAPI server.py

---

### Issue #50 — Token Estimation Accuracy

**Priority:** P1
**Branch:** `fix/token-estimation-50`
**Status:** TODO

#### Scope
- **Yapılıyor:** ContextWindowManager token estimation'i daha doğru hale getirilecek
- **Yapılmıyor:** tiktoken/tiktokenr dependency eklemek (opsiyonel)

#### Pre-conditions
- [ ] LM Studio veya Ollama'da test data hazır
- [ ] Farklı dillerde test corpus mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-50-01 | İngilizce metin: ±10% doğruluk | Token count vs estimate | `abs(estimated - actual) / actual <= 0.10` |
| AC-50-02 | Türkçe metin: ±15% doğruluk | Token count vs estimate | `abs(estimated - actual) / actual <= 0.15` |
| AC-50-03 | Code blocks: 1.3x multiplier | Code test | Code tokens > plain text tokens |
| AC-50-04 | CJK characters: 2 chars/token | Unicode test | `len(text) / 2 ≈ tokens` |

#### Test Scenarios

```python
# Scenario 1: English text accuracy (FAIL CASE)
def test_token_estimation_english_fail():
    """
    FAIL: 1000 char İngilizce metin için estimation yanlış.
    
    Gerçek: ~250 tokens (4 char/token)
    Estimation: 250 tokens
    Diff: 0% ✓
    
    Ama 5000 char için:
    Gerçek: ~1250 tokens
    Estimation: 1250 tokens
    """
    from riks_context_engine.context.manager import ContextWindowManager
    
    mgr = ContextWindowManager()
    
    english_text = "This is a sample text for testing token estimation accuracy. " * 50
    estimated = mgr._estimate_tokens(english_text)
    
    # tiktoken ile gerçek değeri bul (opsiyonel)
    # assert abs(estimated - actual) / actual <= 0.10


# Scenario 2: Turkish text (non-Latin script)
def test_token_estimation_turkish():
    """
    Türkçe'de char/token oranı daha yüksek.
    
    "Merhaba dünya, nasılsın?" → 21 char
    Estimation: 21 / 4 = 5 tokens (yanlış!)
    Gerçek: ~12 tokens (Türkçe < 2 char/token)
    """
    mgr = ContextWindowManager()
    
    turkish_text = "Merhaba dünya! Nasılsın? Bugün hava çok güzel."
    estimated = mgr._estimate_tokens(turkish_text)
    
    # Check non-Latin detection
    assert mgr._contains_non_latin(turkish_text) == False  # Turkish uses Latin script
    # Actual: depends on model tokenizer


# Scenario 3: Code blocks get more tokens
def test_token_estimation_code():
    """Code blocks 1.3x multiplier almalı."""
    mgr = ContextWindowManager()
    
    plain = "Hello world, this is a test message."
    code = "def hello(): print('hello world')"
    
    tokens_plain = mgr._estimate_tokens(plain)
    tokens_code = mgr._estimate_tokens(code)
    
    # Code should have higher token/char ratio
    # (but depends on actual code content)
    assert tokens_code >= tokens_plain


# Scenario 4: CJK characters (2 chars/token)
def test_token_estimation_cjk():
    """Çince/Korece/Japonca: 2 char/token."""
    mgr = ContextWindowManager()
    
    cjk_text = "你好世界これはテストです"  # ~20 chars
    estimated = mgr._estimate_tokens(cjk_text)
    
    # Should detect CJK
    assert mgr._contains_non_latin(cjk_text) == True
    # Expected: 20 / 2 = 10 tokens
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Hardcode: `len(text) // 4` base estimation'a dön

#### Dependencies
- ContextWindowManager._estimate_tokens()
- ContextWindowManager._contains_non_latin()

---

### Issue #52 — KnowledgeGraph Silent Fallback

**Priority:** P1
**Branch:** `fix/kg-silent-fallback-52`
**Status:** TODO

#### Scope
- **Yapılıyor:** Embedder unavailableken graceful degradation + warn log
- **Yapılmıyor:** Retry logic, circuit breaker

#### Pre-conditions
- [ ] Ollama/LM Studio embedder offline test hazır
- [ ] Log capture mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-52-01 | Embedder timeout → keyword fallback | Mock test | `semantic_search()` returns results, no exception |
| AC-52-02 | Warning log atılır | Log capture | `"Embedding service unavailable, using keyword fallback"` |
| AC-52-03 | Score 0.0 dönmez (keyword match varsa) | Mock test | Sonuç döner, pozitif score |
| AC-52-04 | Empty results döner (keyword match yoksa) | Mock test | `[]` + warn log |

#### Test Scenarios

```python
# Scenario 1: Embedder timeout (FAIL CASE)
def test_kg_embedder_timeout_fail():
    """
    FAIL: Embedder unavailable → exception fırlatıyor.
    
    Expected: graceful fallback to keyword search
    """
    kg = KnowledgeGraph()
    kg.add_entity("Test Entity", EntityType.CONCEPT, {"desc": "test"})
    
    # Mock embedder to raise
    original_embed = kg._get_entity_embedding
    def failing_embed(entity):
        raise TimeoutError("Embedder not responding")
    
    # This should NOT raise
    results = kg.semantic_search("test query", top_k=5)
    assert isinstance(results, list)


# Scenario 2: Fallback logs warning
def test_kg_fallback_warning():
    """Warning log atılmalı."""
    import logging
    
    class LogCapture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []
        def emit(self, record):
            self.records.append(record)
    
    handler = LogCapture()
    logging.getLogger("riks_context_engine.graph").addHandler(handler)
    
    kg = KnowledgeGraph()
    kg._get_entity_embedding = lambda e: (_ for _ in ()).throw(TimeoutError())
    
    kg.semantic_search("test")
    
    warning_msgs = [r.getMessage() for r in handler.records if r.levelname == "WARNING"]
    assert any("fallback" in m.lower() for m in warning_msgs)


# Scenario 3: Results returned via keyword fallback
def test_kg_keyword_fallback_results():
    """Keyword fallback çalışıyor."""
    kg = KnowledgeGraph()
    kg.add_entity("Vahit Server", EntityType.PERSON, {"role": "engineer"})
    kg.add_entity("Kubernetes", EntityType.CONCEPT, {"type": "orchestration"})
    
    # Force keyword fallback
    def force_fallback(entity):
        raise Exception("Forced fallback")
    
    results = kg.semantic_search("Kubernetes", top_k=3)
    
    assert len(results) > 0
    assert any("Kubernetes" in str(r[0].name) for r in results)
```

#### Rollback Plan
- [ ] `git revert`
- [ ] `raise EmbedderUnavailableError()` → önceki hali

#### Dependencies
- KnowledgeGraph.semantic_search()
- KnowledgeGraph._keyword_search()

---

### Issue #53 — Memory Import Schema Validation

**Priority:** P1
**Branch:** `fix/memory-import-schema-53`
**Status:** TODO

#### Scope
- **Yapılıyor:** Import edilen manifest'in schema validation'ı (version, required fields)
- **Yapılmıyor:** Full JSON Schema validation, recursive validation

#### Pre-conditions
- [ ] Test fixture'lar hazır (valid/invalid manifests)
- [ ] Error message formatı belirlenmiş

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-53-01 | Geçersiz schema_version → ValueError | Unit test | 400 + error message |
| AC-53-02 | Eksik required field → ValueError | Unit test | 400 + field name |
| AC-53-03 | Major version mismatch → reject | Unit test | `"Schema version mismatch"` |
| AC-53-04 | Valid manifest → import başarılı | Unit test | counts match expected |

#### Test Scenarios

```python
# Scenario 1: Invalid schema version (FAIL CASE)
def test_import_invalid_version_fail():
    """
    FAIL: Schema version 99.9 olan manifest kabul ediliyor.
    
    Expected: ValueError, HTTP 400
    """
    manifest_json = json.dumps({
        "metadata": {
            "schema_version": "99.9",
            "exported_at": "2026-04-19T00:00:00Z",
            "tool": "riks-context-engine"
        },
        "episodic": [],
        "semantic": [],
        "procedural": []
    })
    
    from riks_context_engine.memory.export import parse_manifest
    
    with pytest.raises(ValueError, match="Schema version mismatch"):
        parse_manifest(manifest_json, format="json")


# Scenario 2: Missing required field
def test_import_missing_required_field():
    """metadata key yok → ValueError."""
    manifest_json = json.dumps({
        "episodic": [{"id": "e1", "content": "test"}],
        "semantic": [],
        "procedural": []
    })
    
    with pytest.raises(KeyError):
        parse_manifest(manifest_json, format="json")


# Scenario 3: Major version mismatch
def test_import_major_version_mismatch():
    """Major version farklı → reject."""
    manifest_json = json.dumps({
        "metadata": {
            "schema_version": "2.0",
            "exported_at": "2026-04-19T00:00:00Z",
            "tool": "riks-context-engine"
        },
        "episodic": [],
        "semantic": [],
        "procedural": []
    })
    
    with pytest.raises(ValueError, match="Major version must match"):
        parse_manifest(manifest_json, format="json")


# Scenario 4: Valid manifest passes
def test_import_valid_manifest():
    """Doğru manifest → import başarılı."""
    manifest = ExportManifest(
        metadata=ExportMetadata(),
        episodic=[{
            "id": "e1",
            "content": "test memory",
            "timestamp": "2026-04-19T00:00:00Z",
            "importance": 0.8,
            "tags": ["test"]
        }],
        semantic=[],
        procedural=[]
    )
    
    episodic = EpisodicMemory(storage_path=":memory:")
    imported = import_to_memory(manifest, episodic_memory=episodic)
    
    assert imported["episodic"] == 1
```

#### Rollback Plan
- [ ] `git revert`
- [ ] `parse_manifest()` → `json.loads()` direkt

#### Dependencies
- export.py parse_manifest()
- export.py _check_schema_compat()

---

## P2 — Medium Priority

### Issue #54 — ContextWindowManager Async

**Priority:** P2
**Branch:** `fix/cwmanager-async-54`
**Status:** TODO

#### Scope
- **Yapılıyor:** ContextWindowManager async method'ları eklenecek (add_async, prune_async)
- **Yapılmıyor:** Full async rewrite, await chain refactor

#### Pre-conditions
- [ ] `pytest-asyncio` mevcut
- [ ] Mevcut sync test'ler çalışıyor

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-54-01 | `add_async()` → coroutine | Async test | `inspect.iscoroutinefunction(add_async)` |
| AC-54-02 | Async add works same as sync | Async test | Token count matches |
| AC-54-03 | Lock kullanımı (thread-safe) | Code review | `asyncio.Lock` |
| AC-54-04 | Mevcut test'ler geçiyor | `pytest` | 100% pass |

#### Test Scenarios

```python
import asyncio

# Scenario 1: Async add is a coroutine
def test_add_async_is_coroutine():
    """add_async() coroutine olmalı."""
    import inspect
    mgr = ContextWindowManager()
    
    assert inspect.iscoroutinefunction(mgr.add_async)


# Scenario 2: Async add behavior matches sync
async def test_add_async_behavior():
    """Async add = Sync add."""
    mgr = ContextWindowManager()
    
    await mgr.add_async("user", "Hello world", importance=0.9)
    sync_result = mgr.add("user", "Hello world", importance=0.9)
    
    # Should have same tokens
    assert mgr.messages[-1].tokens == sync_result.tokens


# Scenario 3: Async concurrent adds (FAIL CASE)
async def test_concurrent_adds_async():
    """
    FAIL: Concurrent async adds race condition.
    
    10 coroutines aynı anda add_async() çağırıyor.
    Expected: Sıralı ekleme, 10 mesaj
    """
    mgr = ContextWindowManager()
    
    async def add_msg(i):
        await mgr.add_async("user", f"Message {i}", importance=0.5)
    
    await asyncio.gather(*[add_msg(i) for i in range(10)])
    
    assert len(mgr.messages) == 10
```

#### Rollback Plan
- [ ] `git revert`
- [ ] `add_async` → alias for `add`

#### Dependencies
- ContextWindowManager.add()

---

### Issue #55 — Test Coverage Improvement

**Priority:** P2
**Branch:** `fix/test-coverage-55`
**Status:** TODO

#### Scope
- **Yapılıyor:** Coverage gap'leri kapatılacak (export, graph, reflection)
- **Yapılmıyor:** Yeni feature testleri, performance testleri

#### Pre-conditions
- [ ] `pytest-cov` mevcut
- [ ] Mevcut test'ler çalışıyor

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-55-01 | Coverage ≥ 85% overall | pytest-cov | 85% threshold |
| AC-55-02 | export.py ≥ 90% coverage | pytest-cov | Branch coverage |
| AC-55-03 | graph/knowledge_graph.py ≥ 80% | pytest-cov | 80% threshold |
| AC-55-04 | reflection/analyzer.py ≥ 80% | pytest-cov | 80% threshold |

#### Test Scenarios

```python
# Scenario 1: Current coverage report (FAIL CASE)
def test_coverage_report_fail():
    """
    FAIL: export.py coverage düşük.
    
    Run: pytest --cov=src --cov-report=term-missing
    Expected: export.py → 90%+
    """
    import subprocess
    result = subprocess.run(
        ["pytest", "--cov=src/riks_context_engine/memory/export", "--cov-report=term-missing"],
        capture_output=True,
        text=True
    )
    
    # Check output for export.py coverage
    # assert "export.py" in output
    # assert "90%" in output


# Scenario 2: Uncovered branches in parse_manifest
def test_parse_manifest_uncovered():
    """parse_manifest'ta uncovered branch var."""
    from riks_context_engine.memory.export import parse_manifest
    
    # Invalid YAML (not dict)
    with pytest.raises(ValueError):
        parse_manifest("just a string", format="yaml")
```


#### Rollback Plan
- [ ] `git revert`
- [ ] `@pytest.mark.skip(coverage="low")` ile mark et

#### Dependencies
- export.py, graph/, reflection/ — all modules

---

### Issue #56 — Rate Limiting

**Priority:** P2
**Branch:** `feature/rate-limiting-56`
**Status:** TODO

#### Scope
- **Yapılıyor:** API rate limiting (per-IP, per-token)
- **Yapılmıyor:** Global rate limit, distributed rate limiting

#### Pre-conditions
- [ ] Redis veya in-memory rate limiter hazır
- [ ] Test client mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-56-01 | 100 req/min limit | Load test | 101. req → 429 Too Many Requests |
| AC-56-02 | Rate limit header döner | HTTP test | `X-RateLimit-Remaining` |
| AC-56-03 | Burst allowance (10 req/s) | Load test | 10 req/s × 10s = 100 req |
| AC-56-04 | Configurable via env | Unit test | `RATE_LIMIT_*` env vars |

#### Test Scenarios

```python
import time

# Scenario 1: Rate limit exceeded (FAIL CASE)
def test_rate_limit_exceeded_fail():
    """
    FAIL: Rate limit aşılınca 200 dönüyor.
    
    Expected: 429 Too Many Requests
    """
    client = httpx.Client(base_url="http://localhost:8080")
    
    # Make 100 requests
    for i in range(100):
        r = client.get("/health")
        assert r.status_code == 200
    
    # 101st should be blocked
    r = client.get("/health")
    assert r.status_code == 429, f"Expected 429, got {r.status_code}"


# Scenario 2: Rate limit headers present
def test_rate_limit_headers():
    """Rate limit bilgisi header'larda."""
    r = httpx.get("http://localhost:8080/api/v1/memory/export")
    
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "X-RateLimit-Reset" in r.headers


# Scenario 3: Burst allowance
def test_rate_limit_burst():
    """10 req/s × 10s = 100 req başarılı."""
    start = time.time()
    successes = 0
    
    for i in range(100):
        r = httpx.get("http://localhost:8080/health")
        if r.status_code == 200:
            successes += 1
    
    elapsed = time.time() - start
    
    # Burst: 100 req in ~10 seconds
    assert successes >= 90, f"Only {successes}/100 succeeded"
    assert elapsed < 15, f"Took {elapsed}s, expected ~10s"
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Rate limit middleware'ini kaldır

#### Dependencies
- API server.py

---

### Issue #58 — ReflectionAnalyzer Persistence

**Priority:** P2
**Branch:** `fix/reflection-persistence-58`
**Status:** TODO

#### Scope
- **Yapılıyor:** ReflectionAnalyzer lessons'ları disk'e persist edilecek
- **Yapılmıyor:** Distributed persistence, lesson expiration

#### Pre-conditions
- [ ] Test için geçici JSON dosyası kullanılabilir
- [ ] Lesson serialization mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-58-01 | Lessons disk'e yazılır | File check | `data/lessons.json` exists |
| AC-58-02 | Lessons restart sonrası yüklenir | Restart test | 10 lessons after restart |
| AC-58-03 | Duplicate lesson merge | Unit test | `occurrence_count` artar |
| AC-58-04 | Lessons silinebilir | Unit test | `resolve_lesson()` + save |

#### Test Scenarios

```python
import json
import os

# Scenario 1: Lessons persisted (FAIL CASE)
def test_lessons_not_persisted_fail():
    """
    FAIL: Lessons memory'de kalıyor, restart ile kayboluyor.
    
    Expected: lessons.json oluşur
    """
    analyzer = ReflectionAnalyzer()
    analyzer._add_lesson(Lesson(
        id="l1", category="tool-use", observation="test",
        lesson_text="test lesson"
    ))
    
    # Check file exists
    lessons_path = "data/lessons.json"
    assert os.path.exists(lessons_path), "Lessons not persisted!"
    
    with open(lessons_path) as f:
        data = json.load(f)
    
    assert len(data) >= 1


# Scenario 2: Lessons restored on restart
def test_lessons_restored_after_restart():
    """Restart sonrası lessons yüklenir."""
    # Create analyzer, add lesson
    analyzer1 = ReflectionAnalyzer()
    analyzer1._add_lesson(Lesson(
        id="persist_test", category="context-management",
        observation="context overflow", lesson_text="monitor limits"
    ))
    
    # Simulate restart
    analyzer2 = ReflectionAnalyzer()
    analyzer2.load()  # Load from disk
    
    active = analyzer2.get_active_lessons()
    ids = [l.id for l in active]
    
    assert "persist_test" in ids


# Scenario 3: Duplicate lesson merge
def test_duplicate_lesson_merge():
    """Aynı category + severity → merge, count artar."""
    analyzer = ReflectionAnalyzer()
    
    l1 = Lesson(id="dup1", category="tool-use", observation="obs1",
                lesson_text="text1", severity="warning")
    l2 = Lesson(id="dup2", category="tool-use", observation="obs2",
                lesson_text="text2", severity="warning")
    
    analyzer._add_lesson(l1)
    analyzer._add_lesson(l2)
    
    # Should merge into one
    active = analyzer.get_active_lessons()
    tool_use_lessons = [l for l in active if l.category == "tool-use"]
    
    assert len(tool_use_lessons) == 1
    assert tool_use_lessons[0].occurrence_count == 2
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Persistence feature'ını comment out et, in-memory devam

#### Dependencies
- ReflectionAnalyzer
- SemanticMemory (optional backend)

---

### Issue #60 — SemanticMemory Recall O(n) Optimization

**Priority:** P2
**Branch:** `fix/semantic-recall-on-60`
**Status:** TODO

#### Scope
- **Yapılıyor:** SemanticMemory.recall() linear scan → indexed search
- **Yapılmıyor:** Full-text search engine, vector indexing

#### Pre-conditions
- [ ] 1000+ entries ile performans testi hazır
- [ ] Mevcut SQLite index'leri mevcut

#### Acceptance Criteria

| AC# | Kriter | Test Metodu | Success Condition |
|-----|--------|------------|-------------------|
| AC-60-01 | recall() < 100ms (1000 entries) | Performance test | `timeit` ≤ 0.1s |
| AC-60-02 | SQLite FTS kullanımı | Code review | `CREATE VIRTUAL TABLE` veya `LIKE` optimizasyonu |
| AC-60-03 | Linear scan'ın %10'u zaman | Performance test | Index search dominant |
| AC-60-04 | Query result correctness | Unit test | Index same as full scan |

#### Test Scenarios

```python
import time
import random
import string

# Scenario 1: Recall O(n) performance (FAIL CASE)
def test_recall_slow_fail():
    """
    FAIL: 1000 entries ile recall 2 saniye sürüyor.
    
    Expected: < 100ms
    """
    memory = SemanticMemory(db_path=":memory:")
    
    # Insert 1000 entries
    for i in range(1000):
        subject = f"entity_{i}_{random.choice(['a','b','c'])}"
        memory.add(subject=subject, predicate="related_to", object="test")
    
    # Benchmark recall
    start = time.perf_counter()
    results = memory.recall("entity_a")
    elapsed = time.perf_counter() - start
    
    assert elapsed < 0.1, f"Recall took {elapsed:.3f}s, expected < 0.1s"


# Scenario 2: Index used for search
def test_recall_uses_index():
    """SQLite query plan index kullanıyor."""
    conn = sqlite3.connect(memory.db_path)
    conn.row_factory = sqlite3.Row
    
    # EXPLAIN QUERY PLAN
    cur = conn.execute("SELECT * FROM semantic_entries WHERE subject LIKE '%test%'")
    plan = cur.fetchall()
    
    # Should use index if available
    # assert "INDEX" in str(plan)
    conn.close()


# Scenario 3: Recall correctness
def test_recall_correctness():
    """Index search = Full scan search."""
    memory = SemanticMemory(db_path=":memory:")
    memory.add("apple", "is_a", "fruit")
    memory.add("banana", "is_a", "fruit")
    memory.add("carrot", "is_a", "vegetable")
    
    results = memory.recall("fruit")
    
    assert len(results) == 2
    assert all("fruit" in r.predicate for r in results)
```

#### Rollback Plan
- [ ] `git revert`
- [ ] Full scan'a geri dön (n tolerans kabul edilebilir)

#### Dependencies
- SemanticMemory.recall()
- SemanticMemory.query()

---

## UAT Rapor Formatı

Her feature完成后 şu rapor hazırlanır:

```markdown
## Feature: [Issue #XX - Başlık]

**Test Edildi:** 2026-04-19
**Tester:** [agent name]
**Sonuç:** ✅ PASS / ❌ FAIL

### Detaylar

| AC# | Sonuç | Not |
|-----|-------|-----|
| AC-XX-01 | ✅ PASS | 10/10 test geçti |
| AC-XX-02 | ❌ FAIL | Timeout 2s, beklenen <100ms |

### Fail Durumları

1. **[AC-XX-02]** — Detaylı açıklama
   - Log: `...`
   - Stack trace: `...`
   - Workaround: `...`
```

---

## Notes

- UAT sheet'ler feature branch'inde ayrı dosyada tutulabilir
- Test scenario'ları `tests/uat/` klasörüne pytest olarak yazılabilir
- Rik (chief agent) final report'u Vahit'e sunar