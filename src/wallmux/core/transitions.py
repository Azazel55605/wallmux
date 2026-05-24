"""State-aware wallpaper transition planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from wallmux.core.mime import WallpaperType
from wallmux.core.state import WallpaperEntry


class TransitionKind(Enum):
    FIRST_SET = "first_set"
    IMAGE_TO_IMAGE = "image_to_image"
    IMAGE_TO_VIDEO = "image_to_video"
    VIDEO_TO_IMAGE = "video_to_image"
    VIDEO_TO_VIDEO = "video_to_video"


VIDEO_BACKENDS = {"mpvpaper", "gslapper"}


@dataclass(frozen=True)
class TransitionPlan:
    kind: TransitionKind
    stop_previous_video: bool = False


def plan_transition(
    previous: WallpaperEntry | None,
    next_type: WallpaperType,
    next_backend: str | None = None,
) -> TransitionPlan:
    if previous is None:
        return TransitionPlan(TransitionKind.FIRST_SET)

    previous_is_video = _entry_is_video(previous)
    next_is_video = next_type is WallpaperType.VIDEO or next_backend in VIDEO_BACKENDS

    if previous_is_video and next_is_video:
        return TransitionPlan(TransitionKind.VIDEO_TO_VIDEO, stop_previous_video=True)
    if previous_is_video and not next_is_video:
        return TransitionPlan(TransitionKind.VIDEO_TO_IMAGE, stop_previous_video=True)
    if not previous_is_video and next_is_video:
        return TransitionPlan(TransitionKind.IMAGE_TO_VIDEO)
    return TransitionPlan(TransitionKind.IMAGE_TO_IMAGE)


def _entry_is_video(entry: WallpaperEntry) -> bool:
    return entry.wallpaper_type == WallpaperType.VIDEO.value or entry.backend in VIDEO_BACKENDS
