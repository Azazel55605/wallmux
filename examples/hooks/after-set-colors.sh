#!/usr/bin/env bash
set -euo pipefail

# Generic wallpaper after_set hook.
#
# Suggested config.toml entry:
#
# [hooks]
# after_set = [
#   "~/.config/wallmux/hooks/after-set-colors.sh '{source_for_colors}' '{file}' '{monitor}' '{backend}'"
# ]

SOURCE_FOR_COLORS="${1:-}"
WALLPAPER_FILE="${2:-}"
MONITOR="${3:-}"
BACKEND="${4:-}"

if [[ -z "$SOURCE_FOR_COLORS" || ! -f "$SOURCE_FOR_COLORS" ]]; then
  echo "source image for colors is missing: $SOURCE_FOR_COLORS" >&2
  exit 1
fi

if command -v wal >/dev/null 2>&1; then
  wal -i "$SOURCE_FOR_COLORS" -q
fi

if command -v matugen >/dev/null 2>&1; then
  matugen image "$SOURCE_FOR_COLORS"
fi

if command -v qs >/dev/null 2>&1; then
  qs ipc call reload 2>/dev/null || true
elif command -v quickshell >/dev/null 2>&1; then
  quickshell ipc call reload 2>/dev/null || true
fi

if command -v notify-send >/dev/null 2>&1; then
  notify-send \
    -a "Wallmux" \
    -i "wallmux-gui" \
    "Wallpaper colors updated" \
    "$(basename "$WALLPAPER_FILE") on ${MONITOR:-unknown} via ${BACKEND:-unknown}"
fi
