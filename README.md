# Global Capital Radar
Yabancı yatırımcıların ABD hisseleri, Hazine kâğıtları ve uzun vadeli şirket borcundaki aylık net alımlarını izler. TIC kapsamı tüzel ikametgâha dayanır. İşlemler nihai yatırımcıyı ve satılan paranın sonraki adresini açıklamaz. Şirket borcu kategorisi belediye borcunu da kapsar.

## Kullanım
Python 3.10+ ile proje kökünde `python3 -m unittest -v`, ardından `python3 radar.py` çalıştırın. Standart kütüphane yeterlidir. Veriler internetten alınır. Actions iş akışı günlük ve elle çalışır. Varsayılan dala yazma izni gerekir. LATEST.md son raporu, history/ tarihli gözlemleri ve dondurulmuş tahminleri içerir. Kısmi veri kaydedilir, gecikme veya kaynak hatası çalışmayı başarısız işaretler.

## Ölçüm
catalog.csv kaynak kimliklerini içerir. FRED üzerinden piyasa, enerji, dış ticaret fiyatları, ücret, kredi, enflasyon ve TIC serileri okunur. IMF DataMapper PCPIPCH/WEOWORLD aynı hedef yıla ait dünya ortalama tüketici fiyat enflasyonu tahminini, FEDTARMD katılımcıların yıl sonu medyanını verir. Tahmin eğrilerindeki yıllar yayın tarihi değildir. Dünya Bankası FM.LBL.BMNY.GD.ZS dünya geniş para stokunun GSYH’ye oranını verir. ABD M2 seviyesi, dolar endeksi ve kredi anketi ayrı okunur. SLOOS artışı sıkılaşmadır. VIX, kredi risk primi ve NFCI son ayda birlikte düşerse risk iştahı güçleniyor etiketi verilir. Bu etiket bir model olasılığı değildir.

1G son gözlemden önceki işlem gününe, 1H yedi takvim günü öncesine, diğer sütunlar takvim aylarına göre hesaplanır. Tatil ve hafta sonunda önceki uygun gözlem kullanılır. Aylık seride günlük ve haftalık değişim boş kalır. Akış sütunları iki ayın net alım tutarları arasındaki farktır. TÜFE ve PCE endekslerinde 1Y sütunu yıllık fiyat artışını gösterir. Birikimli akım ve değişim farklı büyüklüklerdir. Eski tarihli satırların yanına gecikme işareti konur.

## İleri test
Her ay ilk kullanılabilir çalışmada bir sonraki tam takvim ayı için üç varlık sınıfının net alım tutarı dondurulur. Tahmin son üç ardışık yayımlanmış ayın medyanıdır. Karşılaştırma modeli son açıklanan tutarı tekrarlar. İşlem ayı tamamlandıktan sonra ilk görülen gerçekleşme saklanır. Model ve karşılaştırmanın ortalama mutlak hatası her sınıf için ayrı raporlanır. Eski veriler sonradan revize edilebilir. İlk kurulumda indirilen tarihsel değerler geçmişte biliniyormuş gibi test edilmez. Aynı gün tekrar çalıştırma günlük özeti günceller, mevcut aylık tahmini değiştirmez.

## Kapsamın genişletilmesi
Makro seriler ilk sürümde koşulları açıklar. İleri testte örnekler biriktikten sonra alternatif modelin dolar, reel faiz ve kredi koşullarından katkı sağlayıp sağlamadığı karşılaştırılabilir. IMF ve Fed aynı hedef yıl için farklı tarihlerde kaydedilen eğriler üzerinden değerlendirilmeli. Sonraki takvim ayının CME Fed fonları kontratı Yahoo Finance üzerinden okunur. Fiyattan ima edilen ortalama efektif faiz 100 eksi kontrat fiyatıdır. Farklar aynı kontrat içinde baz puanla hesaplanır. Bu ölçü tek bir toplantının faiz indirim olasılığını vermez. ICI haftalık birleşik tablosu ABD hissesi, dünya hissesi, karma, tahvil ve emtia fonlarının tahmini net akışını ayrı verir. Buradaki fon evreni ve TIC kapsamı farklıdır. Tutarlar toplanmaz. Offshore dolar kredisi için BIS GLI, arz şoku için navlun ve ticaret hacmi sonraki kapsamdadır. Tarihli gözlem ve tahmin kayıtlarını saklayın.

## Kaynaklar
- https://fred.stlouisfed.org/series/FORTREASNET69995
- https://fred.stlouisfed.org/series/FORLTEQTYNET69995
- https://fred.stlouisfed.org/series/FORLTCORPNET69995
- https://fred.stlouisfed.org/series/FEDTARMD
- https://www.imf.org/external/datamapper/PCPIPCH@WEO/WEOWORLD
- https://data.worldbank.org/indicator/FM.LBL.BMNY.GD.ZS

