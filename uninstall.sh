#!/bin/bash
# Removes launchd agents, the PATH link and the menu-bar plugin. Leaves the project, venv and secrets.
LABEL=com.officeheater
for job in sleepwatcher watchdog bar; do
  launchctl bootout "gui/$(id -u)/$LABEL.$job" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/$LABEL.$job.plist"
done
rm -f "$(brew --prefix)/bin/heater"
pkill -x HeaterBar 2>/dev/null; rm -rf "$HOME/Applications/HeaterBar.app"
rm -f "$HOME/Library/Application Support/xbar/plugins/heater.30s.sh"
SB="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null)"; [ -n "$SB" ] && rm -f "$SB/heater.30s.sh"
echo "Uninstalled (state in ~/Library/Application Support/heater kept)."
