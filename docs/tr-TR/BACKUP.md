# Dışa aktarma, yedekleme ve geri yükleme

**Yönetim › Dışa aktarma ve yedekleme** bölümünde her şey **SQL** veya **TOML** dosyası olarak indirilebilir.

## Neler dışa aktarılabilir

| Dışa aktarma | İçerik |
|---|---|
| Yapılandırma | Bütün yapılandırma bir bütün olarak: ayarlar, menüler ve veri tanımları (veri ekranları ve alanları) |
| Veri biçimleri | Verilerin olması gereken biçimleri: veri ekranları ve alanları ile tablolarının CREATE TABLE komutları (SQL) |
| Veriler | Seçilen veri ekranlarının kayıtları (ve dosyalarının bilgileri) |
| Tam veri tabanı yedeği | Bütün veri tabanı: yapılandırma, veri biçimleri, veriler, kullanıcılar (parola özetleriyle), API anahtarları (yalnızca özetleri), dosya bilgileri ve işlem günlüğü |

Tek bir veri ekranı kendi listesinden de (`x`) CSV, TOML veya SQL olarak dışa aktarılabilir.

## Seçenekler

- **Dosya biçimi**: TOML (okunabilir, taşınabilir, yeniden içe aktarılabilir) veya SQL.
- **SQL lehçesi**: SQLite, MySQL, MariaDB, Microsoft SQL Server veya PostgreSQL. SQL dosyası o veri tabanı sisteminin aracıyla doğrudan çalıştırılabilir; örneğin `mysql erp < yedek.sql`, `psql -d erp -f yedek.sql`, `sqlcmd -i yedek.sql` veya `sqlite3 erp.sqlite3 < yedek.sql`. Böylece bir kurulum başka bir veri tabanı sistemine taşınabilir.
- **Karakter kümesi**: UTF-8, ASCII, DOS 437, DOS 850, DOS 857, Windows-1252, Windows-1254, ISO-8859-1/9/15, Mac Türkçe, UTF-16. Dosya bir `charset:` açıklamasıyla başlar. TOML, seçilen karakter kümesinde bulunmayan karakterleri `\uXXXX` kaçışlarıyla yazar; böylece hiçbir şey kaybolmaz. SQL bunları `?` ile değiştirir.
- **Dosya içeriklerini ekle** (TOML): yüklenen belge, resim ve videolar base64 olarak gömülür. Bu seçenek olmadan yükleme dizinini de ayrıca yedekleyin.

## SQL dosyası ne yapar

- Yapılandırma ve veri biçimleri: eksik tabloları oluşturur, ardından yapılandırma tablolarının satırlarını değiştirir.
- Veriler: eksik tabloları oluşturur, dışa aktarılan veri ekranlarının kayıtlarını silip yeniden ekler.
- Tam yedek: bütün tabloları silip yeniden oluşturur, ardından her şeyi ekler.

Komutlar, veri tabanı sisteminin izin verdiği ölçüde tek bir işlem (transaction) içinde çalışır. MySQL ve MariaDB'nin tablo değişikliklerini (DDL) hemen kalıcı hale getirdiğini unutmayın.

## TOML yapısı

```
# charset: utf-8
[backup]
format = "erp-software"
kind = "full"
schema_version = 1

[settings]
company_name = "Örnek A.Ş."

[[menus]]
id = 1
title = "Satış"

[[entities]]
name = "musteriler"
label = "Müşteriler"

[[entities.fields]]
name = "unvan"
field_type = "text"

[[data.musteriler]]
id = 1
unvan = "Örnek Ticaret A.Ş."
created_at = 2026-11-12T10:15:00
```

Eksik değerler NULL anlamına gelir. Ondalık ve para değerleri tam kalmaları için dizge olarak yazılır.

## İçe aktarma ve geri yükleme

**Yönetim › Dışa aktarma ve yedekleme › İçe aktar / geri yükle** TOML dışa aktarımlarını kabul eder:

- **Yapılandırma**: ayarları ve menüleri değiştirir; eksik veri ekranlarını ve alanları oluşturur, var olanları günceller. Mevcut veriler korunur.
- **Veri biçimleri**: eksik veri ekranlarını ve alanları oluşturur, var olanları günceller.
- **Veriler**: “Kayıtları ekle” kayıtları yeni kimliklerle ekler; “Değiştir” dosyadaki veri ekranlarının kayıtlarını siler ve özgün kimlikleriyle geri yükler. Geçerli tanıma uymayan satırlar atlanır.
- **Tam yedek**: “Bütün veri tabanını değiştir” kutusu işaretlendikten sonra mevcut BÜTÜN içerik değiştirilir. Herkesin oturumu kapanır; yedekteki bir hesapla giriş yapın.

Karakter kümesi `charset:` açıklamasından okunur; elle de seçilebilir. Her içe aktarmadan önce yedek alın.

## Önerilen yedekleme düzeni

1. Düzenli olarak dosya içerikleriyle birlikte TOML biçiminde veya yükleme dizininin bir kopyasıyla birlikte SQL biçiminde **tam veri tabanı yedeği** indirin.
2. Ek olarak veri tabanı sisteminizin yedekleme araçlarını kullanın (`mysqldump`, `pg_dump`, SQL Server yedekleri).
3. `instance/erp.toml` dosyasını güvenli tutun: veri tabanı parolasını ve çerez gizli anahtarını içerir.
