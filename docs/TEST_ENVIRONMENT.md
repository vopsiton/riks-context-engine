# Test Environment — Staging First-Run Guide

> **Kopyala-çalıştır kılavuz.** Staging'i sıfırdan ayağa kaldırıp doğrulamak için
> adım adım komutlar. Bu doküman sadece "komutlar çalışsın" der; kapsamlı
> onboarding dokümanı ayrı (issue #160).

## Overview

Staging, base `docker-compose.yml` üstüne **overlay** olarak çalışır
(`docker-compose.staging.yml` standalone DEĞİLDİR — tek başına `up` edemez):

```
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

- **API:** `http://localhost:8001` (konteyner içi 8000 → host 8001'e yayımlanır)
- **ENV:** `ENVIRONMENT=staging`, `TEST_MODE=true`, `LOG_LEVEL=DEBUG`
- **LLM:** Ollama'ya `host.docker.internal:11434` üzerinden ulaşır
  (compose overlay `extra_hosts: host.docker.internal:host-gateway` ekler)
- **Veri:** `staging-data` named volume (stop'ta silinmez; `--volumes` kullanılmaz)

## Önkoşullar (requirements)

| Gereksinim | Kontrol komutu |
|---|---|
| Docker + Compose v2 (plugin) | `docker compose version` |
| `curl` | `command -v curl` |
| Hostta çalışan Ollama (LLM smoke test için) | `curl -sf http://localhost:11434/api/tags` |
| Repo kök dizininde çalışmak | `pwd` → repo root |

> Not: Legacy `docker-compose` binary'si **gerekli değildir**. Scriptler
> `docker compose` plugin'ini kullanır; yoksa `docker-compose`'a fallback eder.

## Adım adım (step-by-step)

```bash
# 1. Repo köküne git
cd /path/to/riks-context-engine

# 2. .env.staging'ı oluştur (ilk kurulumda; repo'da örnek checked-in)
cp .env.staging.example .env.staging
# İsteğe bağlı: OLLAMA_MODEL değeri, hosttaki yüklü modelle eşleşsin mi
# kontrol et (aşağıdaki smoke test bunu doğrular).

# 3. TEK KOMUTLA staging'i başlat (idempotent; health 60 sn içinde 200 döner)
./scripts/staging.sh start

# 4. Durum kontrolü
./scripts/staging.sh status
```

**Beklenen çıktı (adım 3):**

```
==> Starting staging environment (API: http://localhost:8001)...
==> Waiting for staging to be healthy...
✓ Staging is healthy at http://localhost:8001
```

**Beklenen çıktı (adım 4):**

```
=== Staging Status ===
Container: RUNNING
  Image: riks-context-engine:staging
  Ports: 0.0.0.0:8001->8000/tcp
  Status: Up ... (healthy)

API Health: {"status":"ok", ...}
```

## LLM smoke testi (staging'den gerçek Ollama yanıtı)

```bash
# .env.staging'deki model adı
MODEL=$(grep '^OLLAMA_MODEL=' .env.staging | cut -d= -f2)

# Staging'e gerçek chat isteği (X-Tenant-Id header'ı zorunlu — tenant scoping, #102)
curl -sf http://localhost:8001/api/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: smoke-157' \
  -d "{\"message\": \"Tek cümleyle kendinden bahset.\", \"model\": \"$MODEL\"}"
```

**Beklenen:** `200` + `response` alanında model etiketli LLM metni. Bu smoke
istek, konteynerin API'ye (ve dolayısıyla OLLAMA_HOST'unun konteyner içinden
çözülebilen bir host'a — `host.docker.internal`) ulaştığının kanıtıdır.

**Gerçek Ollama çağrısı için ek adım:** Host Ollama'yı `0.0.0.0`'a dinlet
(varsayılan `127.0.0.1` sadece host-local erişim verir; konteynerden
`host.docker.internal:11434` bağlantısı `Connection refused` döner):

```bash
# /etc/systemd/system/ollama.service (veya systemd drop-in)
Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl daemon-reload && sudo systemctl restart ollama

# Konteyner içinden doğrula:
docker exec riks-context-engine-staging \
  python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:11434/api/tags', timeout=3).status)"
# Beklenen: 200
```

> Not: riks-context-engine'in `/api/chat` endpoint'i şu an echo modunda
> (context engine entegrasyonu ayrıca geliyor); gerçek LLM yanıtı,
> Ollama host-erişimi aktif olduğu anda bu endpoint üzerinden alınır.

## API endpointleri

**Base URL:** `http://localhost:8001`

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `/` | GET | API health check | None |
| `/health` | GET | Detailed health status | None |
| `/api/chat` | POST | LLM chat (Ollama smoke testi) | None (local) |
| `/context` | POST | Submit a context object | None (local) |
| `/context/<id>` | GET | Retrieve context by ID | None (local) |
| `/memory/search` | POST | Semantic memory search | None (local) |
| `/memory/history` | GET | Episodic memory history | None (local) |

## Test suite'i staging'e karşı çalıştırma

```bash
# Sadece health bekle (staging çalışıyorsa)
./scripts/test-staging.sh --wait

# Test suite'ini staging'e karşı koş (başlat → test → teardown)
./scripts/test-staging.sh
```

Sonuçlar `test-results/` altında:

```
test-results/
├── staging-results.xml   # JUnit XML (CI/CD compatible)
└── staging-report.html   # HTML report
```

> `STAGING_API_URL` scriptler tarafından `.env.staging` dosyasından okunur
> (default `http://localhost:8001` — staging portu; dev portu 8000 DEĞİL).

## Teardown

```bash
# Staging'i durdur (staging-data volume korunur; #159 persistence işi)
./scripts/staging.sh stop

# Tam sıfırlama (verilerle birlikte)
docker compose -f docker-compose.yml -f docker-compose.staging.yml down --volumes
```

## Hata tablosu (troubleshooting)

| Belirti | Muhtemel neden | Çözüm |
|---|---|---|
| `docker-compose: command not found` | Legacy binary yok | Scriptler otomatik `docker compose` kullanır; elle koşuyorsan: `docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d` |
| `staging: no such service` | Overlay tek başına çalıştırıldı | İKİ `-f` birden: `-f docker-compose.yml -f docker-compose.staging.yml` |
| Health 60 sn içinde 200 değil | Container start oluyor ama app boot slow | `./scripts/staging.sh logs` ile son logları incele; Ollama boot gecikmesi normaldir |
| `/api/chat` `Connection refused` (host Ollama) | (1) Ollama hostta çalışmıyor, **VEYA** (2) Ollama `127.0.0.1`'e dinliyor (varsayılan) — konteynerden erişilemez | `curl http://localhost:11434/api/tags` ile hosttan doğrula; konteynerden erişim için Ollama'yı `0.0.0.0`'a dinlet: `Environment="OLLAMA_HOST=0.0.0.0:11434"` + `sudo systemctl restart ollama` (detay: LLM smoke testi bölümü) |
| `/api/chat` model not found | `OLLAMA_MODEL` hostta yüklü değil | `ollama pull $MODEL` veya `.env.staging`'de yüklü bir modele çevir |
| `OLLAMA_HOST=localhost` konteyner içi fail | `.env.staging` eski değeri kullanıyor | `.env.staging`'de `OLLAMA_HOST=http://host.docker.internal:11434` olmalı (host.docker.internal konteynerde host'u gösterir) |
| 8001 portu dolu | Başka bir servis 8001'i kullanıyor | `ss -tlnp \| grep 8001` ile kontrol et; staging'i `stop` et veya portu değiştir |
| `Permission denied` (volume) | Named volume sahiplik sorunu | `docker volume inspect riks-context-engine_staging-data`; gerekirse `down --volumes` ile sıfırla |

## Environment variables (özet)

`.env.staging` içinde kritik değişkenler:

| Variable | Değer | Not |
|----------|-------|-----|
| `ENVIRONMENT` | `staging` | Sabit |
| `TEST_MODE` | `true` | Test endpointleri açar |
| `STAGING_API_URL` | `http://localhost:8001` | **Host-side** URL (scriptler okur) |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | **Konteyner-içi** Ollama URL (host-gateway) |
| `OLLAMA_MODEL` | (yüklü model) | Hosttaki Ollama modeline eşleşmeli |
| `LOG_LEVEL` | `DEBUG` | Staging'de debug log |
