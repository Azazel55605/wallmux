"""Process helpers for backend ownership."""

from __future__ import annotations

import os
import signal
import time


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_pid(
    pid: int,
    timeout_seconds: float = 2.0,
    *,
    kill_on_timeout: bool = True,
) -> bool:
    if not pid_is_alive(pid):
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return True
        time.sleep(0.05)

    if not pid_is_alive(pid):
        return True

    if not kill_on_timeout:
        return False

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return False

    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return True
        time.sleep(0.05)

    return not pid_is_alive(pid)
