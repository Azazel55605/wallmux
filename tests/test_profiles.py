from __future__ import annotations

from pathlib import Path

from wallmux.core.autoswitch import load_wallpaper_library
from wallmux.core.config import load_config, write_config
from wallmux.core.profiles import (
    effective_config_for_profile,
    find_profile,
    format_profile_hook,
    get_active_profile,
    list_profiles,
    profile_entries_from_category_root,
    run_profile_hooks,
    switch_profile,
)


def test_lists_profiles_with_category_labels(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")
    config["profiles"]["entries"] = [
        {
            "name": "landscape",
            "category": "orange",
            "subcategory": "mountains",
            "color": "#e27c00",
            "wallpaper_dirs": [str(tmp_path)],
        }
    ]

    profiles = list_profiles(config)

    assert profiles[0].label == "orange / mountains / landscape"
    assert profiles[0].color == "#e27c00"


def test_effective_config_uses_active_profile(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.toml")
    profile_dir = tmp_path / "orange"
    config["profiles"] = {
        "active": "landscape",
        "active_category": "orange",
        "active_subcategory": "",
        "entries": [
            {
                "name": "landscape",
                "category": "orange",
                "wallpaper_dirs": [str(profile_dir)],
                "backend_rules": {"image": "swww"},
                "autoswitch_mode": "name-up",
            }
        ],
    }

    effective = effective_config_for_profile(config)

    assert effective["general"]["wallpaper_dirs"] == [str(profile_dir)]
    assert effective["backend_rules"]["image"] == "swww"
    assert effective["autoswitch"]["mode"] == "name-up"


def test_switch_profile_persists_active_category(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    config["profiles"]["entries"] = [
        {
            "name": "landscape",
            "category": "orange",
            "subcategory": "city",
            "wallpaper_dirs": [str(tmp_path)],
        }
    ]
    write_config(config, config_path)

    profile = switch_profile(
        "landscape",
        category="orange",
        subcategory="city",
        config_path=config_path,
    )
    loaded = load_config(config_path)

    assert profile.label == "orange / city / landscape"
    assert get_active_profile(loaded) == profile


def test_switch_profile_runs_after_write_before_after_hooks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    config_path = tmp_path / "config.toml"
    config = load_config(config_path)
    config["profiles"]["entries"] = [
        {
            "name": "green",
            "after_switch": ["after {profile}"],
        }
    ]
    write_config(config, config_path)
    monkeypatch.setattr("wallmux.core.profiles.subprocess.run", run)

    switch_profile(
        "green",
        config_path=config_path,
        after_write=lambda profile: calls.append(f"reload {profile.name}"),
    )

    assert calls == ["reload green", "after green"]


def test_profile_filters_wallpaper_library(tmp_path: Path) -> None:
    warm = tmp_path / "warm"
    warm.mkdir()
    (warm / "orange.png").write_bytes(b"")
    (warm / "blue.mp4").write_bytes(b"")
    config = load_config(tmp_path / "config.toml")
    config["profiles"] = {
        "active": "landscape",
        "active_category": "orange",
        "active_subcategory": "",
        "entries": [
            {
                "name": "landscape",
                "category": "orange",
                "wallpaper_dirs": [str(warm)],
                "filter_query": "orange",
                "filter_types": ["image"],
            }
        ],
    }

    items = load_wallpaper_library(config)

    assert [item.path.name for item in items] == ["orange.png"]


def test_profile_hook_rejects_unknown_placeholder() -> None:
    try:
        format_profile_hook("echo {unknown}", {})
    except ValueError as error:
        assert "unsupported profile hook placeholder" in str(error)
    else:
        raise AssertionError("expected unsupported placeholder error")


def test_profile_entries_from_category_root(tmp_path: Path) -> None:
    green = tmp_path / "green"
    (green / "Anime").mkdir(parents=True)
    (green / "Landscape").mkdir()
    (green / "note.txt").write_text("ignore", encoding="utf-8")

    entries = profile_entries_from_category_root(green)

    assert [entry["name"] for entry in entries] == ["green", "Anime", "Landscape"]
    assert entries[0]["category"] == ""
    assert entries[0]["wallpaper_dirs"] == [str(green)]
    assert {entry["category"] for entry in entries[1:]} == {"green"}
    assert entries[1]["wallpaper_dirs"] == [str(green / "Anime")]


def test_imported_subcategory_label_avoids_duplicate_name() -> None:
    config = {
        "profiles": {
            "entries": [
                {
                    "name": "Anime",
                    "category": "green",
                    "subcategory": "Anime",
                }
            ]
        }
    }

    assert list_profiles(config)[0].label == "green / Anime"


def test_profile_hooks_can_include_parent_hooks(monkeypatch) -> None:
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("wallmux.core.profiles.subprocess.run", run)
    config = {
        "hooks": {"timeout_seconds": 30},
        "profiles": {
            "entries": [
                {
                    "name": "green",
                    "before_switch": ["parent {profile}"],
                },
                {
                    "name": "Anime",
                    "category": "green",
                    "subcategory": "Anime",
                    "before_switch": ["child {profile}"],
                    "include_parent_hooks": True,
                },
            ]
        },
    }
    child = find_profile(config, name="Anime", category="green")
    assert child is not None

    run_profile_hooks("before_switch", config, child)

    assert calls == ["parent green", "child Anime"]


def test_profile_hooks_include_global_hooks_in_switch_order(monkeypatch) -> None:
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("wallmux.core.profiles.subprocess.run", run)
    config = {
        "hooks": {"timeout_seconds": 30},
        "profiles": {
            "before_switch": ["global-before {profile}"],
            "after_switch": ["global-after {profile}"],
            "entries": [
                {
                    "name": "green",
                    "before_switch": ["profile-before {profile}"],
                    "after_switch": ["profile-after {profile}"],
                },
            ],
        },
    }
    profile = find_profile(config, name="green")
    assert profile is not None

    run_profile_hooks("before_switch", config, profile)
    run_profile_hooks("after_switch", config, profile)

    assert calls == [
        "global-before green",
        "profile-before green",
        "profile-after green",
        "global-after green",
    ]


def test_profile_hooks_export_profile_environment(monkeypatch) -> None:
    envs = []

    def run(_command, **kwargs):
        envs.append(kwargs["env"])
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("wallmux.core.profiles.subprocess.run", run)
    config = {
        "hooks": {"timeout_seconds": 30},
        "profiles": {
            "entries": [
                {
                    "name": "Anime",
                    "category": "green",
                    "subcategory": "Anime",
                    "after_switch": ["theme-hook"],
                    "wallpaper_dirs": ["/wallpapers/green/Anime"],
                },
            ]
        },
    }
    profile = find_profile(config, name="Anime", category="green")
    assert profile is not None

    run_profile_hooks("after_switch", config, profile)

    assert envs[0]["WALLMUX_PROFILE_NAME"] == "Anime"
    assert envs[0]["WALLMUX_PROFILE"] == "Anime"
    assert envs[0]["WALLMUX_PROFILE_CATEGORY"] == "green"
    assert envs[0]["WALLMUX_PROFILE_SUBCATEGORY"] == "Anime"
    assert envs[0]["WALLMUX_PROFILE_COLOR"] == ""
    assert envs[0]["WALLMUX_PROFILE_LABEL"] == "green / Anime"
    assert envs[0]["WALLMUX_PROFILE_WALLPAPER_DIRS"] == "/wallpapers/green/Anime"
