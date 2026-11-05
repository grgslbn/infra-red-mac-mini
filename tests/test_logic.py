"""Offline tests of the sleep/wake/watchdog policy with a fake heater.

Run: .venv/bin/python -m unittest discover -s tests -v
"""
import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

os.environ["HEATER_STATE_DIR"] = tempfile.mkdtemp()
os.environ["HEATER_LOG"] = os.path.join(os.environ["HEATER_STATE_DIR"], "test.log")

from heaterctl import logic, state  # noqa: E402
from heaterctl.config import load_config  # noqa: E402
from heaterctl.device import Status, Unreachable  # noqa: E402


class FakeHeater:
    def __init__(self):
        self.power, self.target, self.timer = True, 21, None
        self.reachable = True
        self.retries = 3
        self.calls = []

    def _check(self):
        if not self.reachable:
            raise Unreachable("down")

    def status(self):
        self._check()
        with state.locked_state() as s:
            s.last_power = self.power
        return Status(self.power, self.target, 19, None, self.timer, None, {})

    def set_power(self, on):
        self._check(); self.power = on; self.calls.append(("power", on))  # noqa: E702

    def set_target(self, t):
        self._check(); self.target = t; return t  # noqa: E702

    def has_timer(self):
        return True

    def set_timer(self, h):
        self._check(); self.timer = h; self.calls.append(("timer", h))  # noqa: E702


class PolicyTests(unittest.TestCase):
    def setUp(self):
        for f in (state.STATE_FILE,):
            if f.exists():
                f.unlink()
        self.cfg = load_config()
        self.cfg["schedule"]["enabled"] = False
        self.h = FakeHeater()
        p = mock.patch.object(logic, "_connect", lambda cfg, **kw: self.h)
        p.start(); self.addCleanup(p.stop)  # noqa: E702
        q = mock.patch.object(logic.time, "sleep", lambda s: None)
        q.start(); self.addCleanup(q.stop)  # noqa: E702

    def test_sleep_then_wake_restores(self):
        logic.on_sleep(self.cfg)
        self.assertFalse(self.h.power)
        self.assertEqual(state.read_state().auto_off_reason, "sleep")
        logic.on_wake(self.cfg)
        self.assertTrue(self.h.power)
        self.assertEqual(self.h.timer, 4)  # safety timer armed
        self.assertIsNone(state.read_state().auto_off_reason)

    def test_manual_off_is_respected_on_wake(self):
        logic.manual_off(self.cfg)
        logic.on_sleep(self.cfg)
        logic.on_wake(self.cfg)
        self.assertFalse(self.h.power)

    def test_heater_already_off_at_sleep_stays_off(self):
        self.h.power = False
        logic.on_sleep(self.cfg)
        logic.on_wake(self.cfg)
        self.assertFalse(self.h.power)

    def test_always_on_mode(self):
        self.cfg["wake"]["action"] = "always_on"
        self.h.power = False
        logic.on_wake(self.cfg)
        self.assertTrue(self.h.power)

    def test_outside_hours_no_auto_on(self):
        self.cfg["schedule"].update(enabled=True, weekdays=[1], start="07:00", end="08:00")
        logic.on_sleep(self.cfg)
        with mock.patch.object(logic, "within_hours", return_value=False):
            logic.on_wake(self.cfg)
        self.assertFalse(self.h.power)

    def test_wake_waits_for_network(self):
        logic.on_sleep(self.cfg)
        n = {"i": 0}
        real = self.h.status

        def flaky():
            n["i"] += 1
            if n["i"] < 3:
                raise Unreachable("wifi not back yet")
            return real()
        self.h.status = flaky
        logic.on_wake(self.cfg)
        self.assertTrue(self.h.power)

    def test_unreachable_at_sleep_does_not_crash(self):
        self.h.reachable = False
        logic.on_sleep(self.cfg)  # logs, no exception

    def test_display_sleep_ignored_by_default(self):
        logic.on_sleep(self.cfg, "display_sleep")
        self.assertTrue(self.h.power)

    def test_watchdog_idle_off_then_restore_when_user_back(self):
        with mock.patch.object(logic.macos, "idle_seconds", return_value=3600):
            self.assertEqual(logic.watchdog(self.cfg), "off: idle")
        self.assertFalse(self.h.power)
        with mock.patch.object(logic.macos, "user_present", return_value=True), \
             mock.patch.object(logic.macos, "idle_seconds", return_value=5):
            self.assertEqual(logic.watchdog(self.cfg), "on: restored (user back)")
        self.assertTrue(self.h.power)

    def test_watchdog_no_restore_on_dark_wake(self):
        logic.on_sleep(self.cfg)
        with mock.patch.object(logic.macos, "user_present", return_value=False), \
             mock.patch.object(logic.macos, "idle_seconds", return_value=9999):
            self.assertEqual(logic.watchdog(self.cfg), "off")
        self.assertFalse(self.h.power)

    def test_watchdog_detects_manual_panel_off(self):
        logic.manual_on(self.cfg)
        self.h.power = False  # someone used the panel / Smart Life
        with mock.patch.object(logic.macos, "idle_seconds", return_value=5):
            self.assertEqual(logic.watchdog(self.cfg), "off: manual (detected)")
        self.assertTrue(state.read_state().manual_off_active())

    def test_watchdog_rearms_timer(self):
        self.h.timer = 1
        with mock.patch.object(logic.macos, "idle_seconds", return_value=5):
            logic.watchdog(self.cfg)
        self.assertEqual(self.h.timer, 4)

    def test_within_hours(self):
        self.cfg["schedule"].update(enabled=True, weekdays=[1, 2, 3, 4, 5], start="07:30", end="19:00")
        self.assertTrue(logic.within_hours(self.cfg, dt.datetime(2026, 11, 2, 9, 0)))   # Mon
        self.assertFalse(logic.within_hours(self.cfg, dt.datetime(2026, 11, 2, 20, 0)))
        self.assertFalse(logic.within_hours(self.cfg, dt.datetime(2026, 11, 8, 9, 0)))  # Sun


if __name__ == "__main__":
    unittest.main()
