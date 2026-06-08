#!/bin/sh

set -eu

STAGE="${1:-}"
MONITOR="${2:-all}"
FADE_DURATION_MS=250
QUICKSHELL_CONFIG="${WALLMUX_QUICKSHELL_FADE_CONFIG:-wallmux-fade}"

case "$STAGE" in
    before)
        ACTION="fadeIn"
        ;;
    after)
        ACTION="fadeOut"
        ;;
    *)
        echo "usage: wallmux-fade.sh before|after [monitor]" >&2
        exit 2
        ;;
esac

qs ipc -c "$QUICKSHELL_CONFIG" call wallmuxFade "$ACTION" "$MONITOR"

# The before stage must remain blocked until the old wallpaper is fully hidden.
# Waiting after fade-out also keeps rapid switches visually ordered.
sleep "$(awk "BEGIN { print $FADE_DURATION_MS / 1000 }")"
