# ERP-Software Kullanım Kılavuzu

ERP-Software sade, web tabanlı bir ERP sistemidir. **Hiçbir veri alanı hazır gelmez**: veri ekranlarını (örneğin müşteriler, ürünler, faturalar veya sensör ölçümleri) ve alanlarını kendiniz tanımlarsınız. Program tamamen klavyeyle kullanılabilir.

Kılavuzun diğer sayfaları:

- [REST API ve sensörler](API.md)
- [Dışa aktarma, yedekleme ve geri yükleme](BACKUP.md)
- [Veri tabanı sistemleri ve işletim](DATABASES.md)

## Gereksinimler

- Python 3.13 veya üstü
- Tornado 6.4 veya üstü
- İsteğe bağlı bir veri tabanı sürücüsü: PyMySQL (MySQL, MariaDB), pyodbc veya pymssql (Microsoft SQL Server), psycopg (PostgreSQL). SQLite Python'la birlikte gelir.

## Kurulum

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install PyMySQL            # yalnızca MySQL / MariaDB için
python3 -m erp --host 0.0.0.0 --port 8888
```

Paketi `pip install .` (veya `pip install ".[mysql]"`, `".[mssql]"`, `".[postgresql]"`) ile kurup `erp-software` komutuyla da başlatabilirsiniz.

Komut satırı seçenekleri:

| Seçenek | Anlamı |
|---|---|
| `--config DOSYA` | Kurulum yapılandırma dosyası (varsayılan `instance/erp.toml` veya `ERP_CONFIG` ortam değişkeni) |
| `--host ADRES` | Dinlenecek adres (varsayılan `127.0.0.1`) |
| `--port PORT` | Port (varsayılan `8888`) |
| `--debug` | Ayrıntılı hata sayfalarıyla geliştirme kipi |

## İlk başlatma: kurulum sihirbazı

Yapılandırma dosyası yoksa program **kurulum kipinde** başlar. Bütün sayfalar `/setup` adresine yönlenir ve sunucu konsoluna tek kullanımlık bir **kurulum anahtarı** yazılır:

```
WARNING erp: Setup mode: open http://127.0.0.1:8888/setup
WARNING erp: Setup token: 3hF0c...
```

Sihirbazda şunları girersiniz:

1. kurulum anahtarı,
2. arayüz dili ve şirket adı,
3. veri tabanı sistemi ve bağlantı bilgileri (önce **Bağlantıyı dene** düğmesini kullanın),
4. ilk yönetici hesabı,
5. varsayılan karakter kümesi, saat dilimi, para birimi ve yükleme dizini.

**Kur** düğmesi tabloları, yöneticiyi ve yalnızca sahibinin okuyabildiği `instance/erp.toml` dosyasını oluşturur. Program kurulum kipinden hemen çıkar; `/setup` artık açılamaz. Sihirbazı yeniden çalıştırmak için sunucuyu durdurup yapılandırma dosyasını silin. Seçilen veri tabanında zaten bir ERP-Software kurulumu varsa korunur.

## Giriş, kullanıcılar ve yetkiler

Birden fazla kişi aynı anda çalışabilir; her kullanıcının kendi oturumu vardır. Üç yetki vardır:

| Yetki | Haklar |
|---|---|
| Yönetici | Her şey: veri tanımları, menüler, kullanıcılar, API anahtarları, ayarlar, yedekler ve bütün veriler |
| Normal kullanıcı | Veri ekranlarıyla çalışır; erişim her ekran için “okuma ve yazma”, “yalnızca okuma” veya “erişim yok” olarak belirlenir |
| Bayi | Yalnızca bayilere açılan ekranları görür; her ekran için “yalnızca okuma” veya “yalnızca kendi kayıtları” (bayi kayıt oluşturur ve yalnızca kendi oluşturduğu kayıtları görüp değiştirir) |

Beş başarısız girişten sonra hesap o adres için 15 dakika kilitlenir. Parolalar scrypt özetleri olarak saklanır. Her kullanıcı **Hesabım** bölümünden adını, e-postasını, dilini ve parolasını değiştirebilir.

## Menülerle ve klavyeyle gezinme

Program menülerle kullanılır: ana menü; menü gruplarına, veri ekranlarına, yönetime, hesaba, yardıma ve çıkışa götürür. Her menü öğesinin bir tuşu vardır.

| Tuş | İşlem |
|---|---|
| `1`…`9`, `a`…`z` | O tuşa sahip menü öğesini aç |
| `↑` `↓` `Home` `End` | Menü öğeleri veya tablo satırları arasında gezin |
| `Enter` | Seçili öğeyi veya satırı aç |
| `Esc` | Önceki ekrana dön (veya metin alanından çık) |
| `0` | Ana menü |
| `/` | Listede ara |
| `n` | Yeni kayıt (veya yeni öğe) |
| `e` | Düzenle |
| `Del` | Sil |
| `PgUp` `PgDn` | Önceki / sonraki sayfa |
| `Ctrl+S` veya `Ctrl+Enter` | Formu kaydet |
| `?` veya `F1` | Klavye kısayollarını göster |

Arayüz dili sağ üst köşedeki bağlantılarla (tr-TR, en-US, en-GB) veya **Hesabım** bölümünden her an değiştirilebilir. Türkçede tarihler GG.AA.YYYY, sayılar 1.234,56 ve tutarlar 1.234,56 ₺ biçiminde gösterilir.

## Veri tanımları: kendi veri ekranlarınız

**Yönetim › Veri tanımları** bölümünde (yalnızca yöneticiler):

1. `n` tuşuna basıp bir veri ekranı oluşturun. **Teknik ad** (örneğin `musteriler`) veri tabanı tablosuna `d_musteriler` adını verir ve API'de kullanılır; sonradan değiştirilemez. **Başlık** kullanıcıların gördüğü addır.
2. `n` tuşuyla alanlar ekleyin. Her alanın teknik adı, etiketi ve türü vardır.

Alan türleri:

| Tür | Saklama | Not |
|---|---|---|
| Metin (tek satır) | VARCHAR | en fazla uzunluk 1-4000 |
| Uzun metin | TEXT | çok satırlı |
| Tam sayı | BIGINT | |
| Ondalık sayı | DECIMAL(18, n) | 0-8 ondalık basamak |
| Ölçüm (kayan noktalı) | DOUBLE | sensör değerleri için uygundur |
| Para tutarı | DECIMAL(19, n) | para birimiyle (TRY, USD, EUR, GBP, ...) |
| Evet / Hayır | BOOLEAN | |
| Tarih, Tarih ve saat | DATE, DATETIME | saatler UTC olarak saklanır, ayarlanan saat diliminde gösterilir |
| Seçim listesi | VARCHAR | her satıra bir seçenek |
| E-posta adresi | VARCHAR | denetlenir |
| Başka veri ekranına bağlantı | BIGINT | başka bir ekranın kaydı seçilir |
| Belge, Resim, Video | dosya | yükleme dizininde saklanır |

Diğer seçenekler: zorunlu, benzersiz, listede göster, varsayılan değer, yardım metni ve sıra. Tür, teknik ad ve saklamayla ilgili ayarlar oluşturulduktan sonra değiştirilemez; bunun yerine alanı silip yeniden oluşturun (değerleri silinir).

Veri ekranı ayarları: menü, normal kullanıcı ve bayi erişimi, başlık alanı (başka ekranlar bir kayda bağlandığında gösterilir), sensör/canlı veri, okuma süresi ve sayfa başına satır.

## Menüler

**Yönetim › Menüler** bölümünde menü grupları ve alt menüler (örneğin “Satış › Siparişler”) oluşturursunuz. Veri ekranının tanımında ekranın ait olduğu menüyü seçersiniz. Menü yoksa bütün veri ekranları ana menüde görünür. Kullanıcılar yalnızca açabilecekleri ekranları içeren menüleri görür.

## Kayıtlarla çalışma

- **Liste**: `/` ile arayın, sütun başlığına tıklayarak sıralayın, `PgUp`/`PgDn` ile sayfa değiştirin, `Enter` ile satırı açın.
- **Yeni** (`n`), **Düzenle** (`e`), **Sil** (`Del`). “Kaydet ve yeni” ile hızlıca art arda kayıt girilir.
- **Dosyalar**: belgeler (PDF, ofis belgeleri, metin, CSV, XML, JSON, ZIP, 7z), resimler (PNG, JPEG, GIF, WebP, BMP) ve videolar (MP4, WebM, Ogg, QuickTime). Resim ve videolar içeriklerine göre denetlenir ve kayıtta gösterilir; videolar oynatılabilir ve ileri-geri sarılabilir.
- **Dışa aktar** (`x`): desteklenen her karakter kümesinde CSV, TOML veya SQL.
- **CSV içe aktar** (`i`): ilk satır teknik alan adlarını içerir; sayılarda ondalık ayırıcı olarak `,` veya `.` kullanılabilir.

## Sensörler ve canlı veri

Bir veri ekranını **Sensör / canlı veri** olarak işaretleyip **okuma süresini** milisaniye olarak girin. Ekranda bu süreyle yenilenen ve en yeni kayıtları gösteren bir **Canlı izleme** (`m`) bulunur (süre sayfada değiştirilebilir; `p` duraklatır). Sensörler değerleri REST API veya WebSocket ile gönderir ve ayarlanan süreyi API'den okuyabilir; böylece okuma süresi merkezden ayarlanır. Bkz. [REST API ve sensörler](API.md).

## Ayarlar

**Yönetim › Ayarlar** bölümünde şirket adı, varsayılan dil, dışa/içe aktarmalar için varsayılan karakter kümesi, saat dilimi, varsayılan para birimi, sayfa başına satır, oturum süresi ve REST API anahtarı bulunur. Bütün ayarlar tek formla birlikte kaydedilir; bütün yapılandırma SQL veya TOML olarak indirilebilir (bkz. [Dışa aktarma, yedekleme ve geri yükleme](BACKUP.md)).

## Karakter kümeleri

Program içinde bütün metinler Unicode'dur. Sisteme giren veya çıkan dosyalar (SQL, TOML ve CSV dışa/içe aktarmaları, `charset` parametreli API istekleri) şunları destekler: UTF-8, BOM'lu UTF-8, UTF-16, ASCII, DOS 437, DOS 850, DOS 857 (Türkçe), Windows-1252, Windows-1254 (Türkçe), ISO-8859-1, ISO-8859-9 (Latin-5), ISO-8859-15 ve Mac Türkçe.

## İşlem günlüğü ve sistem bilgisi

**İşlem günlüğü** girişleri; tanım, kullanıcı, API anahtarı ve ayar değişikliklerini; kayıt değişikliklerini, dışa ve içe aktarmaları kaydeder. **Sistem bilgisi** sürümleri, veri tabanını, yapılandırma dosyasını, yükleme dizinini ve kayıt sayılarını gösterir; hiçbir kayda bağlanmamış yüklemeleri silebilir.

## Görünüm

Arayüz bilerek sade tutulmuştur: yalnızca web güvenli renkler (216 renklik palet) ve web güvenli yazı aileleri (Verdana, Tahoma, Arial, Helvetica, Georgia, Times New Roman, Courier New) kullanılır. Dış kaynak gerektirmez; küçük ekranlarda ve yazdırırken de çalışır.
