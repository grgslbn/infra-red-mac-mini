"""`heater` command line."""
from __future__ import annotations

import argparse
import json
import shlex
import sys

from . import logic
from .config import CONFIG_FILE, LOG_FILE, PROJECT_DIR, load_config, log
from .device import Heater, HeaterError, mask
from .state import locked_state, read_state


def _fmt_temp(v) -> str:
    return "?" if v is None else (f"{v:.1f}".rstrip("0").rstrip(".") + "°C")


def _timer_label(st, cfg) -> str | None:
    """Human 'time left' for the heater's own countdown, or None when no timer runs."""
    mins = st.timer_left_min
    if mins is None:
        t, unit = st.timer, cfg["dps"].get("timer_unit", "hours")
        if isinstance(t, (int, float)) and not isinstance(t, bool) and unit in ("hours", "minutes", "seconds"):
            mins = t * {"hours": 60, "minutes": 1, "seconds": 1 / 60}[unit]
        elif t not in (None, "", 0, False, cfg["dps"].get("timer_enum_cancel")):
            return str(t)
    if not mins:
        return None
    mins = int(mins)
    return f"{mins // 60}h {mins % 60:02d}m left" if mins >= 60 else f"{mins}m left"


def _status_line(st, cfg=None) -> str:
    parts = [f"Power: {'ON' if st.power else 'OFF' if st.power is not None else '?'}",
             f"Sensor: {_fmt_temp(st.current)}", f"Target: {_fmt_temp(st.target)}"]
    if st.mode is not None:
        parts.append(f"Mode: {st.mode}")
    tl = _timer_label(st, cfg or {"dps": {}})
    if tl:
        parts.append(f"Timer: {tl}")
    if st.child_lock is not None:
        parts.append(f"Lock: {'on' if st.child_lock else 'off'}")
    return " | ".join(parts)


# ---------------- commands ----------------
def cmd_status(cfg, a):
    st = Heater(cfg).status()
    s = read_state()
    if a.json:
        print(json.dumps({**st.as_dict(), "manual_off": s.manual_off_active(),
                          "auto_off_reason": s.auto_off_reason}))
    else:
        print(_status_line(st, cfg))
        if s.manual_off_active():
            print("(switched off manually today: won't auto-start on wake)")


def cmd_on(cfg, a):
    logic.manual_on(cfg, a.temp)
    print("Heater ON" + (f" @ {a.temp}°C" if a.temp is not None else ""))


def cmd_off(cfg, a):
    logic.manual_off(cfg)
    print("Heater OFF")


def cmd_set(cfg, a):
    t = Heater(cfg).set_target(a.temp)
    print(f"Target {_fmt_temp(t)}")


def cmd_adjust(cfg, delta):
    h = Heater(cfg)
    cur = h.status().target
    if cur is None:
        cur = cfg["comfort"]["default_temp"]
    t = h.set_target(cur + delta)
    print(f"Target {_fmt_temp(t)}")


def cmd_timer(cfg, a):
    h = Heater(cfg)
    h.set_timer(a.hours)
    print("Timer cancelled" if a.hours <= 0 else f"Timer {a.hours:g} h")


def cmd_mode(cfg, a):
    Heater(cfg).set_mode(a.mode)
    print(f"Mode {a.mode}")


def cmd_lock(cfg, a):
    Heater(cfg).set_child_lock(a.state == "on")
    print(f"Child lock {a.state}")


def cmd_discover(cfg, a):
    """Step 1: read devices.json and find IP + protocol version. Prints no secrets."""
    from .device import _load_device_entry, _snapshot_hint
    e = _load_device_entry(cfg)
    hint = _snapshot_hint(e["id"], cfg)
    print(f"Device:   {e.get('name', '?')}  (id {mask(e['id'])}, local key present: {bool(e.get('key'))})")
    print(f"Category: {e.get('category', '?')}  product: {e.get('product_name', '?')}")
    ip, ver = e.get("ip") or hint.get("ip"), str(e.get("version") or hint.get("version") or "")
    if not ip or a.scan:
        print("Scanning LAN for the heater (UDP 6666/6667, ~18 s)...")
        ip, scanned = Heater.discover(e["id"])
        ver = scanned or ver
    print(f"IP:       {ip}")
    print(f"Protocol: {ver or 'unknown (try 3.3, 3.4, 3.5)'}")
    with locked_state() as s:
        s.ip_cache, s.version_cache = ip, ver or None
    print("\nNext: give this IP a DHCP reservation in your router, then set in config.toml:")
    print(f'  [device]\n  ip = "{ip}"' + (f'\n  version = "{ver}"' if ver else ""))
    try:
        dps = Heater(cfg).raw_dps()
        print(f"\nConnected locally. Data points: {json.dumps(dps)}")
    except HeaterError as ex:
        print(f"\nCould not connect locally yet: {ex}")


