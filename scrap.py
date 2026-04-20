"""
Facebook Scraper Utility
Script untuk extract data bisnis dari grup Facebook Sumba
dengan fokus pada WhatsApp, harga, dan lokasi

Perbaikan v2:
- Config file terpisah untuk flexibility
- Improved regex patterns untuk ekstraksi data
- Better error handling dan retry logic
- Optimized timeouts untuk performance
- Security improvements (no hardcoded credentials)
- Deduplicate data untuk menghindari duplicate entries
- Better logging dan status messages
"""
import asyncio
import logging
import pandas as pd
import os
from datetime import datetime
from getpass import getpass
from typing import Callable, Dict, Any, Optional
from playwright.async_api import async_playwright

# Import dari module custom
import config
import utils

# --- SETUP LOGGING ---
logging.basicConfig(
    filename=config.LOG_FILENAME,
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    encoding='utf-8'
)
logger = logging.getLogger(__name__)


def emit_progress(
    callback: Optional[Callable[[Dict[str, Any]], None]],
    message: str,
    percent: Optional[int] = None,
    stage: str = "running",
    extra: Optional[Dict[str, Any]] = None,
):
    """Send progress updates to optional callback (used by web UI)."""
    if not callback:
        return

    payload: Dict[str, Any] = {
        "message": message,
        "stage": stage,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))

    if extra:
        payload.update(extra)

    callback(payload)


def get_credentials_sync():
    """
    Get Facebook credentials SYNCHRONOUSLY di terminal sebelum browser launch

    Returns:
        Tuple (email, password) atau None jika dari env
    """
    import os

    # Coba dari environment dulu
    email = os.getenv("FACEBOOK_EMAIL")
    password = os.getenv("FACEBOOK_PASSWORD")

    if email and password:
        logger.info("Credentials loaded dari environment .env")
        print("[V] Credentials loaded dari .env")
        return email, password

    # Manual input di terminal
    print("\n" + "="*60)
    print("  SILAKAN INPUT FACEBOOK CREDENTIALS")
    print("="*60)

    try:
        email = input("Email / No HP    : ").strip()
        password = getpass("Password        : ")

        if not email or not password:
            print("[!] Email dan password harus diisi!")
            raise ValueError("Credentials tidak lengkap")

        print("\n[*] Validasi credentials...")
        logger.info(f"User input credentials: {email[:5]}***")
        return email, password

    except Exception as e:
        print(f"[!] Error input credentials: {e}")
        logger.error(f"Credential input error: {e}")
        raise


async def get_credentials():
    """
    Async wrapper for credential retrieval.

    Returns:
        (email, password) tuple. tries environment first, otherwise
        delegates to :func:`get_credentials_sync` in a thread so as not
        to block the event loop.
    """
    # first check environment
    email = os.getenv("FACEBOOK_EMAIL")
    password = os.getenv("FACEBOOK_PASSWORD")
    if email and password:
        logger.info("Credentials loaded dari environment .env (async)")
        print("[V] Credentials loaded dari .env")
        return email, password

    # fall back to synchronous prompt executed in thread
    return await asyncio.to_thread(get_credentials_sync)


async def detect_aw_snap(page) -> bool:
    """
    Deteksi apakah halaman menampilkan "Aw Snap" error

    Args:
        page: Playwright page object

    Returns:
        True jika "Aw Snap" terdeteksi, False sebaliknya
    """
    try:
        # Check for common error page indicators
        error_indicators = [
            "Aw, snap!",
            "Something went wrong while displaying this webpage",
            "chrome://crash",
            "page_title",  # Generic error page
        ]

        # Get page content
        body_text = await page.inner_text("body")

        for indicator in error_indicators:
            if indicator.lower() in body_text.lower():
                logger.warning(f"Detected Aw Snap error: {indicator}")
                return True

        return False
    except:
        return False


