# Wallmux Project Plan

## Goal

Build a Hyprland-first wallpaper manager and orchestrator for Arch Linux.

Wallmux should not render wallpapers itself. It should act as a smart control layer above existing wallpaper backends:

- `awww` or `swww` for images and GIFs with transitions.
- `mpvpaper` or `gSlapper` for videos.
- Optional hooks for `pywal`, `matugen`, QuickShell reloads, and desktop automation.

## Philosophy

```text
Do not render wallpapers yourself.
Do not replace awww, swww, mpvpaper, or gSlapper.
Be the smart control layer above them.
```

Wallmux focuses on backend routing, monitor state, clean process management, a usable GUI, hooks, and restore behavior.

## Stack

- Python
- PySide6
- SQLite
- TOML
- platformdirs
- Pillow
- python-magic with fallback MIME detection
- pytest
- ruff

## Entry Points

```text
wallmuxctl
    Scriptable CLI for Hyprland keybinds, Wofi/Rofi menus, shell scripts, and automation.

wallmuxd
    Background daemon that owns runtime state, restores wallpapers, and tracks video processes.

wallmux-gui
    PySide6 wallpaper browser and settings UI.
```

## Initial Repository Layout

```text
wallmux/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── config/
│   └── default.toml
├── docs/
│   └── PROJECT_PLAN.md
├── src/
│   └── wallmux/
│       ├── __init__.py
│       ├── cli.py
│       ├── daemon.py
│       ├── gui.py
│       ├── core/
│       │   ├── config.py
│       │   ├── hooks.py
│       │   ├── mime.py
│       │   ├── monitors.py
│       │   ├── process.py
│       │   ├── state.py
│       │   └── thumbnails.py
│       └── backends/
│           ├── awww.py
│           ├── base.py
│           ├── gslapper.py
│           ├── mpvpaper.py
│           ├── routing.py
│           └── swww.py
└── tests/
    ├── test_backend_routing.py
    ├── test_config.py
    └── test_mime.py
```

## Backend Strategy

Default routes:

```text
Images -> awww
GIFs   -> awww
Videos -> mpvpaper
```

The backend modules should build commands, while higher-level services decide when to stop or replace monitor-owned processes.

## Switching Rules

```text
image -> image:
    call awww directly

image -> video:
    stop or hide image backend for that monitor if needed
    start mpvpaper
    update state

video -> image:
    stop mpvpaper process for that monitor
    call awww
    update state

video -> video:
    replace mpvpaper process cleanly
```

Avoid broad process killing. Track PIDs per monitor.

## Config Shape

The default config lives at `config/default.toml`.

Important sections:

- `[general]`
- `[backend_rules]`
- `[backends.awww]`
- `[backends.swww]`
- `[backends.mpvpaper]`
- `[backends.gslapper]`
- `[hooks]`
- `[colors]`

## Hooks

Hooks should support:

- `before_set`
- `after_set`
- timeout handling
- logged failures
- placeholders:
  - `{file}`
  - `{monitor}`
  - `{backend}`
  - `{mime}`
  - `{basename}`
  - `{thumbnail}`
  - `{source_for_colors}`

For videos, `{source_for_colors}` should resolve to the generated thumbnail.

## GUI V1

Minimum usable GUI:

- Folder picker
- Thumbnail grid
- Monitor dropdown
- Set wallpaper button
- Settings page

Do not overbuild the GUI before backend behavior is reliable.

## Project Phases

### Phase 0: Repository Setup

- Python project with `pyproject.toml`
- `src/wallmux` layout
- ruff
- pytest
- basic CLI entry point
- README
- default config
- AGENTS.md

### Phase 1: CLI Prototype

Commands:

```bash
wallmuxctl set FILE --monitor MONITOR
wallmuxctl set FILE --all
wallmuxctl restore
wallmuxctl monitors
wallmuxctl detect FILE
```

Acceptance criteria:

- PNG/JPG/WEBP files route to `awww`.
- MP4/WEBM/MKV files route to `mpvpaper`.
- Monitor list comes from `hyprctl`.
- State is saved.
- Restore works after restart.

### Phase 2: Daemon

- `wallmuxd`
- Unix socket IPC with JSON messages
- Restore on startup
- Per-monitor video PID tracking
- Stale PID detection

### Phase 3: GUI V1

- PySide6 main window
- Folder library
- Thumbnail grid
- Monitor selector
- Backend preview label
- Set wallpaper button

### Phase 4: Hooks and Color Integration

- `before_set` and `after_set`
- Thumbnail variable for videos
- Hook timeout
- Hook log viewer

### Phase 5: Transition Polish

Start with clean switching. Fade overlays and screenshot bridges are future work.

### Phase 6: Packaging

- PKGBUILD
- systemd user service
- desktop file
- app icon

## MVP

The first useful MVP should:

- Detect image, GIF, and video files.
- Route images/GIFs to `awww`.
- Route videos to `mpvpaper`.
- Allow choosing a monitor.
- Save current wallpaper state.
- Restore current wallpaper state.
- Provide a basic PySide6 thumbnail grid.
- Run optional `after_set` hooks.
