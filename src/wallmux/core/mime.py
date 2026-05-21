"""Wallpaper type detection."""

from __future__ import annotations

import mimetypes
from enum import Enum
from pathlib import Path


class WallpaperType(Enum):
    IMAGE = "image"
    GIF = "gif"
    VIDEO = "video"
    UNKNOWN = "unknown"


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}


def detect_mime(path: Path) -> str | None:
    try:
        import magic
    except ImportError:
        magic = None

    if magic is not None and path.exists():
        detected = magic.from_file(str(path), mime=True)
        if detected:
            return detected

    guessed, _ = mimetypes.guess_type(path)
    return guessed


def detect_wallpaper_type(path: Path) -> WallpaperType:
    mime = detect_mime(path)
    suffix = path.suffix.lower()

    if mime == "image/gif" or suffix == ".gif":
        return WallpaperType.GIF
    if mime and mime.startswith("image/"):
        return WallpaperType.IMAGE
    if mime and mime.startswith("video/"):
        return WallpaperType.VIDEO
    if suffix in IMAGE_EXTENSIONS:
        return WallpaperType.IMAGE
    if suffix in VIDEO_EXTENSIONS:
        return WallpaperType.VIDEO
    return WallpaperType.UNKNOWN
