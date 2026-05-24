"""Wallpaper type to backend routing."""

from __future__ import annotations

from typing import Any

from wallmux.backends.awww import AwwwBackend
from wallmux.backends.gslapper import GslapperBackend
from wallmux.backends.mpvpaper import MpvpaperBackend
from wallmux.backends.swww import SwwwBackend
from wallmux.core.mime import WallpaperType

DEFAULT_BACKENDS = {
    WallpaperType.IMAGE: "awww",
    WallpaperType.GIF: "awww",
    WallpaperType.VIDEO: "mpvpaper",
}

COMPATIBLE_BACKENDS = {
    WallpaperType.IMAGE: ("awww", "swww"),
    WallpaperType.GIF: ("awww", "swww", "mpvpaper", "gslapper"),
    WallpaperType.VIDEO: ("mpvpaper", "gslapper"),
}


def route_wallpaper(
    wallpaper_type: WallpaperType,
    backend_rules: dict[str, str] | None = None,
) -> str:
    if wallpaper_type is WallpaperType.UNKNOWN:
        raise ValueError(f"no backend route for wallpaper type: {wallpaper_type.value}")

    if backend_rules and wallpaper_type.value in backend_rules:
        return backend_rules[wallpaper_type.value]

    if wallpaper_type not in DEFAULT_BACKENDS:
        raise ValueError(f"no backend route for wallpaper type: {wallpaper_type.value}")

    return DEFAULT_BACKENDS[wallpaper_type]


def build_backend(
    name: str,
    config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
):
    backend_config = dict((config or {}).get("backends", {}).get(name, {}))
    if overrides:
        backend_config.update(overrides)

    if name == "awww":
        return AwwwBackend(**backend_config)
    if name == "swww":
        return SwwwBackend(**backend_config)
    if name == "mpvpaper":
        return MpvpaperBackend(**backend_config)
    if name == "gslapper":
        return GslapperBackend(**backend_config)

    raise ValueError(f"unknown backend: {name}")


def compatible_backends(wallpaper_type: WallpaperType) -> tuple[str, ...]:
    if wallpaper_type is WallpaperType.UNKNOWN:
        return ()
    return COMPATIBLE_BACKENDS.get(wallpaper_type, ())
