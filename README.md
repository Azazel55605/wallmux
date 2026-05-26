# Wallmux

Wallmux is a Hyprland-first wallpaper manager and orchestrator for Arch Linux.

It does not render wallpapers directly. Instead, it routes wallpapers to established backends:

- Images: `awww` by default, with `swww` and `hyprpaper` support.
- GIFs: `awww` by default, with `swww`, `mpvpaper`, and `gSlapper` support.
- Videos: `mpvpaper` first, with `gSlapper` support.
- Hooks: `pywal`, `matugen`, QuickShell reloads, and other desktop automation.

## Status

Wallmux has the core CLI, daemon, hooks, GUI v1, and state-aware transition switching in place.

The first useful MVP will:

- Detect image, GIF, and video files.
- Route images/GIFs to `awww`.
- Route videos to `mpvpaper`.
- Allow choosing a monitor.
- Save and restore wallpaper state.
- Provide a basic PySide6 thumbnail grid.
- Run optional hooks after setting wallpapers.

## Commands

```bash
wallmuxctl detect ~/Wallpapers/foo.png
wallmuxctl monitors
wallmuxctl set ~/Wallpapers/foo.png --monitor DP-1
wallmuxctl restore
wallmuxctl state
wallmuxctl random --all
wallmuxctl autoswitch status
wallmuxctl autoswitch set --enable --interval 300 --mode random --target all
wallmuxctl autoswitch now
wallmuxctl doctor
wallmuxctl doctor video
wallmuxctl reload
wallmuxctl stop-video --monitor DP-1
wallmuxd
wallmux-gui
```

By default, `wallmuxctl set` and `wallmuxctl restore` try to talk to `wallmuxd` first. If the daemon is not running, they fall back to direct execution. Use `--direct` to skip the daemon explicitly:

```bash
wallmuxctl --direct set ~/Wallpapers/foo.png --monitor DP-1
```

`wallmuxd` reloads config before `set` and `restore`, so hook edits are picked up automatically. You can also run `wallmuxctl reload` explicitly after editing config.

Auto switching is daemon-owned. If `wallmuxd` is not running, `wallmuxctl autoswitch status` reports that clearly and daemon-only actions fail with a daemon-required message. Manual `wallmuxctl random` can still fall back to direct execution.

Inhibition can optionally block daemon-routed manual wallpaper changes while a game/fullscreen/render rule is active. This affects GUI sets, daemon-backed `wallmuxctl set`, daemon-backed `wallmuxctl random`, `wallmuxctl autoswitch now`, and daemon-backed `restore`. It is disabled by default, and `wallmuxctl --direct ...` remains uninhibited.

## GUI

```bash
wallmux-gui
```

The GUI opens a wallpaper browser with folder selection, search, media-type filtering, thumbnails, monitor selection, backend selection, and a settings tab for global backend defaults, wallpaper folders, hooks, and transition-effect helpers.

GUI keyboard controls:

- `Arrow keys`: move through wallpapers
- `Enter` / `Return`: set the selected wallpaper
- `F11` / `Ctrl+Z`: toggle zen mode
- `Escape`: exit zen mode

The monitor selector includes an `All monitors` target. Backend controls are filtered by wallpaper type:

- Images: `awww`, `swww`, `hyprpaper`
- GIFs: `awww`, `swww`, `mpvpaper`, `gslapper`
- Videos: `mpvpaper`, `gslapper`

Backend options are global settings. Update them under `Settings -> Backend Defaults`; the browser uses the saved defaults whenever it sets a wallpaper.

`awww` and `swww` expose the full image transition set:

- `none`, `simple`, `fade`, `left`, `right`, `top`, `bottom`
- `wipe`, `wave`, `grow`, `center`, `any`, `outer`, `random`

The global backend defaults also include transition step, duration, FPS, angle, position, invert-y, bezier curve, and wave dimensions for `awww`/`swww`, plus `hyprpaper` command and fit mode settings.

`hyprpaper` support uses `hyprctl hyprpaper preload` followed by `hyprctl hyprpaper wallpaper`, so the `hyprpaper` daemon must already be running with IPC enabled.

Backend fallbacks are conservative. By default, `awww` can fall back to `swww` for compatible image/GIF sets. `hyprpaper` is opt-in as a fallback because it uses a different daemon model. Explicit per-wallpaper backend choices do not fall back; they fail clearly so testing a specific backend stays honest.

```toml
[backend_fallbacks]
awww = ["swww"]
swww = []
hyprpaper = []
mpvpaper = []
gslapper = []
```

Fallback chains can also be edited under `Settings -> Backends -> Fallback Chains`.

The GUI requests a dialog-style Qt window so Hyprland can treat it like a floating manager window by default.
Its Wayland app id is `wallmux-gui` and its window title is `wallmux`, so Hyprland rules can match either:

