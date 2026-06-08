from __future__ import annotations

from pathlib import Path

from wallmux.core.video_posters import ensure_video_poster, video_poster_path


def test_video_poster_path_changes_with_source_and_timestamp(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    first = video_poster_path(video, 0.0)
    later = video_poster_path(video, 1.0)
    video.write_bytes(b"changed")
    changed = video_poster_path(video, 0.0)

    assert first != later
    assert first != changed


def test_ensure_video_poster_reuses_cached_file(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    target = tmp_path / "poster.jpg"
    target.write_bytes(b"poster")
    monkeypatch.setattr("wallmux.core.video_posters.video_poster_path", lambda *_args: target)
    monkeypatch.setattr(
        "wallmux.core.video_posters.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ffmpeg ran")),
    )

    assert ensure_video_poster(video) == target
