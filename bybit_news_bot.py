"""
Bybit News -> Telegram Bot
==========================

Bybit ki website khud JS-heavy hai isliye scraping unreliable hoti,
lekin Bybit ek OFFICIAL PUBLIC API deta hai jahan se saari announcements/
news milti hain (bina API key ke bhi kaam karta hai):

    GET https://api.bybit.com/v5/announcements/index

Yeh script us API ko poll karta hai, naye announcements detect karta hai,
aur unhe tumhare Telegram channel/group pe auto-post kar deta hai.

SETUP
-----
Do tarike se chala sakte ho:

1) GitHub Actions (cron-scheduled, recommended — same pattern jaise
   tumhare purane bots): script by default SINGLE-RUN mode me chalta
   hai — ek baar check karta hai, post karta hai, exit ho jata hai.
   GitHub Actions workflow isko har X minute pe trigger karega.

2) VPS/apna server (hamesha-chalta-rahe mode): env var
   LOOP_FOREVER=1 set karo, phir `python3 bybit_news_bot.py` chalao —
   yeh khud hi loop me chalta rahega.

Dono cases me BOT_TOKEN aur CHANNEL_ID environment variables se
(ya seedha CONFIG section me) set karne hain.

Har announcement sirf EK BAAR post hoga — already-posted URLs ek
local file (seen_announcements.json) me save hote hain, so agli baar
duplicate posts nahi aayenge.
"""

import json
import logging
import os
import time
from pathlib import Path

import requests

# ============ CONFIG — apne values yahan daalo ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@your_channel_username")  # ya -1001234567890

LOCALE = "en-US"          # announcement language
ANN_TYPE = ""             # blank = all types. Options: new_crypto, delisting, latest_activities,
                          # maintenance_system_updates, product_updates etc (see Bybit docs)
FETCH_LIMIT = 20          # kitni latest announcements har baar fetch karni hain
POLL_INTERVAL_SECONDS = 300  # sirf tab use hota hai jab LOOP_FOREVER=1 ho (local/VPS run)
LOOP_FOREVER = os.environ.get("LOOP_FOREVER", "0") == "1"

SEEN_FILE = Path(__file__).parent / "seen_announcements.json"
BYBIT_API_URL = "https://api.bybit.com/v5/announcements/index"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{{token}}/sendMessage"
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bybit-news-bot")


def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except json.JSONDecodeError:
            log.warning("seen_announcements.json corrupt hai, fresh start kar rahe hain")
    return set()


def save_seen(seen: set) -> None:
    # sirf latest 500 rakho, file infinite na badhe
    trimmed = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(trimmed))


def fetch_announcements() -> list:
    params = {"locale": LOCALE, "limit": FETCH_LIMIT}
    if ANN_TYPE:
        params["type"] = ANN_TYPE
    try:
        resp = requests.get(BYBIT_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            log.error("Bybit API error: %s", data.get("retMsg"))
            return []
        return data.get("result", {}).get("list", [])
    except requests.RequestException as e:
        log.error("Bybit API fetch failed: %s", e)
        return []


def format_message(item: dict) -> str:
    title = item.get("title", "").strip()
    description = item.get("description", "").strip()
    url = item.get("url", "")
    type_title = item.get("type", {}).get("title", "")

    msg = f"📢 <b>{title}</b>\n"
    if type_title:
        msg += f"🏷 {type_title}\n"
    if description and description != title:
        msg += f"\n{description}\n"
    if url:
        msg += f"\n🔗 <a href=\"{url}\">Read more</a>"
    return msg


def send_to_telegram(text: str) -> bool:
    url = TELEGRAM_API_URL.format(token=BOT_TOKEN)
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        if resp.status_code == 200:
            return True
        log.error("Telegram send failed [%s]: %s", resp.status_code, resp.text)
        return False
    except requests.RequestException as e:
        log.error("Telegram send exception: %s", e)
        return False


def run_once(seen: set) -> set:
    announcements = fetch_announcements()
    if not announcements:
        return seen

    # oldest-first post karo taaki channel me chronological order bane
    for item in reversed(announcements):
        url = item.get("url")
        if not url or url in seen:
            continue

        message = format_message(item)
        if send_to_telegram(message):
            log.info("Posted: %s", item.get("title"))
            seen.add(url)
            save_seen(seen)
            time.sleep(2)  # Telegram rate limit se bachne ke liye chhota gap
        else:
            log.warning("Skip (send fail), agli baar retry hoga: %s", item.get("title"))

    return seen


def main():
    seen = load_seen()

    if LOOP_FOREVER:
        # VPS / apna server pe chhodne ke liye (hamesha chalta rahega)
        log.info("Loop mode ON. Har %ss me check karega.", POLL_INTERVAL_SECONDS)
        while True:
            seen = run_once(seen)
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        # GitHub Actions / cron ke liye — ek baar check karke exit
        log.info("Single-run mode. Ek baar check karke exit ho jayega (schedule outside karega).")
        run_once(seen)


if __name__ == "__main__":
    main()
