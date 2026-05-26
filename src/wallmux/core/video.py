"""Video metadata and optimization planning helpers."""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path

from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import Monitor, list_monitors

APP_NAME = "wallmux"

VIDEO_OPTIMIZATION_PROFILES: dict[str, dict[str, Any]] = {
    "compatibility": {
        "codec": "libx264",
        "codec_names": {"h264"},
        "container": "mp4",
        "extension": ".mp4",
        "max_width": 1920,
        "max_height": 1080,
        "max_bit_rate": 25_000_000,
        "crf": 23,
        "preset": "veryfast",
        "extra_args": ["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    },
    "balanced": {
        "codec": "libx264",
        "codec_names": {"h264"},
        "container": "mp4",
        "extension": ".mp4",
        "max_width": 2560,
        "max_height": 1440,
        "max_bit_rate": 45_000_000,
        "crf": 22,
        "preset": "medium",
        "extra_args": ["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    },
    "quality": {
        "codec": "libx264",
        "codec_names": {"h264"},
        "container": "mp4",
        "extension": ".mp4",
        "max_width": 3840,
        "max_height": 2160,
        "max_bit_rate": 80_000_000,
        "crf": 20,
        "preset": "slow",
        "extra_args": ["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    },
}


class VideoInspectionError(RuntimeError):
    """Raised when video metadata cannot be inspected."""


@dataclass(frozen=True)
class VideoMetadata:
    path: Path
    codec: str
    container: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    size_bytes: int | None
    bit_rate: int | None
    frame_rate: float | None

    @property
    def pixels(self) -> int | None:
        if self.width is None or self.height is None:
            return None
        return self.width * self.height

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["pixels"] = self.pixels
        return data


@dataclass(frozen=True)
class VideoWarning:
    level: str
    message: str
    details: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class VideoInspection:
    metadata: VideoMetadata
    warnings: tuple[VideoWarning, ...]
    monitors: tuple[Monitor, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.as_dict(),
            "warnings": [warning.as_dict() for warning in self.warnings],
            "monitors": [asdict(monitor) for monitor in self.monitors],
        }


@dataclass(frozen=True)
class VideoOptimizationPlan:
    source: Path
    output: Path
    profile: str
    metadata: VideoMetadata
    already_suitable: bool
    reasons: tuple[str, ...]
    ffmpeg_command: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "output": str(self.output),
            "profile": self.profile,
            "metadata": self.metadata.as_dict(),
            "already_suitable": self.already_suitable,
            "reasons": list(self.reasons),
            "ffmpeg_command": list(self.ffmpeg_command),
        }


@dataclass(frozen=True)
class VideoOptimizationResult:
    plan: VideoOptimizationPlan
    output: Path
    metadata_path: Path | None
    skipped: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.as_dict(),
            "output": str(self.output),
            "metadata_path": str(self.metadata_path) if self.metadata_path else None,
            "skipped": self.skipped,
            "message": self.message,
        }


@dataclass(frozen=True)
class VideoLibraryOptimizationResult:
    optimized: tuple[VideoOptimizationResult, ...]
    skipped: tuple[VideoOptimizationResult, ...]
    failed: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "optimized": [result.as_dict() for result in self.optimized],
            "skipped": [result.as_dict() for result in self.skipped],
            "failed": list(self.failed),
        }


@dataclass(frozen=True)
class VideoOptimizationProgress:
    out_time_seconds: float | None
    duration_seconds: float | None
    total_size: int | None
    speed: str
    progress: str

    @property
    def percent(self) -> float | None:
        if not self.duration_seconds or self.out_time_seconds is None:
            return None
        return min(100.0, max(0.0, (self.out_time_seconds / self.duration_seconds) * 100.0))


def inspect_video(
    path: Path,
    *,
    monitors: list[Monitor] | None = None,
) -> VideoInspection:
    metadata = probe_video(path)
    active_monitors = tuple(monitors if monitors is not None else list_monitors())
    warnings = tuple(video_warnings(metadata, list(active_monitors)))
    return VideoInspection(metadata=metadata, warnings=warnings, monitors=active_monitors)


def video_cache_dir() -> Path:
    return user_cache_path(APP_NAME) / "optimized-videos"


def plan_video_optimization(
    path: Path,
    *,
    profile: str = "balanced",
    cache_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> VideoOptimizationPlan:
    settings = _optimization_profile_settings(profile, config)

    metadata = probe_video(path)
    output = optimized_video_path(
        path,
        profile=profile,
        extension=settings["extension"],
        cache_dir=cache_dir,
    )
    reasons = tuple(_optimization_reasons(metadata, settings))
    command = tuple(_ffmpeg_optimization_command(path, output, settings))
    return VideoOptimizationPlan(
        source=path,
        output=output,
        profile=profile,
        metadata=metadata,
        already_suitable=not reasons,
        reasons=reasons,
        ffmpeg_command=command,
    )


def optimize_video(
    path: Path,
    *,
    profile: str = "balanced",
    force: bool = False,
    cache_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    progress_callback: Callable[[VideoOptimizationProgress], None] | None = None,
) -> VideoOptimizationResult:
    plan = plan_video_optimization(path, profile=profile, cache_dir=cache_dir, config=config)
    if plan.already_suitable and not force:
        return VideoOptimizationResult(
            plan=plan,
            output=plan.source,
            metadata_path=None,
            skipped=True,
            message="source already matches optimization profile",
        )

    plan.output.parent.mkdir(parents=True, exist_ok=True)
    returncode, output = _run_ffmpeg_optimization(plan, progress_callback)
    if returncode != 0:
        output = output.strip() or "ffmpeg failed"
        raise VideoInspectionError(output)

    metadata_path = optimized_video_metadata_path(plan.output)
    write_optimized_video_metadata(plan, metadata_path)
    return VideoOptimizationResult(
        plan=plan,
        output=plan.output,
        metadata_path=metadata_path,
        skipped=False,
        message="optimized video written",
    )


def optimize_video_library(
    items,
    *,
    profile: str = "balanced",
    force: bool = False,
    cache_dir: Path | None = None,
    config: dict[str, Any] | None = None,
    progress_callback: Callable[[Path, VideoOptimizationProgress], None] | None = None,
) -> VideoLibraryOptimizationResult:
    optimized: list[VideoOptimizationResult] = []
    skipped: list[VideoOptimizationResult] = []
    failed: list[dict[str, str]] = []
    video_items = [item for item in items if item.wallpaper_type is WallpaperType.VIDEO]
    for item in video_items:
        callback = None
        if progress_callback is not None:
            def callback(progress, path=item.path):
                progress_callback(path, progress)

        try:
            result = optimize_video(
                item.path,
                profile=profile,
                force=force,
                cache_dir=cache_dir,
                config=config,
                progress_callback=callback,
            )
        except VideoInspectionError as error:
            failed.append({"file": str(item.path), "error": str(error)})
            continue
        if result.skipped:
            skipped.append(result)
        else:
            optimized.append(result)
    return VideoLibraryOptimizationResult(
        optimized=tuple(optimized),
        skipped=tuple(skipped),
        failed=tuple(failed),
    )


def estimated_optimization_input_size(items) -> int:
    total = 0
    for item in items:
        if item.wallpaper_type is not WallpaperType.VIDEO:
            continue
        try:
            total += item.path.stat().st_size
        except OSError:
            continue
    return total


def configured_video_cache_dir(config: dict[str, Any]) -> Path:
    configured = str(config.get("video_optimization", {}).get("cache_dir", "")).strip()
    return Path(configured).expanduser() if configured else video_cache_dir()


def configured_video_profile(config: dict[str, Any]) -> str:
    return str(config.get("video_optimization", {}).get("profile", "balanced"))


def optimized_video_for_source(path: Path, config: dict[str, Any]) -> Path | None:
    video_config = config.get("video_optimization", {})
    if not bool(video_config.get("prefer_optimized", False)):
        return None
    profile = configured_video_profile(config)
    settings = VIDEO_OPTIMIZATION_PROFILES.get(profile)
    if settings is None:
        return None
    candidate = optimized_video_path(
        path,
        profile=profile,
        extension=str(settings["extension"]),
        cache_dir=configured_video_cache_dir(config),
    )
    metadata_path = optimized_video_metadata_path(candidate)
    if candidate.exists() and metadata_path.exists():
        return candidate
    return None


def optimized_video_path(
    path: Path,
    *,
    profile: str,
    extension: str,
    cache_dir: Path | None = None,
) -> Path:
    try:
        stat = path.stat()
        fingerprint = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{profile}"
    except OSError:
        fingerprint = f"{path}:{profile}"
    digest = sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
    return (cache_dir or video_cache_dir()) / profile / f"{path.stem}-{digest}{extension}"


def optimized_video_metadata_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.json")


def write_optimized_video_metadata(plan: VideoOptimizationPlan, path: Path) -> None:
    try:
        source_stat = plan.source.stat()
    except OSError:
        source_stat = None
    try:
        output_stat = plan.output.stat()
    except OSError:
        output_stat = None

    try:
        output_metadata = probe_video(plan.output).as_dict()
    except VideoInspectionError:
        output_metadata = None

    data = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(plan.source),
        "source_mtime_ns": source_stat.st_mtime_ns if source_stat else None,
        "source_size": source_stat.st_size if source_stat else None,
        "profile": plan.profile,
        "output": str(plan.output),
        "output_size": output_stat.st_size if output_stat else None,
        "reasons": list(plan.reasons),
        "ffmpeg_command": list(plan.ffmpeg_command),
        "source_metadata": plan.metadata.as_dict(),
        "output_metadata": output_metadata,
        "last_used_at": None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def probe_video(path: Path) -> VideoMetadata:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = result.stderr.strip() or result.stdout.strip() or "ffprobe failed"
        raise VideoInspectionError(output)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise VideoInspectionError(f"ffprobe returned invalid JSON: {error}") from error

    stream = _first_video_stream(data)
    if stream is None:
        raise VideoInspectionError("no video stream found")

    format_data = data.get("format", {})
    if not isinstance(format_data, dict):
        format_data = {}

    return VideoMetadata(
        path=path,
        codec=str(stream.get("codec_name", "unknown")),
        container=str(format_data.get("format_name", "unknown")),
        width=_optional_int(stream.get("width")),
        height=_optional_int(stream.get("height")),
        duration_seconds=_optional_float(stream.get("duration"))
        or _optional_float(format_data.get("duration")),
        size_bytes=_optional_int(format_data.get("size")),
        bit_rate=_optional_int(stream.get("bit_rate"))
        or _optional_int(format_data.get("bit_rate")),
        frame_rate=_frame_rate(stream),
    )


def video_warnings(metadata: VideoMetadata, monitors: list[Monitor]) -> list[VideoWarning]:
    warnings: list[VideoWarning] = []
    pixels = metadata.pixels
    max_monitor_pixels = _max_monitor_pixels(monitors)

    if pixels is not None and max_monitor_pixels is not None:
        if pixels > max_monitor_pixels * 1.4:
            warnings.append(
                VideoWarning(
                    "warning",
                    "video resolution is much larger than the largest active monitor",
                    f"{_resolution(metadata.width, metadata.height)} video vs "
                    f"{_resolution_from_pixels(max_monitor_pixels)} monitor pixels",
                )
            )
    elif pixels is not None and pixels >= 3840 * 2160:
        warnings.append(
            VideoWarning(
                "warning",
                "4K-or-larger video with unknown monitor setup",
                "run inside Hyprland for monitor-aware advice",
            )
        )

    if metadata.frame_rate is not None and metadata.frame_rate > 60:
        warnings.append(
            VideoWarning(
                "warning",
                "high-frame-rate video may be expensive as a wallpaper",
                f"{metadata.frame_rate:.2f} fps",
            )
        )

    if metadata.bit_rate is not None and metadata.bit_rate > 60_000_000:
        warnings.append(
            VideoWarning(
                "warning",
                "very high bitrate may cause stutter or extra power use",
                _format_bitrate(metadata.bit_rate),
            )
        )

    if metadata.codec.lower() in {"av1", "hevc", "h265"}:
        warnings.append(
            VideoWarning(
                "info",
                "codec smoothness depends heavily on hardware decode support",
                metadata.codec,
            )
        )

    return warnings


def format_video_inspection(inspection: VideoInspection) -> str:
    metadata = inspection.metadata
    lines = [
        f"file: {metadata.path}",
        f"container: {metadata.container}",
        f"codec: {metadata.codec}",
        f"resolution: {_resolution(metadata.width, metadata.height)}",
        f"duration: {_format_duration(metadata.duration_seconds)}",
        f"size: {_format_bytes(metadata.size_bytes)}",
        f"bitrate: {_format_bitrate(metadata.bit_rate)}",
        f"frame_rate: {_format_frame_rate(metadata.frame_rate)}",
    ]
    if inspection.monitors:
        lines.append("monitors:")
        for monitor in inspection.monitors:
            resolution = _resolution(monitor.width, monitor.height)
            focused = " focused" if monitor.focused else ""
            lines.append(f"  {monitor.name}: {resolution}{focused}")
    else:
        lines.append("monitors: none detected")

    if inspection.warnings:
        lines.append("warnings:")
        for warning in inspection.warnings:
            detail = f" ({warning.details})" if warning.details else ""
            lines.append(f"  [{warning.level}] {warning.message}{detail}")
    else:
        lines.append("warnings: none")
    return "\n".join(lines)


def video_inspection_json(inspection: VideoInspection) -> str:
    return json.dumps(inspection.as_dict(), indent=2, sort_keys=True)


def format_video_optimization_plan(plan: VideoOptimizationPlan) -> str:
    lines = [
        f"file: {plan.source}",
        f"profile: {plan.profile}",
        f"output: {plan.output}",
        f"already_suitable: {plan.already_suitable}",
    ]
    if plan.reasons:
        lines.append("reasons:")
        lines.extend(f"  - {reason}" for reason in plan.reasons)
    else:
        lines.append("reasons: none")
    lines.append("ffmpeg:")
    lines.append(f"  {shlex.join(plan.ffmpeg_command)}")
    return "\n".join(lines)


def video_optimization_plan_json(plan: VideoOptimizationPlan) -> str:
    return json.dumps(plan.as_dict(), indent=2, sort_keys=True)


def format_video_optimization_result(result: VideoOptimizationResult) -> str:
    if result.skipped:
        return "\n".join(
            [
                f"file: {result.plan.source}",
                f"profile: {result.plan.profile}",
                "skipped: true",
                f"message: {result.message}",
            ]
        )
    return "\n".join(
        [
            f"file: {result.plan.source}",
            f"profile: {result.plan.profile}",
            f"output: {result.output}",
            f"metadata: {result.metadata_path}",
            "skipped: false",
            f"message: {result.message}",
        ]
    )


def video_optimization_result_json(result: VideoOptimizationResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def video_library_optimization_result_json(result: VideoLibraryOptimizationResult) -> str:
    return json.dumps(result.as_dict(), indent=2, sort_keys=True)


def format_video_library_optimization_result(result: VideoLibraryOptimizationResult) -> str:
    lines = [
        f"optimized: {len(result.optimized)}",
        f"skipped: {len(result.skipped)}",
        f"failed: {len(result.failed)}",
    ]
    for item in result.optimized:
        lines.append(f"  optimized {item.output}")
    for item in result.skipped:
        lines.append(f"  skipped {item.plan.source}: {item.message}")
    for item in result.failed:
        lines.append(f"  failed {item['file']}: {item['error']}")
    return "\n".join(lines)


def _optimization_reasons(metadata: VideoMetadata, settings: dict[str, Any]) -> list[str]:
    reasons = []
    codec_names = settings["codec_names"]
    if metadata.codec.lower() not in codec_names:
        reasons.append(f"codec {metadata.codec} is not {', '.join(sorted(codec_names))}")
    if not _container_matches(metadata.container, str(settings["container"])):
        reasons.append(f"container {metadata.container} is not {settings['container']}")
    max_width = int(settings["max_width"])
    max_height = int(settings["max_height"])
    if metadata.width is not None and metadata.width > max_width:
        reasons.append(f"width {metadata.width} exceeds {max_width}")
    if metadata.height is not None and metadata.height > max_height:
        reasons.append(f"height {metadata.height} exceeds {max_height}")
    max_bit_rate = int(settings["max_bit_rate"])
    if metadata.bit_rate is not None and metadata.bit_rate > max_bit_rate:
        reasons.append(
            f"bitrate {_format_bitrate(metadata.bit_rate)} exceeds {_format_bitrate(max_bit_rate)}"
        )
    return reasons


def _optimization_profile_settings(
    profile: str,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    settings = VIDEO_OPTIMIZATION_PROFILES.get(profile)
    if settings is None:
        names = ", ".join(sorted(VIDEO_OPTIMIZATION_PROFILES))
        raise VideoInspectionError(f"unknown optimization profile: {profile} ({names})")
    merged = dict(settings)
    merged["codec_names"] = set(settings["codec_names"])
    video_config = (config or {}).get("video_optimization", {})
    if str(video_config.get("profile", profile)) == profile:
        for key in (
            "codec",
            "container",
            "extension",
            "max_width",
            "max_height",
            "max_bit_rate",
            "crf",
            "preset",
            "extra_args",
        ):
            if key in video_config:
                merged[key] = video_config[key]
        if "codec_names" in video_config:
            merged["codec_names"] = set(video_config["codec_names"])
    return merged


def _container_matches(container: str, target: str) -> bool:
    names = {name.strip().lower() for name in container.split(",")}
    if target == "mp4":
        return bool(names & {"mp4", "mov", "m4a", "3gp", "3g2", "mj2"})
    return target in names


def _ffmpeg_optimization_command(path: Path, output: Path, settings: dict[str, Any]) -> list[str]:
    scale = (
        f"scale='min({settings['max_width']},iw)':"
        f"'min({settings['max_height']},ih)':force_original_aspect_ratio=decrease"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-y",
        "-i",
        str(path),
        "-an",
        "-vf",
        scale,
        "-c:v",
        str(settings["codec"]),
        "-preset",
        str(settings["preset"]),
        "-crf",
        str(settings["crf"]),
        *_extra_ffmpeg_args(settings.get("extra_args", [])),
        str(output),
    ]


def _extra_ffmpeg_args(value: Any) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _run_ffmpeg_optimization(
    plan: VideoOptimizationPlan,
    progress_callback: Callable[[VideoOptimizationProgress], None] | None,
) -> tuple[int, str]:
    command = list(plan.ffmpeg_command)
    if progress_callback is None:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stderr.strip() or result.stdout.strip()

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None

    output_lines: list[str] = []
    progress_values: dict[str, str] = {}
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        output_lines.append(line)
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        progress_values[key] = value
        if key == "progress":
            progress_callback(_progress_from_values(progress_values, plan.metadata))

    return process.wait(), "\n".join(output_lines)


def _progress_from_values(
    values: dict[str, str],
    metadata: VideoMetadata,
) -> VideoOptimizationProgress:
    return VideoOptimizationProgress(
        out_time_seconds=_progress_out_time_seconds(values),
        duration_seconds=metadata.duration_seconds,
        total_size=_optional_int(values.get("total_size")),
        speed=values.get("speed", ""),
        progress=values.get("progress", ""),
    )


def _progress_out_time_seconds(values: dict[str, str]) -> float | None:
    for key in ("out_time_us", "out_time_ms"):
        value = _optional_int(values.get(key))
        if value is not None:
            return value / 1_000_000
    raw_time = values.get("out_time")
    if not raw_time:
        return None
    parts = raw_time.split(":")
    if len(parts) != 3:
        return None
    try:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return None
    return (hours * 3600) + (minutes * 60) + seconds


def _first_video_stream(data: dict[str, Any]) -> dict[str, Any] | None:
    streams = data.get("streams", [])
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            return stream
    return None


def _frame_rate(stream: dict[str, Any]) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if not value or value == "0/0":
            continue
        try:
            return float(Fraction(str(value)))
        except (ValueError, ZeroDivisionError):
            continue
    return None


def _max_monitor_pixels(monitors: list[Monitor]) -> int | None:
    values = [
        monitor.width * monitor.height
        for monitor in monitors
        if monitor.width is not None and monitor.height is not None
    ]
    return max(values) if values else None


def _resolution(width: int | None, height: int | None) -> str:
    if width is None or height is None:
        return "unknown"
    return f"{width}x{height}"


def _resolution_from_pixels(pixels: int) -> str:
    return f"{pixels:,} px"


def _format_duration(value: float | None) -> str:
    if value is None:
        return "unknown"
    minutes, seconds = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{int(hours)}:{int(minutes):02d}:{seconds:05.2f}"
    return f"{int(minutes)}:{seconds:05.2f}"


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _format_bitrate(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value / 1_000_000:.2f} Mbps"


def _format_frame_rate(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f} fps"


def _optional_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
