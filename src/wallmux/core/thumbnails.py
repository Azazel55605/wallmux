"""Thumbnail cache helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from platformdirs import user_cache_path

APP_NAME = "wallmux"


def thumbnail_cache_dir() -> Path:
    return user_cache_path(APP_NAME) / "thumbnails"


def thumbnail_cache_key(path: Path) -> str:
    stat = path.stat()
    source = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()
