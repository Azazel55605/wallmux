"""Daemon service and JSON command handling."""

from __future__ import annotations

import json
import socket
import sys
import time
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from wallmux.core.autoswitch import (
    autoswitch_enabled,
    autoswitch_interval,
    autoswitch_mode,
    autoswitch_monitor,
    autoswitch_target,
    choose_wallpaper,
    load_wallpaper_library,
)
from wallmux.core.config import load_config, user_config_file
from wallmux.core.inhibition import (
    InhibitionStatus,
    evaluate_inhibition,
    inhibition_interval,
    pause_autoswitch,
    pause_videos,
)
from wallmux.core.ipc import default_socket_path
from wallmux.core.monitors import get_focused_monitor, list_monitors
from wallmux.core.notifications import notify_switch_failed, notify_wallpaper_switched
from wallmux.core.process import pause_pid, pid_is_alive, resume_pid, terminate_pid
from wallmux.core.state import WallmuxState, load_state, save_state, state_file
from wallmux.core.wallpaper import (
    CommandRunner,
    SetResult,
    WallmuxError,
    restore_wallpapers,
    set_wallpaper,
    set_wallpaper_for_all,
    set_wallpaper_for_focused,
)

STATE_SCHEMA_VERSION = 2


class WallmuxDaemon:
    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        config_path: Path | None = None,
        config: dict[str, Any] | None = None,
        runner: CommandRunner | None = None,
        state_path: Path | None = None,
        restore_on_startup: bool | None = None,
    ) -> None:
        self.socket_path = socket_path or default_socket_path()
        self.config_path = config_path
        self.config = config or load_config(config_path)
        self.runner = runner
        self.state_path = state_path
        self.restore_on_startup = (
            bool(self.config.get("general", {}).get("restore_on_startup", True))
            if restore_on_startup is None
            else restore_on_startup
        )
        self.next_autoswitch_at = time.monotonic() + autoswitch_interval(self.config)
        self.startup_restore_pending = False
        self.next_startup_restore_at = time.monotonic()
        self.next_inhibition_check_at = 0.0
        self.inhibition_status = InhibitionStatus(False)
        self.paused_video_pids: set[int] = set()
        self.started_at = time.time()
        self.last_error: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    def start(self) -> None:
        self.cleanup_stale_pids()
        if self.restore_on_startup:
            self._restore_on_startup()

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            server.listen()
            server.settimeout(0.5)
            try:
                while True:
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        self.tick()
                        continue
                    with connection:
                        response = self.handle_raw_request(connection.recv(65536))
                        try:
                            connection.sendall(
                                json.dumps(response).encode("utf-8") + b"\n"
                            )
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                    self.tick()
            finally:
                if self.socket_path.exists():
                    self.socket_path.unlink()

    def handle_raw_request(self, payload: bytes) -> dict[str, Any]:
        try:
            request = json.loads(payload.decode("utf-8").strip())
        except json.JSONDecodeError as error:
            return {"ok": False, "error": f"invalid JSON request: {error.msg}"}

        return self.handle_request(request)

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            command = request["command"]
            if command == "set":
                return self._handle_set(request)
            if command == "restore":
                return self._handle_restore()
            if command == "reload":
                return self._handle_reload()
            if command == "autoswitch-now":
                return self._handle_autoswitch_now(request)
            if command == "stop-video":
                return self._handle_stop_video(request)
            if command == "state":
                return self._handle_state()
            return {"ok": False, "error": f"unknown command: {command}"}
        except KeyError as error:
            return {"ok": False, "error": f"missing required field: {error.args[0]}"}
        except (ValueError, WallmuxError) as error:
            self._record_error("request failed", error)
            notify_switch_failed(self.config, error)
            return {"ok": False, "error": str(error)}

    def cleanup_stale_pids(self) -> None:
        state = load_state(self.state_path)
        changed = False
        for entry in state.monitors.values():
            if entry.pid and not pid_is_alive(entry.pid):
                entry.pid = None
                changed = True
        if changed:
            save_state(state, self.state_path)

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)
        self.next_autoswitch_at = time.monotonic() + autoswitch_interval(self.config)
        self.next_inhibition_check_at = 0.0

    def tick(self) -> None:
        self._retry_startup_restore()
        self._update_inhibition()
        if not autoswitch_enabled(self.config):
            return
        if self.inhibition_status.inhibited and pause_autoswitch(self.config):
            return
        now = time.monotonic()
        if now < self.next_autoswitch_at:
            return
        try:
            results = self.autoswitch_once()
            notify_wallpaper_switched(self.config, results)
            self._record_event("autoswitch", f"switched {len(results)} monitor(s)")
        except (ValueError, WallmuxError) as error:
            self._record_error("autoswitch failed", error)
            notify_switch_failed(self.config, error)
        finally:
            self.next_autoswitch_at = now + autoswitch_interval(self.config)

    def _handle_set(self, request: dict[str, Any]) -> dict[str, Any]:
        self.reload_config()
        file = Path(request["file"])
        backend_override = request.get("backend")
        backend_config_overrides = request.get("backend_config")
        if request.get("all"):
            results = set_wallpaper_for_all(
                file,
                config=self.config,
                backend_override=backend_override,
                backend_config_overrides=backend_config_overrides,
                mode=request.get("all_monitor_mode"),
                runner=self.runner,
                state_path=self.state_path,
            )
        elif request.get("focused_monitor"):
            results = [
                set_wallpaper_for_focused(
                    file,
                    config=self.config,
                    backend_override=backend_override,
                    backend_config_overrides=backend_config_overrides,
                    runner=self.runner,
                    state_path=self.state_path,
                )
            ]
        else:
            results = [
                set_wallpaper(
                    file,
                    request["monitor"],
                    config=self.config,
                    backend_override=backend_override,
                    backend_config_overrides=backend_config_overrides,
                    runner=self.runner,
                    state_path=self.state_path,
                )
            ]

        notify_wallpaper_switched(self.config, results)
        self._record_event("set", f"set wallpaper on {len(results)} monitor(s)")
        return {"ok": True, "results": [_serialize_result(result) for result in results]}

    def _handle_restore(self) -> dict[str, Any]:
        self.reload_config()
        results = restore_wallpapers(
            config=self.config,
            runner=self.runner,
            state_path=self.state_path,
        )
        notify_wallpaper_switched(self.config, results)
        self._record_event("restore", f"restored {len(results)} wallpaper(s)")
        return {"ok": True, "results": [_serialize_result(result) for result in results]}

    def _handle_reload(self) -> dict[str, Any]:
        self.reload_config()
        self._record_event("reload", "config reloaded")
        return {"ok": True}

    def _handle_autoswitch_now(self, request: dict[str, Any]) -> dict[str, Any]:
        self.reload_config()
        mode = request.get("mode")
        results = self.autoswitch_once(
            mode=mode,
            target=request.get("target"),
            monitor=request.get("monitor"),
        )
        self.next_autoswitch_at = time.monotonic() + autoswitch_interval(self.config)
        notify_wallpaper_switched(self.config, results)
        self._record_event("autoswitch", f"switched {len(results)} monitor(s)")
        return {"ok": True, "results": [_serialize_result(result) for result in results]}

    def _handle_stop_video(self, request: dict[str, Any]) -> dict[str, Any]:
        monitor = request["monitor"]
        state = load_state(self.state_path)
        entry = state.monitors.get(monitor)
        if not entry or not entry.pid:
            self._record_event("stop-video", f"no tracked video process on {monitor}")
            return {"ok": True, "stopped": False, "monitor": monitor}

        stopped = terminate_pid(entry.pid)
        entry.pid = None
        save_state(state, self.state_path)
        self._record_event("stop-video", f"stopped video process on {monitor}")
        return {"ok": True, "stopped": stopped, "monitor": monitor}

    def _handle_state(self) -> dict[str, Any]:
        state = load_state(self.state_path)
        return {
            "ok": True,
            "state": asdict(state),
            "monitors": self._monitor_status(state),
            "daemon": {
                "running": True,
                "state_schema_version": STATE_SCHEMA_VERSION,
                "version": _package_version(),
                "started_at": self.started_at,
                "uptime_seconds": max(0.0, time.time() - self.started_at),
                "socket_path": str(self.socket_path),
                "config_path": str(self.config_path or user_config_file()),
                "state_path": str(self.state_path or state_file()),
                "startup_restore_pending": self.startup_restore_pending,
                "last_error": self.last_error,
                "events": self.events[-20:],
                "autoswitch": self._autoswitch_status(),
                "inhibition": self._inhibition_status(),
            },
        }

    def autoswitch_once(
        self,
        *,
        mode: str | None = None,
        target: str | None = None,
        monitor: str | None = None,
    ) -> list[SetResult]:
        selected_mode = mode or autoswitch_mode(self.config)
        items = load_wallpaper_library(self.config)
        selected_target = target or autoswitch_target(self.config)
        selected_monitor = monitor or autoswitch_monitor(self.config)
        current_file = self._current_file_for_target(selected_target, selected_monitor)
        item = choose_wallpaper(items, mode=selected_mode, current_file=current_file)

        if selected_target == "all":
            return set_wallpaper_for_all(
                item.path,
                config=self.config,
                runner=self.runner,
                state_path=self.state_path,
            )
        if selected_target == "focused":
            return [
                set_wallpaper_for_focused(
                    item.path,
                    config=self.config,
                    runner=self.runner,
                    state_path=self.state_path,
                )
            ]
        if not selected_monitor:
            raise WallmuxError("autoswitch target is monitor but no monitor is configured")
        return [
            set_wallpaper(
                item.path,
                selected_monitor,
                config=self.config,
                runner=self.runner,
                state_path=self.state_path,
            )
        ]

    def _current_file_for_target(self, target: str, monitor: str) -> str | None:
        state = load_state(self.state_path)
        if target == "monitor" and monitor in state.monitors:
            return state.monitors[monitor].file
        if target == "focused":
            focused = get_focused_monitor(list_monitors())
            if focused and focused.name in state.monitors:
                return state.monitors[focused.name].file
        if state.monitors:
            first_monitor = sorted(state.monitors)[0]
            return state.monitors[first_monitor].file
        return None

    def _autoswitch_status(self) -> dict[str, Any]:
        return {
            "enabled": autoswitch_enabled(self.config),
            "interval_seconds": autoswitch_interval(self.config),
            "mode": autoswitch_mode(self.config),
            "target": autoswitch_target(self.config),
            "monitor": autoswitch_monitor(self.config),
            "next_switch_seconds": max(0.0, self.next_autoswitch_at - time.monotonic()),
        }

    def _inhibition_status(self) -> dict[str, Any]:
        return {
            "inhibited": self.inhibition_status.inhibited,
            "reason": self.inhibition_status.reason,
            "enabled": bool(self.config.get("inhibition", {}).get("enabled", True)),
            "pause_autoswitch": pause_autoswitch(self.config),
            "pause_videos": pause_videos(self.config),
            "check_interval_seconds": inhibition_interval(self.config),
            "paused_video_pids": sorted(self.paused_video_pids),
        }

    def _restore_on_startup(self) -> None:
        try:
            restore_wallpapers(
                config=self.config,
                runner=self.runner,
                state_path=self.state_path,
            )
        except (ValueError, WallmuxError) as error:
            self.startup_restore_pending = True
            self.next_startup_restore_at = time.monotonic() + self._restore_retry_seconds()
            self._record_error("startup restore failed", error)
            print(
                f"wallmuxd: startup restore failed; will retry: {error}",
                file=sys.stderr,
            )
        else:
            self.startup_restore_pending = False
            self._record_event("startup-restore", "startup restore completed")

    def _retry_startup_restore(self) -> None:
        if not self.startup_restore_pending:
            return
        if time.monotonic() < self.next_startup_restore_at:
            return
        self._restore_on_startup()

    def _restore_retry_seconds(self) -> float:
        return max(
            1.0,
            float(self.config.get("daemon", {}).get("startup_restore_retry_seconds", 5.0)),
        )

    def _update_inhibition(self) -> None:
        now = time.monotonic()
        if now < self.next_inhibition_check_at:
            return
        self.next_inhibition_check_at = now + inhibition_interval(self.config)
        previous = self.inhibition_status
        self.inhibition_status = evaluate_inhibition(self.config)
        if previous != self.inhibition_status:
            if self.inhibition_status.inhibited:
                self._record_event(
                    "inhibition",
                    f"inhibited: {self.inhibition_status.reason}",
                )
            else:
                self._record_event("inhibition", "inhibition cleared")
        if self.inhibition_status.inhibited and pause_videos(self.config):
            self._pause_tracked_videos()
        elif previous.inhibited:
            self._resume_paused_videos()

    def _pause_tracked_videos(self) -> None:
        state = load_state(self.state_path)
        for entry in state.monitors.values():
            if entry.pid and entry.pid not in self.paused_video_pids and pause_pid(entry.pid):
                self.paused_video_pids.add(entry.pid)

    def _resume_paused_videos(self) -> None:
        for pid in list(self.paused_video_pids):
            resume_pid(pid)
            self.paused_video_pids.discard(pid)

    def _monitor_status(self, state: WallmuxState) -> dict[str, Any]:
        live_monitors = {monitor.name: monitor for monitor in list_monitors()}
        statuses: dict[str, Any] = {}
        for monitor_name, entry in state.monitors.items():
            live_monitor = live_monitors.get(monitor_name)
            statuses[monitor_name] = {
                "file": entry.file,
                "backend": entry.backend,
                "wallpaper_type": entry.wallpaper_type,
                "pid": entry.pid,
                "pid_alive": bool(entry.pid and pid_is_alive(entry.pid)),
                "connected": live_monitor is not None,
                "focused": bool(live_monitor.focused) if live_monitor else False,
                "description": live_monitor.description if live_monitor else None,
            }

        for monitor_name, monitor in live_monitors.items():
            statuses.setdefault(
                monitor_name,
                {
                    "file": None,
                    "backend": None,
                    "wallpaper_type": None,
                    "pid": None,
                    "pid_alive": False,
                    "connected": True,
                    "focused": monitor.focused,
                    "description": monitor.description,
                },
            )
        return statuses

    def _record_event(self, kind: str, message: str, *, status: str = "info") -> None:
        self.events.append(
            {
                "time": datetime.fromtimestamp(time.time()).isoformat(timespec="seconds"),
                "kind": kind,
                "status": status,
                "message": message,
            }
        )
        del self.events[:-50]

    def _record_error(self, message: str, error: Exception) -> None:
        self.last_error = {
            "time": datetime.fromtimestamp(time.time()).isoformat(timespec="seconds"),
            "message": message,
            "error": str(error),
        }
        self._record_event("error", f"{message}: {error}", status="error")


def _serialize_result(result: SetResult) -> dict[str, Any]:
    return {
        "monitor": result.monitor,
        "file": str(result.file),
        "backend": result.backend,
        "wallpaper_type": result.wallpaper_type.value,
        "command": result.command,
        "pid": result.pid,
        "transition": result.transition.value,
    }


def _package_version() -> str:
    try:
        return version("wallmux")
    except PackageNotFoundError:
        return "editable"
