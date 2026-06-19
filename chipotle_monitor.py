#!/usr/bin/env python3
"""
Chipotle Promo Monitor
- Twitter/X: Real-time filtered stream (instant, no polling)
- Reddit: Polls r/chipotle, r/deals, r/freebies, r/frugal every 3s
- Chipotle.com: Polls homepage + /promos every 5s
Sends Discord webhook with one-tap SMS deep link on detection.
"""

import os
import re
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "YOUR_DISCORD_WEBHOOK_HERE")
TWITTER_BEARER     = os.environ.get("TWITTER_BEARER_TOKEN", "")
CHIPOTLE_SHORTCODE = "888222"

REDDIT_INTERVAL    = 3    # seconds between Reddit polls
WEBSITE_INTERVAL   = 5    # seconds between Chipotle.com polls
STREAM_RECONNECT   = 10   # seconds before Twitter stream reconnect on failure

SUBREDDITS = ["chipotle", "deals", "freebies", "frugal"]
CHIPOTLE_URLS = [
    "https://www.chipotle.com/",
    "https://www.chipotle.com/promos",
]

PROMO_KEYWORDS = [
    "text", "free", "bogo", "guac", "burrito", "promo", "code",
    "limited", "first", "people", "offer", "deal", "888222",
    "chipotle rewards", "freebie", "win", "score"
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ─── STATE ────────────────────────────────────────────────────────────────────

seen_ids            = set()
last_chipotle_hash  = ""

# ─── DISCORD ──────────────────────────────────────────────────────────────────

def send_discord_alert(source: str, keyword: str, text: str, url: str = ""):
    sms_link = f"sms:{CHIPOTLE_SHORTCODE}?&body={keyword}" if keyword else ""

    embed = {
        "title": "🌯 CHIPOTLE PROMO DETECTED",
        "color": 0xA81612,
        "fields": [
            {"name": "📡 Source", "value": source, "inline": True},
            {"name": "🕐 Time",   "value": f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>", "inline": True},
            {"name": "📝 Snippet","value": text[:300] if text else "N/A", "inline": False},
        ],
        "footer": {"text": "Chipotle Promo Monitor • tap SMS link to claim"}
    }

    if url:
        embed["fields"].append({"name": "🔗 Link", "value": url, "inline": False})

    if sms_link:
        embed["fields"].append({
            "name": "📱 One-Tap Claim",
            "value": f"[Tap to text {CHIPOTLE_SHORTCODE}]({sms_link})\n`{sms_link}`",
            "inline": False
        })
        embed["description"] = f"**Keyword detected: `{keyword}`**"

    payload = {
        "content": "@everyone 🚨 **CHIPOTLE PROMO DROP** — act fast!",
        "embeds": [embed]
    }

    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 204:
            log.info(f"✅ Discord alert sent | source={source} keyword={keyword}")
        else:
            log.warning(f"Discord {r.status_code}: {r.text}")
    except Exception as e:
        log.error(f"Discord alert failed: {e}")

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def extract_sms_keyword(text: str) -> str:
    patterns = [
        r"text\s+([A-Z0-9]{4,20})\s+to\s+888222",
        r"text\s+([A-Z0-9]{4,20})\s+to\s+\(888\)\s*222",
        r"keyword[:\s]+([A-Z0-9]{4,20})",
        r"code[:\s]+([A-Z0-9]{4,20})",
        r"text\s+([A-Z0-9]{4,20})\s+now",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return ""

STRONG_SIGNALS = [
    "888222",
    "text to win",
    "free entree",
    "free burrito",
    "promo code",
    "first 10,000",
    "first 5,000",
    "first 1,000",
    "limited codes",
    "while supplies last",
]

def is_promo_text(text: str, strong_only: bool = False) -> bool:
    t = text.lower()
    chipotle_ref = any(w in t for w in ["chipotle", "burrito", "guac", "888222"])
    has_strong = any(s in t for s in STRONG_SIGNALS)
    if strong_only:
        return chipotle_ref and has_strong
    signal_count = sum(1 for kw in PROMO_KEYWORDS if kw in t)
    return chipotle_ref and (has_strong or signal_count >= 3)

# ─── TWITTER FILTERED STREAM (real-time, push-based) ─────────────────────────

STREAM_URL = "https://api.twitter.com/2/tweets/search/stream"
RULES_URL  = "https://api.twitter.com/2/tweets/search/stream/rules"

def twitter_headers():
    return {
        "Authorization": f"Bearer {TWITTER_BEARER}",
        "User-Agent": "ChipotlePromoMonitor",
    }

def setup_stream_rules():
    """Clear old rules and set rule to only stream @ChipotleTweets."""
    try:
        # Get existing rules
        r = requests.get(RULES_URL, headers=twitter_headers(), timeout=10)
        existing = r.json()
        if "data" in existing:
            ids = [rule["id"] for rule in existing["data"]]
            requests.post(RULES_URL, headers=twitter_headers(),
                          json={"delete": {"ids": ids}}, timeout=10)

        # Add our rule
        payload = {"add": [{"value": "from:ChipotleTweets", "tag": "chipotle-live"}]}
        r2 = requests.post(RULES_URL, headers=twitter_headers(), json=payload, timeout=10)
        if r2.status_code in (200, 201):
            log.info("✅ Twitter stream rule set: from:ChipotleTweets")
        else:
            log.warning(f"Twitter rule setup failed: {r2.status_code} {r2.text}")
    except Exception as e:
        log.error(f"Twitter rule setup error: {e}")

def process_tweet(tweet_json: dict):
    tweet_id   = tweet_json.get("data", {}).get("id", "")
    tweet_text = tweet_json.get("data", {}).get("text", "")

    if not tweet_id or tweet_id in seen_ids:
        return
    seen_ids.add(tweet_id)

    log.info(f"🐦 Tweet received: {tweet_text[:80]}")

    if is_promo_text(tweet_text):
        keyword  = extract_sms_keyword(tweet_text)
        tweet_url = f"https://twitter.com/ChipotleTweets/status/{tweet_id}"
        send_discord_alert(
            source="Twitter/X @ChipotleTweets (live stream)",
            keyword=keyword,
            text=tweet_text,
            url=tweet_url
        )
    else:
        log.info("  → Not a promo tweet, skipping.")

def run_twitter_stream():
    """Persistent blocking stream — reconnects on failure."""
    if not TWITTER_BEARER:
        log.warning("⚠️  No TWITTER_BEARER_TOKEN set — Twitter stream disabled.")
        return

    setup_stream_rules()

    while True:
        try:
            log.info("🐦 Connecting to Twitter filtered stream...")
            with requests.get(
                STREAM_URL,
                headers=twitter_headers(),
                stream=True,
                timeout=90,
                params={"tweet.fields": "text,created_at"}
            ) as resp:
                if resp.status_code != 200:
                    log.warning(f"Twitter stream error {resp.status_code}: {resp.text[:200]}")
                    time.sleep(STREAM_RECONNECT)
                    continue

                log.info("✅ Twitter stream connected — listening for @ChipotleTweets...")
                for line in resp.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            process_tweet(data)
                        except json.JSONDecodeError:
                            pass

        except Exception as e:
            log.error(f"Twitter stream dropped: {e}")

        log.info(f"Reconnecting Twitter stream in {STREAM_RECONNECT}s...")
        time.sleep(STREAM_RECONNECT)

# ─── REDDIT MONITOR ───────────────────────────────────────────────────────────

def check_reddit():
    headers = {"User-Agent": "ChipotlePromoMonitor/1.0"}
    for sub in SUBREDDITS:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/new.json?limit=10",
                headers=headers, timeout=10
            )
            if r.status_code != 200:
                continue
            for post in r.json().get("data", {}).get("children", []):
                d       = post["data"]
                post_id = d["id"]
                if post_id in seen_ids:
                    continue
                full_text = f"{d.get('title','')} {d.get('selftext','')}"
                if is_promo_text(full_text):
                    seen_ids.add(post_id)
                    keyword = extract_sms_keyword(full_text)
                    log.info(f"🔴 Reddit promo in r/{sub}: {d.get('title','')[:60]}")
                    send_discord_alert(
                        source=f"Reddit r/{sub}",
                        keyword=keyword,
                        text=full_text[:300],
                        url=f"https://reddit.com{d.get('permalink','')}"
                    )
        except Exception as e:
            log.warning(f"Reddit r/{sub} error: {e}")

def run_reddit_loop():
    log.info(f"🔴 Reddit monitor started (every {REDDIT_INTERVAL}s)")
    while True:
        check_reddit()
        time.sleep(REDDIT_INTERVAL)

# ─── CHIPOTLE WEBSITE MONITOR ─────────────────────────────────────────────────

def check_chipotle_website():
    global last_chipotle_hash
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    for url in CHIPOTLE_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            text = BeautifulSoup(r.text, "html.parser").get_text(separator=" ", strip=True)
            content_hash = str(hash(text[:5000]))
            if content_hash == last_chipotle_hash:
                continue
            last_chipotle_hash = content_hash
            if is_promo_text(text, strong_only=True):
                keyword = extract_sms_keyword(text)
                log.info(f"🌐 Chipotle website change detected: {url}")
                send_discord_alert(
                    source="Chipotle Website",
                    keyword=keyword,
                    text=text[:300],
                    url=url
                )
        except Exception as e:
            log.warning(f"Chipotle website error ({url}): {e}")

def run_website_loop():
    log.info(f"🌐 Website monitor started (every {WEBSITE_INTERVAL}s)")
    while True:
        check_chipotle_website()
        time.sleep(WEBSITE_INTERVAL)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("🌯 Chipotle Promo Monitor starting...")
    log.info(f"  Twitter stream: {'✅ enabled' if TWITTER_BEARER else '⚠️  disabled (no bearer token)'}")
    log.info(f"  Reddit:         ✅ polling every {REDDIT_INTERVAL}s")
    log.info(f"  Chipotle.com:   ✅ polling every {WEBSITE_INTERVAL}s")

    # Startup ping
    try:
        requests.post(DISCORD_WEBHOOK, json={
            "content": (
                "✅ **Chipotle monitor is live!**\n"
                f"🐦 Twitter: {'real-time stream' if TWITTER_BEARER else 'DISABLED — add TWITTER_BEARER_TOKEN'}\n"
                f"🔴 Reddit: polling every {REDDIT_INTERVAL}s\n"
                f"🌐 Chipotle.com: polling every {WEBSITE_INTERVAL}s"
            )
        }, timeout=10)
    except Exception:
        pass

    # Run Reddit + Website in background threads
    threading.Thread(target=run_reddit_loop,  daemon=True).start()
    threading.Thread(target=run_website_loop, daemon=True).start()

    # Twitter stream runs on main thread (blocks, reconnects on failure)
    if TWITTER_BEARER:
        run_twitter_stream()
    else:
        log.warning("Twitter stream not running. Add TWITTER_BEARER_TOKEN env var for real-time coverage.")
        # Keep main thread alive
        while True:
            time.sleep(60)

if __name__ == "__main__":
    main()
