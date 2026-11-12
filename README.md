# ERP-Software

An open source, web based ERP software · Açık kaynak, web tabanlı ERP yazılımı

Copyright (c) 2026 Ercan Ersoy

This project licensed under MIT License.

---

## Türkçe (Türkiye)

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

## English (United States)

ERP-Software is a simple, keyboard friendly, web based ERP system written in Python 3.13+ with Tornado.

- **Menu navigation**: every screen is reached through menus with numbered keys; `Esc` goes back, `0` opens the main menu, `?` shows the shortcuts.
- **Customizable data fields**: nothing is predefined; you define data screens and their fields (text, numbers, currency, dates, choices, links, documents, images, videos, ...).
- **Users and roles**: administrator, user and dealer; many users at the same time.
- **Databases**: SQLite, MySQL, MariaDB, Microsoft SQL Server, PostgreSQL.
- **Setup wizard**: shown on first start, closed after installation.
- **REST API and WebSocket**: secure data entry authorized by API keys; adjustable reading interval and live monitor for sensors.
- **Export and backup**: configuration, data formats, data and full database backups as SQL or TOML files; restore from TOML.
- **Character sets**: UTF-8, ASCII, DOS 437, DOS 857, Windows-1254 and more.
- **Interface languages**: Turkish (Türkiye), English (US), English (UK).
- **Plain look**: only web safe colors and web safe font families.

Quick start:

```
pip install -r requirements.txt
python3 -m erp --port 8888
```

Then open `http://127.0.0.1:8888/setup`; the setup token is printed in the console. Documentation: [docs/en-US](docs/en-US/README.md).

## English (United Kingdom)

ERP-Software is a simple, keyboard-friendly, web-based ERP system written in Python 3.13+ with Tornado.

- **Menu navigation**: every screen is reached through menus with numbered keys; `Esc` goes back, `0` opens the main menu, `?` shows the shortcuts.
- **Customisable data fields**: nothing is predefined; you define data screens and their fields (text, numbers, currency, dates, choices, links, documents, images, videos, ...).
- **Users and roles**: administrator, user and dealer; many users at the same time.
- **Databases**: SQLite, MySQL, MariaDB, Microsoft SQL Server, PostgreSQL.
- **Setup wizard**: shown on first start, closed after installation.
- **REST API and WebSocket**: secure data entry authorised by API keys; adjustable reading interval and live monitor for sensors.
- **Export and backup**: configuration, data formats, data and full database backups as SQL or TOML files; restore from TOML.
- **Character sets**: UTF-8, ASCII, DOS 437, DOS 857, Windows-1254 and more.
- **Interface languages**: Turkish (Türkiye), English (US), English (UK).
- **Plain look**: only web-safe colours and web-safe font families.

Quick start:

```
pip install -r requirements.txt
python3 -m erp --port 8888
```

Then open `http://127.0.0.1:8888/setup`; the setup token is printed in the console. Documentation: [docs/en-GB](docs/en-GB/README.md).

---

## Development

```
pip install -r requirements.txt pytest
python3 -m pytest
```

The tests use SQLite. To run them against another database system, point `ERP_TEST_DB` at an empty test database, for example:

```
ERP_TEST_DB='{"db_dialect": "postgresql", "db_host": "127.0.0.1", "db_name": "erp_test", "db_user": "erp", "db_password": "secret"}' python3 -m pytest
```

Project layout:

| Path | Contents |
|---|---|
| `erp/app.py` | Application state, URL routes, server start |
| `erp/db/` | Database layer and SQL dialects |
| `erp/repo/` | Data access (users, menus, entities, records, files, API keys, audit log) |
| `erp/handlers/` | Web screens, REST API and WebSocket |
| `erp/backup.py` | SQL/TOML/CSV export, import and restore |
| `erp/locales/` | Interface texts (tr-TR, en-US, en-GB) |
| `erp/templates/`, `erp/static/` | HTML templates, style sheet, keyboard script |
| `docs/` | Documentation in three languages (also shown in the in-app help) |
| `tests/` | Automated tests |
