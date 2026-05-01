"""
Utility functions untuk Facebook Scraper
Berisi helper functions untuk ekstraksi data, validasi, dan processing
"""
import re
import logging
import hashlib
from datetime import datetime
from typing import Dict, Optional, Set
import config
import csv
import asyncio
import json
import os
from datetime import timedelta
from urllib.parse import quote

logger = logging.getLogger(__name__)

SESSION_FILE = "facebook_session.json"


def extract_phone_number(text: str) -> str:
    """Extract Indonesian phone number from text if available."""
    if not text:
        return ""

    # Support common Indonesian phone patterns: 08xx... or +62xx...
    pattern = r'(?:\+62|62|0)\s?(?:8\d(?:[\s\-.]?\d){7,12})'
    match = re.search(pattern, text)
    if not match:
        return ""

    raw_number = match.group(0)
    # Keep only digits and plus for clean CSV output.
    return re.sub(r'[^\d+]', '', raw_number)


def normalize_facebook_url(url: str) -> str:
    """Normalize relative Facebook URL into absolute URL."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return f"https://www.facebook.com{url}"


def _looks_like_post_time(text: str) -> bool:
    if not text:
        return False

    candidate = text.strip().lower()
    if not candidate:
        return False

    relative_patterns = [
        r'\b\d+\s*(menit|mnt|jam|hari|minggu|mgg|bulan|bln|tahun|thn)\b',
        r'\b\d+\s*(minute|hour|day|week|month|year)s?\b',
        r'\bkemarin\b',
        r'\byesterday\b',
        r'\bjust now\b',
    ]
    absolute_patterns = [
        r'\b\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4}\b',
        r'\b\d{1,2}\s+[a-z]+\s+\d{2,4}\b',
        r'\b[a-z]+\s+\d{1,2},\s*\d{2,4}\b',
    ]

    for pattern in relative_patterns + absolute_patterns:
        if re.search(pattern, candidate, flags=re.IGNORECASE):
            return True
    return False


def _format_unix_timestamp(ts_value: str) -> str:
    try:
        timestamp_int = int(ts_value)
        return datetime.fromtimestamp(timestamp_int).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


async def extract_post_time(post) -> str:
    """Extract post publication time from Facebook post article."""
    not_found = "tidak ditemukan"

    try:
        # Best source when available.
        abbr_elem = await post.query_selector('abbr[data-utime]')
        if abbr_elem:
            utime = await abbr_elem.get_attribute('data-utime')
            formatted = _format_unix_timestamp(utime or '')
            if formatted:
                return formatted

        candidate_selectors = [
            'a[aria-label]',
            'span[aria-label]',
            'a[href*="/posts/"]',
            'a[href*="story_fbid"]',
            'abbr',
        ]

        for selector in candidate_selectors:
            elements = await post.query_selector_all(selector)
            for element in elements[:30]:
                try:
                    aria_label = (await element.get_attribute('aria-label') or '').strip()
                    if _looks_like_post_time(aria_label):
                        return aria_label

                    inner_text = (await element.inner_text() or '').strip()
                    if _looks_like_post_time(inner_text):
                        return inner_text
                except Exception:
                    continue

    except Exception:
        pass

    return not_found


def extract_time_from_text(content: str) -> str:
    """Extract relative/absolute time hint from plain text content."""
    if not content:
        return "tidak ditemukan"

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines[:20]:
        if _looks_like_post_time(line):
            return line

    return "tidak ditemukan"


async def extract_post_url(post) -> str:
    """Extract post permalink from a post article using several fallback selectors."""
    candidate_selectors = [
        'a[href*="/posts/"]',
        'a[href*="/permalink/"]',
        'a[href*="story.php"]',
        'a[href*="/groups/"][href*="/posts/"]',
    ]

    for selector in candidate_selectors:
        elem = await post.query_selector(selector)
        if elem:
            href = await elem.get_attribute('href')
            if href:
                return normalize_facebook_url(href)

    # Fallback: scan all anchors and pick the first permalink-like URL.
    anchors = await post.query_selector_all('a[href]')
    for anchor in anchors:
        href = await anchor.get_attribute('href')
        if not href:
            continue

        href_lower = href.lower()
        if any(token in href_lower for token in ['/posts/', '/permalink/', 'story.php']):
            return normalize_facebook_url(href)

    return ""

async def get_credentials():
    """Get Facebook login credentials from user input"""
    print("\n" + "="*50)
    print("🔐 LOGIN KE FACEBOOK")
    print("="*50)
    
    email = input("Masukkan Email Facebook: ").strip()
    password = input("Masukkan Password Facebook: ").strip()
    
    if not email or not password:
        print("❌ Email dan password tidak boleh kosong!")
        return await get_credentials()
    
    return {
        "email": email,
        "password": password
    }

async def save_session(context, email):
    """Save browser session metadata and Playwright storage state to file.

    Writes `facebook_session.json` and, if a Playwright context is provided,
    also writes `facebook_state.json` via `context.storage_state()`.
    """
    try:
        session_data = {
            "email": email,
            "timestamp": datetime.now().isoformat(),
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f)

        # If Playwright context provided, try to persist storage state
        try:
            if context and hasattr(context, 'storage_state'):
                # context.storage_state is async
                await context.storage_state(path='facebook_state.json')
        except Exception as inner_e:
            logger.warning(f"Unable to persist storage_state: {inner_e}")

        print("✅ Session disimpan")
    except Exception as e:
        log_error(f"Error saving session: {str(e)}")

def load_session():
    """Load browser session from file"""
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                session_data = json.load(f)
            
            # Check if session is less than 7 days old
            session_time = datetime.fromisoformat(session_data['timestamp'])
            if (datetime.now() - session_time).days < 7:
                print(f"✅ Ditemukan session untuk: {session_data['email']}")
                return session_data
            else:
                print("⚠️ Session sudah kadaluarsa (> 7 hari)")
                os.remove(SESSION_FILE)
        return None
    except Exception as e:
        log_error(f"Error loading session: {str(e)}")
        return None

def delete_session():
    """Delete saved session"""
    try:
        removed = False
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
            removed = True

        storage_state_file = 'facebook_state.json'
        if os.path.exists(storage_state_file):
            os.remove(storage_state_file)
            removed = True

        if removed:
            print("✅ Session login dihapus")
        else:
            print("ℹ️ Tidak ada session yang perlu dihapus")
    except Exception as e:
        log_error(f"Error deleting session: {str(e)}")

async def check_login_status(page):
    """Check if user is already logged in using DOM markers, not URL only."""
    try:
        await page.goto('https://www.facebook.com/', wait_until='domcontentloaded')
        await page.wait_for_timeout(2000)

        # If login form exists, user is definitely not logged in.
        login_form_selectors = [
            'input[name="email"]',
            'input[name="pass"]',
            'button[name="login"]',
            '[data-testid="royal_login_form"]'
        ]
        for selector in login_form_selectors:
            element = await page.query_selector(selector)
            if element:
                return False

        # Logged-in UI markers in multiple language/variants.
        logged_in_selectors = [
            'div[role="navigation"]',
            'a[aria-label="Home"]',
            'a[aria-label="Beranda"]',
            'a[href*="/friends/"]',
            'a[href*="/watch/"]'
        ]
        for selector in logged_in_selectors:
            element = await page.query_selector(selector)
            if element:
                print("✅ Sudah login (menggunakan session)")
                return True

        current_url = page.url.lower()
        if 'login' in current_url:
            return False

        # Fallback for pages without stable nav selectors.
        body_text = (await page.inner_text('body')).lower()
        if 'email or phone' in body_text or 'forgotten password' in body_text:
            return False

        if 'join or log in to facebook' in body_text or 'masuk ke facebook' in body_text:
            return False

        # Check cookies for Playwright / Facebook logged-in indicator.
        try:
            cookies = await page.context.cookies()
            for c in cookies:
                if c.get('name') == 'c_user' and c.get('value'):
                    print("✅ Ditemukan cookie login 'c_user' — dianggap sudah login")
                    return True
        except Exception:
            # Non-fatal: continue to conservative fallback
            pass

        # Conservative fallback: assume logged out when uncertain.
        return False
    except:
        return False


async def save_login_diagnostics(page, note: str = "diag") -> dict:
    """Save screenshot and page HTML for diagnosing login issues.

    Returns a dict with saved file paths.
    """
    out = {}
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"login_{note}_{ts}"

        # screenshot
        try:
            png_path = f"{base}.png"
            await page.screenshot(path=png_path, full_page=True)
            out['screenshot'] = png_path
        except Exception as e:
            out['screenshot_error'] = str(e)

        # HTML content (trim if large)
        try:
            html = await page.content()
            html_path = f"{base}.html"
            with open(html_path, 'w', encoding='utf-8') as f:
                # store full content; it's useful for debugging
                f.write(html)
            out['html'] = html_path
        except Exception as e:
            out['html_error'] = str(e)

        # Save a short text dump of body inner text to speed inspection
        try:
            text = ''
            if await page.query_selector('body'):
                text = await page.inner_text('body')
            text_path = f"{base}.txt"
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write((text or '').strip()[:20000])
            out['text'] = text_path
        except Exception as e:
            out['text_error'] = str(e)

        log_error(f"Login diagnostics saved: {out}")
    except Exception as e:
        log_error(f"Error saving login diagnostics: {e}")

    return out


async def has_facebook_login_cookie(page) -> bool:
    """Return True when Facebook session cookie is present in the current browser context."""
    try:
        cookies = await page.context.cookies()
        return any(c.get('name') == 'c_user' and c.get('value') for c in cookies)
    except Exception:
        return False


async def create_browser_context(
    playwright,
    headless: bool,
    storage_state_path: str = "facebook_state.json",
    lightweight: Optional[bool] = None,
):
    """Create a Chromium browser and context with the repo's standard settings."""
    browser = await playwright.chromium.launch(
        channel=config.BROWSER_CHANNEL,
        headless=headless,
        slow_mo=config.SLOW_MO if not headless else 0,
        args=config.BROWSER_ARGS,
    )

    context = await browser.new_context(
        storage_state=storage_state_path if storage_state_path and os.path.exists(storage_state_path) else None,
        viewport=config.VIEWPORT,
        reduced_motion="reduce",
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    )
    context.set_default_timeout(config.BROWSER_TIMEOUT)
    context.set_default_navigation_timeout(config.PAGE_LOAD_TIMEOUT)

    if lightweight is None:
        lightweight = config.LIGHTWEIGHT_MODE

    if lightweight:
        blocked_types = set(config.BLOCK_RESOURCE_TYPES)

        async def route_handler(route, request):
            if request.resource_type in blocked_types:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", route_handler)

    return browser, context

