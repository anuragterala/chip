# Deploy: Chipotle monitor (Twitter engine) on a free GCP VM

This runs the Twitter half unattended, 24/7, for **$0 compute** using GCP's
Always-Free `e2-micro`. The only cost is twitterapi.io usage (~$1–5/month).

> Scope: this is the Twitter engine only. It catches codes that are **posted as
> text** (golf/@PGATOUR, @usahockey, @ChipotleTweets, and anyone else). On-screen
> Twitch codes need the separate OCR engine — added later.

---

## 0. Get your two secrets first

1. **Discord webhook** — Server Settings → Integrations → Webhooks → New Webhook → Copy URL.
2. **twitterapi.io key** — sign up at https://twitterapi.io (free $1 trial credit),
   Dashboard → API Key. Set a **spend cap** while you're there.

Test locally before deploying:
```bash
pip install -r requirements.txt
DISCORD_WEBHOOK="..." TWITTERAPI_KEY="..." python3 chipotle_monitor.py
```
You should see a startup ping in Discord and `Priming...` in the logs.

---

## 1. Create the Always-Free VM

In Google Cloud Console → Compute Engine → Create instance. **Must** be one of
the free regions or it won't be free:

- **Region:** `us-west1`, `us-central1`, or `us-east1`
- **Machine type:** `e2-micro`  (this exact type is the free one)
- **Boot disk:** Debian 12, 30 GB standard (free tier covers it)
- Leave the rest default; create.

(The $300 trial credit also exists if you want a bigger box — but e2-micro is
free *forever* and plenty for this.)

SSH in from the console (the "SSH" button) or `gcloud compute ssh`.

---

## 2. Install on the VM

```bash
sudo apt update && sudo apt install -y python3-venv git
sudo useradd -r -m -d /opt/chipotle-monitor chipotle || true
sudo mkdir -p /opt/chipotle-monitor

# Copy the project up (from your laptop), e.g.:
#   gcloud compute scp chipotle_monitor.py requirements.txt chipotle-monitor.service VM:/tmp/
# then on the VM:
sudo cp /tmp/chipotle_monitor.py /tmp/requirements.txt /opt/chipotle-monitor/

sudo python3 -m venv /opt/chipotle-monitor/venv
sudo /opt/chipotle-monitor/venv/bin/pip install -r /opt/chipotle-monitor/requirements.txt
```

Create the env file with your secrets:
```bash
sudo tee /opt/chipotle-monitor/.env >/dev/null <<'EOF'
DISCORD_WEBHOOK=https://discord.com/api/webhooks/XXXX/YYYY
TWITTERAPI_KEY=your_twitterapi_io_key
POLL_INTERVAL=6
HEARTBEAT_HOURS=6
EOF
sudo chown -R chipotle:chipotle /opt/chipotle-monitor
sudo chmod 600 /opt/chipotle-monitor/.env
```

---

## 3. Run it as an auto-restarting service

```bash
sudo cp /tmp/chipotle-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chipotle-monitor
```

Verify:
```bash
systemctl status chipotle-monitor          # should say "active (running)"
journalctl -u chipotle-monitor -f          # live logs
```

You should get the startup ping in Discord. Close your laptop — it keeps running.

---

## 4. Reliability built in

- **Auto-restart:** `Restart=always` brings it back after a crash or VM reboot.
- **Heartbeat:** every `HEARTBEAT_HOURS` it posts "💓 Monitor alive" to Discord —
  if those stop, you know something's wrong (set `HEARTBEAT_HOURS=0` to disable).
- **Crash backoff:** won't hot-loop on a bad key (5 restarts/60s then pauses).

## 5. Day-to-day

```bash
journalctl -u chipotle-monitor -f          # watch it work
sudo systemctl restart chipotle-monitor    # after editing .env
cat /opt/chipotle-monitor/codes_log.jsonl  # the ROI / redemption log
```

The `codes_log.jsonl` has one row per caught code (`caught_at`, `code`, `source`,
`url`). After you text a code, edit its `redeemed` field (`true` / `false` /
`"all out"`) — that's your real worth-it scoreboard at month's end.
