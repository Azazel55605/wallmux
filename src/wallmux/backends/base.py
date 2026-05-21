"""Shared backend protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class WallpaperBackend(Protocol):
    name: str

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        """Build the command used to set a wallpaper."""
