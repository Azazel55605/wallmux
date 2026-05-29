# Cache and Video Optimization Recipes

These examples use the V2.6/V2.7 video cache and maintenance commands.

## Inspect Cache Usage

```bash
wallmuxctl cache stats
wallmuxctl cache stats --json
```

## Clean Caches

Clean stale thumbnails and stale optimized video derivatives:

```bash
wallmuxctl cache clean
```

Clean only thumbnails:

```bash
wallmuxctl cache clean --thumbnails
```

Clean only optimized videos:

```bash
wallmuxctl cache clean --videos
```

Trim optimized videos using the configured LRU size limit:

```bash
wallmuxctl cache clean --videos --policy lru
```

Remove all cached thumbnails and videos:

```bash
wallmuxctl cache clean --policy all
```

## Rebuild Caches

Rebuild thumbnails and optimize videos for the active profile/library:

```bash
wallmuxctl cache rebuild
```

Rebuild thumbnails only:

```bash
wallmuxctl cache rebuild --thumbnails
```

Rebuild optimized videos only:

```bash
wallmuxctl cache rebuild --videos
```

## Video Optimization

Inspect one video:

```bash
wallmuxctl video inspect ~/Pictures/Wallpapers/clip.mkv
```

Preview the optimization command:

```bash
wallmuxctl video plan ~/Pictures/Wallpapers/clip.mkv --profile balanced
```

Optimize one video:

```bash
wallmuxctl video optimize ~/Pictures/Wallpapers/clip.mkv --profile balanced
```

Optimize the active library:

```bash
wallmuxctl video optimize-library --yes
```

## Suggested Cache Settings

```toml
[cache]
maintenance_enabled = true
cleanup_interval_seconds = 86400
cleanup_policy = "stale-only"
thumbnail_max_age_days = 60
optimized_video_max_size_mb = 10240
```

Use `cleanup_policy = "lru"` if you want the daemon to enforce the optimized-video cache size limit during periodic maintenance.
