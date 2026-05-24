"""hyprpaper backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HyprpaperBackend:
    command: str = "hyprctl"
    fit_mode: str = "cover"
    name: str = "hyprpaper"

    def build_set_command(self, file: Path, monitor: str) -> list[list[str]]:
        wallpaper_target = f"{monitor},{file}"
        if self.fit_mode:
            wallpaper_target = f"{wallpaper_target},{self.fit_mode}"
        return [
            [self.command, "hyprpaper", "preload", str(file)],
            [self.command, "hyprpaper", "wallpaper", wallpaper_target],
        ]

    def build_unload_command(self, file: Path) -> list[str]:
        return [self.command, "hyprpaper", "unload", str(file)]
