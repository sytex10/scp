# 🎬 AI YouTube Scenepack Maker (Yapay Zeka Yüz Tanımalı Sahne Paketi Oluşturucu)

YouTube oynatma listelerinden (playlist) veya tekil video linklerinden hedef karakterlerin (**örneğin: Polat Alemdar ve Süleyman Çakır**) bulunduğu sahneleri tespit eden, yapay zeka ile yüz tanıması yapan ve onaylanan sahneleri doğrudan YouTube'dan **orijinal yüksek kalitede (1080p/2K/4K)** kesip kaydeden otomasyon aracı.

---

## ⚡ Neden Bu Kadar Hızlı ve Verimli? (Mimari Mantığı)

1 saatlik bir videoyu veya 20 bölümlük bir oynatma listesini tam çözünürlükte indirmek yüzlerce gigabayt yer ve saatler alır. Bu araç şu 3 kademeli optimizasyonu kullanır:

1. **Ultra Hızlı 360p Proxy Akışı:** Video ilk etapta yalnızca 360p (küçük dosya boyutu, ~100MB) olarak geçici indirilir.
2. **PySceneDetect ile Milisaniyelik Sahne Tespiti:** Kamera açıları ve sahne kesmeleri `ContentDetector` ile anında saptanır. 
3. **Kare Örnekleme (Sample Rate):** Her saniyeden yalnızca 1-2 kare örneklenerek DeepFace / Face Recognition motoruyla taranır.
4. **Kayıpsız & Doğrudan YouTube'dan Kesme (Section Download):** Tüm bölümü tekrar indirmek yerine `yt-dlp --download-sections "*start-end"` ve `ffmpeg` kullanılarak **sadece onaylanan 10-20 saniyelik sahne 1080p kalitesinde** YouTube'dan çekilir.

---

## 📁 Proje Dizin Yapısı

```text
ai-scenepack-maker/
├── characters/                # Hedef karakter fotoğrafları klasörü
│   ├── Polat/                 # polat1.jpg, polat2.jpg...
│   └── Cakir/                 # cakir1.jpg, cakir2.jpg...
├── output_scenepacks/         # Kesilen yüksek kaliteli MP4 sahneleri ve JSON raporu
├── temp_cache/                # Geçici 360p proxy videoları (otomatik temizlenir)
├── config.py                  # Çözünürlük, eşik değerleri ve ayarlar
├── downloader.py              # yt-dlp & FFmpeg indirme ve parça kesme motoru
├── scene_detector.py          # PySceneDetect kamera geçiş tespiti
├── face_matcher.py            # DeepFace / face_recognition eşleştirme motoru
├── scenepack_engine.py        # Ana orkestrasyon ve ilerleme çubuğu
├── main.py                    # CLI ve İnteraktif Sihirbaz
└── requirements.txt           # Gerekli Python kütüphaneleri
```

---

## 🛠️ Kurulum Adımları

