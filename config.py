"""
Konfigurasi untuk Facebook Scraper
Silakan sesuaikan nilai-nilai sesuai kebutuhan Anda
"""
import os
from dotenv import load_dotenv

# Load environment variables dari .env file
load_dotenv()

# === KONFIGURASI FACEBOOK ===
FACEBOOK_URL = "https://www.facebook.com/"
TARGET_GROUP_URL = os.getenv(
    "TARGET_GROUP_URL", 
    "https://www.facebook.com/groups/849737045757400/posts/2033088860755540/"
)

# === KONFIGURASI CHROME/CHROMIUM ===
USER_DATA_DIR = os.path.join(os.getcwd(), "fb_session")
BROWSER_CHANNEL = "chrome"  # Use installed Chrome for better stability on Windows
HEADLESS_MODE = False
BROWSER_TIMEOUT = 120000  # ms - Increased untuk FB yang heavy
PAGE_LOAD_TIMEOUT = 120000  # ms - Increased dari 60000 untuk stabilitas

# Browser arguments untuk stabilitas.
# Hindari flag yang berisiko membuat browser tidak stabil.
BROWSER_ARGS = [
    # "--disable-dev-shm-usage",  # REMOVE - cause crash pada Windows
    # "--no-sandbox",              # REMOVE - unnecessary dan problematic
    # "--disable-gpu",             # REMOVE - Facebook needs GPU
    "--disable-extensions",
    "--disable-plugins",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-breakpad",
    "--disable-background-networking",
    "--window-size=1280,800"
]

VIEWPORT = {"width": 1280, "height": 800}

# === KONFIGURASI MODE RINGAN ===
# Mengurangi beban render agar tidak mudah "Aw Snap" pada halaman berat.
LIGHTWEIGHT_MODE = True
BLOCK_RESOURCE_TYPES = ["image", "media", "font"]

# === KONFIGURASI SCRAPING ===
NUM_SCROLLS = 5
SCROLL_DEPTH = 2000  # pixel - Reduced dari 3000 untuk stabilitas (less aggressive)
SCROLL_WAIT_TIME = 5000  # ms - INCREASED dari 3000 untuk browser recovery
GROUP_LIST_SCROLLS = 2  # Kurangi waktu tunggu saat mengambil daftar grup
MAX_GROUPS_TO_PROCESS = 8  # Batasi jumlah grup agar proses tidak terasa stuck

# Selector untuk mencari artikel
ARTICLE_SELECTOR = 'div[role="article"]'
MAIN_CONTENT_SELECTOR = 'div[role="main"]'

# === KONFIGURASI DELAY & RETRY ===
SLOW_MO = 500  # INCREASED dari 300 - lebih gentle untuk browser (ms)
MAX_RETRIES = 5  # INCREASED dari 3 - lebih banyak retry attempts
RETRY_WAIT = 8000  # INCREASED - beri browser lebih banyak waktu recover (ms)
ESCAPE_KEY_DELAY = 1000  # INCREASED dari 500 untuk popup handling (ms)

# === KONFIGURASI DATA EXTRACTION ===
# Regex patterns untuk ekstraksi data
WHATSAPP_PATTERN = r'(?:\+62|0)\s?(?:8[1-9])\d{7,11}'  # Improved WhatsApp pattern
PRICE_PATTERN = r'(?:Rp\.?|IDR)\s?[\d.,]+'
TEXT_SUMMARY_LENGTH = 250

# Keywords untuk filtering post
REQUIRED_KEYWORDS = ["wa", "rp", "harga", "sumba", "kontak", "hubungi", "08"]

# === KONFIGURASI DATABASE SPASIAL ===
KECAMATAN_REF = {
    "Waikabubak": {"kab": "Sumba Barat", "lat": -9.645, "long": 119.414},
    "Loli": {"kab": "Sumba Barat", "lat": -9.620, "long": 119.350},
    "Lamboya": {"kab": "Sumba Barat", "lat": -9.700, "long": 119.300},
    "Laboya Barat": {"kab": "Sumba Barat", "lat": -9.680, "long": 119.200},
    "Wanokaka": {"kab": "Sumba Barat", "lat": -9.730, "long": 119.450},
    "Tana Righu": {"kab": "Sumba Barat", "lat": -9.560, "long": 119.480},
    "Katikutana": {"kab": "Sumba Tengah", "lat": -9.580, "long": 119.620},
    "Katikutana Selatan": {"kab": "Sumba Tengah", "lat": -9.620, "long": 119.640},
    "Umbu Ratu Nggay Barat": {"kab": "Sumba Tengah", "lat": -9.620, "long": 119.680},
    "Mamboro": {"kab": "Sumba Tengah", "lat": -9.450, "long": 119.550},
    "Umbu Ratu Nggay": {"kab": "Sumba Tengah", "lat": -9.650, "long": 119.750},
    "Umbu Ratu Nggay Tengah": {"kab": "Sumba Tengah", "lat": -9.610, "long": 119.710},
}

# === KONFIGURASI LOGGING ===
LOG_FILENAME = "fb_scraper.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s"

# === KONFIGURASI OUTPUT ===
OUTPUT_FORMAT = "csv"  # csv atau excel
OUTPUT_DIR = os.getcwd()

# === KONFIGURASI SECURITY ===
# Untuk credentials, gunakan environment variables:
# FACEBOOK_EMAIL atau FACEBOOK_USERNAME
# FACEBOOK_PASSWORD
# Jangan hardcode credentials di file ini!
USE_CREDENTIALS_FILE = False  # Jika True, baca dari .env
CREDENTIALS_FILE = ".env"

async def get_credentials():
    """Get credentials dari .env atau input user"""
    email = os.getenv('FB_EMAIL')
    password = os.getenv('FB_PASSWORD')
    
    if not email or not password:
        email = input("📧 Masukkan email Facebook: ").strip()
        password = input("🔐 Masukkan password Facebook: ").strip()
    
    return {"email": email, "password": password}
