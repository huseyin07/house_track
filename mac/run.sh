#!/bin/bash
# Mac'te Sahibinden + Hepsiemlak taraması (launchd her 20 dk çalıştırır)
DIR="$(cd "$(dirname "$0")/.." && pwd)"
set -a; source "$HOME/.ev-bot.env"; set +a
export SITES="sahibinden,hepsiemlak" BROWSER_SITES="sahibinden,hepsiemlak" HEADLESS=1
export STATE_FILE="$HOME/.ev-bot-state.json"
cd "$DIR" && git pull -q 2>/dev/null
"$HOME/.ev-bot-venv/bin/python" "$DIR/bot.py"
