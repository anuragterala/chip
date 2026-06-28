#!/usr/bin/env python3
"""
Twitch on-screen code OCR catcher (Evo 2026 and any Chipotle-sponsored stream).

Pulls a live Twitch stream, grabs a frame every few seconds, OCRs it, and when it
sees "TEXT <CODE> TO 888222" on screen it fires the same Discord alert as the
Twitter engine. This catches the on-screen-only codes (e.g. GLE538 from Evo) that
never get text-posted and so are invisible to the Twitter monitor.

System deps (macOS):  brew install streamlink ffmpeg tesseract
Python deps:          pip install pytesseract Pillow requests

Env:
  DISCORD_WEBHOOK  (required)  Discord webhook URL
  TWITCH_CHANNEL   (default 'evo')  channel to watch, e.g. evo, evo2, chipotle
  OCR_INTERVAL     (default 2)  seconds between frames/OCR
  STREAM_QUALITY   (default '720p,720p60,best')
  CODE_LOG_FILE    (default ocr_codes_log.jsonl)
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

try:
    import pytesseract
    from PIL import Image
except ImportError:
    sys.exit("Missing Python deps. Run: pip install pytesseract Pillow requests")

# ─── CONFIG ─────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
TWITCH_CHANNEL  = os.environ.get("TWITCH_CHANNEL", "evo").strip()
OCR_INTERVAL    = float(os.environ.get("OCR_INTERVAL", "2"))
STREAM_QUALITY  = os.environ.get("STREAM_QUALITY", "720p,720p60,best")
# The Chipotle giveaway code sits in a fixed bottom banner. OCR-ing only that
# strip (upscaled) reads the code with 100% accuracy in testing vs ~noisy
# full-frame OCR (8<->S confusion). Tune if a stream puts the banner elsewhere.
BANNER_TOP_FRAC = float(os.environ.get("BANNER_TOP_FRAC", "0.82"))
CODE_LOG_FILE   = os.environ.get("CODE_LOG_FILE", "ocr_codes_log.jsonl")
FRAME_FILE      = os.environ.get("FRAME_FILE", "/tmp/twitch_ocr_frame.jpg")
SHORTCODE       = "888222"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ocr_monitor")

# Same anchored patterns as the Twitter engine: a code token right before "to 888222".
KEYWORD_RE   = re.compile(r"([A-Z0-9]{4,16})\s+to\s+888[-\s]?222", re.IGNORECASE)
SHORTCODE_RE = re.compile(r"888[-\s]?222")

seen    = set()   # codes already alerted
pending = {}      # code -> times seen; require 2 to beat one-frame OCR noise

# ─── DISCORD ────────────────────────────────────────────────────────────────
def alert(code):
    sms = f"sms:{SHORTCODE}&body={code}"
    payload = {
        "content": "@everyone",
        "embeds": [{
            "description": f"**CODE DROPPED!** ✅ _(on-screen)_\n🌯 [Text {code} to {SHORTCODE}]({sms})",
            "color": 0xA81612,
            "footer": {"text": f"OCR • twitch.tv/{TWITCH_CHANNEL}"},
        }],
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        log.info(f"✅ alert sent {code} (discord {r.status_code})")
    except Exception as e:
        log.error(f"discord failed: {e}")
    try:
        with open(CODE_LOG_FILE, "a") as f:
            f.write(json.dumps({
                "caught_at": datetime.now(timezone.utc).isoformat(),
                "code": code, "source": f"twitch:{TWITCH_CHANNEL}", "redeemed": None,
            }) + "\n")
    except Exception as e:
        log.warning(f"log write failed: {e}")

# ─── STREAM ─────────────────────────────────────────────────────────────────
def start_stream():
    """streamlink pulls the live stream; ffmpeg overwrites FRAME_FILE with the
    newest frame every OCR_INTERVAL seconds."""
    sl = subprocess.Popen(
        ["streamlink", "--stdout",
         f"twitch.tv/{TWITCH_CHANNEL}", STREAM_QUALITY],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
         "-vf", f"fps=1/{OCR_INTERVAL}", "-update", "1", "-y", FRAME_FILE],
        stdin=sl.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sl, ff

def ocr_banner(path):
    """OCR just the bottom giveaway banner (cropped + upscaled). This is what
    made reads exact in testing: 34/34 frames -> correct code, 0 misreads."""
    im = Image.open(path)
    w, h = im.size
    crop = (im.crop((0, int(h * BANNER_TOP_FRAC), w, h))
              .convert("L")
              .resize((w * 2, int(h * (1 - BANNER_TOP_FRAC)) * 2)))
    return pytesseract.image_to_string(crop, config="--psm 11")

def extract_codes(text):
    return {m.group(1).upper() for m in KEYWORD_RE.finditer(text.upper())}

# ─── MAIN ───────────────────────────────────────────────────────────────────
def main():
    if not DISCORD_WEBHOOK:
        sys.exit("DISCORD_WEBHOOK env var is required.")
    log.info(f"🎥 OCR on twitch.tv/{TWITCH_CHANNEL} | frame every {OCR_INTERVAL}s | anchor '{SHORTCODE}'")

    sl, ff = start_stream()
    log.info("Buffering stream (~12s)...")
    time.sleep(12)

    last_seen_log = time.time()
    while True:
        try:
            if sl.poll() is not None or ff.poll() is not None:
                log.warning("stream/ffmpeg exited — restarting (is the channel live?)")
                try: sl.kill(); ff.kill()
                except Exception: pass
                time.sleep(5)
                sl, ff = start_stream(); time.sleep(12); continue

            if not os.path.exists(FRAME_FILE):
                time.sleep(OCR_INTERVAL); continue

            text = ocr_banner(FRAME_FILE)

            if SHORTCODE_RE.search(text):
                for code in extract_codes(text):
                    if code in seen:
                        continue
                    pending[code] = pending.get(code, 0) + 1
                    if pending[code] >= 2:        # stability check vs OCR noise
                        seen.add(code); pending.pop(code, None)
                        log.info(f"🎯 OCR HIT {code}")
                        alert(code)

            # heartbeat so you know it's alive while nothing's dropping
            if time.time() - last_seen_log > 120:
                log.info(f"…watching (alerted {len(seen)} so far)")
                last_seen_log = time.time()

        except Exception as e:
            log.error(f"loop error: {e}")
        time.sleep(OCR_INTERVAL)

if __name__ == "__main__":
    main()
