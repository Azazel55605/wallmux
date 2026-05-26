from __future__ import annotations

import subprocess

from wallmux.core.resources import (
    current_battery_state,
    current_gpu_load_percent,
    evaluate_resource_status,
)


def test_evaluate_resource_status_flags_high_cpu(monkeypatch) -> None:
    monkeypatch.setattr("wallmux.core.resources.current_cpu_load_ratio", lambda: 0.9)
    monkeypatch.setattr("wallmux.core.resources.current_gpu_load_percent", lambda: None)
    monkeypatch.setattr(
        "wallmux.core.resources.current_battery_state",
        lambda: (False, "ac"),
    )

    status = evaluate_resource_status(
        {"resource_mode": {"cpu_load_threshold": 0.8, "gpu_load_threshold": 90.0}}
    )

    assert status.high_cpu_load is True
    assert status.high_load is True


def test_current_gpu_load_percent_reads_nvidia_smi(monkeypatch) -> None:
    monkeypatch.setattr(
        "wallmux.core.resources.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["nvidia-smi"],
            0,
            stdout="12\n88\n",
            stderr="",
        ),
    )

    assert current_gpu_load_percent() == 88.0


def test_current_battery_state_reads_power_supply(tmp_path) -> None:
    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "status").write_text("Discharging\n", encoding="utf-8")

    assert current_battery_state(tmp_path) == (True, "battery")


def test_not_charging_counts_as_ac(tmp_path) -> None:
    battery = tmp_path / "BAT0"
    battery.mkdir()
    (battery / "status").write_text("Not charging\n", encoding="utf-8")

    assert current_battery_state(tmp_path) == (False, "ac")
