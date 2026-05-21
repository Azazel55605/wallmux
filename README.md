# Wallmux

Wallmux is a Hyprland-first wallpaper manager and orchestrator for Arch Linux.

It does not render wallpapers directly. Instead, it routes wallpapers to established backends:

- Images and GIFs: `awww` by default, with `swww` support planned.
- Videos: `mpvpaper` first, with `gSlapper` support planned.
- Hooks: `pywal`, `matugen`, QuickShell reloads, and other desktop automation.

## Early Status

This repository is in Phase 0: project structure, planning, and a thin CLI prototype.

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

## GUI

```bash
wallmux-gui
```

The GUI opens a wallpaper browser with folder selection, search, media-type filtering, thumbnails, monitor selection, backend preview, and a settings tab for wallpaper folders.

GUI keyboard controls:

- `Arrow keys`: move through wallpapers
- `Enter` / `Return`: set the selected wallpaper
- `F11` / `Ctrl+Z`: toggle zen mode
- `Escape`: exit zen mode

The GUI requests a dialog-style Qt window so Hyprland can treat it like a floating manager window by default.

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
