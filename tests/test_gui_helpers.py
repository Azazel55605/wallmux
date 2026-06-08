from __future__ import annotations

from pathlib import Path

from wallmux.core.ipc import DaemonUnavailable
from wallmux.gui import ALL_MONITORS, _set_wallpaper_detached


def test_detached_set_uses_daemon_without_local_fallback(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(
        "wallmux.gui.send_request",
        lambda request: calls.append(request) or {"ok": True, "results": []},
    )
    monkeypatch.setattr(
        "wallmux.gui.load_config",
        lambda: (_ for _ in ()).throw(AssertionError("local fallback ran")),
    )

    request = {"command": "set", "file": str(tmp_path / "wall.jpg"), "monitor": "DP-1"}
    _set_wallpaper_detached(request, tmp_path / "wall.jpg", "DP-1", "awww", "simultaneous")

    assert calls == [request]


def test_detached_set_falls_back_locally_and_notifies(monkeypatch, tmp_path: Path) -> None:
    image = tmp_path / "wall.jpg"
    image.write_bytes(b"")
    result = object()
    notifications: list[list[object]] = []
    monkeypatch.setattr(
        "wallmux.gui.send_request",
        lambda _request: (_ for _ in ()).throw(DaemonUnavailable("offline")),
    )
    monkeypatch.setattr("wallmux.gui.load_config", lambda: {"profiles": {}})
    monkeypatch.setattr("wallmux.gui.effective_config_for_profile", lambda config: config)
    monkeypatch.setattr("wallmux.gui.set_wallpaper", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(
        "wallmux.gui.notify_wallpaper_switched",
        lambda _config, results: notifications.append(results),
    )

    _set_wallpaper_detached(
        {"command": "set", "file": str(image), "monitor": "DP-1"},
        image,
        "DP-1",
        "awww",
        "simultaneous",
    )

    assert notifications == [[result]]


def test_detached_set_all_uses_all_monitor_fallback(monkeypatch, tmp_path: Path) -> None:
    image = tmp_path / "wall.jpg"
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        "wallmux.gui.send_request",
        lambda _request: (_ for _ in ()).throw(DaemonUnavailable("offline")),
    )
    monkeypatch.setattr("wallmux.gui.load_config", lambda: {"profiles": {}})
    monkeypatch.setattr("wallmux.gui.effective_config_for_profile", lambda config: config)
    monkeypatch.setattr(
        "wallmux.gui.set_wallpaper_for_all",
        lambda file, **kwargs: calls.append((file, kwargs["mode"])) or [],
    )
    monkeypatch.setattr("wallmux.gui.notify_wallpaper_switched", lambda *_args: None)

    _set_wallpaper_detached(
        {"command": "set", "file": str(image), "all": True},
        image,
        ALL_MONITORS,
        "awww",
        "sequential",
    )

    assert calls == [(image, "sequential")]
