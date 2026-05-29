"""Cache accounting and maintenance helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wallmux.core.library import WallpaperItem
from wallmux.core.mime import WallpaperType
from wallmux.core.thumbnails import ensure_thumbnail, thumbnail_cache_dir, thumbnail_path
from wallmux.core.video import (
    VideoInspectionError,
    configured_video_cache_dir,
    configured_video_profile,
    optimize_video,
    optimized_video_metadata_path,
)


@dataclass(frozen=True)
class CacheSectionStats:
    name: str
    path: Path
    files: int
    bytes: int
    stale_files: int = 0
    stale_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class CacheStats:
    thumbnails: CacheSectionStats
    optimized_videos: CacheSectionStats

    @property
    def files(self) -> int:
        return self.thumbnails.files + self.optimized_videos.files

    @property
    def bytes(self) -> int:
        return self.thumbnails.bytes + self.optimized_videos.bytes

    @property
    def stale_files(self) -> int:
        return self.thumbnails.stale_files + self.optimized_videos.stale_files

    @property
    def stale_bytes(self) -> int:
        return self.thumbnails.stale_bytes + self.optimized_videos.stale_bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "bytes": self.bytes,
            "stale_files": self.stale_files,
            "stale_bytes": self.stale_bytes,
            "thumbnails": self.thumbnails.as_dict(),
            "optimized_videos": self.optimized_videos.as_dict(),
        }


@dataclass(frozen=True)
class CacheCleanResult:
    removed_files: int
    removed_bytes: int
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CacheRebuildResult:
    thumbnails_built: int
    videos_optimized: int
    videos_skipped: int
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def cache_stats(config: dict[str, Any] | None = None) -> CacheStats:
    active_config = config or {}
    return CacheStats(
        thumbnails=_thumbnail_stats(active_config),
        optimized_videos=_optimized_video_stats(active_config),
    )


def clean_cache(
    config: dict[str, Any],
    *,
    include_thumbnails: bool = True,
    include_videos: bool = True,
    policy: str | None = None,
) -> CacheCleanResult:
    selected_policy = policy or str(config.get("cache", {}).get("cleanup_policy", "stale-only"))
    removed_files = 0
    removed_bytes = 0
    errors: list[str] = []

    if include_thumbnails:
        result = _clean_thumbnails(config, selected_policy)
        removed_files += result.removed_files
        removed_bytes += result.removed_bytes
        errors.extend(result.errors)

    if include_videos:
        result = _clean_optimized_videos(config, selected_policy)
        removed_files += result.removed_files
        removed_bytes += result.removed_bytes
        errors.extend(result.errors)

    return CacheCleanResult(
        removed_files=removed_files,
        removed_bytes=removed_bytes,
        errors=tuple(errors),
    )


def rebuild_cache(
    items: list[WallpaperItem],
    config: dict[str, Any],
    *,
    include_thumbnails: bool = True,
    include_videos: bool = True,
    force_videos: bool = False,
) -> CacheRebuildResult:
    thumbnails_built = 0
    videos_optimized = 0
    videos_skipped = 0
    errors: list[str] = []

    if include_thumbnails:
        for item in items:
            try:
                target = thumbnail_path(item.path)
                if target.exists():
                    target.unlink()
                if ensure_thumbnail(item.path, item.wallpaper_type):
                    thumbnails_built += 1
            except OSError as error:
                errors.append(f"{item.path}: {error}")

    if include_videos:
        profile = configured_video_profile(config)
        for item in items:
            if item.wallpaper_type is not WallpaperType.VIDEO:
                continue
            try:
                result = optimize_video(
                    item.path,
                    profile=profile,
                    force=force_videos,
                    config=config,
                )
            except VideoInspectionError as error:
                errors.append(f"{item.path}: {error}")
                continue
            if result.skipped:
                videos_skipped += 1
            else:
                videos_optimized += 1

    return CacheRebuildResult(
        thumbnails_built=thumbnails_built,
        videos_optimized=videos_optimized,
        videos_skipped=videos_skipped,
        errors=tuple(errors),
    )


def touch_optimized_video_metadata(metadata_path: Path) -> None:
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["last_used_at"] = datetime.now(UTC).isoformat()
    try:
        metadata_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        return


def format_cache_stats(stats: CacheStats) -> str:
    return "\n".join(
        [
            f"total: {stats.files} files, {_format_bytes(stats.bytes)}",
            f"stale: {stats.stale_files} files, {_format_bytes(stats.stale_bytes)}",
            "",
            _format_section_stats(stats.thumbnails),
            "",
            _format_section_stats(stats.optimized_videos),
        ]
    )


def format_cache_clean_result(result: CacheCleanResult) -> str:
    lines = [
        f"removed: {result.removed_files} files",
        f"freed: {_format_bytes(result.removed_bytes)}",
    ]
    if result.errors:
        lines.append("errors:")
        lines.extend(f"  {error}" for error in result.errors)
    return "\n".join(lines)


def format_cache_rebuild_result(result: CacheRebuildResult) -> str:
    lines = [
        f"thumbnails built: {result.thumbnails_built}",
        f"videos optimized: {result.videos_optimized}",
        f"videos skipped: {result.videos_skipped}",
    ]
    if result.errors:
        lines.append("errors:")
        lines.extend(f"  {error}" for error in result.errors)
    return "\n".join(lines)


def cache_stats_json(stats: CacheStats) -> str:
    return json.dumps(stats.as_dict(), indent=2, sort_keys=True)


def cache_clean_result_json(result: CacheCleanResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def cache_rebuild_result_json(result: CacheRebuildResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def optimized_video_cache_limit_bytes(config: dict[str, Any]) -> int:
    megabytes = int(config.get("cache", {}).get("optimized_video_max_size_mb", 10240))
    return max(0, megabytes) * 1024 * 1024


def _thumbnail_stats(config: dict[str, Any]) -> CacheSectionStats:
    path = thumbnail_cache_dir()
    max_age_seconds = _thumbnail_max_age_seconds(config)
    now = datetime.now(UTC).timestamp()
    files = 0
    total = 0
    stale_files = 0
    stale_total = 0
    for file in _iter_files(path):
        size = _file_size(file)
        files += 1
        total += size
        if max_age_seconds is not None and now - file.stat().st_mtime > max_age_seconds:
            stale_files += 1
            stale_total += size
    return CacheSectionStats("thumbnails", path, files, total, stale_files, stale_total)


def _optimized_video_stats(config: dict[str, Any]) -> CacheSectionStats:
    path = configured_video_cache_dir(config)
    files = 0
    total = 0
    stale_files = 0
    stale_total = 0
    for file in _iter_files(path):
        size = _file_size(file)
        files += 1
        total += size
        if _is_stale_optimized_video_file(file):
            stale_files += 1
            stale_total += size
    return CacheSectionStats("optimized_videos", path, files, total, stale_files, stale_total)


def _clean_thumbnails(config: dict[str, Any], policy: str) -> CacheCleanResult:
    errors: list[str] = []
    removed_files = 0
    removed_bytes = 0
    if policy == "lru":
        policy = "stale-only"

    for file in _iter_files(thumbnail_cache_dir()):
        if policy != "all" and not _is_stale_thumbnail(file, config):
            continue
        result = _remove_file(file)
        removed_files += result.removed_files
        removed_bytes += result.removed_bytes
        errors.extend(result.errors)
    return CacheCleanResult(removed_files, removed_bytes, tuple(errors))


def _clean_optimized_videos(config: dict[str, Any], policy: str) -> CacheCleanResult:
    errors: list[str] = []
    removed_files = 0
    removed_bytes = 0
    files = list(_iter_files(configured_video_cache_dir(config)))

    for file in files:
        if policy != "all" and not _is_stale_optimized_video_file(file):
            continue
        result = _remove_file(file)
        removed_files += result.removed_files
        removed_bytes += result.removed_bytes
        errors.extend(result.errors)

    if policy == "lru":
        max_bytes = optimized_video_cache_limit_bytes(config)
        if max_bytes > 0:
            result = _trim_optimized_video_lru(config, max_bytes)
            removed_files += result.removed_files
            removed_bytes += result.removed_bytes
            errors.extend(result.errors)

    return CacheCleanResult(removed_files, removed_bytes, tuple(errors))


def _trim_optimized_video_lru(config: dict[str, Any], max_bytes: int) -> CacheCleanResult:
    entries = []
    total = 0
    for video_file in _iter_optimized_video_outputs(configured_video_cache_dir(config)):
        size = _file_size(video_file)
        total += size
        entries.append((video_file, _optimized_video_last_used(video_file), size))
    if total <= max_bytes:
        return CacheCleanResult(0, 0)

    removed_files = 0
    removed_bytes = 0
    errors: list[str] = []
    for video_file, _last_used, size in sorted(entries, key=lambda entry: entry[1]):
        if total <= max_bytes:
            break
        metadata_file = optimized_video_metadata_path(video_file)
        for file in (video_file, metadata_file):
            result = _remove_file(file)
            removed_files += result.removed_files
            removed_bytes += result.removed_bytes
            errors.extend(result.errors)
        total -= size
    return CacheCleanResult(removed_files, removed_bytes, tuple(errors))


def _is_stale_thumbnail(path: Path, config: dict[str, Any]) -> bool:
    max_age_seconds = _thumbnail_max_age_seconds(config)
    if max_age_seconds is None:
        return False
    return datetime.now(UTC).timestamp() - path.stat().st_mtime > max_age_seconds


def _is_stale_optimized_video_file(path: Path) -> bool:
    if path.suffix == ".json":
        return _is_stale_metadata(path)
    metadata_path = optimized_video_metadata_path(path)
    if not metadata_path.exists():
        return True
    return _is_stale_metadata(metadata_path)


def _is_stale_metadata(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True

    output = Path(str(data.get("output", ""))).expanduser()
    source = Path(str(data.get("source", ""))).expanduser()
    if not output.exists() or not source.exists():
        return True

    try:
        source_stat = source.stat()
    except OSError:
        return True
    return (
        data.get("source_mtime_ns") != source_stat.st_mtime_ns
        or data.get("source_size") != source_stat.st_size
    )


def _optimized_video_last_used(path: Path) -> str:
    metadata_path = optimized_video_metadata_path(path)
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("last_used_at") or data.get("generated_at") or "")


def _iter_optimized_video_outputs(path: Path):
    for file in _iter_files(path):
        if file.suffix != ".json":
            yield file


def _remove_file(path: Path) -> CacheCleanResult:
    try:
        size = _file_size(path)
        path.unlink()
    except FileNotFoundError:
        return CacheCleanResult(0, 0)
    except OSError as error:
        return CacheCleanResult(0, 0, (f"{path}: {error}",))
    return CacheCleanResult(1, size)


def _iter_files(path: Path):
    if not path.exists():
        return
    for file in path.rglob("*"):
        if file.is_file():
            yield file


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _thumbnail_max_age_seconds(config: dict[str, Any]) -> float | None:
    days = float(config.get("cache", {}).get("thumbnail_max_age_days", 60))
    if days <= 0:
        return None
    return days * 24 * 60 * 60


def _format_section_stats(stats: CacheSectionStats) -> str:
    return "\n".join(
        [
            f"{stats.name}:",
            f"  path: {stats.path}",
            f"  files: {stats.files}",
            f"  size: {_format_bytes(stats.bytes)}",
            f"  stale: {stats.stale_files} files, {_format_bytes(stats.stale_bytes)}",
        ]
    )


def _format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)
