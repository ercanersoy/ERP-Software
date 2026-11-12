# ERP-Software — Türkçe (Türkiye)

ERP-Software; Python 3.13+ ve Tornado ile yazılmış, sade ve klavyeyle kolayca kullanılabilen web tabanlı bir ERP yazılımıdır.

- **Menülerle gezinme**: her ekrana menüler üzerinden, numaralı tuşlarla ulaşılır; `Esc` geri, `0` ana menü, `?` kısayollar.
- **Özelleştirilebilir veri alanları**: hiçbir alan hazır gelmez; veri ekranlarını ve alanlarını (metin, sayı, para birimi, tarih, seçim, bağlantı, belge, resim, video, ...) kendiniz tanımlarsınız.
- **Kullanıcılar ve yetkiler**: yönetici, normal kullanıcı ve bayi; aynı anda çok kullanıcı.
- **Veri tabanları**: SQLite, MySQL, MariaDB, Microsoft SQL Server, PostgreSQL.
- **Kurulum sihirbazı**: ilk başlatmada açılır, kurulumdan sonra kapanır.
- **REST API ve WebSocket**: API anahtarlarıyla yetkili, güvenli veri girişi; sensörler için ayarlanabilir okuma süresi ve canlı izleme.
- **Dışa aktarma ve yedekleme**: yapılandırma, veri biçimleri, veriler ve tam veri tabanı yedeği; SQL veya TOML dosyası olarak. TOML ile geri yükleme.
- **Karakter kümeleri**: UTF-8, ASCII, DOS 437, DOS 857, Windows-1254 ve diğerleri.
- **Arayüz dilleri**: Türkiye Türkçesi, Amerikan İngilizcesi, İngiliz İngilizcesi.
- **Sade görünüm**: yalnızca web güvenli renkler ve web güvenli yazı aileleri.

Hızlı başlangıç:

```
pip install -r requirements.txt
python3 -m erp --port 8888
```

Ardından `http://127.0.0.1:8888/setup` adresini açın; kurulum anahtarı konsolda yazar. Belgeler: [docs/tr-TR](docs/tr-TR/README.md).

## Geliştirme

```
pip install -r requirements.txt pytest
python3 -m pytest
```

Testler SQLite kullanır. Başka bir veri tabanı sisteminde çalıştırmak için `ERP_TEST_DB` değişkenini boş bir test veri tabanına yöneltin, örneğin:

```
ERP_TEST_DB='{"db_dialect": "postgresql", "db_host": "127.0.0.1", "db_name": "erp_test", "db_user": "erp", "db_password": "secret"}' python3 -m pytest
```

Proje yapısı:

| Yol | İçerik |
|---|---|
| `erp/app.py` | Uygulama durumu, URL yolları, sunucunun başlatılması |
| `erp/db/` | Veri tabanı katmanı ve SQL lehçeleri |
| `erp/repo/` | Veri erişimi (kullanıcılar, menüler, veri ekranları, kayıtlar, dosyalar, API anahtarları, işlem günlüğü) |
| `erp/handlers/` | Web ekranları, REST API ve WebSocket |
| `erp/backup.py` | SQL/TOML/CSV dışa aktarma, içe aktarma ve geri yükleme |
| `erp/locales/` | Arayüz metinleri (tr-TR, en-US, en-GB) |
| `erp/templates/`, `erp/static/` | HTML şablonları, stil dosyası, klavye betiği |
| `docs/` | Üç dilde belgeler (program içi yardımda da gösterilir) |
| `tests/` | Otomatik testler |

---

Copyright (c) 2026 Ercan Ersoy

This project licensed under MIT License.
