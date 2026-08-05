"""
Bybit News -> Telegram Bot (v2 — Telegram-source version)
==========================================================

api.bybit.com wale approach ko Bybit/Cloudflare block kar raha tha
GitHub Actions ke server se (403 Forbidden) — yeh known issue hai,
exchanges automation-server IPs ko block kar dete hain.

FIX: Ab hum Bybit ke apne OFFICIAL Telegram announcements channel
(@Bybit_Announcements) ka public preview page use kar rahe hain:

    https://t.me/s/Bybit_Announcements

Yeh Telegram ka apna domain hai (bybit.com nahi), koi login/block nahi
hai — Telegram in preview pages ko jaanbujh kar publicly crawlable
rakhta hai (link previews, RSS-jaisे tools ke liye). Same announcements,
zyada reliable source.

SETUP
-----
Do tarike se chala sakte ho:

1) GitHub Actions (recommended, cron-scheduled): script by default
   SINGLE-RUN mode me chalta hai — ek baar check karta hai, post karta
   hai, exit ho jata hai. GitHub Actions workflow isko har X minute pe
   trigger karega.

2) VPS/apna server (hamesha-chalta-rahe mode): env var
   LOOP_FOREVER=1 set karo, phir `python3 bybit_news_bot.py` chalao.

Dono cases me BOT_TOKEN aur CHANNEL_ID environment variables se set
karne hain — yeh TUMHARE naye bot/channel ke hain (jahan post karna
hai), source channel se inka koi lena-dena nahi.

Har message sirf EK BAAR post hoga — already-posted message-IDs ek
local file (seen_messages.json) me save hote hain.
"""

import json
import logging
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============ CONFIG — apne values yahan daalo ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@TheCapitalVertex")  # jahan POST karna hai

SOURCE_CHANNEL = "Bybit_Announcements"   # Bybit ka official announcements channel (source)
SOURCE_URL = f"https://t.me/s/{SOURCE_CHANNEL}"

POLL_INTERVAL_SECONDS = 300
LOOP_FOREVER = os.environ.get("LOOP_FOREVER", "0") == "1"

SEEN_FILE = Path(__file__).parent / "seen_messages.json"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{{token}}/sendMessage"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
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
            log.warning("seen_messages.json corrupt hai, fresh start kar rahe hain")
    return set()


def save_seen(seen: set) -> None:
    trimmed = list(seen)[-500:]
    SEEN_FILE.write_text(json.dumps(trimmed))


def fetch_source_html() -> str:
    try:
        resp = requests.get(SOURCE_URL, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.error("Source channel fetch failed: %s", e)
        return ""


def parse_messages(html: str) -> list:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    messages = []

    for msg_div in soup.select("div.tgme_widget_message"):
        post_id = msg_div.get("data-post")
        if not post_id:
            continue

        text_div = msg_div.select_one(".tgme_widget_message_text")
        text = text_div.get_text(separator="\n").strip() if text_div else ""
        if not text:
            continue  # sirf-image/video wale posts (bina caption) skip

        messages.append({
            "id": post_id,
            "text": text,
            "url": f"https://t.me/{post_id}",
        })

    return messages  # page me already oldest -> newest order me aate hain


def format_message(item: dict) -> str:
    text = re.sub(r"\n{3,}", "\n\n", item["text"])  # extra blank lines hatao
    if len(text) > 3800:
        text = text[:3800].rsplit("\n", 1)[0] + "…"
    return f"📢 {text}"


def send_to_telegram(text: str) -> bool:
    url = TELEGRAM_API_URL.format(token=BOT_TOKEN)
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
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
    html = fetch_source_html()
    messages = parse_messages(html)
    if not messages:
        log.info("Source se koi message parse nahi hua is baar.")
        return seen

    for item in messages:
        if item["id"] in seen:
            continue

        if send_to_telegram(format_message(item)):
            log.info("Posted: %s", item["id"])
            seen.add(item["id"])
            save_seen(seen)
            time.sleep(2)
        else:
            log.warning("Skip (send fail), agli baar retry hoga: %s", item["id"])

    return seen


def main():
    seen = load_seen()

    if LOOP_FOREVER:
        log.info("Loop mode ON. Har %ss me check karega.", POLL_INTERVAL_SECONDS)
        while True:
            seen = run_once(seen)
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        log.info("Single-run mode. Ek baar check karke exit ho jayega.")
        run_once(seen)


if __name__ == "__main__":
    main()
