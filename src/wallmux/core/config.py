"""Configuration loading for Wallmux."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

try:
    import tomli_w
except ImportError:
    tomli_w = None

APP_NAME = "wallmux"
DEFAULT_CONFIG_RESOURCE = "wallmux.data.default.toml"
OLD_MPV_DEFAULT_OPTIONS = "no-audio loop hwdec=auto"
PROFILES_CONFIG_NAME = "wallmux-profiles.toml"
DEFAULT_PROFILES_CONFIG: dict[str, Any] = {
    "active": "",
    "active_category": "",
    "active_subcategory": "",
    "entries": [],
}
PROFILE_ENTRY_DEFAULT: dict[str, Any] = {
    "name": "",
    "category": "",
    "subcategory": "",
    "color": "",
    "wallpaper_dirs": [],
    "backend_rules": {},
    "autoswitch_mode": "",
    "filter_query": "",
    "filter_types": [],
    "before_switch": [],
    "after_switch": [],
    "include_parent_hooks": False,
}


def user_config_file() -> Path:
    return user_config_path(APP_NAME) / "config.toml"


def user_profiles_file() -> Path:
    return user_config_path(APP_NAME) / PROFILES_CONFIG_NAME


def profiles_file_for_config(config_path: Path) -> Path:
    return config_path.parent / PROFILES_CONFIG_NAME


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or user_config_file()
    default_config = load_default_config()

    if not config_path.exists():
        write_config(default_config, config_path)
        config = _copy_mapping(default_config)
    else:
        try:
            with config_path.open("rb") as config_file:
                user_config = tomllib.load(config_file)
        except tomllib.TOMLDecodeError:
            raise

        migrate_profiles_from_main_config(user_config, config_path)
        main_user_config = _copy_mapping(user_config)
        main_user_config.pop("profiles", None)
        migrated_user_config = apply_config_migrations(default_config, main_user_config)
        config = reconcile_config(default_config, migrated_user_config)
        if config != main_user_config or "profiles" in user_config:
            write_config(config, config_path)

    config["profiles"] = load_profiles_config(profiles_file_for_config(config_path))
    return config


def apply_config_migrations(
    default_config: Mapping[str, Any],
    user_config: Mapping[str, Any],
) -> dict[str, Any]:
    migrated = _copy_mapping(user_config)
    mpvpaper = migrated.get("backends", {}).get("mpvpaper", {})
    default_mpvpaper = default_config.get("backends", {}).get("mpvpaper", {})
    if mpvpaper.get("options") == OLD_MPV_DEFAULT_OPTIONS:
        mpvpaper["options"] = default_mpvpaper.get("options", OLD_MPV_DEFAULT_OPTIONS)
    video_optimization = migrated.get("video_optimization", {})
    if isinstance(video_optimization, Mapping) and "auto_optimize" not in video_optimization:
        video_optimization["auto_optimize"] = True
        video_optimization["prefer_optimized"] = True
    return migrated


def default_config_text() -> str:
    return files("wallmux.data").joinpath("default.toml").read_text(encoding="utf-8")


def load_default_config() -> dict[str, Any]:
    return tomllib.loads(default_config_text())


def load_profiles_config(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or user_profiles_file()
    if not profile_path.exists():
        write_profiles_config(DEFAULT_PROFILES_CONFIG, profile_path)
        return _copy_mapping(DEFAULT_PROFILES_CONFIG)

    with profile_path.open("rb") as profile_file:
        user_profiles = tomllib.load(profile_file)

    profiles = reconcile_profiles_config(user_profiles)
    if profiles != user_profiles:
        write_profiles_config(profiles, profile_path)
    return profiles


def migrate_profiles_from_main_config(
    user_config: Mapping[str, Any],
    config_path: Path,
) -> None:
    inline_profiles = user_config.get("profiles")
    if not isinstance(inline_profiles, Mapping):
        return

    profile_path = profiles_file_for_config(config_path)
    if profile_path.exists():
        try:
            current_profiles = load_profiles_config(profile_path)
        except tomllib.TOMLDecodeError:
            return
        if not _profiles_are_empty(current_profiles):
            return

    write_profiles_config(reconcile_profiles_config(inline_profiles), profile_path)


def reconcile_profiles_config(user_profiles: Mapping[str, Any]) -> dict[str, Any]:
    profiles = reconcile_config(DEFAULT_PROFILES_CONFIG, user_profiles)
    entries = profiles.get("entries", [])
    if not isinstance(entries, list):
        profiles["entries"] = []
        return profiles

    reconciled_entries = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        reconciled_entries.append(reconcile_profile_entry(entry))
    profiles["entries"] = reconciled_entries
    return profiles


def reconcile_profile_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    profile_entry = reconcile_config(PROFILE_ENTRY_DEFAULT, entry)
    backend_rules = entry.get("backend_rules", {})
    profile_entry["backend_rules"] = (
        {str(key): str(value) for key, value in backend_rules.items()}
        if isinstance(backend_rules, Mapping)
        else {}
    )
    return profile_entry


def reconcile_config(
    default_config: Mapping[str, Any],
    user_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge user values into defaults while pruning removed config keys.

    The packaged default config is the schema source. User values are kept for
    keys that still exist and have a compatible shape. New keys from defaults
    are added, and keys removed from defaults are omitted from the result.
    """

    reconciled: dict[str, Any] = {}

    for key, default_value in default_config.items():
        if key not in user_config:
            reconciled[key] = default_value
            continue

        user_value = user_config[key]
        if isinstance(default_value, Mapping):
            if isinstance(user_value, Mapping):
                reconciled[key] = reconcile_config(default_value, user_value)
            else:
                reconciled[key] = default_value
            continue

        reconciled[key] = user_value

    return reconciled


