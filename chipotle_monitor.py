#!/usr/bin/env python3
"""
Chipotle Promo Code Monitor — Twitter engine (twitterapi.io)

Watches Twitter/X in near-real-time for any tweet that tells people to text a
keyword to Chipotle's 888222 short code, and fires a Discord alert the moment
one drops, with a one-tap SMS deep link to claim it.

Why twitterapi.io instead of scraping deal accounts:
  The original keywords are posted by the *partner* accounts (@PGATOUR for the
  golf "Hot Streak" promo, @usahockey, @ChipotleTweets, ...). The deal-repost
  accounts we used to poll lag the source by 30-50s. A single wide search for
  the 888222 short code catches whoever posts it FIRST — partner, league, or a
  brand-new source we've never heard of — within one poll interval.

Cost control:
  advanced_search bills per tweet RETURNED. We attach `since_time:<unix>` to the
  query so quiet polls return ~0 tweets (~$0); we only pay during real drops.
  Expected spend at this volume: ~$1-5/month.

Scope note:
  This is the *Twitter* half. Codes that only ever appear on-screen during a
  live Twitch/broadcast stream (and are never posted as text) cannot be caught
  here by design — those need the separate OCR engine.

Required env vars:
  DISCORD_WEBHOOK    Discord webhook URL
  TWITTERAPI_KEY     twitterapi.io API key (x-api-key)

Optional env vars:
  POLL_INTERVAL      seconds between polls (default 10)
  OVERLAP_SECONDS    since_time look-back buffer to avoid edge misses (default 20)
  HEARTBEAT_HOURS    interval for "still alive" pings, 0 disables (default 6)
  CODE_LOG_FILE      JSONL log of every caught code (default codes_log.jsonl)
  SEARCH_QUERY       override the search query (advanced)
"""

import os
import re
import sys
import json
import time
import logging
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo          # py3.9+ stdlib
    _HAVE_ZONEINFO = True
except ImportError:                        # pragma: no cover
    _HAVE_ZONEINFO = False

import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────

DISCORD_WEBHOOK    = os.environ.get("DISCORD_WEBHOOK", "").strip()
TWITTERAPI_KEY     = os.environ.get("TWITTERAPI_KEY", "").strip()
# Optional separate webhook for the "alive" heartbeat (keep it out of the alert
# channel). Falls back to the main webhook if unset.
HEARTBEAT_WEBHOOK  = os.environ.get("HEARTBEAT_WEBHOOK", "").strip() or DISCORD_WEBHOOK

CHIPOTLE_SHORTCODE = "888222"
POLL_INTERVAL      = int(os.environ.get("POLL_INTERVAL", "6"))
OVERLAP_SECONDS    = int(os.environ.get("OVERLAP_SECONDS", "20"))
HEARTBEAT_HOURS    = float(os.environ.get("HEARTBEAT_HOURS", "6"))
CODE_LOG_FILE      = os.environ.get("CODE_LOG_FILE", "codes_log.jsonl")

# ─── SCHEDULE-AWARE POLLING ─────────────────────────────────────────────────
# Codes drop on a tight, predictable schedule (backtest of 37 real text codes:
# golf "Hot Streak" is 100% Thu-Sun afternoons ET; hockey is rare Feb tournament
# bursts). Cost is ~per-poll, so polling fast 24/7 burns ~$30/mo mostly at 3am
# Tuesday for nothing. We poll FAST (POLL_INTERVAL) inside drop windows and SLOW
# (POLL_SLOW) otherwise. FAIL-OPEN by design: off-window is *slow, never paused*,
# and any schedule error (or missing tz data) reverts to FAST — so the worst a
# wrong schedule can do is "caught a bit late", never "missed". The since_time
# lookback in poll_cycle scales with whichever interval this picks, so slow
# periods never drop tweets in the gap. SCHEDULE_ENABLED=0 -> flat POLL_INTERVAL.
SCHEDULE_ENABLED = os.environ.get("SCHEDULE_ENABLED", "1") != "0"
POLL_SLOW        = int(os.environ.get("POLL_SLOW", "60"))        # off-window baseline
SCHEDULE_TZ      = os.environ.get("SCHEDULE_TZ", "America/New_York")
FAST_DAYS        = {3, 4, 5, 6}   # Mon=0..Sun=6 -> Thu,Fri,Sat,Sun (PGA rounds)
FAST_START_HOUR  = int(os.environ.get("FAST_START_HOUR", "10"))  # local (ET), inclusive
FAST_END_HOUR    = int(os.environ.get("FAST_END_HOUR", "20"))    # local (ET), exclusive
# Manual fast windows for known one-off events (Olympic/major hockey, etc.):
# inclusive local-date ranges. Add as events approach, e.g. ("2026-02-11","2026-02-22").
EVENT_WINDOWS    = []

