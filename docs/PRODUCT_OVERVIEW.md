# Rik Context Engine — Ürün Anlatımı ve Kullanım Kılavuzu

> **Ne işe yarar, nasıl kullanırım?** — satış dili yok, sadece ne olduğunu ve nasıl çalıştığını anlatan doküman.
> **Versiyon:** v0.4.0 (staging doğrulamalı, 2026-08-21)
> **Okuyucu:** Ürün yöneticisi / operatör — "bunu alıp ne yaparım" sorusunu cevaplar.

---

## 1. Ne İşe Yarar? (Tek Cümle)

**AI agent'larına kalıcı, hiyerarşik bir hafıza verir — böylece oturumlar arası unutmazlar ve öğrenirler.**

Tekrar eden sohbeti, "bana kullanıcıyı hatırlat" talebini, "şu raporu yaz" işini tek seferde yapar ve bir sonraki oturumda **hâlâ hatırlar**.

---

## 2. Çözdüğü Sorun

| Sorun | Rik Context Engine çözümü |
|-------|---------------------------|
| Her AI oturumu sıfırdan başlar | **Episodic + Semantic + Procedural** katmanlarla uzun süreli hafıza |
| Context window büyüdükçe "kaybolan" bilgi | **Önem puanlama** + **akıllı budama** (low-importance içeriği önce atar) |
| "Neler oldu" vs "ne önemli" ayrımı yok | 3 katmanlı mimari (insan hafızası taklidi) |
| Oturumlar arası sıfır öğrenme | **Consolidation**: episodic → semantic → procedural |
| Aynı veriyi her seferde tekrar girme | **Import/Export**: oturumları dışarı alıp geri yüklenebilir |

---

## 3. Mimari — 3 Katman (İnsan Hafızası Taklidi)

```
📝 Episodic Memory          "Ne oldu?" — oturum anlık, yüksek sadakat
      ↓ consolidate
🧩 Semantic Memory          "Ne biliyorum?" — yapılandırılmış bilgi (SQLite)
      ↓ proceduralize
⚙️ Procedural Memory        "Nasıl yaparım?" — beceriler, iş akışları
```

- **Episodic:** Oturum snapshot'ları, konuşma öne çıkanları, geçici vakıalar
- **Semantic:** Uzun süreli yapılandırılmış bilgi + vektör araması (ChromaDB)
- **Procedural:** Beceri, iş akışı, how-to bilgisi

---

## 4. Nasıl Kullanırım? (3 Yol)

### 4.1. Python API (en hızlı başlangıç)

```bash
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```python
from riks_context_engine.memory import EpisodicMemory, SemanticMemory, ProceduralMemory

# Episodic — oturum hafızası
em = EpisodicMemory()
em.add("Vahit teknik tartışmayı İngilizce tercih eder", importance=0.9, tags=["tercih"])
em.add("Auth service timeout sorunu JWT validasyonuna izlendi", importance=0.8)
print(em.query("JWT")[0].content)

# Semantic — uzun süreli bilgi
sm = SemanticMemory()
sm.add("auth_service", "kullanıyor", "JWT RS256", confidence=1.0)
sm.add("auth_service", "token_sure", "1 saat")
print(sm.query(subject="auth_service"))
```

### 4.2. HTTP API (agent'lar / istemciler)

Docker compose ile staging ortamı:

```bash
docker compose -f docker-compose.staging.yml --profile staging up -d
# http://127.0.0.1:8001
```

| Endpoint | Ne yapar |
|----------|----------|
| `POST /api/chat` | Chat + context wiring (memory'deki bilgi prompt'a bindirilir) |
| `POST /api/v1/memory/import` | Memory'ye dışarıdan veri yükle (JSON manifest) |
| `GET  /api/v1/memory/export` | Memory'yi dışarı al (JSON manifest, id korunur) |
| `POST /api/v1/context/messages` | Context'e mesaj ekle (özellikle UI'lar için) |
| `GET  /health` | Sağlık kontrolü |

**Güvenlik:** Tüm endpoint'ler `X-API-Key` ile fail-closed (anahtar yoksa 401). Tenant izolasyonu: `X-Tenant-Id` ile tenant başına ayrı memory pool.

### 4.3. CLI (ops / bakım)

```bash
scripts/staging.sh status      # staging durumu
scripts/staging.sh smoke       # smoke test (health + auth + export)
scripts/staging.sh logs        # logları tail et
scripts/staging.sh test        # staging'e karşı test
```

---

## 5. Staging'de Doğrulanmış Davranış (2026-08-21)

Canlı test (staging 8001, 510 request, 66 sn):

| Test | Sonuç |
|------|-------|
| 150× GET export (auth + roundtrip) | 150/150 doğru, id'ler korunur |
| 150× POST import (no-dup, idempotency) | 150/150 imported=3 |
| Tenant izolasyonu (A → B sızıntısı) | count=0 (izolasyon sağlam) |
| 50× POST chat (multi-turn) | 50/50 response |
| 10× no-key export (fail-closed auth) | 10/10 401 |
| **Ürünün kalbi — context wiring** | Model, import edilmiş "Ben Vahit" episodic'sini kullanarak "Adın ne" diyor (ECHO MODE ölü) |

**Sonuç:** Ürün amacına uygun çalışıyor.

---

## 6. Hangi Durumda Kullanırım? (Pratik Senaryolar)

1. **Kişisel asistan:** Vahit'in "Ben DevSecOps mühendisiyim" bilgisi bir kez import edilir, sonraki tüm oturumlarda "Benim rolüm ne?" sorusuna doğru cevap verir.
2. **Proje hafızası:** Bir sprint boyunca "X servisinde JWT timeout izlendi" episodic olarak yazılır, sonraki sprintte otomatik olarak prompt'a girer.
3. **Raporlama:** Haftalık "bu hafta neler oldu?" sorusu → episodic export → dışarıda (LLM'e) işlenir, sonuç tekrar import edilir.
4. **Multi-tenant SaaS:** Her tenant'ın verisi ayrı pool'da (`X-Tenant-Id` ile), tenant A verisi B'ye asla sızamaz (test kanıtlı).

---

## 7. Bilinmeyen / Açık Konular

- **LLM provider entegrasyonu:** Şu an `LLM_PROVIDER_URL` set değil → deterministik stub kullanılıyor. Gerçek LLM'e (gemma-31b, qwen, vb.) bağlamak için env set edilmeli.
- **WebSocket streaming (`/ws/v1/context/stream`):** Endpoint mevcut, canlı testte connect + subscribe ACK alıyor, **ama authsuz connect kabul ediliyor** (P1 adayı). #170 turunda veya ayrı P1 ile ele alınacak.
- **CD pipeline:** GHA org-package write yetkisi henüz çözülmüş değil → staging deploy manuel (Rik tarafından). PAT_GHCR fix'i bekleniyor.
- **Production deploy:** Henüz yok. Staging doğrulamalı, prod'a geçiş #176 sonrası planlanacak.

---

## 8. Bağlantılar

- **API referansı:** `docs/API.md`
- **Mimari:** `docs/ARCHITECTURE.md`
- **Kullanıcı kılavuzu (detaylı):** `docs/USER_GUIDE.md`
- **Hızlı başlangıç:** `docs/QUICKSTART.md`
- **Deploy:** `docs/DEPLOYMENT.md`
- **Test ortamı:** `docs/TEST_ENVIRONMENT.md`

---

*Bu doküman "teklif" değildir — ne işe yaradığını ve nasıl kullanılacağını anlatır. Satış dili yoktur.*
