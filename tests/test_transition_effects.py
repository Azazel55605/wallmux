from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from wallmux.core.state import WallpaperEntry
from wallmux.core.transition_effects import TransitionContext, run_transition_stage
from wallmux.core.transitions import TransitionKind


def test_runs_configured_transition_effects(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def run(command, **kwargs):
        calls.append(command)

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr("wallmux.core.transition_effects.subprocess.run", run)
    config = {
        "transitions": {
            "effects": {
                "fade_overlay": True,
                "fade_command": "fade {monitor} {transition}",
                "screenshot_bridge": True,
                "screenshot_command": "shot {from_file} {to_file}",
                "quickshell_overlay": True,
                "quickshell_command": "qs {stage} {to_backend}",
                "timeout_seconds": 1.0,
            }
        }
    }
    context = TransitionContext(
        monitor="DP-1",
        to_file=tmp_path / "next.mp4",
        to_backend="mpvpaper",
        transition=TransitionKind.IMAGE_TO_VIDEO,
        previous=WallpaperEntry(file="/tmp/old.png", backend="awww", wallpaper_type="image"),
    )

    logger = Mock()
    run_transition_stage("before", config, context, logger=logger)
    run_transition_stage("after", config, context, logger=logger)

    assert calls == [
        f"shot /tmp/old.png {tmp_path / 'next.mp4'}",
        "qs before mpvpaper",
        "fade DP-1 image_to_video",
    ]


def test_transition_effects_are_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "wallmux.core.transition_effects.subprocess.run",
        lambda command, **kwargs: calls.append(command),
    )
    context = TransitionContext(
        monitor="DP-1",
        to_file=tmp_path / "next.png",
        to_backend="awww",
        transition=TransitionKind.IMAGE_TO_IMAGE,
    )

    run_transition_stage("before", {"transitions": {}}, context)
    run_transition_stage("after", {"transitions": {}}, context)

    assert calls == []