## Yatırım evreni ve ortak rapor
`python3 rotation.py` ile ROTATION.md, history/rotation/latest.json ve zaman damgalı gözlem üretilir. Günlük Actions her iki raporu da çalıştırır. Streamlit ve Telegram için ortak girdi latest.json dosyasıdır.

SPY, QQQ, IWM ve DIA kendi endeks fonlarının talebini gösterir. SGOV kısa vadeli dolar faizini elde etmek isteyenlerin kullanabildiği bono fonudur. SHY daha uzun vade taşır. Fed faizi ve vadeli faiz beklentisi makro rapordadır. GLD ve SLV kıymetli metal, CPER ve USO vadeli emtia fonlarıdır. IBIT ile ETHA ABD borsasında işlem gören iki kripto fonudur. Tek fonla izlenen bir piyasada yatırımcı diğer fonlara veya spot varlığa geçmiş olabilir. İki satırdaki eşzamanlı hareket aynı yatırımcının parayı birinden diğerine aktardığını kanıtlamaz.

ETF Database verisinden günlük net akımlar alınır. Rapor dönem içindeki akımları toplar. Son gözlem tarihi her satırda görünür. Haftalık yüzdelik, fonun son haftaki akışını önceki 52 haftalık dağılımda konumlandırır. Büyük ve küçük fonların kendi geçmişine göre olağandışı hareketi böyle incelenebilir. Açık pozisyonun yüzdesi olarak CFTC ticari olmayan net uzun pozisyonu (uzun eksi kısa) hesaplanır. Haftalık değişim yüzde puandır. Türev pozisyonu nakit akışına eklenmez. CFTC tarihi pozisyon tarihidir. Arşivdeki seen_at sistemin ilk kullanabileceği zamanı gösterir.

Haftalık ve aylık nakit akışı pozitifse GİRİŞ İZLE, negatifse ÇIKIŞ İZLE. Vadeli pozisyon değişimi de aynı yöndeyse ALIM ADAYI veya AZALTMA ADAYI etiketi verilir. SGOV için vadeli teyit kullanılmaz. Çelişkili akışlar BEKLE, yetersiz veya gecikmiş veri ayrı durum üretir. Aday etiketleri ileriye dönük araştırma içindir. İşlem getirisi ve maliyet sonrası başarı henüz doğrulanmadı. Telegram ve Streamlit yayını sonraki aşamadır.

Kaynaklar
- https://etfdb.com/etf/GLD/ (diğer fonlar için her kayıtta kaynak URL bulunur)
- https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm

Beş seanslık ileri testi çalıştırmak için `python3 evaluate_rotation.py` kullanılır. FORWARD.md ve history/rotation/outcomes.json sonuçları tutar. Ölçüm gözlem tarihinden sonraki ilk seansın açılışında başlar. Getiri, SGOV ile aynı tarihlerde karşılaştırılır. Komisyon ve kayma dahil değildir. Hangi sinyalin maliyet sonrası kullanılabilir olduğu ayrıca sınanmalıdır.

## Vadeye göre yorum
ROTATION.md içinde 1 hafta, 1 ay, 3 ay ve 1 yıl için ayrı tablo bulunur. Mutlak net dolar akışı fonun aynı uzunluktaki son 52 ayrı dönemine kadar karşılaştırılır. En az beş geçerli geçmiş dönem gerekir. Yeni fonların yıllık gücü yeterli tarih oluşana kadar boş kalır. Yüzdelik 15 ve altı yatay, 40 ve altı zayıf, 75 ve üzeri güçlü, 90 ve üzeri olağanüstüdür. Bunlar araştırma için seçilmiş eşiklerdir. Tarihsel dolar tutarları fonun büyümesine göre düzeltilmemiştir. Her vade için CFTC net pozisyon payının o vadedeki değişimiyle yön kontrol edilir. Uyuşmazlık, eski veya eksik veri TEYİTSİZ ve BEKLE sonucu üretir. Yön uyumu, ETF dolar tutarının ikinci bir kaynaktan doğrulandığı anlamına gelmez. Eski haftalık/aylık birleşik etiketin ileri testi ayrı sürer. Vade bazlı yeni eşiklerin işlem başarısı doğrulanmamıştır.

## Streamlit ve Telegram kurulumu
Streamlit Community Cloud üzerinde repo ve main dalını seçin. Giriş dosyası streamlit_app.py. Sayfa kaydedilmiş raporu okur. Sonuçlar GitHub Actions çalıştıkça güncellenir.