def cmd_raw(cfg, a):
    print(json.dumps(Heater(cfg).raw_dps(), indent=2))


def cmd_map(cfg, a):
    """Step 2: interactive DP diff. Change ONE thing on the panel/app, press Enter, see what moved."""
    h = Heater(cfg)
    prev = h.raw_dps()
    print("Baseline:", json.dumps(prev))
    print("Change ONE setting on the panel or in Smart Life, wait 2 s, then press Enter.")
    print("Type a label first (e.g. 'power off', 'temp 22') to record it; 'q' to quit.\n")
    log_lines = []
    while True:
        try:
            label = input("label> ").strip()
        except EOFError:
            break
        if label.lower() in {"q", "quit", "exit"}:
            break
        cur = h.raw_dps()
        diff = {k: (prev.get(k), cur.get(k)) for k in sorted(set(prev) | set(cur), key=str)
                if prev.get(k) != cur.get(k)}
        if not diff:
            print("  no change detected (try again; some panels report with a delay)")
        for k, (o, n) in diff.items():
            line = f"  DP {k}: {o!r} -> {n!r}" + (f"   [{label}]" if label else "")
            print(line)
            log_lines.append(line)
        prev = cur
    if log_lines:
        out = PROJECT_DIR / "dps_capture.txt"
        out.write_text("\n".join(log_lines) + "\n")
        print(f"\nSaved to {out.name}. Copy the mapping into config.toml [dps] and DPS.md.")


def cmd_hook(cfg, a):
    if a.event in ("sleep", "display-sleep"):
        logic.on_sleep(cfg, "sleep" if a.event == "sleep" else "display_sleep")
    elif a.event in ("display-wake", "wake"):
        logic.on_wake(cfg, a.event.replace("-", "_"))


def cmd_watchdog(cfg, a):
    print(logic.watchdog(cfg))


def cmd_state(cfg, a):
    s = read_state()
    print(json.dumps({"auto_off_reason": s.auto_off_reason, "manual_off": s.manual_off_active(),
                      "last_power": s.last_power, "last_target": s.last_target,
                      "ip": s.ip_cache, "version": s.version_cache}, indent=2))
    if a.reset:
        with locked_state() as st:
            st.clear_manual_off()
            st.auto_off_reason = None
        print("state reset")


def cmd_xbar(cfg, a):
    """Menu-bar output in xbar/SwiftBar format."""
    me = shlex.quote(str(PROJECT_DIR / "bin/heater"))
    def act(label, *args):
        if not args:
            print(f"{label} | refresh=true")
            return
        params = " ".join(f"param{i + 1}={x}" for i, x in enumerate(args))
        print(f"{label} | bash={me} {params} terminal=false refresh=true")
    try:
        st = Heater(cfg, timeout=1.5, retries=2).status()
    except HeaterError as e:
        print("🔥 ? | color=gray")
        print("---")
        print("Heater unreachable | color=gray")
        print(f"{str(e)[:80]} | size=11 color=gray")
        print("---")
        act("Retry")
        return
    icon = "🔥" if st.power else "❄️"
    title = f"{icon} {_fmt_temp(st.current)}"
    if st.power:
        title += f" → {_fmt_temp(st.target)}"
    print(title)
    print("---")
    print(_status_line(st, cfg).replace(" | ", "  ·  ") + " | size=12")
    s = read_state()
    if s.manual_off_active():
        print("Manual off today (no auto-start on wake) | size=11 color=gray")
    elif s.auto_off_reason:
        print(f"Auto-off: {s.auto_off_reason} | size=11 color=gray")
    print("---")
    act("Turn OFF" if st.power else "Turn ON", "off" if st.power else "on")
    act("Target +1°C", "up")
    act("Target −1°C", "down")
    print("Set target")
    for t in range(18, 25):
        act(f"--{t}°C", "set", str(t))
    if cfg["dps"].get("timer"):
        print("Timer")
        for hrs in (1, 2, 4, 8):
            act(f"--{hrs} h", "timer", str(hrs))
        act("--Cancel", "timer", "0")
    if cfg["dps"].get("mode"):
        print("Mode")
        for m in cfg.get("modes", {}).get("names", []):
            act(f"--{m}", "mode", m)
    print("---")
    print(f"Open config | bash=/usr/bin/open param1={shlex.quote(str(CONFIG_FILE))} terminal=false")
    print(f"Open log | bash=/usr/bin/open param1=-a param2=Console param3={shlex.quote(str(LOG_FILE))} terminal=false")
    act("Refresh")