# On startup, mark codes already circulating as "seen" so we don't re-announce
# old codes (e.g. a code from yesterday still being reposted). Looks back this
# many hours, paginating up to PRIME_MAX_PAGES.
PRIME_LOOKBACK_HOURS = float(os.environ.get("PRIME_LOOKBACK_HOURS", "48"))
PRIME_MAX_PAGES      = int(os.environ.get("PRIME_MAX_PAGES", "5"))

# twitterapi.io free tier allows 1 request / 5s. We enforce a minimum gap
# between API calls (with margin) so bursts — e.g. priming then the first poll —
# can never trip a 429. Lower this if you upgrade to a paid plan.
MIN_CALL_SPACING   = float(os.environ.get("MIN_CALL_SPACING", "5.5"))

TWITTERAPI_BASE    = "https://api.twitterapi.io"
SEARCH_URL         = f"{TWITTERAPI_BASE}/twitter/tweet/advanced_search"

# The shortcode is written both as "888222" and "888-222" (partner accounts use
# the hyphen). Quote the hyphenated form so search doesn't treat '-' as NOT.
SEARCH_QUERY = os.environ.get("SEARCH_QUERY", '888222 OR "888-222"')

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("chipotle_monitor")

# ─── STATE ────────────────────────────────────────────────────────────────────

seen_codes = set()   # alert once per keyword, no matter how many reposts
seen_ids   = set()   # avoid reprocessing the same tweet across overlapping polls

# API-health tracking so a dead/empty balance can't silently kill monitoring.
api_error_streak = 0       # consecutive failed searches
api_warning_active = False  # a warning is currently outstanding (don't re-spam)
API_ERROR_THRESHOLD = 3    # warn after this many consecutive failures
_last_api_call = 0.0       # wall-clock of last API request, for rate limiting

# ─── HELPERS ──────────────────────────────────────────────────────────────────

# Match "888222" or "888-222" (or "888 222"), but NOT when it's part of a longer
# number like a phone number "888-222-9999" (no digit/hyphen immediately around it).
SHORTCODE_RE = re.compile(r"(?<!\d)888[-\s]?222(?![\d-])")

# Grab the keyword token immediately before "to 888222" — robust to phrasings
# like "text ZRQ792 to 888222" and "...who text STRO41821 to 888-222 get a BOGO".
KEYWORD_RE = re.compile(r"([A-Za-z0-9]{4,16})\s+to\s+888[-\s]?222(?![\d-])", re.IGNORECASE)


def extract_keyword(text):
    """Return the keyword to text to 888222 (uppercased), or '' if none found.

    Requires the token to contain a digit. Real Chipotle codes are always
    alphanumeric with digits (GLE538, ZRQ792, CART60748, PWVER7771); a backtest
    of 37 real text codes found every one carried a digit. Generic announcement
    tweets ("text the code to 888222", with the code shown only in an image/Reel
    — e.g. Super Bowl, NBA Finals) otherwise mis-extract the filler word (CODE,
    DROP, THAT, IMAGE) and fire a false @everyone alert. The digit guard drops
    those; such tweets then fall through to the existing "shortcode w/o parseable
    code" log, which is the correct OCR-case signal."""
    m = KEYWORD_RE.search(text or "")
    if not m:
        return ""
    kw = m.group(1).upper()
    return kw if any(c.isdigit() for c in kw) else ""


