from __future__ import annotations

from pathlib import Path

from wallmux.core.config import load_config
from wallmux.core.monitors import Monitor
from wallmux.core.state import load_state
from wallmux.core.transitions import TransitionKind
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


def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def sample_config(tmp_path: Path) -> dict:
    config = load_config(tmp_path / "config.toml")
    config["hooks"]["before_set"] = []
    config["hooks"]["after_set"] = []
    return config


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
    command = runner.runs[0]
    assert command[0:5] == ["awww", "img", str(image), "--outputs", "DP-1"]
    assert _option(command, "--transition-type") == "grow"
    assert _option(command, "--transition-step") == "90"
    assert _option(command, "--transition-duration") == "0.8"
    assert _option(command, "--transition-fps") == "60"
    assert _option(command, "--transition-angle") == "45.0"
    assert _option(command, "--transition-pos") == "center"
    assert "--invert-y" not in command
    assert _option(command, "--transition-bezier") == ".54,0,.34,.99"
    assert _option(command, "--transition-wave") == "20,20"
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
    assert runner.starts[0][0:3] == [
        "mpvpaper",
        "-o",
        (
            "no-config no-audio loop hwdec=auto profile=fast "
            "video-sync=display-resample interpolation=no scale=bilinear "
            "cscale=bilinear dscale=bilinear panscan=1.0 osd-level=0 msg-level=all=no"
        ),
    ]
    assert runner.starts[0][3:] == ["eDP-1", str(video)]
    state = load_state(state_path)
    assert state.monitors["eDP-1"].pid == 4201


