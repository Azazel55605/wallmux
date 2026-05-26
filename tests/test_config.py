import tomllib
from pathlib import Path

from wallmux.core.config import (
    load_config,
    profiles_file_for_config,
    reconcile_config,
    write_config,
    write_profiles_config,
)


def test_loads_default_config(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")
    assert config["backend_rules"]["image"] == "awww"
    assert config["backend_rules"]["video"] == "mpvpaper"


def test_creates_missing_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    config = load_config(config_path)

    assert config_path.exists()
    assert profiles_file_for_config(config_path).exists()
    assert config["backend_rules"]["image"] == "awww"
    assert config["profiles"] == {
        "active": "",
        "active_category": "",
        "active_subcategory": "",
        "entries": [],
    }


def test_reconcile_keeps_user_values_and_adds_new_defaults() -> None:
    default_config = {
        "general": {
            "thumbnail_size": 256,
            "restore_on_startup": True,
        },
        "backend_rules": {
            "image": "awww",
            "video": "mpvpaper",
        },
    }
    user_config = {
        "general": {
            "thumbnail_size": 512,
        },
        "backend_rules": {
            "image": "swww",
        },
    }

    config = reconcile_config(default_config, user_config)

    assert config["general"]["thumbnail_size"] == 512
    assert config["general"]["restore_on_startup"] is True
    assert config["backend_rules"]["image"] == "swww"
    assert config["backend_rules"]["video"] == "mpvpaper"


def test_reconcile_removes_keys_removed_from_defaults() -> None:
    default_config = {
        "general": {
            "thumbnail_size": 256,
        },
    }
    user_config = {
        "general": {
            "thumbnail_size": 512,
            "old_value": "remove me",
        },
        "old_section": {
            "enabled": True,
        },
    }

    config = reconcile_config(default_config, user_config)

    assert config == {"general": {"thumbnail_size": 512}}


def test_load_config_writes_reconciled_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[general]
thumbnail_size = 512
old_value = "remove me"

[backend_rules]
image = "swww"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    written = config_path.read_text(encoding="utf-8")

    assert config["general"]["thumbnail_size"] == 512
    assert config["backend_rules"]["image"] == "swww"
    assert "old_value" not in written
    assert "video" in written


def test_load_config_migrates_old_mpvpaper_default_options(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[backends.mpvpaper]
command = "mpvpaper"
options = "no-audio loop hwdec=auto"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["backends"]["mpvpaper"]["options"].startswith("no-config no-audio")


def test_load_config_migrates_video_optimization_to_auto_cache_default(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[video_optimization]
enabled = true
prefer_optimized = false
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config["video_optimization"]["auto_optimize"] is True
    assert config["video_optimization"]["prefer_optimized"] is True


def test_load_config_migrates_inline_profiles_to_profile_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[profiles]
active = "green"
active_category = ""
active_subcategory = ""

[[profiles.entries]]
name = "green"
wallpaper_dirs = ["/wallpapers/green"]
before_switch = ["echo before"]
after_switch = ["echo after"]
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    written_config = config_path.read_text(encoding="utf-8")
    profiles_path = profiles_file_for_config(config_path)
    written_profiles = tomllib.loads(profiles_path.read_text(encoding="utf-8"))

    assert "[profiles]" not in written_config
    assert config["profiles"]["active"] == "green"
    assert config["profiles"]["entries"][0]["name"] == "green"
    assert written_profiles["entries"][0]["before_switch"] == ["echo before"]


def test_write_config_splits_profiles_to_profile_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    config["profiles"]["active"] = "orange"
    config["profiles"]["entries"] = [
        {
            "name": "orange",
            "wallpaper_dirs": ["/wallpapers/orange"],
            "after_switch": ["echo orange"],
        }
    ]

    write_config(config, config_path)

    written_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    written_profiles = tomllib.loads(
        profiles_file_for_config(config_path).read_text(encoding="utf-8")
    )
    assert "profiles" not in written_config
    assert written_profiles["active"] == "orange"
    assert written_profiles["entries"][0]["after_switch"] == ["echo orange"]
    assert written_profiles["entries"][0]["color"] == ""


def test_write_profiles_config_reconciles_profile_entry_defaults(tmp_path: Path) -> None:
    profiles_path = tmp_path / "wallmux-profiles.toml"

    write_profiles_config(
        {
            "active": "",
            "active_category": "",
            "active_subcategory": "",
            "entries": [
                {
                    "name": "blue",
                    "wallpaper_dirs": ["/wallpapers/blue"],
                }
            ],
        },
        profiles_path,
    )

    written_profiles = tomllib.loads(profiles_path.read_text(encoding="utf-8"))

    assert written_profiles["entries"][0]["color"] == ""
