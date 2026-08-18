# Rik Context Engine — Kullanım Kılavuzu

> *Bu kılavuz teknik dokümantasyon değil. Sanki bir arkadaşına "şu ne işe yarıyor, nasıl kullanırım" diye anlatıyormuş gibi yazıldı. Kod detayları için [API dokümantasyonu](./API.md)'na, mimari için [ARCHITECTURE.md](./ARCHITECTURE.md) dosyasına bak.*

---

## Bir dakikada ne işe yarıyor?

Kısa sohbetler yaparsın, yapar yapmaz unutursun. Bir hafta sonra aynı soruyu sorduğunda asistan "seni tanımıyorum" modunda baştan başlar.

Rik Context Engine bu soruna karşılık geliştirildi: **AI ajanlarına kalıcı, katmanlı bir hafıza** verir. Ajan bir kere öğrendiği şeyi bir daha öğrenmek zorunda kalmaz.

Bunu insan beyninin yaptığı gibi yapar — üç katman:

1. **Olay hafızası (episodic):** "Bu hafta ne oldu?" — oturum bazlı, kısa ömürlü, canlı.
2. **Anlamsal hafıza (semantic):** "Bu kişi/proje hakkında ne biliyorum?" — kalıcı, yapılandırılmış, aramalara açık.
3. **Yordamsal hafıza (procedural):** "Bu iş nasıl yapılır?" — beceriler, iş akışları, "şunu yapınca şunu da yap" bilgisi.

Bunlara ek olarak **bilgi grafiği** (kişiler/projeler/kavramlar arası ilişkiler) ve **görev ayrıştırma** (büyük hedefi küçük adımlara bölmek) vardır.

---

## Kim için?

- **Kendi AI asistanını geliştirenler:** OpenClaw, LangChain, oturma odasındaki o chatbot — hepsi bu kütüphaneyi bir "hafıza katmanı" olarak kullanabilir.
- **Çok oturumlu sistemler kurdukları:** Aynı kullanıcı farklı cihazlardan/oturumlardan geldiğinde tutarlılık istiyorsa.
- **Ajan tabanlı iş akışları:** Görevleri küçük adımlara bölüp izlemek isteyenler.

---

## Kurulum (2 dakika)

### Python (yerel)

```bash
git clone https://github.com/vopsiton/riks-context-engine.git
cd riks-context-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Çalıştığını görmek için:

```bash
python -c "from riks_context_engine import *; print('OK')"
```

### Docker

```bash
docker-compose up dev
docker-compose exec dev python -c "from riks_context_engine import *; print('OK')"
```

### Yapılandırma (isteğe bağlı)

Vektör araması ve göreve dayalı LLM için Ollama gerekir:

```bash
# Ollama kurulu değilse:
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4-31b-q4   # varsayılan model
```

Yapılandırma `.env` dosyasından yapılır:

| Değişken | Varsayılan | Ne işe yarar |
|----------|-----------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Embedding + LLM sunucusu |
| `OLLAMA_MODEL` | `gemma4-31b-q4` | Görev ayrıştırma için LLM |
| `CHROMA_HOST` | `localhost` | Vektör araması |
| `DATA_DIR` | `/app/data` | Verilerin nereye yazılacağı |

---

## Beş dakikada ilk kullanım

Bir Python oturumunda:

```python
from riks_context_engine.memory import EpisodicMemory, SemanticMemory
from riks_context_engine.context import ContextWindowManager

# 1) Bir hatıra ekle
hafiza = EpisodicMemory()
hafiza.add("Vahit teknik tartışmalarda Türkçe istiyor", importance=0.9)

# 2) Bir bağlam penceresi aç
ctx = ContextWindowManager(max_tokens=50_000)
ctx.add("user", "Prod'a deploy ediyoruz", importance=0.8, is_grounding=True)
ctx.add("assistant", "Tamam, önce staging testleri kontrol edeyim.")

# 3) Özetini al
print(ctx.get_summary())
```

Bu kadar. Geri kalanı aşağıda.

---

## Üç katman — pratikte ne anlama geliyor?

### Olay hafızası (episodic)

Bir oturumda olan biteni kaydetmek için. "Bugün Vahit'le deploy tartıştık, karar şu oldu" gibi.

- Oturum bitince kendiliğinden arşivlenir, silinmez.
- Önem derecesiyle birlikte tutulur (`importance=0.9` gibi) — düşük önemliler birikince birleştirilir.
- JSON dosyada tutulur (`data/episodic.json`), el ile açılıp okunabilir.

### Anlamsal hafıza (semantic)

Kalıcı bilgileri tutar: "X projesi Y teknolojisini kullanıyor", "Z kullanıcısı solak".

- SQLite + ChromaDB ile birlikte çalışır; hem yapılandırılmış sorgu hem vektör arama yapılabilir.
- `subject → predicate → object` formunda tutulur. Yani "Vahit → tercih ediyor → Türkçe" gibi.
- `SemanticMemory.query("Türkçe tercih")` gibi çağrılar hem eşleşmeyi hem de benzerlik vektörünü döndürür.

### Yordamsal hafıza (procedural)

"Nasıl yapılır" bilgisi. "Prod'a deploy için önce staging'e at, sonra health check yap" gibi.

- Bir beceri adı, adım listesi ve başarı oranıyla tutulur.
- Yeni bir görev açılırken "daha önce bu ne kadar iyi geçti" bilgisiyle birlikte sunulur.

---

## Bağlam penceresi: "Ajan çok şey konuşunca ne olur?"

Bu, kütüphanenin asıl varlık sebebini anlatan kısım.

Bir ajan bir konuşmada yüzlerce mesaj biriktirir. LLM'in context window'u doldukça eskileri kesilir — ve çoğu zaman kesilen şey *tam da önemli olan kısımdır.*

**ContextWindowManager** bunu akıllıca yapar:

1. Her mesaja bir **önem skoru** verir (kullanıcı adı geçti mi, karar verildi mi, araç sonucu mu, yeni bilgi mi).
2. Skoru düşük olanları **önce** keser, önemli olanları korur.
3. Kesimden sonra bağlamanın **tutarlı** kaldığını doğrular (paragraf ortasında kopma yok).
4. Dört öncelik katmanı kullanır:
   - `TIER_0` — sistem talimatları (asla kesilmez)
   - `TIER_1` — önemli kullanıcı mesajları
   - `TIER_2` — orta önemliler
   - `TIER_3` — eski, düşük öncelikliler

Kullanımı:

```python
ctx = ContextWindowManager(max_tokens=50_000)
ctx.add("user", "...", importance=0.8)
ctx.add("assistant", "...", importance=0.3)
ctx.prune()  # pencere dolarsa akıllıca kısaltır
print(ctx.get_summary())
```

---

## Bilgi grafiği

"Vahit" ile "opsiton projesi" arasındaki ilişkiyi makineye öğretmek için:

```python
from riks_context_engine.graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_entity("vahit", type="PERSON")
kg.add_entity("opsiton", type="PROJECT")
kg.add_relationship("vahit", "works_on", "opsiton")
kg.add_relationship("opsiton", "uses", "riks-context-engine")

