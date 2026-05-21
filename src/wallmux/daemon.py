"""Wallmux daemon entry point."""

from __future__ import annotations

from wallmux.core.daemon import WallmuxDaemon


def main() -> int:
    WallmuxDaemon().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
