"""awww backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AwwwBackend:
    command: str = "awww"
    transition_type: str = "grow"
    transition_duration: float = 0.8
    transition_fps: int = 60
    name: str = "awww"

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        return [
            self.command,
            "img",
            str(file),
            "--outputs",
            monitor,
            "--transition-type",
            self.transition_type,
            "--transition-duration",
            str(self.transition_duration),
            "--transition-fps",
            str(self.transition_fps),
        ]
