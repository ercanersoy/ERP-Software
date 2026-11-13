# Export, backup and restore

Everything can be downloaded as an **SQL** or a **TOML** file under **Administration › Export and backup**.

## What can be exported

| Export | Contents |
|---|---|
| Configuration | All configuration as a whole: settings, menus and data definitions (data screens and fields) |
| Data formats | The formats the data must have: data screens and fields, plus the CREATE TABLE statements of their tables (SQL) |
| Data | The records of the selected data screens (and the information about their files) |
| Full database backup | The whole database: configuration, data formats, data, users (with password hashes), API keys (hashes only), file information and the audit log |

Single data screens can also be exported from their list (`x`), as CSV, TOML or SQL.

## Options

- **File format**: TOML (readable, portable, can be imported again) or SQL.
- **SQL dialect**: SQLite, MySQL, MariaDB, Microsoft SQL Server or PostgreSQL. The SQL file can be run directly with the tool of that database system, for example `mysql erp < backup.sql`, `psql -d erp -f backup.sql`, `sqlcmd -i backup.sql` or `sqlite3 erp.sqlite3 < backup.sql`. An installation can thus be moved to another database system.
- **Character set**: UTF-8, ASCII, DOS 437, DOS 850, DOS 857, Windows-1252, Windows-1254, ISO-8859-1/9/15, Mac Turkish, UTF-16. The file starts with a `charset:` comment. TOML writes characters that do not exist in the chosen character set as `\uXXXX` escapes, so nothing is lost. SQL replaces them with `?`.
- **Include file contents** (TOML): uploaded documents, images and videos are embedded as base64. Without this option, back up the upload directory as well.

## What an SQL file does

- Configuration and data formats: create missing tables, then replace the rows of the configuration tables.
- Data: create missing tables, delete the records of the exported data screens and insert them again.
- Full backup: drop and re-create all tables, then insert everything.

The statements run inside one transaction where the database system allows it. Note that MySQL and MariaDB commit table changes (DDL) immediately.

## TOML structure

```
# charset: utf-8
[backup]
format = "erp-software"
kind = "full"
schema_version = 1

[settings]
company_name = "Example Ltd"

[[menus]]
id = 1
title = "Sales"

[[entities]]
name = "customers"
label = "Customers"

[[entities.fields]]
name = "name"
field_type = "text"

[[data.customers]]
id = 1
name = "ACME Ltd."
created_at = 2026-11-12T10:15:00
```

Missing values mean NULL. Decimal and currency values are written as strings to keep them exact.

## Import and restore

**Administration › Export and backup › Import / restore** accepts TOML exports:

- **Configuration**: replaces settings and menus; creates missing data screens and fields and updates existing ones. Existing data is kept.
- **Data formats**: creates missing data screens and fields and updates existing ones.
- **Data**: “Append records” adds the records with new ids; “Replace” deletes the records of the data screens in the file and restores them with their original ids. Rows that do not fit the current definition are skipped.
- **Full backup**: after ticking “Replace the whole database”, ALL current content is replaced. Everybody is logged out; log in with an account from the backup.

The character set is read from the `charset:` comment; it can also be chosen by hand. Take a backup before every import.

## Recommended backup routine

1. Download a **full database backup** as TOML with file contents regularly, or as SQL together with a copy of the upload directory.
2. Additionally use the backup tools of your database system (`mysqldump`, `pg_dump`, SQL Server backups).
3. Keep `instance/erp.toml` safe: it contains the database password and the cookie secret.