def test_set_image_accepts_backend_overrides(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")

    result = set_wallpaper(
        image,
        "DP-1",
        config=sample_config(tmp_path),
        backend_override="swww",
        backend_config_overrides={
            "transition_type": "wave",
            "transition_step": 20,
            "transition_duration": 1.5,
            "transition_fps": 30,
            "transition_angle": 120,
            "transition_pos": "bottom-right",
            "invert_y": True,
            "transition_bezier": "0.0,0.0,1.0,1.0",
            "transition_wave": "32,12",
        },
        runner=runner,
        state_path=state_path,
    )

    assert result.backend == "swww"
    command = runner.runs[0]
    assert command[0:5] == ["swww", "img", str(image), "--outputs", "DP-1"]
    assert _option(command, "--transition-type") == "wave"
    assert _option(command, "--transition-step") == "20"
    assert _option(command, "--transition-duration") == "1.5"
    assert _option(command, "--transition-fps") == "30"
    assert _option(command, "--transition-angle") == "120"
    assert _option(command, "--transition-pos") == "bottom-right"
    assert "--invert-y" in command
    assert _option(command, "--transition-bezier") == "0.0,0.0,1.0,1.0"
    assert _option(command, "--transition-wave") == "32,12"


def test_set_image_accepts_hyprpaper_backend(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")

    result = set_wallpaper(
        image,
        "DP-1",
        config=sample_config(tmp_path),
        backend_override="hyprpaper",
        runner=runner,
        state_path=state_path,
    )

    assert result.backend == "hyprpaper"
    assert runner.runs == [
        ["hyprctl", "hyprpaper", "preload", str(image)],
        ["hyprctl", "hyprpaper", "wallpaper", f"DP-1,{image},cover"],
    ]
    state = load_state(state_path)
    assert state.monitors["DP-1"].backend == "hyprpaper"


def test_set_all_hyprpaper_runs_per_monitor_commands(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"")

    results = set_wallpaper_for_all(
        image,
        config=sample_config(tmp_path),
        backend_override="hyprpaper",
        runner=runner,
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1")],
        state_path=state_path,
    )

    assert [result.monitor for result in results] == ["DP-1", "HDMI-A-1"]
    assert ["hyprctl", "hyprpaper", "wallpaper", f"DP-1,{image},cover"] in runner.runs
    assert ["hyprctl", "hyprpaper", "wallpaper", f"HDMI-A-1,{image},cover"] in runner.runs


def test_gif_with_video_backend_tracks_process(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    gif = tmp_path / "animated.gif"
    gif.write_bytes(b"")

    result = set_wallpaper(
        gif,
        "DP-1",
        config=sample_config(tmp_path),
        backend_override="mpvpaper",
        backend_config_overrides={"options": "loop no-audio"},
        runner=runner,
        state_path=state_path,
    )

    assert result.backend == "mpvpaper"
    assert result.pid == 4201
    assert runner.starts == [["mpvpaper", "-o", "loop no-audio", "DP-1", str(gif)]]


def test_rejects_incompatible_backend_override(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")

    try:
        set_wallpaper(
            image,
            "DP-1",
            config=sample_config(tmp_path),
            backend_override="mpvpaper",
            runner=runner,
            state_path=state_path,
        )
    except Exception as error:
        assert "cannot handle image wallpapers" in str(error)
    else:
        raise AssertionError("expected incompatible backend override to fail")


def test_set_all_expands_current_monitors(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"")

    results = set_wallpaper_for_all(
        image,
        config=sample_config(tmp_path),
        runner=runner,
        mode="sequential",
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1")],
        state_path=state_path,
    )

    assert [result.monitor for result in results] == ["DP-1", "HDMI-A-1"]
    assert [command[4] for command in runner.runs] == ["DP-1", "HDMI-A-1"]


def test_set_all_images_uses_one_backend_command_for_all_outputs(tmp_path: Path) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.jpg"
    image.write_bytes(b"")
    config = sample_config(tmp_path)

    results = set_wallpaper_for_all(
        image,
        config=config,
        runner=runner,
        monitor_provider=lambda: [Monitor("DP-1"), Monitor("HDMI-A-1")],
        state_path=state_path,
    )

    assert [result.monitor for result in results] == ["DP-1", "HDMI-A-1"]
    assert len(runner.runs) == 1
    assert _option(runner.runs[0], "--outputs") == "DP-1,HDMI-A-1"
    state = load_state(state_path)
    assert sorted(state.monitors) == ["DP-1", "HDMI-A-1"]


def test_set_all_video_to_image_stops_videos_together(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    video = tmp_path / "wallpaper.mp4"
    image = tmp_path / "wallpaper.jpg"
    video.write_bytes(b"")
    image.write_bytes(b"")
    terminated: list[int] = []

    def terminate(pid: int, timeout_seconds: float, *, kill_on_timeout: bool) -> bool:
        terminated.append(pid)
        assert timeout_seconds == 2.0
        assert kill_on_timeout is True
        return True

    monkeypatch.setattr("wallmux.core.wallpaper.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminate)
    config = sample_config(tmp_path)

    def monitor_provider():
        return [Monitor("DP-1"), Monitor("HDMI-A-1")]

    set_wallpaper_for_all(
        video,
        config=config,
        runner=runner,
        monitor_provider=monitor_provider,
        state_path=state_path,
    )
    result = set_wallpaper_for_all(
        image,
        config=config,
        runner=runner,
        monitor_provider=monitor_provider,
        state_path=state_path,
    )

    assert [item.transition for item in result] == [
        TransitionKind.VIDEO_TO_IMAGE,
        TransitionKind.VIDEO_TO_IMAGE,
    ]
    assert sorted(terminated) == [4201, 4202]
    assert runner.runs[-1][0:2] == ["awww", "img"]
    assert _option(runner.runs[-1], "--outputs") == "DP-1,HDMI-A-1"


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

    def terminate(pid: int, timeout_seconds: float, *, kill_on_timeout: bool) -> bool:
        terminated.append(pid)
        assert timeout_seconds == 2.0
        assert kill_on_timeout is True
        return True

    monkeypatch.setattr("wallmux.core.wallpaper.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminate)

    config = sample_config(tmp_path)
    first = set_wallpaper(first_video, "DP-1", config=config, runner=runner, state_path=state_path)
    second = set_wallpaper(
        second_video,
        "DP-1",
        config=config,
        runner=runner,
        state_path=state_path,
    )

    assert first.transition is TransitionKind.FIRST_SET
    assert second.transition is TransitionKind.VIDEO_TO_VIDEO
    assert terminated == [4201]
    state = load_state(state_path)
    assert state.monitors["DP-1"].file == str(second_video)
    assert state.monitors["DP-1"].pid == 4202


def test_video_to_image_stops_tracked_video_before_image(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    video = tmp_path / "one.mp4"
    image = tmp_path / "two.png"
    video.write_bytes(b"")
    image.write_bytes(b"")
    terminated: list[int] = []

    def terminate(pid: int, timeout_seconds: float, *, kill_on_timeout: bool) -> bool:
        terminated.append(pid)
        return True

    monkeypatch.setattr("wallmux.core.wallpaper.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminate)

    config = sample_config(tmp_path)
    set_wallpaper(video, "DP-1", config=config, runner=runner, state_path=state_path)
    result = set_wallpaper(image, "DP-1", config=config, runner=runner, state_path=state_path)

    assert result.transition is TransitionKind.VIDEO_TO_IMAGE
    assert terminated == [4201]
    assert runner.runs
    assert load_state(state_path).monitors["DP-1"].pid is None


def test_basic_video_to_image_sets_image_before_stopping_video(
    tmp_path: Path,
    monkeypatch,
) -> None:
    events: list[str] = []

    class EventRunner(FakeRunner):
        def run(self, command: list[str]) -> None:
            events.append("run")
            super().run(command)

    runner = EventRunner()
    state_path = tmp_path / "state.json"
    video = tmp_path / "one.mp4"
    image = tmp_path / "two.png"
    video.write_bytes(b"")
    image.write_bytes(b"")

    def terminate(pid: int, timeout_seconds: float, *, kill_on_timeout: bool) -> bool:
        events.append("terminate")
        return True

    monkeypatch.setattr("wallmux.core.wallpaper.pid_is_alive", lambda pid: True)
    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminate)

    config = sample_config(tmp_path)
    set_wallpaper(video, "DP-1", config=config, runner=runner, state_path=state_path)
    set_wallpaper(image, "DP-1", config=config, runner=runner, state_path=state_path)

    assert events == ["run", "terminate"]


def test_image_to_image_keeps_native_backend_transition(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    first_image = tmp_path / "one.png"
    second_image = tmp_path / "two.png"
    first_image.write_bytes(b"")
    second_image.write_bytes(b"")
    terminated: list[int] = []
    monkeypatch.setattr("wallmux.core.wallpaper.terminate_pid", terminated.append)

    config = sample_config(tmp_path)
    set_wallpaper(first_image, "DP-1", config=config, runner=runner, state_path=state_path)
    result = set_wallpaper(
        second_image,
        "DP-1",
        config=config,
        runner=runner,
        state_path=state_path,
    )

    assert result.transition is TransitionKind.IMAGE_TO_IMAGE
    assert terminated == []
    assert runner.runs[-1][0:2] == ["awww", "img"]


def test_runs_hooks_around_backend_execution(tmp_path: Path, monkeypatch) -> None:
    runner = FakeRunner()
    state_path = tmp_path / "state.json"
    image = tmp_path / "wallpaper.png"
    image.write_bytes(b"")
    events: list[str] = []

    def run_hook_stage(stage, config, context):
        events.append(stage)

    monkeypatch.setattr("wallmux.core.wallpaper.run_hook_stage", run_hook_stage)

    set_wallpaper(
        image,
        "DP-1",
        config=sample_config(tmp_path),
        runner=runner,
        state_path=state_path,
    )

    assert events == ["before_set", "after_set"]
    assert runner.runs
