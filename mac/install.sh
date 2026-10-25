#!/bin/bash
# Kullanım: bash mac/install.sh <TELEGRAM_BOT_TOKEN> <CHAT_ID>
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$1" "$2" > "$HOME/.ev-bot.env"
chmod 600 "$HOME/.ev-bot.env"
python3 -m venv "$HOME/.ev-bot-venv"
"$HOME/.ev-bot-venv/bin/pip" install -q -r "$DIR/requirements.txt" playwright
"$HOME/.ev-bot-venv/bin/python" -m playwright install chromium
chmod +x "$DIR/mac/run.sh"
PL="$HOME/Library/LaunchAgents/com.huseyin.evbot.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PL" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.huseyin.evbot</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/mac/run.sh</string></array>
  <key>StartInterval</key><integer>1200</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/.ev-bot.log</string>
  <key>StandardErrorPath</key><string>$HOME/.ev-bot.log</string>
</dict></plist>
PLIST
launchctl unload "$PL" 2>/dev/null || true
launchctl load "$PL"
echo "Kuruldu. Kayıt: ~/.ev-bot.log"
