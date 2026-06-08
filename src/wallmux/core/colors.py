"""Resolve the current wallpaper image used for color generation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from wallmux.core.config import load_config
from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import Monitor, list_monitors
from wallmux.core.state import load_state
from wallmux.core.thumbnails import ensure_thumbnail


class ColorSourceError(RuntimeError):
    """Raised when Wallmux cannot resolve a current color source."""


def current_color_source(
    monitor: str | None = None,
    *,
    config: dict | None = None,
    state_path: Path | None = None,
    monitor_provider: Callable[[], list[Monitor]] = list_monitors,
) -> Path:
    state = load_state(state_path)
    selected_monitor = monitor or _first_monitor_name(monitor_provider())
    if selected_monitor is None:
        raise ColorSourceError("Hyprland did not report any monitors")

    entry = state.monitors.get(selected_monitor)
    if entry is None:
        raise ColorSourceError(f"no wallpaper state for monitor: {selected_monitor}")

    source = Path(entry.file).expanduser()
    if not source.is_file():
        raise ColorSourceError(f"wallpaper file does not exist: {source}")

    if entry.wallpaper_type != WallpaperType.VIDEO.value:
        return source.resolve()

    config = config or load_config()
    thumbnail = ensure_thumbnail(
        source,
        WallpaperType.VIDEO,
        int(config.get("general", {}).get("thumbnail_size", 256)),
    )
    if thumbnail is None or not thumbnail.is_file():
        raise ColorSourceError(f"could not generate video thumbnail: {source}")
    return thumbnail.resolve()


def _first_monitor_name(monitors: list[Monitor]) -> str | None:
    return monitors[0].name if monitors else None
