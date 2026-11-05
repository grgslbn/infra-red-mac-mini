"""Automation policy: sleep/wake hooks, manual on/off, watchdog.

Rules
- Sleep: switch OFF immediately. Remember whether *we* turned it off (auto_off_reason).
- Wake (user wake only): turn back ON only if we turned it off, the user didn't switch it
  off themselves today, and we are inside working hours (if a schedule is enabled).
- Watchdog: re-arms the heater's own countdown timer (dead-man switch), switches off after
  long inactivity / outside hours, and notices when someone switched it off by hand.
"""
from __future__ import annotations

import datetime as dt
import time

from . import macos
from .config import log
from .device import Heater, HeaterError, Unreachable
from .state import locked_state, read_state

RESTORABLE = {"sleep", "display_sleep", "idle"}


# ---------------- helpers ----------------
def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def within_hours(cfg: dict, now: dt.datetime | None = None) -> bool:
    sch = cfg["schedule"]
    if not sch.get("enabled"):
        return True
    now = now or dt.datetime.now()
    if now.isoweekday() not in sch.get("weekdays", [1, 2, 3, 4, 5]):
        return False
    return _hm(sch["start"]) <= now.time() < _hm(sch["end"])


def auto_on_allowed(cfg: dict, s) -> tuple[bool, str]:
    action = cfg["wake"].get("action", "restore")
    if action == "never":
        return False, "wake.action = never"
    if not within_hours(cfg):
        return False, "outside working hours"
    if cfg["wake"].get("respect_manual_off", True) and s.manual_off_active():
        return False, "you switched it off manually today"
    if action == "restore" and s.auto_off_reason not in RESTORABLE:
        return False, "it was already off before (nothing to restore)"
    return True, "ok"


def arm_safety_timer(h: Heater, cfg: dict) -> None:
    hours = cfg["failsafe"].get("safety_timer_hours", 0)
    if hours and h.has_timer():
        try:
            h.set_timer(hours)
        except HeaterError as e:
            log().warning("could not arm safety timer: %s", e)


def _connect(cfg, **kw) -> Heater:
    return Heater(cfg, **kw)


# ---------------- manual actions (CLI / widget / MCP) ----------------
def manual_on(cfg: dict, temp: float | None = None) -> None:
    h = _connect(cfg)
    h.set_power(True)
    if temp is not None:
        h.set_target(temp)
    arm_safety_timer(h, cfg)
    with locked_state() as s:
        s.clear_manual_off()
        s.auto_off_reason = None
        s.last_power = True
    log().info("manual ON%s", f" @ {temp}" if temp is not None else "")


def manual_off(cfg: dict) -> None:
    h = _connect(cfg)
    h.set_power(False)
    with locked_state() as s:
        s.set_manual_off()
        s.last_power = False
    log().info("manual OFF")


# ---------------- hooks ----------------
def on_sleep(cfg: dict, reason: str = "sleep") -> None:
    """Must be fast and synchronous: the network goes away moments after this returns."""
    if reason == "display_sleep" and not cfg["sleep"].get("off_on_display_sleep"):
        return
    t0 = time.monotonic()
    try:
        h = _connect(cfg, timeout=1.5, retries=3)
    except HeaterError as e:
        log().error("%s: cannot reach heater to switch it off: %s", reason, e)
        return
    was_on = None
    try:
        h.retries = 1
        was_on = h.status().power
    except Unreachable:
        pass
    h.retries = 3
    try:
        h.set_power(False)
        ok = True
    except Unreachable as e:
        ok = False
        log().error("%s: OFF failed: %s (heater safety timer is the backstop)", reason, e)
    with locked_state() as s:
        if was_on is None:
            was_on = bool(s.last_power) and not s.manual_off_active()
        if was_on and ok:
            s.auto_off_reason = reason
            s.last_power = False
        elif not was_on:
            # already off by hand/panel: nothing to restore later (keep an earlier auto reason)
            if s.auto_off_reason not in RESTORABLE:
                s.auto_off_reason = None
    log().info("%s: was_on=%s off_sent=%s (%.2fs)", reason, was_on, ok, time.monotonic() - t0)


def on_wake(cfg: dict, trigger: str = "display_wake") -> None:
    """Called on display wake (user wake), never on plain system/dark wake."""
    s = read_state()
    allowed, why = auto_on_allowed(cfg, s)
    if not allowed:
        log().info("%s: not switching on (%s)", trigger, why)
        return
    deadline = time.monotonic() + float(cfg["wake"].get("network_wait_seconds", 60))
    delay, h = 1.0, None
    while True:
        try:
            h = _connect(cfg, retries=1)
            st = h.status()
            break
        except HeaterError as e:
            if time.monotonic() + delay > deadline:
                log().warning("%s: heater unreachable after waiting for network: %s", trigger, e)
                return
            time.sleep(delay)
            delay = min(delay * 2, 10)
    if not st.power:
        h.retries = int(cfg["device"]["retries"])
        h.set_power(True)
    arm_safety_timer(h, cfg)
    with locked_state() as s:
        s.auto_off_reason = None
        s.last_power = True
    log().info("%s: heater ON (restored)", trigger)


# ---------------- watchdog ----------------
def watchdog(cfg: dict) -> str:
    before = read_state()
    try:
        h = _connect(cfg)
        st = h.status()
    except HeaterError as e:
        log().info("watchdog: %s", e)
        return f"unreachable: {e}"
    fs = cfg["failsafe"]
    idle = macos.idle_seconds()

    if st.power:
        with locked_state() as s:
            if s.manual_off:          # someone switched it on by hand / Smart Life
                s.clear_manual_off()
            s.auto_off_reason = None
        if cfg["schedule"].get("off_outside_hours") and not within_hours(cfg):
            h.set_power(False)
            with locked_state() as s:
                s.auto_off_reason, s.last_power = "hours", False
            log().info("watchdog: OFF (outside working hours)")
            return "off: outside hours"
        limit = float(fs.get("idle_off_minutes", 0)) * 60
        if limit and idle is not None and idle > limit:
            h.set_power(False)
            with locked_state() as s:
                s.auto_off_reason, s.last_power = "idle", False
            log().info("watchdog: OFF (idle %.0f min)", idle / 60)
            return "off: idle"
        arm_safety_timer(h, cfg)
        return "on: safety timer re-armed"

    # heater is off
    if before.last_power and before.auto_off_reason is None and not before.manual_off:
        with locked_state() as s:
            s.set_manual_off()
        log().info("watchdog: heater switched off outside our control -> treating as manual off")
        return "off: manual (detected)"
    if before.auto_off_reason in RESTORABLE and macos.user_present():
        allowed, why = auto_on_allowed(cfg, before)
        if allowed:
            on_wake(cfg, trigger="watchdog(user back)")
            return "on: restored (user back)"
    return "off"
