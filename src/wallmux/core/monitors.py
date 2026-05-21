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
        )
        for monitor in monitors
    ]
