# ERP-Software User Guide

ERP-Software is a simple, web based ERP system. It ships with **no predefined data fields**: you define the data screens (for example customers, products, invoices or sensor readings) and their fields yourself. Everything can be used with the keyboard alone.

Other pages of this guide:

- [REST API and sensors](API.md)
- [Export, backup and restore](BACKUP.md)
- [Database systems and operation](DATABASES.md)

## Requirements

- Python 3.13 or newer
- Tornado 6.4 or newer
- Optionally a database driver: PyMySQL (MySQL, MariaDB), pyodbc or pymssql (Microsoft SQL Server), psycopg (PostgreSQL). SQLite is built into Python.

## Installation

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install PyMySQL            # only for MySQL / MariaDB
python3 -m erp --host 0.0.0.0 --port 8888
```

You can also install the package with `pip install .` (or `pip install ".[mysql]"`, `".[mssql]"`, `".[postgresql]"`) and start it with the `erp-software` command.

Command line options:

| Option | Meaning |
|---|---|
| `--config FILE` | Instance configuration file (default `instance/erp.toml`, or the `ERP_CONFIG` environment variable) |
| `--host ADDRESS` | Address to listen on (default `127.0.0.1`) |
| `--port PORT` | Port (default `8888`) |
| `--debug` | Development mode with detailed error pages |

## First start: the setup wizard

When no configuration file exists, the program starts in **setup mode**. Every page then leads to `/setup`, and a one-time **setup token** is printed in the server console:

```
WARNING erp: Setup mode: open http://127.0.0.1:8888/setup
WARNING erp: Setup token: 3hF0c...
```

In the wizard you enter:

1. the setup token,
2. the interface language and the company name,
3. the database system and its connection details (use **Test connection** first),
4. the first administrator account,
5. the default character set, time zone and currency, and the upload directory.

**Install** creates the tables, the administrator and the file `instance/erp.toml` (readable only by its owner). The program leaves setup mode at once; `/setup` is no longer reachable. To run the wizard again, stop the server and delete the configuration file. If the chosen database already contains an ERP-Software installation, it is kept.

## Logging in, users and roles

Several people can work at the same time; every user has their own session. There are three roles:

| Role | Rights |
|---|---|
| Administrator | Everything: data definitions, menus, users, API keys, settings, backups and all data |
| User | Works with the data screens; per screen the access is “read and write”, “read only” or “no access” |
| Dealer | Sees only the screens opened to dealers; per screen “read only” or “own records only” (a dealer creates records and sees and changes only the records they created) |

After five failed logins the account is locked for 15 minutes for that address. Passwords are stored as scrypt hashes. Every user can change their name, e-mail, language and password under **My account**.

## Navigating with menus and the keyboard

The program is operated through menus: the main menu leads to menu groups, data screens, administration, the account, the help and the logout. Every menu item has a key.

| Key | Action |
|---|---|
| `1`…`9`, `a`…`z` | Open the menu item with that key |
| `↑` `↓` `Home` `End` | Move between menu items or table rows |
| `Enter` | Open the selected item or row |
| `Esc` | Back to the previous screen (or leave a text field) |
| `0` | Main menu |
| `/` | Search in a list |
| `n` | New record (or new item) |
| `e` | Edit |
| `Del` | Delete |
| `PgUp` `PgDn` | Previous / next page |
| `Ctrl+S` or `Ctrl+Enter` | Save the form |
| `?` or `F1` | Show the keyboard shortcuts |

The interface language can be changed at any time with the links in the top right corner (tr-TR, en-US, en-GB) or under **My account**. In English (US) dates are shown as MM/DD/YYYY with the 12-hour clock; in English (UK) as DD/MM/YYYY.

## Data definitions: your own data screens

Under **Administration › Data definitions** (only administrators):

1. Press `n` and create a data screen. The **technical name** (for example `customers`) names the database table `d_customers` and is used by the API; it can not be changed later. The **title** is what users see.
2. Add fields with `n`. Each field has a technical name, a label and a type.

Field types:

| Type | Stored as | Notes |
|---|---|---|
| Text (single line) | VARCHAR | maximum length 1-4000 |
| Long text | TEXT | multi-line |
| Integer | BIGINT | |
| Decimal number | DECIMAL(18, n) | 0-8 decimal places |
| Measurement (floating point) | DOUBLE | suited for sensor values |
| Currency amount | DECIMAL(19, n) | with currency (TRY, USD, EUR, GBP, ...) |
| Yes / No | BOOLEAN | |
| Date, Date and time | DATE, DATETIME | times are stored in UTC and shown in the configured time zone |
| Choice list | VARCHAR | one choice per line |
| E-mail address | VARCHAR | checked |
| Link to another data screen | BIGINT | select a record of another screen |
| Document, Image, Video | file | stored in the upload directory |

Further options: required, unique, show in list, default value, help text and order. The type, the technical name and storage relevant settings can not be changed after creation; delete the field and create it again instead (its values are lost).

Settings of a data screen: menu, access for users and dealers, title field (shown when other screens link to a record), sensor/live data, reading interval and rows per page.

## Menus

Under **Administration › Menus** you build menu groups and sub-menus (for example “Sales › Orders”). In the data screen definition you choose the menu the screen belongs to. Without menus, all data screens appear in the main menu. Users only see the menus that contain screens they are allowed to open.

## Working with records

- **List**: search with `/`, sort by clicking a column header, page with `PgUp`/`PgDn`, open a row with `Enter`.
- **New** (`n`), **Edit** (`e`), **Delete** (`Del`). “Save and new” keeps entering records quickly.
- **Files**: documents (PDF, office documents, text, CSV, XML, JSON, ZIP, 7z), images (PNG, JPEG, GIF, WebP, BMP) and videos (MP4, WebM, Ogg, QuickTime). Images and videos are checked by their content and shown in the record; videos can be played and seeked.
- **Export** (`x`): CSV, TOML or SQL in any supported character set.
- **Import CSV** (`i`): the first line contains the technical field names; numbers may use `,` or `.` as decimal separator.

## Sensors and live data

Mark a data screen as **Sensor / live data** and set its **reading interval** in milliseconds. The screen then has a **Live monitor** (`m`) that shows the newest records and refreshes at that interval (the interval can be changed on the page; `p` pauses). Sensors send values through the REST API or a WebSocket and can read the configured interval from the API, so the reading interval is adjusted centrally. See [REST API and sensors](API.md).

## Settings

**Administration › Settings** holds the company name, the default language, the default character set for exports and imports, the time zone, the default currency, rows per page, the session length and the REST API switch. All settings are saved together with one form; the whole configuration can be downloaded as SQL or TOML (see [Export, backup and restore](BACKUP.md)).

## Character sets

Inside the program all text is Unicode. Files that enter or leave the system (SQL, TOML and CSV exports and imports, API requests with a `charset` parameter) support: UTF-8, UTF-8 with BOM, UTF-16, ASCII, DOS 437, DOS 850, DOS 857 (Turkish), Windows-1252, Windows-1254 (Turkish), ISO-8859-1, ISO-8859-9 (Latin-5), ISO-8859-15 and Mac Turkish.

## Audit log and system information

The **audit log** records logins, changes of definitions, users, API keys and settings, record changes, exports and imports. **System information** shows versions, the database, the configuration file, the upload directory and record counts, and can delete uploads that were never attached to a record.

## Look and feel

The interface is deliberately plain: it uses only web safe colors (the 216 color palette) and web safe font families (Verdana, Tahoma, Arial, Helvetica, Georgia, Times New Roman, Courier New). It needs no external resources and works on small screens and in print.