GitHub Settings → Secrets and variables → Actions → New repository secret altında TELEGRAM_BOT_TOKEN (BotFather tarafından verilen anahtar) ve TELEGRAM_CHAT_ID (hedef sohbetin sayısal kimliği) tanımlanır. Kişisel sohbet için önce bota /start gönderin. Ardından radar iş akışını elle çalıştırabilirsiniz. Telegram adımı bugünün varlık raporu kaydedildikten sonra vade özetini gönderir. İki secret da boşsa adımı atlar.

SGOV için en yakın vadeli araç CME 13 haftalık bono kontratı TBF3’tür. Fiyatı 100 eksi iskonto faizidir. 22 Kasım 2026 incelemesinde CFTC Legacy ve TFF Futures Only veri kümelerinin 2025 başından itibaren yayımlanan piyasa listelerinde bono kontratına ait pozisyon serisi bulunamadı. SGOV fon akışı gösterilir, pozisyon teyidi eksik kalır. Kaynak: https://www.cmegroup.com/markets/interest-rates/stirs/us-t-bill/specs.html

FORWARD.md her vadenin aday kararını ilgili hafta veya ay süresi sonunda SGOV ile karşılaştırır. Yönlü fark komisyon ve kayma öncesidir. Geçmiş akış yüzdeliği bir başarı olasılığı değildir. Dokuz geçmiş yıl içindeki en yüksek akış yüzde 100 sıralama alabilir. Bu değer dokuz karşılaştırma ve tek yeni gözleme dayanır.

Fiyat bağlamı SGOV ile aynı kapanış tarihinde dağıtım ve bölünme düzeltilmiş getiriyi hesaplar. Fon büyüklüğüne oranlanmış akış, net dolar akışının dönem başındaki fon varlığına bölümüdür. Göreli sıra yalnız veri bulunan fonlar arasındadır. Fiyat tek başına ve fiyat + akış araştırma modelleri ayrı kaydedilir. RSP/SPY genişlik ve gümüş/altın göreli getirisi yardımcı veridir. Dolar ve reel faiz değişimleri kaynak tarihleriyle taşınır. TBF3, bakır depo stokları, petrol vade farkı ve kripto vadeli primi için doğrulanmış otomatik kaynak entegrasyonu henüz tamamlanmamıştır.

Öncü yöntem deneyi early-v1 üç yöntemi aynı tarihlerde izler. Akış, akış + vadeli pozisyon, akışın komşu vadede sürmesi. Yeni kayıtlar karar anında dondurulur. Eski raporlara sonradan aday eklenmez. Fiyat giriş şartı değildir. Her varlık ve vadede örtüşmeyen dönemler puanlanır. BEKLE puanı sıfırdır. Toplam geçiş maliyeti 10 baz puan varsayılmıştır. En az 30 dönem gerekir. İlk dönemlerde seçilen yöntem son 10 dönemde sınanır. Son 10 dönemin en az yedisinde pozitif puan ve ortalama için yaklaşık iki standart hatalık alt sınırın pozitif olması seçim şartıdır. Bu araştırma eşikleri başarı garantisi vermez. Yıllık vadede yeterli bağımsız gözlem çok uzun sürede oluşur. history/method_selection.json seçimi kaydeder. Doğrulama yeterli olana kadar mevcut yöntem kullanılır.

Telegram ilk kez güçlü giriş oluştuğunda, giriş olağanüstü seviyeye geçtiğinde veya ekonomik karar değiştiğinde bildirim gönderir. İlk kurulumda güçlü girişler gönderilir, diğer kararlar başlangıç olarak kaydedilir. Veri arızası karar değişimi bildirimi üretmez. Kaynak hataları Actions ve history/validation.json içinde görünür. API başarısından sonra gönderim durumu dosyaya kaydedilir. Ağ yanıtının kaybolduğu veya GitHub kaydının başarısız olduğu istisnalarda yeniden gönderim oluşabilir. Kapsam kontrolü tamamlanmamış kaynakları açıkça listeler.

Otomatik yöntem etkinleştirme günlük değerlendirme sonunda history/method_selection.json dosyasına kaydedilir. Sonraki tarama varlık ve vade için doğrulanmış yöntemi kullanır. Seçim ve geri dönüşlerin gerekçeleri history/method_changes.json içinde tutulur. Eksik fiyat kaynağı nedeniyle önceki örneklerin hesaplanamaması mevcut seçimi silmez. Yeni yeterli değerlendirmede doğrulamayı geçemeyen yöntem için varsayılan flow_position kullanılır. Bu geçiş önceden tanımlı üç yöntem arasında gerçekleşir. Streamlit etkin yöntemi ve örnek sayısını gösterir. Karar değişirse Telegram'ın mevcut karar değişimi filtresi çalışır.
