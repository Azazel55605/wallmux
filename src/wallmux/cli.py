"""Command line entry point for Wallmux."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from wallmux.backends.routing import route_wallpaper
from wallmux.core.autoswitch import choose_wallpaper, load_wallpaper_library
from wallmux.core.cache import (
    cache_clean_result_json,
    cache_rebuild_result_json,
    cache_stats,
    cache_stats_json,
    clean_cache,
    format_cache_clean_result,
    format_cache_rebuild_result,
    format_cache_stats,
    rebuild_cache,
)
from wallmux.core.config import load_config, user_config_file, write_config
from wallmux.core.doctor import doctor_report_json, format_doctor_report, run_doctor
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.mime import detect_wallpaper_type
from wallmux.core.monitors import list_monitors
from wallmux.core.profiles import (
    effective_config_for_profile,
    get_active_profile,
    list_profiles,
    switch_profile,
)
from wallmux.core.video import (
    VideoInspectionError,
    VideoOptimizationProgress,
    configured_video_profile,
    estimated_optimization_input_size,
    format_video_inspection,
    format_video_library_optimization_result,
    format_video_optimization_plan,
    format_video_optimization_result,
    inspect_video,
    optimize_video,
    optimize_video_library,
    plan_video_optimization,
    video_inspection_json,
    video_optimization_plan_json,
    video_optimization_result_json,
)
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

    profile = subparsers.add_parser("profile", help="Inspect or switch wallpaper profiles.")
    profile_subparsers = profile.add_subparsers(dest="profile_command", required=True)
    profile_subparsers.add_parser("list", help="List configured profiles.")
    profile_subparsers.add_parser("active", help="Show the active profile.")
    profile_use = profile_subparsers.add_parser("use", help="Switch active profile.")
    profile_use.add_argument("name")
    profile_use.add_argument("--category", default="")
    profile_use.add_argument("--subcategory", default="")

    restore = subparsers.add_parser("restore", help="Restore saved wallpaper state.")
    restore.set_defaults(command="restore")

    reload_config = subparsers.add_parser("reload", help="Reload wallmuxd config.")
    reload_config.set_defaults(command="reload")

    stop_video = subparsers.add_parser("stop-video", help="Stop tracked video wallpaper process.")
    stop_video.add_argument("--monitor", required=True)

    state = subparsers.add_parser("state", help="Print daemon state.")
    state.set_defaults(command="state")

    doctor = subparsers.add_parser("doctor", help="Check Wallmux environment health.")
    doctor.add_argument(
        "scope",
        nargs="?",
        choices=["all", "video"],
        default="all",
        help="Limit checks to a specific area.",
    )
    doctor.add_argument("--json", action="store_true", help="Print checks as JSON.")

    video = subparsers.add_parser("video", help="Inspect or optimize video wallpapers.")
    video_subparsers = video.add_subparsers(dest="video_command", required=True)
    video_inspect = video_subparsers.add_parser("inspect", help="Inspect video metadata.")
    video_inspect.add_argument("file", type=Path)
    video_inspect.add_argument("--json", action="store_true", help="Print metadata as JSON.")
    video_plan = video_subparsers.add_parser("plan", help="Plan video optimization.")
    video_plan.add_argument("file", type=Path)
    video_plan.add_argument(
        "--profile",
        choices=["compatibility", "balanced", "quality"],
        default="balanced",
    )
    video_plan.add_argument("--json", action="store_true", help="Print plan as JSON.")
    video_optimize = video_subparsers.add_parser(
        "optimize",
        help="Optimize a video wallpaper into the cache.",
    )
    video_optimize.add_argument("file", type=Path)
    video_optimize.add_argument(
        "--profile",
        choices=["compatibility", "balanced", "quality"],
        default="balanced",
    )
    video_optimize.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the optimization plan without running ffmpeg.",
    )
    video_optimize.add_argument(
        "--force",
        action="store_true",
        help="Optimize even when the source already matches the selected profile.",
    )
    video_optimize.add_argument("--json", action="store_true", help="Print plan as JSON.")
    video_optimize_library = video_subparsers.add_parser(
        "optimize-library",
        help="Optimize all video wallpapers in the active library.",
    )
    video_optimize_library.add_argument(
        "--profile",
        choices=["compatibility", "balanced", "quality"],
        default=None,
    )
    video_optimize_library.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the bulk plan without running ffmpeg.",
    )
    video_optimize_library.add_argument(
        "--force",
        action="store_true",
        help="Optimize even when a source already matches the selected profile.",
    )
    video_optimize_library.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the bulk operation.",
    )
    video_optimize_library.add_argument("--json", action="store_true", help="Print JSON.")

    cache = subparsers.add_parser("cache", help="Inspect and maintain Wallmux caches.")
    cache_subparsers = cache.add_subparsers(dest="cache_command", required=True)
    cache_stats_cmd = cache_subparsers.add_parser("stats", help="Show cache usage.")
    cache_stats_cmd.add_argument("--json", action="store_true", help="Print JSON.")
    cache_clean = cache_subparsers.add_parser("clean", help="Clean cached files.")
    cache_clean.add_argument("--videos", action="store_true", help="Only clean video cache.")
    cache_clean.add_argument("--thumbnails", action="store_true", help="Only clean thumbnails.")
    cache_clean.add_argument(
        "--policy",
        choices=["stale-only", "lru", "all"],
        default=None,
        help="Cleanup policy. Defaults to config.",
    )
    cache_clean.add_argument("--json", action="store_true", help="Print JSON.")
    cache_rebuild = cache_subparsers.add_parser("rebuild", help="Rebuild cached files.")
    cache_rebuild.add_argument("--videos", action="store_true", help="Only rebuild video cache.")
    cache_rebuild.add_argument(
        "--thumbnails",
        action="store_true",
        help="Only rebuild thumbnails.",
    )
    cache_rebuild.add_argument(
        "--force-videos",
        action="store_true",
        help="Re-encode videos even when they already match the optimization profile.",
    )
    cache_rebuild.add_argument("--json", action="store_true", help="Print JSON.")

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

    if args.command == "profile":
        return _handle_profile(args)

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
        daemon = response.get("daemon", {})
        print(f"uptime_seconds: {daemon.get('uptime_seconds', 0):.1f}")
        print(f"startup_restore_pending: {daemon.get('startup_restore_pending', False)}")
        autoswitch = daemon.get("autoswitch", {})
        print(
            "autoswitch: "
            f"enabled={autoswitch.get('enabled')} "
            f"mode={autoswitch.get('mode')} "
            f"profile={autoswitch.get('profile') or 'none'} "
            f"target={autoswitch.get('target')} "
            f"next={autoswitch.get('next_switch_seconds', 0):.1f}s"
        )
        inhibition = daemon.get("inhibition", {})
        print(
            "inhibition: "
            f"inhibited={inhibition.get('inhibited')} "
            f"manual_commands={inhibition.get('inhibit_manual_commands')} "
            f"reason={inhibition.get('reason') or 'none'}"
        )
        resource_mode = daemon.get("resource_mode", {})
        print(
            "resource_mode: "
            f"battery={resource_mode.get('battery_state', 'unknown')} "
            f"battery_behavior={resource_mode.get('battery_behavior', 'keep')} "
            f"high_load={resource_mode.get('high_load', False)} "
            f"high_load_behavior={resource_mode.get('high_load_behavior', 'keep')}"
        )
        video_optimization = daemon.get("video_optimization", {})
        print(
            "video_optimization: "
            f"running={video_optimization.get('running', 0)} "
            f"queued={video_optimization.get('queued', 0)} "
            f"max_concurrent={video_optimization.get('max_concurrent_jobs', 2)}"
        )
        if daemon.get("last_error"):
            last_error = daemon["last_error"]
            print(f"last_error: {last_error.get('message')}: {last_error.get('error')}")
        monitors = response.get("monitors") or response.get("state", {}).get("monitors", {})
        if not monitors:
            print("no saved wallpapers")
            return 0
        print("monitors:")
        for monitor, entry in monitors.items():
            pid = f" pid={entry['pid']}" if entry.get("pid") else ""
            connected = "connected" if entry.get("connected", True) else "missing"
            focused = " focused" if entry.get("focused") else ""
            file = entry.get("file") or "no wallpaper"
            backend = entry.get("backend") or "none"
            print(f"  {monitor}: {file} via {backend}{pid} [{connected}{focused}]")
        events = daemon.get("events", [])
        if events:
            print("recent_events:")
            for event in events[-5:]:
                print(f"  {event.get('time')} {event.get('kind')}: {event.get('message')}")
        return 0

    if args.command == "doctor":
        report = run_doctor(video_only=args.scope == "video")
        if args.json:
            print(doctor_report_json(report))
        else:
            print(format_doctor_report(report))
        return 1 if report.has_errors else 0

    if args.command == "video":
        return _handle_video(args)

    if args.command == "cache":
        return _handle_cache(args)

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
        print(f"profile: {autoswitch.get('profile') or 'none'}")
        print(f"next_switch_seconds: {autoswitch.get('next_switch_seconds', 0):.1f}")
        inhibition = response.get("daemon", {}).get("inhibition", {})
        print(f"inhibit_manual_commands: {inhibition.get('inhibit_manual_commands')}")
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


def _handle_profile(args) -> int:
    config = load_config()
    if args.profile_command == "list":
        profiles = list_profiles(config)
        if not profiles:
            print("no profiles configured")
            return 0
        active = get_active_profile(config)
        for profile in profiles:
            marker = "*" if active and profile == active else " "
            print(f"{marker} {profile.label}")
        return 0

    if args.profile_command == "active":
        active = get_active_profile(config)
        if active is None:
            print("no active profile")
            return 0
        print(active.label)
        return 0

    try:
        profile = switch_profile(
            args.name,
            category=args.category,
            subcategory=args.subcategory,
            config=config,
            after_write=_reload_daemon_if_running,
        )
    except ValueError as error:
        print(f"wallmuxctl: {error}")
        return 1

    if not _daemon_running():
        print(f"profile active: {profile.label}")
        print("wallmuxd: not running; config saved")
        return 0

    print(f"profile active: {profile.label}")
    print("wallmuxd: running; config reloaded")
    return 0


def _handle_video(args) -> int:
    if args.video_command == "inspect":
        try:
            inspection = inspect_video(args.file)
        except VideoInspectionError as error:
            print(f"wallmuxctl: {error}")
            return 1
        if args.json:
            print(video_inspection_json(inspection))
        else:
            print(format_video_inspection(inspection))
        return 0
    if args.video_command in {"plan", "optimize"}:
        if args.video_command == "optimize" and not args.dry_run:
            config = load_config()
            try:
                cache_before = cache_stats(config).optimized_videos.bytes
                progress = None if args.json else _video_progress_printer()
                result = optimize_video(
                    args.file,
                    profile=args.profile,
                    force=args.force,
                    config=config,
                    progress_callback=progress,
                )
                cache_after = cache_stats(config).optimized_videos.bytes
            except VideoInspectionError as error:
                print(f"wallmuxctl: {error}")
                return 1
            if progress is not None:
                print(file=sys.stderr)
            if args.json:
                print(video_optimization_result_json(result))
            else:
                print(format_video_optimization_result(result))
                print(f"cache before: {_format_cli_bytes(cache_before)}")
                print(f"cache after: {_format_cli_bytes(cache_after)}")
            return 0
        try:
            plan = plan_video_optimization(args.file, profile=args.profile, config=load_config())
        except VideoInspectionError as error:
            print(f"wallmuxctl: {error}")
            return 1
        if args.json:
            print(video_optimization_plan_json(plan))
        else:
            print(format_video_optimization_plan(plan))
        return 0
    if args.video_command == "optimize-library":
        config = effective_config_for_profile(load_config())
        profile = args.profile or configured_video_profile(config)
        items = load_wallpaper_library(config)
        video_count = sum(1 for item in items if item.wallpaper_type.value == "video")
        input_size = estimated_optimization_input_size(items)
        if args.dry_run:
            current_cache_size = cache_stats(config).optimized_videos.bytes
            payload = {
                "profile": profile,
                "videos": video_count,
                "estimated_input_size": input_size,
                "optimized_video_cache_size": current_cache_size,
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"profile: {profile}")
                print(f"videos: {video_count}")
                print(f"estimated input: {_format_cli_bytes(input_size)}")
                print(f"current optimized cache: {_format_cli_bytes(current_cache_size)}")
            return 0
        if not args.yes:
            print(
                "wallmuxctl: optimize-library can take a long time and use significant "
                "disk space; rerun with --yes to confirm"
            )
            print(f"videos: {video_count}")
            print(f"estimated input: {_format_cli_bytes(input_size)}")
            return 1
        progress = None if args.json else _video_library_progress_printer()
        cache_before = cache_stats(config).optimized_videos.bytes
        result = optimize_video_library(
            items,
            profile=profile,
            force=args.force,
            config=config,
            progress_callback=progress,
        )
        cache_after = cache_stats(config).optimized_videos.bytes
        if progress is not None:
            print(file=sys.stderr)
        if args.json:
            payload = result.as_dict()
            payload["cache"] = {
                "optimized_video_before": cache_before,
                "optimized_video_after": cache_after,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_video_library_optimization_result(result))
            print(f"cache before: {_format_cli_bytes(cache_before)}")
            print(f"cache after: {_format_cli_bytes(cache_after)}")
        return 0
    return 1


def _handle_cache(args) -> int:
    config = effective_config_for_profile(load_config())

    if args.cache_command == "stats":
        stats = cache_stats(config)
        if args.json:
            print(cache_stats_json(stats))
        else:
            print(format_cache_stats(stats))
        return 0

    include_videos, include_thumbnails = _cache_scope(args)

    if args.cache_command == "clean":
        result = clean_cache(
            config,
            include_videos=include_videos,
            include_thumbnails=include_thumbnails,
            policy=args.policy,
        )
        if args.json:
            print(cache_clean_result_json(result))
        else:
            print(format_cache_clean_result(result))
        return 1 if result.errors else 0

    if args.cache_command == "rebuild":
        items = load_wallpaper_library(config)
        result = rebuild_cache(
            items,
            config,
            include_videos=include_videos,
            include_thumbnails=include_thumbnails,
            force_videos=args.force_videos,
        )
        if args.json:
            print(cache_rebuild_result_json(result))
        else:
            print(format_cache_rebuild_result(result))
        return 1 if result.errors else 0

    return 1


def _cache_scope(args) -> tuple[bool, bool]:
    if args.videos and not args.thumbnails:
        return True, False
    if args.thumbnails and not args.videos:
        return False, True
    return True, True


def _daemon_running() -> bool:
    try:
        response = send_request({"command": "state"})
    except DaemonUnavailable:
        return False
    return bool(response.get("ok"))


def _reload_daemon_if_running(_profile=None) -> None:
    try:
        send_request({"command": "reload"})
    except DaemonUnavailable:
        return


def _set_random_direct(args) -> list:
    config = load_config()
    effective_config = effective_config_for_profile(config)
    item = choose_wallpaper(load_wallpaper_library(config), mode="random")
    if args.focused_monitor:
        return [set_wallpaper_for_focused(item.path, config=effective_config)]
    if args.monitor:
        return [set_wallpaper(item.path, args.monitor, config=effective_config)]
    return set_wallpaper_for_all(item.path, config=effective_config, mode=args.all_mode)


def _print_autoswitch_config(config: dict) -> None:
    autoswitch = config.get("autoswitch", {})
    for key in ("enabled", "interval_seconds", "mode", "target", "monitor"):
        print(f"{key}: {autoswitch.get(key)}")
    inhibition = config.get("inhibition", {})
    print(f"inhibit_manual_commands: {inhibition.get('inhibit_manual_commands', False)}")


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


def _video_progress_printer():
    started_at = time.monotonic()

    def print_progress(progress: VideoOptimizationProgress) -> None:
        percent = progress.percent
        if percent is None:
            percent_text = "  ?.?%"
            filled = 0
        else:
            percent_text = f"{percent:5.1f}%"
            filled = int((percent / 100) * 28)
        bar = "#" * filled + "-" * (28 - filled)
        elapsed = max(0.001, time.monotonic() - started_at)
        data_rate = _format_rate(progress.total_size, elapsed)
        out_time = _format_cli_duration(progress.out_time_seconds)
        duration = _format_cli_duration(progress.duration_seconds)
        speed = f" {progress.speed}" if progress.speed else ""
        print(
            f"\r[{bar}] {percent_text} {out_time}/{duration} {data_rate}{speed}",
            end="",
            file=sys.stderr,
            flush=True,
        )

    return print_progress


def _video_library_progress_printer():
    current = {"path": ""}
    inner = _video_progress_printer()

    def print_progress(path: Path, progress: VideoOptimizationProgress) -> None:
        if current["path"] != str(path):
            current["path"] = str(path)
            print(f"\n{path.name}", file=sys.stderr)
        inner(progress)

    return print_progress


def _format_rate(size_bytes: int | None, elapsed_seconds: float) -> str:
    if size_bytes is None:
        return "?/s"
    return f"{_format_cli_bytes(size_bytes / elapsed_seconds)}/s"


def _format_cli_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value:.1f} B"


def _format_cli_duration(value: float | None) -> str:
    if value is None:
        return "??:??"
    minutes, seconds = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
    return f"{int(minutes):02d}:{int(seconds):02d}"


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
