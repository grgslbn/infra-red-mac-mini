#!/bin/bash
# Installs: venv + tinytuya, sleepwatcher, launchd agents, `heater` on PATH, HeaterBar menu-bar app.
# Re-run any time (idempotent). Usage: ./install.sh [--mcp] [--no-agents] [--xbar]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.officeheater
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
WITH_MCP=0; AGENTS=1; XBAR=0
for a in "$@"; do case "$a" in --mcp) WITH_MCP=1;; --no-agents) AGENTS=0;; --xbar) XBAR=1;; esac; done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
xml() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"; printf '%s' "$s"; }
sq()  { printf "'%s'" "${1//\'/\'\\\'\'}"; }   # single-quote for sleepwatcher's shell

# 1. Python venv
PY=""
for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1; then PY="$(command -v "$c")"; break; fi
done
[ -n "$PY" ] || { echo "Need Python >= 3.11: brew install python@3.13"; exit 1; }
if [ ! -x "$ROOT/.venv/bin/python" ]; then say "Creating venv with $PY"; "$PY" -m venv "$ROOT/.venv"; fi
say "Installing tinytuya"
"$ROOT/.venv/bin/python" -m pip -q install --upgrade tinytuya
[ "$WITH_MCP" = 1 ] && { say "Installing MCP SDK"; "$ROOT/.venv/bin/python" -m pip -q install --upgrade "mcp>=1.2"; }

# 2. sleepwatcher
if ! command -v sleepwatcher >/dev/null 2>&1 && [ ! -x "$(brew --prefix)/sbin/sleepwatcher" ]; then
  say "Installing sleepwatcher"; brew install sleepwatcher
fi
SW="$(command -v sleepwatcher || echo "$(brew --prefix)/sbin/sleepwatcher")"

# 3. CLI on PATH
BIN_DIR="$(brew --prefix)/bin"
ln -sf "$ROOT/bin/heater" "$BIN_DIR/heater" && say "Linked $BIN_DIR/heater"

# 4. Menu bar: native HeaterBar app (default) or the xbar/SwiftBar plugin (--xbar)
if [ "$XBAR" = 1 ]; then
  for d in "$HOME/Library/Application Support/xbar/plugins" \
           "$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"; do
    [ -n "$d" ] && [ -d "$d" ] || continue
    sed "s|__HEATER_BIN__|$ROOT/bin/heater|" "$ROOT/xbar/heater.30s.sh" > "$d/heater.30s.sh"
    chmod +x "$d/heater.30s.sh"; say "Menu-bar plugin -> $d"
  done
else
  rm -f "$HOME/Library/Application Support/xbar/plugins/heater.30s.sh"
  say "Building HeaterBar.app"
  "$ROOT/menubar/build.sh" >/dev/null
  mkdir -p "$HOME/Applications"
  launchctl bootout "gui/$(id -u)/$LABEL.bar" 2>/dev/null || true
  pkill -x HeaterBar 2>/dev/null || true
  rm -rf "$HOME/Applications/HeaterBar.app"
  cp -R "$ROOT/menubar/HeaterBar.app" "$HOME/Applications/HeaterBar.app"
  defaults write com.officeheater.bar heaterPath "$ROOT/bin/heater"
  cat > "$LA/$LABEL.bar.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL.bar</string>
  <key>ProgramArguments</key><array>
    <string>$(xml "$HOME/Applications/HeaterBar.app/Contents/MacOS/HeaterBar")</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Interactive</string>
</dict></plist>
PLIST
  launchctl bootstrap "gui/$(id -u)" "$LA/$LABEL.bar.plist"
  say "HeaterBar is in your menu bar (starts at login; quit it from its ••• menu)"
fi

# 5. launchd agents
if [ ! -f "$ROOT/devices.json" ]; then
  echo; echo "devices.json not found yet -> skipping launchd agents."
  echo "Run the wizard (see README), then ./install.sh again."; AGENTS=0
fi
if [ "$AGENTS" = 1 ]; then
  mkdir -p "$LA" "$HOME/Library/Logs"
  INTERVAL=$("$ROOT/.venv/bin/python" -c "import sys;sys.path.insert(0,'$ROOT');from heaterctl.config import load_config;print(int(load_config()['failsafe']['watchdog_interval_seconds']))")

  cat > "$LA/$LABEL.sleepwatcher.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL.sleepwatcher</string>
  <key>ProgramArguments</key><array>
    <string>$(xml "$SW")</string><string>-V</string>
    <string>-s</string><string>$(xml "$(sq "$ROOT/hooks/sleep.sh")")</string>
    <string>-S</string><string>$(xml "$(sq "$ROOT/hooks/displaysleep.sh")")</string>
    <string>-W</string><string>$(xml "$(sq "$ROOT/hooks/displaywake.sh")")</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$(xml "$HOME/Library/Logs/heater-sleepwatcher.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$HOME/Library/Logs/heater-sleepwatcher.log")</string>
</dict></plist>
EOF

  cat > "$LA/$LABEL.watchdog.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL.watchdog</string>
  <key>ProgramArguments</key><array>
    <string>$(xml "$ROOT/bin/heater")</string><string>watchdog</string>
  </array>
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>$(xml "$HOME/Library/Logs/heater-watchdog.err")</string>
</dict></plist>
EOF

  for job in sleepwatcher watchdog; do
    launchctl bootout "gui/$(id -u)/$LABEL.$job" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LA/$LABEL.$job.plist"
    say "Loaded $LABEL.$job"
  done
fi

echo
say "Done. Try: heater status"
[ "$WITH_MCP" = 1 ] && echo "MCP: claude mcp add heater -- $(sq "$ROOT/.venv/bin/python") $(sq "$ROOT/mcp_server.py")"
exit 0
