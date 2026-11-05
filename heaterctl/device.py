"""Local-only tinytuya wrapper with short timeouts and retries.

Never prints or logs the local key or the contents of devices.json.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import time
from dataclasses import dataclass

from .config import devices_path, log
from .state import STATE_DIR, locked_state, read_state

DEVICE_LOCK = STATE_DIR / "device.lock"


@contextlib.contextmanager
def device_lock(wait: float = 10.0):
    """The heater accepts ONE local TCP connection at a time: serialise every process
    (menu bar, watchdog, sleep hook, CLI) so they never collide."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEVICE_LOCK, "w") as f:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    break  # proceed anyway rather than hang forever
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class HeaterError(Exception):
    pass


class Unreachable(HeaterError):
    """Device did not answer: mains rocker off, Wi-Fi down, wrong IP, or Mac offline."""


@dataclass
class Status:
    power: bool | None
    target: float | None
    current: float | None
    mode: str | None
    timer: object | None
    child_lock: bool | None
    raw: dict
    timer_left_min: int | None = None   # minutes left on the heater's countdown, if reported

    def as_dict(self) -> dict:
        return {"power": self.power, "target": self.target, "current": self.current,
                "mode": self.mode, "timer": self.timer, "child_lock": self.child_lock,
                "timer_left_min": self.timer_left_min}


def _load_device_entry(cfg: dict) -> dict:
    path = devices_path(cfg)
    if not path.exists():
        raise HeaterError(f"{path.name} not found. Run `python -m tinytuya wizard` in {path.parent}.")
    try:
        devices = json.loads(path.read_text())
    except ValueError:
        raise HeaterError(f"{path.name} is not valid JSON; rerun the wizard.") from None
    name = cfg["device"].get("name") or ""
    for d in devices:
        if not name or d.get("name") == name:
            return d
    raise HeaterError(f"No device named {name!r} in {path.name}.")


def _snapshot_hint(dev_id: str, cfg: dict) -> dict:
    """tinytuya's snapshot.json (from the wizard's scan) usually has ip + version."""
    snap = devices_path(cfg).with_name("snapshot.json")
    try:
        for d in json.loads(snap.read_text()).get("devices", []):
            if d.get("id") == dev_id:
                return {"ip": d.get("ip"), "version": str(d.get("ver") or d.get("version") or "")}
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def mask(s: str | None) -> str:
    if not s:
        return "?"
    return s[:4] + "…" + s[-3:] if len(s) > 8 else "…"


