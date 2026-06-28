# ERRORS.md — failure log

When something takes **>2 attempts**, log: *what failed / what worked / note for next time*. Check this before trying a similar approach.

---

### twitter-cli (agent-reach backend) is throttled/broken
- **Failed:** local `twitter-cli` polling — logs `Failed to init ClientTransaction`, `search` 404s, `user-posts` hangs/times out; rate-limits under load.
- **Worked:** switched the whole Twitter engine to **twitterapi.io** (HTTP + `x-api-key`).
- **Note:** twitter-cli is fine for one-off lookups, not production monitoring.

### twitterapi.io 429 (free tier 1 req/5s)
- **Failed:** rapid polling / a quick restart firing a call <5s after the previous process → `429 Too Many Requests`.
- **Worked:** in-process **rate limiter** (`MIN_CALL_SPACING=5.5`) + set `_last_api_call=time.time()` at startup so the first call waits out the account-wide limit.
- **Note:** the QPS limit is per-API-key (account-wide), not per-process.

### Mac Anaconda python has broken numpy
- **Failed:** `pip install pytesseract` into `/opt/anaconda3` python → `ImportError: numpy._core.multiarray failed to import`.
- **Worked:** clean venv — `python3 -m venv /tmp/ocrenv && /tmp/ocrenv/bin/pip install pytesseract Pillow requests`; run OCR with `/tmp/ocrenv/bin/python`.
- **Note:** `/tmp` venv is wiped on reboot; recreate if missing.

### GCP browser-SSH "Upload file" makes duplicate names
- **Failed:** re-uploading `chipotle_monitor.py` saved it as `chipotle_monitor_(1).py`; `cp ~/chipotle_monitor.py` then copied the OLD file → fix didn't deploy.
- **Worked:** **use git** — `sudo git -C /opt/chipotle-monitor pull`. (If uploading: `rm` old file first, or verify with `grep <marker>` before `cp`.)
- **Note:** prefer git pull over uploads entirely.

### systemd: git "dubious ownership"
- **Failed:** `sudo git -C /opt/chipotle-monitor …` → `fatal: detected dubious ownership` (dir owned by `chipotle`, git run as root).
- **Worked:** `sudo git config --global --add safe.directory /opt/chipotle-monitor`.

### systemd: StartLimitIntervalSec ignored
- **Failed:** `StartLimitIntervalSec`/`StartLimitBurst` under `[Service]` → "Unknown key … ignoring".
- **Worked:** move them to the **`[Unit]`** section.

### .env heredoc paste stalled
- **Failed:** pasting a `sudo tee <<'EOF' … EOF` block "returned nothing" — shell was stuck at the `>` continuation prompt waiting for `EOF`; later lines never ran → service failed `Failed to load environment files`.
- **Worked:** write `.env` line-by-line with `echo '…' | sudo tee -a`.
- **Note:** only paste lines that look like commands; skip prose in instructions.

### OCR misread 8↔S on full frame
- **Failed:** full-frame `image_to_string` read `GLE538` as `GLES38` in many frames.
- **Worked:** crop to the bottom banner, grayscale, 2× upscale, `--psm 11` → 34/34 frames correct. Majority-vote / 2-sighting dedup as backstop.
