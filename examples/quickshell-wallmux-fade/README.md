# QuickShell Fade Overlay

This example creates one non-interactive background layer-shell surface per
monitor. Wallmux fades the wallpaper area to black before changing wallpaper
backends, performs the switch while it is covered, and fades it away afterward.
Applications, panels, notifications, and other foreground surfaces remain
visible.

It improves image/video and video/image transitions without modifying mpvpaper.

## Install

Copy the example into QuickShell's config directory:

```bash
mkdir -p ~/.config/quickshell/wallmux-fade
cp examples/quickshell-wallmux-fade/shell.qml ~/.config/quickshell/wallmux-fade/
cp examples/quickshell-wallmux-fade/wallmux-fade.sh ~/.config/quickshell/wallmux-fade/
chmod +x ~/.config/quickshell/wallmux-fade/wallmux-fade.sh
```

Start it once per login:

```bash
qs -c wallmux-fade --daemonize
```

For Hyprland Lua configuration:

```lua
hl.exec_once("qs -c wallmux-fade --daemonize")
```

Copy the settings from `wallmux.toml` into
`~/.config/wallmux/config.toml`, then reload Wallmux:

```bash
wallmuxctl reload
```

Wallmux calls the configured QuickShell helper twice: `before` blocks until the
overlay is opaque, and `after` reveals the completed wallpaper switch.

By default, the example only fades transitions involving video. Native
`awww`/`swww` image-to-image transitions remain visible. Enable or disable
individual transition kinds under Settings > Transitions > QuickShell
transitions, or edit `quickshell_transitions` in the TOML configuration.

## Test

Test both transition stages without changing a wallpaper:

```bash
~/.config/quickshell/wallmux-fade/wallmux-fade.sh before all
~/.config/quickshell/wallmux-fade/wallmux-fade.sh after all
```

Replace `all` with a monitor name such as `DP-1` to test one output.

## Customize

Change `fadeDuration` and `fadeColor` near the top of `shell.qml`. Keep
`FADE_DURATION_MS` in `wallmux-fade.sh` equal to the QML duration so Wallmux
waits until the desktop is fully covered before switching.

`video_start_settle_seconds` keeps the overlay opaque while mpvpaper creates its
layer and renders the first frame. Increase it if the fade finishes before the
video appears. `video_to_image_settle_seconds` gives the replacement image a
short moment to settle before Wallmux removes mpvpaper.

The overlay uses an empty input region and does not reserve screen space, so it
does not intercept clicks or affect window layout.

## Limitations

- This is a fade-through-color transition, not a screenshot crossfade.
- Wallpaper backends also use low layer-shell layers. If a backend appears above
  the fade surface on your compositor, change `WlrLayer.Background` to
  `WlrLayer.Bottom` or `WlrLayer.Overlay`. `Overlay` reliably covers the
  wallpaper but also covers applications during the transition.
- QuickShell must already be running when Wallmux calls the helper.
- The example expects QuickShell's executable to be named `qs`.
- Wallmux logs helper failures to `~/.local/state/wallmux/transitions.log`.
