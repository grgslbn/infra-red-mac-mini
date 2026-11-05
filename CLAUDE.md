# Office heater automation

Control a Klarstein infrared heating panel (Tuya-based, paired in Smart Life) from this Mac Mini, over the local network.

## Goals
1. Heater turns OFF when the Mac goes to sleep, ON when the user wakes it.
2. Control temperature, on/off, mode and timer from the Mac (CLI + menu-bar widget).
3. Never leave the heater running unattended (fail-safe).

## Stack
- Python 3 + `tinytuya`, LOCAL control only (no cloud calls at runtime).
- `sleepwatcher` (Homebrew) for sleep/wake hooks.
- launchd agents for background jobs.
- SwiftBar (or xbar) for the menu-bar widget.

## Secrets — important
- `tinytuya.json` (cloud API key/secret) and `devices.json` (device id, local key, IP) are secrets.
- Never print, log or commit their contents. Add both to `.gitignore` before the first commit.
- The user runs `python3 -m tinytuya wizard` himself (with `!` prefix); do not ask him to paste the secret.

## Build plan
1. **Discover**: read `devices.json`, get IP + protocol version. Recommend a DHCP reservation for the heater's IP.
2. **Map data points**: read `status()`, change settings on the physical panel / Smart Life one at a time, diff the DPs. Document the mapping (power, target temp, current temp, mode, timer, child lock) in `DPS.md`.
3. **Control module + CLI** `heater` : `on`, `off`, `set <temp>`, `status`, `timer <h>`. Retries with backoff; short timeouts.
4. **Sleep/wake hooks** via sleepwatcher:
   - Sleep → send OFF immediately and synchronously (network drops fast).
   - Wake → only on USER wake (display wake / unlock), NOT dark wakes (Power Nap, maintenance). Wait for network with retries.
   - Respect manual override: if the user switched the heater off by hand within the session, don't re-enable on wake (configurable).
5. **Fail-safe**:
   - Optional heartbeat watchdog (later: M5Stack Cardputer on the LAN pings the Mac, turns heater off if Mac gone > N min).
   - Use the heater's own timer as a safety cap where possible.
   - Optional: no auto-ON outside working hours / on weekends (configurable).
6. **Menu-bar widget**: room temp, target temp, state; quick actions (on/off, ±1°C, timer).
7. **Optional**: small MCP server wrapping the CLI so Claude can control the heater.

## Notes
- Heater Wi-Fi is 2.4 GHz only.
- Re-pairing the heater in Smart Life changes the local key → rerun the wizard.
- Panel also has a physical mains rocker switch; if it's off, the device is unreachable — handle gracefully.
- Config (temps, hours, override behaviour) lives in `config.toml`, not in code.
