"""Daemon-owned automatic video optimization queue."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wallmux.core.library import WallpaperItem
from wallmux.core.mime import WallpaperType
from wallmux.core.notifications import notify_video_optimization
from wallmux.core.video import (
    VideoInspectionError,
    VideoOptimizationProgress,
    cached_optimized_video_for_source,
    configured_video_profile,
    optimize_video,
)


@dataclass(frozen=True)
class QueuedVideo:
    key: str
    path: Path
    config: dict[str, Any]


class VideoOptimizationQueue:
    def __init__(
        self,
        *,
        max_workers: int = 2,
        event_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.max_workers = max(1, min(2, max_workers))
        self.event_callback = event_callback
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="wallmux-video",
        )
        self.pending: deque[QueuedVideo] = deque()
        self.running: dict[str, Future] = {}
        self.known: set[str] = set()
        self.progress: dict[str, dict[str, Any]] = {}
        self.notification_ids: dict[str, int] = {}
        self.last_notification_at: dict[str, float] = {}
        self.lock = threading.RLock()

    def enqueue_library(self, items: list[WallpaperItem], config: dict[str, Any]) -> int:
        if not _auto_optimize_enabled(config):
            return 0
        added = 0
        with self.lock:
            for item in items:
                if item.wallpaper_type is not WallpaperType.VIDEO:
                    continue
                key = _video_key(item.path, config)
                if key in self.known or key in self.running:
                    continue
                if cached_optimized_video_for_source(item.path, config) is not None:
                    self.known.add(key)
                    continue
                self.known.add(key)
                self.pending.append(
                    QueuedVideo(
                        key=key,
                        path=item.path.expanduser().resolve(),
                        config=deepcopy(config),
                    )
                )
                self.progress[key] = {
                    "file": str(item.path),
                    "status": "queued",
                    "percent": 0.0,
                }
                added += 1
        self.pump()
        return added

    def pump(self) -> None:
        with self.lock:
            while self.pending and len(self.running) < self.max_workers:
                item = self.pending.popleft()
                future = self.executor.submit(self._optimize, item)
                self.running[item.key] = future
                future.add_done_callback(
                    lambda completed, queued=item: self._completed(queued, completed)
                )

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "max_concurrent_jobs": self.max_workers,
                "queued": len(self.pending),
                "running": len(self.running),
                "jobs": list(self.progress.values()),
            }

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _optimize(self, item: QueuedVideo):
        notification_id = notify_video_optimization(
            item.config,
            "Optimizing video wallpaper",
            f"Starting {item.path.name}",
            percent=0,
        )
        if notification_id is not None:
            with self.lock:
                self.notification_ids[item.key] = notification_id
        self._set_progress(item, "running", 0.0)
        self._event("video-optimize", f"started {item.path.name}", "info")
        return optimize_video(
            item.path,
            profile=configured_video_profile(item.config),
            config=item.config,
            progress_callback=lambda progress: self._on_progress(item, progress),
        )

    def _on_progress(self, item: QueuedVideo, progress: VideoOptimizationProgress) -> None:
        percent = progress.percent
        self._set_progress(item, "running", percent)
        now = time.monotonic()
        with self.lock:
            last = self.last_notification_at.get(item.key, 0.0)
            notification_id = self.notification_ids.get(item.key)
            if now - last < 2.0 and progress.progress != "end":
                return
            self.last_notification_at[item.key] = now
        percent_text = "working" if percent is None else f"{percent:.0f}%"
        replacement = notify_video_optimization(
            item.config,
            "Optimizing video wallpaper",
            f"{item.path.name}: {percent_text}",
            percent=percent,
            replace_id=notification_id,
        )
        if replacement is not None:
            with self.lock:
                self.notification_ids[item.key] = replacement

    def _completed(self, item: QueuedVideo, future: Future) -> None:
        try:
            result = future.result()
        except VideoInspectionError as error:
            with self.lock:
                self.known.discard(item.key)
            self._finish_notification(item, "Video optimization failed", str(error))
            self._set_progress(item, "failed", None, error=str(error))
            self._event("video-optimize", f"failed {item.path.name}: {error}", "error")
        except Exception as error:  # pragma: no cover - worker safety boundary.
            with self.lock:
                self.known.discard(item.key)
            self._finish_notification(item, "Video optimization failed", str(error))
            self._set_progress(item, "failed", None, error=str(error))
            self._event("video-optimize", f"failed {item.path.name}: {error}", "error")
        else:
            status = "skipped" if result.skipped else "done"
            self._finish_notification(
                item,
                "Video optimization finished",
                f"{item.path.name}: {result.message}",
                percent=100,
            )
            self._set_progress(item, status, 100.0)
            self._event("video-optimize", f"{status} {item.path.name}", "info")
        finally:
            with self.lock:
                self.running.pop(item.key, None)
                self.notification_ids.pop(item.key, None)
                self.last_notification_at.pop(item.key, None)
            self.pump()

    def _finish_notification(
        self,
        item: QueuedVideo,
        title: str,
        body: str,
        *,
        percent: float | None = None,
    ) -> None:
        with self.lock:
            notification_id = self.notification_ids.get(item.key)
        notify_video_optimization(
            item.config,
            title,
            body,
            percent=percent,
            replace_id=notification_id,
        )

    def _set_progress(
        self,
        item: QueuedVideo,
        status: str,
        percent: float | None,
        *,
        error: str | None = None,
    ) -> None:
        with self.lock:
            entry = {
                "file": str(item.path),
                "status": status,
                "percent": percent,
            }
            if error:
                entry["error"] = error
            self.progress[item.key] = entry

    def _event(self, kind: str, message: str, status: str) -> None:
        if self.event_callback is not None:
            self.event_callback(kind, message, status)


def _auto_optimize_enabled(config: dict[str, Any]) -> bool:
    settings = config.get("video_optimization", {})
    return bool(settings.get("auto_optimize", settings.get("enabled", True)))


def _video_key(path: Path, config: dict[str, Any]) -> str:
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
        fingerprint = f"{resolved}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        fingerprint = str(resolved)
    return f"{fingerprint}:{configured_video_profile(config)}"
