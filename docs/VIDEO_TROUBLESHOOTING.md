# Video Wallpaper Troubleshooting

## Automatic Optimization

Automatic video optimization is owned by `wallmuxd`.

When `video_optimization.auto_optimize` is enabled, the daemon scans the active profile/library:

- when the daemon starts
- after the daemon reloads, including profile and folder changes
- periodically while running

At most two ffmpeg optimization jobs run at once. Remaining videos stay queued until a worker is available. `wallmuxctl state` and the GUI State tab show running and queued jobs. Progress notifications reuse one notification per video when the notification daemon supports replacement IDs.

```toml
[video_optimization]
auto_optimize = true
max_concurrent_jobs = 2
library_scan_interval_seconds = 30

[notifications]
video_optimization = true
```

## Video to Image Handoff

Wallmux sets the next image underneath mpvpaper, waits briefly for the image backend transition to finish, and then stops mpvpaper. This prevents the previously displayed image from flashing between the video and the next image.

```toml
[transitions.basic]
enabled = true
set_image_before_stopping_video = true
video_to_image_settle_seconds = 0.9
video_start_settle_seconds = 0.6
```

Increase the settle time if your `awww` or `swww` transition is longer. A true fade of the mpvpaper layer itself still requires a compositor or layer-shell overlay helper because mpvpaper/libmpv does not expose layer opacity control.

`video_start_settle_seconds` delays an overlay's reveal while a newly started
video backend creates its layer and renders its first frame.

## Black Frames and Flicker

Black frames can come from several layers:

- mpv display-synchronization assumptions not matching the Wayland surface timing
- hardware-decoder or GPU-driver presentation issues
- mpvpaper/libmpv layer-surface behavior
- compositor VRR, direct scanout, or multi-GPU synchronization issues
- black frames encoded into the source video

Wallmux defaults use the more robust system-clock video synchronization mode, safer automatic hardware decoding, explicit infinite file looping, and a persistent final frame:

```toml
[backends.mpvpaper]
options = "no-config no-audio loop-file=inf keep-open=yes profile=fast video-sync=audio interpolation=no scale=bilinear cscale=bilinear dscale=bilinear panscan=1.0 osd-level=0 no-osc no-osd-bar really-quiet"
hardware_decoding = "automatic"
```

If flicker remains, test these one at a time:

1. Select `Software (flicker-safe)` under Settings > Backends > mpvpaper. If flicker stops, the hardware decode/driver path is responsible.
2. Temporarily disable VRR/adaptive sync in Hyprland. Flicker mostly visible on an empty desktop can be compositor/display timing related.
3. Test the same file with `gSlapper`. If it is stable, the issue is likely specific to mpvpaper/libmpv.
4. Test an H.264/YUV420 optimized derivative. If only the original flickers, the codec, pixel format, or decoder path is responsible.
5. Check whether the source itself contains black frames around its loop boundary.

mpv documents `video-sync=audio` as the most robust timing mode when audio is disabled, using the system clock. mpvpaper also has an upstream open issue for black flashes, so not every flicker can be corrected inside Wallmux.

## Loop-Boundary Flicker

Enable loop-friendly encoding under Settings > Video Optimization to create
derivatives with constant frame pacing, closed GOPs, and no B-frames:

```toml
[video_optimization]
loop_friendly = true
loop_gop_size = 60
```

This makes seeking back to the first frame cheaper and reduces decoder flicker
at loop boundaries. It slightly increases file size and forces a derivative
even when the original video already matches the selected codec and resolution.
It cannot hide a visible seam that is encoded into the source video itself.
