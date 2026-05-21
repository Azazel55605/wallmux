"""gSlapper backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GslapperBackend:
    command: str = "gslapper"
    name: str = "gslapper"

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        return [self.command, "--monitor", monitor, str(file)]
