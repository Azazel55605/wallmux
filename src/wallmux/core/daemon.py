"""Daemon service and JSON command handling."""

from __future__ import annotations

import json
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any

from wallmux.core.config import load_config
from wallmux.core.ipc import default_socket_path
from wallmux.core.process import pid_is_alive, terminate_pid
from wallmux.core.state import load_state, save_state
from wallmux.core.wallpaper import (
    CommandRunner,
    SetResult,
    WallmuxError,
    restore_wallpapers,
    set_wallpaper,
    set_wallpaper_for_all,
    set_wallpaper_for_focused,
)


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

    def start(self) -> None:
        self.cleanup_stale_pids()
        if self.restore_on_startup:
            restore_wallpapers(
                config=self.config,
                runner=self.runner,
                state_path=self.state_path,
            )

        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            server.listen()
            try:
                while True:
                    connection, _ = server.accept()
                    with connection:
                        response = self.handle_raw_request(connection.recv(65536))
                        connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
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
            if command == "stop-video":
                return self._handle_stop_video(request)
            if command == "state":
                return self._handle_state()
            return {"ok": False, "error": f"unknown command: {command}"}
        except KeyError as error:
            return {"ok": False, "error": f"missing required field: {error.args[0]}"}
        except (ValueError, WallmuxError) as error:
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

        return {"ok": True, "results": [_serialize_result(result) for result in results]}

    def _handle_restore(self) -> dict[str, Any]:
        self.reload_config()
        results = restore_wallpapers(
            config=self.config,
            runner=self.runner,
            state_path=self.state_path,
        )
        return {"ok": True, "results": [_serialize_result(result) for result in results]}

    def _handle_reload(self) -> dict[str, Any]:
        self.reload_config()
        return {"ok": True}

    def _handle_stop_video(self, request: dict[str, Any]) -> dict[str, Any]:
        monitor = request["monitor"]
        state = load_state(self.state_path)
        entry = state.monitors.get(monitor)
        if not entry or not entry.pid:
            return {"ok": True, "stopped": False, "monitor": monitor}

        stopped = terminate_pid(entry.pid)
        entry.pid = None
        save_state(state, self.state_path)
        return {"ok": True, "stopped": stopped, "monitor": monitor}

    def _handle_state(self) -> dict[str, Any]:
        state = load_state(self.state_path)
        return {"ok": True, "state": asdict(state)}


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
