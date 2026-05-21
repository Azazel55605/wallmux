"""mpvpaper backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MpvpaperBackend:
    command: str = "mpvpaper"
    options: str = "no-audio loop hwdec=auto"
    name: str = "mpvpaper"

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        return [self.command, "-o", self.options, monitor, str(file)]
