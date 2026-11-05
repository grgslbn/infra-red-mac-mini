# Data-point (DP) mapping

Device: **Infra-redneck**, product "Wonderwall Heater" (Tuya category `qn`), protocol 3.4.
Source: DP name mapping downloaded by the tinytuya wizard, then verified with the `heater` CLI on 2026-11-05.

| Function      | DP  | Tuya code        | Type / range                                   | Verified |
|---------------|-----|------------------|------------------------------------------------|----------|
| Power         | 1   | `switch`         | bool                                           | ✅ on/off |
| Target temp   | 2   | `temp_set`       | int °C, 0–37, step 1 (no scaling)              | ✅ set 21 |
| Current temp  | 3   | `temp_current`   | int °C, 0–50, read-only                        | ✅ reads |
| Timer         | 19  | `countdown_set`  | enum `cancel`, `1h` … `6h`                     | ✅ 1h, cancel |
| Timer left    | 20  | `countdown_left` | int minutes, 0–1440, read-only                 | ✅ 60 after `1h` |
| Mode          | –   | –                | not present on this model                      | |
| Child lock    | –   | –                | not present on this model                      | |

Notes:
- The safety timer uses DP 19 (max 6 h). The watchdog re-sends `4h` every 5 minutes while the Mac is alive.
- `temp_current` read 30 °C while the heater was running: the sensor sits in/near the panel, so it
  reads warmer than the room. Treat it as "panel temperature", not true room temperature.
- Still to check by hand: when the countdown reaches 0, does the heater switch OFF (expected) and
  stay off? If it toggles instead, set `safety_timer_hours = 0` in config.toml.
