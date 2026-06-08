"""Wallpaper set and restore orchestration."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from platformdirs import user_state_path

from wallmux.backends.routing import (
    build_backend,
    compatible_backends,
    fallback_backends,
    route_wallpaper,
)
from wallmux.core.config import load_config
from wallmux.core.hooks import HookContext, run_hook_stage
from wallmux.core.mime import WallpaperType, detect_wallpaper_type
from wallmux.core.monitors import Monitor, get_focused_monitor, list_monitors
from wallmux.core.process import pid_is_alive, terminate_pid
from wallmux.core.state import WallpaperEntry, load_state, save_state
from wallmux.core.transition_effects import TransitionContext, run_transition_stage
from wallmux.core.transitions import TransitionKind, plan_transition
from wallmux.core.video import optimized_video_for_source

STATE_LOCK = threading.Lock()
APP_NAME = "wallmux"
Command = list[str]
CommandPlan = Command | list[Command]
IMAGE_BACKENDS = {"awww", "swww", "hyprpaper"}
GROUPED_OUTPUT_BACKENDS = {"awww", "swww"}


class WallmuxError(RuntimeError):
    """Raised when Wallmux cannot complete a requested operation."""


class CommandRunner(Protocol):
    def run(self, command: Command) -> None:
        """Run a foreground backend command."""

    def start(self, command: Command) -> int:
        """Start a long-lived backend process and return its PID."""


class SubprocessCommandRunner:
    def run(self, command: Command) -> None:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "command failed"
            raise WallmuxError(f"{command[0]} failed: {message}")

    def start(self, command: Command) -> int:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise WallmuxError(f"backend command not found: {command[0]}") from error
        return process.pid


@dataclass(frozen=True)
class SetResult:
    monitor: str
    file: Path
    backend: str
    wallpaper_type: WallpaperType
    command: CommandPlan
    pid: int | None = None
    transition: TransitionKind = TransitionKind.FIRST_SET


def set_wallpaper(
    file: Path,
    monitor: str,
    *,
    config: dict | None = None,
    backend_override: str | None = None,
    backend_config_overrides: dict[str, Any] | None = None,
    runner: CommandRunner | None = None,
    state_path: Path | None = None,
) -> SetResult:
    config = config or load_config()
    runner = runner or SubprocessCommandRunner()
    resolved_file = file.expanduser().resolve()
    wallpaper_type = detect_wallpaper_type(resolved_file)
    backend_name = backend_override or route_wallpaper(
        wallpaper_type,
        config.get("backend_rules", {}),
    )
    if backend_override and backend_override not in compatible_backends(wallpaper_type):
        raise WallmuxError(
            f"{backend_override} cannot handle {wallpaper_type.value} wallpapers"
        )
    if backend_config_overrides is not None and not isinstance(
        backend_config_overrides,
        dict,
    ):
        raise WallmuxError("backend_config must be an object")
    backend_file = _backend_file(resolved_file, wallpaper_type, config)
    with STATE_LOCK:
        state = load_state(state_path)
        previous = state.monitors.get(monitor)
        if previous and previous.pid and not pid_is_alive(previous.pid):
            previous.pid = None
            save_state(state, state_path)

    candidates = _backend_candidates(
        backend_name,
        wallpaper_type,
        config,
        allow_fallbacks=backend_override is None,
    )
    failures: list[str] = []
    for index, candidate in enumerate(candidates):
        try:
            return _set_wallpaper_with_backend(
                backend_file,
                monitor,
                wallpaper_type,
                candidate,
                config=config,
                backend_config_overrides=backend_config_overrides,
                runner=runner,
                state_path=state_path,
                previous=previous,
            )
        except WallmuxError as error:
            failures.append(f"{candidate}: {error}")
            if index < len(candidates) - 1:
                _log_backend_fallback(candidate, candidates[index + 1], error)
                continue
            raise WallmuxError("; ".join(failures)) from error

    raise WallmuxError(f"no backend candidates for {wallpaper_type.value} wallpaper")


def _backend_file(resolved_file: Path, wallpaper_type: WallpaperType, config: dict) -> Path:
    if wallpaper_type is not WallpaperType.VIDEO:
        return resolved_file
    optimized = optimized_video_for_source(resolved_file, config)
    return optimized or resolved_file


def _set_wallpaper_with_backend(
    resolved_file: Path,
    monitor: str,
    wallpaper_type: WallpaperType,
    backend_name: str,
    *,
    config: dict,
    backend_config_overrides: dict[str, Any] | None,
    runner: CommandRunner,
    state_path: Path | None,
    previous: WallpaperEntry | None,
) -> SetResult:
    backend = build_backend(backend_name, config, backend_config_overrides)
    command = backend.build_set_command(resolved_file, monitor)
    hook_context = HookContext(
        file=resolved_file,
        monitor=monitor,
        backend=backend_name,
        wallpaper_type=wallpaper_type,
    )

    run_hook_stage("before_set", config, hook_context)
    transition = plan_transition(previous, wallpaper_type, backend_name)
    transition_context = TransitionContext(
        monitor=monitor,
        to_file=resolved_file,
        to_backend=backend_name,
        transition=transition.kind,
        previous=previous,
    )
    run_transition_stage("before", config, transition_context)

    stop_video_after_image_set = _should_stop_video_after_image_set(
        config,
        transition.kind,
        backend_name,
        previous.pid if previous else None,
    )

    if (
        previous
        and previous.pid
        and transition.stop_previous_video
        and not stop_video_after_image_set
    ):
        transitions_config = config.get("transitions", {})
        terminate_pid(
            previous.pid,
            float(transitions_config.get("video_stop_timeout_seconds", 2.0)),
            kill_on_timeout=bool(transitions_config.get("kill_video_on_timeout", True)),
        )
        previous.pid = None

    pid = _execute(command, backend_name, wallpaper_type, runner)
    _wait_for_video_start_handoff(config, wallpaper_type, backend_name)
    if previous and previous.pid and stop_video_after_image_set:
        _wait_for_video_to_image_handoff(config)
        transitions_config = config.get("transitions", {})
        terminate_pid(
            previous.pid,
            float(transitions_config.get("video_stop_timeout_seconds", 2.0)),
            kill_on_timeout=bool(transitions_config.get("kill_video_on_timeout", True)),
        )
        previous.pid = None
    with STATE_LOCK:
        state = load_state(state_path)
        state.monitors[monitor] = WallpaperEntry(
            file=str(resolved_file),
            backend=backend_name,
            wallpaper_type=wallpaper_type.value,
            pid=pid,
        )
        save_state(state, state_path)
    run_transition_stage("after", config, transition_context)
    run_hook_stage(
        "after_set",
        config,
        HookContext(
            file=resolved_file,
            monitor=monitor,
            backend=backend_name,
            wallpaper_type=wallpaper_type,
        ),
    )

    return SetResult(
        monitor=monitor,
        file=resolved_file,
        backend=backend_name,
        wallpaper_type=wallpaper_type,
        command=command,
        pid=pid,
        transition=transition.kind,
    )


def set_wallpaper_for_all(
    file: Path,
    *,
    config: dict | None = None,
    backend_override: str | None = None,
    backend_config_overrides: dict[str, Any] | None = None,
    mode: str | None = None,
    runner: CommandRunner | None = None,
    monitor_provider=list_monitors,
    state_path: Path | None = None,
) -> list[SetResult]:
    monitors = monitor_provider()
    if not monitors:
        raise WallmuxError("no Hyprland monitors found")

    config = config or load_config()
    monitor_names = [_monitor_name(monitor) for monitor in monitors]
    all_monitor_mode = mode or config.get("general", {}).get(
        "all_monitor_mode",
        "simultaneous",
    )
    if all_monitor_mode == "simultaneous" and _can_set_all_outputs_together(
        file,
        config,
        backend_override,
    ):
        return _set_image_wallpaper_for_all_outputs(
            file,
            monitor_names,
            config=config,
            backend_override=backend_override,
            backend_config_overrides=backend_config_overrides,
            runner=runner,
            state_path=state_path,
        )

    if all_monitor_mode == "sequential":
        return [
            set_wallpaper(
                file,
                monitor,
                config=config,
                backend_override=backend_override,
                backend_config_overrides=backend_config_overrides,
                runner=runner,
                state_path=state_path,
            )
            for monitor in monitor_names
        ]

    if all_monitor_mode != "simultaneous":
        raise WallmuxError(f"unknown all monitor mode: {all_monitor_mode}")

    with ThreadPoolExecutor(max_workers=len(monitor_names)) as executor:
        futures = [
            executor.submit(
                set_wallpaper,
                file,
                monitor,
                config=config,
                backend_override=backend_override,
                backend_config_overrides=backend_config_overrides,
                runner=runner,
                state_path=state_path,
            )
            for monitor in monitor_names
        ]
        return [future.result() for future in futures]


def set_wallpaper_for_focused(
    file: Path,
    *,
    config: dict | None = None,
    backend_override: str | None = None,
    backend_config_overrides: dict[str, Any] | None = None,
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
        backend_override=backend_override,
        backend_config_overrides=backend_config_overrides,
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
    command: CommandPlan,
    backend_name: str,
    wallpaper_type: WallpaperType,
    runner: CommandRunner,
) -> int | None:
    if wallpaper_type is WallpaperType.VIDEO or backend_name in {"mpvpaper", "gslapper"}:
        if _is_command_sequence(command):
            raise WallmuxError(f"{backend_name} cannot be started from multiple commands")
        return runner.start(command)

    _run_foreground(command, runner)
    return None


def _backend_candidates(
    backend_name: str,
    wallpaper_type: WallpaperType,
    config: dict,
    *,
    allow_fallbacks: bool,
) -> tuple[str, ...]:
    if not allow_fallbacks:
        return (backend_name,)
    fallbacks = fallback_backends(backend_name, wallpaper_type, config)
    return (backend_name, *fallbacks)


def backend_log_file() -> Path:
    return user_state_path(APP_NAME) / "backends.log"


def get_backend_logger() -> logging.Logger:
    logger = logging.getLogger("wallmux.backends")
    if logger.handlers:
        return logger

    log_file = backend_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _log_backend_fallback(failed_backend: str, fallback_backend: str, error: Exception) -> None:
    try:
        get_backend_logger().warning(
            "backend %s failed; trying fallback %s: %s",
            failed_backend,
            fallback_backend,
            error,
        )
    except OSError:
        return


def _can_set_all_outputs_together(
    file: Path,
    config: dict,
    backend_override: str | None,
) -> bool:
    wallpaper_type = detect_wallpaper_type(file.expanduser().resolve())
    backend_name = backend_override or route_wallpaper(
        wallpaper_type,
        config.get("backend_rules", {}),
    )
    return backend_name in GROUPED_OUTPUT_BACKENDS and wallpaper_type is not WallpaperType.VIDEO


def _set_image_wallpaper_for_all_outputs(
    file: Path,
    monitors: list[str],
    *,
    config: dict,
    backend_override: str | None,
    backend_config_overrides: dict[str, Any] | None,
    runner: CommandRunner | None,
    state_path: Path | None,
) -> list[SetResult]:
    runner = runner or SubprocessCommandRunner()
    resolved_file = file.expanduser().resolve()
    wallpaper_type = detect_wallpaper_type(resolved_file)
    backend_name = backend_override or route_wallpaper(
        wallpaper_type,
        config.get("backend_rules", {}),
    )
    if backend_override and backend_override not in compatible_backends(wallpaper_type):
        raise WallmuxError(
            f"{backend_override} cannot handle {wallpaper_type.value} wallpapers"
        )
    joined_outputs = ",".join(monitors)

    transitions: dict[str, TransitionKind] = {}
    pids_to_stop: list[int] = []
    previous_entries: list[WallpaperEntry] = []
    with STATE_LOCK:
        state = load_state(state_path)
        for monitor in monitors:
            previous = state.monitors.get(monitor)
            if previous:
                previous_entries.append(previous)
            transition = plan_transition(previous, wallpaper_type, backend_name)
            transitions[monitor] = transition.kind
            if previous and previous.pid and not pid_is_alive(previous.pid):
                previous.pid = None
            if previous and previous.pid and transition.stop_previous_video:
                pids_to_stop.append(previous.pid)
                previous.pid = None
        save_state(state, state_path)

    hook_context = HookContext(
        file=resolved_file,
        monitor=joined_outputs,
        backend=backend_name,
        wallpaper_type=wallpaper_type,
    )
    run_hook_stage("before_set", config, hook_context)
    transition_context = TransitionContext(
        monitor=joined_outputs,
        to_file=resolved_file,
        to_backend=backend_name,
        transition=_grouped_transition_kind(transitions.values()),
        previous=previous_entries[0] if previous_entries else None,
    )
    run_transition_stage("before", config, transition_context)

    stop_videos_after_image_set = bool(pids_to_stop) and _basic_image_bridge_enabled(config)
    transitions_config = config.get("transitions", {})
    if not stop_videos_after_image_set:
        _terminate_pids(
            pids_to_stop,
            timeout_seconds=float(transitions_config.get("video_stop_timeout_seconds", 2.0)),
            kill_on_timeout=bool(transitions_config.get("kill_video_on_timeout", True)),
        )
    candidates = _backend_candidates(
        backend_name,
        wallpaper_type,
        config,
        allow_fallbacks=backend_override is None,
    )
    command: CommandPlan | None = None
    failures: list[str] = []
    for index, candidate in enumerate(candidates):
        backend = build_backend(candidate, config, backend_config_overrides)
        command = backend.build_set_command(resolved_file, joined_outputs)
        try:
            _run_foreground(command, runner)
        except WallmuxError as error:
            failures.append(f"{candidate}: {error}")
            if index < len(candidates) - 1:
                _log_backend_fallback(
                    candidate,
                    candidates[index + 1],
                    error,
                )
                continue
            raise WallmuxError("; ".join(failures)) from error
        backend_name = candidate
        break

    if command is None:
        raise WallmuxError(f"no backend candidates for {wallpaper_type.value} wallpaper")

    if stop_videos_after_image_set:
        _wait_for_video_to_image_handoff(config)
        _terminate_pids(
            pids_to_stop,
            timeout_seconds=float(transitions_config.get("video_stop_timeout_seconds", 2.0)),
            kill_on_timeout=bool(transitions_config.get("kill_video_on_timeout", True)),
        )

    with STATE_LOCK:
        state = load_state(state_path)
        for monitor in monitors:
            state.monitors[monitor] = WallpaperEntry(
                file=str(resolved_file),
                backend=backend_name,
                wallpaper_type=wallpaper_type.value,
                pid=None,
            )
        save_state(state, state_path)

    run_transition_stage("after", config, transition_context)
    run_hook_stage(
        "after_set",
        config,
        HookContext(
            file=resolved_file,
            monitor=joined_outputs,
            backend=backend_name,
            wallpaper_type=wallpaper_type,
        ),
    )
    return [
        SetResult(
            monitor=monitor,
            file=resolved_file,
            backend=backend_name,
            wallpaper_type=wallpaper_type,
            command=command,
            transition=transitions.get(monitor, TransitionKind.FIRST_SET),
        )
        for monitor in monitors
    ]


def _monitor_name(monitor: Monitor | str) -> str:
    if isinstance(monitor, str):
        return monitor
    return monitor.name


def _should_stop_video_after_image_set(
    config: dict,
    transition: TransitionKind,
    backend_name: str,
    previous_pid: int | None,
) -> bool:
    if not previous_pid:
        return False
    if transition is not TransitionKind.VIDEO_TO_IMAGE:
        return False
    if backend_name not in IMAGE_BACKENDS:
        return False
    return _basic_image_bridge_enabled(config)


def _basic_image_bridge_enabled(config: dict) -> bool:
    basic_config = config.get("transitions", {}).get("basic", {})
    if not bool(basic_config.get("enabled", True)):
        return False
    return bool(basic_config.get("set_image_before_stopping_video", True))


def _wait_for_video_to_image_handoff(config: dict) -> None:
    basic_config = config.get("transitions", {}).get("basic", {})
    delay = max(0.0, float(basic_config.get("video_to_image_settle_seconds", 0.9)))
    if delay:
        time.sleep(delay)


def _wait_for_video_start_handoff(
    config: dict,
    wallpaper_type: WallpaperType,
    backend_name: str,
) -> None:
    if wallpaper_type is not WallpaperType.VIDEO and backend_name not in {
        "mpvpaper",
        "gslapper",
    }:
        return
    basic_config = config.get("transitions", {}).get("basic", {})
    delay = max(0.0, float(basic_config.get("video_start_settle_seconds", 0.6)))
    if delay:
        time.sleep(delay)


def _grouped_transition_kind(transitions) -> TransitionKind:
    transition_set = set(transitions)
    for kind in (
        TransitionKind.VIDEO_TO_IMAGE,
        TransitionKind.IMAGE_TO_IMAGE,
        TransitionKind.FIRST_SET,
    ):
        if kind in transition_set:
            return kind
    return TransitionKind.FIRST_SET


def _run_foreground(command: CommandPlan, runner: CommandRunner) -> None:
    if _is_command_sequence(command):
        for item in command:
            runner.run(item)
        return
    runner.run(command)


def _is_command_sequence(command: CommandPlan) -> bool:
    return bool(command) and isinstance(command[0], list)


def _terminate_pids(
    pids: list[int],
    *,
    timeout_seconds: float,
    kill_on_timeout: bool,
) -> None:
    if not pids:
        return
    if len(pids) == 1:
        terminate_pid(
            pids[0],
            timeout_seconds,
            kill_on_timeout=kill_on_timeout,
        )
        return

    with ThreadPoolExecutor(max_workers=len(pids)) as executor:
        futures = [
            executor.submit(
                terminate_pid,
                pid,
                timeout_seconds,
                kill_on_timeout=kill_on_timeout,
            )
            for pid in pids
        ]
        for future in futures:
            future.result()
