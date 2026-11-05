"""Paths, config.toml loading and logging. Secrets are never logged."""
from __future__ import annotations

import logging
import os
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("HEATER_HOME", Path(__file__).resolve().parent.parent))
CONFIG_FILE = Path(os.environ.get("HEATER_CONFIG", PROJECT_DIR / "config.toml"))
STATE_DIR = Path(os.environ.get("HEATER_STATE_DIR", Path.home() / "Library/Application Support/heater"))
LOG_FILE = Path(os.environ.get("HEATER_LOG", Path.home() / "Library/Logs/heater.log"))

DEFAULTS: dict = {
    "device": {"devices_file": "devices.json", "name": "", "ip": "", "version": "",
               "timeout": 2.0, "retries": 3},
    "dps": {"power": "1", "target_temp": "2", "current_temp": "3", "mode": "4",
            "timer": "", "child_lock": "", "temp_scale": 1, "timer_unit": "hours",
            "timer_enum_format": "{h}h", "timer_enum_cancel": "cancel"},
    "comfort": {"default_temp": 21, "min_temp": 5, "max_temp": 30},
    "wake": {"action": "restore", "respect_manual_off": True, "network_wait_seconds": 60},
    "sleep": {"off_on_display_sleep": False},
    "schedule": {"enabled": False, "weekdays": [1, 2, 3, 4, 5], "start": "07:30",
                 "end": "19:00", "off_outside_hours": False},
    "failsafe": {"safety_timer_hours": 4, "idle_off_minutes": 45, "watchdog_interval_seconds": 300},
}


def load_config(path: Path = CONFIG_FILE) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if path.exists():
        with open(path, "rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            cfg.setdefault(section, {}).update(values)
    return cfg


def devices_path(cfg: dict) -> Path:
    p = Path(cfg["device"]["devices_file"]).expanduser()
    return p if p.is_absolute() else PROJECT_DIR / p


_logger: logging.Logger | None = None


def log() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("heater")
        _logger.setLevel(logging.INFO)
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            h = RotatingFileHandler(LOG_FILE, maxBytes=512_000, backupCount=2)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            _logger.addHandler(h)
        except OSError:
            _logger.addHandler(logging.NullHandler())
        # keep tinytuya quiet: its debug output can include payloads
        logging.getLogger("tinytuya").setLevel(logging.WARNING)
    return _logger
