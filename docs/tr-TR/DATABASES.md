# Veri tabanı sistemleri ve işletim

## Desteklenen veri tabanı sistemleri

| Sistem | Python sürücüsü | Not |
|---|---|---|
| SQLite | yerleşik | Sunucu gerekmez; tek ofis ve deneme için idealdir |
| MySQL 8 | `PyMySQL` | Tablolar InnoDB ve `utf8mb4` kullanır |
| MariaDB 10.6+ | `PyMySQL` (veya `mariadb`) | MySQL ile aynı |
| Microsoft SQL Server 2016+ | `pyodbc` (Microsoft ODBC sürücüsüyle) veya `pymssql` | Metinler NVARCHAR (Unicode) olarak saklanır |
| PostgreSQL 12+ | `psycopg` (3) veya `psycopg2` | |

Otomatik testler SQLite, PostgreSQL ve MariaDB (hem MySQL hem MariaDB ayarıyla) üzerinde çalıştırılır.

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

Veri tabanı **UTF8** kodlamasını kullanmalıdır. Sunucunun şablon veri tabanı başka bir kodlama kullanıyorsa (örneğin C veya POSIX yerel ayarıyla kurulmuş sunucularda SQL_ASCII), CREATE DATABASE komutuna `TEMPLATE template0` ekleyin. Kurulum sihirbazındaki **Bağlantıyı dene** düğmesi kodlama UTF8 değilse uyarır: böyle veri tabanlarında Ç, Ğ, İ, Ö, Ş, Ü gibi harflerle yapılan aramalarda büyük/küçük harf ayrımı gözetilir. Yerel ayarın (LC_COLLATE, LC_CTYPE) önemi yoktur; aramalar C dahil her yerel ayarda büyük/küçük harf ayrımı gözetmez.

```
-- template1 UTF8 değilse:
CREATE DATABASE erp OWNER erp ENCODING 'UTF8' TEMPLATE template0;
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
- Ondalık ve para değerleri tam olarak saklanır (DECIMAL sütunları; SQLite'ta sayısal olarak sıralanan metin olarak).
- Veri tanımlarındaki metinlerin en fazla uzunlukları sabittir: başlık ve etiketler 200 karakter, varsayılan değerler ve seçenekler 255, yardım metinleri 500. Formlar bunları denetler; böylece hiçbir veri tabanı sistemi bir değeri reddetmez.
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

## Güncellemeler

Program başlarken veri tabanını kendiliğinden güncel şema sürümüne getirir. Yeni bir sürüm kurmadan önce tam yedek alın.

| Şema sürümü | Değişiklik |
|---|---|
| 1 | İlk sürüm |
| 2 | Yalnızca SQLite: ondalık ve para sütunları tam saklamaya dönüştürülür (daha önce yuvarlanmış basamaklar geri gelmez) |

## Güvenlik

- Parolalar: scrypt özetleri; oturumlar: SHA-256 özeti olarak saklanan rastgele belirteçler, imzalı çerezler (HttpOnly, SameSite).
- Formlar siteler arası istek sahteciliğine (XSRF) karşı korunur.
- Sayfalar sıkı bir İçerik Güvenliği Politikası (CSP) gönderir; yüklenen resim ve videolar içeriklerine göre denetlenir.
- API anahtarları SHA-256 özetleri olarak saklanır; veri ekranı, haklar, IP ağı, süre ve geçerlilik sonu ile sınırlandırılabilir.
- Giriş denemeleri sınırlıdır.
- Yüklenen dosyalar kendi kısıtlayıcı (sandbox) İçerik Güvenliği Politikasıyla gönderilir; belgeler her zaman indirilir.
- Girişten sonra dönülecek adresler denetlenir; bağlantılar kullanıcıları başka sitelere götüremez.
