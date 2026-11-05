"""Small persistent state (who turned the heater off and why), guarded by a file lock."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
from dataclasses import asdict, dataclass, field

from .config import STATE_DIR

STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "state.lock"


@dataclass
class State:
    # Why the heater is currently off because of us: "sleep" | "display_sleep" | "idle" | "hours" | None
    auto_off_reason: str | None = None
    # User switched it off (CLI, widget, panel or app). Blocks auto-ON on wake.
    manual_off: bool = False
    manual_off_date: str | None = None   # ISO date; manual-off expires at the next day
    last_power: bool | None = None       # last power state we observed
    last_target: float | None = None
    ip_cache: str | None = None          # discovered IP (not a secret)
    version_cache: str | None = None
    extra: dict = field(default_factory=dict)

    def set_manual_off(self) -> None:
        self.manual_off = True
        self.manual_off_date = dt.date.today().isoformat()
        self.auto_off_reason = None

    def clear_manual_off(self) -> None:
        self.manual_off = False
        self.manual_off_date = None

    def manual_off_active(self) -> bool:
        if not self.manual_off:
            return False
        if self.manual_off_date != dt.date.today().isoformat():
            self.clear_manual_off()      # expires overnight
            return False
        return True


def _load() -> State:
    try:
        data = json.loads(STATE_FILE.read_text())
        known = {k: v for k, v in data.items() if k in State.__dataclass_fields__}
        return State(**known)
    except (OSError, ValueError, TypeError):
        return State()


def _save(s: State) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2))
    os.replace(tmp, STATE_FILE)


@contextlib.contextmanager
def locked_state():
    """Read-modify-write the state while holding an exclusive lock (hooks can race)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        s = _load()
        try:
            yield s
        finally:
            _save(s)
            fcntl.flock(lf, fcntl.LOCK_UN)


def read_state() -> State:
    return _load()