```lua
hl.window_rule({
    match = { class = "^(wallmux-gui)$" },
    float = true,
    size = "800 600",
    center = true,
})
```

For Qt theme diagnostics:

```bash
wallmux-gui --theme-debug
```

## Config

Wallmux stores user config at:

```text
~/.config/wallmux/config.toml
```

If the file does not exist, Wallmux creates it from the packaged defaults. Future default config changes are merged automatically: changed user values are kept, new defaults are added, and removed defaults are pruned.

## Hooks

Wallmux supports `before_set` and `after_set` hooks in `~/.config/wallmux/config.toml`.

Supported placeholders:

- `{file}`
- `{monitor}`
- `{backend}`
- `{mime}`
- `{basename}`
- `{thumbnail}`
- `{source_for_colors}`

For images, `{source_for_colors}` is the wallpaper file. For videos, it is the generated thumbnail when available. Hook failures are logged to `~/.local/state/wallmux/hooks.log` and do not roll back wallpaper changes.

## Transitions

Wallmux keeps switching simple and state-aware:

- image -> image: use the native image backend transition
- image -> video: start the video backend and update monitor ownership
- video -> image: stop the tracked video process before setting the image
- video -> video: stop the tracked old video process before starting the new one

Video cleanup is controlled by:

```toml
[transitions]
video_stop_timeout_seconds = 2.0
kill_video_on_timeout = true
```

The `All monitors` target can apply wallpapers either together or one by one:

```toml
[general]
all_monitor_mode = "simultaneous" # or "sequential"
```

For `awww` and `swww`, simultaneous mode sends one command with all outputs joined, so `any` and `random` transitions choose one shared effect across monitors. `hyprpaper` uses per-monitor IPC commands because its target syntax is monitor-specific.

Auto switching is configured with:

```toml
[autoswitch]
enabled = false
interval_seconds = 300
mode = "random" # random, name-up, or name-down
target = "all"  # all, focused, or monitor
monitor = ""
```

Wallmux can inhibit auto switching and pause tracked video wallpapers while specific apps are active:

```toml
[inhibition]
enabled = true
check_interval_seconds = 5.0
pause_autoswitch = true
pause_videos = true
inhibit_manual_commands = false
fullscreen = true
process_names = ["gamescope", "gamemode", "wine64", "wineserver"]
class_patterns = []
title_patterns = []
```

Process names are checked with `pgrep -x`. Class/title patterns are optional regular expressions matched against Hyprland clients from `hyprctl clients -j`.

Desktop notifications use `notify-send` by default:

```toml
[notifications]
enabled = true
switched_wallpaper = true
switching_failed = true
command = "notify-send"
app_name = "Wallmux"
icon = "wallmux-gui"
desktop_entry = "wallmux-gui"
```

The default `mpvpaper` options ignore the user's mpv config, suppress mpv status output, crop/fill mixed aspect-ratio monitors, and use cheaper scaling for large videos:

```toml
[backends.mpvpaper]
options = "no-config no-audio loop hwdec=auto profile=fast video-sync=display-resample interpolation=no scale=bilinear cscale=bilinear dscale=bilinear panscan=1.0 osd-level=0 msg-level=all=no"
```

Optional transition effect helpers can call external commands for fade overlays, screenshot bridges, or QuickShell integration. They are disabled by default:

```toml
[transitions.effects]
fade_overlay = false
fade_command = ""
screenshot_bridge = false
screenshot_command = ""
quickshell_overlay = false
quickshell_command = ""
timeout_seconds = 2.0
```

Supported transition placeholders are `{monitor}`, `{from_file}`, `{to_file}`, `{from_backend}`, `{to_backend}`, `{transition}`, and `{stage}`.

Wallmux also ships with basic transition orchestration enabled by default:

```toml
[transitions.basic]
enabled = true
set_image_before_stopping_video = true
```

For `video -> image`, this sets the image backend first and then stops the old video processes, reducing visible blank gaps without requiring a custom overlay.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Build

```bash
python -m build
```

See `docs/PACKAGING.md` for packaging notes.

For quick local wheel testing with an isolated Python environment:

```bash
make pipx-install
make pipx-uninstall
```

For active-environment pip testing:

```bash
make install
make uninstall
```

## Desktop Integration

For local `pipx` testing:

```bash
make install-desktop
make install-service
systemctl --user enable --now wallmux.service
```

Hyprland startup:

```ini
exec-once = systemctl --user start wallmux.service
```

Hyprland 0.55 Lua:

```lua
hl.exec_cmd("systemctl --user start wallmux.service")
```

Packaging assets live in `packaging/`, including a desktop file, icon, systemd user service, and Arch `PKGBUILD` template.
