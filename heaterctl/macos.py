"""macOS helpers: user idle time and display state (used to tell a user wake from a dark wake)."""
from __future__ import annotations

import ctypes
import ctypes.util
import re
import subprocess


def idle_seconds() -> float | None:
    """Seconds since last keyboard/mouse input. Dark wakes (Power Nap) have no input."""
    try:
        out = subprocess.run(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"],
                             capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
        return int(m.group(1)) / 1e9 if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def display_asleep() -> bool | None:
    try:
        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
        cg.CGDisplayIsAsleep.restype = ctypes.c_bool
        return bool(cg.CGDisplayIsAsleep(cg.CGMainDisplayID()))
    except (OSError, AttributeError):
        return None


def user_present(max_idle: float = 120) -> bool:
    """True only if someone touched the keyboard/mouse recently and the display is on."""
    idle = idle_seconds()
    if idle is None or idle > max_idle:
        return False
    return display_asleep() is not True
