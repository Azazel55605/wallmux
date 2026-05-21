"""Hook command formatting and execution."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from platformdirs import user_state_path

from wallmux.core.mime import WallpaperType, detect_mime
from wallmux.core.thumbnails import ensure_thumbnail

APP_NAME = "wallmux"

SUPPORTED_PLACEHOLDERS = {
    "file",
    "monitor",
    "backend",
    "mime",
    "basename",
    "thumbnail",
    "source_for_colors",
}


@dataclass(frozen=True)
class HookContext:
    file: Path
    monitor: str
    backend: str
    wallpaper_type: WallpaperType
    thumbnail: Path | None = None


def format_hook(command: str, values: dict[str, str]) -> str:
    fields = {
        field_name
        for _, field_name, _, _ in Formatter().parse(command)
        if field_name is not None
    }
    unsupported = fields - SUPPORTED_PLACEHOLDERS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsupported hook placeholder(s): {names}")
    return command.format(**values)


def hook_log_file() -> Path:
    return user_state_path(APP_NAME) / "hooks.log"


def run_hook_stage(
    stage: str,
    config: dict[str, Any],
    context: HookContext,
    *,
    logger: logging.Logger | None = None,
) -> None:
    hooks_config = config.get("hooks", {})
    commands = hooks_config.get(stage, [])
    if not commands or not _hooks_enabled_for_backend(hooks_config, context.backend):
        return

    timeout = float(hooks_config.get("timeout_seconds", 30))
    values = build_hook_values(config, context)
    hook_logger = logger or get_hook_logger()

    for command in commands:
        try:
            formatted = format_hook(command, values)
            result = subprocess.run(
                formatted,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            hook_logger.warning("%s hook failed before execution: %s", stage, error)
            continue

        if result.returncode != 0:
            output = result.stderr.strip() or result.stdout.strip() or "no output"
            hook_logger.warning(
                "%s hook exited %s: %s\n%s",
                stage,
                result.returncode,
                formatted,
                output,
            )


def build_hook_values(config: dict[str, Any], context: HookContext) -> dict[str, str]:
    thumbnail = context.thumbnail
    if thumbnail is None and context.wallpaper_type is WallpaperType.VIDEO:
        thumbnail = ensure_thumbnail(
            context.file,
            context.wallpaper_type,
            int(config.get("general", {}).get("thumbnail_size", 256)),
        )

    source_for_colors = context.file
    if context.wallpaper_type is WallpaperType.VIDEO:
        source_for_colors = thumbnail or context.file

    return {
        "file": str(context.file),
        "monitor": context.monitor,
        "backend": context.backend,
        "mime": detect_mime(context.file) or context.wallpaper_type.value,
        "basename": context.file.name,
        "thumbnail": str(thumbnail or ""),
        "source_for_colors": str(source_for_colors),
    }


def get_hook_logger() -> logging.Logger:
    logger = logging.getLogger("wallmux.hooks")
    if logger.handlers:
        return logger

    log_file = hook_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _hooks_enabled_for_backend(hooks_config: dict[str, Any], backend: str) -> bool:
    backend_config = hooks_config.get("backends", {})
    if backend not in backend_config:
        return True
    return bool(backend_config[backend])
