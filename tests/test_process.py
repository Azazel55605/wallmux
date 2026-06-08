from __future__ import annotations

import signal

from wallmux.core.process import terminate_pid_async


def test_terminate_pid_async_signals_and_returns_without_waiting(monkeypatch) -> None:
    signals: list[tuple[int, signal.Signals]] = []
    started: list[bool] = []

    class FakeThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            started.append(True)

    monkeypatch.setattr("wallmux.core.process.pid_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        "wallmux.core.process.os.kill",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    monkeypatch.setattr("wallmux.core.process.threading.Thread", FakeThread)

    assert terminate_pid_async(42, 2.0, kill_on_timeout=True) is True
    assert signals == [(42, signal.SIGTERM)]
    assert started == [True]
