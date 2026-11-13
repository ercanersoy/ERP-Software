# Veri tabanı sistemleri ve işletim

## Desteklenen veri tabanı sistemleri

| Sistem | Python sürücüsü | Not |
|---|---|---|
| SQLite | yerleşik | Sunucu gerekmez; tek ofis ve deneme için idealdir |
| MySQL 8 | `PyMySQL` | Tablolar InnoDB ve `utf8mb4` kullanır |
| MariaDB 10.6+ | `PyMySQL` (veya `mariadb`) | MySQL ile aynı |
| Microsoft SQL Server 2016+ | `pyodbc` (Microsoft ODBC sürücüsüyle) veya `pymssql` | Metinler NVARCHAR (Unicode) olarak saklanır |
| PostgreSQL 12+ | `psycopg` (3) veya `psycopg2` | |

Sistemi kurulum sihirbazında seçin. Önce **boş bir veri tabanı** ve tablo oluşturma hakkı olan bir kullanıcı oluşturun.

MySQL / MariaDB:

```
CREATE DATABASE erp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'erp'@'localhost' IDENTIFIED BY 'guclu-bir-parola';
GRANT ALL PRIVILEGES ON erp.* TO 'erp'@'localhost';
```

PostgreSQL:

```
CREATE USER erp WITH PASSWORD 'guclu-bir-parola';
CREATE DATABASE erp OWNER erp ENCODING 'UTF8';
```

Microsoft SQL Server:

```
CREATE DATABASE erp;
CREATE LOGIN erp WITH PASSWORD = 'Guclu-bir-parola1';
USE erp;
CREATE USER erp FOR LOGIN erp;
ALTER ROLE db_owner ADD MEMBER erp;
```

SQL Server için “ODBC Driver 18 for SQL Server” sürücüsünü ve `pip install pyodbc` paketini kurun ya da sürücü olarak `pymssql` girerek onu kullanın.

## Veriler nasıl saklanır

- Sistem tabloları `erp_` ile başlar (`erp_users`, `erp_entities`, `erp_fields`, `erp_settings`, ...).
- Her veri ekranının `d_<ad>` adlı kendi tablosu vardır; `id`, `created_at`, `updated_at`, `created_by`, `updated_by`, `api_key_id` sütunlarını ve her alan için bir sütun içerir. Alan eklemek veya silmek tabloyu değiştirir. Bu nedenle veriler sıradan SQL ve raporlama araçlarıyla da okunabilir.
- Saatler UTC olarak saklanır.
- Yüklenen dosyalar yükleme dizininde saklanır; `erp_files` tablosu bunları tanımlar.

## Yapılandırma dosyası

Kurulum sihirbazı `instance/erp.toml` dosyasını (veya `--config` / `ERP_CONFIG` ile verilen dosyayı) yazar:

```
[server]
cookie_secret = "..."
max_upload_mb = 256
# address = "0.0.0.0"
# port = 8888
# certfile = "/etc/ssl/erp.crt"   # HTTPS
# keyfile = "/etc/ssl/erp.key"
# xheaders = true                 # ters vekil sunucunun arkasında

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

Göreli yollar, yapılandırma dosyasının bulunduğu dizine göredir. Kurulum sihirbazını yeniden çalıştırmak için (sunucu durdurulmuşken) dosyayı silin.

## İşletim

- **HTTPS**: `certfile` ve `keyfile` ayarlayın ya da programı HTTPS kullanan bir ters vekil sunucunun (nginx, Apache, IIS) arkasında çalıştırıp istemci adreslerinin doğru günlüğe yazılması için `xheaders = true` ayarlayın. `/api/v1/stream/` için WebSocket yükseltmelerini vekil sunucudan geçirin.
- **Çok kullanıcı**: veri tabanı işleri bir iş parçacığı havuzunda (`pool_size` bağlantı) çalışır; böylece sunucu aynı anda çok sayıda kullanıcı ve sensörle de hızlı yanıt verir.
- **Yükleme boyutu**: `max_upload_mb` bir isteğin boyutunu sınırlar (varsayılan 256 MB).
- **Hizmet**: `python3 -m erp --config /srv/erp/erp.toml` komutunu systemd, bir Windows hizmet sarmalayıcısı veya bir kapsayıcı ile çalıştırın.

Örnek systemd birimi:

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

## Güvenlik

- Parolalar: scrypt özetleri; oturumlar: SHA-256 özeti olarak saklanan rastgele belirteçler, imzalı çerezler (HttpOnly, SameSite).
- Formlar siteler arası istek sahteciliğine (XSRF) karşı korunur.
- Sayfalar sıkı bir İçerik Güvenliği Politikası (CSP) gönderir; yüklenen resim ve videolar içeriklerine göre denetlenir.
- API anahtarları SHA-256 özetleri olarak saklanır; veri ekranı, haklar, IP ağı, süre ve geçerlilik sonu ile sınırlandırılabilir.
- Giriş denemeleri sınırlıdır.
