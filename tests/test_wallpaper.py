from __future__ import annotations

from pathlib import Path

from wallmux.core.config import load_config
from wallmux.core.monitors import Monitor
from wallmux.core.state import load_state
from wallmux.core.wallpaper import (
    CommandRunner,
    restore_wallpapers,
    set_wallpaper,
    set_wallpaper_for_all,
    set_wallpaper_for_focused,
)


class FakeRunner(CommandRunner):
    def __init__(self) -> None:
        self.runs: list[list[str]] = []
        self.starts: list[list[str]] = []
        self.next_pid = 4200

    def run(self, command: list[str]) -> None:
        self.runs.append(command)

    def start(self, command: list[str]) -> int:
        self.starts.append(command)
        self.next_pid += 1
        return self.next_pid


def sample_config(tmp_path: Path) -> dict:
    return load_config(tmp_path / "config.toml")


def test_set_image_executes_awww_and_saves_state(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")

    result = set_wallpaper(
        image,
        "DP-1",
        config=sample_config(tmp_path),
        runner=runner,
        state_path=state_path,
    )

    assert result.backend == "awww"
    assert runner.runs == [
        [
            "awww",
            "img",
            str(image),
            "--outputs",
            "DP-1",
            "--transition-type",
            "grow",
            "--transition-duration",
            "0.8",
            "--transition-fps",
            "60",
        ]
    ]
    state = load_state(state_path)
    assert state.monitors["DP-1"].file == str(image)
    assert state.monitors["DP-1"].pid is None


def test_set_video_starts_mpvpaper_and_saves_pid(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    video = tmp_path / "wallpaper.webm"
    video.write_bytes(b"")

    result = set_wallpaper(
        video,
        "eDP-1",
        config=sample_config(tmp_path),
        runner=runner,
        state_path=state_path,
    )

    assert result.backend == "mpvpaper"
    assert result.pid == 4201
    assert runner.starts == [
        ["mpvpaper", "-o", "no-audio loop hwdec=auto", "eDP-1", str(video)]
    ]
    state = load_state(state_path)
    assert state.monitors["eDP-1"].pid == 4201


def test_set_all_expands_current_monitors(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"")

    results = set_wallpaper_for_all(
        image,
        config=sample_config(tmp_path),
        runner=runner,
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1")],
        state_path=state_path,
    )

    assert [result.monitor for result in results] == ["DP-1", "HDMI-A-1"]
    assert [command[4] for command in runner.runs] == ["DP-1", "HDMI-A-1"]


def test_set_focused_uses_focused_monitor(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"")

    result = set_wallpaper_for_focused(
        image,
        config=sample_config(tmp_path),
        runner=runner,
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1", focused=True)],
        state_path=state_path,
    )

    assert result.monitor == "HDMI-A-1"
    assert runner.runs[0][4] == "HDMI-A-1"


def test_restore_executes_saved_state(tmp_path: Path) -> None:
    first_runner = FakeRunner()
    restore_runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "restore.png"
    image.write_bytes(b"")
    config = sample_config(tmp_path)
    set_wallpaper(image, "DP-1", config=config, runner=first_runner, state_path=state_path)

    results = restore_wallpapers(config=config, runner=restore_runner, state_path=state_path)

    assert [result.monitor for result in results] == ["DP-1"]
    assert len(restore_runner.runs) == 1
    assert restore_runner.runs[0][2] == str(image)


def test_replaces_tracked_video_process(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    first_video = tmp_path / "one.mp4"
    second_video = tmp_path / "two.mp4"
    first_video.write_bytes(b"")
    second_video.write_bytes(b"")
    terminated: list[int] = []

    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminated.append)

    config = sample_config(tmp_path)
    set_wallpaper(first_video, "DP-1", config=config, runner=runner, state_path=state_path)
    set_wallpaper(second_video, "DP-1", config=config, runner=runner, state_path=state_path)

    assert terminated == [4201]
    state = load_state(state_path)
    assert state.monitors["DP-1"].file == str(second_video)
    assert state.monitors["DP-1"].pid == 4202
