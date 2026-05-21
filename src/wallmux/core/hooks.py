"""Hook command formatting."""

from __future__ import annotations

from string import Formatter

SUPPORTED_PLACEHOLDERS = {
    "file",
    "monitor",
    "backend",
    "mime",
    "basename",
    "thumbnail",
    "source_for_colors",
}


def format_hook(command: str, values: dict[str, str]) -> str:
    fields = {
        field_name
        for _, field_name, _, _ in Formatter().parse(command)
        if field_name is not None
    }
    unsupported = fields - SUPPORTED_PLACEHOLDERS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsupported hook placeholder(s): {names}")
    return command.format(**values)
