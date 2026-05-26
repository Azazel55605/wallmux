from __future__ import annotations

import subprocess

from wallmux.core import doctor
from wallmux.core.doctor import DoctorCheck, run_doctor


def test_video_doctor_reports_hwaccels_and_gpu_hints(monkeypatch) -> None:
    def which(command: str) -> str | None:
        if command in {"ffmpeg", "ffprobe", "lspci"}:
            return f"/usr/bin/{command}"
        return None

    def run_command(command: list[str]):
        if command[:3] == ["ffmpeg", "-hide_banner", "-hwaccels"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Hardware acceleration methods:\nvaapi\ncuda\n",
                stderr="",
            )
        if command == ["lspci"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="00:02.0 VGA compatible controller: Intel Corporation Iris Xe\n",
                stderr="",
            )
        return None

    monkeypatch.setattr("wallmux.core.doctor.shutil.which", which)
    monkeypatch.setattr("wallmux.core.doctor._run_command", run_command)

    report = run_doctor(video_only=True, config={})
    checks = {check.name: check for check in report.checks}

    assert checks["ffmpeg"].status == "ok"
    assert checks["ffprobe"].status == "ok"
    assert checks["ffmpeg hwaccels"].message == "vaapi, cuda"
    assert checks["GPU hints"].status == "ok"
    assert checks["vainfo"].status == "warning"
    assert checks["nvidia-smi"].status == "warning"
    assert report.has_errors is False


def test_core_doctor_reports_missing_configured_backend(monkeypatch) -> None:
    def which(command: str) -> str | None:
        if command in {"hyprctl", "ffmpeg", "ffprobe"}:
            return f"/usr/bin/{command}"
        return None

    monkeypatch.setattr("wallmux.core.doctor.shutil.which", which)
    monkeypatch.setattr(
        "wallmux.core.doctor._hyprland_session_check",
        lambda: DoctorCheck("Hyprland session", "ok", "detected"),
    )
    monkeypatch.setattr(
        "wallmux.core.doctor._hyprland_monitor_check",
        lambda: DoctorCheck("Hyprland monitors", "ok", "1 monitor(s) detected"),
    )
    monkeypatch.setattr(
        "wallmux.core.doctor._daemon_check",
        lambda: DoctorCheck("wallmuxd", "warning", "not running"),
    )
    monkeypatch.setattr(
        "wallmux.core.doctor._path_check",
        lambda name, path, directory=False: DoctorCheck(name, "ok", "writable", str(path)),
    )
    monkeypatch.setattr(
        "wallmux.core.doctor._ffmpeg_hwaccels_check",
        lambda: DoctorCheck("ffmpeg hwaccels", "ok", "vaapi"),
    )
    monkeypatch.setattr(
        "wallmux.core.doctor._gpu_hint_check",
        lambda: DoctorCheck("GPU hints", "ok", "1 device(s)"),
    )

    report = run_doctor(
        config={
            "general": {"wallpaper_dirs": []},
            "backend_rules": {"image": "awww", "video": "mpvpaper"},
            "backends": {
                "awww": {"command": "awww"},
                "mpvpaper": {"command": "mpvpaper"},
            },
        },
    )

    backend_checks = [check for check in report.checks if check.name in {"awww", "mpvpaper"}]

    assert [(check.name, check.status) for check in backend_checks] == [
        ("awww", "error"),
        ("mpvpaper", "error"),
    ]
    assert report.has_errors is True


def test_format_doctor_report_includes_summary() -> None:
    report = doctor.DoctorReport(
        [
            DoctorCheck("one", "ok", "fine"),
            DoctorCheck("two", "warning", "soft problem"),
            DoctorCheck("three", "error", "hard problem"),
        ]
    )

    output = doctor.format_doctor_report(report)

    assert "[OK   ] one: fine" in output
    assert "[WARN ] two: soft problem" in output
    assert "[ERROR] three: hard problem" in output
    assert "summary: 1 ok, 1 warning, 1 error" in output
