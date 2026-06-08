from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wallmux.core.library import WallpaperItem
from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import Monitor
from wallmux.core.video import (
    VideoInspectionError,
    estimated_optimization_input_size,
    inspect_video,
    optimize_video,
    optimize_video_library,
    optimized_video_path,
    plan_video_optimization,
    probe_video,
    video_warnings,
)


def test_probe_video_reads_primary_stream(monkeypatch) -> None:
    def run(command: list[str], **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "audio",
                            "codec_name": "aac",
                        },
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 3840,
                            "height": 2160,
                            "duration": "20.5",
                            "avg_frame_rate": "30000/1001",
                            "bit_rate": "48000000",
                        },
                    ],
                    "format": {
                        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                        "size": "123456789",
                        "duration": "21.0",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("wallmux.core.video.subprocess.run", run)

    metadata = probe_video(Path("wallpaper.mp4"))

    assert metadata.codec == "h264"
    assert metadata.width == 3840
    assert metadata.height == 2160
    assert metadata.duration_seconds == 20.5
    assert metadata.size_bytes == 123456789
    assert metadata.frame_rate == pytest.approx(29.97, rel=0.001)


def test_probe_video_raises_for_missing_video_stream(monkeypatch) -> None:
    def run(command: list[str], **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"streams": [{"codec_type": "audio"}], "format": {}}),
            stderr="",
        )

    monkeypatch.setattr("wallmux.core.video.subprocess.run", run)

    with pytest.raises(VideoInspectionError, match="no video stream"):
        probe_video(Path("audio-only.mp4"))


def test_video_warnings_flag_oversized_video_for_monitor() -> None:
    metadata = probe_video_from_data(width=3840, height=2160, bit_rate=80_000_000)

    warnings = video_warnings(metadata, [Monitor("eDP-1", width=1920, height=1080)])

    assert any("larger than the largest active monitor" in warning.message for warning in warnings)
    assert any("very high bitrate" in warning.message for warning in warnings)


def test_inspect_video_includes_passed_monitor_context(monkeypatch) -> None:
    def run(command: list[str], **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "hevc",
                            "width": 2560,
                            "height": 1600,
                            "avg_frame_rate": "60/1",
                        }
                    ],
                    "format": {"format_name": "matroska,webm", "size": "42"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("wallmux.core.video.subprocess.run", run)

    inspection = inspect_video(
        Path("clip.mkv"),
        monitors=[Monitor("eDP-1", focused=True, width=2560, height=1600)],
    )

    assert inspection.metadata.codec == "hevc"
    assert inspection.monitors[0].name == "eDP-1"
    assert any("hardware decode" in warning.message for warning in inspection.warnings)


def test_plan_video_optimization_detects_suitable_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"video")

    monkeypatch.setattr(
        "wallmux.core.video.probe_video",
        lambda path: probe_video_from_data(
            path=path,
            codec="h264",
            container="mov,mp4,m4a,3gp,3g2,mj2",
            width=1920,
            height=1080,
            bit_rate=20_000_000,
        ),
    )

    plan = plan_video_optimization(source, profile="compatibility", cache_dir=tmp_path)

    assert plan.already_suitable is True
    assert plan.reasons == ()
    assert plan.output.parent == tmp_path / "compatibility"


