"""
Utility functions untuk Facebook Scraper
Berisi helper functions untuk ekstraksi data, validasi, dan processing
"""
import re
import logging
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

def save_session(context, email):
    """Save browser session to file"""
    try:
        session_data = {
            "email": email,
            "timestamp": datetime.now().isoformat(),
        }
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f)
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

        # Conservative fallback: assume logged out when uncertain.
        return False
    except:
        return False

async def login_to_facebook(page, email, password, context=None):
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
        
        # Check if login successful
        current_url = page.url
        if 'login' not in current_url.lower():
            print("✅ Login berhasil")
            
            # Save session
            if context:
                save_session(context, email)
            
            return True
        else:
            print("⚠️ Mungkin perlu verifikasi tambahan atau login gagal")
            await page.wait_for_timeout(10000)
            return True
            
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

                post_data['phone_number'] = extract_phone_number(post_data['text'])
                
                posts_data.append(post_data)
            except:
                continue
        
        return posts_data
    except Exception as e:
        log_error(f"Error scraping group posts: {str(e)}")
        return []

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
