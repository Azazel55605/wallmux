"""Environment health checks for Wallmux."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from wallmux.core.config import load_config, user_config_file
from wallmux.core.hooks import hook_log_file
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.state import state_file
from wallmux.core.thumbnails import thumbnail_cache_dir


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    details: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: list[DoctorCheck]

    @property
    def has_errors(self) -> bool:
        return any(check.status == "error" for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == "warning" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.has_errors,
            "summary": {
                "ok": sum(1 for check in self.checks if check.status == "ok"),
                "warnings": sum(1 for check in self.checks if check.status == "warning"),
                "errors": sum(1 for check in self.checks if check.status == "error"),
            },
            "checks": [asdict(check) for check in self.checks],
        }


def run_doctor(*, video_only: bool = False, config: dict[str, Any] | None = None) -> DoctorReport:
    config = config or load_config()
    checks: list[DoctorCheck] = []
    if not video_only:
        checks.extend(_core_checks(config))
    checks.extend(_video_checks())
    return DoctorReport(checks)


def format_doctor_report(report: DoctorReport) -> str:
    labels = {
        "ok": "OK",
        "warning": "WARN",
        "error": "ERROR",
    }
    lines = []
    for check in report.checks:
        line = f"[{labels.get(check.status, check.status.upper()):5}] {check.name}: {check.message}"
        if check.details:
            line = f"{line} ({check.details})"
        lines.append(line)
    summary = report.as_dict()["summary"]
    lines.append(
        f"summary: {summary['ok']} ok, {summary['warnings']} warning, {summary['errors']} error"
    )
    return "\n".join(lines)


def doctor_report_json(report: DoctorReport) -> str:
    return json.dumps(report.as_dict(), indent=2, sort_keys=True)


def _core_checks(config: dict[str, Any]) -> list[DoctorCheck]:
    checks = [
        _command_check("hyprctl", required=True, reason="Hyprland monitor detection"),
        _hyprland_session_check(),
        _hyprland_monitor_check(),
        _daemon_check(),
        _path_check("config", user_config_file()),
        _path_check("state", state_file()),
        _path_check("thumbnail cache", thumbnail_cache_dir(), directory=True),
        _path_check("hook log", hook_log_file()),
    ]
    checks.extend(_backend_checks(config))
    checks.extend(_wallpaper_dir_checks(config))
    checks.extend(
        [
            _command_check("notify-send", required=False, reason="desktop notifications"),
            _command_check("wal", required=False, reason="optional pywal hooks"),
            _command_check("matugen", required=False, reason="optional matugen hooks"),
        ]
    )
    return checks


def _video_checks() -> list[DoctorCheck]:
    checks = [
        _command_check("ffmpeg", required=False, reason="video thumbnail extraction"),
        _command_check("ffprobe", required=False, reason="video metadata inspection"),
        _ffmpeg_hwaccels_check(),
        _command_check("vainfo", required=False, reason="VAAPI decode diagnostics"),
        _command_check("nvidia-smi", required=False, reason="NVIDIA GPU diagnostics"),
        _gpu_hint_check(),
    ]
    return checks


def _command_check(command: str, *, required: bool, reason: str) -> DoctorCheck:
    executable = _command_executable(command)
    resolved = shutil.which(executable)
    if resolved:
        return DoctorCheck(command, "ok", "installed", resolved)
    status = "error" if required else "warning"
    label = "missing required command" if required else "missing optional command"
    return DoctorCheck(command, status, label, reason)


def _backend_checks(config: dict[str, Any]) -> list[DoctorCheck]:
    backend_rules = config.get("backend_rules", {})
    backends = config.get("backends", {})
    configured = sorted(
        {
            str(value)
            for value in backend_rules.values()
            if isinstance(value, str) and value
        }
    )
    checks = []
    for backend in configured:
        backend_config = backends.get(backend, {})
        command = str(backend_config.get("command", backend))
        checks.append(
            _command_check(
                command,
                required=True,
                reason=f"configured {backend} backend",
            )
        )
    return checks


def _wallpaper_dir_checks(config: dict[str, Any]) -> list[DoctorCheck]:
    checks = []
    for raw_dir in config.get("general", {}).get("wallpaper_dirs", []):
        path = Path(str(raw_dir)).expanduser()
        if path.is_dir():
            checks.append(DoctorCheck("wallpaper dir", "ok", "available", str(path)))
        else:
            checks.append(DoctorCheck("wallpaper dir", "warning", "missing", str(path)))
    return checks


def _hyprland_session_check() -> DoctorCheck:
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return DoctorCheck("Hyprland session", "ok", "detected")
    return DoctorCheck(
        "Hyprland session",
        "warning",
        "HYPRLAND_INSTANCE_SIGNATURE is not set",
        "checks may be running outside Hyprland",
    )


def _hyprland_monitor_check() -> DoctorCheck:
    result = _run_command(["hyprctl", "monitors", "-j"])
    if result is None:
        return DoctorCheck("Hyprland monitors", "error", "hyprctl is not available")
    if result.returncode != 0:
        return DoctorCheck(
            "Hyprland monitors",
            "error",
            "hyprctl monitors failed",
            _compact_output(result),
        )
    try:
        monitors = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        return DoctorCheck("Hyprland monitors", "error", "invalid JSON", str(error))
    count = len(monitors)
    if count:
        return DoctorCheck("Hyprland monitors", "ok", f"{count} monitor(s) detected")
    return DoctorCheck("Hyprland monitors", "warning", "no monitors reported")


def _daemon_check() -> DoctorCheck:
    try:
        response = send_request({"command": "state"}, timeout_seconds=0.2)
    except DaemonUnavailable as error:
        return DoctorCheck("wallmuxd", "warning", "not running", str(error))
    if response.get("ok"):
        return DoctorCheck("wallmuxd", "ok", "running")
    return DoctorCheck("wallmuxd", "warning", "responded with error", str(response.get("error")))


def _path_check(name: str, path: Path, *, directory: bool = False) -> DoctorCheck:
    target = path if directory else path.parent
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return DoctorCheck(name, "error", "cannot create directory", f"{target}: {error}")
    if os.access(target, os.W_OK):
        return DoctorCheck(name, "ok", "writable", str(path))
    return DoctorCheck(name, "error", "not writable", str(target))


def _ffmpeg_hwaccels_check() -> DoctorCheck:
    result = _run_command(["ffmpeg", "-hide_banner", "-hwaccels"])
    if result is None:
        return DoctorCheck("ffmpeg hwaccels", "warning", "ffmpeg is missing")
    if result.returncode != 0:
        return DoctorCheck("ffmpeg hwaccels", "warning", "could not query", _compact_output(result))
    accelerators = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("hardware acceleration")
    ]
    if accelerators:
        return DoctorCheck("ffmpeg hwaccels", "ok", ", ".join(accelerators))
    return DoctorCheck("ffmpeg hwaccels", "warning", "none reported")


def _gpu_hint_check() -> DoctorCheck:
    result = _run_command(["lspci"])
    if result is None:
        return DoctorCheck("GPU hints", "warning", "lspci is missing")
    if result.returncode != 0:
        return DoctorCheck("GPU hints", "warning", "could not query lspci", _compact_output(result))
    gpu_lines = [
        line
        for line in result.stdout.splitlines()
        if "VGA compatible controller" in line
        or "3D controller" in line
        or "Display controller" in line
    ]
    if not gpu_lines:
        return DoctorCheck("GPU hints", "warning", "no GPU lines found")
    return DoctorCheck("GPU hints", "ok", f"{len(gpu_lines)} device(s)", "; ".join(gpu_lines))


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _compact_output(result: subprocess.CompletedProcess[str]) -> str:
    output = result.stderr.strip() or result.stdout.strip()
    return output.splitlines()[0] if output else f"exit {result.returncode}"


def _command_executable(command: str) -> str:
    try:
        parts = shlex.split(command)
    except ValueError:
        return command
    return parts[0] if parts else command
