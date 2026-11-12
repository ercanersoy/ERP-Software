# Database systems and operation

## Supported database systems

| System | Python driver | Notes |
|---|---|---|
| SQLite | built in | No server needed; ideal for a single office and for testing |
| MySQL 8 | `PyMySQL` | Tables use InnoDB and `utf8mb4` |
| MariaDB 10.6+ | `PyMySQL` (or `mariadb`) | Same as MySQL |
| Microsoft SQL Server 2016+ | `pyodbc` (with the Microsoft ODBC driver) or `pymssql` | Texts are stored as NVARCHAR (Unicode) |
| PostgreSQL 12+ | `psycopg` (3) or `psycopg2` | |

Choose the system in the setup wizard. Create an **empty database** and a user with the right to create tables first.

MySQL / MariaDB:

```
CREATE DATABASE erp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'erp'@'localhost' IDENTIFIED BY 'a-strong-password';
GRANT ALL PRIVILEGES ON erp.* TO 'erp'@'localhost';
```

PostgreSQL:

```
CREATE USER erp WITH PASSWORD 'a-strong-password';
CREATE DATABASE erp OWNER erp ENCODING 'UTF8';
```

Microsoft SQL Server:

```
CREATE DATABASE erp;
CREATE LOGIN erp WITH PASSWORD = 'A-strong-password1';
USE erp;
CREATE USER erp FOR LOGIN erp;
ALTER ROLE db_owner ADD MEMBER erp;
```

For SQL Server install the “ODBC Driver 18 for SQL Server” and `pip install pyodbc`, or use `pymssql` by entering it as the driver.

## How data is stored

- System tables start with `erp_` (`erp_users`, `erp_entities`, `erp_fields`, `erp_settings`, ...).
- Every data screen has its own table `d_<name>` with the columns `id`, `created_at`, `updated_at`, `created_by`, `updated_by`, `api_key_id` and one column per field. Adding or deleting a field changes the table. The data can therefore also be read with ordinary SQL and reporting tools.
- Times are stored in UTC.
- Uploaded files are stored in the upload directory; the table `erp_files` describes them.

## The configuration file

The setup wizard writes `instance/erp.toml` (or the file given by `--config` / `ERP_CONFIG`):

```
[server]
cookie_secret = "..."
max_upload_mb = 256
# address = "0.0.0.0"
# port = 8888
# certfile = "/etc/ssl/erp.crt"   # HTTPS
# keyfile = "/etc/ssl/erp.key"
# xheaders = true                 # behind a reverse proxy

[database]
dialect = "mariadb"
host = "localhost"
port = 3306
name = "erp"
user = "erp"
password = "..."
pool_size = 8

[storage]
upload_dir = "uploads"
```

Relative paths are relative to the directory of the configuration file. Delete the file (with the server stopped) to run the setup wizard again.

## Operation

- **HTTPS**: set `certfile` and `keyfile`, or run the program behind a reverse proxy (nginx, Apache, IIS) with HTTPS and set `xheaders = true` so that client addresses are logged correctly. Pass WebSocket upgrades for `/api/v1/stream/` through the proxy.
- **Many users**: database work runs in a thread pool (`pool_size` connections), so the server stays responsive with many users and sensors at the same time.
- **Upload size**: `max_upload_mb` limits the size of a request (default 256 MB).
- **Service**: run `python3 -m erp --config /srv/erp/erp.toml` with systemd, a Windows service wrapper or a container.

Example systemd unit:

```
[Unit]
Description=ERP-Software
After=network.target

[Service]
User=erp
WorkingDirectory=/srv/erp
ExecStart=/srv/erp/.venv/bin/python -m erp --config /srv/erp/instance/erp.toml --host 127.0.0.1 --port 8888
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Security

- Passwords: scrypt hashes; sessions: random tokens stored as SHA-256 hashes, signed cookies (HttpOnly, SameSite).
- Forms are protected against cross site request forgery (XSRF).
- Pages send a strict Content Security Policy; uploaded images and videos are checked by their content.
- API keys are stored as SHA-256 hashes and can be limited by data screen, rights, IP network, interval and expiry date.
- Login attempts are limited.
