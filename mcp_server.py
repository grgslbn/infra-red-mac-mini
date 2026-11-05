"""Optional MCP server so Claude can control the heater.

Install:  ./install.sh --mcp
Register: claude mcp add heater -- <project>/.venv/bin/python <project>/mcp_server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from heaterctl import logic  # noqa: E402
from heaterctl.config import load_config  # noqa: E402
from heaterctl.device import Heater, HeaterError  # noqa: E402
from heaterctl.state import read_state  # noqa: E402

mcp = FastMCP("office-heater")


def _run(fn):
    try:
        return fn()
    except HeaterError as e:
        return {"error": str(e)}


@mcp.tool()
def heater_status() -> dict:
    """Current power, room temperature, target temperature, mode and timer of the office heater."""
    def f():
        st = Heater(load_config()).status()
        s = read_state()
        return {**st.as_dict(), "manual_off_today": s.manual_off_active(),
                "auto_off_reason": s.auto_off_reason}
    return _run(f)


@mcp.tool()
def heater_on(target_temp: float | None = None) -> dict:
    """Turn the heater on, optionally setting the target temperature in °C."""
    return _run(lambda: (logic.manual_on(load_config(), target_temp), {"ok": True})[1])


@mcp.tool()
def heater_off() -> dict:
    """Turn the heater off (counts as a manual off: it won't auto-start on wake today)."""
    return _run(lambda: (logic.manual_off(load_config()), {"ok": True})[1])


@mcp.tool()
def heater_set_temperature(target_temp: float) -> dict:
    """Set the target temperature in °C (clamped to the configured min/max)."""
    return _run(lambda: {"target": Heater(load_config()).set_target(target_temp)})


@mcp.tool()
def heater_set_timer(hours: float) -> dict:
    """Set the heater's own countdown timer in hours (0 cancels)."""
    return _run(lambda: (Heater(load_config()).set_timer(hours), {"ok": True})[1])


if __name__ == "__main__":
    mcp.run()
