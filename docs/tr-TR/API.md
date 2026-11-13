# REST API ve sensörler

Diğer programlar, cihazlar ve sensörler `/api/v1` adresindeki REST API ile veri okuyup yazabilir. Bütün veriler JSON olarak alınıp verilir (istek başka bir `charset` belirtmedikçe UTF-8).

## Yetkilendirme

1. Bir yönetici **Yönetim › API anahtarları** bölümünde bir anahtar oluşturur. Anahtar şunlarla sınırlandırılabilir:
   - seçilen veri ekranları (hiçbiri seçilmezse = hepsi),
   - okuma ve/veya yazma,
   - IP adresleri veya ağlar (örneğin `192.168.10.0/24`),
   - yazmalar arası milisaniye cinsinden en kısa süre (daha sık yazmalar HTTP 429 alır),
   - geçerlilik sonu tarihi.
2. Anahtar **yalnızca bir kez** gösterilir; yalnızca SHA-256 özeti saklanır.
3. Her istekle birlikte gönderin:

```
Authorization: Bearer erp_1a2b3c4d_...
```

veya `X-API-Key: erp_1a2b3c4d_...`. Canlı kullanımda HTTPS kullanın (bkz. [Veri tabanı sistemleri ve işletim](DATABASES.md)). API, **Ayarlar** bölümünden kapatılabilir.

## Uç noktalar

| Yöntem ve yol | Amaç |
|---|---|
| `GET /api/v1/ping` | Anahtarı denetler; adını ve haklarını döndürür |
| `GET /api/v1/entities` | Anahtarın kullanabileceği veri ekranları ve alanları |
| `GET /api/v1/entities/{ad}` | Bir veri ekranının veri biçimi (alanları) |
| `GET /api/v1/entities/{ad}/config` | Sensörler için okuma süresi (`read_interval_ms`) |
| `GET /api/v1/entities/{ad}/records` | Kayıtları listeler |
| `POST /api/v1/entities/{ad}/records` | Bir kayıt (nesne) veya çok sayıda kayıt (dizi, en fazla 1000) oluşturur |
| `GET /api/v1/entities/{ad}/records/{id}` | Bir kaydı okur |
| `PUT /api/v1/entities/{ad}/records/{id}` | Bir kaydı baştan yazar |
| `PATCH /api/v1/entities/{ad}/records/{id}` | Bir kaydın bazı alanlarını değiştirir |
| `DELETE /api/v1/entities/{ad}/records/{id}` | Bir kaydı siler |
| `GET /api/v1/entities/{ad}/latest?n=10` | En yeni kayıtlar (göstergeler için) |
| `POST /api/v1/files?kind=image&entity={ad}` | Dosya yükler (multipart alanı `file`); kimliğini döndürür |
| `GET /api/v1/files/{id}` | Dosya indirir |
| `WS /api/v1/stream/{ad}` | Anlık veri için WebSocket |

`GET .../records` parametreleri: `limit` (1-1000, varsayılan 100), `offset`, `since_id` (yalnızca daha yeni kayıtlar, eskiden yeniye), `order` (bir alan adı, `id`, `created_at` veya `updated_at`), `dir` (`asc`/`desc`), `q` (arama) ve tam eşleşme süzgeçleri için `<alan>=<değer>`.

## Değerler

| Alan türü | JSON değeri |
|---|---|
| Metin, uzun metin, seçim, e-posta | dizge |
| Tam sayı, bağlantı | sayı (bağlı kaydın kimliği) |
| Ondalık, para | dizge (`"1234.50"`) veya sayı |
| Ölçüm | sayı |
| Evet / Hayır | `true` / `false` |
| Tarih | `"2026-11-12"` |
| Tarih ve saat | `"2026-11-12T10:15:00Z"` (UTC olarak saklanır) |
| Belge, resim, video | `POST /api/v1/files` ile alınan dosya kimliği |

Her kaydın ayrıca `id`, `created_at`, `updated_at`, `created_by` ve `api_key_id` alanları vardır.

