# OpenClaw Timekeeper - Setup

## What it does
- `get_time` for clawd whenever he needs to know the current time
- Persistent task tracker so long autonomous runs don't lose context
- Wakeup pings with three delivery modes: `telegram`, `openclaw_run` (spawn fresh clawd session directly), `webhook`, or `all` — see [Wakeup delivery modes](#wakeup-delivery-modes)
- Local web UI to inspect tasks, wakeups, settings, event log

## Local development (Windows / Linux / macOS)

```bash
pip install -r requirements.txt
python timekeeper.py
```

Open `http://127.0.0.1:7779/` for the UI. API at `http://127.0.0.1:7779/api/*`.

The first run creates `~/.openclaw/timekeeper/config.json` with defaults.

## Homelab install (Linux + systemd)

```bash
git clone <this repo url> ~/openclaw-timekeeper
cd ~/openclaw-timekeeper
bash install.sh
```

The installer:
1. Copies `timekeeper.py` and `ui/` into `~/.openclaw/timekeeper/`
2. Installs Python deps (user scope)
3. Patches the systemd unit with the current user + paths
4. Enables + starts `openclaw-timekeeper.service`
5. Hits the status endpoint to sanity-check

## Configure Telegram

Edit `~/.openclaw/timekeeper/config.json` (or use the SETTINGS tab in the UI):

```json
{
  "telegram_bot_token": "123456:ABC...",
  "telegram_chat_id": "987654321"
}
```

You can use the **same bot** clawd's openclaw telegram extension uses, or a separate "alarm clock" bot - either works as long as the bot can post into the chat clawd lives in.

To find your `chat_id`: send any message to the bot, then:
```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
# look for message.chat.id
```

After editing config: `sudo systemctl restart openclaw-timekeeper`.

Without telegram configured, wakeups still queue and fire on schedule - they just don't push a notification (you'd have to poll `/api/wakeups` to know).

## Wakeup delivery modes

Set `wakeup_mode` in `config.json` (or SETTINGS tab) to pick how fired wakeups reach clawd:

| Mode | What happens | When to use |
|---|---|---|
| `telegram` (default) | Sends a Telegram message to the configured chat. Clawd's telegram extension picks it up as an incoming message. | You already have clawd's telegram extension running and trust the round-trip. |
| `openclaw_run` | Spawns `openclaw run "<message>"` locally as a detached subprocess. Invokes a fresh clawd session directly on the homelab. | Most reliable — bypasses Telegram entirely. Matches how `presence_scanner` triggers clawd via cron. Recommended for unattended autonomous runs. |
| `webhook` | POSTs a JSON payload (`wakeup_id`, `message`, `task_id`, `text`, ...) to `wakeup_webhook_url`. | You have a custom HTTP endpoint that should handle wakeups (e.g. a queue, Home Assistant, n8n). |
| `all` | Fires all three in sequence. | Maximum redundancy — use if you want Telegram as a visible audit trail *and* `openclaw run` as the guaranteed trigger. |

Example config for the recommended unattended setup:

```json
{
  "wakeup_mode": "openclaw_run",
  "openclaw_binary": "openclaw"
}
```

If `openclaw` isn't on PATH for the systemd service, set `openclaw_binary` to the absolute path (e.g. `/usr/local/bin/openclaw` or `/home/michael/.npm-global/bin/openclaw`).

## Register the tool with openclaw

Drop `timekeeper_tool.json` into the same folder where your other openclaw tool manifests live (next to where `presence_scanner` is registered). Restart clawd.

## Sanity test

In Telegram, ask clawd:
> "Use timekeeper. What time is it? Then start a task called 'demo' and schedule a wakeup in 30 seconds with the message 'demo wakeup test'."

You should see:
1. Clawd calls `get_time`, replies with the time
2. Clawd calls `start_task` and `schedule_wakeup`
3. ~30 seconds later, your Telegram chat receives a message starting with `[TIMEKEEPER WAKEUP]`
4. Clawd's telegram extension delivers the message to him; he responds

## Long autonomous run pattern

```
User:  "Work on cleaning up the codebase for the next 2 hours, check in every 15 min."

Clawd: start_task(name="codebase cleanup", ttl_seconds=7800)
   ->  id=ab12cd34
       schedule_wakeup(in_seconds=900,
                       message="Resume cleanup, do next pass",
                       task_id="ab12cd34")
       [does work, idles]

(15m) Telegram: "[TIMEKEEPER WAKEUP] Resume cleanup, do next pass"
       Clawd resumes:
       heartbeat(id="ab12cd34", progress_note="cleaned auth module")
       schedule_wakeup(in_seconds=900, ...)

(... continues for 2h, then ...)

       complete_task(id="ab12cd34", result="cleaned auth, models, routes")
```

## Storage layout (on the homelab)

```
~/.openclaw/timekeeper/
|-- timekeeper.py
|-- ui/
|   |-- index.html
|   |-- app.js
|   `-- styles.css
|-- config.json
|-- db/
|   |-- tasks.json       active + completed
|   |-- wakeups.json     pending + fired
|   `-- history.json     rolling event log
`-- log/
    `-- daemon.log
```

## API reference

```
GET    /api/status
GET    /api/time
GET    /api/config
PUT    /api/config

POST   /api/tasks
GET    /api/tasks?status=active|completed|all
GET    /api/tasks/{id}
POST   /api/tasks/{id}/heartbeat
POST   /api/tasks/{id}/complete
DELETE /api/tasks/{id}

POST   /api/wakeups
GET    /api/wakeups?include_fired=false
DELETE /api/wakeups/{id}

GET    /api/history?limit=100
```

## Troubleshooting

```bash
# Daemon logs
sudo journalctl -u openclaw-timekeeper -f
tail -f ~/.openclaw/timekeeper/log/daemon.log

# Inspect raw state
cat ~/.openclaw/timekeeper/db/wakeups.json | python3 -m json.tool
cat ~/.openclaw/timekeeper/db/tasks.json | python3 -m json.tool

# Manual wakeup test (no clawd needed)
curl -X POST http://127.0.0.1:7779/api/wakeups \
  -H 'Content-Type: application/json' \
  -d '{"in_seconds": 5, "message": "manual test"}'

# If wakeup doesn't deliver to telegram:
# - check /api/status shows "telegram_configured": true
# - check daemon.log for "telegram send failed: ..."

# If openclaw_run mode fails:
# - check daemon.log for "openclaw binary not found" or spawn errors
# - verify the systemd unit PATH includes wherever `openclaw` lives
#   (add Environment="PATH=/usr/local/bin:/usr/bin:/home/michael/.npm-global/bin")
#   or set "openclaw_binary" to an absolute path in config.json

# Inspect per-wakeup delivery results (since v1.1, wakeups record which
# channels reported success):
cat ~/.openclaw/timekeeper/db/wakeups.json | python3 -m json.tool
# look at wakeup.send_result.{telegram|openclaw_run|webhook}.sent
```