# Vahit'ten "uses" ilişkisini takip et
kg.find_path("vahit", "riks-context-engine", max_depth=3)
```

Vektör araması da var: "Türkçe konuşan kim" gibi doğal dilde soru sorabilirsin, benzerlik skoruyla sonuç döner.

---

## Görev ayrıştırma

Büyük hedefi küçük, bağımlılıkları doğru adımlara bölmek:

```python
from riks_context_engine.tasks import TaskDecomposer

decomposer = TaskDecomposer()
gorev = decomposer.decompose(
    "Prod'a deploy et ve health check yap"
)
# Sonuç: bağımlılığı doğru sıralanmış alt görev listesi
```

Her adımda: ne yapılması gerektiği, başarı ölçütü, geri alma adımı. Döngüsel bağımlılıklar otomatik yakalanır.

---

## Kendi kendine düşünme (reflection)

Bir oturum bittikten sonra "ne iyi gitti, ne kötü gitti" analizi:

```python
from riks_context_engine.reflection import ReflectionAnalyzer

ana = ReflectionAnalyzer()
analiz = ana.analyze(session_id="2026-08-18-abc")
# Sonuç: kategorilendirilmiş dersler (tool-use, context-management, ...)
# ve önem derecesi (info → warning → critical)
```

Sonraki görevlerde bu dersler otomatik olarak "consult-before-task" aşamasında sorulur: "daha önce benzer şeyde şunu yapmıştın, hatırlıyor musun?"

---

## Komut satırı (CLI)

```bash
riks --version
riks memory add --type semantic "Vahit solak"
riks memory query --type episodic "deploy"
riks memory stats
riks context stats
riks context prune
riks task "Prod'a deploy et" --execute
riks reflect --session 2026-08-18-abc
```

---

## API (HTTP)

Sunucu olarak çalıştırdığında şunlar var:

| Endpoint | Ne yapar |
|----------|----------|
| `GET /health` | Sağlıklı mı? |
| `GET /models` | LLM modeli listesi |
| `POST /api/chat` | Chat (hafızayla birlikte) |
| `GET /api/v1/memory/export` | Tüm hafızayı dışa aktar (JSON) |
| `POST /api/v1/memory/import` | Hafıza içe aktar |

Türev endpoint'ler (tenant isolation, context window v2) v0.3.0'da geliyor.

---

## Verin nereye gidiyor?

Tümden yerel. Hiçbir veri buluta gitmez.

| Katman | Dosya | Format |
|--------|-------|--------|
| Episodic | `data/episodic.json` | JSON |
| Semantic | `data/semantic.db` + ChromaDB | SQLite + vektör |
| Procedural | `data/procedural.json` | JSON |
| Bilgi grafiği | `data/knowledge_graph.db` | SQLite |
| Bağlam penceresi | — | Bellek (kalıcı değil) |

`DATA_DIR` değişkeniyle hepsini başka bir yere taşıyabilirsin.

---

## Sık sorulanlar

**Soru: Bu, LangChain'ın memory'siyle ne farkı var?**
Cevap: LangChain'ın memory'si çoğunlukla tek katman (genellikle kısa ömürlü). Burada üç katman + bilgi grafiği + görev ayrıştırma + yansıma döngüsü bir arada. Ayrıca "önem skorlama" mantığı LangChain'da yok — her mesaj aynı ağırlıkta.

**Soru: Ollama kurmak zorunda mıyım?**
Cevap: Hayır. Ollama sadece vektör arama ve görev ayrıştırma için lazım. Sadece katmanlı hafıza + bağlam penceresi kullanacaksan Ollama'sız da çalışır.

**Soru: Verilerim nereye gidiyor?**
Cevap: `DATA_DIR`'e. Varsayılan `/app/data` (Docker) veya `./data` (yerel). Hiçbir yere gitmez.

**Soru: Python sürümü?**
Cevap: 3.10, 3.11, 3.12 destekli (test edildi). 3.9 ve altı desteklenmez.

**Soru: Lisansı?**
Cevap: AGPL-3.0. Üzerine kuracağın ticari bir ürün varsa, kaynak kodu paylaşman gerekir.

---

*İlk bakış için yeter. Derine inmek için [QUICKSTART](./QUICKSTART.md) ve [API.md](./API.md) dosyalarına bak.*
