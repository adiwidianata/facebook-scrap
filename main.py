import asyncio
import sys
import os
from datetime import datetime
from playwright.async_api import async_playwright
from config import *
from utils import (
    get_credentials,
    login_to_facebook,
    search_posts_by_query,
    extract_search_results,
    save_to_csv,
    log_error,
    navigate_to_groups_menu,
    get_all_groups,
    scrape_group_posts,
    load_session,
    delete_session,
    check_login_status
)

def get_timestamp():
    """Generate timestamp for file naming"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")

async def main():
    """Main entry point dengan menu pilihan scraping"""
    print("\n" + "="*50)
    print("🔍 FACEBOOK SCRAPER - PILIH METODE")
    print("="*50)
    print("\n1. Scraping Berdasarkan Pencarian Kata Kunci")
    print("2. Scraping Berdasarkan Grup Facebook")
    print("3. Hapus Session Login (Logout)")
    print("4. Exit")
    
    choice = input("\nPilih metode (1/2/3/4): ").strip()
    
    if choice == "1":
        await scrape_by_search()
    elif choice == "2":
        await scrape_by_groups()
    elif choice == "3":
        delete_session()
        print("Session berhasil dihapus. Anda akan diminta login lagi di scraping berikutnya.")
        await main()
    elif choice == "4":
        print("Keluar dari aplikasi.")
        sys.exit(0)
    else:
        print("❌ Pilihan tidak valid!")
        await main()

async def scrape_by_search():
    """Metode 1: Scraping berdasarkan pencarian kata kunci"""
    print("\n" + "="*50)
    print("📌 METODE 1: SCRAPING BERDASARKAN PENCARIAN")
    print("="*50)
    
    query = input("\nMasukkan kata kunci (contoh: kain waikabubak): ").strip()
    if not query:
        print("❌ Kata kunci tidak boleh kosong!")
        return
    
    # Check for existing session and storage state consistency
    session = load_session()
    storage_state_path = "facebook_state.json"
    has_storage_state = os.path.exists(storage_state_path)

    if session and not has_storage_state:
        print("⚠️ Metadata session ada, tapi file state login hilang. Login ulang diperlukan.")
        session = None

    credentials = None
    
    if not session:
        credentials = await get_credentials()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel=BROWSER_CHANNEL,
            headless=HEADLESS_MODE,
            slow_mo=SLOW_MO,
            args=BROWSER_ARGS
        )
        
        # Use persistent context to save session
        user_data_dir = "./facebook_user_data"
        context = await browser.new_context(
            storage_state=storage_state_path if session and has_storage_state else None,
            viewport=VIEWPORT,
            reduced_motion="reduce",
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        context.set_default_timeout(BROWSER_TIMEOUT)
        context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT)

        if LIGHTWEIGHT_MODE:
            blocked_types = set(BLOCK_RESOURCE_TYPES)

            async def route_handler(route, request):
                if request.resource_type in blocked_types:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)
        
        page = await context.new_page()
        
        try:
            # Check if already logged in
            is_logged_in = await check_login_status(page)
            
            if not is_logged_in:
                if not credentials:
                    credentials = await get_credentials()
                # Login ke Facebook
                print(f"\n🔐 Melakukan login...")
                await login_to_facebook(page, credentials["email"], credentials["password"], context)
                
                # Save storage state
                await context.storage_state(path="facebook_state.json")
            
            # Navigate ke search dengan kata kunci biasa
            print(f"\n🔍 Mencari kata kunci: {query}")
            await search_posts_by_query(page, query)
            
            # Scraping hasil pencarian
            print(f"\n📊 Melakukan scraping hasil pencarian...")
            data = await extract_search_results(page)
            
            # Save hasil
            if data:
                output_file = f"facebook_search_{query.replace(' ', '_')}_{get_timestamp()}.csv"
                save_to_csv(data, output_file)
                print(f"\n✅ Scraping berhasil! Data disimpan ke: {output_file}")
                print(f"📈 Total data: {len(data)} posts")
            else:
                print("⚠️ Tidak ada data yang berhasil di-scrape")
                
        except Exception as e:
            log_error(f"Error di metode pencarian: {str(e)}")
            print(f"❌ Error: {str(e)}")
        finally:
            await browser.close()

async def scrape_by_groups():
    """Metode 2: Scraping berdasarkan grup Facebook"""
    print("\n" + "="*50)
    print("👥 METODE 2: SCRAPING BERDASARKAN GRUP")
    print("="*50)
    
    # Check for existing session and storage state consistency
    session = load_session()
    storage_state_path = "facebook_state.json"
    has_storage_state = os.path.exists(storage_state_path)

    if session and not has_storage_state:
        print("⚠️ Metadata session ada, tapi file state login hilang. Login ulang diperlukan.")
        session = None

    credentials = None
    
    if not session:
        credentials = await get_credentials()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel=BROWSER_CHANNEL,
            headless=HEADLESS_MODE,
            slow_mo=SLOW_MO,
            args=BROWSER_ARGS
        )
        
        # Use persistent context to save session
        context = await browser.new_context(
            storage_state=storage_state_path if session and has_storage_state else None,
            viewport=VIEWPORT,
            reduced_motion="reduce",
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        context.set_default_timeout(BROWSER_TIMEOUT)
        context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT)

        if LIGHTWEIGHT_MODE:
            blocked_types = set(BLOCK_RESOURCE_TYPES)

            async def route_handler(route, request):
                if request.resource_type in blocked_types:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)
        
        page = await context.new_page()
        
        try:
            # Check if already logged in
            is_logged_in = await check_login_status(page)
            
            if not is_logged_in:
                if not credentials:
                    credentials = await get_credentials()
                # Login ke Facebook
                print(f"\n🔐 Melakukan login...")
                await login_to_facebook(page, credentials["email"], credentials["password"], context)
                
                # Save storage state
                await context.storage_state(path="facebook_state.json")
            
            # Navigate ke menu grup
            print(f"\n👥 Navigasi ke menu grup...")
            await navigate_to_groups_menu(page)
            
            # Ambil daftar semua grup
            print(f"\n📋 Mengambil daftar semua grup...")
            groups = await get_all_groups(page)
            
            if not groups:
                print("⚠️ Tidak ada grup yang ditemukan")
                return
            
            print(f"✅ Ditemukan {len(groups)} grup")

            if MAX_GROUPS_TO_PROCESS and len(groups) > MAX_GROUPS_TO_PROCESS:
                print(f"[*] Membatasi proses ke {MAX_GROUPS_TO_PROCESS} grup pertama agar lebih ringan")
                groups = groups[:MAX_GROUPS_TO_PROCESS]
            
            # Scraping setiap grup
            all_data = []
            for idx, group in enumerate(groups, 1):
                print(f"\n" + "="*50)
                print(f"📌 Grup {idx}/{len(groups)}: {group['name']}")
                print("="*50)
                
                try:
                    # Navigate ke grup
                    await page.goto(group['url'], wait_until='domcontentloaded')
                    await page.wait_for_timeout(2000)
                    
                    # Scraping postingan setahun terakhir
                    print(f"📊 Melakukan scraping postingan (1 tahun terakhir)...")
                    group_data = await scrape_group_posts(page, days=365)
                    
                    if group_data:
                        all_data.extend(group_data)
                        print(f"✅ Berhasil scrape {len(group_data)} posts dari grup ini")
                    else:
                        print(f"⚠️ Tidak ada data dari grup ini")
                        
                except Exception as e:
                    log_error(f"Error scraping grup {group['name']}: {str(e)}")
                    print(f"❌ Error scraping grup: {str(e)}")
                    continue
            
            # Save semua hasil
            if all_data:
                output_file = f"facebook_groups_{get_timestamp()}.csv"
                save_to_csv(all_data, output_file)
                print(f"\n" + "="*50)
                print(f"✅ SCRAPING SELESAI!")
                print(f"📁 Data disimpan ke: {output_file}")
                print(f"📈 Total data dari {len(groups)} grup: {len(all_data)} posts")
                print("="*50)
            else:
                print("⚠️ Tidak ada data yang berhasil di-scrape dari semua grup")
                
        except Exception as e:
            log_error(f"Error di metode grup: {str(e)}")
            print(f"❌ Error: {str(e)}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())