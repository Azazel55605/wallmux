"""Configuration loading for Wallmux."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

APP_NAME = "wallmux"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "default.toml"


def user_config_file() -> Path:
    return user_config_path(APP_NAME) / "config.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or user_config_file()
    if not config_path.exists():
        config_path = DEFAULT_CONFIG_PATH
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)
