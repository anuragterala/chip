#!/usr/bin/env python3
"""
One-time backtest — reconstruct Chipotle 888222 code-drop history from the SOURCE
accounts via twitterapi.io advanced_search.

Why source-only (not the whole 888222 firehose):
  Restricting to the partner accounts that ORIGINATE drops (vs the thousands of
  reposts/replies) makes this ~pennies and minutes instead of dollars and hours,
  and gives clean data: one row per real drop instead of 50 reposts of each.

Output:
  A dated CSV (date, source, code, event_guess, url, text) — one row per unique
  code, earliest sighting kept (= when the drop actually broke).

Cost & safety:
  Bills ~$0.00015 per tweet RETURNED. A hard MAX_TWEETS budget cap stops the run
  before any surprise spend. It prints an estimated cost at the end.

⚠️  Run this with the monitor STOPPED — twitterapi.io's QPS limit is per-API-key
    (account-wide), so a running monitor + this script will throttle each other.
    On the VM:  sudo systemctl stop chipotle-monitor
                <run this>
                sudo systemctl start chipotle-monitor

Required env:
  TWITTERAPI_KEY   twitterapi.io API key (x-api-key)   ← lives in the VM's .env

Optional env (sensible defaults):
  BACKTEST_MONTHS  how far back to sweep (default 24)
  MAX_TWEETS       hard budget cap on tweets returned (default 20000 ≈ ~$3)
  MAX_PAGES        hard cap on API requests (default 2000)
  OUT_CSV          output path (default backtest_codes.csv)
  SOURCE_ACCOUNTS  comma-separated handles to override the default source list
"""

import os
import re
import csv
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────

TWITTERAPI_KEY = os.environ.get("TWITTERAPI_KEY", "").strip()

# The confirmed origin accounts for Chipotle text-code drops (golf + hockey + the
# brand itself). Add NHL team handles or new partners here as you confirm them.
DEFAULT_SOURCES = [
    "ChipotleTweets", "PGATOUR", "NHL", "usahockey",
    "DetroitRedWings", "NHLBlackhawks",
]
SOURCE_ACCOUNTS = [
    h.strip().lstrip("@")
    for h in os.environ.get("SOURCE_ACCOUNTS", ",".join(DEFAULT_SOURCES)).split(",")
    if h.strip()
]

BACKTEST_MONTHS = int(os.environ.get("BACKTEST_MONTHS", "24"))
MAX_TWEETS      = int(os.environ.get("MAX_TWEETS", "20000"))   # budget cap
MAX_PAGES       = int(os.environ.get("MAX_PAGES", "2000"))     # request cap
OUT_CSV         = os.environ.get("OUT_CSV", "backtest_codes.csv")

# Free tier = 1 req / 5s, account-wide. Keep margin (matches the monitor).
MIN_CALL_SPACING = float(os.environ.get("MIN_CALL_SPACING", "5.5"))
PRICE_PER_TWEET  = 0.00015   # ~$0.15 / 1,000 tweets returned

TWITTERAPI_BASE = "https://api.twitterapi.io"
SEARCH_URL      = f"{TWITTERAPI_BASE}/twitter/tweet/advanced_search"

# Shortcode written as "888222" and "888-222"; quote the hyphen form so search
# doesn't treat '-' as NOT. Scoped to the source accounts via (from:a OR from:b).
SHORTCODE_OR = '(888222 OR "888-222")'

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backtest")

# ─── EXTRACTION (same rules as the monitor) ─────────────────────────────────────

SHORTCODE_RE = re.compile(r"(?<!\d)888[-\s]?222(?![\d-])")
KEYWORD_RE   = re.compile(
    r"([A-Za-z0-9]{4,16})\s+to\s+888[-\s]?222(?![\d-])", re.IGNORECASE
)


def extract_keyword(text):
    m = KEYWORD_RE.search(text or "")
    return m.group(1).upper() if m else ""


def guess_event(author, text):
    """Best-effort sport/event tag — a hint for eyeballing, not authoritative."""
    a = (author or "").lower()
    t = (text or "").lower()
    if "pgatour" in a or any(k in t for k in ("hot streak", "golf", "tournament", "bogo")):
        return "golf"
    if any(k in a for k in ("nhl", "hockey", "redwings", "blackhawks")) or \
       any(k in t for k in ("hockey", "stanley", "jersey", "puck")):
        return "hockey"
    if any(k in t for k in ("super bowl", "game day", "big game")):
        return "nfl/superbowl"
    if any(k in t for k in ("nba", "finals", "53", "dub", "championship")):
        return "nba"
    return ""


# ─── twitterapi.io ──────────────────────────────────────────────────────────────

_last_api_call = 0.0


