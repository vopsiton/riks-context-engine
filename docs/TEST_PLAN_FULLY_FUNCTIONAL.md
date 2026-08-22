# Test Plan — "Tam Anlamıyla Çalışıyor" Kriteri

> **Issue:** #188 | **Talep:** Vahit, 2026-08-21 22:32 (+03): "Projeyi tam anlamıyla
> çalışır hale getirecek testleri dahil plan yap."
>
> Bu dokümanın tek amacı: **hangi testler geçtiğinde "bu proje TAMAMEN
> ÇALIŞIYOR" diyebileceğimiz** kriterini tanımlamak. Satış dili yok — yalnızca
> kanıtlanan davranış, eksik test ve engeller.
>
> Güncelleme: 2026-08-21 (staging 510-request doğrulamasından sonra)

---

## 0. Özet

| Katman | Mevcut test sayısı | Durum |
|---|---|---|
| Unit (tests/ kökü + modül) | ~500+ (724 toplam `def test`) | ✅ CI'da her PR'da çalışıyor (`ci.yml`, `--cov=src/`) |
| Integration (tests/test_api/, tests/ui/) | ~140 (TestClient, real-LLM gerektirmez) | ✅ CI'da çalışıyor |
| E2E CI (in-app, #166/#167/#168/#169 serisi) | 69 test (auth 9, roundtrip 13, id-preservation 3, tenant-scoping 13, audit 14, context-window 10, WS 20 — WS tarafı henüz gerçek e2e değil, model/test seviyesi) | ✅ CI'da |
| E2E Staging (canlı HTTP + Ollama) | 510-request doğrulama seti (2026-08-21) | ✅ Manuel/staging smoke olarak kanıtlı, CI'a taşınmadı |
| E2E eksik seri (#170–#176) | 0 (dispatch edilmedi) | ⏳ |
| Production | 0 | 🚫 deploy yok |

**Toplam: 724 test fonksiyonu, hepsi CI'da çalışır durumda** (son commit'te yeşil CI
varsayımı — `ci.yml` her PR'da `pytest --cov=src/` çalıştırıyor).

---

## 1. Mevcut Test Durumu

### 1.1 Katman dağılımı (dosya bazında)

- **Unit:** `test_context.py` (41), `test_memory.py` (39), `test_tool_calling.py` (39),
  `test_context_manager.py` (32), `test_export.py` (31), `test_summarizer.py` (28),
  `test_mcp.py` (30), CLI seti (~43), `test_decomposer`/`test_embedding`/`test_graph`
  /`test_reflection*`/`test_kg_fallback`/`test_tier*`/`test_backup_integrity` vb.
- **Integration (TestClient, HTTP yüzeyi):**
  - `tests/test_api/test_api.py` (19) — endpoint baz kontrolü
  - `tests/test_api/test_openapi.py` (15) — spec bütünlüğü
  - `tests/ui/test_ui.py` (3) — UI yüklenmesi + health + models
  - `tests/test_api/test_websocket_streaming.py` (20) — **dikkat:** bu dosya
    `WSClientMessage`/`WSContextUpdate` modelleri ve `WebSocketContextStreamer`
    sınıfı üzerindeki testler (in-memory streamer). `/ws/v1/context/stream`
    endpoint'ine **HTTP/WebSocket üzerinden gerçek connect + auth'lu e2e yok**
    (bkz. #170).
- **E2E CI (in-app, gerçek LLM gerektirmez):**
  - `tests/e2e/test_auth.py` (9) — #166: auth matrisi + tenant izolasyonu + 100
    rastgele key → 401; **staging smoke varyantı da içeriyor**
    (`test_staging_auth_matrix`, `test_staging_chat_real_llm` — `E2E_API_KEY` +
    gerçek staging instance set olduğunda gerçek HTTP/LLM ile çalışır).
  - `tests/test_api/test_memory_roundtrip_e2e.py` (13) — #167: export→import
    roundtrip, tenant izolasyonu, format stability.
  - `tests/test_api/test_memory_import_id_preservation_e2e.py` (3) — id preservation.
  - `tests/test_api/test_memory_tenant_scoping_e2e.py` (13) — #184: export/import
    tenant-scoping.
  - `tests/test_api/test_audit_log_e2e.py` (14) — #169: write/read, append-only,
    filtering, tenant izolasyonu.
  - `tests/test_api/test_context_window_manager_e2e.py` (10) — #168: truncation,
    tenant scoping, context-aware reply (stub).
  - `tests/test_chat_memory_e2e_158.py` (6) — #158: multi-turn context wiring.
- **Güvenlik/güç testi (unit seviyesinde ama e2e niteliğinde):**
  `test_sql_injection.py` (13), `test_rate_limit.py` (19), `test_tenant_isolation.py`
  (19), `test_access_audit.py` (13), `test_metrics.py` (6), `test_cors_patch_head.py`
  (6), `test_recall_performance.py` (3), `test_semantic_concurrency_163.py` (4),
  `test_orphan_thread_151.py` (9), `test_k8s_manifests.py` (18).

### 1.2 Açık e2e issue'ları (dispatch edilmemiş, hâlen `open`)

```
#170 test: WebSocket /ws/v1/context/stream e2e — subscription + yayın + disconnect [P2]
#171 test: /metrics — Prometheus format + counter artış doğrulaması [P2]
#172 test: /models + model routing e2e — model seçimi gerçekten LLM'i değiştiriyor mu [P2]
#173 test: rate limiting e2e — 429 + Retry-After, per-tenant, /health muafiyeti [P2]
#174 test: CORS e2e — origin allow/deny + preflight (OPTIONS) [P2]
#175 test: UI / (index.html) e2e — load + API connect + temel interaksiyon [P2]
#176 test: load test — concurrent users, p95 latency, hata oranı [P2]
```

Bu issue'ların hiçbiri için test kodu repo'da yok; hepsi `tests/e2e/` altına
yazılacak yeni e2e setleri.

---

## 2. Staging'de Doğrulanmış Davranışlar (2026-08-21, 510 request / 66 sn)

Canlı staging instance'ında (gerçek HTTP, gerçek container, tüm fazlar yeşil)
kanıtlanan davranışlar. Bunlar planın **✅ Mevcut** satırlarının delili.

| # | Senaryo | Doğrulama | Katman | Öncelik | Durum |
|---|---|---|---|---|---|
| S1 | 150× GET `/api/v1/memory/export` — auth + export→import roundtrip, id preservation | 150/150 200; export edilen id'ler import'tan sonra birebir aynı (id preservation) | E2E Staging | P0 | ✅ Staging'de kanıtlı (CI karşılığı: #167 + id-preservation e2e'leri CI'da) |
| S2 | 150× POST `/api/v1/memory/import` — no-dup + idempotency | 150/150 200; aynı manifest'i tekrar import → kayıt sayısı artmaz (idempotent) | E2E Staging | P0 | ✅ Staging'de kanıtlı (CI karşılığı: roundtrip e2e no-data-loss; **staging smoke CI'a taşınmadı** → ⏳ kısmi) |
| S3 | Tenant izolasyonu — A'nın verisi B'ye sıfır sızıntı | A manifest'ini B import edince B'nin export'u değişmedi; A→B sızıntı = 0 | E2E Staging | P1 | ✅ Staging'de kanıtlı + CI'da (#166, #168, #184, #169 tenant testleri) |
| S4 | 50× POST `/api/chat` — multi-turn context wiring | 50/50 200; önceki turn'ların context'te kullanıldığı (wiring) kanıtlandı | E2E Staging | P0 | ✅ Staging'de kanıtlı (CI karşılığı: #158 + #168) |
| S5 | 10× no-key export — fail-closed auth | 10/10 `401` (key yoksa erişim reddi; open-mode sadece `RIKS_ENV=local`) | E2E Staging | P1 | ✅ Staging'de kanıtlı + CI'da (#166 `test_no_key_401`, 100 random key) |
| S6 | **Ürünün kalbi — episodic hatırlama:** import edilmiş "Ben Vahit" episodiğiyle chat'e "Adın ne" denildi | Model, import edilmiş episodic içeriğini kullanarak "Vahit" dedi (deterministik stub'dan ECHO MODE değil, gerçek context wiring — episodik hatıranın cevapta kullanılması) | E2E Staging | P0 | ✅ Staging'de kanıtlı (CI karşılığı: `test_chat_reply_is_context_aware_not_echo_stub` — **ama CI tarafı stub LLM ile; gerçek LLM ile kanıtı staging'de**) |

> Not: S2 ve S6'nın "gerçek LLM" varyantı yalnızca staging'de (canlı Ollama)
> çalıştı; CI'daki eşdeğerler deterministik stub kullanır. Gerçek-LLM kanıtının
> CI/otomasyona taşınması aşağıdaki L1 testidir.

---

## 3. Test Planı — Eksikler ve Yeni Testler

Her satır: **Katman / Senaryo / Doğrulama / Öncelik / Durum**.
⏳ = test yazılmalı (dispatch edilecek) · 🚫 = önce fix/önce koşul gerekli.

### 3.1 LLM Provider Entegrasyonu

| Katman | Senaryo | Doğrulama | Önc. | Durum |
|---|---|---|---|---|
| Integration | **L1 — `LLM_PROVIDER_URL` set iken `/api/chat` gerçek LLM'i çağırır.** Şu an env set değil → deterministik stub (`server.py:840`: "real provider if LLM_PROVIDER_URL set, deterministic stub otherwise"). | `LLM_PROVIDER_URL` (Ollama `host.docker.internal:11434` veya vLLM `:8010`) set edilmiş staging instance'ta: (a) `POST /api/chat {"message":"Adın ne"}` + önceden import edilmiş "Ben Vahit" episodiği → cevap "Vahit" içerir VE stub çıktısından farklıdır (stub'un deterministik metni birebir gelmez); (b) mock provider'da (HTTP spy) prompt'un context block'unu içerdiğini assert et. | P0 | ⏳ Yazılmalı. S6 staging'de kanıtlı ama otomasyonda değil. `tests/e2e/test_auth.py::test_staging_chat_real_llm` iskelet zaten var (E2E_API_KEY+staging gerektirir) — genişletilmeli |
| Integration | **L2 — Provider erişilemezse graceful degradation (crash yok, log + stub fallback veya açık hata).** | `LLM_PROVIDER_URL=http://127.0.0.1:1` (ölü port) ile chat → 500 değil; tanımlı davranış (fallback veya 502/503 + error detail) tutarlı; `docker compose logs`'ta error log entry | P2 | ⏳ |
| Integration | **L3 — #172 `/models` + model routing: model seçimi gerçekten LLM'i değiştiriyor mu.** | `GET /api/models` → listede en az 1 model; `POST /api/chat {"model":"qwen3.5:9b"}` (Ollama) ile `{"model":"gemma4:31b"}` yanıt farklı model çıktısı üretir; mock provider'da `model` parametresinin provider'a geçtiği assert edilir. Bilinmeyen model → 400 (mevcut davranış, unit'te mevcut, e2e'si yok) | P2 | ⏳ (issue #172 open, test yazılmamış) |

### 3.2 WebSocket Streaming + Auth

> **Mevcut durum (kod inceleme):** `APIKeyAuthMiddleware` yalnız HTTP
> (`BaseHTTPMiddleware`) — WebSocket handshake'inde `X-API-Key` doğrulanmıyor.
> `websocket_context_stream` (server.py:649) `streamer.connect(websocket)` ile
> doğrudan accept ediyor; **authsuz connect kabul ediliyor** (P1 adayı, #170
> stalled). `tests/test_api/test_websocket_streaming.py`'daki 20 test in-memory
> `WebSocketContextStreamer` sınıfını test eder; endpoint'e gerçek WS handshake
> testi yok.

| Katman | Senaryo | Doğrulama | Önc. | Durum |
|---|---|---|---|---|
| E2E (CI) | **W1 — #170: authsuz WS connect reddedilir (403/close).** **FIX GEREKLİ, sonra test.** | Önce fix: `/ws/v1/context/stream` handshake'inde `X-API-Key` (+tenant) doğrula, geçersiz/eksik → close(4401) veya 403. Sonra test: `TestClient.websocket_connect` (a) key'siz → connection refused/403; (b) geçersiz key → aynı; (c) geçerli key → `subscribed` mesajı al, `{"type":"ping"}` → `heartbeat/pong`. | P1 | 🚫 Fix gerekli (auth middleware WS'yi kapsamıyor). Test sonrası ⏳→CI |
| E2E (CI) | **W2 — #170: subscription + yayın + disconnect.** Aynı tenant A'da chat turn'u tetiklediğinde, A'ya subscribe'li WS istemcisi `context_update` alır; B'ye subscribe'li istemci A'nın güncellemesini almaz (tenant izolasyonu WS'de de). | TestClient'la 2 WS client (A, B) → A'ya chat POST → A client `context_update` mesajı alır, B client almaz; A client kapatılınca `streamer._connections`'tan düşer (disconnect temiz) | P1 | ⏳ (issue #170 open) |
| E2E (Staging) | **W3 — Gerçek WS istemcisi (python `websockets` / `ws` CLI) staging instance'a connect, publish, cleanup.** CI TestClient'inin kapsamadığı gerçek frame seviyesi. | Staging'de: key'li connect → subscribe → chat tetikle → güncelleme frame'i al → kapat; log'da temiz disconnect entry'si | P2 | ⏳ (W1 fix'i + staging'de) |

### 3.3 e2e Serisi #170–#176 (dispatch edilmemiş)

| Katman | Senaryo | Doğrulama | Önc. | Durum |
|---|---|---|---|---|
| E2E (CI) | **M1 — #171: `/metrics` Prometheus format + counter artış.** | GET `/metrics` → Prometheus exposition format (satır baz parse: `name{labels} value`); 3 istek at → istek counter'ı en az 3 artar; hata yolları (401) da counter'a düşer | P2 | ⏳ (issue #171; `test_metrics.py` 6 unit testi var, e2e format/counter doğrulaması yok) |
| E2E (CI) | **R1 — #173: rate limiting e2e — 429 + Retry-After, per-tenant, `/health` muafiyeti.** | Limit aşıldığında 429 + `Retry-After` header; tenant A kısıtlıyken B etkilenmez; `/health` limit dışı (asla 429 değil) | P2 | ⏳ (issue #173; `test_rate_limit.py` 19 unit testi var — HTTP/middleware e2e'si yok) |
| E2E (CI) | **C1 — #174: CORS e2e — origin allow/deny + preflight.** | `ALLOWED_ORIGINS` içindeki origin'den `OPTIONS` preflight → 200 + doğru `Access-Control-Allow-*` headers; listede olmayan origin → CORS header'ı yok; `PATCH`/`HEAD` metotları (bkz. `test_cors_patch_head.py`) e2e'de de tutarlı | P2 | ⏳ (issue #174) |
| E2E (CI) | **U1 — #175: UI `/` (index.html) e2e — load + API connect + temel interaksiyon.** | GET `/` → 200 HTML (auth'lu tenant çağrısında export branch'i, auth'suzda UI — mevcut davranış `server.py` root handler'ında); UI'daki API çağrılarının (health/models) CORS+auth ile 200; Playwright seçeneği: sayfa yüklenir, health göstergesi "ok" görür | P2 | ⏳ (issue #175; `tests/ui/test_ui.py` yalnız 3 temel assert — gerçek browser/interaksiyon yok) |
| E2E (Staging) | **LD1 — #176: load test — concurrent users, p95 latency, hata oranı.** | Locust/k6 scripti (repo'ya `tests/load/` altına): N=20 concurrent × 2 dk mixed traffic (export/import/chat) → hata oranı < %1, p95 < tanımlı eşik (örn. chat 3s, export 500ms — eşik Vahit onaylı); sonuç raporu dokümana işlenir | P2 | ⏳ (issue #176; 510-request smoke'ın ölçeklenmiş hâli) |

### 3.4 Production Deploy + CD

| Katman | Senaryo | Doğrulama | Önc. | Durum |
|---|---|---|---|---|
| Production | **P1 — Production compose deploy smoke.** `docker-compose.prod.yml` ile başlat → `/health` 200, fail-closed auth açık (API_KEY required), veri `prod-data` volume'unda kalıcı (restart sonrası veri kaybolmaz). | `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` → health + no-key 401 + seed→restart→export aynı veri | P0 | 🚫 **Production deploy henüz yok** — `docker-compose.prod.yml` mevcut ama ilk prod ayağa kaldırma yapılmadı. Önce deploy, sonra test |
| Production | **P2 — K8s manifest doğrulaması canary.** `k8s/` manifestleri (deployment/service/hpa/configmap) gerçek cluster'da (ya da kind'de) ayağa kalkar; `kubectl get pods` Running, service health 200. | kind cluster'a `kubectl apply -f k8s/` → pod Ready + service üzerinden health | P1 | ⏳ (`test_k8s_manifests.py` 18 unit testi var — manifest schema/syntax; **canlı cluster testi yok**) |
| Production | **P3 — CD pipeline: GHA → GHCR org package publish (AC4, PAT_GHCR).** `cd.yml` pipeline'ı release tag'inde image'ı org GHCR package'ına push eder. | GHA secret `PAT_GHCR` set edilince: tag push → CI yeşil → GHCR'da `ghcr.io/vopsiton/riks-context-engine:<tag>` mevcut (`curl -s <PAT>@ghcr.io/v2/vopsiton/riks-context-engine/manifests/<tag>` 200). | P0 | 🚫 **Engel:** GHA org-package write yetkisi (PAT_GHCR) henüz set değil — set edilmeden test yazılsa da koşamaz. Env/secret seti → otomatik doğrulanır |
| Production | **P4 — Backup/restore prod verisiyle.** `test_backup_integrity.py` (17 unit) prod volume'unda: backup al → sil → restore → export birebir. | Staging/prod'da: `scripts/` backup → veri sil → restore → GET export = orijinal | P1 | ⏳ (unit mevcut; canlı volume testi yok) |

---

## 4. "TAMAMEN ÇALIŞIYOR" Kriteri

**Tek cümle:** Yukarıdaki **P0/P1 tümü yeşil** (L1, W1-fix+W1+W2, S1–S6 otomasyona
taşınmış hâlleri, P1 prod smoke, P3 CD publish) **ve CI'daki mevcut 724 testin
toplamda yeşil** olduğu noktada "bu proje TAMAMEN ÇALIŞIYOR" deriz.

### Checklist (merge/release kapısı)

- [ ] **C1 (P0):** `/api/chat`, `LLM_PROVIDER_URL` set (Ollama veya vLLM :8010), import edilmiş episodik hatırayla "Adın ne" → doğru isim (gerçek LLM, otomatik test — L1). Stub yok; gerçek model kanıtı CI/staging-gate'de.
- [ ] **C2 (P0):** Memory roundtrip 510-request seti (S1+S2: 150 export + 150 import, no-dup, idempotency, id preservation) **CI'da tekrarlanabilir** hâle geldi (staging smoke'u `cd.yml` staging job'una taşındı).
- [ ] **C3 (P1):** Auth: no-key/invalid-key → 401 (fail-closed), tenant A→B sızıntı = 0 — hem HTTP (mevcut, ✅) **hem WebSocket** (W1 fix + W1/W2 testleri) için kanıtlı.
- [ ] **C4 (P1):** WS streaming: authsuz connect reddi + subscribe/yayın/disconnect + WS tenant izolasyonu (W1, W2, opsiyonel W3).
- [ ] **C5 (P0):** Production smoke: `docker-compose.prod.yml` ayağa kalkar, `/health` 200, fail-closed auth, restart sonrası veri bütünlüğü (P1).
- [ ] **C6 (P0):** CD: GHCR org package publish (PAT_GHCR set + tag → `ghcr.io/vopsiton/riks-context-engine:<tag>` manifest 200) (P3/AC4).
- [ ] **C7 (P2):** e2e serisi #171–#176 dispatch edilmiş ve yeşil (M1, R1, C1, U1, LD1). *(P2 — "tamamen çalışıyor" için zorunlu değil ama release kalitesinin parçası.)*
- [ ] **C8:** `pytest --cov=src/` tam yeşil (724 test + yeni eklenenler), coverage regression yok.

> C1–C6 (P0/P1) = "TAMAMEN ÇALIŞIYOR" tanımlayıcısı. C7–C8 = kalite tamamlama
> (P2). C1–C6 geçmeden "üretimde hazır" denmez.

### Öncelik sırası (yapım planı)

1. **WS auth fix** (W1'in önkoşulu — P1 güvenlik, #170 stalled nedeni)
2. **L1 gerçek-LLM e2e** (P0 — ürünü "AI context engine" yapan şey)
3. **P3 CD/PAT_GHCR** (P0 — org yetkisi bekleniyor; env seti dışındaki kısım hazır)
4. **P1 prod smoke** (P0 — `docker-compose.prod.yml` ile ilk ayağa kaldırma)
5. **S1/S2 staging smoke'larının CI'ya taşınması** (P0)
6. **#171–#176 e2e serisi dispatch** (P2)

---

## 5. Kaynak / Kanıt İpuçları

- Staging kılavuzu: `docs/TEST_ENVIRONMENT.md` (overlay compose, `http://localhost:8001`, Ollama `host.docker.internal:11434`)
- Staging smoke iskeleti: `tests/e2e/test_auth.py` (`test_staging_auth_matrix`, `test_staging_chat_real_llm` — `E2E_API_KEY` + staging instance ile gerçek HTTP/LLM)
- LLM provider switch: `src/riks_context_engine/api/server.py` — `LLM_PROVIDER_URL` env; set değilse deterministik stub (docstring: "real provider if LLM_PROVIDER_URL set, deterministic stub otherwise")
- WS endpoint: `server.py:775` (`app.add_api_websocket_route("/ws/v1/context/stream", ...)`); auth middleware yalnız HTTP (`BaseHTTPMiddleware`) → WS handshake authsuz (P1)
- CI/CD: `.github/workflows/ci.yml` (pytest + cov), `cd.yml` (pytest + staging job), `deploy.yml`
- Açık e2e issue'ları: #170–#176 (hepsi `open`, P2 label)
- Production güvenlik notu: `SECURITY_AUDIT_PROD_DEPLOY.md` (BLOCKER-1: `network_mode: host` — prod deploy öncesi fix gerekli)
