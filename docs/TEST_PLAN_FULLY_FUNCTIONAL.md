# Test Plan — "Tam Anlamıyla Çalışır" Kriteri

> **Issue:** #188 · **Talep:** Vahit, 2026-08-21 22:32+03 — "Projeyi tam anlamıyla çalışır
> hale getirecek testleri dahil plan yap"
>
> **Amaç:** Bu doküman, "riks-context-engine TAMAMEN ÇALIŞIYOR" diyebilmemiz için
> geçmesi gereken testlerin tam listesidir. Satış dili yok. Her satır ya
> ✅ staging'de kanıtlanmış, ya ⏳ yazılması gereken bir test, ya da 🚫 önce fix
> gerektiren bir engeldir. Tablodaki P0/P1 satırlarının tamamı ✅'ye dönene kadar
> "tamamen çalışıyor" denemez.

---

## 1. Mevcut Test Durumu (2026-08-21 itibarıyla)

### 1.1 Test envanteri

| Konum | Dosya | Test sayısı | Katman |
|---|---|---|---|
| `tests/` (kök) | 37 dosya (context, memory, graph, embedding, sql_injection, tenant_isolation, rate_limit, backup_integrity, …) | ~11 600 satır kod | Unit / Integration |
| `tests/test_api/` | `test_api.py` (19), `test_audit_log_e2e.py` (14), `test_context_window_manager_e2e.py` (10), `test_memory_import_id_preservation_e2e.py` (3), `test_memory_roundtrip_e2e.py` (13), `test_memory_tenant_scoping_e2e.py` (13), `test_openapi.py` (15), `test_websocket_streaming.py` (20) | ~107 | Integration (TestClient) + e2e-style |
| `tests/e2e/` | `test_auth.py` (9) | 9 | E2E (gerçek HTTP) |
| `tests/ui/` | `test_ui.py` (3) | 3 | UI |

**Toplam:** 40+ test dosyası, ~11 700 satır test kodu.

### 1.2 E2E kapsamı — issue #170–#176 ile karşılaştırma

| Issue | Kapsam | Durum |
|---|---|---|
| #170 | WebSocket `/ws/v1/context/stream` e2e (subscription + yayın + disconnect) | ⏳ AÇIK — `tests/test_api/test_websocket_streaming.py` var ama **unit/TestClient seviyesi**; gerçek WS istemcisi + staging instance üzerinde doğrulanmadı. Authsuz connect problemiyle stalled (bkz. §3.2) |
| #171 | `/metrics` — Prometheus formatı + counter artışı e2e | ⏳ AÇIK |
| #172 | `/models` + model routing e2e — model seçimi LLM'i gerçekten değiştiriyor mu | ⏳ AÇIK |
| #173 | Rate limiting e2e — 429 + Retry-After, per-tenant, `/health` muafiyeti | ⏳ AÇIK (unit: `tests/test_rate_limit.py` var) |
| #174 | CORS e2e — origin allow/deny + preflight (OPTIONS) | ⏳ AÇIK (unit: `tests/test_cors_patch_head.py` var) |
| #175 | UI `/` (index.html) e2e — load + API connect | ⏳ AÇIK (temel: `tests/ui/test_ui.py` var, 3 test) |
| #176 | Load test — concurrent users, p95 latency, hata oranı | ⏳ AÇIK |