def search_page(query, cursor=""):
    """One advanced_search page. Returns (tweets, next_cursor, has_next)."""
    global _last_api_call
    wait = MIN_CALL_SPACING - (time.time() - _last_api_call)
    if wait > 0:
        time.sleep(wait)
    try:
        _last_api_call = time.time()
        r = requests.get(
            SEARCH_URL,
            headers={"X-API-Key": TWITTERAPI_KEY},
            params={"query": query, "queryType": "Latest", "cursor": cursor},
            timeout=20,
        )
    except requests.RequestException as e:
        log.error(f"request failed: {e}")
        return None, "", False
    if r.status_code != 200:
        log.error(f"HTTP {r.status_code}: {r.text[:200]}")
        return None, "", False
    try:
        data = r.json()
    except ValueError:
        log.error("non-JSON response")
        return None, "", False
    return (data.get("tweets", []) or [],
            data.get("next_cursor", "") or "",
            bool(data.get("has_next_page")))


# ─── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    if not TWITTERAPI_KEY:
        log.error("TWITTERAPI_KEY not set (it lives in the VM's .env). Exiting.")
        sys.exit(1)

    now = datetime.now(timezone.utc)
    since_dt = now - timedelta(days=int(BACKTEST_MONTHS * 30.44))
    since_unix = int(since_dt.timestamp())
    until_unix = int(now.timestamp())

    froms = " OR ".join(f"from:{h}" for h in SOURCE_ACCOUNTS)
    query = f'{SHORTCODE_OR} ({froms}) since_time:{since_unix} until_time:{until_unix}'

    log.info(f"Backtest window: {since_dt.date()} → {now.date()} ({BACKTEST_MONTHS} mo)")
    log.info(f"Sources ({len(SOURCE_ACCOUNTS)}): {', '.join(SOURCE_ACCOUNTS)}")
    log.info(f"Caps: MAX_TWEETS={MAX_TWEETS}  MAX_PAGES={MAX_PAGES}")

    codes = {}          # code -> earliest row (dedup)
    total_tweets = 0    # for cost
    pages = 0
    cursor = ""
    capped = None

    while pages < MAX_PAGES:
        tweets, cursor, has_next = search_page(query, cursor)
        if tweets is None:           # hard error already logged
            capped = "api-error"
            break
        pages += 1
        total_tweets += len(tweets)

        for tw in tweets:
            text = tw.get("text") or ""
            if not SHORTCODE_RE.search(text):
                continue
            code = extract_keyword(text)
            if not code:
                continue
            author = (tw.get("author") or {}).get("userName") or "?"
            created = tw.get("createdAt") or tw.get("created_at") or ""
            # keep earliest sighting per code (= when the drop broke)
            prev = codes.get(code)
            if prev is None or (created and created < prev["_sort"]):
                codes[code] = {
                    "date": created,
                    "source": author,
                    "code": code,
                    "event_guess": guess_event(author, text),
                    "url": f"https://x.com/{author}/status/{tw.get('id','')}",
                    "text": text.replace("\n", " ")[:200],
                    "_sort": created or "z",
                }

        log.info(f"page {pages}: +{len(tweets)} tweets, {total_tweets} total, "
                 f"{len(codes)} unique codes")

        if total_tweets >= MAX_TWEETS:
            capped = "budget"
            break
        if not has_next or not cursor:
            break

    if pages >= MAX_PAGES and capped is None:
        capped = "page-cap"

    # ── write CSV (chronological) ──
    rows = sorted(codes.values(), key=lambda r: r["_sort"])
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["date", "source", "code", "event_guess", "url", "text"]
        )
        w.writeheader()
        for r in rows:
            r.pop("_sort", None)
            w.writerow(r)

    # ── summary ──
    est_cost = total_tweets * PRICE_PER_TWEET
    by_src, by_evt = {}, {}
    for r in rows:
        by_src[r["source"]] = by_src.get(r["source"], 0) + 1
        by_evt[r["event_guess"] or "?"] = by_evt.get(r["event_guess"] or "?", 0) + 1

    print("\n" + "=" * 60)
    print(f"BACKTEST DONE — wrote {len(rows)} unique codes to {OUT_CSV}")
    print(f"  tweets scanned : {total_tweets} over {pages} requests")
    print(f"  est. cost      : ${est_cost:.2f}  (~$0.00015/tweet)")
    if rows:
        print(f"  date span      : {rows[0]['date']}  →  {rows[-1]['date']}")
    print(f"  by source      : " +
          ", ".join(f"{k}={v}" for k, v in sorted(by_src.items(), key=lambda x: -x[1])))
    print(f"  by event_guess : " +
          ", ".join(f"{k}={v}" for k, v in sorted(by_evt.items(), key=lambda x: -x[1])))
    if capped == "budget":
        print(f"  ⚠ STOPPED at MAX_TWEETS={MAX_TWEETS} budget cap — window not fully "
              f"covered. Raise MAX_TWEETS or shorten BACKTEST_MONTHS to finish.")
    elif capped == "page-cap":
        print(f"  ⚠ STOPPED at MAX_PAGES={MAX_PAGES} — raise it to finish.")
    elif capped == "api-error":
        print(f"  ⚠ STOPPED on an API error (see log above) — partial results saved.")
    print("=" * 60)


if __name__ == "__main__":
    main()
