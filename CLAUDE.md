# CLAUDE.md — working agreement & project context

Read this first, every session. Kept short on purpose: long rule sets decay out of context.

---

## Project context (so you don't start from zero)
- **What this is:** a Chipotle promo-code alert system. It watches for "text `<CODE>` to **888222**" drops and fires a Discord alert instantly, to compete with an existing bot ("Book of Alpha" / Rios·Divine).
- **Two engines, one Discord pipeline:**
  - **Twitter engine** (`chipotle_monitor.py`) — polls **twitterapi.io** for `888222 OR "888-222"`. Catches **text-posted** codes (golf @PGATOUR is the steady weekly source). Runs **24/7 on a GCP e2-micro** via systemd, git-backed at `/opt/chipotle-monitor`.
  - **OCR engine** (`evo_ocr_monitor.py`) — streamlink→ffmpeg→tesseract on a live Twitch stream. Catches **on-screen** codes (FGC majors like Evo). **Event-driven**, run locally during events.
  - Pending: a **supervisor + `events.json`** calendar that auto-runs OCR during known events.
- **About Anurag:** directs the work well, but **newer to terminal / devops / cloud**. → Give **exact copy-paste commands**, clearly separate **browser-GUI steps from terminal steps**, say whether a command runs on the **VM** vs **his Mac**, and don't assume infra knowledge.

## Stack — use these, don't propose alternatives unless asked
- **Python 3**, stdlib + `requests`; `pytesseract`/`Pillow` for OCR
- **twitterapi.io** for Twitter data (NOT the official X API — no streaming for new customers)
- **streamlink + ffmpeg + tesseract** for OCR
- **GCP Always-Free e2-micro** + **systemd** for hosting; **git** repo `github.com/anuragterala/chip`
- **Discord webhooks** for alerts

## Permanent facts (always true — flag if a task conflicts)
- **Secrets live in `.env` (gitignored). NEVER commit secrets.** `.env` exists only on the VM.
- twitterapi.io free tier = **1 req/5s**, bills ~**per call** (~16 credits/call). `POLL_INTERVAL` drives cost (~$30/mo at 12s).
- **Code updates:** edit locally → `git push` → on VM `sudo git -C /opt/chipotle-monitor pull && sudo systemctl restart chipotle-monitor`. **`.env`/config changes are VM-only** (not git).
- This `MEMORY.md`/`ERRORS.md` are **project files** — separate from Claude's own `~/.claude` memory.

---

## How to work
1. **Ask, don't assume.** Unclear intent/architecture/requirements → ask before writing code.
2. **Simplest thing that works** — no unrequested abstractions. Before a non-trivial approach, state in 1–2 lines what it makes **harder** later.
3. **Stay in scope.** Only touch code for the current task. Spot a worthwhile refactor? **Flag it in a closing note — don't silently do it, don't silently leave debt.**
4. **Flag uncertainty / unknown facts explicitly** before relying on them. Never fill a knowledge gap with plausible-sounding info.
5. **Be a thinking partner.** See a clearly better path, or a request that deviates from settled practice? Say so in 2–4 bullets, then proceed — unless it avoids serious risk/wasted work, then wait. Don't bikeshed style.

## Three modes — pick one explicitly
- **Execute** exactly (default for clear, low-risk tasks)
- **Flag, then wait** (clearly better path exists)
- **Stop** (requested path risks something hard to undo)

## Confirm before irreversible / outward-facing actions
Require an explicit "yes" **in the current message** before: deploying/pushing, DB or schema changes, deleting/overwriting files, or sending/posting anything external (Discord/email/etc.). "You said so earlier" ≠ confirmation.

## Finish every task with
**Files changed** (one line each) · **Intentionally not touched** · **What I did NOT do** (skipped edge cases / untested paths) · **Follow-up needed.**

## Style
No filler openers ("Great question!"). Match length to the task. Lead with the answer.

---

## Memory protocol
- **`MEMORY.md`** — decision log. After a significant decision, append: *what was decided / why / what was rejected*. Read it at session start; don't contradict a logged decision without flagging.
- On "session end" / "wrapping up": append a summary (worked on / done / in progress / next priorities).
- **`ERRORS.md`** — when something takes **>2 attempts**, log: *what failed / what worked / note for next time*. Check it before trying a similar approach.

*Adapted from Andrej Karpathy's 4 CLAUDE.md clauses + the r/ClaudeAI / @0xDepressionn framework, curated for this project.*
