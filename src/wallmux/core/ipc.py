"""Unix socket IPC for wallmuxd."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

from platformdirs import user_runtime_path

APP_NAME = "wallmux"
DEFAULT_TIMEOUT_SECONDS = 2.0


class DaemonUnavailable(RuntimeError):
    """Raised when the wallmux daemon socket cannot be reached."""


def default_socket_path() -> Path:
    return user_runtime_path(APP_NAME) / "wallmux.sock"


def send_request(
    request: dict[str, Any],
    *,
    socket_path: Path | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    target = socket_path or default_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_seconds)
            client.connect(str(target))
            client.sendall(json.dumps(request).encode("utf-8") + b"\n")
            return _read_response(client)
    except OSError as error:
        raise DaemonUnavailable(f"wallmuxd is not available at {target}") from error


def _read_response(client: socket.socket) -> dict[str, Any]:
    chunks = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break

    if not chunks:
        raise DaemonUnavailable("wallmuxd closed the connection without a response")

    raw_response = b"".join(chunks).split(b"\n", maxsplit=1)[0]
    return json.loads(raw_response.decode("utf-8"))
