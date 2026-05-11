# OpenClaw Timekeeper

A local REST API + web UI that gives clawd:

- Awareness of the current time / date / day / timezone
- Persistent task tracking (start, heartbeat, complete) so long autonomous runs don't lose context
- Scheduled wakeup pings that arrive as Telegram messages, prompting clawd to resume work after a delay
- A small terminal-style web UI for the human to inspect load, tasks, wakeups, settings, and the event log

Built to slot in alongside the `presence_scanner` tool — same REST-API-on-loopback pattern.

```
clawd  --(REST 7779)-->  timekeeper.py daemon  --(Telegram API)-->  user chat
                                                                          |
                                                                          v
                                                              clawd's telegram extension
                                                                  receives & resumes
```

## Quick links
- Setup: [docs/SETUP.md](docs/SETUP.md)
- Daemon: [timekeeper.py](timekeeper.py)
- openclaw tool manifest: [timekeeper_tool.json](timekeeper_tool.json)
- Web UI: [ui/index.html](ui/index.html)

## Local dev

```bash
pip install -r requirements.txt
python timekeeper.py
# open http://127.0.0.1:7779/
```

## Homelab install

```bash
git clone <this repo> ~/openclaw-timekeeper
cd ~/openclaw-timekeeper
bash install.sh
```

---
*Co-authored by Clawd <clawd@qloak.me>
