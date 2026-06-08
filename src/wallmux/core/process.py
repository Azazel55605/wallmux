"""Process helpers for backend ownership."""

from __future__ import annotations

import os
import signal
import threading
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


def terminate_pid_async(
    pid: int,
    timeout_seconds: float = 2.0,
    *,
    kill_on_timeout: bool = True,
) -> bool:
    """Request termination now and supervise cleanup without blocking the caller."""
    if not pid_is_alive(pid):
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False

    thread = threading.Thread(
        target=_finish_pid_termination,
        args=(pid, timeout_seconds, kill_on_timeout),
        daemon=True,
        name=f"wallmux-stop-{pid}",
    )
    thread.start()
    return True


def _finish_pid_termination(
    pid: int,
    timeout_seconds: float,
    kill_on_timeout: bool,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_is_alive(pid):
            return
        time.sleep(0.05)

    if not kill_on_timeout or not pid_is_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def pause_pid(pid: int) -> bool:
    if not pid_is_alive(pid):
        return False
    try:
        os.kill(pid, signal.SIGSTOP)
    except ProcessLookupError:
        return False
    return True


def resume_pid(pid: int) -> bool:
    if not pid_is_alive(pid):
        return False
    try:
        os.kill(pid, signal.SIGCONT)
    except ProcessLookupError:
        return False
    return True
