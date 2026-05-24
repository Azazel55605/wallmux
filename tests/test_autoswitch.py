from __future__ import annotations

from pathlib import Path

from wallmux.core.autoswitch import choose_wallpaper, load_wallpaper_library
from wallmux.core.config import load_config


def test_choose_wallpaper_by_name_up_and_down(tmp_path: Path) -> None:
    one = tmp_path / "a.png"
    two = tmp_path / "b.png"
    three = tmp_path / "c.png"
    for path in (one, two, three):
        path.write_bytes(b"")
    config = load_config(tmp_path / "config.toml")
    config["general"]["wallpaper_dirs"] = [str(tmp_path)]
    items = load_wallpaper_library(config)

    assert choose_wallpaper(items, mode="name-up", current_file=str(two)).path == three
    assert choose_wallpaper(items, mode="name-down", current_file=str(two)).path == one
    assert choose_wallpaper(items, mode="name-up", current_file=str(three)).path == one


def test_choose_wallpaper_random_avoids_current_when_possible(tmp_path: Path, monkeypatch) -> None:
    one = tmp_path / "a.png"
    two = tmp_path / "b.png"
    for path in (one, two):
        path.write_bytes(b"")
    config = load_config(tmp_path / "config.toml")
    config["general"]["wallpaper_dirs"] = [str(tmp_path)]
    items = load_wallpaper_library(config)
    monkeypatch.setattr("wallmux.core.autoswitch.random.choice", lambda candidates: candidates[0])

    selected = choose_wallpaper(items, mode="random", current_file=str(one))

    assert selected.path == two
