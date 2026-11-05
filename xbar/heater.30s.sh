#!/bin/bash
# <xbar.title>Office heater</xbar.title>
# <xbar.desc>Klarstein IR panel via local Tuya</xbar.desc>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# Installed as a symlink by install.sh; HEATER_BIN is filled in there.
HEATER_BIN="__HEATER_BIN__"
exec "$HEATER_BIN" xbar
