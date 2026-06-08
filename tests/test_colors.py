from pathlib import Path

import pytest

from wallmux.core.colors import ColorSourceError, current_color_source
from wallmux.core.monitors import Monitor
from wallmux.core.state import WallmuxState, WallpaperEntry, save_state


def test_color_source_uses_first_hyprland_monitor(tmp_path: Path) -> None:
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"image")
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={
                "DP-1": WallpaperEntry(str(image), "awww", "image"),
                "HDMI-A-1": WallpaperEntry("/missing.png", "swww", "image"),
            }
        ),
        state_path,
    )

    source = current_color_source(
        state_path=state_path,
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1")],
    )

    assert source == image.resolve()


def test_color_source_uses_requested_monitor(tmp_path: Path) -> None:
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"image")
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={"eDP-1": WallpaperEntry(str(image), "hyprpaper", "image")}
        ),
        state_path,
    )

    source = current_color_source(
        "eDP-1",
        state_path=state_path,
        monitor_provider=lambda: [],
    )

    assert source == image.resolve()


def test_color_source_uses_video_thumbnail(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "wallpaper.mp4"
    thumbnail = tmp_path / "thumbnail.jpg"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"image")
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={"DP-1": WallpaperEntry(str(video), "mpvpaper", "video")}
        ),
        state_path,
    )
    monkeypatch.setattr(
        "wallmux.core.colors.ensure_thumbnail",
        lambda *_args, **_kwargs: thumbnail,
    )

    source = current_color_source(
        "DP-1",
        config={"general": {"thumbnail_size": 512}},
        state_path=state_path,
    )

    assert source == thumbnail.resolve()


def test_color_source_errors_when_monitor_has_no_state(tmp_path: Path) -> None:
    with pytest.raises(ColorSourceError, match="no wallpaper state"):
        current_color_source(
            "DP-1",
            state_path=tmp_path / "state.json",
        )