def has_shortcode(text):
    return bool(SHORTCODE_RE.search(text or ""))


def tweet_url(tweet):
    author = tweet.get("author") or {}
    handle = author.get("userName") or "i"
    return f"https://x.com/{handle}/status/{tweet.get('id', '')}"


def log_code(code, tweet, source):
    """Append one JSONL row per caught code for the ROI/redemption scoreboard."""
    row = {
        "caught_at": datetime.now(timezone.utc).isoformat(),
        "code": code,
        "source": source,
        "tweet_id": tweet.get("id"),
        "url": tweet_url(tweet),
        "text": (tweet.get("text") or "")[:280],
        "redeemed": None,   # fill in manually: true / false / "all out"
    }
    try:
        with open(CODE_LOG_FILE, "a") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning(f"Could not write code log: {e}")


# ─── TWITTER (twitterapi.io) ────────────────────────────────────────────────────

def search_tweets(since_unix, cursor=""):
    """Return (tweets, next_cursor, has_next_page) for one page matching
    SEARCH_QUERY since `since_unix` (newest first). Returns ([], "", False) on any
    error so the loop keeps running. Tracks API health so an exhausted balance /
    bad key can't fail silently."""
    global _last_api_call
    # Respect the free-tier QPS limit no matter when we're called.
    wait = MIN_CALL_SPACING - (time.time() - _last_api_call)
    if wait > 0:
        time.sleep(wait)

    query = f"{SEARCH_QUERY} since_time:{since_unix}"
    try:
        _last_api_call = time.time()
        r = requests.get(
            SEARCH_URL,
            headers={"X-API-Key": TWITTERAPI_KEY},
            params={"query": query, "queryType": "Latest", "cursor": cursor},
            timeout=15,
        )
    except requests.RequestException as e:
        log.warning(f"search request failed: {e}")
        note_api_error("network", str(e)[:120])
        return [], "", False

    # 402=out of credits, 401/403=bad/expired key, 429=rate limited.
    if r.status_code != 200:
        log.warning(f"search HTTP {r.status_code}: {r.text[:200]}")
        note_api_error(r.status_code, r.text[:120])
        return [], "", False

    try:
        data = r.json()
    except ValueError:
        log.warning("search returned non-JSON")
        note_api_error("non-json", "")
        return [], "", False

    note_api_ok()
    return (data.get("tweets", []) or [],
            data.get("next_cursor", "") or "",
            bool(data.get("has_next_page")))


# ─── DISCORD ──────────────────────────────────────────────────────────────────

