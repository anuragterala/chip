# MEMORY.md — decision log

Append after any significant decision: **what / why / what was rejected**. Read at session start; don't contradict a logged decision without flagging. (Project file — separate from Claude's own memory.)

---

### Architecture: two engines, one Discord pipeline
- **Decided:** Twitter engine (text codes) + OCR engine (on-screen stream codes), both feeding the same Discord alert + dedup.
- **Why:** backtest of the competitor's 3-month history showed codes split ~50/50 — golf/sports are text-posted; FGC/esports codes are flashed on-screen only. Neither source type alone covers both.
- **Rejected:** Twitter-only (misses on-screen codes like GLE538); OCR-only (misses text codes).

### Twitter data: twitterapi.io, not official X API
- **Decided:** use twitterapi.io.
- **Why:** new customers can't get the official streaming tier; pay-per-use excludes streaming and is ~33× pricier. twitterapi.io ~$0.00015/call, no minimum.
- **Rejected:** official X API (no streaming for new accounts, ~$50–5k/mo); self-host scrapers (twscrape/nitter — fragile, account bans).

### Monitor the source/wide net, not deal reposters
- **Decided:** wide query `888222 OR "888-222"` (+ partner accounts), not the 16 deal-repost accounts.
- **Why:** deal accounts lag the original source ~40s; the wide net catches whoever posts first, including unknown new sources. Must match both `888222` and `888-222` (partners use the hyphen).
- **Open gap:** bare-code posts (e.g. @EsseDeals posts just `GLE538` with no shortcode) slip the anchor — would need `from:account` following.

### Cost vs latency: POLL_INTERVAL=12
- **Decided:** poll every 12s (~$30/mo, ~14s latency).
- **Why:** twitterapi.io bills ~per call (~16 credits), so cost scales with poll frequency, not tweets. 6s ≈ $53/mo; 12s ≈ $30/mo and still beats deal accounts. Tune via redemption data.

### Hosting: Twitter on GCP always-free; OCR local/event-driven
- **Decided:** Twitter engine 24/7 on GCP Always-Free e2-micro (systemd, git-backed). OCR run locally during events (too heavy for e2-micro; only needed a few weekends/quarter).
- **Why:** Twitter workload is featherlight + must be always-on; OCR is bursty + CPU/bandwidth heavy.

### Sources backtest → monitoring targets
- **Golf / @PGATOUR "Hot Streak":** steady, near-weekly, **text-posted** → handled by Twitter engine, zero effort.
- **FGC majors (Evo confirmed; CEO/GOML/BITE candidates):** **on-screen** → OCR + calendar. Scheduled publicly, so knowable in advance.
- **Creator/vanity codes:** sporadic, not predictable → Twitter wide-net backstop.

### OCR tuning
- **Decided:** OCR the cropped bottom banner (upscaled, `--psm 11`), full-frame as fallback.
- **Why:** full-frame misread 8↔S; banner crop read GLE538 34/34 frames, 0 errors. Fallback keeps it general for non-Evo layouts.