async def handle_aw_snap(page):
    """
    Handle "Aw Snap" error - tunggu 5 detik lalu refresh

    Args:
        page: Playwright page object
    """
    print("[!] Detected 'Aw Snap' error page!")
    print("[*] Waiting 5 seconds before auto-refresh...")
    logger.warning("Aw Snap detected, attempting auto-recovery")

    # Wait 5 detik
    await page.wait_for_timeout(5000)

    # Auto refresh
    print("[*] Auto-refreshing page...")
    await page.reload()
    await page.wait_for_timeout(5000)  # Wait setelah refresh
    logger.info("Page refreshed after Aw Snap")

    # Coba dari environment
    email = os.getenv("FACEBOOK_EMAIL")
    password = os.getenv("FACEBOOK_PASSWORD")

    if email and password:
        logger.info("Credentials loaded dari environment")
        return email, password

    # Manual input
    print("\n[?] Input Facebook Credentials")
    email = input("   Email/No HP: ").strip()
    password = getpass("   Password: ")

    if not email or not password:
        raise ValueError("Email dan password harus diisi!")

    return email, password


async def handle_login(page, email: str, password: str):
    """
    Handle Facebook login dengan error handling yang lebih baik

    Args:
        page: Playwright page object
        email: Email atau nomor HP
        password: Password
    """
    try:
        print("[*] Melakukan login...")
        logger.info(f"Login attempt dengan user: {email[:5]}***")

        # Fill credentials
        await page.fill('input[name="email"]', email)
        await page.fill('input[name="pass"]', password)

        # Click login button
        login_btn = await page.query_selector('button[name="login"]')
        if login_btn:
            await login_btn.click(force=True)
        else:
            logger.warning("Login button tidak ditemukan, coba Enter key")
            await page.keyboard.press("Enter")

        # Wait untuk redirect
        await page.wait_for_timeout(10000)

        # Check apakah login berhasil (seharusnya tidak ada email input lagi)
        if await page.query_selector('input[name="email"]'):
            raise RuntimeError("Login gagal - form login masih terlihat")

        print("[V] Login berhasil!")
        logger.info("Login successful")

    except Exception as e:
        logger.error(f"Login error: {e}")
        raise


async def navigate_to_group(page, group_url: str) -> bool:
    """
    Navigate ke grup target dengan retry logic

    Args:
        page: Playwright page object
        group_url: URL grup Facebook

    Returns:
        True jika berhasil, False jika gagal
    """
    print(f"\n[*] Menavigasi ke grup: {group_url}")
    logger.info(f"Navigating to: {group_url}")

    for attempt in range(config.MAX_RETRIES):
        try:
            await page.goto(
                group_url,
                wait_until="domcontentloaded",
                timeout=config.PAGE_LOAD_TIMEOUT
            )

            # Check untuk Aw Snap error
            if await detect_aw_snap(page):
                print("[!] Aw Snap detected saat navigasi!")
                await handle_aw_snap(page)
                # Coba reload URL sekali lagi
                if attempt < config.MAX_RETRIES - 1:
                    print("[*] Retrying navigate to group...")
                    continue

            # Wait untuk elemen kunci (memastikan halaman fully loaded)
            await page.wait_for_selector(
                config.MAIN_CONTENT_SELECTOR,
                timeout=15000
            )

            print(f"[V] Halaman grup berhasil dimuat")
            logger.info("Group page loaded successfully")
            return True

        except Exception as e:
            print(f"[!] Percobaan {attempt+1}/{config.MAX_RETRIES} gagal. Error: {str(e)[:50]}")
            logger.warning(f"Navigate attempt {attempt+1} failed: {e}")

            if attempt < config.MAX_RETRIES - 1:
                await page.reload()
                await page.wait_for_timeout(config.RETRY_WAIT)
            else:
                logger.error(f"Failed to navigate after {config.MAX_RETRIES} attempts")
                return False

    return False


async def extract_articles_data(page) -> list:
    """
    Extract data dari semua artikel yang terlihat di halaman saat ini

    Args:
        page: Playwright page object

    Returns:
        List of extracted data dictionaries
    """
    extracted_data = []

    try:
        # Wait untuk articles fully render
        try:
            await page.wait_for_selector(config.ARTICLE_SELECTOR, timeout=10000)
        except:
            logger.warning("Article selector not found, continuing...")
            return extracted_data

        articles = await page.query_selector_all(config.ARTICLE_SELECTOR)
        logger.info(f"Found {len(articles)} articles on page")

        for idx, article in enumerate(articles):
            try:
                content = await article.inner_text()

                if not content:
                    continue

                # Try to extract data
                data_point = utils.extract_data_points(content)

                if data_point:
                    extracted_data.append(data_point)
                    logger.debug(f"Article {idx}: Data extracted - {data_point['whatsapp'][:10]}")

            except Exception as e:
                logger.debug(f"Error extracting article {idx}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in extract_articles_data: {e}")

    return extracted_data


