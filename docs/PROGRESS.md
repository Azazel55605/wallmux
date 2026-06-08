# Wallmux Progress

This file tracks implementation progress against the phases in `docs/PROJECT_PLAN.md`.

Status legend:

- `[x]` Done
- `[~]` In progress
- `[ ]` Not started

## Current Snapshot

- Current phase: Phase 6 complete / ready for packaging validation on target systems
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
- [x] Add `PKGBUILD`
- [x] Add systemd user service
- [x] Add desktop file
- [x] Add app icon
- [x] Document Hyprland `exec-once`
- [x] Prepare AUR packaging notes

## V2 Roadmap

Goal: turn the current daily-driver base into a more diagnosable, resilient, and workflow-aware wallpaper orchestrator.

### V2.1: Health Checks and Diagnostics

- [x] Add `wallmuxctl doctor`
- [x] Add `wallmuxctl doctor video`
- [x] Check Hyprland session and `hyprctl` availability
- [x] Check configured backend commands and daemon requirements
- [x] Check optional tools such as `ffmpeg`, `notify-send`, `wal`, and `matugen`
- [x] Check config, state, library, thumbnail, and log path readability/writability
- [x] Check daemon socket reachability and report daemon version/state
- [x] Check video playback prerequisites such as `ffprobe`, available `ffmpeg` hardware accelerators, optional `vainfo`, and optional `nvidia-smi`
- [x] Detect GPU/driver hints from available system tools
- [ ] Expose best-effort video decode recommendations
- [x] Add actionable status levels: ok, warning, error

### V2.2: Better Runtime State

- [x] Expand `wallmuxctl state` with daemon uptime, last error, inhibition status, autoswitch timing, active backend per monitor, and tracked PIDs
- [x] Add a GUI state tab showing daemon status, monitor state, autoswitch status, inhibition reason, backend ownership, and recent errors
- [x] Show available video-related resources in the GUI state tab: GPU/driver hints, hardware decode tools, and `ffmpeg`/`ffprobe` status
- [ ] Show recommended smooth-playback profile in the GUI state tab
- [ ] Show dependency status in the GUI state tab for configured backends and helper tools, including installed, missing, optional, and unavailable states
- [ ] Show current resource mode in the GUI state tab: AC/battery state, high CPU/GPU load inhibition, video pause/skip behavior, and active video cache usage
- [x] Add a lightweight daemon event/error log suitable for GUI display
- [x] Show whether daemon-command inhibition is active and which requests it affects

### V2.3: Conservative Backend Fallbacks

- [x] Add image backend fallback chains for compatible backends such as `awww` -> `swww`
- [x] Keep `hyprpaper` opt-in rather than a default fallback for `awww`/`swww`
- [x] Add clear fallback logging so users know when the configured backend failed
- [x] Avoid cross-family fallbacks unless explicitly configured by the user
- [x] Add GUI settings for editing fallback chains without hand-editing TOML

### V2.4: Optional Daemon-Command Inhibition

- [x] Add an opt-in setting for inhibiting daemon-handled manual commands while inhibition is active
- [x] Keep explicit CLI direct mode/manual local execution uninhibited by default
- [x] Document that the setting affects daemon-routed commands such as GUI sets, daemon-backed `wallmuxctl set`, and daemon-backed `wallmuxctl random`
- [x] Return clear CLI/GUI messages when a command is inhibited and explain the active inhibition reason

### V2.5: Profiles and Subcategories

