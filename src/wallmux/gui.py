"""PySide6 GUI entry point."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from wallmux.core.config import load_config, user_config_file, write_config
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.library import WallpaperItem, filter_wallpapers, scan_wallpaper_dir
from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import list_monitors
from wallmux.core.thumbnails import ensure_thumbnail
from wallmux.core.wallpaper import WallmuxError, set_wallpaper

try:
    from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
    from PySide6.QtGui import QAction, QIcon, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSplitter,
        QStatusBar,
        QStyle,
        QStyleFactory,
        QTabWidget,
        QToolBar,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - exercised by main on systems without PySide6.
    QApplication = None
    QMainWindow = object
    QObject = object
    QRunnable = object

    def Signal(*_args, **_kwargs):
        return None

    def Slot(*_args, **_kwargs):
        def decorator(function):
            return function

        return decorator


TYPE_FILTERS = {
    "All": None,
    "Images": WallpaperType.IMAGE,
    "GIFs": WallpaperType.GIF,
    "Videos": WallpaperType.VIDEO,
}

THEME_DEBUG_ARG = "--theme-debug"
SYSTEM_QT_PLUGIN_PATHS = [
    Path("/usr/lib/qt6/plugins"),
    Path("/usr/lib/qt/plugins"),
    Path("/usr/lib64/qt6/plugins"),
]


class ThumbnailSignals(QObject):
    loaded = Signal(str, str)
    failed = Signal(str)


class ThumbnailTask(QRunnable):
    def __init__(self, item: WallpaperItem, size: int) -> None:
        super().__init__()
        self.item = item
        self.size = size
        self.signals = ThumbnailSignals()

    @Slot()
    def run(self) -> None:
        thumbnail = ensure_thumbnail(self.item.path, self.item.wallpaper_type, self.size)
        if thumbnail is None:
            self.signals.failed.emit(str(self.item.path))
            return
        self.signals.loaded.emit(str(self.item.path), str(thumbnail))


class WallmuxWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.items: list[WallpaperItem] = []
        self.current_folder: Path | None = None
        self.selected_item: WallpaperItem | None = None
        self.pending_thumbnails: set[str] = set()
        self.thumbnail_size = int(self.config.get("general", {}).get("thumbnail_size", 256))
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(min(4, max(2, self.thread_pool.maxThreadCount())))

        self.setWindowTitle("Wallmux")
        self.resize(1100, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._build_browser_tab()
        self._build_settings_tab()
        self._load_monitors()
        self.preview.setText("Choose a folder")
        QTimer.singleShot(0, self._load_initial_folder)

    def _build_browser_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)

        toolbar = QToolBar()
        toolbar.setIconSize(QSize(18, 18))
        open_action = QAction(
            self._theme_icon("folder-open", QStyle.SP_DirOpenIcon),
            "Open Folder",
            self,
        )
        open_action.triggered.connect(self.choose_folder)
        refresh_action = QAction(
            self._theme_icon("view-refresh", QStyle.SP_BrowserReload),
            "Refresh",
            self,
        )
        refresh_action.triggered.connect(self.refresh_library)
        toolbar.addAction(open_action)
        toolbar.addAction(refresh_action)

        self.search_box = QLineEdit()
        self.search_box.setMinimumWidth(240)
        self.search_box.setPlaceholderText("Search")
        self.search_box.textChanged.connect(self.populate_grid)

        self.filter_box = QComboBox()
        self.filter_box.addItems(TYPE_FILTERS.keys())
        self.filter_box.currentTextChanged.connect(self.populate_grid)

        toolbar.addWidget(self.search_box)
        toolbar.addWidget(self.filter_box)
        outer.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(160, 120))
        self.grid.setGridSize(QSize(190, 170))
        self.grid.itemSelectionChanged.connect(self.select_current_item)
        splitter.addWidget(self.grid)

        panel = QFrame()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(360)
        panel_layout = QVBoxLayout(panel)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        panel_layout.addWidget(self.preview)

        self.info_label = QLabel("No wallpaper selected")
        self.info_label.setWordWrap(True)
        panel_layout.addWidget(self.info_label)

        form = QFormLayout()
        self.backend_label = QLabel("-")
        self.monitor_box = QComboBox()
        form.addRow("Backend", self.backend_label)
        form.addRow("Monitor", self.monitor_box)
        panel_layout.addLayout(form)

        self.set_button = QPushButton("Set Wallpaper")
        self.set_button.clicked.connect(self.set_selected_wallpaper)
        self.set_button.setEnabled(False)
        panel_layout.addWidget(self.set_button)
        panel_layout.addStretch(1)

        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        outer.addWidget(splitter, 1)

        self.tabs.addTab(tab, "Browser")

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.config_path_label = QLabel(str(user_config_file()))
        self.config_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(QLabel("Config"))
        layout.addWidget(self.config_path_label)

        self.folder_list = QListWidget()
        layout.addWidget(QLabel("Wallpaper Folders"))
        layout.addWidget(self.folder_list, 1)

        buttons = QHBoxLayout()
        add_button = QPushButton("Add Folder")
        add_button.clicked.connect(self.add_config_folder)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_config_folder)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.tabs.addTab(tab, "Settings")
        self.refresh_settings()

    def _load_initial_folder(self) -> None:
        dirs = self.config.get("general", {}).get("wallpaper_dirs", [])
        for raw_dir in dirs:
            path = Path(raw_dir).expanduser()
            if path.exists() and path.is_dir():
                self.load_folder(path)
                return
        self.populate_grid()

    def _load_monitors(self) -> None:
        self.monitor_box.clear()
        monitors = list_monitors()
        if monitors:
            for monitor in monitors:
                self.monitor_box.addItem(monitor.name)
        else:
            self.monitor_box.addItem("all")

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Wallpaper Folder")
        if selected:
            self.load_folder(Path(selected))

    def load_folder(self, folder: Path) -> None:
        self.current_folder = folder
        self.status.showMessage(f"Scanning {folder}")
        self.items = scan_wallpaper_dir(
            folder,
            backend_rules=self.config.get("backend_rules", {}),
        )
        self.populate_grid()
        self.status.showMessage(f"{len(self.items)} wallpapers in {folder}", 5000)

    def refresh_library(self) -> None:
        if self.current_folder is not None:
            self.load_folder(self.current_folder)
        else:
            self.populate_grid()
        self._load_monitors()

    def populate_grid(self) -> None:
        self.grid.clear()
        selected_type = TYPE_FILTERS[self.filter_box.currentText()]
        query = self.search_box.text()
        for item in filter_wallpapers(self.items, query=query, wallpaper_type=selected_type):
            widget_item = QListWidgetItem(self._placeholder_icon(item), item.path.name)
            widget_item.setData(Qt.ItemDataRole.UserRole, item)
            widget_item.setToolTip(str(item.path))
            self.grid.addItem(widget_item)
            self.queue_thumbnail(item)

        if self.grid.count() == 0:
            self.preview.setText("No wallpapers")
            self.set_button.setEnabled(False)

    def select_current_item(self) -> None:
        selected = self.grid.selectedItems()
        if not selected:
            self.selected_item = None
            self.set_button.setEnabled(False)
            return

        self.selected_item = selected[0].data(Qt.ItemDataRole.UserRole)
        self.backend_label.setText(self.selected_item.backend)
        self.info_label.setText(
            f"{self.selected_item.path.name}\n"
            f"{self.selected_item.wallpaper_type.value}\n"
            f"{self.selected_item.path}"
        )
        self._set_preview_pixmap(self._placeholder_pixmap(self.selected_item))
        self.queue_thumbnail(self.selected_item)
        self.set_button.setEnabled(True)

    def set_selected_wallpaper(self) -> None:
        if self.selected_item is None:
            return

        monitor = self.monitor_box.currentText()
        request = {
            "command": "set",
            "file": str(self.selected_item.path),
            "monitor": monitor,
        }
        try:
            response = send_request(request)
            if not response.get("ok"):
                raise WallmuxError(response.get("error", "unknown daemon error"))
            result = response["results"][0]
            self.status.showMessage(
                f"Set {Path(result['file']).name} on {result['monitor']} via {result['backend']}",
                6000,
            )
        except DaemonUnavailable:
            try:
                result = set_wallpaper(self.selected_item.path, monitor, config=self.config)
            except (ValueError, WallmuxError) as error:
                QMessageBox.critical(self, "Wallmux", str(error))
                return
            self.status.showMessage(
                f"Set {result.file.name} on {result.monitor} via {result.backend}",
                6000,
            )
        except WallmuxError as error:
            QMessageBox.critical(self, "Wallmux", str(error))

    def add_config_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Add Wallpaper Folder")
        if not selected:
            return

        dirs = self.config.setdefault("general", {}).setdefault("wallpaper_dirs", [])
        if selected not in dirs:
            dirs.append(selected)
            write_config(self.config, user_config_file())
        self.refresh_settings()
        self.load_folder(Path(selected))

    def remove_config_folder(self) -> None:
        selected = self.folder_list.selectedItems()
        if not selected:
            return

        folder = selected[0].text()
        dirs = self.config.setdefault("general", {}).setdefault("wallpaper_dirs", [])
        self.config["general"]["wallpaper_dirs"] = [item for item in dirs if item != folder]
        write_config(self.config, user_config_file())
        self.refresh_settings()

    def refresh_settings(self) -> None:
        self.folder_list.clear()
        for folder in self.config.get("general", {}).get("wallpaper_dirs", []):
            self.folder_list.addItem(folder)

    def queue_thumbnail(self, item: WallpaperItem) -> None:
        key = str(item.path)
        if key in self.pending_thumbnails:
            return

        self.pending_thumbnails.add(key)
        task = ThumbnailTask(item, self.thumbnail_size)
        task.signals.loaded.connect(self.apply_thumbnail)
        task.signals.failed.connect(self.finish_thumbnail)
        self.thread_pool.start(task)

    def apply_thumbnail(self, source_path: str, thumbnail_path: str) -> None:
        self.finish_thumbnail(source_path)
        pixmap = QPixmap(thumbnail_path)
        if pixmap.isNull():
            return

        icon = QIcon(pixmap)
        for index in range(self.grid.count()):
            widget_item = self.grid.item(index)
            item = widget_item.data(Qt.ItemDataRole.UserRole)
            if str(item.path) == source_path:
                widget_item.setIcon(icon)

        if self.selected_item is not None and str(self.selected_item.path) == source_path:
            self._set_preview_pixmap(pixmap)

    def finish_thumbnail(self, source_path: str) -> None:
        self.pending_thumbnails.discard(source_path)

    def _set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self.preview.setPixmap(
            pixmap.scaled(
                320,
                220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _placeholder_icon(self, item: WallpaperItem) -> QIcon:
        if item.wallpaper_type is WallpaperType.VIDEO:
            return self._theme_icon("video-x-generic", QStyle.SP_FileIcon)
        if item.wallpaper_type is WallpaperType.GIF:
            return self._theme_icon("image-gif", QStyle.SP_FileIcon)
        return self._theme_icon("image-x-generic", QStyle.SP_FileIcon)

    def _placeholder_pixmap(self, item: WallpaperItem) -> QPixmap:
        return self._placeholder_icon(item).pixmap(QSize(160, 120))

    def _theme_icon(self, name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
        return self.style().standardIcon(fallback)


def main() -> int:
    if QApplication is None:
        print("PySide6 is not installed. Install project dependencies to run wallmux-gui.")
        return 1

    try:
        theme_debug = THEME_DEBUG_ARG in sys.argv
        argv = [arg for arg in sys.argv if arg != THEME_DEBUG_ARG]

        QApplication.setDesktopSettingsAware(True)
        _add_system_qt_plugin_paths()
        app = QApplication(argv)
        app.setApplicationName("Wallmux")
        app.setApplicationDisplayName("Wallmux")

        if theme_debug:
            _print_theme_debug(app)
            return 0

        window = WallmuxWindow()
        window.show()
        return app.exec()
    except Exception:
        traceback.print_exc()
        return 1


def _add_system_qt_plugin_paths() -> None:
    for path in SYSTEM_QT_PLUGIN_PATHS:
        if path.exists():
            QApplication.addLibraryPath(str(path))


def _print_theme_debug(app: QApplication) -> None:
    print(f"platform: {app.platformName()}")
    print(f"style: {app.style().objectName()}")
    print(f"available styles: {', '.join(QStyleFactory.keys())}")
    print("library paths:")
    for path in QApplication.libraryPaths():
        print(f"  {path}")


if __name__ == "__main__":
    raise SystemExit(main())
