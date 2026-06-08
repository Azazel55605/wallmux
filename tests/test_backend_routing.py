from pathlib import Path

import pytest

from wallmux.backends.routing import (
    build_backend,
    compatible_backends,
    fallback_backends,
    route_wallpaper,
)
from wallmux.core.mime import WallpaperType


def test_routes_images_to_awww() -> None:
    assert route_wallpaper(WallpaperType.IMAGE) == "awww"
    assert "hyprpaper" in compatible_backends(WallpaperType.IMAGE)


def test_routes_gifs_to_awww() -> None:
    assert route_wallpaper(WallpaperType.GIF) == "awww"


def test_routes_videos_to_mpvpaper() -> None:
    assert route_wallpaper(WallpaperType.VIDEO) == "mpvpaper"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("automatic", "hwdec=auto-safe"),
        ("software", "hwdec=no"),
        ("hardware", "hwdec=auto"),
    ],
)
def test_mpvpaper_hardware_decoding_mode(mode: str, expected: str) -> None:
    backend = build_backend(
        "mpvpaper",
        {
            "backends": {
                "mpvpaper": {
                    "options": "no-audio hwdec=old loop-file=inf",
                    "hardware_decoding": mode,
                }
            }
        },
    )

    command = backend.build_set_command(Path("/tmp/video.mp4"), "DP-1")

    assert expected in command[2]
    assert "hwdec=old" not in command[2]


def test_default_image_fallback_is_awww_to_swww() -> None:
    assert fallback_backends("awww", WallpaperType.IMAGE, {}) == ("swww",)


def test_fallbacks_ignore_incompatible_backends() -> None:
    config = {"backend_fallbacks": {"awww": ["mpvpaper", "swww", "swww"]}}

    assert fallback_backends("awww", WallpaperType.IMAGE, config) == ("swww",)


def test_rejects_unknown_wallpaper_type() -> None:
    with pytest.raises(ValueError):
        route_wallpaper(WallpaperType.UNKNOWN)
