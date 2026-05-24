from __future__ import annotations

from wallmux.core.inhibition import HyprlandClient, evaluate_inhibition


def test_inhibits_for_fullscreen_client() -> None:
    config = {"inhibition": {"enabled": True, "fullscreen": True}}

    status = evaluate_inhibition(
        config,
        clients=[HyprlandClient(class_name="firefox", title="Video", fullscreen=True)],
    )

    assert status.inhibited is True
    assert status.reason == "fullscreen: firefox"


def test_inhibits_for_matching_class_pattern() -> None:
    config = {
        "inhibition": {
            "enabled": True,
            "fullscreen": False,
            "class_patterns": ["^steam_app_"],
            "title_patterns": [],
        }
    }

    status = evaluate_inhibition(
        config,
        clients=[HyprlandClient(class_name="steam_app_123", title="Game")],
    )

    assert status.inhibited is True
    assert status.reason == "class: steam_app_123"


def test_inhibits_for_matching_process_name() -> None:
    config = {
        "inhibition": {
            "enabled": True,
            "fullscreen": False,
            "process_names": ["gamescope"],
            "class_patterns": [],
            "title_patterns": [],
        }
    }

    status = evaluate_inhibition(
        config,
        clients=[],
        process_checker=lambda name: name == "gamescope",
    )

    assert status.inhibited is True
    assert status.reason == "process: gamescope"


def test_no_inhibition_when_disabled() -> None:
    status = evaluate_inhibition(
        {"inhibition": {"enabled": False}},
        clients=[HyprlandClient(class_name="steam_app_123", title="Game", fullscreen=True)],
    )

    assert status.inhibited is False
