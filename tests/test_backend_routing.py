import pytest

from wallmux.backends.routing import compatible_backends, route_wallpaper
from wallmux.core.mime import WallpaperType


def test_routes_images_to_awww() -> None:
    assert route_wallpaper(WallpaperType.IMAGE) == "awww"
    assert "hyprpaper" in compatible_backends(WallpaperType.IMAGE)


def test_routes_gifs_to_awww() -> None:
    assert route_wallpaper(WallpaperType.GIF) == "awww"


def test_routes_videos_to_mpvpaper() -> None:
    assert route_wallpaper(WallpaperType.VIDEO) == "mpvpaper"


def test_rejects_unknown_wallpaper_type() -> None:
    with pytest.raises(ValueError):
        route_wallpaper(WallpaperType.UNKNOWN)
