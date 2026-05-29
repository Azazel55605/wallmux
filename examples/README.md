# Wallmux Examples

These examples are meant to be copied, edited, and treated as recipes rather than installed as-is.

## Generic Examples

These are portable across most Wallmux setups:

- `hooks/after-set-colors.sh`
  Runs `pywal`, `matugen`, optional QuickShell reloads, and an optional notification after a wallpaper changes.
- `profiles/color-topic-profiles.toml`
  Demonstrates parent color profiles and child topic profiles.
- `profiles/parent-child-hooks.toml`
  Demonstrates parent hooks, child hooks, and `include_parent_hooks`.
- `autoswitch/*.toml`
  Shows random, name-up, name-down, focused-monitor, and all-monitor autoswitch settings.
- `backends/*.toml`
  Shows backend defaults and fallback chains for `awww`, `swww`, `hyprpaper`, and `mpvpaper`.
- `cache-video-optimization.md`
  Shows cache maintenance and video optimization commands from V2.6/V2.7.

## Adapt-To-Your-System Examples

These are intentionally more personal and depend on local paths:

- `hooks/profile-theme-hook.sh`
  A profile switch hook based on a color/topic desktop theme workflow. It can update Hyprland border colors, hyprlock colors, fastfetch logos, an optional SDDM background, and optionally trigger `wallmuxctl random`.

Review every path near the top of the script before using it.

## Hook Types

Wallpaper hooks live in `config.toml` under `[hooks]` and receive wallpaper placeholders such as `{file}`, `{monitor}`, and `{source_for_colors}`.

Profile hooks live in `wallmux-profiles.toml` as `before_switch` or `after_switch` commands and receive profile placeholders such as `{profile}`, `{category}`, `{subcategory}`, `{color}`, `{label}`, and `{wallpaper_dirs}`.

Wallmux also exports these variables for profile hooks:

```text
WALLMUX_PROFILE
WALLMUX_PROFILE_NAME
WALLMUX_PROFILE_CATEGORY
WALLMUX_PROFILE_SUBCATEGORY
WALLMUX_PROFILE_COLOR
WALLMUX_PROFILE_LABEL
WALLMUX_PROFILE_WALLPAPER_DIRS
```
