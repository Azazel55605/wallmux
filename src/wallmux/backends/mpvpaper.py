"""mpvpaper backend command builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MpvpaperBackend:
    command: str = "mpvpaper"
    options: str = "no-audio loop hwdec=auto"
    hardware_decoding: str = "automatic"
    name: str = "mpvpaper"

    def build_set_command(self, file: Path, monitor: str) -> list[str]:
        options = _with_hardware_decoding(self.options, self.hardware_decoding)
        return [self.command, "-o", options, monitor, str(file)]


def _with_hardware_decoding(options: str, mode: str) -> str:
    hwdec = {
        "automatic": "auto-safe",
        "software": "no",
        "hardware": "auto",
    }.get(mode, "auto-safe")
    tokens = [token for token in options.split() if not token.startswith("hwdec=")]
    tokens.append(f"hwdec={hwdec}")
    return " ".join(tokens)