- [x] Add named wallpaper profiles
- [x] Support nested profile categories such as color -> topic
- [x] Allow profile/category selection from CLI
- [x] Add a small GUI profile picker popup for quick switching
- [x] Add `wallmux-gui profile-picker` standalone picker mode
- [x] Add keyboard shortcut for opening the profile picker from the GUI
- [x] Add GUI profile configuration for creating and editing profile entries
- [x] Rework profile settings list into a tree structure
- [x] Rework profile picker into a searchable tree for larger profile collections
- [x] Reduce profile settings clutter by moving primary actions to the top and hooks into a sub-tab
- [x] Split profile settings into Identity, Folders, Backends, Filters, and Hooks tabs
- [x] Add folder picker controls for profile wallpaper directories
- [x] Add import flow that turns category root child folders into profile subcategories
- [x] Treat imported roots as parent/all profiles and imported child folders as separate subprofiles
- [x] Clarify in GUI/docs that categories are organizational labels and wallpaper membership comes from profile folders and filters
- [x] Add profile-level pre-switch and post-switch hooks
- [x] Add per-profile switch for including parent profile hooks in child profiles
- [x] Allow profiles to define wallpaper dirs, backend rules, autoswitch mode, filters, and hook behavior
- [x] Replace long profile help text with compact hover help markers and add contextual help to dense GUI settings
- [x] Move profiles into `wallmux-profiles.toml` with automatic migration from older inline config profiles
- [x] Add example profile theme hook for moving legacy color/theme side effects into Wallmux profile switching
- [x] Add debounced autosave for profile editor changes
- [x] Add optional profile color swatches for tagging and visual identification

### V2.6: Video Optimization

- [x] Detect video resolution, codec, duration, and file size
- [x] Warn about unusually heavy videos for the active monitor setup
- [x] Add `wallmuxctl video inspect FILE`
- [x] Add `wallmuxctl video plan FILE --profile PROFILE` for dry-run optimization planning
- [x] Add `wallmuxctl video optimize FILE --profile PROFILE --dry-run`
- [x] Add `wallmuxctl video optimize FILE --profile PROFILE`
- [x] Show CLI progress while `ffmpeg` optimization is running, including percentage, video time, output write rate, and ffmpeg speed
- [x] Add `wallmuxctl video optimize-library --profile PROFILE` as an explicit bulk action with a clear disk-usage/time warning
- [x] Add video quality/performance presets
- [x] Improve pause/resume behavior for locked, fullscreen, inhibited, battery, and high-load states
- [x] Consider optional thumbnail/frame metadata caching for faster video browsing; keep separate metadata sidecars for optimized videos first
- [x] Add optional video optimization that creates cached playback-friendly derivatives through `ffmpeg` without modifying originals
- [x] Detect when a video is already suitable and skip unnecessary optimization
- [x] Add optimization profiles such as compatibility, balanced, quality, and manual `ffmpeg` arguments
- [x] Add settings for preferred optimized codec/container, max resolution, bitrate/quality, cache location, and whether optimized videos are preferred automatically when present
- [x] Track optimized video derivatives separately from thumbnails because they can be large
- [x] Store optimized-video metadata for source path, mtime, size, codec, resolution, profile, generated file, generated size, and last-used time
- [x] Add battery-aware video behavior for laptops: keep playing, pause, skip video wallpapers, or show first frame while on battery
- [x] Add high-resource-use behavior for CPU/GPU load: pause video playback, pause autoswitching, or both after a configurable sustained threshold
- [x] Make GPU load detection best-effort with vendor/tool-specific support and clear unavailable-state reporting

### V2.7: Cache Maintenance

- [x] Add `wallmuxctl cache stats`
- [x] Add `wallmuxctl cache clean`
- [x] Add `wallmuxctl cache rebuild`
- [x] Add `wallmuxctl cache clean --videos` and `wallmuxctl cache clean --thumbnails`
- [x] Add optional periodic stale-thumbnail cleanup in `wallmuxd`
- [x] Add optimized video cache stats, cleanup, and rebuild controls
- [x] Add a GUI cache tab for thumbnails and optimized video derivatives
- [x] Show estimated and actual optimized-video cache size before and after optimization jobs
- [x] Add config for enabling/disabling cache maintenance, setting cleanup interval, and limiting optimized-video cache size
- [x] Add cleanup policies such as stale-only and least-recently-used for optimized video derivatives

