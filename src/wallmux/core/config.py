"""Configuration loading for Wallmux."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

APP_NAME = "wallmux"
DEFAULT_CONFIG_RESOURCE = "wallmux.data.default.toml"


def user_config_file() -> Path:
    return user_config_path(APP_NAME) / "config.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or user_config_file()
    if config_path.exists():
        with config_path.open("rb") as config_file:
            return tomllib.load(config_file)

    return tomllib.loads(default_config_text())


def default_config_text() -> str:
    return files("wallmux.data").joinpath("default.toml").read_text(encoding="utf-8")
