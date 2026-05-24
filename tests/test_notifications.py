from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from wallmux.core.notifications import (
    notification_icon,
    notify_switch_failed,
    notify_wallpaper_switched,
)


def test_notify_wallpaper_switched_uses_notify_send(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "wallmux.core.notifications.subprocess.Popen",
        lambda command, **kwargs: calls.append(command),
    )
    config = {
        "notifications": {
            "enabled": True,
            "switched_wallpaper": True,
            "command": "notify-send",
            "app_name": "Wallmux",
            "icon": "wallmux-gui",
        }
    }

    notify_wallpaper_switched(
        config,
        [SimpleNamespace(file=Path("/tmp/wall.png"), monitor="DP-1", backend="awww")],
    )

    expected_icon = notification_icon("wallmux-gui")
    assert calls == [
        [
            "notify-send",
            "--app-name",
            "Wallmux",
            "--icon",
            expected_icon,
            "--app-icon",
            "wallmux-gui",
            "Wallpaper switched",
            "wall.png on DP-1 via awww",
        ]
    ]


def test_notification_icon_resolves_paths(tmp_path: Path) -> None:
    icon = tmp_path / "wallmux.svg"
    icon.write_text("<svg />", encoding="utf-8")

    assert notification_icon(str(icon)) == str(icon)


def test_notify_icon_can_be_disabled(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "wallmux.core.notifications.subprocess.Popen",
        lambda command, **kwargs: calls.append(command),
    )

    notify_switch_failed(
        {"notifications": {"enabled": True, "switching_failed": True, "icon": ""}},
        RuntimeError("boom"),
    )

    assert calls == [
        [
            "notify-send",
            "--app-name",
            "Wallmux",
            "Wallpaper switch failed",
            "boom",
        ]
    ]


def test_notify_switch_failed_can_be_disabled(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "wallmux.core.notifications.subprocess.Popen",
        lambda command, **kwargs: calls.append(command),
    )

    notify_switch_failed(
        {"notifications": {"enabled": True, "switching_failed": False}},
        RuntimeError("boom"),
    )

    assert calls == []
