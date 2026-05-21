from wallmux.core.config import load_config


def test_loads_default_config() -> None:
    config = load_config()
    assert config["backend_rules"]["image"] == "awww"
    assert config["backend_rules"]["video"] == "mpvpaper"
