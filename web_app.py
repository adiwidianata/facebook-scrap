import asyncio
import os
import threading
from datetime import datetime
from uuid import uuid4

from flask import Flask, jsonify, make_response, render_template, request, send_from_directory
from playwright.async_api import async_playwright

from config import (
    BROWSER_ARGS,
    BROWSER_CHANNEL,
    BROWSER_TIMEOUT,
    KECAMATAN_REF,
    LIGHTWEIGHT_MODE,
    MAX_GROUPS_TO_PROCESS,
    PAGE_LOAD_TIMEOUT,
    SLOW_MO,
    VIEWPORT,
    BLOCK_RESOURCE_TYPES,
)
from utils import (
    check_login_status,
    delete_session,
    extract_search_results,
    extract_marketplace_results,
    get_all_groups,
    load_session,
    log_error,
    login_to_facebook,
    navigate_to_groups_menu,
    search_marketplace_by_query,
    search_posts_by_query,
    save_to_csv,
    scrape_group_posts,
)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

state_lock = threading.Lock()
job_state = {
    "running": False,
    "job_id": None,
    "mode": None,
    "status": "Idle",
    "progress": 0,
    "logs": [],
    "error": None,
    "output_file": None,
    "total_data": 0,
    "started_at": None,
    "finished_at": None,
    "preview_columns": [],
    "preview_rows": [],
}


def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _append_log(message: str):
    with state_lock:
        now = datetime.now().strftime("%H:%M:%S")
        job_state["logs"].append(f"[{now}] {message}")
        if len(job_state["logs"]) > 200:
            job_state["logs"] = job_state["logs"][-200:]


def _set_state(**kwargs):
    with state_lock:
        for key, value in kwargs.items():
            job_state[key] = value


def _snapshot_state():
    with state_lock:
        return {
            "running": job_state["running"],
            "job_id": job_state["job_id"],
            "mode": job_state["mode"],
            "status": job_state["status"],
            "progress": job_state["progress"],
            "logs": list(job_state["logs"]),
            "error": job_state["error"],
            "output_file": job_state["output_file"],
            "total_data": job_state["total_data"],
            "started_at": job_state["started_at"],
            "finished_at": job_state["finished_at"],
            "preview_columns": list(job_state["preview_columns"]),
            "preview_rows": list(job_state["preview_rows"]),
        }


def _clear_finished_state():
    with state_lock:
        if job_state["running"]:
            return False

        job_state["job_id"] = None
        job_state["mode"] = None
        job_state["status"] = "Idle"
        job_state["progress"] = 0
        job_state["logs"] = []
        job_state["error"] = None
        job_state["output_file"] = None
        job_state["total_data"] = 0
        job_state["started_at"] = None
        job_state["finished_at"] = None
        job_state["preview_columns"] = []
        job_state["preview_rows"] = []
        return True


def _filter_phone_only(rows):
    return [row for row in rows if (row.get("phone_number") or "").strip()]


def _build_preview_payload(rows, max_rows=30, max_text=220):
    if not rows:
        return {"preview_columns": [], "preview_rows": []}

    columns = list(rows[0].keys())
    preview_rows = []
    for row in rows[:max_rows]:
        clean_row = {}
        for col in columns:
            val = row.get(col, "")
            text = "" if val is None else str(val)
            if len(text) > max_text:
                text = text[: max_text - 3] + "..."
            clean_row[col] = text
        preview_rows.append(clean_row)

    return {
        "preview_columns": columns,
        "preview_rows": preview_rows,
    }


def _build_location_options():
    options = {}
    for district, meta in KECAMATAN_REF.items():
        kab = meta.get("kab", "Lainnya")
        options.setdefault(kab, []).append(district)

    # Keep UI order predictable.
    for kab in options:
        options[kab] = sorted(options[kab])
    return options


def _resolve_marketplace_location(
    marketplace_location: str,
    marketplace_kabupaten: str,
    marketplace_kecamatan: str,
) -> str:
    if marketplace_kecamatan:
        matched = KECAMATAN_REF.get(marketplace_kecamatan)
        if matched:
            kab = matched.get("kab", marketplace_kabupaten or "")
            return f"{marketplace_kecamatan}, {kab}, Nusa Tenggara Timur"

    if marketplace_kabupaten:
        return f"{marketplace_kabupaten}, Nusa Tenggara Timur"

    if marketplace_location:
        return marketplace_location

    return "Waikabubak, Sumba Barat, Nusa Tenggara Timur"