def _post_discord(payload, what, url=None):
    try:
        r = requests.post(url or DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code in (200, 204):
            return True
        log.warning(f"Discord {what} {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"Discord {what} failed: {e}")
    return False


def send_startup_ping():
    _post_discord(
        {"content": (
            "✅ **Chipotle monitor (Twitter engine) live.**\n"
            f"🔎 Watching X for `{CHIPOTLE_SHORTCODE}` every {POLL_INTERVAL}s "
            "via twitterapi.io."
        )},
        "startup",
    )


def send_heartbeat():
    _post_discord(
        {"content": (
            f"💓 Monitor alive — {len(seen_codes)} codes seen so far. "
            f"Last check {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC."
        )},
        "heartbeat",
        url=HEARTBEAT_WEBHOOK,
    )


# Human-readable hints for the codes we treat as "monitoring is down".
_API_ERROR_HINTS = {
    402: "out of credits — top up at twitterapi.io/payment",
    401: "API key rejected (401) — check TWITTERAPI_KEY",
    403: "API key forbidden (403) — check TWITTERAPI_KEY",
    429: "rate limited (429) — polling too fast or plan limit",
}


def note_api_error(code, detail=""):
    """Record a failed search; after a streak, fire ONE distinct Discord warning
    so a dry balance / bad key can't silently stop monitoring."""
    global api_error_streak, api_warning_active
    api_error_streak += 1
    if api_error_streak >= API_ERROR_THRESHOLD and not api_warning_active:
        api_warning_active = True
        hint = _API_ERROR_HINTS.get(code, f"search failing ({code})")
        _post_discord(
            {"content": (
                f"⚠️ **Chipotle monitor: Twitter searches are failing** — {hint}.\n"
                f"No codes will be caught until this is fixed. "
                f"({api_error_streak} consecutive failures)"
            )},
            "api-warning",
        )
        log.error(f"API DOWN warning sent: {hint} | {detail}")


def note_api_ok():
    """A search succeeded — clear the alarm and tell Discord we've recovered."""
    global api_error_streak, api_warning_active
    if api_warning_active:
        _post_discord(
            {"content": "✅ **Chipotle monitor: Twitter searches recovered.** Back online."},
            "api-recovered",
        )
        log.info("API recovered, monitoring resumed")
    api_error_streak = 0
    api_warning_active = False


def send_discord_alert(code, tweet, source):
    url = tweet_url(tweet)
    if code:
        sms_link = f"sms:{CHIPOTLE_SHORTCODE}&body={code}"
        description = (
            "**CODE DROPPED!** ✅\n"
            f"🌯 [Text {code} to {CHIPOTLE_SHORTCODE}]({sms_link})"
        )
    else:
        description = f"**CODE DROPPED!** ✅\n🌯 [View tweet]({url})"

    payload = {
        "content": "@everyone",
        "embeds": [{
            "description": description,
            "color": 0xA81612,
            "footer": {"text": f"via @{source} • tap link on a phone"},
        }],
    }
    if _post_discord(payload, "alert"):
        log.info(f"✅ alert sent | {code or 'n/a'} via @{source} | {url}")


# ─── POLL LOOP ────────────────────────────────────────────────────────────────

def process_tweets(tweets, alert=True):
    """Scan a batch of tweets; alert + log on each genuinely new code.
    Returns the number of new codes handled."""
    hits = 0
    # oldest-first so alerts fire in the order codes were actually posted
    for tweet in reversed(tweets):
        tid = tweet.get("id")
        text = tweet.get("text") or ""
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)
        if not has_shortcode(text):
            continue

        code = extract_keyword(text)
        source = (tweet.get("author") or {}).get("userName") or "?"

        if not code:
            # shortcode present but no parseable keyword — likely an image/video
            # code (the OCR case). Log it so we can see what we're missing.
            log.info(f"  ⚠ shortcode w/o parseable code @{source}: {text[:80]!r}")
            continue
        if code in seen_codes:
            continue

        seen_codes.add(code)
        hits += 1
        if alert:
            log.info(f"  🎯 HIT {code} via @{source}")
            log_code(code, tweet, source)
            send_discord_alert(code, tweet, source)
    return hits


def current_interval():
    """Seconds to wait before the next poll: FAST (POLL_INTERVAL) inside a known
    drop window — Thu-Sun afternoons ET (golf) or a manual EVENT_WINDOW — else
    SLOW (POLL_SLOW). FAIL-OPEN: scheduling off, missing tz data, or any error
    returns FAST, so a bad schedule degrades to 'always fast' (the old behavior),
    never to 'blind'."""
    if not SCHEDULE_ENABLED or not _HAVE_ZONEINFO:
        return POLL_INTERVAL
    try:
        now = datetime.now(ZoneInfo(SCHEDULE_TZ))
        today = now.date().isoformat()
        for start, end in EVENT_WINDOWS:
            if start <= today <= end:
                return POLL_INTERVAL
        if now.weekday() in FAST_DAYS and FAST_START_HOUR <= now.hour < FAST_END_HOUR:
            return POLL_INTERVAL
        return POLL_SLOW
    except Exception as e:
        log.warning(f"schedule check failed, defaulting to fast poll: {e}")
        return POLL_INTERVAL


def poll_cycle(lookback):
    # lookback covers the full gap since the last poll (interval + overlap) so a
    # slow window never leaves a hole between polls.
    since = int(time.time()) - lookback
    tweets, _, _ = search_tweets(since)
    hits = process_tweets(tweets, alert=True)
    if hits:
        log.info(f"── cycle: {hits} new code(s), {len(seen_codes)} total ──")


def load_seen_from_log():
    """Pre-load codes we've already alerted on (from the log) so a restart never
    re-announces them."""
    try:
        with open(CODE_LOG_FILE) as f:
            for line in f:
                try:
                    code = (json.loads(line).get("code") or "").upper()
                    if code:
                        seen_codes.add(code)
                except ValueError:
                    continue
    except FileNotFoundError:
        return
    if seen_codes:
        log.info(f"Loaded {len(seen_codes)} previously-alerted code(s) from log.")


def prime():
    """Mark codes already circulating as seen WITHOUT alerting, so we don't
    re-announce old codes (e.g. a code from yesterday someone just reposted)."""
    log.info(f"Priming (no alerts) over last {PRIME_LOOKBACK_HOURS:.0f}h...")
    since = int(time.time()) - int(PRIME_LOOKBACK_HOURS * 3600)
    primed, cursor = 0, ""
    for _ in range(PRIME_MAX_PAGES):
        tweets, cursor, has_next = search_tweets(since, cursor)
        if not tweets:
            break
        primed += process_tweets(tweets, alert=False)
        if not has_next or not cursor:
            break
    log.info(f"Primed {primed} existing code(s).")


def main():
    global _last_api_call
    missing = [n for n, v in (("DISCORD_WEBHOOK", DISCORD_WEBHOOK),
                              ("TWITTERAPI_KEY", TWITTERAPI_KEY)) if not v]
    if missing:
        log.error(f"Missing required env var(s): {', '.join(missing)}. Exiting.")
        sys.exit(1)

    # Pretend we just made a call so the FIRST request waits out the account-wide
    # QPS limit — prevents a 429 when a quick restart lands <5s after the previous
    # process's last call.
    _last_api_call = time.time()

    log.info("🌯 Chipotle monitor (twitterapi.io) starting...")
    log.info(f"  query={SEARCH_QUERY!r} interval={POLL_INTERVAL}s heartbeat={HEARTBEAT_HOURS}h")
    if SCHEDULE_ENABLED and _HAVE_ZONEINFO:
        log.info(f"  schedule-aware: fast={POLL_INTERVAL}s in-window, slow={POLL_SLOW}s "
                 f"off-window (Thu-Sun {FAST_START_HOUR}:00-{FAST_END_HOUR}:00 {SCHEDULE_TZ}"
                 f"{' + ' + str(len(EVENT_WINDOWS)) + ' event window(s)' if EVENT_WINDOWS else ''})")
    elif SCHEDULE_ENABLED and not _HAVE_ZONEINFO:
        log.warning("  schedule-aware requested but zoneinfo unavailable -> flat fast poll")

    send_startup_ping()
    load_seen_from_log()
    prime()

    last_heartbeat = time.time()
    while True:
        interval = current_interval()
        try:
            poll_cycle(interval + OVERLAP_SECONDS)
        except Exception as e:
            log.error(f"poll cycle error: {e}")

        if HEARTBEAT_HOURS > 0 and time.time() - last_heartbeat >= HEARTBEAT_HOURS * 3600:
            send_heartbeat()
            last_heartbeat = time.time()

        time.sleep(interval)


if __name__ == "__main__":
    main()
