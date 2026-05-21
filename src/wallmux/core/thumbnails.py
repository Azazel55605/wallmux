"""Thumbnail cache helpers."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from platformdirs import user_cache_path

from wallmux.core.mime import WallpaperType

APP_NAME = "wallmux"


def thumbnail_cache_dir() -> Path:
    return user_cache_path(APP_NAME) / "thumbnails"


def thumbnail_cache_key(path: Path) -> str:
    stat = path.stat()
    source = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def thumbnail_path(path: Path) -> Path:
    return thumbnail_cache_dir() / f"{thumbnail_cache_key(path)}.jpg"


def ensure_thumbnail(path: Path, wallpaper_type: WallpaperType, size: int = 256) -> Path | None:
    if wallpaper_type is WallpaperType.VIDEO:
        return ensure_video_thumbnail(path, size)
    if wallpaper_type in {WallpaperType.IMAGE, WallpaperType.GIF}:
        return ensure_image_thumbnail(path, size)
    return None


def ensure_image_thumbnail(path: Path, size: int = 256) -> Path | None:
    target = thumbnail_path(path)
    if target.exists():
        return target

    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((size, size))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGB").save(target, "JPEG", quality=85)
    except OSError:
        return None

    return target


def ensure_video_thumbnail(path: Path, size: int = 256) -> Path | None:
    target = thumbnail_path(path)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:02",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={size}:-1",
        str(target),
    ]
    result = subprocess.run(command, check=False, capture_output=True)
    if result.returncode != 0 or not target.exists():
        return None
    return target