async def _run_scraper(
    mode: str,
    query: str,
    email: str,
    password: str,
    phone_only: bool,
    marketplace_location: str,
    marketplace_radius_km: int,
):
    storage_state_path = "facebook_state.json"
    has_storage_state = os.path.exists(storage_state_path)
    session = load_session()

    if session and not has_storage_state:
        _append_log("Metadata session ada, tetapi file state hilang. Login ulang akan dilakukan.")
        session = None

    _append_log("Menjalankan Playwright dalam mode headless (Chromium di background).")
    _set_state(status="Membuka browser background", progress=5)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            channel=BROWSER_CHANNEL,
            headless=True,
            slow_mo=SLOW_MO,
            args=BROWSER_ARGS,
        )

        context = await browser.new_context(
            storage_state=storage_state_path if session and has_storage_state else None,
            viewport=VIEWPORT,
            reduced_motion="reduce",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        context.set_default_timeout(BROWSER_TIMEOUT)
        context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT)

        if LIGHTWEIGHT_MODE:
            blocked_types = set(BLOCK_RESOURCE_TYPES)

            async def route_handler(route, req):
                if req.resource_type in blocked_types:
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_handler)

        page = await context.new_page()

        try:
            _set_state(status="Memeriksa status login", progress=12)
            is_logged_in = await check_login_status(page)

            if not is_logged_in:
                if not email or not password:
                    raise ValueError("Akun belum login. Isi email dan password di GUI untuk login.")
                _append_log("Session belum valid. Melakukan login Facebook.")
                _set_state(status="Login ke Facebook", progress=20)
                await login_to_facebook(page, email, password, context)
                await context.storage_state(path=storage_state_path)
                _append_log("Login berhasil dan session disimpan.")
            else:
                _append_log("Session login ditemukan, lanjut scraping.")

            if mode == "search":
                if not query:
                    raise ValueError("Kata kunci pencarian wajib diisi.")

                clean_query = query.strip()
                _set_state(status=f"Mencari kata kunci: {clean_query}", progress=40)
                _append_log(f"Navigasi pencarian kata kunci: {clean_query}")
                await search_posts_by_query(page, clean_query)

                _set_state(status="Mengambil hasil post", progress=75)
                data = await extract_search_results(page)

                if phone_only:
                    before_count = len(data)
                    data = _filter_phone_only(data)
                    _append_log(
                        f"Filter nomor telepon aktif: {before_count} -> {len(data)} post."
                    )

                if not data:
                    _append_log("Tidak ada data post yang memenuhi kriteria.")
                    return {
                        "output_file": None,
                        "total_data": 0,
                        "preview_columns": [],
                        "preview_rows": [],
                    }

                output_file = f"facebook_search_{clean_query.replace(' ', '_')}_{_timestamp()}.csv"
                save_to_csv(data, output_file)
                preview_payload = _build_preview_payload(data)
                _append_log(f"Scraping selesai. File disimpan: {output_file}")
                return {
                    "output_file": output_file,
                    "total_data": len(data),
                    "preview_columns": preview_payload["preview_columns"],
                    "preview_rows": preview_payload["preview_rows"],
                }

            if mode == "marketplace":
                if not query:
                    raise ValueError("Keyword marketplace wajib diisi.")

                clean_query = query.strip()
                _set_state(status=f"Marketplace search: {clean_query}", progress=40)
                _append_log(
                    f"Membuka Marketplace: keyword '{clean_query}', lokasi '{marketplace_location}', radius {marketplace_radius_km} km."
                )
                location_data = await search_marketplace_by_query(
                    page,
                    clean_query,
                    marketplace_location,
                    marketplace_radius_km,
                )

                _set_state(status="Mengambil listing marketplace", progress=78)
                data = await extract_marketplace_results(page)

                for row in data:
                    row["search_query"] = clean_query
                    row["search_location"] = location_data["label"]

                if phone_only:
                    before_count = len(data)
                    data = _filter_phone_only(data)
                    _append_log(
                        f"Filter nomor telepon aktif: {before_count} -> {len(data)} listing."
                    )

                if not data:
                    _append_log("Tidak ada listing marketplace yang memenuhi kriteria.")
                    return {
                        "output_file": None,
                        "total_data": 0,
                        "preview_columns": [],
                        "preview_rows": [],
                    }

                safe_name = clean_query.replace(' ', '_')
                output_file = f"facebook_marketplace_{safe_name}_{_timestamp()}.csv"
                save_to_csv(data, output_file)
                preview_payload = _build_preview_payload(data)
                _append_log(f"Marketplace scraping selesai. File disimpan: {output_file}")
                return {
                    "output_file": output_file,
                    "total_data": len(data),
                    "preview_columns": preview_payload["preview_columns"],
                    "preview_rows": preview_payload["preview_rows"],
                }

            if mode == "groups":
                _set_state(status="Membuka menu grup", progress=35)
                _append_log("Navigasi ke feed grup.")
                await navigate_to_groups_menu(page)

                _set_state(status="Mengambil daftar grup", progress=50)
                groups = await get_all_groups(page)
                if not groups:
                    _append_log("Tidak ada grup ditemukan dari akun ini.")
                    return {
                        "output_file": None,
                        "total_data": 0,
                    }

                if MAX_GROUPS_TO_PROCESS and len(groups) > MAX_GROUPS_TO_PROCESS:
                    groups = groups[:MAX_GROUPS_TO_PROCESS]
                    _append_log(f"Jumlah grup dibatasi ke {len(groups)} sesuai konfigurasi.")

                _append_log(f"Mulai scraping {len(groups)} grup.")
                all_data = []
                total_groups = len(groups)

                for idx, group in enumerate(groups, start=1):
                    # Progress dinaikkan bertahap seiring proses tiap grup.
                    progress = 55 + int((idx / total_groups) * 35)
                    _set_state(
                        status=f"Scraping grup {idx}/{total_groups}: {group['name']}",
                        progress=progress,
                    )
                    _append_log(f"Buka grup: {group['name']}")

                    try:
                        await page.goto(group["url"], wait_until="domcontentloaded")
                        await page.wait_for_timeout(2000)
                        group_data = await scrape_group_posts(page, days=365)
                        all_data.extend(group_data)
                        _append_log(f"{group['name']}: {len(group_data)} post ditemukan.")
                    except Exception as group_err:
                        log_error(f"Error scraping group {group['name']}: {str(group_err)}")
                        _append_log(f"Gagal scraping grup {group['name']}: {str(group_err)}")

                if not all_data:
                    _append_log("Tidak ada data post dari seluruh grup.")
                    return {
                        "output_file": None,
                        "total_data": 0,
                        "preview_columns": [],
                        "preview_rows": [],
                    }

                if phone_only:
                    before_count = len(all_data)
                    all_data = _filter_phone_only(all_data)
                    _append_log(
                        f"Filter nomor telepon aktif: {before_count} -> {len(all_data)} post."
                    )

                if not all_data:
                    _append_log("Tidak ada data grup yang memiliki nomor telepon.")
                    return {
                        "output_file": None,
                        "total_data": 0,
                        "preview_columns": [],
                        "preview_rows": [],
                    }

                output_file = f"facebook_groups_{_timestamp()}.csv"
                save_to_csv(all_data, output_file)
                preview_payload = _build_preview_payload(all_data)
                _append_log(f"Scraping grup selesai. File disimpan: {output_file}")
                return {
                    "output_file": output_file,
                    "total_data": len(all_data),
                    "preview_columns": preview_payload["preview_columns"],
                    "preview_rows": preview_payload["preview_rows"],
                }

            raise ValueError("Mode scraping tidak valid.")

        finally:
            await browser.close()


