# Wallmux Progress

This file tracks implementation progress against the phases in `docs/PROJECT_PLAN.md`.

Status legend:

- `[x]` Done
- `[~]` In progress
- `[ ]` Not started

## Current Snapshot

- Current phase: Phase 1 complete / ready for Phase 2
- Repository scaffold: done
- CLI prototype: complete for Phase 1
- Daemon: skeleton only
- GUI: skeleton only
- Last verified: `pytest` and `ruff check .` passing

## Phase 0: Repository Setup

Goal: make the project easy to work on with Codex and normal local tooling.

- [x] Create Python project with `pyproject.toml`
- [x] Use `src/wallmux` layout
- [x] Add `ruff` config
- [x] Add `pytest` config
- [x] Add basic CLI entry point: `wallmuxctl`
- [x] Add daemon entry point: `wallmuxd`
- [x] Add GUI entry point: `wallmux-gui`
- [x] Add `README.md`
- [x] Add default config
- [x] Add `AGENTS.md`
- [x] Add project plan file
- [x] Add initial tests

## Phase 1: CLI Prototype

Goal: set wallpapers without the GUI.

- [x] `wallmuxctl detect FILE`
- [x] `wallmuxctl monitors`
- [x] `wallmuxctl set FILE --monitor MONITOR`
- [x] `wallmuxctl set FILE --all`
- [x] `wallmuxctl restore`
- [x] Add MIME routing module
- [x] Add extension fallback detection
- [x] Route images to `awww`
- [x] Route GIFs to `awww`
- [x] Route videos to `mpvpaper`
- [x] Add `hyprctl monitors -j` wrapper
- [x] Add JSON state save/load helper
- [x] Execute image backend commands
- [x] Execute video backend commands
- [x] Restore wallpapers by executing saved state
- [x] Track and replace per-monitor video processes
- [x] Add focused monitor support

Acceptance criteria:

- [x] PNG/JPG/WEBP files go to `awww`
- [x] MP4/WEBM/MKV files go to `mpvpaper`
- [x] Monitor list comes from `hyprctl`
- [x] State is saved
- [x] Restore works after restart

## Phase 2: Daemon

Goal: stable backend ownership.

- [~] Add `wallmuxd` entry point
- [ ] Read config on startup
- [ ] Restore wallpapers on startup
- [ ] Maintain video backend processes
- [ ] Detect stale PIDs on startup
- [ ] Expose Unix socket IPC
- [ ] Accept JSON control messages
- [ ] Stop/restart per-monitor video wallpapers
- [ ] Add daemon tests around command handling

## Phase 3: GUI V1

Goal: usable Waypaper-like manager.

- [~] Add `wallmux-gui` entry point
- [ ] PySide6 main window structure
- [ ] Folder picker
- [ ] Wallpaper folder library
- [ ] Thumbnail grid
- [ ] Image thumbnails
- [ ] Video thumbnails through `ffmpeg`
- [ ] Monitor selector
- [ ] Backend preview label
- [ ] Set wallpaper button
- [ ] Basic settings page
- [ ] Reuse CLI/service logic instead of duplicating routing

## Phase 4: Hooks and Color Integration

Goal: fit into Hyprland rice/theme workflows.

- [~] Define supported hook placeholders
- [~] Add hook command formatter
- [ ] Run `before_set` hooks
- [ ] Run `after_set` hooks
- [ ] Add hook timeout
- [ ] Log hook failures without reverting wallpaper changes
- [ ] Resolve video `{source_for_colors}` to thumbnail
- [ ] Add per-backend hook enable/disable
- [ ] Add hook log viewer

## Phase 5: Transition Polish

Goal: improve cross-backend switching after the MVP is reliable.

- [ ] Keep native `awww` transitions for image -> image
- [ ] Clean video -> video replacement
- [ ] Clean image -> video switching
- [ ] Clean video -> image switching
- [ ] Optional fade overlay
- [ ] Optional screenshot bridge
- [ ] Optional QuickShell overlay integration

## Phase 6: Packaging

Goal: easy install on Arch.

- [x] Add Python wheel build configuration
- [x] Add source distribution build configuration
- [x] Package default config inside the Python package
- [x] Add packaging documentation
- [x] Add Makefile build helper
- [x] Add Makefile local install helper
- [x] Add Makefile local uninstall helper
- [x] Add Makefile pipx install helper
- [x] Add Makefile pipx uninstall helper
- [ ] Add `PKGBUILD`
- [ ] Add systemd user service
- [ ] Add desktop file
- [ ] Add app icon
- [ ] Document Hyprland `exec-once`
- [ ] Prepare AUR packaging notes

## MVP Checklist

- [x] Detect image, GIF, and video files
- [x] Route images/GIFs to `awww`
- [x] Route videos to `mpvpaper`
- [x] Allow choosing a monitor
- [x] Save current wallpaper state
- [x] Restore current wallpaper state by executing backend commands
- [ ] Provide a basic PySide6 thumbnail grid
- [ ] Run optional `after_set` hooks

## Verification Log

Record notable checks here as the project moves.

- 2026-05-21: Fixed malformed `pyproject.toml` dev dependency list.
- 2026-05-21: `pytest` passed, 9 tests.
- 2026-05-21: `ruff check .` passed.
- 2026-05-21: Finished Phase 1 CLI prototype with backend execution, restore execution, `--all` and focused monitor expansion, and tracked video PID replacement.
- 2026-05-21: `pytest` passed, 15 tests.
- 2026-05-21: `ruff check .` passed.
- 2026-05-21: Added Python wheel/sdist packaging, packaged default config resource, Makefile build helper, and packaging docs.
- 2026-05-21: `python -m build` produced `wallmux-0.1.0.tar.gz` and `wallmux-0.1.0-py3-none-any.whl`.
- 2026-05-21: Added `make install` and `make uninstall` for local wheel testing.
- 2026-05-21: `make build` passed and produced wheel/sdist artifacts.
- 2026-05-21: `twine check dist/*` passed for wheel and sdist.
- 2026-05-21: Added `make pipx-install` and `make pipx-uninstall` for isolated install testing.
- 2026-05-21: Added self-creating and self-reconciling user config behavior.
