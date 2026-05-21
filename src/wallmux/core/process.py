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


def terminate_pid(pid: int, timeout_seconds: float = 2.0) -> bool:
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

    return not pid_is_alive(pid)
