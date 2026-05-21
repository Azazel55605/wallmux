"""Persistent runtime state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_state_path

APP_NAME = "wallmux"


@dataclass
class WallpaperEntry:
    file: str
    backend: str
    wallpaper_type: str
    pid: int | None = None


@dataclass
class WallmuxState:
    monitors: dict[str, WallpaperEntry] = field(default_factory=dict)


def state_file() -> Path:
    return user_state_path(APP_NAME) / "state.json"


def load_state(path: Path | None = None) -> WallmuxState:
    target = path or state_file()
    if not target.exists():
        return WallmuxState()

    payload = json.loads(target.read_text(encoding="utf-8"))
    monitors = {
        monitor: WallpaperEntry(**entry)
        for monitor, entry in payload.get("monitors", {}).items()
    }
    return WallmuxState(monitors=monitors)


def save_state(state: WallmuxState, path: Path | None = None) -> None:
    target = path or state_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "monitors": {
            monitor: asdict(entry)
            for monitor, entry in state.monitors.items()
        }
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def save_wallpaper_state(
    monitor: str,
    file: Path,
    backend: str,
    wallpaper_type: str,
    path: Path | None = None,
) -> None:
    state = load_state(path)
    state.monitors[monitor] = WallpaperEntry(
        file=str(file.expanduser()),
        backend=backend,
        wallpaper_type=wallpaper_type,
    )
    save_state(state, path)