def _job_runner(
    job_id: str,
    mode: str,
    query: str,
    email: str,
    password: str,
    phone_only: bool,
    marketplace_location: str,
    marketplace_radius_km: int,
):
    try:
        result = asyncio.run(
            _run_scraper(
                mode,
                query,
                email,
                password,
                phone_only,
                marketplace_location,
                marketplace_radius_km,
            )
        )
        _set_state(
            running=False,
            status="Selesai",
            progress=100,
            output_file=result.get("output_file"),
            total_data=result.get("total_data", 0),
            preview_columns=result.get("preview_columns", []),
            preview_rows=result.get("preview_rows", []),
            error=None,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as err:
        log_error(f"Web app job error ({job_id}): {str(err)}")
        _append_log(f"Error: {str(err)}")
        _set_state(
            running=False,
            status="Gagal",
            error=str(err),
            preview_columns=[],
            preview_rows=[],
            finished_at=datetime.now().isoformat(),
        )


@app.get("/")
def index():
    response = make_response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.post("/api/start")
def start_scraping():
    payload = request.get_json(silent=True) or {}
    mode = (payload.get("mode") or "").strip().lower()
    query = (payload.get("query") or "").strip()
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    phone_only = bool(payload.get("phone_only", False))
    marketplace_location = (
        (payload.get("marketplace_location") or "Waikabubak, Sumba Barat, Nusa Tenggara Timur")
        .strip()
    )
    marketplace_kabupaten = (payload.get("marketplace_kabupaten") or "").strip()
    marketplace_kecamatan = (payload.get("marketplace_kecamatan") or "").strip()
    try:
        marketplace_radius_km = int(payload.get("marketplace_radius_km", 40))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Radius marketplace harus berupa angka."}), 400

    with state_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "Masih ada scraping yang berjalan."}), 409

    if mode not in {"search", "groups", "marketplace"}:
        return jsonify({"ok": False, "message": "Mode harus 'search', 'groups', atau 'marketplace'."}), 400

    if mode in {"search", "marketplace"} and not query:
        return jsonify({"ok": False, "message": "Kata kunci wajib diisi."}), 400

    if marketplace_radius_km < 1 or marketplace_radius_km > 500:
        return jsonify({"ok": False, "message": "Radius marketplace harus 1-500 km."}), 400

    marketplace_location = _resolve_marketplace_location(
        marketplace_location,
        marketplace_kabupaten,
        marketplace_kecamatan,
    )

    job_id = str(uuid4())
    _set_state(
        running=True,
        job_id=job_id,
        mode=mode,
        status="Memulai job",
        progress=1,
        logs=[],
        error=None,
        output_file=None,
        total_data=0,
        preview_columns=[],
        preview_rows=[],
        started_at=datetime.now().isoformat(),
        finished_at=None,
    )
    _append_log(f"Job {job_id} dimulai untuk mode: {mode}")
    if phone_only:
        _append_log("Filter aktif: hanya post dengan nomor telepon yang akan disimpan.")

    thread = threading.Thread(
        target=_job_runner,
        args=(
            job_id,
            mode,
            query,
            email,
            password,
            phone_only,
            marketplace_location,
            marketplace_radius_km,
        ),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/status")
def get_status():
    return jsonify(_snapshot_state())


@app.post("/api/reset")
def reset_status():
    cleared = _clear_finished_state()
    if not cleared:
        return jsonify({"ok": False, "message": "Job sedang berjalan, reset ditolak."}), 409
    return jsonify({"ok": True})


@app.post("/api/session/reset")
def reset_facebook_session():
    with state_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "Job sedang berjalan, reset session ditolak."}), 409

    delete_session()
    _clear_finished_state()
    return jsonify({"ok": True, "message": "Session Facebook berhasil dihapus. Login ulang diperlukan."})


@app.get("/api/location-options")
def get_location_options():
    return jsonify({
        "kabupaten_options": _build_location_options(),
        "default_kabupaten": "Sumba Barat",
        "default_kecamatan": "Waikabubak",
    })


@app.get("/api/download/<path:filename>")
def download_file(filename: str):
    safe_name = os.path.basename(filename)
    full_path = os.path.join(os.getcwd(), safe_name)
    if not os.path.exists(full_path):
        return jsonify({"ok": False, "message": "File tidak ditemukan."}), 404
    return send_from_directory(os.getcwd(), safe_name, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
