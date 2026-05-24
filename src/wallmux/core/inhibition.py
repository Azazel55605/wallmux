"""Hyprland client based wallpaper inhibition."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HyprlandClient:
    class_name: str
    title: str
    fullscreen: bool = False


@dataclass(frozen=True)
class InhibitionStatus:
    inhibited: bool
    reason: str = ""


def inhibition_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("inhibition", {})


def inhibition_enabled(config: dict[str, Any]) -> bool:
    return bool(inhibition_config(config).get("enabled", True))


def inhibition_interval(config: dict[str, Any]) -> float:
    return max(1.0, float(inhibition_config(config).get("check_interval_seconds", 5.0)))


def pause_autoswitch(config: dict[str, Any]) -> bool:
    return bool(inhibition_config(config).get("pause_autoswitch", True))


def pause_videos(config: dict[str, Any]) -> bool:
    return bool(inhibition_config(config).get("pause_videos", True))


def list_clients() -> list[HyprlandClient]:
    result = subprocess.run(
        ["hyprctl", "clients", "-j"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    payload = json.loads(result.stdout)
    return [
        HyprlandClient(
            class_name=str(client.get("class", "")),
            title=str(client.get("title", "")),
            fullscreen=bool(client.get("fullscreen", False)),
        )
        for client in payload
    ]


def evaluate_inhibition(
    config: dict[str, Any],
    *,
    clients: list[HyprlandClient] | None = None,
    process_checker: Any | None = None,
) -> InhibitionStatus:
    if not inhibition_enabled(config):
        return InhibitionStatus(False)

    rules = inhibition_config(config)
    checker = process_checker or process_is_running
    for process_name in rules.get("process_names", []):
        if checker(str(process_name)):
            return InhibitionStatus(True, f"process: {process_name}")

    clients = clients if clients is not None else list_clients()
    if rules.get("fullscreen", True):
        for client in clients:
            if client.fullscreen:
                return InhibitionStatus(True, f"fullscreen: {client.class_name}")

    class_patterns = [re.compile(pattern) for pattern in rules.get("class_patterns", [])]
    title_patterns = [re.compile(pattern) for pattern in rules.get("title_patterns", [])]
    for client in clients:
        if _matches(class_patterns, client.class_name):
            return InhibitionStatus(True, f"class: {client.class_name}")
        if _matches(title_patterns, client.title):
            return InhibitionStatus(True, f"title: {client.title}")

    return InhibitionStatus(False)


def process_is_running(process_name: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-x", process_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _matches(patterns: list[re.Pattern], value: str) -> bool:
    return any(pattern.search(value) for pattern in patterns)