async def login_to_facebook(page, email, password, context=None, allow_manual_fallback=True):
    """Login to Facebook"""
    try:
        await page.goto('https://www.facebook.com/', wait_until='networkidle')
        await page.wait_for_timeout(2000)
        
        # Check if already logged in
        if await check_login_status(page):
            return True
        
        print("🔐 Melakukan login baru...")
        
        # Fill email
        email_input = await page.query_selector('input[name="email"]')
        if email_input:
            await email_input.fill(email)
            print("✅ Email terisi")
        await page.wait_for_timeout(500)
        
        # Fill password
        pass_input = await page.query_selector('input[name="pass"]')
        if pass_input:
            await pass_input.fill(password)
            print("✅ Password terisi")
        await page.wait_for_timeout(500)
        
        # Try multiple selectors for login button
        login_clicked = False
        selectors = [
            'button[name="login"]',
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Masuk")',
            '[data-testid="royal_login_button"]'
        ]
        
        for selector in selectors:
            try:
                login_button = await page.query_selector(selector)
                if login_button:
                    print(f"🔍 Mencoba klik tombol login dengan selector: {selector}")
                    await login_button.click()
                    login_clicked = True
                    break
            except:
                continue
        
        if not login_clicked:
            # Fallback: press Enter
            print("⚠️ Tombol tidak ditemukan, mencoba press Enter...")
            await page.keyboard.press('Enter')
        
        print("⏳ Menunggu proses login...")
        await page.wait_for_timeout(8000)
        
        # Wait for navigation to complete
        try:
            await page.wait_for_load_state('networkidle', timeout=15000)
        except:
            pass
        
        # Check if login successful by inspecting DOM markers
        # First, try cookie-based check (faster/more reliable)
        if await has_facebook_login_cookie(page):
            print("✅ Cookie 'c_user' terdeteksi — login berhasil")
            if context:
                try:
                    await save_session(context, email)
                except Exception:
                    logger.warning("Gagal menyimpan session, melanjutkan tanpa crash")
            return True

        is_logged = await check_login_status(page)
        if is_logged:
            print("✅ Login berhasil")
            # Save session metadata (non-blocking)
            if context:
                try:
                    await save_session(context, email)
                except Exception:
                    logger.warning("Gagal menyimpan session, melanjutkan tanpa crash")
            return True

        # Not logged in yet — likely needs verification or failed
        print("⚠️ Login tampak gagal atau butuh verifikasi")
        await page.wait_for_timeout(10000)
        # Re-check once more before failing
        if await check_login_status(page):
            if context:
                try:
                    await save_session(context, email)
                except Exception:
                    logger.warning("Gagal menyimpan session pada re-check")
            return True

        if allow_manual_fallback:
            print("\n🖐️ Login otomatis gagal. Silakan selesaikan verifikasi/login manual di browser yang terbuka.")
            print("    Saya akan menunggu beberapa menit dan memeriksa ulang status login secara berkala.")

            manual_deadline = datetime.now() + timedelta(seconds=180)
            while datetime.now() < manual_deadline:
                if await has_facebook_login_cookie(page):
                    print("✅ Login manual terdeteksi lewat cookie 'c_user'")
                    if context:
                        try:
                            await save_session(context, email)
                        except Exception:
                            logger.warning("Gagal menyimpan session setelah login manual")
                    return True

                try:
                    current_url = (page.url or "").lower()
                except Exception:
                    current_url = ""

                if 'checkpoint' in current_url:
                    print("⚠️ Browser terdeteksi berada di checkpoint. Silakan selesaikan verifikasi pada browser.")

                await page.wait_for_timeout(3000)

            print("⚠️ Batas waktu menunggu login manual habis.")

        # Diagnose possible checkpoint or verification page
        try:
            current_url = (page.url or "").lower()
        except Exception:
            current_url = ""

        body_text = ""
        try:
            if await page.query_selector('body'):
                body_text = (await page.inner_text('body') or '')
        except Exception:
            try:
                body_text = await page.content()
            except Exception:
                body_text = ""

        if 'checkpoint' in current_url or re.search(r"verify|verification|checkpoint|two[- ]?factor|enter code|security|confirm", body_text, flags=re.IGNORECASE):
            diag = {}
            try:
                diag = await save_login_diagnostics(page, note='checkpoint')
            except Exception as e:
                logger.warning(f"Failed to write diagnostics: {e}")
            raise RuntimeError(f"Checkpoint/verification required. Diagnostics: {diag}")

        # Generic failure: save diagnostics then raise
        try:
            diag = await save_login_diagnostics(page, note='login_failed')
        except Exception as e:
            logger.warning(f"Failed to write diagnostics: {e}")
        raise RuntimeError("Login gagal atau memerlukan verifikasi tambahan; diagnostics saved.")
            
    except Exception as e:
        log_error(f"Error during login: {str(e)}")
        raise