async def start_ultra_scraper(
    target_url: str = None,
    num_scrolls: int = None,
    email: str = None,
    password: str = None,
    headless_override: Optional[bool] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
):
    """
    Main scraper engine dengan improved architecture

    Args:
        target_url: URL grup Facebook (default dari config)
        num_scrolls: Jumlah scroll (default dari config)
        email: Email/No HP untuk login
        password: Password untuk login
        headless_override: Paksa headless mode untuk run background
        progress_callback: Callback untuk update progress UI

    Returns:
        dict summary hasil run
    """
    target_url = target_url or config.TARGET_GROUP_URL
    num_scrolls = num_scrolls or config.NUM_SCROLLS
    headless_mode = config.HEADLESS_MODE if headless_override is None else headless_override

    result: Dict[str, Any] = {
        "status": "running",
        "records": 0,
        "file": None,
        "message": "Scraper started",
    }

    emit_progress(progress_callback, "Memulai scraper...", percent=1)

    user_data_dir = config.USER_DATA_DIR

    async with async_playwright() as p:
        context = None
        try:
            # Launch browser dengan stabilized arguments
            print("[*] Memulai Chromium Browser...")
            logger.info("Starting browser")
            emit_progress(progress_callback, "Menjalankan browser background (headless)...", percent=5)

            context = await p.chromium.launch_persistent_context(
                user_data_dir,
                channel=config.BROWSER_CHANNEL,
                headless=headless_mode,
                slow_mo=config.SLOW_MO,
                args=config.BROWSER_ARGS,
                viewport=config.VIEWPORT
            )

            context.set_default_timeout(config.BROWSER_TIMEOUT)
            context.set_default_navigation_timeout(config.PAGE_LOAD_TIMEOUT)

            page = context.pages[0] if context.pages else await context.new_page()

            if getattr(config, "LIGHTWEIGHT_MODE", False):
                blocked_types = set(getattr(config, "BLOCK_RESOURCE_TYPES", []))

                async def route_handler(route, request):
                    if request.resource_type in blocked_types:
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", route_handler)

            # --- OPEN TARGET GROUP DIRECTLY ---
            print(f"[*] Membuka grup target: {target_url}")
            logger.info(f"Opening target group: {target_url}")
            emit_progress(progress_callback, "Membuka grup target...", percent=12, extra={"target_url": target_url})

            try:
                await page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=config.BROWSER_TIMEOUT
                )
            except Exception as e:
                logger.error(f"Failed to open target group: {e}")
                print(f"[!] Gagal membuka grup: {e}")
                result.update({"status": "error", "message": f"Gagal membuka grup: {e}"})
                emit_progress(progress_callback, result["message"], percent=100, stage="error")
                return result

            # Jika Aw Snap terjadi di halaman group, coba recovery
            if await detect_aw_snap(page):
                await handle_aw_snap(page)
                emit_progress(progress_callback, "Aw Snap terdeteksi, mencoba recovery...", percent=18)

            # Jika sudah login sebelumnya, Facebook akan menampilkan konten grup
            # Cek keberadaan elemen utama grup
            group_loaded = False
            try:
                await page.wait_for_selector(config.MAIN_CONTENT_SELECTOR, timeout=10000)
                group_loaded = True
            except:
                group_loaded = False

            # Jika belum loaded, kemungkinan muncul login popup/page
            if not group_loaded:
                # Tunggu popup fully render
                await page.wait_for_timeout(3000)
                
                # Cek login form dengan selector yang lebih robust
                login_required = await page.query_selector('input[data-testid="royal_email"]') is not None or \
                                await page.query_selector('input[name="email"]') is not None
                
                if login_required:
                    print("[!] Login popup terdeteksi. Melakukan login otomatis...")
                    logger.info("Login popup detected on group page")
                    emit_progress(progress_callback, "Login diperlukan, mengisi kredensial...", percent=20)
                    
                    # gunakan credentials yang diberikan ke fungsi
                    if not email or not password:
                        try:
                            email, password = await get_credentials()
                        except Exception as e:
                            logger.error(f"No credentials available: {e}")
                            print("[!] Tidak ada credentials untuk login")
                            result.update({"status": "error", "message": "Tidak ada kredensial login"})
                            emit_progress(progress_callback, result["message"], percent=100, stage="error")
                            return result

                    try:
                        # Try multiple selectors untuk robustness
                        email_input = await page.query_selector('input[data-testid="royal_email"]') or \
                                     await page.query_selector('input[name="email"]')
                        pass_input = await page.query_selector('input[data-testid="royal_pass"]') or \
                                    await page.query_selector('input[name="pass"]')
                        
                        if email_input and pass_input:
                            await email_input.fill(email)
                            await page.wait_for_timeout(500)
                            await pass_input.fill(password)
                            await page.wait_for_timeout(1000)
                            
                            # Click login button
                            login_btn = await page.query_selector('button[name="login"]') or \
                                       await page.query_selector('button[data-testid="royal_login_button"]')
                            
                            if login_btn:
                                await login_btn.click(force=True)
                            else:
                                await page.keyboard.press("Enter")
                            
                            # Tunggu redirect lebih lama
                            await page.wait_for_timeout(8000)
                            print("[V] Login submitted, waiting for redirect...")
                            
                            # Navigate balik ke grup setelah login
                            await page.goto(target_url, wait_until="domcontentloaded", timeout=config.BROWSER_TIMEOUT)
                            await page.wait_for_timeout(5000)
                            emit_progress(progress_callback, "Login berhasil, kembali ke grup target...", percent=30)
                        else:
                            logger.error("Login input fields not found with any selector")
                            print("[!] Tidak menemukan field login")
                            result.update({"status": "error", "message": "Field login tidak ditemukan"})
                            emit_progress(progress_callback, result["message"], percent=100, stage="error")
                            return result
                            
                    except Exception as e:
                        logger.error(f"Auto login failed: {e}")
                        print(f"[!] Login otomatis gagal: {e}")
                        result.update({"status": "error", "message": f"Login otomatis gagal: {e}"})
                        emit_progress(progress_callback, result["message"], percent=100, stage="error")
                        return result
                else:
                    logger.warning("Group content not loaded and no login form found; attempting navigate_to_group")
                    success = await navigate_to_group(page, target_url)
                    if not success:
                        print("[!] Gagal mengakses halaman grup")
                        logger.error("Failed to navigate to group")
                        result.update({"status": "error", "message": "Gagal mengakses halaman grup"})
                        emit_progress(progress_callback, result["message"], percent=100, stage="error")
                        return result
            else:
                print("[V] Sudah login di sesi sebelumnya, konten grup tampil")
                logger.info("Already logged in from previous session")

            # Page sudah berada di grup (atau navigate_to_group telah dipanggil di fallback)
            # Wait untuk DOM fully stabilize sebelum mulai extract
            print("[*] Menunggu halaman fully loaded...")
            await page.wait_for_timeout(5000)

            # Close pop-ups
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(config.ESCAPE_KEY_DELAY)
                print("[*] Pop-up/Dialog ditutup")
            except:
                pass

            # --- DATA SCRAPING LOOP ---
            all_data = []
            print(f"\n[*] Memulai ekstraksi data ({num_scrolls} tahap scroll)...")
            logger.info(f"Starting data extraction - {num_scrolls} scrolls")
            emit_progress(progress_callback, f"Memulai ekstraksi ({num_scrolls} tahap)...", percent=35)

            for scroll_num in range(num_scrolls):
                print(f"   [{scroll_num+1}/{num_scrolls}] Scanning posts...", end=" ", flush=True)

                loop_percent = 35 + int(((scroll_num + 1) / max(1, num_scrolls)) * 50)
                emit_progress(
                    progress_callback,
                    f"Scanning posts tahap {scroll_num+1}/{num_scrolls}",
                    percent=loop_percent,
                    extra={"scroll": scroll_num + 1, "total_scroll": num_scrolls},
                )

                # Wait untuk halaman stabilize setelah scroll (atau di tahap pertama)
                await page.wait_for_timeout(config.SCROLL_WAIT_TIME)

                # Check untuk Aw Snap error
                if await detect_aw_snap(page):
                    print(f"\n[!] Aw Snap detected di scroll {scroll_num+1}!")
                    await handle_aw_snap(page)
                    print("[*] Continuing scraping after recovery...")

                # Extract data dari posts yang terlihat
                page_data = await extract_articles_data(page)
                all_data.extend(page_data)

                print(f"({len(page_data)} found)")
                logger.info(f"Scroll {scroll_num+1}: {len(page_data)} records extracted")

                # Scroll kebawah
                if scroll_num < num_scrolls - 1:  # Jangan scroll di tahap terakhir
                    print(f"   Scrolling down..." , end=" ", flush=True)
                    await page.mouse.wheel(0, config.SCROLL_DEPTH)
                    print("done")
                    # Wait setelah scroll untuk browser process
                    await page.wait_for_timeout(2000)

            # --- CLEANUP & SAVE ---
            if all_data:
                print(f"\n[*] Membersihkan data (deduplication)...")
                logger.info(f"Total data before dedup: {len(all_data)}")
                emit_progress(progress_callback, "Membersihkan data dan menyimpan hasil...", percent=90)

                # Deduplicate
                clean_data = utils.deduplicate_data(all_data)

                # Convert to DataFrame dan save
                df = pd.DataFrame(clean_data)

                filename = utils.generate_filename("inovasi_sumba")
                filepath = os.path.join(config.OUTPUT_DIR, filename)

                df.to_csv(filepath, index=False, encoding='utf-8')

                print(f"\n{'='*60}")
                print(f"[✓] SUKSES!")
                print(f"  Total records: {len(df)}")
                print(f"  File: {filepath}")
                print(f"  Columns: {', '.join(df.columns)}")
                print(f"{'='*60}\n")

                logger.info(f"Scraping completed: {len(df)} records saved to {filename}")
                result.update(
                    {
                        "status": "success",
                        "records": len(df),
                        "file": filepath,
                        "message": "Scraping selesai",
                    }
                )
                emit_progress(
                    progress_callback,
                    f"Selesai. {len(df)} data tersimpan.",
                    percent=100,
                    stage="success",
                    extra={"records": len(df), "file": filepath},
                )

            else:
                print("\n[!] Tidak ada data yang ditemukan.")
                print("   - Periksa apakah URL grup benar")
                print("   - Periksa apakah sudah login")
                print("   - Periksa apakah filter keyword sesuai")
                logger.warning("No data extracted")
                result.update(
                    {
                        "status": "no_data",
                        "records": 0,
                        "message": "Tidak ada data yang ditemukan",
                    }
                )
                emit_progress(progress_callback, result["message"], percent=100, stage="warning")

        except Exception as e:
            logger.error(f"Critical error in scraper: {e}", exc_info=True)
            print(f"\n[!] Error: {e}")
            import traceback
            traceback.print_exc()
            result.update({"status": "error", "message": str(e)})
            emit_progress(progress_callback, f"Error: {e}", percent=100, stage="error")

        finally:
            if context:
                await context.close()
                logger.info("Browser context closed")
            print("\n[*] Selesai.")

    return result


def main():
    """Main entry point"""
    print("\n" + "="*60)
    print("  FACEBOOK SCRAPER - INOVASI SUMBA v2.0")
    print("="*60)
    print()
    print(f"Target: {config.TARGET_GROUP_URL}")
    print(f"Num Scrolls: {config.NUM_SCROLLS}")
    print()
    
    # Get credentials FIRST sebelum launch browser
    try:
        email, password = get_credentials_sync()
    except Exception as e:
        print(f"[!] Credentials required to proceed!")
        logger.error(f"Failed to get credentials: {e}")
        return
    
    print("[V] Credentials accepted. Launching browser in 3 seconds...")
    import time
    time.sleep(3)
    
    try:
        asyncio.run(start_ultra_scraper(email=email, password=password))
    except KeyboardInterrupt:
        print("\n\n[!] Cancelled by user")
        logger.info("Scraper cancelled by user")
    except Exception as e:
        logger.critical(f"Uncaught exception: {e}", exc_info=True)
        print(f"\n[!] Fatal error: {e}")


if __name__ == "__main__":
    main()