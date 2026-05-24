"""Automatic wallpaper selection helpers."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from wallmux.core.library import WallpaperItem, scan_wallpaper_dir

MODES = {"random", "name-up", "name-down"}
TARGETS = {"all", "focused", "monitor"}


def autoswitch_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("autoswitch", {})


def autoswitch_enabled(config: dict[str, Any]) -> bool:
    return bool(autoswitch_config(config).get("enabled", False))


def autoswitch_interval(config: dict[str, Any]) -> float:
    return max(1.0, float(autoswitch_config(config).get("interval_seconds", 300)))


def autoswitch_mode(config: dict[str, Any]) -> str:
    mode = str(autoswitch_config(config).get("mode", "random"))
    if mode not in MODES:
        raise ValueError(f"unknown autoswitch mode: {mode}")
    return mode


def autoswitch_target(config: dict[str, Any]) -> str:
    target = str(autoswitch_config(config).get("target", "all"))
    if target not in TARGETS:
        raise ValueError(f"unknown autoswitch target: {target}")
    return target


def autoswitch_monitor(config: dict[str, Any]) -> str:
    return str(autoswitch_config(config).get("monitor", ""))


def load_wallpaper_library(config: dict[str, Any]) -> list[WallpaperItem]:
    items: list[WallpaperItem] = []
    backend_rules = config.get("backend_rules", {})
    for raw_dir in config.get("general", {}).get("wallpaper_dirs", []):
        items.extend(scan_wallpaper_dir(Path(raw_dir), backend_rules=backend_rules))
    return sorted(_deduplicate(items), key=lambda item: item.path.name.casefold())


def choose_wallpaper(
    items: list[WallpaperItem],
    *,
    mode: str,
    current_file: str | None = None,
) -> WallpaperItem:
    if not items:
        raise ValueError("no wallpapers found in configured wallpaper_dirs")
    if mode == "random":
        if len(items) == 1:
            return items[0]
        candidates = [
            item
            for item in items
            if str(item.path.expanduser().resolve()) != current_file
        ]
        return random.choice(candidates or items)
    if mode in {"name-up", "name-down"}:
        return _choose_by_name(items, current_file=current_file, reverse=mode == "name-down")
    raise ValueError(f"unknown autoswitch mode: {mode}")


def _choose_by_name(
    items: list[WallpaperItem],
    *,
    current_file: str | None,
    reverse: bool,
) -> WallpaperItem:
    if current_file is None:
        return items[-1] if reverse else items[0]

    normalized = str(Path(current_file).expanduser().resolve())
    paths = [str(item.path.expanduser().resolve()) for item in items]
    if normalized not in paths:
        return items[-1] if reverse else items[0]

    current_index = paths.index(normalized)
    offset = -1 if reverse else 1
    return items[(current_index + offset) % len(items)]


def _deduplicate(items: list[WallpaperItem]) -> list[WallpaperItem]:
    seen: set[Path] = set()
    deduplicated: list[WallpaperItem] = []
    for item in items:
        path = item.path.expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        deduplicated.append(item)
    return deduplicated
