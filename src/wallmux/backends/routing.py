"""Wallpaper type to backend routing."""

from __future__ import annotations

from wallmux.core.mime import WallpaperType

DEFAULT_BACKENDS = {
    WallpaperType.IMAGE: "awww",
    WallpaperType.GIF: "awww",
    WallpaperType.VIDEO: "mpvpaper",
}


def route_wallpaper(wallpaper_type: WallpaperType) -> str:
    if wallpaper_type not in DEFAULT_BACKENDS:
        raise ValueError(f"no backend route for wallpaper type: {wallpaper_type.value}")
    return DEFAULT_BACKENDS[wallpaper_type]
