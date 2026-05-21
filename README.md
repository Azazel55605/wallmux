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
wallmuxd
wallmux-gui
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```
