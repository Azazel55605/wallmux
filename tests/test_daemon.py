from __future__ import annotations

from pathlib import Path

from wallmux.core.config import load_config
from wallmux.core.daemon import WallmuxDaemon
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.state import WallmuxState, WallpaperEntry, load_state, save_state
from wallmux.core.wallpaper import CommandRunner, WallmuxError


class FakeRunner(CommandRunner):
    def __init__(self) -> None:
        self.runs: list[list[str]] = []
        self.starts: list[list[str]] = []
        self.next_pid = 9000

    def run(self, command: list[str]) -> None:
        self.runs.append(command)

    def start(self, command: list[str]) -> int:
        self.starts.append(command)
        self.next_pid += 1
        return self.next_pid


def sample_config(tmp_path: Path) -> dict:
    return load_config(tmp_path / "config.toml")


def sample_config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_daemon_handles_set_request(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        runner=runner,
        state_path=state_path,
        restore_on_startup=False,
    )

    response = daemon.handle_request(
        {
            "command": "set",
            "file": str(image),
            "monitor": "DP-1",
        }
    )

    assert response["ok"] is True
    assert response["results"][0]["backend"] == "awww"
    assert runner.runs[0][4] == "DP-1"


def test_daemon_reloads_config_for_set_request(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")
    config_path = sample_config_path(tmp_path)
    config = load_config(config_path)
    config["backend_rules"]["image"] = "swww"
    monkeypatch.setattr("wallmux.core.daemon.load_config", lambda *_args: config)
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=config_path,
        runner=runner,
        state_path=state_path,
        restore_on_startup=False,
    )

    response = daemon.handle_request(
        {
            "command": "set",
            "file": str(image),
            "monitor": "DP-1",
        }
    )

    assert response["ok"] is True
    assert response["results"][0]["backend"] == "swww"


def test_daemon_handles_reload_request(tmp_path: Path, monkeypatch) -> None:
    config = sample_config(tmp_path)
    config["backend_rules"]["image"] = "swww"
    monkeypatch.setattr("wallmux.core.daemon.load_config", lambda *_args: config)
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        state_path=tmp_path / "state.json",
        restore_on_startup=False,
    )

    response = daemon.handle_request({"command": "reload"})

    assert response == {"ok": True}
    assert daemon.config["backend_rules"]["image"] == "swww"


def test_daemon_handles_restore_request(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")
    save_state(
        WallmuxState(
            monitors={
                "DP-1": WallpaperEntry(
                    file=str(image),
                    backend="awww",
                    wallpaper_type="image",
                )
            }
        ),
        state_path,
    )
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        runner=runner,
        state_path=state_path,
        restore_on_startup=False,
    )

    response = daemon.handle_request({"command": "restore"})

    assert response["ok"] is True
    assert response["results"][0]["monitor"] == "DP-1"
    assert runner.runs[0][2] == str(image)


def test_daemon_startup_restore_failure_is_retryable(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def restore(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise WallmuxError("awww-daemon is not ready")
        return []

    monkeypatch.setattr("wallmux.core.daemon.restore_wallpapers", restore)
    monkeypatch.setattr("wallmux.core.daemon.time.monotonic", lambda: 100.0)
    config = sample_config(tmp_path)
    config["daemon"]["startup_restore_retry_seconds"] = 1.0
    daemon = WallmuxDaemon(
        config=config,
        config_path=sample_config_path(tmp_path),
        state_path=tmp_path / "state.json",
        restore_on_startup=True,
    )

    daemon._restore_on_startup()
    assert daemon.startup_restore_pending is True

    monkeypatch.setattr("wallmux.core.daemon.time.monotonic", lambda: 101.0)
    daemon.tick()

    assert calls == 2
    assert daemon.startup_restore_pending is False


def test_daemon_stops_tracked_video(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={
                "DP-1": WallpaperEntry(
                    file="/tmp/video.mp4",
                    backend="mpvpaper",
                    wallpaper_type="video",
                    pid=1234,
                )
            }
        ),
        state_path,
    )
    terminated: list[int] = []

    def terminate(pid: int) -> bool:
        terminated.append(pid)
        return True

    monkeypatch.setattr("wallmux.core.daemon.terminate_pid", terminate)
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        state_path=state_path,
        restore_on_startup=False,
    )

    response = daemon.handle_request({"command": "stop-video", "monitor": "DP-1"})

    assert response == {"ok": True, "stopped": True, "monitor": "DP-1"}
    assert terminated == [1234]
    assert load_state(state_path).monitors["DP-1"].pid is None


def test_daemon_cleans_stale_pids(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={
                "DP-1": WallpaperEntry(
                    file="/tmp/video.mp4",
                    backend="mpvpaper",
                    wallpaper_type="video",
                    pid=1234,
                )
            }
        ),
        state_path,
    )
    monkeypatch.setattr("wallmux.core.daemon.pid_is_alive", lambda pid: False)
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        state_path=state_path,
        restore_on_startup=False,
    )

    daemon.cleanup_stale_pids()

    assert load_state(state_path).monitors["DP-1"].pid is None


def test_daemon_pauses_and_resumes_tracked_videos_when_inhibited(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "state.json"
    save_state(
        WallmuxState(
            monitors={
                "DP-1": WallpaperEntry(
                    file="/tmp/video.mp4",
                    backend="mpvpaper",
                    wallpaper_type="video",
                    pid=1234,
                )
            }
        ),
        state_path,
    )
    paused: list[int] = []
    resumed: list[int] = []
    statuses = iter([True, False])

    monkeypatch.setattr(
        "wallmux.core.daemon.evaluate_inhibition",
        lambda config: type("Status", (), {"inhibited": next(statuses), "reason": "game"})(),
    )
    monkeypatch.setattr("wallmux.core.daemon.pause_pid", lambda pid: paused.append(pid) or True)
    monkeypatch.setattr("wallmux.core.daemon.resume_pid", lambda pid: resumed.append(pid) or True)
    config = sample_config(tmp_path)
    daemon = WallmuxDaemon(
        config=config,
        config_path=sample_config_path(tmp_path),
        state_path=state_path,
        restore_on_startup=False,
    )

    daemon._update_inhibition()
    daemon.next_inhibition_check_at = 0.0
    daemon._update_inhibition()

    assert paused == [1234]
    assert resumed == [1234]


def test_daemon_reports_invalid_json(tmp_path: Path) -> None:
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        state_path=tmp_path / "state.json",
        restore_on_startup=False,
    )

    response = daemon.handle_raw_request(b"{")

    assert response["ok"] is False
    assert "invalid JSON" in response["error"]


def test_daemon_reports_empty_state(tmp_path: Path) -> None:
    daemon = WallmuxDaemon(
        config=sample_config(tmp_path),
        config_path=sample_config_path(tmp_path),
        state_path=tmp_path / "state.json",
        restore_on_startup=False,
    )

    response = daemon.handle_request({"command": "state"})

    assert response["ok"] is True
    assert response["state"] == {"monitors": {}}
    assert response["daemon"]["running"] is True
    assert response["daemon"]["autoswitch"]["enabled"] is False


def test_send_request_reports_unavailable_daemon(tmp_path: Path) -> None:
    try:
        send_request(
            {"command": "state"},
            socket_path=tmp_path / "missing.sock",
            timeout_seconds=0.01,
        )
    except DaemonUnavailable as error:
        assert "wallmuxd is not available" in str(error)
    else:
        raise AssertionError("expected DaemonUnavailable")
