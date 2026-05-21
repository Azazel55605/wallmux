"""Command line entry point for Wallmux."""

from __future__ import annotations

import argparse
from pathlib import Path

from wallmux.backends.routing import route_wallpaper
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.mime import detect_wallpaper_type
from wallmux.core.monitors import list_monitors
from wallmux.core.wallpaper import (
    WallmuxError,
    restore_wallpapers,
    set_wallpaper,
    set_wallpaper_for_all,
    set_wallpaper_for_focused,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallmuxctl")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run commands directly instead of asking wallmuxd.",
    )
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
    target.add_argument("--focused-monitor", action="store_true")

    restore = subparsers.add_parser("restore", help="Restore saved wallpaper state.")
    restore.set_defaults(command="restore")

    reload_config = subparsers.add_parser("reload", help="Reload wallmuxd config.")
    reload_config.set_defaults(command="reload")

    stop_video = subparsers.add_parser("stop-video", help="Stop tracked video wallpaper process.")
    stop_video.add_argument("--monitor", required=True)

    state = subparsers.add_parser("state", help="Print daemon state.")
    state.set_defaults(command="state")

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
        if not args.direct:
            request = {"command": "set", "file": str(args.file)}
            if args.all:
                request["all"] = True
            elif args.focused_monitor:
                request["focused_monitor"] = True
            else:
                request["monitor"] = args.monitor

            if _send_daemon_command(request, "set"):
                return 0

        try:
            if args.all:
                results = set_wallpaper_for_all(args.file)
            elif args.focused_monitor:
                results = [set_wallpaper_for_focused(args.file)]
            else:
                results = [set_wallpaper(args.file, args.monitor)]
        except (ValueError, WallmuxError) as error:
            print(f"wallmuxctl: {error}")
            return 1

        for result in results:
            pid = f" pid={result.pid}" if result.pid else ""
            print(f"set {result.file} for {result.monitor} via {result.backend}{pid}")
        return 0

    if args.command == "restore":
        if not args.direct and _send_daemon_command({"command": "restore"}, "restored"):
            return 0

        try:
            results = restore_wallpapers()
        except (ValueError, WallmuxError) as error:
            print(f"wallmuxctl: {error}")
            return 1

        if not results:
            print("no saved wallpapers")
            return 0
        for result in results:
            pid = f" pid={result.pid}" if result.pid else ""
            print(f"restored {result.file} for {result.monitor} via {result.backend}{pid}")
        return 0

    if args.command == "reload":
        try:
            response = send_request({"command": "reload"})
        except DaemonUnavailable as error:
            print(f"wallmuxctl: {error}")
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        print("wallmuxd config reloaded")
        return 0

    if args.command == "stop-video":
        try:
            response = send_request({"command": "stop-video", "monitor": args.monitor})
        except DaemonUnavailable as error:
            print(f"wallmuxctl: {error}")
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        stopped = "stopped" if response.get("stopped") else "no tracked video process"
        print(f"{args.monitor}: {stopped}")
        return 0

    if args.command == "state":
        try:
            response = send_request({"command": "state"})
        except DaemonUnavailable as error:
            print(f"wallmuxctl: {error}")
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        monitors = response.get("state", {}).get("monitors", {})
        if not monitors:
            print("no saved wallpapers")
            return 0
        for monitor, entry in monitors.items():
            pid = f" pid={entry['pid']}" if entry.get("pid") else ""
            print(f"{monitor}: {entry['file']} via {entry['backend']}{pid}")
        return 0

    return 1


def _send_daemon_command(request: dict, verb: str) -> bool:
    try:
        response = send_request(request)
    except DaemonUnavailable as error:
        print(f"wallmuxctl: {error}; running directly")
        return False

    if not response.get("ok"):
        print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
        raise SystemExit(1)

    results = response.get("results", [])
    if not results:
        print("no saved wallpapers")
        return True

    for result in results:
        pid = f" pid={result['pid']}" if result.get("pid") else ""
        print(f"{verb} {result['file']} for {result['monitor']} via {result['backend']}{pid}")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
