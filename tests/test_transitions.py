from wallmux.core.mime import WallpaperType
from wallmux.core.state import WallpaperEntry
from wallmux.core.transitions import TransitionKind, plan_transition


def test_first_set_transition() -> None:
    plan = plan_transition(None, WallpaperType.IMAGE)

    assert plan.kind is TransitionKind.FIRST_SET
    assert plan.stop_previous_video is False


def test_image_to_video_transition() -> None:
    previous = WallpaperEntry(
        file="/tmp/wall.png",
        backend="awww",
        wallpaper_type="image",
    )

    plan = plan_transition(previous, WallpaperType.VIDEO)

    assert plan.kind is TransitionKind.IMAGE_TO_VIDEO
    assert plan.stop_previous_video is False


def test_video_to_image_transition_stops_previous_video() -> None:
    previous = WallpaperEntry(
        file="/tmp/wall.mp4",
        backend="mpvpaper",
        wallpaper_type="video",
        pid=1234,
    )

    plan = plan_transition(previous, WallpaperType.IMAGE)

    assert plan.kind is TransitionKind.VIDEO_TO_IMAGE
    assert plan.stop_previous_video is True


def test_video_to_video_transition_stops_previous_video() -> None:
    previous = WallpaperEntry(
        file="/tmp/one.mp4",
        backend="mpvpaper",
        wallpaper_type="video",
        pid=1234,
    )

    plan = plan_transition(previous, WallpaperType.VIDEO)

    assert plan.kind is TransitionKind.VIDEO_TO_VIDEO
    assert plan.stop_previous_video is True
