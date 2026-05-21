from __future__ import annotations

import logging
from pathlib import Path

from wallmux.core.hooks import HookContext, build_hook_values, format_hook, run_hook_stage
from wallmux.core.mime import WallpaperType


class CaptureLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, message, *args) -> None:
        self.messages.append(message % args)


def test_format_hook_rejects_unknown_placeholder() -> None:
    try:
        format_hook("echo {nope}", {})
    except ValueError as error:
        assert "unsupported hook placeholder" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_build_hook_values_uses_image_as_color_source(tmp_path: Path) -> None:
    image = tmp_path / "wall.png"
    image.write_bytes(b"")
    context = HookContext(
        file=image,
        monitor="DP-1",
        backend="awww",
        wallpaper_type=WallpaperType.IMAGE,
    )

    values = build_hook_values({}, context)

    assert values["file"] == str(image)
    assert values["source_for_colors"] == str(image)
    assert values["basename"] == "wall.png"


def test_build_hook_values_uses_video_thumbnail_as_color_source(tmp_path: Path) -> None:
    video = tmp_path / "wall.mp4"
    thumbnail = tmp_path / "thumb.jpg"
    video.write_bytes(b"")
    thumbnail.write_bytes(b"")
    context = HookContext(
        file=video,
        monitor="DP-1",
        backend="mpvpaper",
        wallpaper_type=WallpaperType.VIDEO,
        thumbnail=thumbnail,
    )

    values = build_hook_values({}, context)

    assert values["thumbnail"] == str(thumbnail)
    assert values["source_for_colors"] == str(thumbnail)


def test_run_hook_stage_logs_failure(tmp_path: Path) -> None:
    logger = CaptureLogger()
    context = HookContext(
        file=tmp_path / "wall.png",
        monitor="DP-1",
        backend="awww",
        wallpaper_type=WallpaperType.IMAGE,
    )
    config = {
        "hooks": {
            "after_set": ["python -c 'import sys; sys.exit(3)'"],
            "timeout_seconds": 5,
        }
    }

    run_hook_stage("after_set", config, context, logger=logger)  # type: ignore[arg-type]

    assert logger.messages
    assert "after_set hook exited 3" in logger.messages[0]


def test_run_hook_stage_honors_backend_disable(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.WARNING)
    context = HookContext(
        file=tmp_path / "wall.png",
        monitor="DP-1",
        backend="awww",
        wallpaper_type=WallpaperType.IMAGE,
    )
    config = {
        "hooks": {
            "after_set": ["python -c 'import sys; sys.exit(3)'"],
            "backends": {"awww": False},
            "timeout_seconds": 5,
        }
    }

    run_hook_stage("after_set", config, context)

    assert not caplog.records