**Çıkarım:** Memory roundtrip / tenant scoping / import id-preservation / audit log /
context window manager e2e'leri **yazıldı ve staging'de kanıtlandı** (#168, #169,
#184 serisi). Geriye e2e serisi #170–#176 kaldı.

---

## 2. Staging'de Doğrulanmış Davranışlar (2026-08-21 canlı test)

**Koşul:** `./scripts/staging.sh start` (tek komut), API `http://localhost:8001`,
510 request / 66 sn, tüm fazlar yeşil.

| # | Faz | Sonuç | Katman | Durum |
|---|---|---|---|---|
| S1 | 150× GET `/api/v1/memory/export` — auth + roundtrip, id preservation | 150/150 200, id'ler korunuyor | E2E (staging) | ✅ |
| S2 | 150× POST `/api/v1/memory/import` — no-dup, idempotency | 150/150 200, dup yok | E2E (staging) | ✅ |
| S3 | Tenant izolasyonu — A'nın verisini B'den okuma | A→B sızıntı = **0** | E2E (staging) | ✅ |
| S4 | 50× POST `/api/chat` — multi-turn context wiring | 50/50 200, bağlam taşıyor | E2E (staging) | ✅ |
| S5 | 10× no-key export — fail-closed auth | 10/10 **401** (#166) | E2E (staging) | ✅ |
| S6 | **Ürünün kalbi:** "Ben Vahit" episodic'si import edildikten sonra `Adın ne?` → model "Vahit" diyor (ECHO MODE ölü) | Doğrulandı | E2E (staging) | ✅ |

S1–S6'nın her biri `tests/test_api/` altındaki e2e testlerin (id_preservation,
roundtrip, tenant_scoping) staging karşılığıdır. CI'da da yeşil.

---

## 3. Eksikler / Açık Konular

### 3.1 LLM provider entegrasyonu (P0)

`src/riks_context_engine/api/server.py:83` — `LLM_PROVIDER_URL` env varı set
edilirse gerçek provider'a (Ollama `/api/chat` ya da OpenAI-compatible) POST
gidiyor; **set değilse deterministik stub** çalışıyor. Staging smoke testi
(`docs/TEST_ENVIRONMENT.md`) Ollama'ya bağlanıyor ama:

- `.env.staging.example`'da **`LLM_PROVIDER_URL` yok** → staging şu an stub ile
  çalışıyor (S6 stub tarafından kanıtlandı, gerçek LLM değil).
- Gerçek LLM (gemma-31b / qwen / vLLM `:8010`) bağlandığında chat yolunun
  gerçekten çalıştığını gösteren test **yok**.
- Provider düşerse stub'a fallback davranışı `logger.warning` ile sessiz geçiyor —
  "stub modunda çalışıyorum" uyarısı API yanıtında görünmüyor (operasyonel risk).

### 3.2 WebSocket streaming authsuz (P1 — #170 stalled nedeni)

`app.add_api_websocket_route("/ws/v1/context/stream", websocket_context_stream)`
(server.py:775). Middleware'lar (API key + tenant) **HTTP middleware**'i; WebSocket
upgrade isteğinde çalışmıyor. Sonuç:

- **Authsuz connect kabul ediliyor** — kimse `ws://host/ws/v1/context/stream`
  açabilir ve context update'lerini dinleyebilir.
- Tenant izolasyonu WS'de yok (tenant B, A'nın event'lerini görebilir).
- #170'ın AC-2 (tenant izolasyonu) bu fix olmadan geçemez.

### 3.3 Production deploy (P0)

`docker-compose.prod.yml` mevcut ama **henüz production'da çalıştırılmadı**.
`SECURITY_AUDIT_PROD_DEPLOY.md`'deki iki BLOCKER'ın durumu:

- BLOCKER-1 `network_mode: host` → compose prod'da hâlâ host networking (fix
  gerektirebilir; staging bridge network kullanıyor).
- BLOCKER-2 auth → #110/#166 ile API key middleware geldi (fail-closed) ama
  production'da `API_KEY` + reverse proxy (TLS) kurulumu doğrulanmadı.

### 3.4 CD pipeline (P2, AC4)

`.github/workflows/cd.yml` GHA org-package'ine push ediyor; **org package write
yetkisi (`PAT_GHCR`) bekleniyor** → `docker push ghcr.io/...` başarısız olabiliyor.
Staging image'ı bu yüzden local build ile ayağa kalkıyor (staging.sh bunu
gösteriyor). Yetki gelene kadar "image registry üzerinden dağıtım" kanıtlanamaz.

### 3.5 E2E test serisi #170–#176 (P2)

§1.2'de listelendi. Hiçbiri dispatch edilmedi. #170 önce 3.2'yi gerektiriyor (🚫).

---

## 4. Test Planı

> **Durum sembolleri:** ✅ = mevcut ve staging'de kanıtlı · ⏳ = test yazılmalı ·
> 🚫 = önce fix gerekli (fix bitmeden test yazılmaz)

### 4.1 Unit

| ID | Katman | Senaryo | Doğrulama | Öncelik | Durum |
|---|---|---|---|---|---|
| U1 | Unit | `LLM_PROVIDER_URL` set iken Ollama-format yanıt (`{"message":{"content"}}`) parse ediliyor | `tests/`: `_default_llm_call` monkeypatch ile `urlopen` mock → content döner | P0 | ⏳ |
| U2 | Unit | OpenAI-compatible yanıt (`{"choices":[…]}`) parse ediliyor | U1'deki mock, OpenAI shape ile | P0 | ⏳ |
| U3 | Unit | Provider unreachable → stub'a fallback (warning log, crash yok) | mock `urlopen` exception fırlatır; stub cevabı gelir + `caplog`'da warning | P0 | ⏳ |
| U4 | Unit | WS authsuz connect → `streamer.connect` kabul ETMEZ (403/4403 close code) | Önce 3.2 fix; `WebSocketTestClient` authsuz connect → close; auth'lu → accept | P1 | 🚫 |
| U5 | Unit | WS tenant izolasyonu — B client'ı A'nın broadcast'ini almaz | Önce 3.2 fix; iki tenant'lı streamer, broadcast tenant filter'ı | P1 | 🚫 |
| U6 | Unit | Stub fallback'te yanıt metadata'ında `llm="stub"` işareti (operasyonel görünürlük) | Önce metadata ekleme fix; chat response field kontrolü | P2 | 🚫 |

