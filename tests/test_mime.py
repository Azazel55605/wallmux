from pathlib import Path

from wallmux.core.mime import WallpaperType, detect_wallpaper_type


def test_detects_image_from_extension_when_file_is_missing() -> None:
    assert detect_wallpaper_type(Path("wallpaper.png")) is WallpaperType.IMAGE


def test_detects_gif_separately_from_images() -> None:
    assert detect_wallpaper_type(Path("animated.gif")) is WallpaperType.GIF


def test_detects_video_from_extension_when_file_is_missing() -> None:
    assert detect_wallpaper_type(Path("clip.webm")) is WallpaperType.VIDEO


def test_unknown_file_type() -> None:
    assert detect_wallpaper_type(Path("notes.txt")) is WallpaperType.UNKNOWN
