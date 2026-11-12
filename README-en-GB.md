# ERP-Software — English (United Kingdom)

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

---

Copyright (c) 2026 Ercan Ersoy

This project licensed under MIT License.
