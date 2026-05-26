"""Best-effort system resource mode checks."""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResourceStatus:
    on_battery: bool | None = None
    battery_state: str = "unknown"
    cpu_load_ratio: float | None = None
    gpu_load_percent: float | None = None
    high_cpu_load: bool = False
    high_gpu_load: bool = False

    @property
    def high_load(self) -> bool:
        return self.high_cpu_load or self.high_gpu_load

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["high_load"] = self.high_load
        return data


def resource_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("resource_mode", {})


def battery_behavior(config: dict[str, Any]) -> str:
    return str(resource_config(config).get("battery_behavior", "keep"))


def high_load_behavior(config: dict[str, Any]) -> str:
    return str(resource_config(config).get("high_load_behavior", "keep"))


def evaluate_resource_status(config: dict[str, Any]) -> ResourceStatus:
    resources = resource_config(config)
    cpu_ratio = current_cpu_load_ratio()
    gpu_percent = current_gpu_load_percent()
    cpu_threshold = float(resources.get("cpu_load_threshold", 0.85))
    gpu_threshold = float(resources.get("gpu_load_threshold", 85.0))
    on_battery, battery_state = current_battery_state()
    return ResourceStatus(
        on_battery=on_battery,
        battery_state=battery_state,
        cpu_load_ratio=cpu_ratio,
        gpu_load_percent=gpu_percent,
        high_cpu_load=cpu_ratio is not None and cpu_ratio >= cpu_threshold,
        high_gpu_load=gpu_percent is not None and gpu_percent >= gpu_threshold,
    )


def current_cpu_load_ratio() -> float | None:
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        return None
    cpu_count = os.cpu_count() or 1
    return load / cpu_count


def current_gpu_load_percent() -> float | None:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    values = []
    for line in result.stdout.splitlines():
        try:
            values.append(float(line.strip()))
        except ValueError:
            continue
    return max(values) if values else None


def current_battery_state(
    power_supply_root: Path = Path("/sys/class/power_supply"),
) -> tuple[bool | None, str]:
    if not power_supply_root.exists():
        return None, "unknown"
    states = []
    for battery in power_supply_root.glob("BAT*"):
        status_path = battery / "status"
        if not status_path.exists():
            continue
        try:
            states.append(status_path.read_text(encoding="utf-8").strip().casefold())
        except OSError:
            continue
    if not states:
        return None, "unknown"
    if any(state == "discharging" for state in states):
        return True, "battery"
    return False, "ac"
