"""PySide6 GUI entry point."""

from __future__ import annotations


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QLabel
    except ImportError:
        print("PySide6 is not installed. Install project dependencies to run wallmux-gui.")
        return 1

    app = QApplication([])
    label = QLabel("Wallmux GUI skeleton - thumbnail grid lands in Phase 3")
    label.resize(520, 120)
    label.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
