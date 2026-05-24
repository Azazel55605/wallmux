"""Desktop notification helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wallmux.core.wallpaper import SetResult


def notifications_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("notifications", {})


def notifications_enabled(config: dict[str, Any]) -> bool:
    return bool(notifications_config(config).get("enabled", True))


def notify_wallpaper_switched(config: dict[str, Any], results: list[SetResult]) -> None:
    settings = notifications_config(config)
    if not notifications_enabled(config) or not settings.get("switched_wallpaper", True):
        return
    if not results:
        return

    first = results[0]
    if len(results) == 1:
        body = f"{Path(first.file).name} on {first.monitor} via {first.backend}"
    else:
        body = f"{Path(first.file).name} on {len(results)} monitors via {first.backend}"
    send_notification(config, "Wallpaper switched", body)


def notify_switch_failed(config: dict[str, Any], error: Exception) -> None:
    settings = notifications_config(config)
    if not notifications_enabled(config) or not settings.get("switching_failed", True):
        return
    send_notification(config, "Wallpaper switch failed", str(error))


def send_notification(config: dict[str, Any], title: str, body: str) -> None:
    settings = notifications_config(config)
    command = str(settings.get("command", "notify-send"))
    app_name = str(settings.get("app_name", "Wallmux"))
    try:
        subprocess.Popen(
            [command, "--app-name", app_name, title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return