class Heater:
    def __init__(self, cfg: dict, timeout: float | None = None, retries: int | None = None):
        import tinytuya  # imported lazily: keeps `heater --help` fast

        self.cfg = cfg
        self.dps = cfg["dps"]
        self.timeout = float(timeout if timeout is not None else cfg["device"]["timeout"])
        self.retries = int(retries if retries is not None else cfg["device"]["retries"])
        entry = _load_device_entry(cfg)
        self.dev_id = entry["id"]
        self.name = entry.get("name", "heater")
        hint = _snapshot_hint(self.dev_id, cfg)
        st = read_state()
        self.ip = cfg["device"].get("ip") or entry.get("ip") or hint.get("ip") or st.ip_cache
        self.version = (cfg["device"].get("version") or str(entry.get("version") or "")
                        or hint.get("version") or st.version_cache or "3.3")
        if not self.ip:
            self.ip, found_ver = self.discover(self.dev_id)
            if found_ver:
                self.version = found_ver
        self._dev = tinytuya.Device(self.dev_id, address=self.ip, local_key=entry["key"],
                                    version=float(self.version),
                                    connection_timeout=self.timeout,
                                    connection_retry_limit=1, connection_retry_delay=0.2)
        self._dev.set_socketPersistent(False)
        self._dev.set_socketTimeout(self.timeout)

    # ---------- discovery ----------
    @staticmethod
    def discover(dev_id: str) -> tuple[str, str | None]:
        import tinytuya

        log().info("discovering heater on LAN (UDP broadcast)")
        found = tinytuya.find_device(dev_id=dev_id)
        ip = found.get("ip") if isinstance(found, dict) else None
        if not ip:
            raise Unreachable("Heater not found on the LAN (mains switch off? 2.4 GHz Wi-Fi down?)")
        ver = str(found.get("version") or "") or None
        with locked_state() as s:
            s.ip_cache, s.version_cache = ip, ver
        return ip, ver

    # ---------- low level with retries ----------
    def _call(self, fn, *args):
        last = None
        for attempt in range(self.retries):
            try:
                with device_lock():
                    r = fn(*args)
            except Exception as e:  # socket errors etc.
                r = {"Error": f"{type(e).__name__}"}
            if isinstance(r, dict) and "Error" not in r:
                return r
            last = r.get("Error") if isinstance(r, dict) else r
            if attempt < self.retries - 1:
                time.sleep(min(0.4 * 2 ** attempt, 3))
        raise Unreachable(f"Heater not responding ({last}). Mains switch off or Wi-Fi down?")

    def raw_dps(self) -> dict:
        r = self._call(self._dev.status)
        return r.get("dps", {})

    def _set(self, values: dict) -> dict:
        values = {str(k): v for k, v in values.items() if k}
        if not values:
            return {}
        if len(values) == 1:
            (dp, v), = values.items()
            return self._call(self._dev.set_value, dp, v)
        return self._call(self._dev.set_multiple_values, values)

    # ---------- high level ----------
    def _scale(self, v):
        if v is None:
            return None
        sc = self.dps.get("temp_scale") or 1
        return v / sc if sc != 1 else v

    def status(self) -> Status:
        d = self.raw_dps()
        g = lambda key: d.get(str(self.dps.get(key))) if self.dps.get(key) else None  # noqa: E731
        st = Status(power=g("power"), target=self._scale(g("target_temp")),
                    current=self._scale(g("current_temp")), mode=g("mode"),
                    timer=g("timer"), child_lock=g("child_lock"), raw=d,
                    timer_left_min=g("timer_left"))
        with locked_state() as s:
            if st.power is not None:
                s.last_power = bool(st.power)
            if st.target is not None:
                s.last_target = st.target
        return st

    def set_power(self, on: bool) -> None:
        self._set({self.dps["power"]: bool(on)})

    def set_target(self, temp: float) -> float:
        c = self.cfg["comfort"]
        temp = max(c["min_temp"], min(c["max_temp"], temp))
        raw = temp * (self.dps.get("temp_scale") or 1)
        self._set({self.dps["target_temp"]: int(round(raw))})
        return temp

    def set_mode(self, mode: str) -> None:
        if not self.dps.get("mode"):
            raise HeaterError("No mode DP configured in config.toml [dps].")
        self._set({self.dps["mode"]: mode})

    def set_child_lock(self, on: bool) -> None:
        if not self.dps.get("child_lock"):
            raise HeaterError("No child_lock DP configured in config.toml [dps].")
        self._set({self.dps["child_lock"]: bool(on)})

    def has_timer(self) -> bool:
        return bool(self.dps.get("timer"))

    def timer_value(self, hours: float):
        unit = self.dps.get("timer_unit", "hours")
        if unit == "enum":
            if hours <= 0:
                return self.dps.get("timer_enum_cancel", "cancel")
            h = max(1, min(int(self.dps.get("timer_enum_max_h", 6)), int(round(hours))))
            return self.dps.get("timer_enum_format", "{h}h").format(h=h)
        mult = {"hours": 1, "minutes": 60, "seconds": 3600}.get(unit, 1)
        return int(round(max(0, hours) * mult))

    def set_timer(self, hours: float) -> None:
        if not self.has_timer():
            raise HeaterError("No timer DP configured in config.toml [dps].")
        self._set({self.dps["timer"]: self.timer_value(hours)})