def test_plan_video_optimization_explains_transcode_reasons(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "wallpaper.mkv"
    source.write_bytes(b"video")

    monkeypatch.setattr(
        "wallmux.core.video.probe_video",
        lambda path: probe_video_from_data(
            path=path,
            codec="hevc",
            container="matroska,webm",
            width=3840,
            height=2160,
            bit_rate=90_000_000,
        ),
    )

    plan = plan_video_optimization(source, profile="balanced", cache_dir=tmp_path)

    assert plan.already_suitable is False
    assert any("codec hevc" in reason for reason in plan.reasons)
    assert any("container matroska,webm" in reason for reason in plan.reasons)
    assert any("width 3840" in reason for reason in plan.reasons)
    assert any("height 2160" in reason for reason in plan.reasons)
    assert any("bitrate" in reason for reason in plan.reasons)
    assert "-c:v" in plan.ffmpeg_command
    assert "libx264" in plan.ffmpeg_command


def test_loop_friendly_optimization_adds_seek_friendly_encoding_flags(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        "wallmux.core.video.probe_video",
        lambda path: probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=1920,
            height=1080,
            bit_rate=20_000_000,
        ),
    )
    config = {
        "video_optimization": {
            "profile": "balanced",
            "loop_friendly": True,
            "loop_gop_size": 48,
        }
    }

    plan = plan_video_optimization(
        source,
        profile="balanced",
        cache_dir=tmp_path,
        config=config,
    )

    assert plan.already_suitable is False
    assert "loop-friendly derivative requested" in plan.reasons
    for option in ("-bf", "-g", "-fps_mode", "-keyint_min", "-sc_threshold", "-x264-params"):
        assert option in plan.ffmpeg_command
    assert plan.ffmpeg_command[plan.ffmpeg_command.index("-g") + 1] == "48"
    assert plan.ffmpeg_command[plan.ffmpeg_command.index("-bf") + 1] == "0"


def test_optimized_video_path_changes_with_optimization_settings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(
        "wallmux.core.video.probe_video",
        lambda path: probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=1920,
            height=1080,
            bit_rate=20_000_000,
        ),
    )

    regular = plan_video_optimization(
        source,
        profile="balanced",
        cache_dir=tmp_path,
        config={"video_optimization": {"profile": "balanced", "loop_friendly": False}},
    )
    loop_friendly = plan_video_optimization(
        source,
        profile="balanced",
        cache_dir=tmp_path,
        config={"video_optimization": {"profile": "balanced", "loop_friendly": True}},
    )

    assert regular.output != loop_friendly.output


def test_optimized_video_path_changes_when_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"one")
    first = optimized_video_path(
        source,
        profile="balanced",
        extension=".mp4",
        cache_dir=tmp_path,
    )

    source.write_bytes(b"two")
    second = optimized_video_path(
        source,
        profile="balanced",
        extension=".mp4",
        cache_dir=tmp_path,
    )

    assert first != second


def test_optimize_video_skips_suitable_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "wallpaper.mp4"
    source.write_bytes(b"video")
    calls = []

    monkeypatch.setattr(
        "wallmux.core.video.probe_video",
        lambda path: probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=1920,
            height=1080,
            bit_rate=20_000_000,
        ),
    )
    monkeypatch.setattr(
        "wallmux.core.video.subprocess.run",
        lambda command, **_kwargs: calls.append(command),
    )

    result = optimize_video(source, profile="compatibility", cache_dir=tmp_path)

    assert result.skipped is True
    assert result.output == source
    assert result.metadata_path is None
    assert calls == []


def test_optimize_video_runs_ffmpeg_and_writes_metadata(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "wallpaper.mkv"
    source.write_bytes(b"source")
    commands = []

    def probe(path: Path):
        if path == source:
            return probe_video_from_data(
                path=path,
                codec="hevc",
                container="matroska,webm",
                width=3840,
                height=2160,
                bit_rate=90_000_000,
            )
        return probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=2560,
            height=1440,
            bit_rate=30_000_000,
        )

    def run(command: list[str], **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"optimized")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("wallmux.core.video.probe_video", probe)
    monkeypatch.setattr("wallmux.core.video.subprocess.run", run)

    result = optimize_video(source, profile="balanced", cache_dir=tmp_path)

    assert result.skipped is False
    assert result.output.exists()
    assert result.metadata_path is not None
    assert result.metadata_path.exists()
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source"] == str(source)
    assert metadata["profile"] == "balanced"
    assert metadata["output"] == str(result.output)
    assert metadata["source_metadata"]["codec"] == "hevc"
    assert metadata["output_metadata"]["codec"] == "h264"
    assert commands[0] == list(result.plan.ffmpeg_command)


