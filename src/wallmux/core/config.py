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


def user_config_file() -> Path:
    return user_config_path(APP_NAME) / "config.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or user_config_file()
    default_config = load_default_config()

    if not config_path.exists():
        write_config(default_config, config_path)
        return default_config

    try:
        with config_path.open("rb") as config_file:
            user_config = tomllib.load(config_file)
    except tomllib.TOMLDecodeError:
        raise

    config = reconcile_config(default_config, user_config)
    if config != user_config:
        write_config(config, config_path)

    return config


def default_config_text() -> str:
    return files("wallmux.data").joinpath("default.toml").read_text(encoding="utf-8")


def load_default_config() -> dict[str, Any]:
    return tomllib.loads(default_config_text())


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_toml(config), encoding="utf-8")


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
