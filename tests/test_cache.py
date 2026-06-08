from __future__ import annotations

import json
import os
import time
from pathlib import Path

from wallmux.core.cache import cache_stats, clean_cache, rebuild_cache
from wallmux.core.library import WallpaperItem
from wallmux.core.mime import WallpaperType
from wallmux.core.video import optimized_video_metadata_path


def test_cache_stats_counts_thumbnail_and_video_files(monkeypatch, tmp_path: Path) -> None:
    thumbnails = tmp_path / "thumbnails"
    videos = tmp_path / "videos"
    thumbnails.mkdir()
    videos.mkdir()
    (thumbnails / "one.jpg").write_bytes(b"thumb")
    (videos / "clip.mp4").write_bytes(b"video")

    monkeypatch.setattr("wallmux.core.cache.thumbnail_cache_dir", lambda: thumbnails)
    monkeypatch.setattr(
        "wallmux.core.cache.video_poster_cache_dir",
        lambda: tmp_path / "posters",
    )

    stats = cache_stats(sample_cache_config(videos))

    assert stats.files == 2
    assert stats.bytes == 10
    assert stats.thumbnails.files == 1
    assert stats.optimized_videos.files == 1


def test_cache_clean_removes_age_stale_thumbnails(monkeypatch, tmp_path: Path) -> None:
    thumbnails = tmp_path / "thumbnails"
    videos = tmp_path / "videos"
    thumbnails.mkdir()
    stale = thumbnails / "old.jpg"
    fresh = thumbnails / "new.jpg"
    stale.write_bytes(b"old")
    fresh.write_bytes(b"new")
    old_time = time.time() - 3 * 24 * 60 * 60
    os.utime(stale, (old_time, old_time))

    monkeypatch.setattr("wallmux.core.cache.thumbnail_cache_dir", lambda: thumbnails)
    monkeypatch.setattr(
        "wallmux.core.cache.video_poster_cache_dir",
        lambda: tmp_path / "posters",
    )

    result = clean_cache(
        sample_cache_config(videos, thumbnail_max_age_days=1),
        include_videos=False,
        policy="stale-only",
    )

    assert result.removed_files == 1
    assert not stale.exists()
    assert fresh.exists()


def test_cache_clean_removes_stale_optimized_video_pair(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    video = tmp_path / "cache" / "balanced" / "source-cache.mp4"
    source.write_bytes(b"source")
    video.parent.mkdir(parents=True)
    video.write_bytes(b"optimized")
    metadata = optimized_video_metadata_path(video)
    metadata.write_text(
        json.dumps(
            {
                "source": str(source),
                "source_mtime_ns": 1,
                "source_size": 1,
                "output": str(video),
                "generated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    result = clean_cache(
        sample_cache_config(tmp_path / "cache"),
        include_thumbnails=False,
        policy="stale-only",
    )

    assert result.removed_files == 2
    assert not video.exists()
    assert not metadata.exists()


def test_cache_lru_trims_optimized_videos_to_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    cache = tmp_path / "cache"
    old = write_cached_video(cache, source, "old", last_used="2026-01-01T00:00:00+00:00")
    new = write_cached_video(cache, source, "new", last_used="2026-02-01T00:00:00+00:00")

    result = clean_cache(
        sample_cache_config(cache, optimized_video_max_size_mb=1),
        include_thumbnails=False,
        policy="lru",
    )

    assert result.removed_files == 2
    assert not old.exists()
    assert not optimized_video_metadata_path(old).exists()
    assert new.exists()


def test_rebuild_cache_rebuilds_thumbnails(monkeypatch, tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"image")
    calls = []

    def ensure(path, wallpaper_type):
        calls.append((path, wallpaper_type))
        return tmp_path / "thumb.jpg"

    monkeypatch.setattr("wallmux.core.cache.ensure_thumbnail", ensure)
    monkeypatch.setattr("wallmux.core.cache.thumbnail_path", lambda _path: tmp_path / "old.jpg")

    result = rebuild_cache(
        [WallpaperItem(image, WallpaperType.IMAGE, "awww")],
        sample_cache_config(tmp_path / "videos"),
        include_videos=False,
    )

    assert result.thumbnails_built == 1
    assert calls == [(image, WallpaperType.IMAGE)]


def sample_cache_config(
    video_cache: Path,
    *,
    thumbnail_max_age_days: int = 60,
    optimized_video_max_size_mb: int = 10240,
) -> dict:
    return {
        "cache": {
            "thumbnail_max_age_days": thumbnail_max_age_days,
            "optimized_video_max_size_mb": optimized_video_max_size_mb,
            "cleanup_policy": "stale-only",
        },
        "video_optimization": {
            "cache_dir": str(video_cache),
            "profile": "balanced",
            "prefer_optimized": True,
        },
    }


def write_cached_video(cache: Path, source: Path, name: str, *, last_used: str) -> Path:
    video = cache / "balanced" / f"{name}.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"x" * 800_000)
    source_stat = source.stat()
    optimized_video_metadata_path(video).write_text(
        json.dumps(
            {
                "source": str(source),
                "source_mtime_ns": source_stat.st_mtime_ns,
                "source_size": source_stat.st_size,
                "output": str(video),
                "generated_at": "2026-01-01T00:00:00+00:00",
                "last_used_at": last_used,
            }
        ),
        encoding="utf-8",
    )
    return video