## Örnekler

Kayıt oluşturma:

```
curl -X POST https://erp.ornek.com.tr/api/v1/entities/musteriler/records \
  -H "Authorization: Bearer $ERP_KEY" -H "Content-Type: application/json" \
  -d '{"unvan": "Örnek Ticaret A.Ş.", "bakiye": "1500.00", "aktif": true}'
```

Yanıt: `201 Created` ve `{"id": 42}`.

Çok sayıda sensör değerini birlikte gönderme:

```
curl -X POST https://erp.ornek.com.tr/api/v1/entities/sicakliklar/records \
  -H "Authorization: Bearer $ERP_KEY" -H "Content-Type: application/json" \
  -d '[{"sensor": "salon", "celsius": 21.4}, {"sensor": "depo", "celsius": 4.1}]'
```

Yalnızca yeni kayıtları okuma:

```
curl "https://erp.ornek.com.tr/api/v1/entities/sicakliklar/records?since_id=1200&limit=500" \
  -H "Authorization: Bearer $ERP_KEY"
```

Eski bir karakter kümesindeki istek:

```
Content-Type: application/json; charset=cp857
```

## Hatalar

Hatalar `{"error": "kod", "message": "...", "details": {...}}` biçimindedir.

| Durum | Anlamı |
|---|---|
| 400 | Geçersiz JSON veya istek |
| 401 | Eksik, yanlış, süresi dolmuş veya izin verilmeyen anahtar (ya da yanlış IP adresi) |
| 403 | Anahtar bu veri ekranını okuyamaz veya yazamaz |
| 404 | Bilinmeyen veri ekranı veya kayıt |
| 422 | Doğrulama başarısız; `details` alanları adlandırır (`required`, `invalid_number`, `not_unique`, `unknown_field`, ...) |
| 429 | Anahtarın en kısa süresinden daha sık; `Retry-After` başlığına bakın |
| 503 | API kapalı |

## Sensörler: ayarlanabilir okuma süresi

**Sensör / canlı veri** olarak işaretlenen bir veri ekranı için yönetici **okuma süresini** (milisaniye) belirler. Sensör bu değeri düzenli olarak sorar ve ona uyar; böylece cihazlara dokunmadan süre merkezden değiştirilebilir:

```
GET /api/v1/entities/sicakliklar/config
{"entity": "sicakliklar", "read_interval_ms": 1000, "min_interval_ms": 0, "server_time": "..."}
```

Python ile küçük bir sensör programı (yalnızca standart kütüphane):

```
import json, time, urllib.request

BASE = "https://erp.ornek.com.tr/api/v1/entities/sicakliklar"
HEADERS = {"Authorization": "Bearer erp_...", "Content-Type": "application/json"}

def call(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)

interval = call("GET", BASE + "/config")["read_interval_ms"] / 1000
while True:
    value = sicaklik_oku()              # sensör kodunuz
    call("POST", BASE + "/records", {"sensor": "salon", "celsius": value})
    time.sleep(interval)
    interval = call("GET", BASE + "/config")["read_interval_ms"] / 1000
```

## Anlık veri için WebSocket

`/api/v1/stream/{ad}` tek bir bağlantıyı açık tutar. Kimlik doğrulama `Authorization` başlığıyla (başlık gönderemeyen istemciler için `?token=...`) yapılır.

- Bağlanınca sunucu `{"event": "hello", "read_interval_ms": 1000, ...}` gönderir.
- Kayıt saklamak için bir JSON nesnesi veya dizisi gönderin; yanıt `{"event": "stored", "ids": [...]}` olur.
- Geçerli okuma süresini almak için `{"event": "config"}` gönderin.
- Okuma izni olan anahtarlar veri ekranının her yeni kaydını alır: `{"event": "created", "records": [...]}` (REST ile oluşturulanlar da).
- Hatalar: `{"event": "error", "error": "...", "details": {...}}`.

Web arayüzündeki canlı izleme ekranı (sensör ekranı listesinde `m`) okuma süresiyle yenilenir.
