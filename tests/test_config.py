from pathlib import Path

from wallmux.core.config import load_config, reconcile_config


def test_loads_default_config(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")
    assert config["backend_rules"]["image"] == "awww"
    assert config["backend_rules"]["video"] == "mpvpaper"


def test_creates_missing_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    config = load_config(config_path)

    assert config_path.exists()
    assert config["backend_rules"]["image"] == "awww"


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
