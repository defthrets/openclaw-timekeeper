#!/usr/bin/env bash
# OpenClaw Timekeeper installer (Linux / homelab)
set -euo pipefail

TARGET="$HOME/.openclaw/timekeeper"
SERVICE_NAME="openclaw-timekeeper"
SERVICE_FILE="$SERVICE_NAME.service"

echo "[1/5] Creating $TARGET"
mkdir -p "$TARGET"

echo "[2/5] Copying daemon + UI"
cp timekeeper.py "$TARGET/"
rm -rf "$TARGET/ui"
cp -r ui "$TARGET/ui"

echo "[3/5] Installing Python deps (user scope)"
pip3 install --user -r requirements.txt

echo "[4/5] Installing systemd unit"
USER_NAME="$(whoami)"
sed "s/^User=.*/User=$USER_NAME/" "$SERVICE_FILE" \
  | sed "s|^WorkingDirectory=.*|WorkingDirectory=$TARGET|" \
  | sed "s|^ExecStart=.*|ExecStart=/usr/bin/python3 $TARGET/timekeeper.py|" \
  | sudo tee "/etc/systemd/system/$SERVICE_FILE" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "[5/5] Verifying"
sleep 2
sudo systemctl status "$SERVICE_NAME" --no-pager || true
echo
echo "Status check:"
curl -s http://127.0.0.1:7779/api/status || echo "(daemon not responding yet)"
echo
echo
echo "Done. Next steps:"
echo "  1. Edit $TARGET/config.json — add telegram_bot_token + telegram_chat_id"
echo "  2. sudo systemctl restart $SERVICE_NAME"
echo "  3. Open http://127.0.0.1:7779/ in a browser to use the web UI"
echo "  4. Drop timekeeper_tool.json wherever your openclaw tool manifests live"
echo "  5. Restart clawd so he picks up the new tool"