def test_optimize_video_reports_ffmpeg_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "wallpaper.mkv"
    source.write_bytes(b"source")
    events = []

    def probe(path: Path):
        if path == source:
            return probe_video_from_data(
                path=path,
                codec="hevc",
                container="matroska,webm",
                width=3840,
                height=2160,
                bit_rate=90_000_000,
                duration_seconds=10.0,
            )
        return probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=2560,
            height=1440,
            bit_rate=30_000_000,
            duration_seconds=10.0,
        )

    class Process:
        def __init__(self, command: list[str], **_kwargs) -> None:
            Path(command[-1]).write_bytes(b"optimized")
            self.stdout = iter(
                [
                    "out_time_us=5000000\n",
                    "total_size=1048576\n",
                    "speed=2.0x\n",
                    "progress=continue\n",
                    "out_time_us=10000000\n",
                    "total_size=2097152\n",
                    "speed=2.4x\n",
                    "progress=end\n",
                ]
            )

        def wait(self) -> int:
            return 0

    monkeypatch.setattr("wallmux.core.video.probe_video", probe)
    monkeypatch.setattr("wallmux.core.video.subprocess.Popen", Process)

    result = optimize_video(
        source,
        profile="balanced",
        cache_dir=tmp_path,
        progress_callback=events.append,
    )

    assert result.skipped is False
    assert [event.progress for event in events] == ["continue", "end"]
    assert events[0].percent == pytest.approx(50.0)
    assert events[0].total_size == 1048576
    assert events[1].percent == pytest.approx(100.0)


def test_optimize_video_library_collects_results(monkeypatch, tmp_path: Path) -> None:
    heavy = tmp_path / "heavy.mkv"
    suitable = tmp_path / "suitable.mp4"
    image = tmp_path / "image.png"
    heavy.write_bytes(b"heavy")
    suitable.write_bytes(b"suitable")
    image.write_bytes(b"image")

    def probe(path: Path):
        if path == heavy:
            return probe_video_from_data(
                path=path,
                codec="hevc",
                container="matroska,webm",
                width=3840,
                height=2160,
                bit_rate=90_000_000,
            )
        return probe_video_from_data(
            path=path,
            codec="h264",
            container="mp4",
            width=1920,
            height=1080,
            bit_rate=20_000_000,
        )

    def run(command: list[str], **_kwargs):
        Path(command[-1]).write_bytes(b"optimized")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("wallmux.core.video.probe_video", probe)
    monkeypatch.setattr("wallmux.core.video.subprocess.run", run)

    result = optimize_video_library(
        [
            WallpaperItem(heavy, WallpaperType.VIDEO, "mpvpaper"),
            WallpaperItem(suitable, WallpaperType.VIDEO, "mpvpaper"),
            WallpaperItem(image, WallpaperType.IMAGE, "awww"),
        ],
        profile="compatibility",
        cache_dir=tmp_path,
    )

    assert len(result.optimized) == 1
    assert len(result.skipped) == 1
    assert result.failed == ()


def test_estimated_optimization_input_size_counts_videos_only(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    image = tmp_path / "image.png"
    video.write_bytes(b"video")
    image.write_bytes(b"image")

    assert (
        estimated_optimization_input_size(
            [
                WallpaperItem(video, WallpaperType.VIDEO, "mpvpaper"),
                WallpaperItem(image, WallpaperType.IMAGE, "awww"),
            ]
        )
        == 5
    )


def probe_video_from_data(
    *,
    width: int,
    height: int,
    path: Path = Path("wallpaper.mp4"),
    codec: str = "h264",
    container: str = "mp4",
    bit_rate: int | None = None,
    duration_seconds: float | None = 10.0,
):
    from wallmux.core.video import VideoMetadata

    return VideoMetadata(
        path=path,
        codec=codec,
        container=container,
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        size_bytes=100,
        bit_rate=bit_rate,
        frame_rate=30.0,
    )
