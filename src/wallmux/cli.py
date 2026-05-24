"""Command line entry point for Wallmux."""

from __future__ import annotations

import argparse
from pathlib import Path

from wallmux.backends.routing import route_wallpaper
from wallmux.core.autoswitch import choose_wallpaper, load_wallpaper_library
from wallmux.core.config import load_config, user_config_file, write_config
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
    set_cmd.add_argument(
        "--all-mode",
        choices=["simultaneous", "sequential"],
        help="How to apply --all across monitors.",
    )

    random_cmd = subparsers.add_parser("random", help="Set a random wallpaper.")
    random_target = random_cmd.add_mutually_exclusive_group()
    random_target.add_argument("--monitor")
    random_target.add_argument("--all", action="store_true")
    random_target.add_argument("--focused-monitor", action="store_true")
    random_cmd.add_argument(
        "--all-mode",
        choices=["simultaneous", "sequential"],
        help="How to apply --all across monitors.",
    )

    autoswitch = subparsers.add_parser("autoswitch", help="Control daemon autoswitching.")
    autoswitch_subparsers = autoswitch.add_subparsers(dest="autoswitch_command", required=True)
    autoswitch_subparsers.add_parser("status", help="Show autoswitch status.")
    autoswitch_now = autoswitch_subparsers.add_parser("now", help="Switch immediately.")
    autoswitch_now.add_argument("--mode", choices=["random", "name-up", "name-down"])
    autoswitch_set = autoswitch_subparsers.add_parser("set", help="Update autoswitch config.")
    enabled = autoswitch_set.add_mutually_exclusive_group()
    enabled.add_argument("--enable", action="store_true")
    enabled.add_argument("--disable", action="store_true")
    autoswitch_set.add_argument("--interval", type=float)
    autoswitch_set.add_argument("--mode", choices=["random", "name-up", "name-down"])
    autoswitch_set.add_argument("--target", choices=["all", "focused", "monitor"])
    autoswitch_set.add_argument("--monitor")

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
                if args.all_mode:
                    request["all_monitor_mode"] = args.all_mode
            elif args.focused_monitor:
                request["focused_monitor"] = True
            else:
                request["monitor"] = args.monitor

            if _send_daemon_command(request, "set"):
                return 0

        try:
            if args.all:
                results = set_wallpaper_for_all(args.file, mode=args.all_mode)
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

    if args.command == "random":
        request = {"command": "autoswitch-now", "mode": "random"}
        if args.focused_monitor:
            request["target"] = "focused"
        elif args.monitor:
            request["target"] = "monitor"
            request["monitor"] = args.monitor
        else:
            request["target"] = "all"
        if not args.direct:
            try:
                response = send_request(request)
            except DaemonUnavailable as error:
                print(f"wallmuxctl: {error}; running directly")
            else:
                if not response.get("ok"):
                    print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
                    return 1
                _print_results(response.get("results", []), "set")
                return 0

        try:
            results = _set_random_direct(args)
        except (ValueError, WallmuxError) as error:
            print(f"wallmuxctl: {error}")
            return 1
        _print_result_objects(results, "set")
        return 0

    if args.command == "autoswitch":
        return _handle_autoswitch(args)

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
            print(f"wallmuxd: not running ({error})")
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        print("wallmuxd: running")
        monitors = response.get("state", {}).get("monitors", {})
        if not monitors:
            print("no saved wallpapers")
            return 0
        for monitor, entry in monitors.items():
            pid = f" pid={entry['pid']}" if entry.get("pid") else ""
            print(f"{monitor}: {entry['file']} via {entry['backend']}{pid}")
        return 0

    return 1


def _handle_autoswitch(args) -> int:
    if args.autoswitch_command == "status":
        try:
            response = send_request({"command": "state"})
        except DaemonUnavailable as error:
            print(f"wallmuxd: not running ({error})")
            config = load_config()
            _print_autoswitch_config(config)
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        print("wallmuxd: running")
        autoswitch = response.get("daemon", {}).get("autoswitch", {})
        for key in ("enabled", "interval_seconds", "mode", "target", "monitor"):
            print(f"{key}: {autoswitch.get(key)}")
        print(f"next_switch_seconds: {autoswitch.get('next_switch_seconds', 0):.1f}")
        return 0

    if args.autoswitch_command == "now":
        try:
            response = send_request({"command": "autoswitch-now", "mode": args.mode})
        except DaemonUnavailable as error:
            print(f"wallmuxctl: autoswitch requires wallmuxd ({error})")
            return 1
        if not response.get("ok"):
            print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
            return 1
        print("wallmuxd: running")
        _print_results(response.get("results", []), "set")
        return 0

    config = load_config()
    autoswitch = config.setdefault("autoswitch", {})
    daemon_running = _daemon_running()
    if args.enable and not daemon_running:
        print("wallmuxctl: auto switching requires wallmuxd; start wallmuxd before enabling it")
        return 1
    if args.enable:
        autoswitch["enabled"] = True
    if args.disable:
        autoswitch["enabled"] = False
    if args.interval is not None:
        autoswitch["interval_seconds"] = args.interval
    if args.mode:
        autoswitch["mode"] = args.mode
    if args.target:
        autoswitch["target"] = args.target
    if args.monitor is not None:
        autoswitch["monitor"] = args.monitor
    write_config(config, user_config_file())

    if not daemon_running:
        print("wallmuxd: not running; config saved")
        return 0

    response = send_request({"command": "reload"})
    if not response.get("ok"):
        print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
        return 1
    print("wallmuxd: running; autoswitch config saved and reloaded")
    return 0


def _daemon_running() -> bool:
    try:
        response = send_request({"command": "state"})
    except DaemonUnavailable:
        return False
    return bool(response.get("ok"))


def _set_random_direct(args) -> list:
    config = load_config()
    item = choose_wallpaper(load_wallpaper_library(config), mode="random")
    if args.focused_monitor:
        return [set_wallpaper_for_focused(item.path, config=config)]
    if args.monitor:
        return [set_wallpaper(item.path, args.monitor, config=config)]
    return set_wallpaper_for_all(item.path, config=config, mode=args.all_mode)


def _print_autoswitch_config(config: dict) -> None:
    autoswitch = config.get("autoswitch", {})
    for key in ("enabled", "interval_seconds", "mode", "target", "monitor"):
        print(f"{key}: {autoswitch.get(key)}")


def _print_result_objects(results: list, verb: str) -> None:
    for result in results:
        pid = f" pid={result.pid}" if result.pid else ""
        print(f"{verb} {result.file} for {result.monitor} via {result.backend}{pid}")


def _print_results(results: list[dict], verb: str) -> None:
    if not results:
        print("no saved wallpapers")
        return
    for result in results:
        pid = f" pid={result['pid']}" if result.get("pid") else ""
        print(f"{verb} {result['file']} for {result['monitor']} via {result['backend']}{pid}")


def _send_daemon_command(request: dict, verb: str) -> bool:
    try:
        response = send_request(request)
    except DaemonUnavailable as error:
        print(f"wallmuxctl: {error}; running directly")
        return False

    if not response.get("ok"):
        print(f"wallmuxctl: {response.get('error', 'unknown daemon error')}")
        raise SystemExit(1)

    _print_results(response.get("results", []), verb)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