### 4.2 Integration (CI, gerçek servisler)

| ID | Katman | Senaryo | Doğrulama | Öncelik | Durum |
|---|---|---|---|---|---|
| I1 | Integration | Gerçek LLM (gemma-31b, Ollama `:11434`) ile `/api/chat`: import edilmiş "Ben Vahit" episodic'sinden "Adın ne?" → "Vahit" (stub DEĞİL) | `LLM_PROVIDER_URL=http://host.docker.internal:11434/api/chat` + `OLLAMA_MODEL=gemma4:31b` ile integration test (CI'da Ollama service container'ı); yanıtın model çıktısı olduğunun kanıtı: stub'un üretemediği serbest metin + `llm="provider"` metadata | P0 | ⏳ |
| I2 | Integration | vLLM (`:8010`, OpenAI-compatible) ile aynı senaryo — provider-agnostik routing | `LLM_PROVIDER_URL=http://vllm:8010/v1/chat/completions` (CI service) | P1 | ⏳ |
| I3 | Integration | `LLM_PROVIDER_URL` set ama provider 404/500 → stub fallback + HTTP 503 DEĞİL (hizmet ayağı kalmaz), yanıtta stub işareti | I3: provider'a `httpx.MockTransport` 500 → chat 200 + stub content | P0 | ⏳ |
| I4 | Integration | `/metrics` Prometheus formatı: export/import/chat sonrası counter artış | `# HELP`/`# TYPE` satırları + `GET /metrics` iki okuma arası delta ≥ 1 (#171'in CI ayağı) | P2 | ⏳ |
| I5 | Integration | Model routing: `model` parametresi prompt'a işleniyor, bilinmeyen model 400 | `/api/chat` `model=gemma4:31b` vs `model=sahte` → 200 vs 400 (#172) | P2 | ⏳ |
| I6 | Integration | Rate limit: threshold aşımında 429 + `Retry-After`, per-tenant, `/health` muaf | N+1'inci istek 429; tenant A limitlenirken B 200; `/health` her zaman 200 (#173) | P2 | ⏳ |
| I7 | Integration | CORS: allowed origin → `Access-Control-Allow-Origin`, foreign origin → yok; OPTIONS preflight 200 + methods (#174) | `TestClient` origin header varyasyonları | P2 | ⏳ |

### 4.3 E2E (staging instance, gerçek HTTP/WS istemcisi)

| ID | Katman | Senaryo | Doğrulama | Öncelik | Durum |
|---|---|---|---|---|---|
| E1 | E2E | Memory export → import roundtrip, id preservation | ✅ S1 (150× 200) + `tests/test_api/test_memory_roundtrip_e2e.py` | P0 | ✅ |
| E2 | E2E | Import idempotency / no-duplicate | ✅ S2 (150× 200) + `test_memory_import_id_preservation_e2e.py` | P0 | ✅ |
| E3 | E2E | Tenant izolasyonu — A verisi B'den okunmaz | ✅ S3 (sızıntı=0) + `test_memory_tenant_scoping_e2e.py` | P0 | ✅ |
| E4 | E2E | Multi-turn chat context wiring | ✅ S4 (50× 200) + `test_context_window_manager_e2e.py` | P0 | ✅ |
| E5 | E2E | Fail-closed auth: API_KEY yok / yanlış key → 401 | ✅ S5 (10/10 401) + `tests/e2e/test_auth.py` | P1 | ✅ |
| E6 | E2E | **Kalp testi:** episodic import → `Adın ne?` → "Vahit" | ✅ S6 (stub ile) + I1 (gerçek LLM ile tekrar) | P0 | ✅ stub / ⏳ real-LLM |
| E7 | E2E | WS: subscribe → 3 context event sırayla ≤5 sn'de; authsuz connect REDDEDİLİR; B→A sızıntı yok; disconnect'te connection map temiz (leak yok); sağlıklı JSON'ya drop yok (close code belgeli) | `tests/e2e/test_ws_stream_e2e.py` + `websockets` klibi ile staging'e canlı bağlanma (#170; 3.2 fix sonrası) | P1 | 🚫 |
| E8 | E2E | UI `/` load + API connect + temel interaksiyon | Browser/playwright: index.html 200, `/health` çağrısı, bir chat round-trip görünür (#175) | P2 | ⏳ |
| E9 | E2E | Load: N concurrent user, p95 latency + hata oranı eşiği | `scripts/load-test.py` (kısasayıcı: 100 concurrent, 60 sn, p95 < 1s, hata < 1%) (#176) | P2 | ⏳ |

### 4.4 Production

| ID | Katman | Senaryo | Doğrulama | Öncelik | Durum |
|---|---|---|---|---|---|
| P1prod | Production | `docker-compose.prod.yml` ile prod ayağa kalkar; health 60 sn'de 200; `API_KEY` zorunlu (fail-closed); TLS reverse proxy (nginx) önünde | `scripts/prod.sh start` (yazılacak) + `curl -sf https://<host>/health` + authsuz istek 401 | P0 | 🚫 (BLOCKER-1 network_mode host kararı + API_KEY dağıtımı) |
| P2prod | Production | CD: GHA `PAT_GHCR` ile `ghcr.io/vopsiton/riks-context-engine:ci-<sha>` push + Trivy temiz + pull'edane staging'e çalışır | CD run log'unda `docker push` başarılı; `docker pull ghcr.io/...` staging'de 200 (AC4) | P1 | 🚫 (PAT_GHCR bekleniyor) |
| P3prod | Production | Backup/restore: `data/` snapshot → sil → restore → export verisi aynı (`test_backup_integrity.py`'in prod ayağı) | `scripts/backup.sh` + diff | P1 | ⏳ |
| P4prod | Production | Prod'da kalp testi (I1 senaryosu, gerçek model, gerçek veri) | Prod'a S6 akışı yeniden; "Vahit" cevabı | P0 | 🚫 (P1prod sonrası) |

---

## 5. "TAMAMEN ÇALIŞIYOR" Kriteri

**Tek cümle:** Gerçek LLM'e bağlı, auth'lu (HTTP + WebSocket), tenant-izole bir
instance'da import edilmiş episodic hafızadan sorulan soru doğru cevaplanıyorsa ve
bütün bu davranışlar CI + staging + prod üçgeninde tekrarlanıyorsa, proje tam
anlamıyla çalışıyor demektir.

### Checklist — hepsi yeşil olmalı

- [ ] **P0:** I1 + E6 — gerçek LLM (gemma-31b) ile kalp testi: "Ben Vahit" episodic'si import → `Adın ne?` → "Vahit", yanıtın stub olmadığı kanıtlı (provider metadata / serbest metin).
- [ ] **P0:** U1+U2+U3+I3 — provider parse (Ollama + OpenAI) ve fallback (provider ölürse hizmet ayakta, stub işareti var).
- [ ] **P0:** U4+U5+E7 — WebSocket authsuz connect red + tenant izolasyonu + clean disconnect (3.2 fix'li, #170 kapatıldı).
- [ ] **P0:** P1prod — production'da fail-closed auth + TLS reverse proxy ile canlı; P4prod prod kalp testi.
- [ ] **P0:** E1–E5 mevcut ✅'ler CI + staging'de her run'da yeşil (regresyon).
- [ ] **P1:** P2prod — CD `ghcr.io` push/pull (PAT_GHCR).
- [ ] **P2 (nice-to-have, "tamamen" için zorunlu değil):** I4–I7, E8, E9 (#171–#176 serisi), U6, P3prod.

**Kural:** P0'nun tümü + P1'in tümü ✅ ise "TAMAMEN ÇALIŞIYOR". P2, ürün kalitesini
ölçer ama eksikliği projeyi "çalışmıyor" yapmaz.

---

## 6. Sıralama Önerisi (kritik yol)

1. **3.2 WS auth fix** (P1) → #170 unblock → U4/U5/E7. *(en erken yapılmazsa E7 ve
   prod WS yüzeyi açık kalır)*
2. **LLM provider env + I1/I3** (P0) → stub'tan gerçek LLM'e geçiş, staging
   smoke test'i I1'i doğrular.
3. **Prod deploy (P1prod)** — WS auth + LLM provider hazır olduktan sonra.
4. #171–#176 e2e serisi (P2) — paralel dispatch edilebilir.