### V2.8: Examples and Recipes

- [x] Create an `examples/` collection for reusable Wallmux workflows
- [x] Add profile hook recipes for pywal, matugen, QuickShell, hyprlock, and notification workflows
- [x] Add profile/theme switching examples that demonstrate parent and child profile hooks
- [x] Add autoswitch examples for random, name-up, name-down, focused-monitor, and all-monitor setups
- [x] Add backend configuration examples for `awww`, `swww`, `hyprpaper`, `mpvpaper`, and fallback chains
- [x] Add cache/video optimization examples once V2.6/V2.7 land
- [x] Document which examples are generic and which are personal/adapt-to-your-system recipes

### Deferred / Needs More Design

- [ ] Import compatibility for Waypaper, hyprpaper, swww, or ad hoc wallpaper scripts
- [ ] Random-mode `previous` command without full history UI

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
- 2026-05-24: Added daemon-owned auto switching with random/name-up/name-down selection, GUI controls, CLI controls, manual `wallmuxctl random`, and daemon status reporting.
- 2026-05-24: `pytest` passed, 51 tests.
- 2026-05-24: Persisted GUI zen mode in config and set Qt app id/title to `wallmux-gui`/`wallmux` for Hyprland window rule matching.
- 2026-05-24: Optimized multi-monitor video -> image switching by terminating tracked video processes concurrently before issuing one grouped image backend command.
- 2026-05-24: Added default basic transition orchestration for video -> image by setting images before stopping old video processes, with GUI toggles and custom transition effects still available.
- 2026-05-24: Added inhibition rules for fullscreen clients and running process names, pausing auto switching and tracked video wallpaper processes while games/rendering tasks are active without blocking merely open launchers.
- 2026-05-24: Added toggleable desktop notifications for successful wallpaper switches and switching failures through `notify-send`.
- 2026-05-24: Finished Phase 6 packaging assets with Arch `PKGBUILD`, systemd user service, desktop file, app icon, Hyprland startup docs, AUR notes, and local desktop/service Makefile helpers.
- 2026-05-24: Added `hyprpaper` as an optional static image backend and refreshed the packaged app icon into a minimal line-style mark.
- 2026-05-25: Added notification icon support using the `wallmux-gui` app icon by default, including resolved icon paths and desktop-entry hints for notification daemons.
- 2026-05-26: Started V2.1 with `wallmuxctl doctor` and `wallmuxctl doctor video` health checks for environment, backends, paths, daemon reachability, and video tooling.
- 2026-05-26: Started V2.2 with richer daemon state, monitor status, recent daemon events, improved `wallmuxctl state`, and a GUI State tab with daemon/runtime and video doctor information.
- 2026-05-26: Finished V2.3 conservative backend fallbacks with default `awww` -> `swww`, opt-in fallback chains, fallback logging, grouped all-monitor fallback handling, and GUI fallback settings.
- 2026-05-26: Finished V2.4 optional daemon-command inhibition for GUI sets, daemon-backed set/random/restore/autoswitch-now commands, with status visibility and direct CLI execution kept uninhibited.
- 2026-05-26: Finished V2.5 wallpaper profiles with category/subcategory labels, active profile config, CLI profile switching, GUI profile picker, profile-scoped wallpaper dirs/backend rules/autoswitch mode/filters, and profile switch hooks.
- 2026-05-26: Started V2.6 with `wallmuxctl video inspect`, `ffprobe` metadata parsing, monitor-aware heavy-video warnings, and structured inspection output for future optimization/cache work.
- 2026-05-26: Added V2.6 video optimization planning with compatibility/balanced/quality presets, deterministic optimized-video cache paths, suitability detection, and dry-run command output.
- 2026-05-26: Added single-file V2.6 video optimization execution, writing playback-friendly derivatives into a separate optimized-video cache with JSON sidecar metadata.
- 2026-05-26: Added CLI progress reporting for video optimization using ffmpeg progress events, with percent, video time, output write rate, and ffmpeg speed.
- 2026-05-26: Finished V2.6 with bulk video optimization, configurable optimization settings, optional optimized-video preference, resource-mode state, battery/high-load inhibition behavior, and best-effort GPU load detection.
- 2026-05-29: Finished V2.7 cache maintenance with shared cache stats/clean/rebuild helpers, `wallmuxctl cache` commands, periodic daemon cleanup, age-based thumbnail cleanup, optimized-video stale/LRU cleanup, and a GUI Cache settings tab.
- 2026-05-29: Finished V2.8 examples and recipes with generic wallpaper/color hooks, an adaptable profile theme hook, profile parent/child examples, autoswitch presets, backend fallback snippets, and cache/video optimization recipes.
- 2026-06-08: Moved automatic video optimization into `wallmuxd` with active-library scans, a two-job queue, replaceable progress notifications, GUI/CLI queue status, improved video-to-image handoff timing, and safer mpvpaper defaults for black-frame mitigation.
- 2026-06-08: Added explicit Automatic, Software, and Hardware mpvpaper decoding modes with GUI selection and migration from existing `hwdec` options.
- 2026-06-08: Added immediate daemon video-optimization scans when profiles, configured libraries, or manually opened GUI folders change.
- 2026-06-08: Added a runnable QuickShell layer-shell fade overlay example with IPC controller, Wallmux configuration, setup guide, and before/after helper invocation.
- 2026-06-08: Improved QuickShell handoffs with configurable video-start settling and external transition stages for grouped all-monitor image switches.
- 2026-06-08: Added per-transition QuickShell overlay controls, leaving image-to-image fades disabled by default.
- 2026-05-26: Added GUI profile configuration for editing profile metadata, folders, backend rules, autoswitch behavior, filters, and profile switch hooks.
- 2026-05-26: Improved profile GUI setup with folder picker controls and clearer category/subcategory guidance.
- 2026-05-26: Added profile category import from existing folder structures, creating one profile per child folder such as `green/Anime` and `green/Landscape`.
- 2026-05-26: Reworked profile hierarchy UX so imported roots become parent/all profiles, child folders become separate subprofiles, and `wallmux-gui profile-picker` opens the switcher directly.
- 2026-05-26: Cleaned up profile settings UX with a tree view, top-level action buttons, hook sub-tab, and `Ctrl+P` profile picker shortcut.
- 2026-05-26: Split profile editing into focused Identity, Folders, Backends, Filters, and Hooks tabs.
- 2026-05-26: Added `include_parent_hooks` for child profiles, running parent hooks before child hooks when enabled.
- 2026-05-26: Replaced the profile explanation block with compact hover help markers and added contextual help markers to dense settings rows across profiles, backend defaults, notifications, inhibition, autoswitching, and transitions.
- 2026-05-26: Moved profile storage to `~/.config/wallmux/wallmux-profiles.toml`, added automatic migration from inline `[profiles]`, and fixed profile tree parent rows so parent hooks can be edited normally.
- 2026-05-26: Added `examples/hooks/profile-theme-hook.sh` as a Wallmux-profile-native replacement for the old Wofi wallpaper theme script's Hyprland, hyprlock, fastfetch, SDDM, notification, and optional random-wallpaper side effects.
- 2026-05-26: Added V2.8 roadmap section for examples and recipes so personal workflow scripts can evolve into reusable documentation without bloating core Wallmux.
- 2026-05-26: Updated the profile theme hook example for Hyprland Lua `borders.lua` active border colors and added debounced profile-editor autosave.
- 2026-05-26: Reworked the profile picker from a flat list into a searchable parent/child tree for larger profile collections.
- 2026-05-26: Added optional profile color swatches to profile config, the profile settings tree, and the profile picker.
