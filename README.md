# Facebook Scraper - Inovasi Sumba

## 📋 Deskripsi

Aplikasi scraper untuk mengekstrak data bisnis dari grup Facebook, khususnya fokus pada:
- Nomor WhatsApp
- Harga produk/jasa  
- Lokasi geografis (Kecamatan Sumba Barat & Tengah)

## ✨ Fitur Utama

- ✅ **Scraping otomatis** dari posts grup Facebook
- ✅ **Alur login kombinasi**: login manual di Chromium terlihat, lalu scraping lanjut headless setelah session valid
- ✅ **Ekstraksi data smart** dengan regex patterns yang akurat
- ✅ **Deduplication** untuk menghindari data duplikat
- ✅ **Error handling & retry logic** untuk stabilitas
- ✅ **Logging detail** untuk debugging
- ✅ **Security improvements** - no hardcoded credentials
- ✅ **Config file terpisah** untuk flexibility
- ✅ **Performance optimized** - reduced timeouts

## 🚀 Instalasi

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Atau manual:
```bash
pip install playwright pandas python-dotenv
playwright install chromium
```

### 2. Setup Environment Variables

Copy `.env.example` menjadi `.env`:
```bash
cp .env.example .env
```

Edit `.env` dan tambahkan credentials (opsional):
```
FACEBOOK_EMAIL=your_email@gmail.com
FACEBOOK_PASSWORD=your_password
TARGET_GROUP_URL=https://www.facebook.com/groups/YOUR_GROUP_ID
```

**Catatan:** Jika tidak set di `.env`, aplikasi akan meminta credentials saat dijalankan.

## 📖 Cara Penggunaan

### Mode Web GUI (Direkomendasikan)

1. Install dependency:
```bash
pip install -r requirements.txt
```

2. Jalankan aplikasi web:
```bash
python web_app.py
```

3. Buka browser:
```text
http://localhost:5000
```

4. Dari dashboard:
- Pilih mode `search`, `marketplace`, atau `groups`
- Isi kata kunci jika mode `search`
- Jika mode `marketplace`, pilih `Kabupaten` lalu `Kecamatan` (otomatis sesuai kabupaten), isi keyword, dan radius
- Isi email/password jika session login belum valid
- Opsional: centang `Simpan hanya post yang punya nomor telepon`
- Klik `Start Scraping`
- Pantau progress realtime sampai selesai

Catatan:
- Jika session belum valid, aplikasi akan membuka Chromium terlihat untuk login manual dan verifikasi CAPTCHA/2FA.
- Setelah login berhasil dan session tersimpan, scraping berikutnya berjalan di Chromium headless (background).
- File hasil scraping bisa diunduh langsung dari dashboard saat job selesai.

### Cara Dasar

```bash
python scrap.py
```

### Web GUI Dashboard (Recommended)

Jalankan aplikasi web:

```bash
python web_app.py
```

Lalu buka browser:

```text
http://127.0.0.1:5000
```

Fitur dashboard:
- Menjalankan scraping dari website (mode search / marketplace / groups)
- Login awal bisa tampil di jendela Chromium untuk verifikasi manual
- Setelah session valid, Chromium scraping berjalan headless di background
- Progress bar + log realtime
- Download hasil CSV langsung dari UI

Catatan:
- Isi email/password jika session login belum valid.
- Jika muncul verifikasi gambar/CAPTCHA, selesaikan di browser yang terbuka lalu tunggu session terdeteksi.
- Jika session sudah valid, bisa jalan tanpa isi password.

### Dengan Custom Parameter

Buka `config.py` dan ubah:
```python
NUM_SCROLLS = 15          # Jumlah scroll iterations
SLOW_MO = 200             # Delay per action (ms)
SCROLL_WAIT_TIME = 2000   # Wait time after scroll (ms)
TARGET_GROUP_URL = "https://www.facebook.com/groups/XXXX"
```

### Modes

- **Interactive Login Mode** (default untuk login): Browser terlihat dipakai untuk login manual dan verifikasi jika session belum valid
- **Headless Scraping Mode**: Setelah login berhasil, scraping berjalan di Chromium background
- **Silent Mode**: Set credentials di `.env`/environment dan gunakan session yang sudah tersimpan

Untuk mode web (`web_app.py`), aplikasi memakai dua fase: visible browser untuk login manual jika diperlukan, lalu headless browser untuk scraping.

## 📁 Struktur File

```
.
├── scrap.py              # Main scraper script (improved)
├── config.py             # Configuration file
├── utils.py              # Utility functions untuk data extraction
├── .env.example          # Template environment variables
├── .env                  # Environment variables (CREATE FROM EXAMPLE)
├── requirements.txt      # Python dependencies
├── fb_session/           # Chrome session data (auto-created)
├── fb_scraper.log        # Log file
└── inovasi_sumba_*.csv   # Output file
```

## 🔧 File Konfigurasi: `config.py`

