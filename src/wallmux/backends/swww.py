"""swww backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SwwwBackend:
    command: str = "swww"
    transition_type: str = "grow"
    transition_step: int = 90
    transition_duration: float = 0.8
    transition_fps: int = 60
    transition_angle: float = 45.0
    transition_pos: str = "center"
    invert_y: bool = False
    transition_bezier: str = ".54,0,.34,.99"
    transition_wave: str = "20,20"
    name: str = "swww"

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        command = [
            self.command,
            "img",
            str(file),
            "--outputs",
            monitor,
            "--transition-type",
            self.transition_type,
            "--transition-step",
            str(self.transition_step),
            "--transition-duration",
            str(self.transition_duration),
            "--transition-fps",
            str(self.transition_fps),
            "--transition-angle",
            str(self.transition_angle),
            "--transition-pos",
            self.transition_pos,
            "--transition-bezier",
            self.transition_bezier,
            "--transition-wave",
            self.transition_wave,
        ]
        if self.invert_y:
            command.append("--invert-y")
        return command
