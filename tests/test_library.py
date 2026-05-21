from pathlib import Path

from wallmux.core.library import filter_wallpapers, scan_wallpaper_dir
from wallmux.core.mime import WallpaperType


def test_scan_wallpaper_dir_returns_supported_files(tmp_path: Path) -> None:
    image = tmp_path / "one.png"
    video = tmp_path / "two.mp4"
    ignored = tmp_path / "notes.txt"
    image.write_bytes(b"")
    video.write_bytes(b"")
    ignored.write_text("nope", encoding="utf-8")

    items = scan_wallpaper_dir(tmp_path)

    assert [item.path for item in items] == [image, video]
    assert [item.backend for item in items] == ["awww", "mpvpaper"]


def test_filter_wallpapers_by_query_and_type(tmp_path: Path) -> None:
    image = tmp_path / "forest.png"
    video = tmp_path / "forest-loop.mp4"
    image.write_bytes(b"")
    video.write_bytes(b"")
    items = scan_wallpaper_dir(tmp_path)

    filtered = filter_wallpapers(
        items,
        query="loop",
        wallpaper_type=WallpaperType.VIDEO,
    )

    assert [item.path for item in filtered] == [video]
