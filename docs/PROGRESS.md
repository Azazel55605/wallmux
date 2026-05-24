# Wallmux Progress

This file tracks implementation progress against the phases in `docs/PROJECT_PLAN.md`.

Status legend:

- `[x]` Done
- `[~]` In progress
- `[ ]` Not started

## Current Snapshot

- Current phase: Phase 5 complete / ready for Phase 6 packaging polish
- Repository scaffold: done
- CLI prototype: complete for Phase 1
- Daemon: complete for Phase 2
- GUI: complete for Phase 3
- Last verified: `pytest`, `ruff check .`, GUI offscreen smoke check, build, and `twine check` passing

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

- [x] Add `wallmuxd` entry point
- [x] Read config on startup
- [x] Restore wallpapers on startup
- [x] Maintain video backend processes
- [x] Detect stale PIDs on startup
- [x] Expose Unix socket IPC
- [x] Accept JSON control messages
- [x] Stop/restart per-monitor video wallpapers
- [x] Add daemon tests around command handling

## Phase 3: GUI V1

Goal: usable Waypaper-like manager.

- [x] Add `wallmux-gui` entry point
- [x] PySide6 main window structure
- [x] Folder picker
- [x] Wallpaper folder library
- [x] Thumbnail grid
- [x] Image thumbnails
- [x] Video thumbnails through `ffmpeg`
- [x] Monitor selector
- [x] Backend preview label
- [x] Set wallpaper button
- [x] Basic settings page
- [x] Reuse CLI/service logic instead of duplicating routing

## Phase 4: Hooks and Color Integration

Goal: fit into Hyprland rice/theme workflows.

- [x] Define supported hook placeholders
- [x] Add hook command formatter
- [x] Run `before_set` hooks
- [x] Run `after_set` hooks
- [x] Add hook timeout
- [x] Log hook failures without reverting wallpaper changes
- [x] Resolve video `{source_for_colors}` to thumbnail
- [x] Add per-backend hook enable/disable
- [x] Add hook log viewer

## Phase 5: Transition Polish

Goal: improve cross-backend switching after the MVP is reliable.

- [x] Keep native `awww` transitions for image -> image
- [x] Clean video -> video replacement
- [x] Clean image -> video switching
- [x] Clean video -> image switching
- [x] Optional fade overlay
- [x] Optional screenshot bridge
- [x] Optional QuickShell overlay integration

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
- [x] Provide a basic PySide6 thumbnail grid
- [x] Run optional `after_set` hooks

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
- 2026-05-21: Finished Phase 2 daemon with Unix socket JSON IPC, startup restore, stale PID cleanup, daemon-backed CLI commands, state reporting, and per-monitor video stopping.
- 2026-05-21: `pytest` passed, 25 tests.
- 2026-05-21: `ruff check .` passed.
- 2026-05-21: Finished Phase 3 GUI v1 with PySide6 browser, folder picker, thumbnail grid, filters, monitor selector, backend preview, settings folder management, and set-wallpaper action.
- 2026-05-21: Added GUI background thumbnail generation, Qt theme/plugin discovery, zen mode, keyboard navigation, and a dialog-style floating hint.
- 2026-05-21: Finished Phase 4 hooks with before/after stages, placeholders, timeouts, failure logging, video thumbnail color source, per-backend hook enable flags, and GUI hook log viewer.
- 2026-05-21: Finished Phase 5 simple transition polish with transition classification, stale PID cleanup, configurable video stop timeout, SIGKILL fallback, and tests for image/video switch paths.
- 2026-05-24: Added per-set backend controls in the GUI, an all-monitors target, daemon/core backend overrides, and opt-in external transition effect commands for fade, screenshot bridge, and QuickShell overlay helpers.
- 2026-05-24: `pytest` passed, 47 tests.
- 2026-05-24: `ruff check .` passed.
- 2026-05-24: GUI offscreen smoke check passed.
- 2026-05-24: Reworked Settings into grouped sections, moved backend options to persistent global defaults, added simultaneous/sequential all-monitor mode, quiet/crop/fill mpvpaper defaults, and migration for the old mpvpaper default options.
- 2026-05-24: `pytest` passed, 48 tests.
- 2026-05-24: Added full `awww`/`swww` transition defaults for type, step, duration, FPS, angle, position, invert-y, bezier, and wave dimensions.
- 2026-05-24: Changed simultaneous all-monitor image sets to issue one unified `awww`/`swww` command with comma-separated outputs, keeping random/any transitions consistent across monitors.
