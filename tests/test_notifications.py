from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from wallmux.core.notifications import notify_switch_failed, notify_wallpaper_switched


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
        }
    }

    notify_wallpaper_switched(
        config,
        [SimpleNamespace(file=Path("/tmp/wall.png"), monitor="DP-1", backend="awww")],
    )

    assert calls == [
        [
            "notify-send",
            "--app-name",
            "Wallmux",
            "Wallpaper switched",
            "wall.png on DP-1 via awww",
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
