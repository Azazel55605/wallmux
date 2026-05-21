# AGENTS.md

Guidance for Codex and other coding agents working on Wallmux.

## Project Identity

Wallmux is a Hyprland-first wallpaper manager and orchestrator for Arch Linux.

Core rule:

```text
Do not render wallpapers yourself.
Do not replace awww, swww, mpvpaper, or gSlapper.
Be the smart control layer above them.
```

Wallmux should focus on:

- Detecting wallpaper file types.
- Routing files to the correct backend.
- Managing per-monitor wallpaper state.
- Starting and stopping video wallpaper processes cleanly.
- Providing a Waypaper-like PySide6 GUI.
- Running optional color and desktop automation hooks.
- Restoring wallpapers after login or daemon restart.

## Stack

- Python 3.11+
- PySide6
- SQLite eventually
- TOML
- platformdirs
- Pillow
- python-magic with extension fallback
- pytest
- ruff

Use the `src/wallmux` layout. Keep modules small and boring until real complexity appears.

## Entry Points

- `wallmuxctl`: CLI for scripts, keybinds, menus, and tests.
- `wallmuxd`: daemon for backend ownership, restore, process tracking, and IPC.
- `wallmux-gui`: PySide6 GUI.

## Build Order

1. CLI `set` command.
2. MIME routing.
3. Hyprland monitor detection with `hyprctl monitors -j`.
4. State save and restore.
5. `mpvpaper` process tracking.
6. PySide6 thumbnail grid.
7. Hooks.
8. Daemon and Unix socket IPC.
9. Transition polish.

## Backend Rules

Default routing:

- Images: `awww`
- GIFs: `awww`
- Videos: `mpvpaper`

Only one backend should own a monitor at a time. Track video PIDs per monitor; do not use broad `pkill mpvpaper` behavior.

## Paths

Use `platformdirs`; do not hardcode user paths.

Expected locations:

- Config: `~/.config/wallmux/config.toml`
- State: `~/.local/state/wallmux/state.json`
- Logs: `~/.local/state/wallmux/wallmux.log`
- Thumbnails: `~/.cache/wallmux/thumbnails/`
- Library DB: `~/.local/share/wallmux/library.db`

## Testing

Before finishing code changes, run:

```bash
pytest
ruff check .
```

If dependencies are not installed, report that clearly.

## Style

- Prefer simple data classes and explicit functions over early framework abstractions.
- Keep external command construction in backend modules.
- Keep state serialization in `core/state.py`.
- Keep MIME and routing logic testable without Hyprland or wallpaper backends installed.
- Log hook failures but do not revert wallpaper changes because a hook failed.
