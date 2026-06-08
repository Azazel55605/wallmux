"""Optional external transition helper commands."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from platformdirs import user_state_path

from wallmux.core.state import WallpaperEntry
from wallmux.core.transitions import TransitionKind

APP_NAME = "wallmux"

SUPPORTED_PLACEHOLDERS = {
    "monitor",
    "from_file",
    "to_file",
    "from_backend",
    "to_backend",
    "transition",
    "stage",
}


@dataclass(frozen=True)
class TransitionContext:
    monitor: str
    to_file: Path
    to_backend: str
    transition: TransitionKind
    previous: WallpaperEntry | None = None


def transition_log_file() -> Path:
    return user_state_path(APP_NAME) / "transitions.log"


def run_transition_stage(
    stage: str,
    config: dict[str, Any],
    context: TransitionContext,
    *,
    logger: logging.Logger | None = None,
) -> None:
    transitions_config = config.get("transitions", {})
    effects_config = transitions_config.get("effects", {})
    if not effects_config:
        return

    commands = _commands_for_stage(stage, effects_config, context.transition)
    if not commands:
        return

    timeout = float(effects_config.get("timeout_seconds", 2.0))
    values = _build_values(stage, context)
    transition_logger = logger or get_transition_logger()

    for command in commands:
        try:
            formatted = _format_command(command, values)
            result = subprocess.run(
                formatted,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            transition_logger.warning(
                "%s transition command failed before execution: %s",
                stage,
                error,
            )
            continue

        if result.returncode != 0:
            output = result.stderr.strip() or result.stdout.strip() or "no output"
            transition_logger.warning(
                "%s transition command exited %s: %s\n%s",
                stage,
                result.returncode,
                formatted,
                output,
            )


def get_transition_logger() -> logging.Logger:
    logger = logging.getLogger("wallmux.transitions")
    if logger.handlers:
        return logger

    log_file = transition_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _commands_for_stage(
    stage: str,
    effects_config: dict[str, Any],
    transition: TransitionKind,
) -> list[str]:
    commands: list[str] = []
    if stage == "before":
        if effects_config.get("screenshot_bridge") and _is_cross_backend_transition(transition):
            command = effects_config.get("screenshot_command", "")
            if command:
                commands.append(command)
    if effects_config.get("quickshell_overlay") and _quickshell_transition_enabled(
        effects_config,
        transition,
    ):
        command = effects_config.get("quickshell_command", "")
        if command:
            commands.append(command)
    if stage == "after" and effects_config.get("fade_overlay"):
        command = effects_config.get("fade_command", "")
        if command:
            commands.append(command)
    return commands


def _is_cross_backend_transition(transition: TransitionKind) -> bool:
    return transition in {
        TransitionKind.IMAGE_TO_VIDEO,
        TransitionKind.VIDEO_TO_IMAGE,
        TransitionKind.VIDEO_TO_VIDEO,
    }


def _quickshell_transition_enabled(
    effects_config: dict[str, Any],
    transition: TransitionKind,
) -> bool:
    enabled = effects_config.get("quickshell_transitions")
    if not isinstance(enabled, list):
        return transition is not TransitionKind.IMAGE_TO_IMAGE
    return transition.value in enabled


def _build_values(stage: str, context: TransitionContext) -> dict[str, str]:
    previous = context.previous
    return {
        "monitor": context.monitor,
        "from_file": previous.file if previous else "",
        "to_file": str(context.to_file),
        "from_backend": previous.backend if previous else "",
        "to_backend": context.to_backend,
        "transition": context.transition.value,
        "stage": stage,
    }


def _format_command(command: str, values: dict[str, str]) -> str:
    fields = {
        field_name
        for _, field_name, _, _ in Formatter().parse(command)
        if field_name is not None
    }
    unsupported = fields - SUPPORTED_PLACEHOLDERS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsupported transition placeholder(s): {names}")
    return command.format(**values)
