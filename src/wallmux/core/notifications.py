"""Desktop notification helpers."""

from __future__ import annotations

import subprocess
from importlib.resources import files
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
    icon = str(settings.get("icon", "wallmux-gui")).strip()
    desktop_entry = str(settings.get("desktop_entry", "wallmux-gui")).strip()
    notification_command = [command, "--app-name", app_name]
    if icon:
        resolved_icon = notification_icon(icon)
        notification_command.extend(["--icon", resolved_icon, "--app-icon", resolved_icon])
        notification_command.extend(["--hint", f"string:image-path:{resolved_icon}"])
    if desktop_entry:
        notification_command.extend(["--hint", f"string:desktop-entry:{desktop_entry}"])
    notification_command.extend([title, body])
    try:
        subprocess.Popen(
            notification_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def notification_icon(icon: str) -> str:
    configured_icon = Path(icon).expanduser()
    if configured_icon.exists():
        return str(configured_icon)

    for candidate in _icon_candidates(icon):
        if candidate.exists():
            return str(candidate)

    try:
        icon_resource = files("wallmux.data").joinpath(f"{icon}.svg")
        if icon_resource.is_file():
            return str(icon_resource)
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    return icon


def _icon_candidates(icon: str) -> list[Path]:
    icon_names = [icon]
    if not icon.endswith(".svg"):
        icon_names.append(f"{icon}.svg")

    roots = [
        Path.home() / ".local/share/icons/hicolor/scalable/apps",
        Path.home() / ".local/share/pixmaps",
        Path("/usr/share/icons/hicolor/scalable/apps"),
        Path("/usr/share/pixmaps"),
    ]
    return [root / icon_name for root in roots for icon_name in icon_names]
