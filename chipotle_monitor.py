#!/usr/bin/env python3
"""
Chipotle Promo Code Monitor (Twitter polling only)

Polls a fixed list of Twitter/X accounts every POLL_INTERVAL seconds using the
locally-installed twitter-cli (cookie auth). Whenever a monitored account posts
a tweet containing "888222", fires a Discord webhook alert immediately with a
one-tap SMS deep link to claim the code.

No Reddit, no website scraping, no streaming API — just the polling loop.

Env vars:
  DISCORD_WEBHOOK  (required)  Discord webhook URL
  POLL_INTERVAL    (optional)  seconds between full poll cycles, default 30
"""

import os
import re
import sys
import json
import time
import logging
import subprocess
from datetime import datetime, timezone

import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "").strip()
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", "30"))
CHIPOTLE_SHORTCODE = "888222"
TWEETS_PER_ACCOUNT = 5

# Accounts to monitor (without the leading @).
ACCOUNTS = [
    "usahockey", "LordOfDiscounts", "LordOfSavings", "Pricerrors",
    "Sneaky_Steals", "thedealsguy_", "Info4Days", "GlitchedDeals",
    "Wario64", "Dexerto", "ChipotleTweets", "OldSchoolRS",
    "ShockedDeals", "HoomanDeals", "GlitchDealGroup", "Misprints",
]

# twitter-cli lives in pipx's bin dir; make sure it's reachable.
TWITTER_BIN = os.environ.get("TWITTER_BIN", "twitter")

# Regex to pull the SMS keyword out of "text <KEYWORD> to 888222".
SMS_KEYWORD_RE = re.compile(r"text\s+([A-Z0-9]+)\s+to\s+888222", re.IGNORECASE)

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chipotle_monitor")

# ─── STATE ────────────────────────────────────────────────────────────────────

seen_ids = set()

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def extract_sms_keyword(text):
    """Return the keyword to text to 888222, or '' if none found."""
    m = SMS_KEYWORD_RE.search(text)
    return m.group(1).upper() if m else ""


def fetch_account_tweets(account):
    """Run twitter-cli for one account and return a list of tweet dicts.

    Uses `twitter user-posts <account> -n 5 --json`. (Note: the CLI exposes
    a user's tweets via `user-posts`, not `user`, and the count flag is -n.)
    """
    try:
        proc = subprocess.run(
            [TWITTER_BIN, "user-posts", account, "-n", str(TWEETS_PER_ACCOUNT), "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        log.warning(f"  @{account}: timed out")
        return []
    except FileNotFoundError:
        log.error(f"twitter-cli not found at '{TWITTER_BIN}'. Set TWITTER_BIN env var.")
        return []

    if proc.returncode != 0:
        log.warning(f"  @{account}: cli exit {proc.returncode}: {proc.stderr.strip()[:120]}")
        return []

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log.warning(f"  @{account}: could not parse JSON output")
        return []

    # twitter-cli returns {"ok": true, "data": [ ...tweets... ]}
    if isinstance(data, dict):
        return data.get("data", []) or []
    if isinstance(data, list):
        return data
    return []


def tweet_url(tweet, account):
    author = tweet.get("author") or {}
    handle = author.get("screenName") or account
    return f"https://x.com/{handle}/status/{tweet.get('id', '')}"


# ─── DISCORD ──────────────────────────────────────────────────────────────────

def send_startup_ping():
    handles = ", ".join(f"@{a}" for a in ACCOUNTS)
    payload = {
        "content": (
            "✅ **Chipotle promo monitor is live!**\n"
            f"🐦 Polling {len(ACCOUNTS)} Twitter accounts every {POLL_INTERVAL}s for "
            f"`{CHIPOTLE_SHORTCODE}`.\n"
            f"📋 Watching: {handles}"
        )
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 204:
            log.info("✅ Startup ping sent to Discord")
        else:
            log.warning(f"Startup ping Discord {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"Startup ping failed: {e}")


def send_discord_alert(account, text, url):
    keyword  = extract_sms_keyword(text)
    sms_link = f"sms:{CHIPOTLE_SHORTCODE}?&body={keyword}" if keyword else ""

    embed = {
        "title": "🌯 CHIPOTLE PROMO DETECTED",
        "color": 0xA81612,
        "fields": [
            {"name": "📡 Account", "value": f"@{account}", "inline": True},
            {"name": "🕐 Time",
             "value": f"<t:{int(datetime.now(timezone.utc).timestamp())}:R>",
             "inline": True},
            {"name": "📝 Tweet", "value": text[:1000] if text else "N/A", "inline": False},
            {"name": "🔗 Link", "value": url, "inline": False},
        ],
        "footer": {"text": "Chipotle Promo Monitor • tap SMS link to claim"},
    }

    if sms_link:
        embed["description"] = f"**Keyword detected: `{keyword}`**"
        embed["fields"].append({
            "name": "📱 One-Tap Claim",
            "value": f"[Tap to text {CHIPOTLE_SHORTCODE}]({sms_link})\n`{sms_link}`",
            "inline": False,
        })

    payload = {
        "content": "@everyone 🚨 **CHIPOTLE PROMO DROP** — act fast!",
        "embeds": [embed],
    }

    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 204:
            log.info(f"✅ Discord alert sent | @{account} keyword={keyword or 'n/a'}")
        else:
            log.warning(f"Discord {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"Discord alert failed: {e}")


# ─── POLL LOOP ────────────────────────────────────────────────────────────────

def poll_cycle():
    log.info(f"── Poll cycle: checking {len(ACCOUNTS)} accounts ──")
    hits = 0
    for account in ACCOUNTS:
        tweets = fetch_account_tweets(account)
        log.info(f"  @{account}: {len(tweets)} tweet(s) fetched")
        for tweet in tweets:
            tid  = tweet.get("id")
            text = tweet.get("text", "") or ""
            if not tid:
                continue
            if CHIPOTLE_SHORTCODE not in text:
                continue
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            url = tweet_url(tweet, account)
            log.info(f"  🎯 HIT @{account}: {text[:80]!r} → {url}")
            send_discord_alert(account, text, url)
            hits += 1
    log.info(f"── Cycle done: {hits} new hit(s), {len(seen_ids)} ids tracked ──")


def prime_seen_ids():
    """Record existing 888222 tweets WITHOUT alerting, so the first live cycle
    only fires on genuinely new drops (avoids a burst of alerts on startup)."""
    log.info("Priming seen-ids from current tweets (no alerts)...")
    for account in ACCOUNTS:
        for tweet in fetch_account_tweets(account):
            tid  = tweet.get("id")
            text = tweet.get("text", "") or ""
            if tid and CHIPOTLE_SHORTCODE in text:
                seen_ids.add(tid)
    log.info(f"Primed {len(seen_ids)} existing 888222 tweet id(s).")


def main():
    if not DISCORD_WEBHOOK:
        log.error("DISCORD_WEBHOOK env var is required. Exiting.")
        sys.exit(1)

    log.info("🌯 Chipotle promo monitor starting...")
    log.info(f"  Accounts: {len(ACCOUNTS)} | poll interval: {POLL_INTERVAL}s | keyword: {CHIPOTLE_SHORTCODE}")

    send_startup_ping()
    prime_seen_ids()

    while True:
        try:
            poll_cycle()
        except Exception as e:
            log.error(f"Poll cycle error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
