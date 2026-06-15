# 🌯 Chipotle Promo Monitor

Monitors Reddit, Twitter/X, and Chipotle.com for promo drops and sends a Discord alert with a one-tap SMS deep link to claim.

## Setup

### 1. Add your Discord Webhook
Open `chipotle_monitor.py` and replace the `DISCORD_WEBHOOK` value at the top:
```python
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/YOUR_NEW_WEBHOOK_URL"
```

### 2. Deploy to Railway (free, 24/7)

1. Push this folder to a GitHub repo (can be private)
2. Go to [railway.app](https://railway.app) → sign in with GitHub
3. Click **New Project** → **Deploy from GitHub repo**
4. Select your repo → Railway auto-detects Python and deploys
5. Go to your service → **Variables** tab → add:
   - `DISCORD_WEBHOOK` = your webhook URL (more secure than hardcoding)
6. That's it — it runs forever

### 3. Optional: Use environment variable instead of hardcoding

In `chipotle_monitor.py`, replace:
```python
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/..."
```
with:
```python
import os
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
```
Then set it in Railway's Variables tab. Keeps your webhook out of GitHub.

## What it monitors
- `r/chipotle`, `r/deals`, `r/freebies`, `r/frugal` — new posts every 30s
- `@ChipotleTweets` via Nitter RSS — no API key needed
- `chipotle.com` and `chipotle.com/promos` — detects page changes

## Discord alert includes
- Source (Reddit/Twitter/Website)
- Promo snippet
- **One-tap SMS link** → opens Messages with keyword pre-filled to 888222