### Browser Settings
```python
HEADLESS_MODE = False              # false = visible window saat login manual
SLOW_MO = 300                      # delay per action
BROWSER_TIMEOUT = 90000            # page load timeout
PAGE_LOAD_TIMEOUT = 60000          # group page timeout
```

### Scraping Settings
```python
NUM_SCROLLS = 10                   # iterations
SCROLL_DEPTH = 3000                # pixels per scroll
SCROLL_WAIT_TIME = 3000            # wait after scroll (ms)
```

### Data Extraction
```python
WHATSAPP_PATTERN = r'...'          # regex untuk WhatsApp
PRICE_PATTERN = r'...'             # regex untuk harga
REQUIRED_KEYWORDS = [...]          # filter keywords
```

## 📊 Output

Hasil scraping akan disimpan sebagai CSV dengan columns:

| Column | Deskripsi |
|--------|-----------|
| `tanggal_ambil` | Waktu data diambil |
| `kabupaten` | Kabupaten (Sumba Barat/Tengah) |
| `kecamatan` | Kecamatan |
| `whatsapp` | Nomor WhatsApp |
| `harga` | Harga produk/jasa |
| `latitude` | Koordinat latitude |
| `longitude` | Koordinat longitude |
| `ringkasan_iklan` | Preview text dari post |
| `facebook_user` | Nama user/akun Facebook penulis post |
| `facebook_profile_url` | Link profil user Facebook jika terdeteksi |
| `phone_number` | Nomor telepon dari isi post (jika ada) |
| `post_url` | Link postingan Facebook (permalink) |
| `search_query` | Keyword pencarian (terutama untuk mode marketplace) |
| `search_location` | Lokasi target pencarian marketplace |

## 🐛 Troubleshooting

### "Aw Snap" Error / Browser Crash
- Kurangi `NUM_SCROLLS` di config
- Naikkan `SCROLL_WAIT_TIME`
- Disable extensions jika ada yang conflict

### Login Failed
- Periksa credentials (email/password)
- Coba clear `fb_session/` folder dan restart
- Jika akun punya 2FA/CAPTCHA, login manual di browser yang terbuka lalu tunggu session tersimpan
- Pastikan jendela login manual tidak memakai mode ringan yang memblokir image

### "No data found"
- Periksa `TARGET_GROUP_URL` benar
- Pastikan sudah login ke akun yang punya akses ke group
- Cek `REQUIRED_KEYWORDS` di config
- Increase `NUM_SCROLLS` untuk scan lebih banyak

### Slow Performance
- Kurangi `SLOW_MO` dari 300 → 100
- Kurangi `SCROLL_WAIT_TIME` dari 3000 → 1500
- Enable `HEADLESS_MODE = True`

## 📝 Logs

Semua activity dicatat di `fb_scraper.log`:
```
2026-03-04 10:30:45 - INFO - Starting browser
2026-03-04 10:30:50 - INFO - Opening Facebook
2026-03-04 10:31:00 - INFO - Already logged in from previous session
2026-03-04 10:31:05 - INFO - Navigating to: https://www.facebook.com/groups/...
```

Check logs untuk debugging issues.

## 🔒 Security Notes

1. **Never hardcode credentials** - gunakan `.env`
2. **Jangan commit `.env`** ke git
3. **Keep `.env.example`** tetap generic
4. **Use environment variables** di production
5. **Session data disimpan di `fb_session/`** - keep it private

## 📦 Deployment

### Production Checklist

- [ ] Set credentials di environment variables
- [ ] Enable `HEADLESS_MODE = True`  
- [ ] Disable screenshot/image downloads
- [ ] Set appropriate `NUM_SCROLLS` dan timeouts
- [ ] Enable detailed logging
- [ ] Setup log rotation untuk `fb_scraper.log`
- [ ] Add error notification (email/Slack)
- [ ] Setup scheduled runs (cron/task scheduler)

## 📚 Improvements v2.0

Dibanding versi original, ada perbaikan:

### Security
- ✅ Credentials dari environment variables (bukan hardcoded)
- ✅ Safer password input handling

### Performance  
- ✅ `slow_mo`: 1000 → 300 ms
- ✅ `scroll_wait_time`: 5000 → 3000 ms
- ✅ Optimized browser arguments
- ✅ Deduplication untuk less data noise

### Code Quality
- ✅ Modular structure (config, utils, scrap)
- ✅ Better error handling & logging
- ✅ Type hints & docstrings
- ✅ Removed duplicate code

### Data Quality
- ✅ Improved WhatsApp regex pattern
- ✅ Better price extraction regex
- ✅ Smart deduplication logic
- ✅ Content filtering dengan keywords

## 📞 Support

Untuk issues atau suggestions, check:
1. Log file (`fb_scraper.log`)
2. Browser console (saat login manual atau headless scraping)
3. Facebook session (`fb_session/` folder)

## 📄 License

Internal use only

---

**Last Updated:** May 1, 2026  
**Version:** 2.1