def write_config(config: Mapping[str, Any], path: Path) -> None:
    config = _copy_mapping(config)
    profiles = config.pop("profiles", None)
    if isinstance(profiles, Mapping):
        write_profiles_config(reconcile_profiles_config(profiles), profiles_file_for_config(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(config), encoding="utf-8")


def write_profiles_config(profiles: Mapping[str, Any], path: Path) -> None:
    profiles = reconcile_profiles_config(profiles)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(profiles), encoding="utf-8")


def dump_toml(config: Mapping[str, Any]) -> str:
    if tomli_w is not None:
        return tomli_w.dumps(config)

    lines: list[str] = []
    scalar_items = {
        key: value
        for key, value in config.items()
        if not isinstance(value, Mapping)
    }
    table_items = {
        key: value
        for key, value in config.items()
        if isinstance(value, Mapping)
    }

    for key, value in scalar_items.items():
        lines.append(f"{key} = {_format_toml_value(value)}")

    if scalar_items and table_items:
        lines.append("")

    for table_index, (table_name, table_value) in enumerate(table_items.items()):
        if table_index:
            lines.append("")
        _write_table(lines, table_name, table_value)

    return "\n".join(lines) + "\n"


def _write_table(lines: list[str], name: str, values: Mapping[str, Any]) -> None:
    lines.append(f"[{name}]")
    nested_tables: dict[str, Mapping[str, Any]] = {}

    for key, value in values.items():
        if isinstance(value, Mapping):
            nested_tables[f"{name}.{key}"] = value
        else:
            lines.append(f"{key} = {_format_toml_value(value)}")

    for nested_name, nested_values in nested_tables.items():
        lines.append("")
        _write_table(lines, nested_name, nested_values)


def _format_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _format_toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        formatted = ", ".join(_format_toml_value(item) for item in value)
        return f"[{formatted}]"
    raise TypeError(f"unsupported config value type: {type(value).__name__}")


def _format_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            copied[key] = _copy_mapping(item)
        elif isinstance(item, list):
            copied[key] = list(item)
        else:
            copied[key] = item
    return copied


def _profiles_are_empty(profiles: Mapping[str, Any]) -> bool:
    return (
        not profiles.get("active")
        and not profiles.get("active_category")
        and not profiles.get("active_subcategory")
        and not profiles.get("entries")
    )
