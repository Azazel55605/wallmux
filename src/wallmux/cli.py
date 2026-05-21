"""Command line entry point for Wallmux."""

from __future__ import annotations

import argparse
from pathlib import Path

from wallmux.backends.routing import route_wallpaper
from wallmux.core.mime import detect_wallpaper_type
from wallmux.core.monitors import list_monitors
from wallmux.core.state import load_state, save_wallpaper_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallmuxctl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="Detect wallpaper type and route.")
    detect.add_argument("file", type=Path)

    monitors = subparsers.add_parser("monitors", help="List Hyprland monitors.")
    monitors.set_defaults(command="monitors")

    set_cmd = subparsers.add_parser("set", help="Set a wallpaper.")
    set_cmd.add_argument("file", type=Path)
    target = set_cmd.add_mutually_exclusive_group(required=True)
    target.add_argument("--monitor")
    target.add_argument("--all", action="store_true")

    restore = subparsers.add_parser("restore", help="Print saved wallpaper state for now.")
    restore.set_defaults(command="restore")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "detect":
        wallpaper_type = detect_wallpaper_type(args.file)
        backend = route_wallpaper(wallpaper_type)
        print(f"{args.file}: {wallpaper_type.value} -> {backend}")
        return 0

    if args.command == "monitors":
        for monitor in list_monitors():
            marker = " focused" if monitor.focused else ""
            print(f"{monitor.name}{marker}")
        return 0

    if args.command == "set":
        wallpaper_type = detect_wallpaper_type(args.file)
        backend = route_wallpaper(wallpaper_type)
        monitor = "all" if args.all else args.monitor
        save_wallpaper_state(monitor, args.file, backend, wallpaper_type.value)
        print(f"saved {args.file} for {monitor} via {backend}")
        return 0

    if args.command == "restore":
        state = load_state()
        if not state.monitors:
            print("no saved wallpapers")
            return 0
        for monitor, entry in state.monitors.items():
            print(f"{monitor}: {entry.file} via {entry.backend}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
