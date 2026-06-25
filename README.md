# 🌯 Chipotle Promo Monitor

Polls a fixed list of Twitter/X accounts every `POLL_INTERVAL` seconds using
[`twitter-cli`](https://pypi.org/project/twitter-cli/) (cookie auth). When any
monitored account posts a tweet containing `888222`, it fires a Discord webhook
alert with a one-tap SMS deep link to claim the code.

Twitter polling only — no Reddit, no website scraping, no streaming API.

## How auth works (important)

`twitter-cli` authenticates with your X session cookies. It reads them from the
environment variables **`TWITTER_AUTH_TOKEN`** and **`TWITTER_CT0`** — no browser
needed, so it runs fine in a headless container.

Get your cookie values locally (after running `agent-reach configure
--from-browser chrome`):

```bash
cat ~/.agent-reach/config.yaml
# twitter_auth_token: <-- this is TWITTER_AUTH_TOKEN
# twitter_ct0:        <-- this is TWITTER_CT0
```

> ⚠️ These are live session credentials. Never commit them. Set them as Railway
> variables only. If X invalidates the session (e.g. it dislikes the datacenter
> IP), re-run `agent-reach configure --from-browser chrome` locally and update
> the Railway variables.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DISCORD_WEBHOOK` | ✅ | — | Discord webhook URL |
| `TWITTER_AUTH_TOKEN` | ✅ | — | X `auth_token` cookie |
| `TWITTER_CT0` | ✅ | — | X `ct0` cookie |
| `POLL_INTERVAL` | — | `30` | Seconds between full poll cycles |

## Deploy to Railway (24/7)

1. Push this repo to GitHub.
2. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select this repo.
3. Service → **Variables** tab → add the four variables above.
4. Railway installs `requirements.txt` (which includes `twitter-cli`) and runs
   `python chipotle_monitor.py` per `railway.json` / `Procfile`. It restarts on
   failure automatically.

## Run locally

```bash
export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."
export TWITTER_AUTH_TOKEN="..."   # or rely on local agent-reach/keychain auth
export TWITTER_CT0="..."
export POLL_INTERVAL=30           # optional
python chipotle_monitor.py
```

## Monitored accounts

usahockey, LordOfDiscounts, LordOfSavings, Pricerrors, Sneaky_Steals,
thedealsguy_, Info4Days, GlitchedDeals, Wario64, Dexerto, ChipotleTweets,
OldSchoolRS, ShockedDeals, HoomanDeals, GlitchDealGroup, Misprints

## Discord alert includes

- The account that posted it
- The full tweet text
- A direct link to the tweet
- A one-tap `sms:888222?&body=<KEYWORD>` link (keyword parsed from
  `text <KEYWORD> to 888222`)

On startup it sends a ping listing all monitored accounts, and primes the
already-seen `888222` tweets so you only get alerts for genuinely new drops.
