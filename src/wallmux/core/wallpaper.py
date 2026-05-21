"""Wallpaper set and restore orchestration."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from wallmux.backends.routing import build_backend, route_wallpaper
from wallmux.core.config import load_config
from wallmux.core.mime import WallpaperType, detect_wallpaper_type
from wallmux.core.monitors import Monitor, get_focused_monitor, list_monitors
from wallmux.core.process import pid_is_alive, terminate_pid
from wallmux.core.state import WallpaperEntry, load_state, save_state


class WallmuxError(RuntimeError):
    """Raised when Wallmux cannot complete a requested operation."""


class CommandRunner(Protocol):
    def run(self, command: list[str]) -> None:
        """Run a foreground backend command."""

    def start(self, command: list[str]) -> int:
        """Start a long-lived backend process and return its PID."""


class SubprocessCommandRunner:
    def run(self, command: list[str]) -> None:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "command failed"
            raise WallmuxError(f"{command[0]} failed: {message}")

    def start(self, command: list[str]) -> int:
        try:
            process = subprocess.Popen(command)
        except FileNotFoundError as error:
            raise WallmuxError(f"backend command not found: {command[0]}") from error
        return process.pid


@dataclass(frozen=True)
class SetResult:
    monitor: str
    file: Path
    backend: str
    wallpaper_type: WallpaperType
    command: list[str]
    pid: int | None = None


def set_wallpaper(
    file: Path,
    monitor: str,
    *,
    config: dict | None = None,
    runner: CommandRunner | None = None,
    state_path: Path | None = None,
) -> SetResult:
    config = config or load_config()
    runner = runner or SubprocessCommandRunner()
    resolved_file = file.expanduser().resolve()
    wallpaper_type = detect_wallpaper_type(resolved_file)
    backend_name = route_wallpaper(wallpaper_type, config.get("backend_rules", {}))
    backend = build_backend(backend_name, config)
    command = backend.build_set_command(resolved_file, monitor)

    state = load_state(state_path)
    previous = state.monitors.get(monitor)
    if previous and previous.pid and previous.backend in {"mpvpaper", "gslapper"}:
        terminate_pid(previous.pid)

    pid = _execute(command, wallpaper_type, runner)
    state.monitors[monitor] = WallpaperEntry(
        file=str(resolved_file),
        backend=backend_name,
        wallpaper_type=wallpaper_type.value,
        pid=pid,
    )
    save_state(state, state_path)

    return SetResult(
        monitor=monitor,
        file=resolved_file,
        backend=backend_name,
        wallpaper_type=wallpaper_type,
        command=command,
        pid=pid,
    )


def set_wallpaper_for_all(
    file: Path,
    *,
    config: dict | None = None,
    runner: CommandRunner | None = None,
    monitor_provider=list_monitors,
    state_path: Path | None = None,
) -> list[SetResult]:
    monitors = monitor_provider()
    if not monitors:
        raise WallmuxError("no Hyprland monitors found")

    return [
        set_wallpaper(
            file,
            _monitor_name(monitor),
            config=config,
            runner=runner,
            state_path=state_path,
        )
        for monitor in monitors
    ]


def set_wallpaper_for_focused(
    file: Path,
    *,
    config: dict | None = None,
    runner: CommandRunner | None = None,
    monitor_provider=list_monitors,
    state_path: Path | None = None,
) -> SetResult:
    monitor = get_focused_monitor(monitor_provider())
    if monitor is None:
        raise WallmuxError("no focused Hyprland monitor found")

    return set_wallpaper(
        file,
        monitor.name,
        config=config,
        runner=runner,
        state_path=state_path,
    )


def restore_wallpapers(
    *,
    config: dict | None = None,
    runner: CommandRunner | None = None,
    state_path: Path | None = None,
) -> list[SetResult]:
    state = load_state(state_path)
    if not state.monitors:
        return []

    config = config or load_config()
    runner = runner or SubprocessCommandRunner()
    results = []

    for monitor, entry in list(state.monitors.items()):
        if entry.pid and not pid_is_alive(entry.pid):
            entry.pid = None
        results.append(
            set_wallpaper(
                Path(entry.file),
                monitor,
                config=config,
                runner=runner,
                state_path=state_path,
            )
        )

    return results


def _execute(
    command: list[str],
    wallpaper_type: WallpaperType,
    runner: CommandRunner,
) -> int | None:
    if wallpaper_type is WallpaperType.VIDEO:
        return runner.start(command)

    runner.run(command)
    return None


def _monitor_name(monitor: Monitor | str) -> str:
    if isinstance(monitor, str):
        return monitor
    return monitor.name
