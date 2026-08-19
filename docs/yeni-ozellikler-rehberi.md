# Rik Context Engine — Yeni Özellikler Rehberi

> Bu belge, teknik jargona boğulmadan, son eklenen üç büyük özelliği anlatır.  
> Hedef kitle: ürünü merak eden herkes — geliştirici olmanız gerekmiyor.

---

## 🧠 Ortak Hafıza (Shared Memory) — #108

### Ne yapıyor?

Normalde bir AI asistan sadece kendi "kafasının içini" bilir. Başka bir asistan aynı bilgiye ulaşamaz. Ortak Hafıza bunu değiştiriyor: birden fazla AI agent, **aynı bilgi havuzunu** kullanabiliyor — ama birbirinin özel bilgilerine karışmadan.

### Günlük hayattan örnek

Bir şirketin muhasebe ekibi ve pazarlama ekibini düşünün. İkisi de "şirket bilgilerini" görür, ama muhasebenin mali raporları pazarlamacıya karışmaz. Ortak Hafıza tam bunu yapıyor — **kiracı (tenant) bazlı izolasyon**.

### Nasıl çalışıyor?

```
Agent A (tenant: "proje-alfa")     Agent B (tenant: "proje-beta")
        ↓                                    ↓
   Kendi hafızası                       Kendi hafızası
        ↓                                    ↓
  ┌──────────────────────────────────────────────┐
  │         Rik Context Engine (sunucu)          │
  │  ┌─────────────┐    ┌─────────────┐         │
  │  │ alfa verileri│    │ beta verileri│         │
  │  └─────────────┘    └─────────────┘         │
  │  Birbirine erişemez — her biri kendi odasında│
  └──────────────────────────────────────────────┘
```

### Kısa özet

| Soru | Cevap |
|------|-------|
| **Kim kullanır?** | Birden fazla AI agent'ı olan herkes |
| **Ne kazanırım?** | Agent'lar bilgi paylaşır ama birbirinin özel verisini göremez |
| **Kurulum gerekir mi?** | Hayır — her MCP isteğinde `tenant_id` göndermeniz yeterli |

---

## 💾 Yedekleme ve Sağlık Kontrolü — #105

### Ne yapıyor?

Rik Context Engine verilerinizi düzenli olarak yedekleyebiliyor ve "doktor" komutuyla veri bütünlüğünü kontrol edebiliyorsunuz.

### Neden önemli?

AI hafızası, zaman içinde biriken değerli bir varlık. Bir veritabanı bozulması veya disk arızası, haftalarca biriken bilgiyi silebilir. Yedekleme bunu önlüyor.

### Nasıl kullanılır?

**Yedek almak** — tek komut:

```bash
python scripts/backup.py
```

**Sağlık kontrolü** — "veri dosyalarım sağlam mı?" sorusuna cevap verir:

```bash
riks doctor
```

Her şey tamamsa ✅, bir sorun varsa hangi dosyada olduğunu ve en son yedeğin nerede durduğunu gösterir.

### Otomatik yedekleme

Her 6 saatte bir otomatik yedek almak isterseniz, sunucunuza şu satırı ekleyin:

```
0 */6 * * * cd /proje/yolu && python scripts/backup.py
```

### Kısa özet

| Soru | Cevap |
|------|-------|
| **Kim kullanır?** | Rik Context Engine çalıştıran herkes |
| **Ne kazanırım?** | Veri kaybına karşı güvenlik ağı + "bir şey bozuldu mu?" kontrolü |
| **Zor mu?** | Hayır — iki komut: `backup.py` (yedekle) ve `riks doctor` (kontrol et) |

---

## ⚡ MCP v2 — Görev Çalıştırma (Task Execute) — #107

### Ne yapıyor?

AI agent'ınız artık Rik'e sadece "hatırla" veya "hatırlat" demekle kalmıyor — doğrudan **görev çalıştırabiliyor**. "Şu hedefe ulaş" diyorsunuz, Rik gerisini hallediyor.

### Günlük hayattan örnek

Bir asistana "bu dosyayı analiz et ve özet çıkar" demek gibi. Asistan görevi alıyor, süre sınırı içinde tamamlıyor ve sonucu size dönüyor. Süre aşılırsa panik yapmak yerine düzgünce "zaman yetmedi" diyor.

### Nasıl çalışıyor?

```
Agent → "Hedef: kullanıcının son 5 notunu özetle (30 saniye süren var)"
  ↓
Rik Context Engine
  ↓
  ├─ Görevi alır
  ├─ 30 saniye zamanlayıcı kurar
  ├─ Çalıştırır
  └─ Sonuç: ✅ tamamlandı veya ⏱️ süre doldu
```

### Önemli detaylar

- **Süre sınırı zorunlu** — sonsuz döngüye girmez, en fazla 120 saniye çalışır
- **Hata yönetimi düzgün** — bir şey patlarsa sistem çökmez, anlaşılır hata döner
- **Tenant bazlı** — her agent kendi görev kuyruğunda çalışır

### Kısa özet

| Soru | Cevap |
|------|-------|
| **Kim kullanır?** | Agent'larına iş yaptırmak isteyen geliştiriciler |
| **Ne kazanırım?** | "Hafıza motoru" artık "iş yapan motor" oluyor |
| **Risk var mı?** | Hayır — zorunlu zaman aşımı + hata yönetimi var |

---

## Üç özellik birlikte ne anlama geliyor?

Rik Context Engine artık sadece "hatırlayan" bir motor değil:

1. **Hatırlıyor** — ve bunu birden fazla agent arasında güvenle paylaşıyor (Ortak Hafıza)
2. **Korunuyor** — verilerinizi yedekliyor ve bütünlüğünü kontrol ediyor (Yedekleme)
3. **İş yapıyor** — agent'lara doğrudan görev çalıştırma yeteneği veriyor (Task Execute)

```
  🧠 Hatırla  →  💾 Koru  →  ⚡ Çalıştır
     ↑                            ↓
     └────── öğren ← sonuç ──────┘
```

---

*Bu belge, [Rik Context Engine](https://github.com/vopsiton/riks-context-engine) v0.3.0 özelliklerini kapsar.*