async def search_posts_by_query(page, query):
    """Search Facebook posts by plain keyword query (without hashtag)."""
    try:
        normalized = query.strip()
        if not normalized:
            raise ValueError("Kata kunci kosong")

        encoded_query = quote(normalized)
        search_urls = [
            f'https://www.facebook.com/search/posts/?q={encoded_query}',
            f'https://www.facebook.com/search/top/?q={encoded_query}',
            f'https://www.facebook.com/search/?q={encoded_query}',
            f'https://m.facebook.com/search/posts/?q={encoded_query}',
            f'https://mbasic.facebook.com/search/posts/?q={encoded_query}',
        ]

        error_markers = [
            "This page isn't available",
            "The link you followed may be broken",
            "Halaman ini tidak tersedia"
        ]

        for search_url in search_urls:
            try:
                await page.goto(search_url, wait_until='domcontentloaded')
                await page.wait_for_timeout(3500)
            except Exception:
                continue

            body_text = await page.inner_text('body')
            if any(marker.lower() in body_text.lower() for marker in error_markers):
                continue

            # Scroll to trigger lazy-loading results.
            for _ in range(4):
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(1800)

            print(f"✅ Berhasil mencari kata kunci: {normalized}")
            return True

        # Fallback: perform search from Facebook UI search box.
        try:
            await page.goto('https://www.facebook.com/', wait_until='domcontentloaded')
            await page.wait_for_timeout(2500)

            search_input_selectors = [
                'input[aria-label*="Search"]',
                'input[placeholder*="Search"]',
                'input[aria-label*="Cari"]',
                'input[placeholder*="Cari"]',
                'input[type="search"]',
            ]

            search_input = None
            for selector in search_input_selectors:
                search_input = await page.query_selector(selector)
                if search_input:
                    break

            if search_input:
                await search_input.click()
                await search_input.fill(normalized)
                await page.keyboard.press('Enter')
                await page.wait_for_timeout(3500)

                # Try going specifically to posts tab after UI search.
                posts_tab = await page.query_selector('a[href*="/search/posts/"]')
                if posts_tab:
                    await posts_tab.click()
                    await page.wait_for_timeout(2500)

                for _ in range(4):
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await page.wait_for_timeout(1800)

                body_after = await page.inner_text('body')
                if not any(marker.lower() in body_after.lower() for marker in error_markers):
                    print(f"✅ Berhasil mencari kata kunci via UI: {normalized}")
                    return True
        except Exception:
            pass

        raise RuntimeError(
            "URL pencarian Facebook tidak tersedia. Facebook kemungkinan mengubah endpoint atau membatasi akses."
        )
    except Exception as e:
        log_error(f"Error searching query: {str(e)}")
        raise


