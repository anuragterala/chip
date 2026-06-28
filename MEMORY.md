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

### Cost model RESOLVED: twitterapi.io bills ~per-poll, not per-tweet (2026-06-28)
- **Confirmed:** the whole 2-yr code history backtest = **68 tweets → $0.01**, so per-tweet cost is rounding error. The ~$30/mo bill is the **per-request floor (~$0.00015/poll)**. At 12s that's ~216k polls/mo × $0.00015 ≈ $32 — matches reality.
- **Therefore:** cost scales with **poll frequency**, full stop. The old `chipotle_monitor.py` docstring claim "quiet polls ~$0 (per tweet)" was **wrong**; the MEMORY.md "per call" note was right.

### Backtest findings (Sep 2024–Jun 2026, 37 real text codes) (2026-06-28)
- Ran `backtest_codes.py` (source-account sweep via twitterapi.io advanced_search). Findings:
- **Golf @PGATOUR = the steady backbone:** 100% **Thu–Sun afternoons ET**, ~biweekly in PGA season (~Jan–Aug). 16 codes.
- **Hockey @usahockey = rare intense burst:** 21 codes in a 10-day window (Feb 13–22 2026 ≈ Winter Olympics). Event-driven, NOT a steady monthly source — so it out-counts golf only because of one Olympic spike.
- **Real text codes come from PARTNER accounts (PGATOUR, usahockey), not @ChipotleTweets's own feed** (that feed is mostly banter + generic "text the code" announcements where the code is in an image).
- **Headline Super Bowl (Feb) / NBA Finals (Jun) drops are IMAGE/Reel codes → NOT text-catchable by the Twitter engine** (OCR territory). The Twitter engine's real value = golf + occasional event hockey, NOT the famous drops.
- **No other brand runs the catchable mechanic** (Wendy's/Taco Bell/etc.) — confirmed via Twitter + web + Reddit. It's Chipotle-specific. Don't build multi-brand expansion.
- **Coverage caveat:** twitterapi.io search index is **recency-weighted** (~21 months back, sparse before Jan 2026). Treat 2026 cadence as reliable, older as undercounted.

### Decision: digit-filter in extract_keyword (2026-06-28)
- **Decided:** require the extracted code to contain ≥1 digit.
- **Why:** real codes always carry a digit (GLE538, CART60748, PWVER7771); generic "text **the code** to 888222" tweets otherwise mis-extract the filler word (CODE/DROP/THAT/IMAGE) and fire a false `@everyone`. Backtest: every real text code had a digit.
- **Risk/revert:** if Chipotle ever issues a letters-only code this misses it — one-line revert.

### Decision: schedule-aware polling, FAIL-OPEN (2026-06-28)
- **Decided:** FAST (`POLL_INTERVAL`) Thu–Sun 10:00–20:00 ET + manual `EVENT_WINDOWS`; SLOW (`POLL_SLOW`=60s) otherwise. ~$19/mo saved (~60%, $32→~$12) with no loss of in-window speed.
- **Why fail-open:** off-window is *slow, never paused*; any schedule error / missing tzdata → revert to FAST. `since_time` lookback scales with the interval so slow periods never drop tweets. Worst case of a bad schedule = "caught late", never "blind".
- **Rejected:** pause-off-window (silent-failure risk — for a system whose job is being first, missing a code >> saving $5 more).
- **Scope:** Twitter engine only. OCR engine (`evo_ocr_monitor.py`) is fully independent (no shared imports) and untouched.

### Future improvements / backlog (potential follow-ups)
- **Tune in-window `POLL_INTERVAL` down (12→6–8s):** off-window is now cheap, so poll harder during drops (better vs Book of Alpha) and still pay less than today. `.env` change, no code.
- **Add `EVENT_WINDOWS` before known hockey/major tournaments** (Olympics, 4 Nations, World Juniors) so rare hockey bursts get FAST polling instead of the 60s baseline.
- **Apply the digit-filter heuristic to the OCR engine's extraction** — same false-positive surface; real codes carry digits. Parallel improvement, currently out of scope.
- **Bare-code / `from:account` gap** (still open): reposters (e.g. @EsseDeals) post bare codes like `GLE538` with no `888222` anchor → slip the wide query. Could add `from:` follows for known reposters.
- **Image/video headline drops (Super Bowl/NBA) are a Twitter blind spot** — would need OCR on the Reel/broadcast or a manual fast-path during those known windows.
- **Re-run `backtest_codes.py` periodically** (≈pennies) to keep the cadence model current and re-confirm `EVENT_WINDOWS`; widen `SOURCE_ACCOUNTS` as new partners confirm.
- **NHL team accounts** (DetroitRedWings/NHLBlackhawks) appeared in 888222 traffic but yielded 0 parseable text codes — revisit if they start posting redeemable codes.
