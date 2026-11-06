# Roadmap

## Next: real room temperature (ESP32 + DHT11)

**Why:** the heater's built-in sensor sits above the panel and reads far too warm (31 °C with a
24 °C target). The heater regulates on that value, so the room ends up colder than the target.
The Mac mini has no ambient sensor (its internal sensors follow CPU load, not the room).

**Hardware** (already on hand): ESP32 + DHT11.
- Wiring: DATA → GPIO 4, VCC → 3.3 V, GND → GND. A bare 4-pin DHT11 needs a 10 kΩ pull-up
  DATA → 3.3 V; 3-pin breakout boards have it built in.
- Place it at desk height, away from the panel and out of its direct radiation.
- DHT11 is ±2 °C, 1 °C steps: fine for display, coarse for control. A DHT22 or SHT31 is a
  drop-in upgrade.

**Steps**
1. ESP32 firmware (`esp32/`, built with `arduino-cli` from Homebrew): join Wi-Fi, serve
   `GET /` → `{"temp": 20.4, "humidity": 48, "uptime": 1234}`. Advertise as `heater-sensor.local`
   (mDNS). Wi-Fi credentials in a git-ignored `esp32/secrets.h` that the user fills in.
2. Mac side: `[room_sensor] url = "http://heater-sensor.local/"` in `config.toml`; short timeout,
   stale-reading detection. Show **Room** (ESP32) next to **Panel sensor** in `heater status`,
   `heater panel` JSON, HeaterBar (popover + menu-bar title) and the MCP status tool.
3. Optional Mac thermostat mode (`[thermostat] source = "room"`):
   - set the heater's own setpoint high (e.g. max) so its warm sensor never blocks heating;
   - the watchdog switches power on/off around the target with ±0.5 °C hysteresis and a
     minimum on/off time (e.g. 5 min); check interval shorter than the current 5 min;
   - if the ESP32 is unreachable or stale, fall back to the heater's own thermostat (restore a
     normal setpoint). All existing fail-safes (sleep-off, idle-off, rolling timer) stay in force.
4. Tests with a fake sensor; update README and DPS.md.

## Next: Windows PC + Tapo P110 smart plug

**Goal:** the same behaviour as on the Mac, but for a heater on a TP-Link Tapo P110 plug, driven by
a Windows PC: off when the PC sleeps or you're away, back on when you return, never left running.

**Steps**
1. Device backend: add a Tapo P110 backend next to the Tuya one (local control via `python-kasa`,
   which speaks Tapo's KLAP protocol). The plug can only switch power, so no target temp or timer:
   the heater keeps its own thermostat. If the P110 firmware's built-in countdown / auto-off is
   reachable locally, use it as the safety cap like the Tuya timer; otherwise rely on the watchdog.
   Tapo local auth needs the TP-Link account email + password → keep them in a git-ignored secrets
   file the user fills in, same rules as `devices.json`.
2. Platform layer: split `heaterctl/macos.py` behind a small interface and add `windows.py`:
   - idle time via `GetLastInputInfo`;
   - display/session state (locked, display off) via WTS session notifications / power broadcasts;
   - sleep/resume hooks via a small background process listening for `WM_POWERBROADCAST`
     (`PBT_APMSUSPEND` → OFF synchronously, `PBT_APMRESUMEAUTOMATIC` + user input → restore),
     or Task Scheduler triggers on Kernel-Power / Power-Troubleshooter events.
3. Background jobs: Task Scheduler entries (at logon + every 5 min watchdog) instead of launchd;
   an `install.ps1` / `uninstall.ps1` pair.
4. Tray widget: a Windows tray icon (e.g. `pystray`) showing on/off with quick on/off, reusing the
   `heater panel` JSON. HeaterBar stays Mac-only.
5. Config: one `config.toml` per machine, with `[device] backend = "tuya" | "tapo"`.
6. Tests for the Tapo backend and Windows platform layer with fakes; README section for Windows.

**Open questions**
- Which heater is on the P110, and how much power does it draw (P110 is rated 16 A / 3680 W)?
- Does the P110 support local control on its current firmware (TP-Link has changed this before)?
- The P110 also measures power: could show whether the heater element is actually heating.

## Later

- **Heartbeat fail-safe on the ESP32** (replaces the M5Stack Cardputer idea): the Mac pings the
  ESP32 every few minutes; if the Mac is gone > N min, the ESP32 switches the heater off itself
  (Tuya local protocol on the ESP32, which needs the heater's local key stored on the device).
- Working-hours schedule: decide whether to enable `[schedule]` so idle-restore can't switch the
  heater on at weekends or early mornings.
- Tune fail-safes: `safety_timer_hours` 4 → 1, `idle_off_minutes` 45 → 20–30.
- Verify by hand: timer expiry switches the heater off and it stays off; a real sleep/wake cycle.
- DHCP reservation for the heater (192.168.1.76) and later the ESP32.
