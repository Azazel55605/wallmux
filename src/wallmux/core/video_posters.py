"""Full-resolution poster frames used beneath video wallpaper processes."""

from __future__ import annotations

import hashlib
import subprocess
import threading
from pathlib import Path

from platformdirs import user_cache_path

APP_NAME = "wallmux"


def video_poster_cache_dir() -> Path:
    return user_cache_path(APP_NAME) / "video-posters"


def video_poster_path(path: Path, timestamp_seconds: float = 0.0) -> Path:
    stat = path.stat()
    source = (
        f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:"
        f"{max(0.0, timestamp_seconds):.3f}"
    )
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return video_poster_cache_dir() / f"{key}.jpg"


def ensure_video_poster(path: Path, timestamp_seconds: float = 0.0) -> Path | None:
    """Extract and cache a full-resolution video frame without modifying the source."""
    try:
        target = video_poster_path(path, timestamp_seconds)
    except OSError:
        return None
    if target.exists():
        return target

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    temporary = target.with_name(f".{target.name}.{threading.get_ident()}.tmp.jpg")
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0.0, timestamp_seconds)),
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-update",
        "1",
        str(temporary),
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except OSError:
        return None
    if result.returncode != 0 or not temporary.exists():
        _remove_temporary(temporary)
        return None
    try:
        temporary.replace(target)
    except OSError:
        _remove_temporary(temporary)
        return target if target.exists() else None
    return target


def _remove_temporary(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
