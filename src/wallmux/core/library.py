"""Wallpaper library scanning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wallmux.backends.routing import route_wallpaper
from wallmux.core.mime import WallpaperType, detect_wallpaper_type


@dataclass(frozen=True)
class WallpaperItem:
    path: Path
    wallpaper_type: WallpaperType
    backend: str


def scan_wallpaper_dir(
    directory: Path,
    *,
    backend_rules: dict[str, str] | None = None,
) -> list[WallpaperItem]:
    root = directory.expanduser()
    if not root.exists() or not root.is_dir():
        return []

    items: list[WallpaperItem] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        wallpaper_type = detect_wallpaper_type(path)
        if wallpaper_type is WallpaperType.UNKNOWN:
            continue

        items.append(
            WallpaperItem(
                path=path,
                wallpaper_type=wallpaper_type,
                backend=route_wallpaper(wallpaper_type, backend_rules),
            )
        )

    return items


def filter_wallpapers(
    items: list[WallpaperItem],
    *,
    query: str = "",
    wallpaper_type: WallpaperType | None = None,
) -> list[WallpaperItem]:
    normalized_query = query.casefold().strip()

    return [
        item
        for item in items
        if (wallpaper_type is None or item.wallpaper_type is wallpaper_type)
        and (not normalized_query or normalized_query in item.path.name.casefold())
    ]
