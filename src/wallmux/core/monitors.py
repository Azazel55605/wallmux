"""Hyprland monitor detection."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Monitor:
    name: str
    focused: bool = False
    description: str | None = None
    width: int | None = None
    height: int | None = None
    refresh_rate: float | None = None
    scale: float | None = None


def list_monitors() -> list[Monitor]:
    result = subprocess.run(
        ["hyprctl", "monitors", "-j"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    monitors = json.loads(result.stdout)
    return [
        Monitor(
            name=monitor["name"],
            focused=bool(monitor.get("focused", False)),
            description=monitor.get("description"),
            width=_optional_int(monitor.get("width")),
            height=_optional_int(monitor.get("height")),
            refresh_rate=_optional_float(monitor.get("refreshRate")),
            scale=_optional_float(monitor.get("scale")),
        )
        for monitor in monitors
    ]


def get_focused_monitor(monitors: list[Monitor] | None = None) -> Monitor | None:
    for monitor in monitors if monitors is not None else list_monitors():
        if monitor.focused:
            return monitor
    return None


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
