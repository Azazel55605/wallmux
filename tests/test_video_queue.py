from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from wallmux.core.library import WallpaperItem
from wallmux.core.mime import WallpaperType
from wallmux.core.video_queue import VideoOptimizationQueue


def test_video_queue_limits_automatic_jobs_to_two(monkeypatch, tmp_path: Path) -> None:
    active = 0
    maximum_active = 0
    release = threading.Event()
    all_started = threading.Event()
    lock = threading.Lock()
    started = 0

    def optimize(path, **_kwargs):
        nonlocal active, maximum_active, started
        with lock:
            active += 1
            started += 1
            maximum_active = max(maximum_active, active)
            if started == 2:
                all_started.set()
        release.wait(timeout=2)
        with lock:
            active -= 1
        return SimpleNamespace(skipped=False, message="done")

    monkeypatch.setattr("wallmux.core.video_queue.optimize_video", optimize)
    monkeypatch.setattr(
        "wallmux.core.video_queue.cached_optimized_video_for_source",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "wallmux.core.video_queue.notify_video_optimization",
        lambda *_args, **_kwargs: None,
    )
    items = []
    for index in range(4):
        path = tmp_path / f"{index}.mp4"
        path.write_bytes(b"video")
        items.append(WallpaperItem(path, WallpaperType.VIDEO, "mpvpaper"))

    queue = VideoOptimizationQueue(max_workers=8)
    try:
        assert queue.enqueue_library(items, sample_config()) == 4
        assert all_started.wait(timeout=2)
        assert queue.status()["running"] == 2
        assert queue.status()["queued"] == 2
        assert maximum_active == 2
        release.set()
        deadline = time.monotonic() + 2
        while queue.status()["running"] or queue.status()["queued"]:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        release.set()
        queue.shutdown()


def test_video_queue_skips_cached_derivatives(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "cached.mp4"
    path.write_bytes(b"video")
    monkeypatch.setattr(
        "wallmux.core.video_queue.cached_optimized_video_for_source",
        lambda *_args: tmp_path / "optimized.mp4",
    )
    queue = VideoOptimizationQueue()
    try:
        added = queue.enqueue_library(
            [WallpaperItem(path, WallpaperType.VIDEO, "mpvpaper")],
            sample_config(),
        )
    finally:
        queue.shutdown()

    assert added == 0
    assert queue.status()["queued"] == 0


def sample_config() -> dict:
    return {
        "video_optimization": {
            "enabled": True,
            "auto_optimize": True,
            "profile": "balanced",
        },
        "notifications": {"enabled": False},
    }