def cmd_panel(cfg, a):
    """One JSON object for the menu-bar app. Never fails: reports errors in the payload."""
    s = read_state()
    out = {"ok": False, "error": None, "power": None, "target": None, "current": None,
           "mode": None, "timer": None, "child_lock": None,
           "manual_off": s.manual_off_active(), "auto_off_reason": s.auto_off_reason,
           "presets": [{"label": k, "temp": v} for k, v in
                       (cfg.get("presets") or {"Eco": 18, "Comfort": 21, "Boost": 23}).items()],
           "timer_choices": cfg.get("panel", {}).get("timer_choices", [1, 2, 4]),
           "has_timer": bool(cfg["dps"].get("timer")),
           "modes": cfg.get("modes", {}).get("names", []),
           "min_temp": cfg["comfort"]["min_temp"], "max_temp": cfg["comfort"]["max_temp"],
           "wake_action": cfg["wake"]["action"],
           "off_on_sleep": True,
           "safety_timer_hours": cfg["failsafe"].get("safety_timer_hours", 0),
           "idle_off_minutes": cfg["failsafe"].get("idle_off_minutes", 0),
           "schedule": cfg["schedule"] if cfg["schedule"].get("enabled") else None}
    try:
        st = Heater(cfg, timeout=1.5, retries=2).status()
        out.update(st.as_dict(), ok=True)
        out["timer"] = _timer_label(st, cfg)
    except HeaterError as e:
        out["error"] = str(e)
    print(json.dumps(out))


def main(argv=None):
    p = argparse.ArgumentParser(prog="heater", description="Control the office IR heater over the LAN.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("status"); sp.add_argument("--json", action="store_true")  # noqa: E702
    sp = sub.add_parser("on"); sp.add_argument("temp", nargs="?", type=float)  # noqa: E702
    sub.add_parser("off")
    sp = sub.add_parser("set"); sp.add_argument("temp", type=float)  # noqa: E702
    sub.add_parser("up"); sub.add_parser("down")  # noqa: E702
    sp = sub.add_parser("timer", help="countdown in hours, 0 = cancel"); sp.add_argument("hours", type=float)  # noqa: E702
    sp = sub.add_parser("mode"); sp.add_argument("mode")  # noqa: E702
    sp = sub.add_parser("lock"); sp.add_argument("state", choices=["on", "off"])  # noqa: E702
    sp = sub.add_parser("discover", help="step 1: find IP + protocol"); sp.add_argument("--scan", action="store_true")  # noqa: E702
    sub.add_parser("map", help="step 2: interactive data-point diff")
    sub.add_parser("raw", help="print raw data points")
    sp = sub.add_parser("hook"); sp.add_argument("event", choices=["sleep", "display-sleep", "display-wake", "wake"])  # noqa: E702
    sub.add_parser("watchdog")
    sp = sub.add_parser("state"); sp.add_argument("--reset", action="store_true")  # noqa: E702
    sub.add_parser("xbar")
    sub.add_parser("panel", help="JSON for the menu-bar app")
    a = p.parse_args(argv)

    cfg = load_config()
    handlers = {"status": cmd_status, "on": cmd_on, "off": cmd_off, "set": cmd_set,
                "up": lambda c, a: cmd_adjust(c, +1), "down": lambda c, a: cmd_adjust(c, -1),
                "timer": cmd_timer, "mode": cmd_mode, "lock": cmd_lock, "discover": cmd_discover,
                "map": cmd_map, "raw": cmd_raw, "hook": cmd_hook, "watchdog": cmd_watchdog,
                "state": cmd_state, "xbar": cmd_xbar, "panel": cmd_panel}
    try:
        handlers[a.cmd](cfg, a)
    except HeaterError as e:
        if a.cmd in ("hook", "watchdog"):
            log().error("%s: %s", a.cmd, e)
        print(f"heater: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