def resolve_marketplace_location(location_text: str) -> dict:
    """Resolve marketplace location text into a known coordinate target."""
    default_item = config.KECAMATAN_REF.get("Waikabubak", {})
    default_lat = default_item.get("lat", -9.645)
    default_long = default_item.get("long", 119.414)
    default_label = "Waikabubak, Sumba Barat, Nusa Tenggara Timur"

    if not location_text:
        return {
            "label": default_label,
            "lat": default_lat,
            "long": default_long,
        }

    normalized = location_text.strip().lower()
    if "waikabubak" in normalized:
        return {
            "label": default_label,
            "lat": default_lat,
            "long": default_long,
        }

    for district, metadata in config.KECAMATAN_REF.items():
        if district.lower() in normalized:
            kab = metadata.get("kab", "")
            label = f"{district}, {kab}, Nusa Tenggara Timur".strip().strip(",")
            return {
                "label": label,
                "lat": metadata.get("lat", default_lat),
                "long": metadata.get("long", default_long),
            }

    return {
        "label": default_label,
        "lat": default_lat,
        "long": default_long,
    }


async def search_marketplace_by_query(page, query, location_text="", radius_km=40):
    """Search Facebook Marketplace by keyword with coordinate-based location filter."""
    try:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Keyword marketplace kosong")

        location_data = resolve_marketplace_location(location_text)
        safe_radius_km = max(1, min(int(radius_km), 500))
        radius_meter = safe_radius_km * 1000
        encoded_query = quote(normalized_query)

        marketplace_urls = [
            (
                "https://www.facebook.com/marketplace/search/"
                f"?query={encoded_query}&latitude={location_data['lat']}&longitude={location_data['long']}"
                f"&radius={radius_meter}&sortBy=creation_time_descend"
            ),
            (
                "https://www.facebook.com/marketplace/search/"
                f"?query={encoded_query}&latitude={location_data['lat']}&longitude={location_data['long']}"
                f"&radius={radius_meter}"
            ),
        ]

        for marketplace_url in marketplace_urls:
            await page.goto(marketplace_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(4000)

            if "marketplace" not in page.url.lower():
                continue

            for _ in range(5):
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(1800)

            print(
                f"✅ Marketplace search berhasil: '{normalized_query}' @ {location_data['label']}"
            )
            return location_data

        raise RuntimeError("Tidak berhasil membuka halaman Marketplace search.")
    except Exception as e:
        log_error(f"Error marketplace search: {str(e)}")
        raise


async def extract_marketplace_results(page):
    """Extract marketplace listing cards from current page."""
    try:
        listings = []
        seen_urls = set()

        anchors = await page.query_selector_all('a[href*="/marketplace/item/"]')
        for anchor in anchors:
            try:
                href = await anchor.get_attribute('href')
                listing_url = normalize_facebook_url(href or '')
                normalized_url = listing_url.split('?')[0]
                if not normalized_url or normalized_url in seen_urls:
                    continue
                seen_urls.add(normalized_url)

                card_text = await anchor.evaluate(
                    """
                    (el) => {
                        let node = el;
                        let best = (el.innerText || '').trim();
                        for (let i = 0; i < 6 && node; i++) {
                            const txt = (node.innerText || '').trim();
                            if (txt.length > best.length) {
                                best = txt;
                            }
                            node = node.parentElement;
                        }
                        return best;
                    }
                    """
                )
                card_text = (card_text or '').strip()

                title_text = (await anchor.inner_text() or '').strip()
                if not title_text and card_text:
                    title_text = card_text.splitlines()[0].strip()

                price_match = re.search(config.PRICE_PATTERN, card_text or '', flags=re.IGNORECASE)
                price = price_match.group(0).strip() if price_match else ''

                listings.append({
                    'text': card_text,
                    'title': title_text,
                    'author': '',
                    'facebook_user': '',
                    'facebook_profile_url': '',
                    'phone_number': extract_phone_number(card_text),
                    'price': price,
                    'timestamp': extract_time_from_text(card_text),
                    'waktu_postingan': extract_time_from_text(card_text),
                    'url': normalized_url,
                    'post_url': normalized_url,
                    'scraped_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception:
                continue

        return listings
    except Exception as e:
        log_error(f"Error extracting marketplace results: {str(e)}")
        return []


async def search_hashtag(page, hashtag):
    """Backward-compatible wrapper to existing callers."""
    return await search_posts_by_query(page, hashtag)

async def extract_search_results(page):
    """Extract search results from page"""
    try:
        posts_data = []
        
        # Extract posts
        posts = await page.query_selector_all('div[role="article"]')
        
        for post in posts:
            try:
                post_data = {
                    'text': '',
                    'author': '',
                    'facebook_user': '',
                    'facebook_profile_url': '',
                    'phone_number': '',
                    'timestamp': 'tidak ditemukan',
                    'waktu_postingan': 'tidak ditemukan',
                    'url': '',
                    'post_url': '',
                    'scraped_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Extract text
                text_elem = await post.query_selector('div[dir="auto"]')
                if text_elem:
                    post_data['text'] = await text_elem.inner_text()
                
                # Extract author
                author_elem = await post.query_selector('a[role="link"]')
                if author_elem:
                    post_data['author'] = (await author_elem.inner_text()).strip()
                    post_data['facebook_user'] = post_data['author']
                    profile_href = await author_elem.get_attribute('href')
                    post_data['facebook_profile_url'] = normalize_facebook_url(profile_href or '')

                # Extract post link/permalink using multiple fallbacks.
                post_data['url'] = await extract_post_url(post)
                post_data['post_url'] = post_data['url']

                posting_time = await extract_post_time(post)
                post_data['timestamp'] = posting_time
                post_data['waktu_postingan'] = posting_time

                post_data['phone_number'] = extract_phone_number(post_data['text'])
                
                posts_data.append(post_data)
            except:
                continue
        
        return posts_data
    except Exception as e:
        log_error(f"Error extracting search results: {str(e)}")
        return []

async def navigate_to_groups_menu(page):
    """Navigate to Facebook Groups menu"""
    try:
        await page.goto('https://www.facebook.com/groups/feed/', wait_until='domcontentloaded')
        try:
            await page.wait_for_selector('div[role="main"]', timeout=15000)
        except:
            await page.wait_for_timeout(2500)
        
        print("✅ Berhasil navigasi ke menu grup")
        return True
    except Exception as e:
        log_error(f"Error navigating to groups menu: {str(e)}")
        raise

async def get_all_groups(page):
    """Get all groups that user has joined"""
    try:
        groups = []
        
        await page.goto('https://www.facebook.com/groups/feed/', wait_until='domcontentloaded')
        try:
            await page.wait_for_selector('a[href*="/groups/"]', timeout=15000)
        except:
            await page.wait_for_timeout(3000)
        
        # Scroll secukupnya untuk load daftar grup tanpa terlalu membebani browser.
        for _ in range(config.GROUP_LIST_SCROLLS):
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(2000)
        
        # Extract group links
        group_links = await page.query_selector_all('a[href*="/groups/"]')
        
        seen_urls = set()
        for link in group_links:
            try:
                href = await link.get_attribute('href')
                text = await link.inner_text()
                
                if href and '/groups/' in href and text and href not in seen_urls:
                    url = href.split('?')[0] if '?' in href else href
                    if not url.startswith('http'):
                        url = f'https://www.facebook.com{url}'
                    
                    groups.append({
                        'name': text.strip(),
                        'url': url
                    })
                    seen_urls.add(href)
            except:
                continue
        
        return groups
    except Exception as e:
        log_error(f"Error getting groups: {str(e)}")
        return []

async def scrape_group_posts(page, days=365):
    """Scrape posts from a group for specified number of days"""
    try:
        posts_data = []
        
        # Scroll and load posts
        for _ in range(10):
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(2000)
        
        # Extract posts
        posts = await page.query_selector_all('div[role="article"]')
        
        for post in posts:
            try:
                post_data = {
                    'text': '',
                    'author': '',
                    'facebook_user': '',
                    'facebook_profile_url': '',
                    'phone_number': '',
                    'timestamp': 'tidak ditemukan',
                    'waktu_postingan': 'tidak ditemukan',
                    'url': '',
                    'post_url': '',
                    'scraped_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # Extract text
                text_elem = await post.query_selector('div[dir="auto"]')
                if text_elem:
                    post_data['text'] = await text_elem.inner_text()

                # Extract author/profile for group post
                author_elem = await post.query_selector('a[role="link"]')
                if author_elem:
                    post_data['author'] = (await author_elem.inner_text()).strip()
                    post_data['facebook_user'] = post_data['author']
                    profile_href = await author_elem.get_attribute('href')
                    post_data['facebook_profile_url'] = normalize_facebook_url(profile_href or '')

                # Extract group post permalink.
                post_data['url'] = await extract_post_url(post)
                post_data['post_url'] = post_data['url']

                posting_time = await extract_post_time(post)
                post_data['timestamp'] = posting_time
                post_data['waktu_postingan'] = posting_time

                # Apply days filter if posting_time can be parsed
                post_dt = None
                try:
                    post_dt = _parse_post_datetime(posting_time)
                except Exception:
                    post_dt = None

                if post_dt is not None:
                    age_days = (datetime.now() - post_dt).days
                    if age_days > int(days):
                        # Skip posts older than configured days
                        continue

                post_data['phone_number'] = extract_phone_number(post_data['text'])
                
                posts_data.append(post_data)
            except:
                continue
        
        return posts_data
    except Exception as e:
        log_error(f"Error scraping group posts: {str(e)}")
        return []


def _parse_post_datetime(time_str: str) -> Optional[datetime]:
    """Try to parse several common time string formats returned by extract_post_time.

    Returns a datetime when parsable, otherwise None.
    Supports absolute unix timestamp formatting (YYYY-MM-DD HH:MM:SS),
    simple date strings, and relative Indonesian/English phrases like '2 hari yang lalu'.
    """
    if not time_str:
        return None

    s = time_str.strip()

    # Common absolute format produced by _format_unix_timestamp in this module
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        pass

    s_lower = s.lower()
    now = datetime.now()

    # Relative patterns (Indonesian/English)
    m = re.search(r"(\d+)\s*(menit|mnt|min|minute|minutes)", s_lower)
    if m:
        minutes = int(m.group(1))
        return now - timedelta(minutes=minutes)

    m = re.search(r"(\d+)\s*(jam|hour|hours)", s_lower)
    if m:
        hours = int(m.group(1))
        return now - timedelta(hours=hours)

    m = re.search(r"(\d+)\s*(hari|day|days)", s_lower)
    if m:
        days = int(m.group(1))
        return now - timedelta(days=days)

    if "kemarin" in s_lower or "yesterday" in s_lower:
        return now - timedelta(days=1)

    if "just now" in s_lower or "baru saja" in s_lower:
        return now

    # Can't parse -> None (will keep the post)
    return None


def extract_data_points(text: str) -> Optional[Dict[str, str]]:
    """Extract business data points from a block of text.

    Returns a dictionary with common output keys or None if nothing found.
    """
    if not text or not text.strip():
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    phone = extract_phone_number(text)

    price_match = re.search(config.PRICE_PATTERN, text, flags=re.IGNORECASE)
    price = price_match.group(0).strip() if price_match else ""

    # Detect kecamatan from KECAMATAN_REF keys
    kecamatan = ""
    kabupaten = ""
    lat = ""
    long = ""
    lower_text = text.lower()
    for district, meta in config.KECAMATAN_REF.items():
        if district.lower() in lower_text:
            kecamatan = district
            kabupaten = meta.get("kab", "")
            lat = str(meta.get("lat", ""))
            long = str(meta.get("long", ""))
            break

    summary = text.strip()

    data = {
        "tanggal_ambil": now,
        "kabupaten": kabupaten,
        "kecamatan": kecamatan,
        "whatsapp": phone,
        "harga": price,
        "latitude": lat,
        "longitude": long,
        "ringkasan_iklan": summary[: config.TEXT_SUMMARY_LENGTH] if hasattr(config, 'TEXT_SUMMARY_LENGTH') else summary[:250],
        "facebook_user": "",
        "facebook_profile_url": "",
        "phone_number": phone,
        "post_url": "",
        "search_query": "",
        "search_location": "",
    }

    # If nothing useful extracted, return None
    if not phone and not price and not kecamatan:
        return None

    return data


def deduplicate_data(data_list: list) -> list:
    """Deduplicate entries using composite key (whatsapp, harga, kecamatan, post_url or text-hash)."""
    seen = set()
    unique = []

    for item in data_list:
        whatsapp = (item.get("whatsapp") or item.get("phone_number") or "").strip()
        harga = (item.get("harga") or item.get("price") or "").strip()
        kecamatan = (item.get("kecamatan") or "").strip()
        post_url = (item.get("post_url") or item.get("url") or "").strip()

        if post_url:
            key = (whatsapp, harga, kecamatan, post_url)
        else:
            # fallback: use hash of text content
            txt = (item.get("ringkasan_iklan") or item.get("text") or "").strip()
            h = hashlib.sha1(txt.encode('utf-8')).hexdigest() if txt else ""
            key = (whatsapp, harga, kecamatan, h)

        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique


def generate_filename(prefix: str = "scrape") -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = prefix.replace(" ", "_")
    return f"{safe}_{ts}.csv"

def save_to_csv(data, filename):
    """Save data to CSV file"""
    try:
        if not data:
            return
        
        keys = data[0].keys()
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
        
        print(f"✅ Data berhasil disimpan ke {filename}")
    except Exception as e:
        log_error(f"Error saving to CSV: {str(e)}")

def log_error(message):
    """Log error to file"""
    try:
        with open('scraper_errors.log', 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{timestamp}] {message}\n")
    except:
        pass