### 1. Sistem Gereksinimi: FFmpeg
Sisteminizde FFmpeg kurulu olmalıdır. Terminalde kontrol edin:
```bash
ffmpeg -version
```
*(Windows'ta kurulu değilse `winget install Gyan.FFmpeg` veya ffmpeg.org adresinden kurabilirsiniz.)*

### 2. Python Kütüphanelerini Yükleme
```bash
cd ai-scenepack-maker
pip install -r requirements.txt
```

> **Not:** Windows'ta `deepface` (TensorFlow/OpenCV backend) hazır kurulur ve ek bir C++ derleyicisi istemez. Eğer `face_recognition` kullanmak isterseniz `pip install face_recognition` yapabilirsiniz.

---

## 🚀 Kullanım Yöntemleri

### Yöntem 1: Modern Web & Stüdyo Arayüzü (Önerilen 🌟)
Tek bir komutla tarayıcınızda çalışan görsel stüdyo panelini başlatın:
```bash
python app.py
```
👉 Tarayıcınızda açın: **`http://localhost:5000`**

**Arayüzün Sunduğu Özellikler:**
* **Doğrudan Video İçinden Yüz Seçici:** Zaman çubuğunu (timeline slider) kaydırın, "Bu Karedeki Yüzleri Tara" deyin; ekrandaki yüzler kartlar halinde gelsin, tek tıkla adını yazıp ekleyin!
* **Karakter Yönetimi:** Eklenen yüzleri önizleyin, silin veya yenilerini ekleyin.
* **Canlı İlerleme Çubuğu:** Proxy indirme, sahne analizi ve yapay zeka yüz tarama aşamalarını yüzde olarak canlı izleyin.
* **Tek Tıkla Klasör Açma:** Kesilen sahneleri doğrudan Windows Gezgini'nde açın veya tarayıcıdan önizleyin.

---

### Yöntem 2: Terminal / Konsol İnteraktif Sihirbazı
Konsolda soru-cevap ile ilerlemek isterseniz:
```bash
python main.py
```
> **🌟 Doğrudan Video İçinden Seçim:** Karakter fotoğrafınız yoksa sihirbazda `[3] DOĞRUDAN VİDEO İÇİNDEN SEÇ` seçeneğini belirleyin!
> - **Görsel Pencere ile:** Klavyeden `A/D` tuşlarıyla videoyu sarın, karakteri gördüğünüzde `BOŞLUK` tuşuna basın. Program ekrandaki yüzleri yeşil kutuya alıp `1, 2, 3..` şeklinde numaralandırır. Tuşa basıp adını yazmanız yeterlidir!
> - **Zaman Damgası ile:** Sadece karakterin göründüğü dakikayı girin (örn: `03:45`). Program otomatik yüzü kırpar ve hafızaya alır.

### Yöntem 2: Hızlı Klasör Taramalı CLI
Karakter fotoğraflarınızı `characters/Polat` ve `characters/Cakir` içerisine koyduktan sonra:
```bash
# Polat VEYA Çakır'ın olduğu sahneler (OR Modu)
python main.py -u "https://www.youtube.com/playlist?list=PLAYLIST_ID" --chars-dir characters/ --logic OR

# Yalnızca Polat VE Çakır'ın AYNI ANDA / AYNI SAHNEDE olduğu ikili sahneler (AND Modu)
python main.py -u "https://www.youtube.com/watch?v=VIDEO_ID" --chars-dir characters/ --logic AND
```

### Yöntem 3: CLI ile Doğrudan Videodan Yüz Seçme
```bash
# Görsel oynatıcı açarak videodan yüz seç ve tarat:
python main.py -u "https://www.youtube.com/watch?v=VIDEO_ID" --pick-gui

# Belirli bir dakika:saniyeden yüzü otomatik kırpıp tarat:
python main.py -u "https://www.youtube.com/watch?v=VIDEO_ID" --pick-at "02:15" --pick-name "Polat"
```

---

## ⚙️ Parametreler ve İnce Ayarlar

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `-u`, `--url` | - | YouTube Video veya Playlist Linki |
| `--items` | `all` | Playlistten seçilecek videolar (örn: `1`, `1,3,5`, `1-5` veya `all`) |
| `--chars-dir` | - | Otomatik karakter alt klasörlerini okur (`characters/Isim/*.jpg`) |
| `--logic` | `OR` | `OR`: Biri varsa al, `AND`: İkisi de varsa al |
| `--min-duration` | `2.0` | Saniyeden kısa sahneleri atlar (hızlı kurgu hatalarını önler) |
| `--sample-fps` | `1.0` | Her sahneden saniyede kaç kare örneklenip taranacak |
| `--threshold` | `0.40` | Cosine benzerlik eşiği (0.35 daha katı, 0.45 daha esnek) |
| `--quality` | `1080p` | Nihai kesilen sahnelerin kalitesi (`1080p`, `720p`, `best`) |
| `--cookies` | - | YouTube bot koruması/yaş sınırı için `cookies.txt` yolu |
| `--cookies-browser` | - | Tarayıcı çerezleri (`chrome`, `edge`, `firefox`) |

---

## 🎞️ Çıktı Dosyaları & Kurgu Programı Entegrasyonu

Oluşturulan sahneler `output_scenepacks/` klasörüne kurgucuların (After Effects, Premiere Pro, CapCut, DaVinci Resolve) doğrudan kullanabileceği şekilde isimlendirilir:
```text
Scenepack_KurtlarVadisi_B01_S012_Polat_02m14s-02m38s.mp4
Scenepack_KurtlarVadisi_B01_S045_Polat_Cakir_12m05s-12m54s.mp4
```

Ayrıca her tarama sonrasında `scenepack_report.json` dosyası oluşturulur; bu dosyada hangi saniyede hangi karakterin çıktığı ve benzerlik skorları döküm olarak yer alır.
