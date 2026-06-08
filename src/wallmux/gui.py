"""PySide6 GUI entry point."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from wallmux.backends.routing import compatible_backends
from wallmux.core.cache import (
    cache_stats,
    clean_cache,
    format_cache_clean_result,
    format_cache_rebuild_result,
    format_cache_stats,
    rebuild_cache,
)
from wallmux.core.config import load_config, user_config_file, write_config
from wallmux.core.doctor import format_doctor_report, run_doctor
from wallmux.core.hooks import hook_log_file
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.library import WallpaperItem, filter_wallpapers, scan_wallpaper_dir
from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import list_monitors
from wallmux.core.notifications import notify_switch_failed, notify_wallpaper_switched
from wallmux.core.profiles import (
    effective_config_for_profile,
    get_active_profile,
    list_profiles,
    profile_entries_from_category_root,
    profile_matches_filters,
    switch_profile,
)
from wallmux.core.thumbnails import ensure_thumbnail
from wallmux.core.video import (
    cached_optimized_video_for_source,
    configured_video_cache_dir,
    format_video_library_optimization_result,
    format_video_optimization_result,
    optimize_video,
    optimize_video_library,
)
from wallmux.core.wallpaper import WallmuxError, set_wallpaper, set_wallpaper_for_all

try:
    from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
    from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSplitter,
        QStatusBar,
        QStyle,
        QStyleFactory,
        QTabWidget,
        QTextEdit,
        QToolBar,
        QTreeWidget,
        QTreeWidgetItem,
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

ALL_MONITORS = "__all_monitors__"
IMAGE_BACKENDS = {"awww", "swww", "hyprpaper"}
VIDEO_BACKENDS = {"mpvpaper", "gslapper"}
APP_ID = "wallmux-gui"
WINDOW_TITLE = "wallmux"
IMAGE_TRANSITIONS = [
    "none",
    "simple",
    "fade",
    "left",
    "right",
    "top",
    "bottom",
    "wipe",
    "wave",
    "grow",
    "center",
    "any",
    "outer",
    "random",
]

THEME_DEBUG_ARG = "--theme-debug"
PROFILE_PICKER_ARG = "profile-picker"
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
        self.setAutoDelete(False)
        self.item = item
        self.size = size
        self.signals = ThumbnailSignals()

    @Slot()
    def run(self) -> None:
        thumbnail = ensure_thumbnail(self.item.path, self.item.wallpaper_type, self.size)
        try:
            if thumbnail is None:
                self.signals.failed.emit(str(self.item.path))
                return
            self.signals.loaded.emit(str(self.item.path), str(thumbnail))
        except RuntimeError:
            return


class VideoOptimizeSignals(QObject):
    progress = Signal(str)
    source_progress = Signal(str, float, str)
    source_done = Signal(str, str)
    source_failed = Signal(str, str)
    finished = Signal(str)
    failed = Signal(str)


class CacheMaintenanceSignals(QObject):
    finished = Signal(str)
    failed = Signal(str)


class VideoOptimizeTask(QRunnable):
    def __init__(
        self,
        items: list[WallpaperItem],
        *,
        profile: str,
        force: bool,
        library: bool,
        config: dict,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.items = items
        self.profile = profile
        self.force = force
        self.library = library
        self.config = config
        self.signals = VideoOptimizeSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.library:
                result = optimize_video_library(
                    self.items,
                    profile=self.profile,
                    force=self.force,
                    config=self.config,
                    progress_callback=self._library_progress,
                )
                for item in result.optimized:
                    self._emit(self.signals.source_done, str(item.plan.source), item.message)
                for item in result.skipped:
                    self._emit(self.signals.source_done, str(item.plan.source), item.message)
                for item in result.failed:
                    self._emit(self.signals.source_failed, item["file"], item["error"])
                self._emit(
                    self.signals.finished,
                    format_video_library_optimization_result(result),
                )
                return

            result = optimize_video(
                self.items[0].path,
                profile=self.profile,
                force=self.force,
                config=self.config,
                progress_callback=self._progress,
            )
            self._emit(self.signals.source_done, str(result.plan.source), result.message)
            self._emit(self.signals.finished, format_video_optimization_result(result))
        except Exception as error:  # pragma: no cover - defensive GUI boundary.
            if self.items:
                self._emit(self.signals.source_failed, str(self.items[0].path), str(error))
            self._emit(self.signals.failed, str(error))

    def _library_progress(self, path: Path, progress) -> None:
        message = f"{path.name}: {_video_progress_text(progress)}"
        self._emit(self.signals.progress, message)
        self._emit(
            self.signals.source_progress,
            str(path),
            -1.0 if progress.percent is None else progress.percent,
            message,
        )

    def _progress(self, progress) -> None:
        message = _video_progress_text(progress)
        self._emit(self.signals.progress, message)
        self._emit(
            self.signals.source_progress,
            str(self.items[0].path),
            -1.0 if progress.percent is None else progress.percent,
            message,
        )

    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            return


class CacheMaintenanceTask(QRunnable):
    def __init__(
        self,
        *,
        mode: str,
        config: dict,
        items: list[WallpaperItem] | None = None,
        include_thumbnails: bool = True,
        include_videos: bool = True,
        policy: str | None = None,
        force_videos: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.mode = mode
        self.config = config
        self.items = items or []
        self.include_thumbnails = include_thumbnails
        self.include_videos = include_videos
        self.policy = policy
        self.force_videos = force_videos
        self.signals = CacheMaintenanceSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.mode == "clean":
                result = clean_cache(
                    self.config,
                    include_thumbnails=self.include_thumbnails,
                    include_videos=self.include_videos,
                    policy=self.policy,
                )
                self._emit(self.signals.finished, format_cache_clean_result(result))
                return
            result = rebuild_cache(
                self.items,
                self.config,
                include_thumbnails=self.include_thumbnails,
                include_videos=self.include_videos,
                force_videos=self.force_videos,
            )
            self._emit(self.signals.finished, format_cache_rebuild_result(result))
        except Exception as error:  # pragma: no cover - defensive GUI boundary.
            self._emit(self.signals.failed, str(error))

    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            return


class WallmuxWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.items: list[WallpaperItem] = []
        self.current_folder: Path | None = None
        self.selected_item: WallpaperItem | None = None
        self.pending_thumbnails: set[str] = set()
        self.thumbnail_tasks: dict[str, ThumbnailTask] = {}
        self.thumbnail_pixmaps: dict[str, QPixmap] = {}
        self.video_optimize_tasks: dict[str, VideoOptimizeTask] = {}
        self.video_optimize_state: dict[str, dict] = {}
        self.video_cache_size_before: int | None = None
        self.cache_task: CacheMaintenanceTask | None = None
        self.zen_mode = False
        self.daemon_running = False
        self.profile_settings_loading = False
        self.thumbnail_size = int(self.config.get("general", {}).get("thumbnail_size", 256))
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(min(4, max(2, self.thread_pool.maxThreadCount())))
        self.profile_autosave_timer = QTimer(self)
        self.profile_autosave_timer.setSingleShot(True)
        self.profile_autosave_timer.setInterval(700)
        self.profile_autosave_timer.timeout.connect(self.autosave_profile_settings)
        self.global_profile_hooks_autosave_timer = QTimer(self)
        self.global_profile_hooks_autosave_timer.setSingleShot(True)
        self.global_profile_hooks_autosave_timer.setInterval(700)
        self.global_profile_hooks_autosave_timer.timeout.connect(
            self.autosave_global_profile_hooks
        )

        self.setWindowFlag(Qt.WindowType.Dialog, True)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1100, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self._build_browser_tab()
        self._build_state_tab()
        self._build_settings_tab()
        self._build_shortcuts()
        self._load_monitors()
        self.refresh_daemon_status()
        self.daemon_status_timer = QTimer(self)
        self.daemon_status_timer.timeout.connect(self.refresh_daemon_status)
        self.daemon_status_timer.start(5000)
        self.video_optimization_status_timer = QTimer(self)
        self.video_optimization_status_timer.timeout.connect(
            self.refresh_daemon_video_optimization
        )
        self.video_optimization_status_timer.start(2000)
        self.set_zen_mode(
            bool(self.config.get("gui", {}).get("zen_mode", False)),
            persist=False,
        )
        self.preview.setText("Choose a folder")
        QTimer.singleShot(0, self._load_initial_folder)
        QTimer.singleShot(0, self.refresh_state_tab)

    def _build_browser_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)

        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(18, 18))
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
        profile_action = QAction(
            self._theme_icon("view-list-symbolic", QStyle.SP_FileDialogListView),
            "Profiles",
            self,
        )
        profile_action.triggered.connect(self.show_profile_picker)
        self.toolbar.addAction(open_action)
        self.toolbar.addAction(refresh_action)
        self.toolbar.addAction(profile_action)

        self.search_box = QLineEdit()
        self.search_box.setMinimumWidth(240)
        self.search_box.setPlaceholderText("Search")
        self.search_box.textChanged.connect(self.populate_grid)

        self.filter_box = QComboBox()
        self.filter_box.addItems(TYPE_FILTERS.keys())
        self.filter_box.currentTextChanged.connect(self.populate_grid)

        self.toolbar.addWidget(self.search_box)
        self.toolbar.addWidget(self.filter_box)
        outer.addWidget(self.toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.grid = QListWidget()
        self.grid.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(160, 120))
        self.grid.setGridSize(QSize(190, 170))
        self.grid.itemSelectionChanged.connect(self.select_current_item)
        self.grid.itemActivated.connect(self.set_selected_wallpaper)
        self.splitter.addWidget(self.grid)

        self.side_panel = QFrame()
        self.side_panel.setMinimumWidth(280)
        self.side_panel.setMaximumWidth(360)
        panel_layout = QVBoxLayout(self.side_panel)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        panel_layout.addWidget(self.preview)

        self.info_label = QLabel("No wallpaper selected")
        self.info_label.setWordWrap(True)
        panel_layout.addWidget(self.info_label)

        form = QFormLayout()
        self.backend_box = QComboBox()
        self.backend_box.currentTextChanged.connect(self._backend_changed)
        self.monitor_box = QComboBox()
        form.addRow("Backend", self.backend_box)
        form.addRow("Monitor", self.monitor_box)
        panel_layout.addLayout(form)

        self.set_button = QPushButton("Set Wallpaper")
        self.set_button.clicked.connect(self.set_selected_wallpaper)
        self.set_button.setEnabled(False)
        panel_layout.addWidget(self.set_button)
        panel_layout.addStretch(1)

        self.splitter.addWidget(self.side_panel)
        self.splitter.setStretchFactor(0, 1)
        outer.addWidget(self.splitter, 1)

        self.tabs.addTab(tab, "Browser")

    def _build_state_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.state_view = QTextEdit()
        self.state_view.setReadOnly(True)
        self.state_view.setMinimumHeight(360)
        layout.addWidget(self.state_view, 1)

        buttons = QHBoxLayout()
        refresh_button = QPushButton("Refresh State")
        refresh_button.clicked.connect(self.refresh_state_tab)
        start_button = QPushButton("Start Daemon")
        start_button.clicked.connect(lambda: self.control_daemon("start"))
        restart_button = QPushButton("Restart Daemon")
        restart_button.clicked.connect(lambda: self.control_daemon("restart"))
        stop_button = QPushButton("Stop Daemon")
        stop_button.clicked.connect(lambda: self.control_daemon("stop"))
        buttons.addWidget(refresh_button)
        buttons.addWidget(start_button)
        buttons.addWidget(restart_button)
        buttons.addWidget(stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.tabs.addTab(tab, "State")

    def _build_shortcuts(self) -> None:
        zen_action = QAction("Toggle Zen Mode", self)
        zen_action.setShortcuts([QKeySequence("F11"), QKeySequence("Ctrl+Z")])
        zen_action.triggered.connect(self.toggle_zen_mode)
        self.addAction(zen_action)

        exit_zen_action = QAction("Close", self)
        exit_zen_action.setShortcut(QKeySequence("Escape"))
        exit_zen_action.triggered.connect(self.close)
        self.addAction(exit_zen_action)

        set_action = QAction("Set Selected Wallpaper", self)
        set_action.setShortcuts([QKeySequence("Return"), QKeySequence("Enter")])
        set_action.triggered.connect(self.set_selected_wallpaper)
        self.addAction(set_action)

        profile_picker_action = QAction("Open Profile Picker", self)
        profile_picker_action.setShortcut(QKeySequence("Ctrl+P"))
        profile_picker_action.triggered.connect(self.show_profile_picker)
        self.addAction(profile_picker_action)

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        self.settings_tabs = QTabWidget()
        outer.addWidget(self.settings_tabs)

        general_page, general_layout = self._settings_page()
        library_page, library_layout = self._settings_page()
        profiles_page, profiles_layout = self._settings_page()
        backend_page, backend_page_layout = self._settings_page()
        video_page, video_layout = self._settings_page()
        cache_page, cache_layout = self._settings_page()
        autoswitch_page, autoswitch_layout = self._settings_page()
        inhibition_page, inhibition_layout = self._settings_page()
        notifications_page, notifications_layout = self._settings_page()
        hooks_page, hooks_page_layout = self._settings_page()
        transitions_page, transitions_layout = self._settings_page()

        self.config_path_label = QLabel(str(user_config_file()))
        self.config_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        general_group = QGroupBox("General")
        general_form = QFormLayout(general_group)
        general_form.addRow("Config", self.config_path_label)

        self.zen_mode_check = QCheckBox("Zen mode")
        self.zen_mode_check.setToolTip("Show only the wallpaper grid.")
        self.zen_mode_check.toggled.connect(self.set_zen_mode)
        general_form.addRow("", self.zen_mode_check)

        self.close_after_set_check = QCheckBox("Close immediately after requesting wallpaper")
        self.close_after_set_check.toggled.connect(self.set_close_after_set)
        general_form.addRow("", self.close_after_set_check)

        self.all_monitor_mode_box = QComboBox()
        self.all_monitor_mode_box.addItem("All at the same time", "simultaneous")
        self.all_monitor_mode_box.addItem("One by one", "sequential")
        general_form.addRow(
            _form_label(
                "All Monitors",
                "Controls how Wallmux applies one wallpaper to every monitor. "
                "Simultaneous sends one grouped command when the backend supports it.",
            ),
            self.all_monitor_mode_box,
        )
        general_layout.addWidget(general_group)
        general_layout.addStretch(1)

        autoswitch_group = QGroupBox("Auto Switching")
        autoswitch_form = QFormLayout(autoswitch_group)
        self.daemon_status_label = QLabel("wallmuxd: unknown")
        self.autoswitch_enabled_check = QCheckBox("Enabled")
        self.autoswitch_interval_spin = QDoubleSpinBox()
        self.autoswitch_interval_spin.setRange(1.0, 86400.0)
        self.autoswitch_interval_spin.setSingleStep(30.0)
        self.autoswitch_interval_spin.setDecimals(0)
        self.autoswitch_mode_box = QComboBox()
        self.autoswitch_mode_box.addItem("Random", "random")
        self.autoswitch_mode_box.addItem("Name up", "name-up")
        self.autoswitch_mode_box.addItem("Name down", "name-down")
        self.autoswitch_target_box = QComboBox()
        self.autoswitch_target_box.addItem("All monitors", "all")
        self.autoswitch_target_box.addItem("Focused monitor", "focused")
        self.autoswitch_target_box.addItem("Specific monitor", "monitor")
        self.autoswitch_monitor_edit = QLineEdit()
        autoswitch_form.addRow("Daemon", self.daemon_status_label)
        autoswitch_form.addRow("", self.autoswitch_enabled_check)
        autoswitch_form.addRow(
            _form_label("Interval", "Seconds between automatic wallpaper switches."),
            self.autoswitch_interval_spin,
        )
        autoswitch_form.addRow(
            _form_label(
                "Next Wallpaper",
                "Random chooses from the active library. Name up/down walks the sorted list.",
            ),
            self.autoswitch_mode_box,
        )
        autoswitch_form.addRow(
            _form_label(
                "Target",
                "Where automatic switches apply: all monitors, focused monitor, "
                "or one named monitor.",
            ),
            self.autoswitch_target_box,
        )
        autoswitch_form.addRow(
            _form_label(
                "Monitor",
                "Monitor name used only when the target is Specific monitor.",
            ),
            self.autoswitch_monitor_edit,
        )
        autoswitch_buttons = QHBoxLayout()
        save_autoswitch_button = QPushButton("Save Auto Switching")
        save_autoswitch_button.clicked.connect(self.save_autoswitch_settings)
        self.autoswitch_now_button = QPushButton("Switch Now")
        self.autoswitch_now_button.clicked.connect(self.autoswitch_now)
        autoswitch_buttons.addWidget(save_autoswitch_button)
        autoswitch_buttons.addWidget(self.autoswitch_now_button)
        autoswitch_buttons.addStretch(1)
        autoswitch_form.addRow("", autoswitch_buttons)
        autoswitch_layout.addWidget(autoswitch_group)
        autoswitch_layout.addStretch(1)

        inhibition_group = QGroupBox("Inhibition")
        inhibition_form = QFormLayout(inhibition_group)
        self.inhibition_enabled_check = QCheckBox("Enabled")
        self.inhibition_pause_autoswitch_check = QCheckBox("Pause auto switching")
        self.inhibition_pause_videos_check = QCheckBox("Pause video wallpapers")
        self.inhibition_manual_commands_check = QCheckBox("Also inhibit manual daemon commands")
        self.inhibition_manual_commands_check.setToolTip(
            "Blocks GUI sets and daemon-backed wallmuxctl set/random/restore while "
            "inhibition is active. wallmuxctl --direct is still allowed."
        )
        self.inhibition_fullscreen_check = QCheckBox("Any fullscreen window")
        self.inhibition_interval_spin = QDoubleSpinBox()
        self.inhibition_interval_spin.setRange(1.0, 300.0)
        self.inhibition_interval_spin.setSingleStep(1.0)
        self.inhibition_interval_spin.setDecimals(1)
        self.inhibition_process_names_edit = QTextEdit()
        self.inhibition_process_names_edit.setMinimumHeight(55)
        self.inhibition_class_patterns_edit = QTextEdit()
        self.inhibition_class_patterns_edit.setMinimumHeight(70)
        self.inhibition_title_patterns_edit = QTextEdit()
        self.inhibition_title_patterns_edit.setMinimumHeight(70)
        inhibition_form.addRow("", self.inhibition_enabled_check)
        inhibition_form.addRow("", self.inhibition_pause_autoswitch_check)
        inhibition_form.addRow("", self.inhibition_pause_videos_check)
        inhibition_form.addRow("", self.inhibition_manual_commands_check)
        inhibition_form.addRow("", self.inhibition_fullscreen_check)
        inhibition_form.addRow(
            _form_label(
                "Check Interval",
                "Seconds between inhibition checks. Lower values react faster "
                "but wake up more often.",
            ),
            self.inhibition_interval_spin,
        )
        inhibition_form.addRow(
            _form_label(
                "Process Names",
                "Exact process names that pause autoswitch/video playback, "
                "such as gamescope or wine64.",
            ),
            self.inhibition_process_names_edit,
        )
        inhibition_form.addRow(
            _form_label(
                "Class Patterns",
                "Regular expressions matched against Hyprland window classes.",
            ),
            self.inhibition_class_patterns_edit,
        )
        inhibition_form.addRow(
            _form_label(
                "Title Patterns",
                "Regular expressions matched against Hyprland window titles.",
            ),
            self.inhibition_title_patterns_edit,
        )
        self.battery_behavior_box = QComboBox()
        self.battery_behavior_box.addItem("Keep videos", "keep")
        self.battery_behavior_box.addItem("Pause videos", "pause-videos")
        self.battery_behavior_box.addItem("Skip videos", "skip-videos")
        self.battery_behavior_box.addItem("First frame", "first-frame")
        self.battery_behavior_box.addItem("Pause all", "pause-all")
        self.high_load_behavior_box = QComboBox()
        self.high_load_behavior_box.addItem("Keep", "keep")
        self.high_load_behavior_box.addItem("Pause videos", "pause-videos")
        self.high_load_behavior_box.addItem("Pause auto switching", "pause-autoswitch")
        self.high_load_behavior_box.addItem("Pause all", "pause-all")
        self.cpu_load_threshold_spin = QDoubleSpinBox()
        self.cpu_load_threshold_spin.setRange(0.0, 8.0)
        self.cpu_load_threshold_spin.setSingleStep(0.05)
        self.cpu_load_threshold_spin.setDecimals(2)
        self.gpu_load_threshold_spin = QDoubleSpinBox()
        self.gpu_load_threshold_spin.setRange(0.0, 100.0)
        self.gpu_load_threshold_spin.setSingleStep(5.0)
        self.gpu_load_threshold_spin.setDecimals(0)
        self.sustained_seconds_spin = QDoubleSpinBox()
        self.sustained_seconds_spin.setRange(0.0, 600.0)
        self.sustained_seconds_spin.setSingleStep(5.0)
        self.sustained_seconds_spin.setDecimals(1)
        inhibition_form.addRow(
            _form_label("Battery Behavior", "What to do with videos while on battery."),
            self.battery_behavior_box,
        )
        inhibition_form.addRow(
            _form_label("High Load Behavior", "What to do after sustained CPU/GPU load."),
            self.high_load_behavior_box,
        )
        inhibition_form.addRow(
            _form_label("CPU Threshold", "Load ratio per CPU core that counts as high load."),
            self.cpu_load_threshold_spin,
        )
        inhibition_form.addRow(
            _form_label("GPU Threshold", "NVIDIA GPU utilization percent for high-load mode."),
            self.gpu_load_threshold_spin,
        )
        inhibition_form.addRow(
            _form_label("Sustained Seconds", "How long high load must persist before inhibiting."),
            self.sustained_seconds_spin,
        )
        save_inhibition_button = QPushButton("Save Inhibition")
        save_inhibition_button.clicked.connect(self.save_inhibition_settings)
        inhibition_form.addRow("", save_inhibition_button)
        inhibition_layout.addWidget(inhibition_group)
        inhibition_layout.addStretch(1)

        notifications_group = QGroupBox("Notifications")
        notifications_form = QFormLayout(notifications_group)
        self.notifications_enabled_check = QCheckBox("Enabled")
        self.notify_switched_check = QCheckBox("Switched wallpaper")
        self.notify_failed_check = QCheckBox("Switching failed")
        self.notify_video_optimization_check = QCheckBox("Video optimization progress")
        self.notification_command_edit = QLineEdit()
        self.notification_app_name_edit = QLineEdit()
        self.notification_icon_edit = QLineEdit()
        self.notification_desktop_entry_edit = QLineEdit()
        notifications_form.addRow("", self.notifications_enabled_check)
        notifications_form.addRow("", self.notify_switched_check)
        notifications_form.addRow("", self.notify_failed_check)
        notifications_form.addRow("", self.notify_video_optimization_check)
        notifications_form.addRow(
            _form_label(
                "Command",
                "Notification command to run. notify-send compatible commands work best.",
            ),
            self.notification_command_edit,
        )
        notifications_form.addRow(
            _form_label(
                "App Name",
                "Application name shown by the notification daemon.",
            ),
            self.notification_app_name_edit,
        )
        notifications_form.addRow(
            _form_label(
                "Icon",
                "Icon name or icon path passed to the notification daemon.",
            ),
            self.notification_icon_edit,
        )
        notifications_form.addRow(
            _form_label(
                "Desktop Entry",
                "Desktop entry identity used by portals and some notification daemons.",
            ),
            self.notification_desktop_entry_edit,
        )
        save_notifications_button = QPushButton("Save Notifications")
        save_notifications_button.clicked.connect(self.save_notification_settings)
        notifications_form.addRow("", save_notifications_button)
        notifications_layout.addWidget(notifications_group)
        notifications_layout.addStretch(1)

        self.folder_list = QListWidget()
        folders_group = QGroupBox("Wallpaper Folders")
        folders_layout = QVBoxLayout(folders_group)
        folders_layout.addWidget(self.folder_list)

        buttons = QHBoxLayout()
        add_button = QPushButton("Add Folder")
        add_button.clicked.connect(self.add_config_folder)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_config_folder)
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        folders_layout.addLayout(buttons)
        library_layout.addWidget(folders_group)
        library_layout.addStretch(1)

        profiles_group = QGroupBox("Profiles")
        profiles_outer = QHBoxLayout(profiles_group)
        self.profile_tree = QTreeWidget()
        self.profile_tree.setMinimumWidth(240)
        self.profile_tree.setHeaderHidden(True)
        self.profile_tree.currentItemChanged.connect(self.select_profile_tree_item)
        profiles_outer.addWidget(self.profile_tree)

        profile_editor = QVBoxLayout()
        profile_buttons = QHBoxLayout()
        add_profile_button = QPushButton("Add")
        add_profile_button.clicked.connect(self.add_profile_settings)
        import_profile_button = QPushButton("Import Folder Tree")
        import_profile_button.clicked.connect(self.import_profile_category_settings)
        remove_profile_button = QPushButton("Remove")
        remove_profile_button.clicked.connect(self.remove_profile_settings)
        save_profile_button = QPushButton("Save")
        save_profile_button.clicked.connect(self.save_profile_settings)
        active_profile_button = QPushButton("Set Active")
        active_profile_button.clicked.connect(self.set_active_profile_settings)
        profile_help = _help_marker(
            "A parent profile is the broad set, for example green. It can point at the "
            "green folder and show all wallpapers below it. Subprofiles are separate "
            "selectable profiles inside that parent, for example green / Anime. "
            "Import Folder Tree creates both from an existing folder structure."
        )
        profile_buttons.addWidget(add_profile_button)
        profile_buttons.addWidget(import_profile_button)
        profile_buttons.addWidget(remove_profile_button)
        profile_buttons.addWidget(save_profile_button)
        profile_buttons.addWidget(active_profile_button)
        profile_buttons.addWidget(profile_help)
        profile_buttons.addStretch(1)
        profile_editor.addLayout(profile_buttons)

        profile_tabs = QTabWidget()
        identity_profile_page = QWidget()
        folders_profile_page = QWidget()
        backends_profile_page = QWidget()
        filters_profile_page = QWidget()
        hooks_profile_page = QWidget()
        identity_profile_layout = QVBoxLayout(identity_profile_page)
        folders_profile_layout = QVBoxLayout(folders_profile_page)
        backends_profile_layout = QVBoxLayout(backends_profile_page)
        filters_profile_layout = QVBoxLayout(filters_profile_page)
        hooks_profile_layout = QVBoxLayout(hooks_profile_page)
        identity_profile_form = QFormLayout()
        self.profile_name_edit = QLineEdit()
        self.profile_category_edit = QLineEdit()
        self.profile_category_edit.setPlaceholderText("leave empty for a parent profile")
        self.profile_category_edit.setToolTip(
            "Parent profile name for subprofiles. Example: green for green / Anime."
        )
        self.profile_subcategory_edit = QLineEdit()
        self.profile_subcategory_edit.setPlaceholderText("optional display grouping")
        self.profile_subcategory_edit.setToolTip(
            "Optional subprofile label. Imported child profiles use their folder name."
        )
        self.profile_color_edit = QLineEdit()
        self.profile_color_edit.setPlaceholderText("#7ab574")
        self.profile_color_edit.setToolTip("Optional hex color used as a profile swatch.")
        profile_color_button = QPushButton("Choose")
        profile_color_button.clicked.connect(self.choose_profile_color)
        profile_color_layout = QHBoxLayout()
        profile_color_layout.addWidget(self.profile_color_edit)
        profile_color_layout.addWidget(profile_color_button)
        self.profile_dirs_list = QListWidget()
        self.profile_dirs_list.setMinimumHeight(75)
        self.profile_image_backend_box = QComboBox()
        self.profile_image_backend_box.addItem("Global default", "")
        self.profile_image_backend_box.addItems(["awww", "swww", "hyprpaper"])
        self.profile_gif_backend_box = QComboBox()
        self.profile_gif_backend_box.addItem("Global default", "")
        self.profile_gif_backend_box.addItems(["awww", "swww", "mpvpaper", "gslapper"])
        self.profile_video_backend_box = QComboBox()
        self.profile_video_backend_box.addItem("Global default", "")
        self.profile_video_backend_box.addItems(["mpvpaper", "gslapper"])
        self.profile_autoswitch_mode_box = QComboBox()
        self.profile_autoswitch_mode_box.addItem("Global default", "")
        self.profile_autoswitch_mode_box.addItem("Random", "random")
        self.profile_autoswitch_mode_box.addItem("Name up", "name-up")
        self.profile_autoswitch_mode_box.addItem("Name down", "name-down")
        self.profile_filter_query_edit = QLineEdit()
        self.profile_filter_types_edit = QLineEdit()
        self.profile_filter_types_edit.setPlaceholderText("image, gif, video")
        self.profile_before_switch_edit = QTextEdit()
        self.profile_before_switch_edit.setMinimumHeight(65)
        self.profile_after_switch_edit = QTextEdit()
        self.profile_after_switch_edit.setMinimumHeight(65)
        self.global_profile_before_switch_edit = QTextEdit()
        self.global_profile_before_switch_edit.setMinimumHeight(65)
        self.global_profile_after_switch_edit = QTextEdit()
        self.global_profile_after_switch_edit.setMinimumHeight(65)
        self.profile_include_parent_hooks_check = QCheckBox("Include parent profile hooks")
        self.profile_include_parent_hooks_check.setToolTip(
            "When this is a subprofile, run the parent profile hooks first."
        )
        self._connect_profile_autosave()

        identity_profile_form.addRow(
            _form_label("Profile Name", "The selectable profile name shown in the picker."),
            self.profile_name_edit,
        )
        identity_profile_form.addRow(
            _form_label(
                "Parent Profile",
                "Leave empty for a parent/all profile. For child profiles, "
                "set this to the parent name.",
            ),
            self.profile_category_edit,
        )
        identity_profile_form.addRow(
            _form_label(
                "Subprofile Label",
                "Optional grouping label. Imported child profiles use their folder name.",
            ),
            self.profile_subcategory_edit,
        )
        identity_profile_form.addRow(
            _form_label("Color", "Optional swatch color for profile identification."),
            profile_color_layout,
        )
        identity_profile_layout.addLayout(identity_profile_form)
        identity_profile_layout.addStretch(1)

        profile_dirs_layout = QVBoxLayout()
        profile_dirs_layout.addWidget(self.profile_dirs_list)
        profile_dirs_buttons = QHBoxLayout()
        add_profile_dir_button = QPushButton("Add Folder")
        add_profile_dir_button.clicked.connect(self.add_profile_dir_settings)
        remove_profile_dir_button = QPushButton("Remove Selected")
        remove_profile_dir_button.clicked.connect(self.remove_profile_dir_settings)
        profile_dirs_buttons.addWidget(add_profile_dir_button)
        profile_dirs_buttons.addWidget(remove_profile_dir_button)
        profile_dirs_buttons.addStretch(1)
        profile_dirs_layout.addLayout(profile_dirs_buttons)
        folders_profile_layout.addWidget(
            _help_marker(
                "Wallpapers belong to a profile through these folders. Parent profiles can point "
                "at a root folder; child profiles usually point at one child folder."
            )
        )
        folders_profile_layout.addLayout(profile_dirs_layout)
        folders_profile_layout.addStretch(1)

        backends_profile_form = QFormLayout()
        backends_profile_form.addRow(
            _form_label("Images", "Optional image backend override for this profile."),
            self.profile_image_backend_box,
        )
        backends_profile_form.addRow(
            _form_label("GIFs", "Optional GIF backend override for this profile."),
            self.profile_gif_backend_box,
        )
        backends_profile_form.addRow(
            _form_label("Videos", "Optional video backend override for this profile."),
            self.profile_video_backend_box,
        )
        backends_profile_form.addRow(
            _form_label("Autoswitch", "Optional next-wallpaper mode override for this profile."),
            self.profile_autoswitch_mode_box,
        )
        backends_profile_layout.addLayout(backends_profile_form)
        backends_profile_layout.addStretch(1)

        filters_profile_form = QFormLayout()
        filters_profile_form.addRow(
            _form_label(
                "Name Filter",
                "Optional text filter matched against wallpaper filenames in this profile.",
            ),
            self.profile_filter_query_edit,
        )
        filters_profile_form.addRow(
            _form_label(
                "Media Types",
                "Optional comma-separated type filter: image, gif, video.",
            ),
            self.profile_filter_types_edit,
        )
        filters_profile_layout.addLayout(filters_profile_form)
        filters_profile_layout.addStretch(1)

        global_hooks_group = QGroupBox("Global Profile Hooks")
        global_hooks_form = QFormLayout(global_hooks_group)
        global_hooks_form.addRow(
            _form_label(
                "Before Switch",
                "Commands run before every profile switch.",
            ),
            self.global_profile_before_switch_edit,
        )
        global_hooks_form.addRow(
            _form_label(
                "After Switch",
                "Commands run after every profile switch.",
            ),
            self.global_profile_after_switch_edit,
        )
        profile_hooks_group = QGroupBox("Selected Profile Hooks")
        hooks_profile_form = QFormLayout(profile_hooks_group)
        hooks_profile_form.addRow("", self.profile_include_parent_hooks_check)
        hooks_profile_form.addRow(
            _form_label("Before Switch", "Commands run before this profile becomes active."),
            self.profile_before_switch_edit,
        )
        hooks_profile_form.addRow(
            _form_label("After Switch", "Commands run after this profile becomes active."),
            self.profile_after_switch_edit,
        )
        hooks_profile_layout.addWidget(global_hooks_group)
        hooks_profile_layout.addWidget(profile_hooks_group)
        hooks_profile_layout.addStretch(1)

        profile_tabs.addTab(identity_profile_page, "Identity")
        profile_tabs.addTab(folders_profile_page, "Folders")
        profile_tabs.addTab(backends_profile_page, "Backends")
        profile_tabs.addTab(filters_profile_page, "Filters")
        profile_tabs.addTab(hooks_profile_page, "Hooks")
        profile_editor.addWidget(profile_tabs)
        profiles_outer.addLayout(profile_editor, 1)
        profiles_layout.addWidget(profiles_group)
        profiles_layout.addStretch(1)

        backend_group = QGroupBox("Backend Defaults")
        backend_layout = QVBoxLayout(backend_group)

        routing_form = QFormLayout()
        self.image_backend_default_box = QComboBox()
        self.image_backend_default_box.addItems(["awww", "swww", "hyprpaper"])
        self.gif_backend_default_box = QComboBox()
        self.gif_backend_default_box.addItems(["awww", "swww", "mpvpaper", "gslapper"])
        self.video_backend_default_box = QComboBox()
        self.video_backend_default_box.addItems(["mpvpaper", "gslapper"])
        routing_form.addRow(
            _form_label("Images", "Default backend used for static image wallpapers."),
            self.image_backend_default_box,
        )
        routing_form.addRow(
            _form_label("GIFs", "Default backend used for animated GIF wallpapers."),
            self.gif_backend_default_box,
        )
        routing_form.addRow(
            _form_label("Videos", "Default backend used for video wallpapers."),
            self.video_backend_default_box,
        )
        backend_layout.addLayout(routing_form)

        fallback_form = QFormLayout()
        self.awww_fallbacks_edit = QLineEdit()
        self.swww_fallbacks_edit = QLineEdit()
        self.hyprpaper_fallbacks_edit = QLineEdit()
        self.mpvpaper_fallbacks_edit = QLineEdit()
        self.gslapper_fallbacks_edit = QLineEdit()
        self.awww_fallbacks_edit.setPlaceholderText("swww")
        self.swww_fallbacks_edit.setPlaceholderText("comma-separated backend names")
        self.hyprpaper_fallbacks_edit.setPlaceholderText("opt-in only")
        self.mpvpaper_fallbacks_edit.setPlaceholderText("gslapper")
        self.gslapper_fallbacks_edit.setPlaceholderText("mpvpaper")
        fallback_form.addRow(
            _form_label(
                "awww",
                "Comma-separated fallback chain tried when awww fails. "
                "Incompatible backends are ignored.",
            ),
            self.awww_fallbacks_edit,
        )
        fallback_form.addRow(
            _form_label(
                "swww",
                "Comma-separated fallback chain tried when swww fails.",
            ),
            self.swww_fallbacks_edit,
        )
        fallback_form.addRow(
            _form_label(
                "hyprpaper",
                "Comma-separated fallback chain tried when hyprpaper fails. "
                "This is opt-in because hyprpaper behaves differently from awww/swww.",
            ),
            self.hyprpaper_fallbacks_edit,
        )
        fallback_form.addRow(
            _form_label(
                "mpvpaper",
                "Comma-separated fallback chain tried when mpvpaper fails.",
            ),
            self.mpvpaper_fallbacks_edit,
        )
        fallback_form.addRow(
            _form_label(
                "gSlapper",
                "Comma-separated fallback chain tried when gSlapper fails.",
            ),
            self.gslapper_fallbacks_edit,
        )
        fallback_box = QGroupBox("Fallback Chains")
        fallback_box.setLayout(fallback_form)
        backend_layout.addWidget(fallback_box)

        self.awww_command_edit = QLineEdit()
        self.awww_transition_type_box = self._transition_type_combo()
        self.awww_transition_step_spin = self._step_spin()
        self.awww_transition_duration_spin = self._duration_spin()
        self.awww_transition_fps_spin = self._fps_spin()
        self.awww_transition_angle_spin = self._angle_spin()
        self.awww_transition_pos_edit = QLineEdit()
        self.awww_invert_y_check = QCheckBox("Invert Y")
        self.awww_transition_bezier_edit = QLineEdit()
        self.awww_transition_wave_edit = QLineEdit()
        awww_form = QFormLayout()
        awww_form.addRow(
            _form_label("Command", "Executable name or path used for the awww backend."),
            self.awww_command_edit,
        )
        awww_form.addRow(
            _form_label("Transition", "awww transition type used for image changes."),
            self.awww_transition_type_box,
        )
        awww_form.addRow(
            _form_label("Step", "Transition step value passed through to awww."),
            self.awww_transition_step_spin,
        )
        awww_form.addRow(
            _form_label("Duration", "Transition duration in seconds."),
            self.awww_transition_duration_spin,
        )
        awww_form.addRow(
            _form_label("FPS", "Transition frame rate passed through to awww."),
            self.awww_transition_fps_spin,
        )
        awww_form.addRow(
            _form_label("Angle", "Transition angle used by angle-aware effects."),
            self.awww_transition_angle_spin,
        )
        awww_form.addRow(
            _form_label("Position", "Transition origin, for example center or cursor."),
            self.awww_transition_pos_edit,
        )
        awww_form.addRow("", self.awww_invert_y_check)
        awww_form.addRow(
            _form_label("Bezier", "Optional custom bezier curve for supported effects."),
            self.awww_transition_bezier_edit,
        )
        awww_form.addRow(
            _form_label("Wave", "Optional wave parameters for supported effects."),
            self.awww_transition_wave_edit,
        )
        awww_box = QGroupBox("awww")
        awww_box.setLayout(awww_form)
        backend_layout.addWidget(awww_box)

        self.swww_command_edit = QLineEdit()
        self.swww_transition_type_box = self._transition_type_combo()
        self.swww_transition_step_spin = self._step_spin()
        self.swww_transition_duration_spin = self._duration_spin()
        self.swww_transition_fps_spin = self._fps_spin()
        self.swww_transition_angle_spin = self._angle_spin()
        self.swww_transition_pos_edit = QLineEdit()
        self.swww_invert_y_check = QCheckBox("Invert Y")
        self.swww_transition_bezier_edit = QLineEdit()
        self.swww_transition_wave_edit = QLineEdit()
        swww_form = QFormLayout()
        swww_form.addRow(
            _form_label("Command", "Executable name or path used for the swww backend."),
            self.swww_command_edit,
        )
        swww_form.addRow(
            _form_label("Transition", "swww transition type used for image changes."),
            self.swww_transition_type_box,
        )
        swww_form.addRow(
            _form_label("Step", "Transition step value passed through to swww."),
            self.swww_transition_step_spin,
        )
        swww_form.addRow(
            _form_label("Duration", "Transition duration in seconds."),
            self.swww_transition_duration_spin,
        )
        swww_form.addRow(
            _form_label("FPS", "Transition frame rate passed through to swww."),
            self.swww_transition_fps_spin,
        )
        swww_form.addRow(
            _form_label("Angle", "Transition angle used by angle-aware effects."),
            self.swww_transition_angle_spin,
        )
        swww_form.addRow(
            _form_label("Position", "Transition origin, for example center or cursor."),
            self.swww_transition_pos_edit,
        )
        swww_form.addRow("", self.swww_invert_y_check)
        swww_form.addRow(
            _form_label("Bezier", "Optional custom bezier curve for supported effects."),
            self.swww_transition_bezier_edit,
        )
        swww_form.addRow(
            _form_label("Wave", "Optional wave parameters for supported effects."),
            self.swww_transition_wave_edit,
        )
        swww_box = QGroupBox("swww")
        swww_box.setLayout(swww_form)
        backend_layout.addWidget(swww_box)

        self.hyprpaper_command_edit = QLineEdit()
        self.hyprpaper_fit_mode_box = QComboBox()
        self.hyprpaper_fit_mode_box.setEditable(True)
        self.hyprpaper_fit_mode_box.addItems(["cover", "contain", "tile"])
        hyprpaper_form = QFormLayout()
        hyprpaper_form.addRow(
            _form_label("Command", "Executable name or path used for hyprpaperctl."),
            self.hyprpaper_command_edit,
        )
        hyprpaper_form.addRow(
            _form_label("Fit mode", "hyprpaper display mode for new wallpapers."),
            self.hyprpaper_fit_mode_box,
        )
        hyprpaper_box = QGroupBox("hyprpaper")
        hyprpaper_box.setLayout(hyprpaper_form)
        backend_layout.addWidget(hyprpaper_box)

        self.mpvpaper_command_edit = QLineEdit()
        self.mpvpaper_options_edit = QLineEdit()
        self.mpvpaper_hwdec_box = QComboBox()
        self.mpvpaper_hwdec_box.addItem("Automatic (safe)", "automatic")
        self.mpvpaper_hwdec_box.addItem("Software (flicker-safe)", "software")
        self.mpvpaper_hwdec_box.addItem("Hardware", "hardware")
        mpvpaper_form = QFormLayout()
        mpvpaper_form.addRow(
            _form_label("Command", "Executable name or path used for mpvpaper."),
            self.mpvpaper_command_edit,
        )
        mpvpaper_form.addRow(
            _form_label(
                "Hardware decoding",
                "Automatic uses mpv's safe hardware decoding. Software is slower but can "
                "avoid driver-related black frames. Hardware prefers GPU decoding.",
            ),
            self.mpvpaper_hwdec_box,
        )
        mpvpaper_form.addRow(
            _form_label(
                "Options",
                "Advanced mpv options. Hardware decoding is controlled separately.",
            ),
            self.mpvpaper_options_edit,
        )
        mpvpaper_box = QGroupBox("mpvpaper")
        mpvpaper_box.setLayout(mpvpaper_form)
        backend_layout.addWidget(mpvpaper_box)

        self.gslapper_command_edit = QLineEdit()
        gslapper_form = QFormLayout()
        gslapper_form.addRow(
            _form_label("Command", "Executable name or path used for gSlapper."),
            self.gslapper_command_edit,
        )
        gslapper_box = QGroupBox("gSlapper")
        gslapper_box.setLayout(gslapper_form)
        backend_layout.addWidget(gslapper_box)

        save_backend_button = QPushButton("Save Backend Defaults")
        save_backend_button.clicked.connect(self.save_backend_settings)
        backend_layout.addWidget(save_backend_button)
        backend_page_layout.addWidget(backend_group)
        backend_page_layout.addStretch(1)

        video_group = QGroupBox("Video Optimization")
        video_form = QFormLayout(video_group)
        self.video_opt_enabled_check = QCheckBox("Auto cache videos")
        self.video_prefer_optimized_check = QCheckBox("Prefer optimized videos when available")
        self.video_opt_profile_box = QComboBox()
        self.video_opt_profile_box.addItems(["compatibility", "balanced", "quality"])
        self.video_cache_dir_edit = QLineEdit()
        self.video_cache_dir_edit.setReadOnly(True)
        self.video_cache_dir_edit.setToolTip(
            "Wallmux uses its default optimized-video cache. "
            "This path is informational and is not written as a config override."
        )
        self.video_codec_edit = QLineEdit()
        self.video_codec_names_edit = QLineEdit()
        self.video_container_edit = QLineEdit()
        self.video_extension_edit = QLineEdit()
        self.video_max_width_spin = QSpinBox()
        self.video_max_width_spin.setRange(1, 16384)
        self.video_max_height_spin = QSpinBox()
        self.video_max_height_spin.setRange(1, 16384)
        self.video_max_bitrate_spin = QSpinBox()
        self.video_max_bitrate_spin.setRange(1, 1000)
        self.video_crf_spin = QSpinBox()
        self.video_crf_spin.setRange(0, 51)
        self.video_preset_edit = QLineEdit()
        self.video_loop_friendly_check = QCheckBox("Loop-friendly encoding")
        self.video_loop_friendly_check.setToolTip(
            "Encode closed GOPs without B-frames to reduce decoder flicker at loop boundaries."
        )
        self.video_loop_gop_spin = QSpinBox()
        self.video_loop_gop_spin.setRange(1, 1000)
        self.video_extra_args_edit = QLineEdit()
        video_form.addRow("", self.video_opt_enabled_check)
        video_form.addRow("", self.video_prefer_optimized_check)
        video_form.addRow(
            _form_label("Profile", "Optimization preset used for CLI and GUI jobs."),
            self.video_opt_profile_box,
        )
        video_form.addRow(
            _form_label("Cache Dir", "Optional optimized video cache directory."),
            self.video_cache_dir_edit,
        )
        video_form.addRow(_form_label("Codec", "ffmpeg video encoder."), self.video_codec_edit)
        video_form.addRow(
            _form_label("Codec Names", "Comma-separated codecs considered already suitable."),
            self.video_codec_names_edit,
        )
        video_form.addRow(
            _form_label("Container", "Target container name."),
            self.video_container_edit,
        )
        video_form.addRow(
            _form_label("Extension", "Output file extension."),
            self.video_extension_edit,
        )
        video_form.addRow(
            _form_label("Max Width", "Maximum optimized video width."),
            self.video_max_width_spin,
        )
        video_form.addRow(
            _form_label("Max Height", "Maximum optimized video height."),
            self.video_max_height_spin,
        )
        video_form.addRow(
            _form_label("Max Bitrate", "Maximum suitable bitrate in Mbps."),
            self.video_max_bitrate_spin,
        )
        video_form.addRow(_form_label("CRF", "ffmpeg CRF quality value."), self.video_crf_spin)
        video_form.addRow(_form_label("Preset", "ffmpeg encoder preset."), self.video_preset_edit)
        video_form.addRow("", self.video_loop_friendly_check)
        video_form.addRow(
            _form_label(
                "Loop GOP Size",
                "Frames between loop-friendly keyframes. 60 is suitable for most wallpapers.",
            ),
            self.video_loop_gop_spin,
        )
        video_form.addRow(
            _form_label("Extra Args", "Additional ffmpeg arguments, shell-style."),
            self.video_extra_args_edit,
        )
        video_buttons = QHBoxLayout()
        save_video_button = QPushButton("Save Video Settings")
        save_video_button.clicked.connect(self.save_video_settings)
        optimize_selected_button = QPushButton("Optimize Selected")
        optimize_selected_button.clicked.connect(self.optimize_selected_video)
        optimize_library_button = QPushButton("Optimize Library")
        optimize_library_button.clicked.connect(self.optimize_video_library_gui)
        self.video_force_optimize_check = QCheckBox("Force")
        video_buttons.addWidget(save_video_button)
        video_buttons.addWidget(optimize_selected_button)
        video_buttons.addWidget(optimize_library_button)
        video_buttons.addWidget(self.video_force_optimize_check)
        video_buttons.addStretch(1)
        video_layout.addWidget(video_group)
        video_layout.addLayout(video_buttons)
        self.video_opt_log = QTextEdit()
        self.video_opt_log.setReadOnly(True)
        self.video_opt_log.setMinimumHeight(110)
        video_layout.addWidget(self.video_opt_log)
        video_layout.addStretch(1)

        cache_group = QGroupBox("Cache Maintenance")
        cache_form = QFormLayout(cache_group)
        self.cache_maintenance_check = QCheckBox("Periodic daemon cleanup")
        self.cache_cleanup_policy_box = QComboBox()
        self.cache_cleanup_policy_box.addItem("Stale only", "stale-only")
        self.cache_cleanup_policy_box.addItem("Least recently used", "lru")
        self.cache_cleanup_policy_box.addItem("All cached files", "all")
        self.cache_cleanup_interval_spin = QSpinBox()
        self.cache_cleanup_interval_spin.setRange(60, 604800)
        self.cache_cleanup_interval_spin.setSingleStep(3600)
        self.cache_thumbnail_age_spin = QSpinBox()
        self.cache_thumbnail_age_spin.setRange(0, 3650)
        self.cache_video_limit_spin = QSpinBox()
        self.cache_video_limit_spin.setRange(0, 1_000_000)
        self.cache_video_limit_spin.setSingleStep(1024)
        cache_form.addRow("", self.cache_maintenance_check)
        cache_form.addRow(
            _form_label(
                "Policy",
                "Stale-only validates videos and age-cleans thumbnails. "
                "LRU also trims videos to the configured size limit.",
            ),
            self.cache_cleanup_policy_box,
        )
        cache_form.addRow(
            _form_label("Interval", "Seconds between daemon cache maintenance runs."),
            self.cache_cleanup_interval_spin,
        )
        cache_form.addRow(
            _form_label(
                "Thumbnail Age",
                "Days before thumbnail files count as stale. Set 0 to disable age cleanup.",
            ),
            self.cache_thumbnail_age_spin,
        )
        cache_form.addRow(
            _form_label(
                "Video Limit",
                "Maximum optimized-video cache size in MiB. "
                "Set 0 to disable LRU size trimming.",
            ),
            self.cache_video_limit_spin,
        )
        cache_buttons = QHBoxLayout()
        save_cache_button = QPushButton("Save Cache Settings")
        save_cache_button.clicked.connect(self.save_cache_settings)
        refresh_cache_button = QPushButton("Refresh Stats")
        refresh_cache_button.clicked.connect(self.refresh_cache_stats)
        clean_stale_button = QPushButton("Clean Stale")
        clean_stale_button.clicked.connect(lambda: self.clean_cache_gui("stale-only"))
        clean_lru_button = QPushButton("Clean LRU")
        clean_lru_button.clicked.connect(lambda: self.clean_cache_gui("lru"))
        rebuild_thumbnails_button = QPushButton("Rebuild Thumbnails")
        rebuild_thumbnails_button.clicked.connect(self.rebuild_thumbnail_cache_gui)
        rebuild_videos_button = QPushButton("Rebuild Videos")
        rebuild_videos_button.clicked.connect(self.rebuild_video_cache_gui)
        cache_buttons.addWidget(save_cache_button)
        cache_buttons.addWidget(refresh_cache_button)
        cache_buttons.addWidget(clean_stale_button)
        cache_buttons.addWidget(clean_lru_button)
        cache_buttons.addWidget(rebuild_thumbnails_button)
        cache_buttons.addWidget(rebuild_videos_button)
        cache_buttons.addStretch(1)
        self.cache_stats_view = QTextEdit()
        self.cache_stats_view.setReadOnly(True)
        self.cache_stats_view.setMinimumHeight(170)
        cache_layout.addWidget(cache_group)
        cache_layout.addLayout(cache_buttons)
        cache_layout.addWidget(self.cache_stats_view)
        cache_layout.addStretch(1)

        self.hook_log_view = QTextEdit()
        self.hook_log_view.setReadOnly(True)
        self.hook_log_view.setMinimumHeight(140)
        hooks_group = QGroupBox("Hooks")
        hooks_layout = QVBoxLayout(hooks_group)
        hooks_layout.addWidget(self.hook_log_view)

        hook_buttons = QHBoxLayout()
        refresh_hooks_button = QPushButton("Refresh Hook Log")
        refresh_hooks_button.clicked.connect(self.refresh_hook_log)
        hook_buttons.addWidget(refresh_hooks_button)
        hook_buttons.addStretch(1)
        hooks_layout.addLayout(hook_buttons)
        hooks_page_layout.addWidget(hooks_group)
        hooks_page_layout.addStretch(1)

        transition_form = QFormLayout()
        self.basic_transitions_check = QCheckBox("Basic transitions")
        self.video_poster_bridge_check = QCheckBox("Keep video poster beneath playback")
        self.video_poster_timestamp_spin = QDoubleSpinBox()
        self.video_poster_timestamp_spin.setRange(0.0, 60.0)
        self.video_poster_timestamp_spin.setSingleStep(0.1)
        self.video_poster_timestamp_spin.setDecimals(1)
        self.video_poster_settle_spin = QDoubleSpinBox()
        self.video_poster_settle_spin.setRange(0.0, 10.0)
        self.video_poster_settle_spin.setSingleStep(0.1)
        self.video_poster_settle_spin.setDecimals(1)
        self.video_start_settle_spin = QDoubleSpinBox()
        self.video_start_settle_spin.setRange(0.0, 10.0)
        self.video_start_settle_spin.setSingleStep(0.1)
        self.video_start_settle_spin.setDecimals(1)
        self.fade_overlay_check = QCheckBox("Fade overlay")
        self.screenshot_bridge_check = QCheckBox("Screenshot bridge")
        self.quickshell_overlay_check = QCheckBox("QuickShell overlay")
        self.quickshell_image_to_image_check = QCheckBox("Image to image")
        self.quickshell_image_to_video_check = QCheckBox("Image to video")
        self.quickshell_video_to_image_check = QCheckBox("Video to image")
        self.quickshell_video_to_video_check = QCheckBox("Video to video")
        self.fade_command_edit = QLineEdit()
        self.screenshot_command_edit = QLineEdit()
        self.quickshell_command_edit = QLineEdit()
        self.transition_effect_timeout_spin = QDoubleSpinBox()
        self.transition_effect_timeout_spin.setRange(0.1, 30.0)
        self.transition_effect_timeout_spin.setSingleStep(0.5)
        self.transition_effect_timeout_spin.setDecimals(1)

        transition_form.addRow("", self.basic_transitions_check)
        transition_form.addRow("", self.video_poster_bridge_check)
        transition_form.addRow(
            _form_label(
                "Poster Timestamp",
                "Video timestamp used for the full-resolution image kept beneath playback.",
            ),
            self.video_poster_timestamp_spin,
        )
        transition_form.addRow(
            _form_label(
                "Poster Settle",
                "Seconds to let awww or swww finish switching to the poster before video starts.",
            ),
            self.video_poster_settle_spin,
        )
        transition_form.addRow(
            _form_label(
                "Video Start Settle",
                "Seconds to keep an overlay opaque while a new video renders its first frame.",
            ),
            self.video_start_settle_spin,
        )
        transition_form.addRow("", self.fade_overlay_check)
        transition_form.addRow(
            _form_label(
                "Fade Command",
                "Optional external command used for fade helper transitions.",
            ),
            self.fade_command_edit,
        )
        transition_form.addRow("", self.screenshot_bridge_check)
        transition_form.addRow(
            _form_label(
                "Screenshot Command",
                "Optional external command used for screenshot bridge transitions.",
            ),
            self.screenshot_command_edit,
        )
        transition_form.addRow("", self.quickshell_overlay_check)
        transition_form.addRow(
            _form_label(
                "QuickShell Command",
                "Optional external command used to trigger a QuickShell overlay/helper.",
            ),
            self.quickshell_command_edit,
        )
        quickshell_transition_checks = QHBoxLayout()
        quickshell_transition_checks.addWidget(self.quickshell_image_to_image_check)
        quickshell_transition_checks.addWidget(self.quickshell_image_to_video_check)
        quickshell_transition_checks.addWidget(self.quickshell_video_to_image_check)
        quickshell_transition_checks.addWidget(self.quickshell_video_to_video_check)
        quickshell_transition_checks.addStretch(1)
        transition_form.addRow(
            _form_label(
                "QuickShell transitions",
                "Choose which wallpaper transition kinds use the QuickShell overlay.",
            ),
            quickshell_transition_checks,
        )
        transition_form.addRow(
            _form_label(
                "Effect Timeout",
                "Maximum time Wallmux waits for external transition helpers.",
            ),
            self.transition_effect_timeout_spin,
        )
        transition_group = QGroupBox("Transition Effects")
        transition_group.setLayout(transition_form)
        transitions_layout.addWidget(transition_group)

        save_transitions_button = QPushButton("Save Transition Effects")
        save_transitions_button.clicked.connect(self.save_transition_settings)
        transitions_layout.addWidget(save_transitions_button)
        transitions_layout.addStretch(1)

        self.settings_tabs.addTab(general_page, "General")
        self.settings_tabs.addTab(library_page, "Library")
        self.settings_tabs.addTab(profiles_page, "Profiles")
        self.settings_tabs.addTab(backend_page, "Backends")
        self.settings_tabs.addTab(video_page, "Video")
        self.settings_tabs.addTab(cache_page, "Cache")
        self.settings_tabs.addTab(autoswitch_page, "Auto")
        self.settings_tabs.addTab(inhibition_page, "Inhibition")
        self.settings_tabs.addTab(notifications_page, "Notifications")
        self.settings_tabs.addTab(hooks_page, "Hooks")
        self.settings_tabs.addTab(transitions_page, "Transitions")

        self.tabs.addTab(tab, "Settings")
        self.refresh_settings()
        self.refresh_hook_log()

    def _settings_page(self) -> tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        return scroll, layout

    def _load_initial_folder(self) -> None:
        dirs = self._configured_wallpaper_dirs()
        for raw_dir in dirs:
            path = Path(raw_dir).expanduser()
            if path.exists() and path.is_dir():
                self.load_configured_library()
                return
        self.populate_grid()

    def _configured_wallpaper_dirs(self) -> list[str]:
        config = effective_config_for_profile(self.config)
        return list(config.get("general", {}).get("wallpaper_dirs", []))

    def _load_monitors(self) -> None:
        self.monitor_box.clear()
        self.monitor_box.addItem("All monitors", ALL_MONITORS)
        monitors = list_monitors()
        for monitor in monitors:
            self.monitor_box.addItem(monitor.name, monitor.name)

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Open Wallpaper Folder")
        if selected:
            self.load_folder(Path(selected))

    def load_folder(self, folder: Path) -> None:
        self.current_folder = folder
        self.status.showMessage(f"Scanning {folder}")
        config = effective_config_for_profile(self.config)
        self.items = scan_wallpaper_dir(
            folder,
            backend_rules=config.get("backend_rules", {}),
        )
        active = get_active_profile(self.config)
        self.items = [item for item in self.items if profile_matches_filters(active, item)]
        self._request_immediate_video_scan([folder])
        self.populate_grid()
        self.status.showMessage(f"{len(self.items)} wallpapers in {folder}", 5000)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def load_configured_library(self) -> None:
        self.current_folder = None
        config = effective_config_for_profile(self.config)
        dirs = config.get("general", {}).get("wallpaper_dirs", [])
        active = get_active_profile(self.config)
        self.status.showMessage("Scanning configured wallpaper folders")
        items: list[WallpaperItem] = []
        for raw_dir in dirs:
            items.extend(
                scan_wallpaper_dir(
                    Path(raw_dir),
                    backend_rules=config.get("backend_rules", {}),
                )
            )
        self.items = sorted(
            {
                str(item.path.expanduser().resolve()): item
                for item in items
                if profile_matches_filters(active, item)
            }.values(),
            key=lambda item: item.path.name.casefold(),
        )
        self._request_immediate_video_scan([Path(raw_dir) for raw_dir in dirs])
        self.populate_grid()
        label = f" for {active.label}" if active else ""
        self.status.showMessage(f"{len(self.items)} wallpapers{label}", 5000)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _request_immediate_video_scan(self, directories: list[Path]) -> None:
        try:
            send_request(
                {
                    "command": "scan-video-library",
                    "directories": [str(path.expanduser()) for path in directories],
                }
            )
        except DaemonUnavailable:
            pass

    def closeEvent(self, event) -> None:
        self.thread_pool.waitForDone(1000)
        super().closeEvent(event)

    def refresh_library(self) -> None:
        if self.current_folder is not None:
            self.load_folder(self.current_folder)
        else:
            self.load_configured_library()
        self._load_monitors()

    def show_profile_picker(self) -> None:
        switched, label = run_profile_picker_dialog(self, self.config)
        if not switched:
            return
        self.config = load_config()
        self.refresh_settings()
        self.load_configured_library()
        self.status.showMessage(f"Profile active: {label}", 5000)

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
            self.refresh_video_cache_marker(item)

        if self.grid.count() == 0:
            self.preview.setText("No wallpapers")
            self.set_button.setEnabled(False)
        elif self.grid.currentRow() < 0:
            self.grid.setCurrentRow(0)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def select_current_item(self) -> None:
        selected = self.grid.selectedItems()
        if not selected:
            self.selected_item = None
            self.set_button.setEnabled(False)
            return

        self.selected_item = selected[0].data(Qt.ItemDataRole.UserRole)
        self._populate_backend_box(self.selected_item)
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

        monitor = self.monitor_box.currentData()
        backend = self.backend_box.currentText()
        all_monitor_mode = self.all_monitor_mode_box.currentData()
        request = {
            "command": "set",
            "file": str(self.selected_item.path),
            "backend": backend,
        }
        if monitor == ALL_MONITORS:
            request["all"] = True
            request["all_monitor_mode"] = all_monitor_mode
        else:
            request["monitor"] = monitor or self.monitor_box.currentText()

        if self.close_after_set_check.isChecked():
            thread = threading.Thread(
                target=_set_wallpaper_detached,
                args=(
                    request,
                    self.selected_item.path,
                    ALL_MONITORS if request.get("all") else str(request["monitor"]),
                    backend,
                    all_monitor_mode,
                ),
                daemon=False,
                name="wallmux-gui-set",
            )
            thread.start()
            self.close()
            return

        try:
            response = send_request(request)
            if not response.get("ok"):
                raise WallmuxError(response.get("error", "unknown daemon error"))
            self._show_set_results(response["results"])
        except DaemonUnavailable:
            config = effective_config_for_profile(self.config)
            try:
                if monitor == ALL_MONITORS:
                    results = set_wallpaper_for_all(
                        self.selected_item.path,
                        config=config,
                        backend_override=backend,
                        mode=all_monitor_mode,
                    )
                else:
                    result = set_wallpaper(
                        self.selected_item.path,
                        monitor or self.monitor_box.currentText(),
                        config=config,
                        backend_override=backend,
                    )
                    results = [result]
            except (ValueError, WallmuxError) as error:
                QMessageBox.critical(self, "Wallmux", str(error))
                return
            self._show_set_results(
                [
                    {
                        "file": str(result.file),
                        "monitor": result.monitor,
                        "backend": result.backend,
                    }
                    for result in results
                ]
            )
        except WallmuxError as error:
            QMessageBox.critical(self, "Wallmux", str(error))

    def _populate_backend_box(self, item: WallpaperItem) -> None:
        current = item.backend
        options = compatible_backends(item.wallpaper_type)
        self.backend_box.blockSignals(True)
        self.backend_box.clear()
        self.backend_box.addItems(options)
        if current in options:
            self.backend_box.setCurrentText(current)
        self.backend_box.blockSignals(False)

    def _backend_changed(self, backend: str) -> None:
        self.status.showMessage(f"{backend} will use the saved backend defaults", 3000)

    def _show_set_results(self, results: list[dict]) -> None:
        if not results:
            return
        first = results[0]
        if len(results) == 1:
            message = (
                f"Set {Path(first['file']).name} on {first['monitor']} "
                f"via {first['backend']}"
            )
        else:
            message = f"Set {Path(first['file']).name} on {len(results)} monitors"
        self.status.showMessage(message, 6000)

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

    def add_profile_settings(self) -> None:
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        entries.append(
            {
                "name": "new-profile",
                "category": "",
                "subcategory": "",
                "color": "",
                "wallpaper_dirs": [],
                "backend_rules": {},
                "autoswitch_mode": "",
                "filter_query": "",
                "filter_types": [],
                "before_switch": [],
                "after_switch": [],
                "include_parent_hooks": False,
            }
        )
        write_config(self.config, user_config_file())
        self.refresh_profile_settings(select_index=len(entries) - 1)

    def import_profile_category_settings(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Import Profile Category Folder",
        )
        if not selected:
            return

        try:
            new_entries = profile_entries_from_category_root(Path(selected))
        except ValueError as error:
            QMessageBox.warning(self, "Wallmux", str(error))
            return
        if not new_entries:
            QMessageBox.information(
                self,
                "Wallmux",
                "No child folders found. Add subfolders such as Anime or Landscape first.",
            )
            return

        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        existing_keys = {
            (
                str(entry.get("category", "")),
                str(entry.get("subcategory", "")),
                str(entry.get("name", "")),
            )
            for entry in entries
        }
        added = 0
        for entry in new_entries:
            key = (
                str(entry.get("category", "")),
                str(entry.get("subcategory", "")),
                str(entry.get("name", "")),
            )
            if key in existing_keys:
                continue
            entries.append(entry)
            existing_keys.add(key)
            added += 1

        write_config(self.config, user_config_file())
        self.refresh_profile_settings(select_index=max(0, len(entries) - added))
        self.status.showMessage(f"Imported {added} profile(s)", 5000)

    def _connect_profile_autosave(self) -> None:
        for line_edit in (
            self.profile_name_edit,
            self.profile_category_edit,
            self.profile_subcategory_edit,
            self.profile_color_edit,
            self.profile_filter_query_edit,
            self.profile_filter_types_edit,
        ):
            line_edit.textEdited.connect(self.schedule_profile_autosave)
        for combo in (
            self.profile_image_backend_box,
            self.profile_gif_backend_box,
            self.profile_video_backend_box,
            self.profile_autoswitch_mode_box,
        ):
            combo.currentIndexChanged.connect(self.schedule_profile_autosave)
        self.profile_before_switch_edit.textChanged.connect(self.schedule_profile_autosave)
        self.profile_after_switch_edit.textChanged.connect(self.schedule_profile_autosave)
        self.profile_include_parent_hooks_check.toggled.connect(self.schedule_profile_autosave)
        self.global_profile_before_switch_edit.textChanged.connect(
            self.schedule_global_profile_hooks_autosave
        )
        self.global_profile_after_switch_edit.textChanged.connect(
            self.schedule_global_profile_hooks_autosave
        )

    def choose_profile_color(self) -> None:
        current = QColor(self.profile_color_edit.text().strip())
        if not current.isValid():
            current = QColor("#7ab574")
        color = QColorDialog.getColor(current, self, "Choose Profile Color")
        if not color.isValid():
            return
        self.profile_color_edit.setText(color.name())
        self.profile_autosave_timer.stop()
        self.autosave_profile_settings()

    def remove_profile_settings(self) -> None:
        row = self._current_profile_row()
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        if row < 0 or row >= len(entries):
            return

        removed = entries.pop(row)
        profiles = self.config.setdefault("profiles", {})
        if profiles.get("active") == removed.get("name"):
            profiles["active"] = ""
            profiles["active_category"] = ""
            profiles["active_subcategory"] = ""
        write_config(self.config, user_config_file())
        self.refresh_profile_settings(select_index=min(row, len(entries) - 1))
        self.status.showMessage("Profile removed", 5000)

    def add_profile_dir_settings(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Add Profile Wallpaper Folder")
        if not selected:
            return
        existing = {
            self.profile_dirs_list.item(index).text()
            for index in range(self.profile_dirs_list.count())
        }
        if selected not in existing:
            self.profile_dirs_list.addItem(selected)
            self.schedule_profile_autosave()

    def remove_profile_dir_settings(self) -> None:
        for item in self.profile_dirs_list.selectedItems():
            row = self.profile_dirs_list.row(item)
            self.profile_dirs_list.takeItem(row)
        self.schedule_profile_autosave()

    def save_profile_settings(self) -> None:
        self.profile_autosave_timer.stop()
        row = self._current_profile_row()
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        if row < 0 or row >= len(entries):
            return

        name = self.profile_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Wallmux", "Profile name is required.")
            return

        entries[row] = self._profile_editor_entry()
        profiles = self.config.setdefault("profiles", {})
        if profiles.get("active") == entries[row]["name"]:
            profiles["active_category"] = entries[row]["category"]
            profiles["active_subcategory"] = entries[row]["subcategory"]
        write_config(self.config, user_config_file())
        self.config = load_config()
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        self.refresh_profile_settings(select_index=row)
        self.refresh_library()
        self.status.showMessage("Profile saved", 5000)

    def schedule_profile_autosave(self, *_args) -> None:
        if self.profile_settings_loading:
            return
        if self._current_profile_row() < 0:
            return
        self.profile_autosave_timer.start()

    def autosave_profile_settings(self) -> None:
        row = self._current_profile_row()
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        if row < 0 or row >= len(entries):
            return
        if not self.profile_name_edit.text().strip():
            self.status.showMessage("Profile name is required before autosave", 5000)
            return

        previous_entry = dict(entries[row])
        entries[row] = self._profile_editor_entry()
        profiles = self.config.setdefault("profiles", {})
        if _profile_entry_is_active(previous_entry, profiles):
            profiles["active"] = entries[row]["name"]
            profiles["active_category"] = entries[row]["category"]
            profiles["active_subcategory"] = entries[row]["subcategory"]
        write_config(self.config, user_config_file())
        self.config = load_config()
        profiles = self.config.setdefault("profiles", {})
        entries = profiles.setdefault("entries", [])
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        current_item = self.profile_tree.currentItem()
        if current_item is not None and _profile_tree_item_row(current_item) == row:
            current_item.setText(
                0,
                _profile_tree_label(
                    entries[row],
                    active=_profile_entry_is_active(entries[row], profiles),
                ),
            )
            _apply_profile_swatch(current_item, str(entries[row].get("color", "")))
        self.status.showMessage("Profile autosaved", 2500)

    def schedule_global_profile_hooks_autosave(self) -> None:
        if self.profile_settings_loading:
            return
        self.global_profile_hooks_autosave_timer.start()

    def autosave_global_profile_hooks(self) -> None:
        profiles = self.config.setdefault("profiles", {})
        profiles["before_switch"] = self._pattern_lines(
            self.global_profile_before_switch_edit
        )
        profiles["after_switch"] = self._pattern_lines(
            self.global_profile_after_switch_edit
        )
        write_config(self.config, user_config_file())
        self.config = load_config()
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        self.status.showMessage("Global profile hooks autosaved", 2500)

    def set_active_profile_settings(self) -> None:
        if self.profile_autosave_timer.isActive():
            self.profile_autosave_timer.stop()
            self.autosave_profile_settings()
        row = self._current_profile_row()
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        if row < 0 or row >= len(entries):
            return

        entry = entries[row]
        try:
            switch_profile(
                str(entry.get("name", "")),
                category=str(entry.get("category", "")),
                subcategory=str(entry.get("subcategory", "")),
                config=self.config,
                after_write=_reload_daemon_quietly,
            )
        except ValueError as error:
            QMessageBox.critical(self, "Wallmux", str(error))
            return
        self.config = load_config()
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        self.refresh_profile_settings(select_index=row)
        self.load_configured_library()
        self.status.showMessage(f"Profile active: {_profile_entry_label(entry)}", 5000)

    def _profile_editor_entry(self) -> dict:
        backend_rules = {}
        for key, combo in (
            ("image", self.profile_image_backend_box),
            ("gif", self.profile_gif_backend_box),
            ("video", self.profile_video_backend_box),
        ):
            value = combo.currentData()
            if value:
                backend_rules[key] = value

        return {
            "name": self.profile_name_edit.text().strip(),
            "category": self.profile_category_edit.text().strip(),
            "subcategory": self.profile_subcategory_edit.text().strip(),
            "color": _normalize_profile_color(self.profile_color_edit.text()),
            "wallpaper_dirs": [
                self.profile_dirs_list.item(index).text()
                for index in range(self.profile_dirs_list.count())
            ],
            "backend_rules": backend_rules,
            "autoswitch_mode": self.profile_autoswitch_mode_box.currentData() or "",
            "filter_query": self.profile_filter_query_edit.text().strip(),
            "filter_types": self._comma_values(self.profile_filter_types_edit.text()),
            "before_switch": self._pattern_lines(self.profile_before_switch_edit),
            "after_switch": self._pattern_lines(self.profile_after_switch_edit),
            "include_parent_hooks": self.profile_include_parent_hooks_check.isChecked(),
        }

    def save_backend_settings(self) -> None:
        self.config.setdefault("general", {})["all_monitor_mode"] = (
            self.all_monitor_mode_box.currentData()
        )
        self.config["backend_rules"] = {
            "image": self.image_backend_default_box.currentText(),
            "gif": self.gif_backend_default_box.currentText(),
            "video": self.video_backend_default_box.currentText(),
        }
        self.config["backend_fallbacks"] = {
            "awww": self._fallback_values(self.awww_fallbacks_edit),
            "swww": self._fallback_values(self.swww_fallbacks_edit),
            "hyprpaper": self._fallback_values(self.hyprpaper_fallbacks_edit),
            "mpvpaper": self._fallback_values(self.mpvpaper_fallbacks_edit),
            "gslapper": self._fallback_values(self.gslapper_fallbacks_edit),
        }
        self.config["backends"] = {
            "awww": {
                "command": self.awww_command_edit.text(),
                "transition_type": self.awww_transition_type_box.currentText(),
                "transition_step": self.awww_transition_step_spin.value(),
                "transition_duration": self.awww_transition_duration_spin.value(),
                "transition_fps": self.awww_transition_fps_spin.value(),
                "transition_angle": self.awww_transition_angle_spin.value(),
                "transition_pos": self.awww_transition_pos_edit.text(),
                "invert_y": self.awww_invert_y_check.isChecked(),
                "transition_bezier": self.awww_transition_bezier_edit.text(),
                "transition_wave": self.awww_transition_wave_edit.text(),
            },
            "swww": {
                "command": self.swww_command_edit.text(),
                "transition_type": self.swww_transition_type_box.currentText(),
                "transition_step": self.swww_transition_step_spin.value(),
                "transition_duration": self.swww_transition_duration_spin.value(),
                "transition_fps": self.swww_transition_fps_spin.value(),
                "transition_angle": self.swww_transition_angle_spin.value(),
                "transition_pos": self.swww_transition_pos_edit.text(),
                "invert_y": self.swww_invert_y_check.isChecked(),
                "transition_bezier": self.swww_transition_bezier_edit.text(),
                "transition_wave": self.swww_transition_wave_edit.text(),
            },
            "hyprpaper": {
                "command": self.hyprpaper_command_edit.text(),
                "fit_mode": self.hyprpaper_fit_mode_box.currentText(),
            },
            "mpvpaper": {
                "command": self.mpvpaper_command_edit.text(),
                "options": self.mpvpaper_options_edit.text(),
                "hardware_decoding": self.mpvpaper_hwdec_box.currentData(),
            },
            "gslapper": {
                "command": self.gslapper_command_edit.text(),
            },
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        if self.current_folder is not None:
            self.load_folder(self.current_folder)
        self.status.showMessage("Backend defaults saved", 5000)

    def save_video_settings(self) -> None:
        current = self.config.get("video_optimization", {})
        self.config["video_optimization"] = {
            "enabled": self.video_opt_enabled_check.isChecked(),
            "auto_optimize": self.video_opt_enabled_check.isChecked(),
            "profile": self.video_opt_profile_box.currentText(),
            "cache_dir": "",
            "prefer_optimized": True,
            "bulk_warning": True,
            "max_concurrent_jobs": min(2, int(current.get("max_concurrent_jobs", 2))),
            "library_scan_interval_seconds": float(
                current.get("library_scan_interval_seconds", 30)
            ),
            "codec": self.video_codec_edit.text(),
            "codec_names": self._comma_values(self.video_codec_names_edit.text()),
            "container": self.video_container_edit.text(),
            "extension": self.video_extension_edit.text(),
            "max_width": self.video_max_width_spin.value(),
            "max_height": self.video_max_height_spin.value(),
            "max_bit_rate": self.video_max_bitrate_spin.value() * 1_000_000,
            "crf": self.video_crf_spin.value(),
            "preset": self.video_preset_edit.text(),
            "loop_friendly": self.video_loop_friendly_check.isChecked(),
            "loop_gop_size": self.video_loop_gop_spin.value(),
            "extra_args": self.video_extra_args_edit.text(),
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            self.status.showMessage("Video settings saved; wallmuxd is not running", 6000)
            return
        self.status.showMessage("Video settings saved and reloaded", 5000)

    def optimize_selected_video(self) -> None:
        if (
            self.selected_item is None
            or self.selected_item.wallpaper_type is not WallpaperType.VIDEO
        ):
            QMessageBox.information(self, "Wallmux", "Select a video wallpaper first.")
            return
        self.save_video_settings()
        self._start_video_optimize_task([self.selected_item], library=False)

    def optimize_video_library_gui(self) -> None:
        videos = [item for item in self.items if item.wallpaper_type is WallpaperType.VIDEO]
        if not videos:
            QMessageBox.information(self, "Wallmux", "No videos in the current library.")
            return
        if (
            QMessageBox.question(
                self,
                "Wallmux",
                f"Optimize {len(videos)} video(s)? This can take a while and use disk space.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.save_video_settings()
        self._start_video_optimize_task(videos, library=True)

    def _start_video_optimize_task(self, items: list[WallpaperItem], *, library: bool) -> None:
        self.video_opt_log.clear()
        self.video_cache_size_before = cache_stats(self.config).optimized_videos.bytes
        task = VideoOptimizeTask(
            items,
            profile=self.video_opt_profile_box.currentText(),
            force=self.video_force_optimize_check.isChecked(),
            library=library,
            config=self.config,
        )
        task.signals.progress.connect(self._video_optimize_progress)
        task.signals.source_progress.connect(self._video_source_progress)
        task.signals.source_done.connect(self._video_source_done)
        task.signals.source_failed.connect(self._video_source_failed)
        task.signals.finished.connect(self._video_optimize_finished)
        task.signals.failed.connect(self._video_optimize_failed)
        for item in items:
            if item.wallpaper_type is WallpaperType.VIDEO:
                self.video_optimize_tasks[str(item.path)] = task
                self.video_optimize_state[str(item.path)] = {
                    "status": "running",
                    "percent": 0.0,
                    "message": "queued",
                }
                self.update_video_item_icon(str(item.path))
        self.status.showMessage("Video optimization started", 5000)
        self.thread_pool.start(task)

    def _video_optimize_progress(self, message: str) -> None:
        self.video_opt_log.setPlainText(message)
        self.status.showMessage(message, 3000)

    def _video_source_progress(self, source_path: str, percent: float, message: str) -> None:
        self.video_optimize_state[source_path] = {
            "status": "running",
            "percent": None if percent < 0 else percent,
            "message": message,
        }
        self.update_video_item_icon(source_path)

    def _video_source_done(self, source_path: str, message: str) -> None:
        self._release_video_task_later(source_path)
        self.video_optimize_state[source_path] = {
            "status": "done",
            "percent": 100.0,
            "message": message,
        }
        self.update_video_item_icon(source_path)

    def _video_source_failed(self, source_path: str, message: str) -> None:
        self._release_video_task_later(source_path)
        self.video_optimize_state[source_path] = {
            "status": "failed",
            "percent": None,
            "message": message,
        }
        self.update_video_item_icon(source_path)

    def _release_video_task_later(self, source_path: str) -> None:
        task = self.video_optimize_tasks.get(source_path)
        if task is None:
            return
        QTimer.singleShot(
            1500,
            lambda path=source_path, released_task=task: self._release_video_task(
                path,
                released_task,
            ),
        )

    def _release_video_task(self, source_path: str, task: VideoOptimizeTask) -> None:
        if self.video_optimize_tasks.get(source_path) is task:
            self.video_optimize_tasks.pop(source_path, None)

    def _video_optimize_finished(self, message: str) -> None:
        cache_after = cache_stats(self.config).optimized_videos.bytes
        cache_lines = []
        if self.video_cache_size_before is not None:
            cache_lines = [
                "",
                f"cache before: {_format_bytes(self.video_cache_size_before)}",
                f"cache after: {_format_bytes(cache_after)}",
            ]
        self.video_cache_size_before = None
        self.video_opt_log.setPlainText("\n".join([message, *cache_lines]))
        self.refresh_cache_stats()
        self.status.showMessage("Video optimization finished", 6000)

    def _video_optimize_failed(self, message: str) -> None:
        self.video_opt_log.setPlainText(message)
        QMessageBox.critical(self, "Wallmux", message)

    def save_cache_settings(self) -> None:
        self.config["cache"] = {
            "maintenance_enabled": self.cache_maintenance_check.isChecked(),
            "cleanup_interval_seconds": self.cache_cleanup_interval_spin.value(),
            "cleanup_policy": self.cache_cleanup_policy_box.currentData(),
            "thumbnail_max_age_days": self.cache_thumbnail_age_spin.value(),
            "optimized_video_max_size_mb": self.cache_video_limit_spin.value(),
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            self.status.showMessage("Cache settings saved; wallmuxd is not running", 6000)
            return
        self.status.showMessage("Cache settings saved and reloaded", 5000)

    def clean_cache_gui(self, policy: str) -> None:
        self.save_cache_settings()
        self._start_cache_task("clean", policy=policy)

    def rebuild_thumbnail_cache_gui(self) -> None:
        self._start_cache_task("rebuild", include_thumbnails=True, include_videos=False)

    def rebuild_video_cache_gui(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Wallmux",
                "Rebuild optimized video cache for the current library? This can take a while.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.save_cache_settings()
        self._start_cache_task("rebuild", include_thumbnails=False, include_videos=True)

    def _start_cache_task(
        self,
        mode: str,
        *,
        include_thumbnails: bool = True,
        include_videos: bool = True,
        policy: str | None = None,
    ) -> None:
        if self.cache_task is not None:
            QMessageBox.information(self, "Wallmux", "A cache job is already running.")
            return
        self.cache_stats_view.setPlainText("Cache job running...")
        self.cache_task = CacheMaintenanceTask(
            mode=mode,
            config=self.config,
            items=list(self.items),
            include_thumbnails=include_thumbnails,
            include_videos=include_videos,
            policy=policy,
        )
        self.cache_task.signals.finished.connect(self._cache_task_finished)
        self.cache_task.signals.failed.connect(self._cache_task_failed)
        self.thread_pool.start(self.cache_task)

    def _cache_task_finished(self, message: str) -> None:
        self.cache_task = None
        self.cache_stats_view.setPlainText(message)
        self.refresh_cache_stats(append=True)
        self.status.showMessage("Cache job finished", 6000)

    def _cache_task_failed(self, message: str) -> None:
        self.cache_task = None
        self.cache_stats_view.setPlainText(message)
        QMessageBox.critical(self, "Wallmux", message)

    def save_autoswitch_settings(self) -> None:
        if self.autoswitch_enabled_check.isChecked() and not self.daemon_running:
            QMessageBox.warning(
                self,
                "Wallmux",
                "Auto switching requires wallmuxd. Start wallmuxd before enabling it.",
            )
            self.autoswitch_enabled_check.setChecked(False)
            return

        autoswitch = self.config.setdefault("autoswitch", {})
        autoswitch["enabled"] = self.autoswitch_enabled_check.isChecked()
        autoswitch["interval_seconds"] = self.autoswitch_interval_spin.value()
        autoswitch["mode"] = self.autoswitch_mode_box.currentData()
        autoswitch["target"] = self.autoswitch_target_box.currentData()
        autoswitch["monitor"] = self.autoswitch_monitor_edit.text()
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            self.status.showMessage("Auto switching saved; wallmuxd is not running", 6000)
            self.refresh_daemon_status(False)
            return
        self.status.showMessage("Auto switching saved and reloaded", 5000)
        self.refresh_daemon_status(True)

    def save_inhibition_settings(self) -> None:
        self.config["inhibition"] = {
            "enabled": self.inhibition_enabled_check.isChecked(),
            "check_interval_seconds": self.inhibition_interval_spin.value(),
            "pause_autoswitch": self.inhibition_pause_autoswitch_check.isChecked(),
            "pause_videos": self.inhibition_pause_videos_check.isChecked(),
            "inhibit_manual_commands": self.inhibition_manual_commands_check.isChecked(),
            "fullscreen": self.inhibition_fullscreen_check.isChecked(),
            "process_names": self._pattern_lines(self.inhibition_process_names_edit),
            "class_patterns": self._pattern_lines(self.inhibition_class_patterns_edit),
            "title_patterns": self._pattern_lines(self.inhibition_title_patterns_edit),
        }
        self.config["resource_mode"] = {
            "battery_behavior": self.battery_behavior_box.currentData(),
            "high_load_behavior": self.high_load_behavior_box.currentData(),
            "cpu_load_threshold": self.cpu_load_threshold_spin.value(),
            "gpu_load_threshold": self.gpu_load_threshold_spin.value(),
            "sustained_seconds": self.sustained_seconds_spin.value(),
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            self.status.showMessage("Inhibition saved; wallmuxd is not running", 6000)
            return
        self.status.showMessage("Inhibition saved and reloaded", 5000)

    def save_notification_settings(self) -> None:
        self.config["notifications"] = {
            "enabled": self.notifications_enabled_check.isChecked(),
            "switched_wallpaper": self.notify_switched_check.isChecked(),
            "switching_failed": self.notify_failed_check.isChecked(),
            "video_optimization": self.notify_video_optimization_check.isChecked(),
            "command": self.notification_command_edit.text(),
            "app_name": self.notification_app_name_edit.text(),
            "icon": self.notification_icon_edit.text(),
            "desktop_entry": self.notification_desktop_entry_edit.text(),
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            self.status.showMessage("Notifications saved; wallmuxd is not running", 6000)
            return
        self.status.showMessage("Notifications saved and reloaded", 5000)

    def autoswitch_now(self) -> None:
        request = {
            "command": "autoswitch-now",
            "mode": self.autoswitch_mode_box.currentData(),
            "target": self.autoswitch_target_box.currentData(),
        }
        if self.autoswitch_target_box.currentData() == "monitor":
            request["monitor"] = self.autoswitch_monitor_edit.text()
        try:
            response = send_request(request)
        except DaemonUnavailable as error:
            QMessageBox.warning(self, "Wallmux", f"wallmuxd is not running: {error}")
            self.refresh_daemon_status(False)
            return
        if not response.get("ok"):
            QMessageBox.critical(self, "Wallmux", response.get("error", "unknown daemon error"))
            return
        self._show_set_results(response.get("results", []))
        self.refresh_daemon_status(True)

    def refresh_settings(self) -> None:
        self.folder_list.clear()
        for folder in self.config.get("general", {}).get("wallpaper_dirs", []):
            self.folder_list.addItem(folder)
        self.refresh_gui_settings()
        self.refresh_profile_settings()
        self.refresh_backend_settings()
        self.refresh_video_settings()
        self.refresh_cache_settings()
        self.refresh_cache_stats()
        self.refresh_autoswitch_settings()
        self.refresh_inhibition_settings()
        self.refresh_notification_settings()
        self.refresh_transition_settings()

    def refresh_gui_settings(self) -> None:
        gui = self.config.get("gui", {})
        self.close_after_set_check.blockSignals(True)
        self.close_after_set_check.setChecked(bool(gui.get("close_after_set", False)))
        self.close_after_set_check.blockSignals(False)

    def refresh_profile_settings(self, *, select_index: int | None = None) -> None:
        profiles = self.config.setdefault("profiles", {})
        entries = profiles.setdefault("entries", [])
        self.profile_settings_loading = True
        try:
            self.global_profile_before_switch_edit.setPlainText(
                "\n".join(profiles.get("before_switch", []))
            )
            self.global_profile_after_switch_edit.setPlainText(
                "\n".join(profiles.get("after_switch", []))
            )
        finally:
            self.profile_settings_loading = False
        active_name = str(profiles.get("active", ""))
        active_category = str(profiles.get("active_category", ""))
        active_subcategory = str(profiles.get("active_subcategory", ""))

        current_row = self._current_profile_row() if select_index is None else select_index
        self.profile_tree.blockSignals(True)
        self.profile_tree.clear()
        parent_items: dict[str, QTreeWidgetItem] = {}
        pending_selection: QTreeWidgetItem | None = None
        for index, entry in enumerate(entries):
            if str(entry.get("category", "")):
                continue
            name = str(entry.get("name", ""))
            if not name:
                continue
            is_active = (
                entry.get("name") == active_name
                and str(entry.get("category", "")) == active_category
                and str(entry.get("subcategory", "")) == active_subcategory
            )
            parent = QTreeWidgetItem([_profile_tree_label(entry, active=is_active)])
            parent.setData(0, Qt.ItemDataRole.UserRole, index)
            _apply_profile_swatch(parent, str(entry.get("color", "")))
            parent.setExpanded(True)
            self.profile_tree.addTopLevelItem(parent)
            parent_items[name] = parent
            if index == current_row:
                pending_selection = parent

        for index, entry in enumerate(entries):
            if not str(entry.get("category", "")):
                continue
            is_active = (
                entry.get("name") == active_name
                and str(entry.get("category", "")) == active_category
                and str(entry.get("subcategory", "")) == active_subcategory
            )
            item = QTreeWidgetItem([_profile_tree_label(entry, active=is_active)])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            _apply_profile_swatch(item, str(entry.get("color", "")))
            category = str(entry.get("category", ""))
            if category:
                parent = parent_items.get(category)
                if parent is None:
                    parent = QTreeWidgetItem([category])
                    parent.setData(0, Qt.ItemDataRole.UserRole, -1)
                    self.profile_tree.addTopLevelItem(parent)
                    parent_items[category] = parent
                parent.addChild(item)
                parent.setExpanded(True)
            if index == current_row:
                pending_selection = item

        if pending_selection is not None:
            self.profile_tree.setCurrentItem(pending_selection)
        self.profile_tree.blockSignals(False)
        self.select_profile_settings(self._current_profile_row())

    def select_profile_tree_item(self, current, _previous) -> None:
        if current is None:
            self.select_profile_settings(-1)
            return
        self.select_profile_settings(_profile_tree_item_row(current))

    def _current_profile_row(self) -> int:
        item = self.profile_tree.currentItem()
        if item is None:
            return -1
        return _profile_tree_item_row(item)

    def select_profile_settings(self, row: int) -> None:
        self.profile_settings_loading = True
        entries = self.config.setdefault("profiles", {}).setdefault("entries", [])
        enabled = 0 <= row < len(entries)
        try:
            for widget in (
            self.profile_name_edit,
            self.profile_category_edit,
            self.profile_subcategory_edit,
            self.profile_color_edit,
            self.profile_dirs_list,
                self.profile_image_backend_box,
                self.profile_gif_backend_box,
                self.profile_video_backend_box,
                self.profile_autoswitch_mode_box,
                self.profile_filter_query_edit,
                self.profile_filter_types_edit,
                self.profile_before_switch_edit,
                self.profile_after_switch_edit,
                self.profile_include_parent_hooks_check,
            ):
                widget.setEnabled(enabled)

            if not enabled:
                self.profile_name_edit.clear()
                self.profile_category_edit.clear()
                self.profile_subcategory_edit.clear()
                self.profile_color_edit.clear()
                self.profile_dirs_list.clear()
                self.profile_filter_query_edit.clear()
                self.profile_filter_types_edit.clear()
                self.profile_before_switch_edit.clear()
                self.profile_after_switch_edit.clear()
                self.profile_include_parent_hooks_check.setChecked(False)
                return

            entry = entries[row]
            self.profile_name_edit.setText(str(entry.get("name", "")))
            self.profile_category_edit.setText(str(entry.get("category", "")))
            self.profile_subcategory_edit.setText(str(entry.get("subcategory", "")))
            self.profile_color_edit.setText(str(entry.get("color", "")))
            self.profile_dirs_list.clear()
            for folder in entry.get("wallpaper_dirs", []):
                self.profile_dirs_list.addItem(str(folder))
            backend_rules = entry.get("backend_rules", {})
            self._set_combo_data(
                self.profile_image_backend_box,
                str(backend_rules.get("image", "")),
            )
            self._set_combo_data(
                self.profile_gif_backend_box,
                str(backend_rules.get("gif", "")),
            )
            self._set_combo_data(
                self.profile_video_backend_box,
                str(backend_rules.get("video", "")),
            )
            self._set_combo_data(
                self.profile_autoswitch_mode_box,
                str(entry.get("autoswitch_mode", "")),
            )
            self.profile_filter_query_edit.setText(str(entry.get("filter_query", "")))
            self.profile_filter_types_edit.setText(", ".join(entry.get("filter_types", [])))
            self.profile_before_switch_edit.setPlainText(
                "\n".join(entry.get("before_switch", []))
            )
            self.profile_after_switch_edit.setPlainText("\n".join(entry.get("after_switch", [])))
            self.profile_include_parent_hooks_check.setChecked(
                bool(entry.get("include_parent_hooks", False))
            )
        finally:
            self.profile_settings_loading = False

    def refresh_daemon_status(self, running: bool | None = None) -> None:
        if running is None:
            try:
                send_request({"command": "state"}, timeout_seconds=0.2)
            except DaemonUnavailable:
                running = False
            else:
                running = True
        self.daemon_status_label.setText(
            "wallmuxd: running" if running else "wallmuxd: not running"
        )
        self.daemon_running = running
        self.autoswitch_now_button.setEnabled(running)
        self.autoswitch_enabled_check.setEnabled(running)

    def refresh_state_tab(self) -> None:
        lines = []
        lines.extend(_daemon_process_status_lines())
        lines.append("")
        try:
            response = send_request({"command": "state"}, timeout_seconds=0.5)
        except DaemonUnavailable as error:
            lines.append(f"wallmuxd: not running ({error})")
            self.refresh_daemon_status(False)
        else:
            if not response.get("ok"):
                lines.append(f"wallmuxd: error ({response.get('error', 'unknown error')})")
            else:
                self.refresh_daemon_status(True)
                self._sync_daemon_video_optimization(
                    response.get("daemon", {}).get("video_optimization", {})
                )
                lines.extend(self._format_state_response(response))

        lines.append("")
        lines.append("Dependencies")
        lines.append(format_doctor_report(run_doctor(video_only=True)))
        self.state_view.setPlainText("\n".join(lines))

    def refresh_daemon_video_optimization(self) -> None:
        try:
            response = send_request({"command": "state"}, timeout_seconds=0.2)
        except DaemonUnavailable:
            return
        if response.get("ok"):
            self._sync_daemon_video_optimization(
                response.get("daemon", {}).get("video_optimization", {})
            )

    def _sync_daemon_video_optimization(self, status: dict) -> None:
        for job in status.get("jobs", []):
            source_path = str(job.get("file", ""))
            if not source_path:
                continue
            self.video_optimize_state[source_path] = {
                "status": job.get("status", "queued"),
                "percent": job.get("percent"),
                "message": job.get("error", ""),
            }
            self.update_video_item_icon(source_path)

    def control_daemon(self, action: str) -> None:
        ok, message = _control_wallmuxd(action)
        if not ok:
            QMessageBox.critical(self, "Wallmux", f"Could not {action} wallmuxd:\n{message}")
            return

        self.status.showMessage(message, 5000)
        QTimer.singleShot(500, self.refresh_state_tab)

    def _format_state_response(self, response: dict) -> list[str]:
        daemon = response.get("daemon", {})
        autoswitch = daemon.get("autoswitch", {})
        inhibition = daemon.get("inhibition", {})
        resource_mode = daemon.get("resource_mode", {})
        video_optimization = daemon.get("video_optimization", {})
        schema_version = daemon.get("state_schema_version")
        lines = [
            "Daemon",
            f"running: {daemon.get('running')}",
            f"version: {_state_value(daemon, 'version')}",
            f"state schema: {_state_value(daemon, 'state_schema_version')}",
            f"uptime: {_format_seconds(daemon.get('uptime_seconds'))}",
            f"socket: {_state_value(daemon, 'socket_path')}",
            f"config: {_state_value(daemon, 'config_path')}",
            f"state: {_state_value(daemon, 'state_path')}",
            f"startup restore pending: {daemon.get('startup_restore_pending', False)}",
        ]
        if schema_version is None:
            lines.extend(
                [
                    "warning: wallmuxd is using an older state payload; "
                    "restart wallmuxd after upgrading Wallmux.",
                    "",
                ]
            )
        else:
            lines.append("")
        lines.extend(
            [
                "Autoswitch",
                f"enabled: {autoswitch.get('enabled')}",
                f"mode: {autoswitch.get('mode')}",
                f"profile: {autoswitch.get('profile') or 'none'}",
                f"target: {autoswitch.get('target')}",
                f"monitor: {autoswitch.get('monitor')}",
                f"next switch: {_format_seconds(autoswitch.get('next_switch_seconds'))}",
                "",
                "Inhibition",
                f"enabled: {inhibition.get('enabled')}",
                f"inhibited: {inhibition.get('inhibited')}",
                f"reason: {inhibition.get('reason') or 'none'}",
                f"pause autoswitch: {inhibition.get('pause_autoswitch')}",
                f"pause videos: {inhibition.get('pause_videos')}",
                f"inhibit manual daemon commands: {inhibition.get('inhibit_manual_commands')}",
                f"paused video pids: {inhibition.get('paused_video_pids', [])}",
                "",
                "Resource Mode",
                f"battery: {resource_mode.get('battery_state', 'unknown')}",
                f"battery behavior: {resource_mode.get('battery_behavior', 'keep')}",
                f"cpu load ratio: {_state_value(resource_mode, 'cpu_load_ratio')}",
                f"gpu load percent: {_state_value(resource_mode, 'gpu_load_percent')}",
                f"high load: {resource_mode.get('high_load', False)}",
                f"high load behavior: {resource_mode.get('high_load_behavior', 'keep')}",
                "",
                "Video Optimization",
                f"running: {video_optimization.get('running', 0)}",
                f"queued: {video_optimization.get('queued', 0)}",
                f"max concurrent: {video_optimization.get('max_concurrent_jobs', 2)}",
                "",
                "Monitors",
            ]
        )
        monitors = response.get("monitors", {})
        if not monitors:
            lines.append("no monitor state")
        for monitor, entry in monitors.items():
            pid = f" pid={entry.get('pid')}" if entry.get("pid") else ""
            connected = "connected" if entry.get("connected") else "missing"
            focused = " focused" if entry.get("focused") else ""
            lines.append(
                f"{monitor}: {entry.get('file') or 'no wallpaper'} "
                f"via {entry.get('backend') or 'none'}{pid} [{connected}{focused}]"
            )

        if daemon.get("last_error"):
            error = daemon["last_error"]
            lines.extend(
                [
                    "",
                    "Last Error",
                    f"{error.get('time')} {error.get('message')}: {error.get('error')}",
                ]
            )

        events = daemon.get("events", [])
        if events:
            lines.extend(["", "Recent Events"])
            for event in events[-10:]:
                lines.append(
                    f"{event.get('time')} {event.get('kind')} "
                    f"[{event.get('status')}]: {event.get('message')}"
                )
        return lines

    def refresh_autoswitch_settings(self) -> None:
        autoswitch = self.config.get("autoswitch", {})
        self.autoswitch_enabled_check.setChecked(bool(autoswitch.get("enabled", False)))
        self.autoswitch_interval_spin.setValue(float(autoswitch.get("interval_seconds", 300)))
        self._set_combo_data(self.autoswitch_mode_box, str(autoswitch.get("mode", "random")))
        self._set_combo_data(self.autoswitch_target_box, str(autoswitch.get("target", "all")))
        self.autoswitch_monitor_edit.setText(str(autoswitch.get("monitor", "")))

    def refresh_inhibition_settings(self) -> None:
        inhibition = self.config.get("inhibition", {})
        resource_mode = self.config.get("resource_mode", {})
        self.inhibition_enabled_check.setChecked(bool(inhibition.get("enabled", True)))
        self.inhibition_interval_spin.setValue(
            float(inhibition.get("check_interval_seconds", 5.0))
        )
        self.inhibition_pause_autoswitch_check.setChecked(
            bool(inhibition.get("pause_autoswitch", True))
        )
        self.inhibition_pause_videos_check.setChecked(bool(inhibition.get("pause_videos", True)))
        self.inhibition_manual_commands_check.setChecked(
            bool(inhibition.get("inhibit_manual_commands", False))
        )
        self.inhibition_fullscreen_check.setChecked(bool(inhibition.get("fullscreen", True)))
        self.inhibition_process_names_edit.setPlainText(
            "\n".join(inhibition.get("process_names", []))
        )
        self.inhibition_class_patterns_edit.setPlainText(
            "\n".join(inhibition.get("class_patterns", []))
        )
        self.inhibition_title_patterns_edit.setPlainText(
            "\n".join(inhibition.get("title_patterns", []))
        )
        self._set_combo_data(
            self.battery_behavior_box,
            str(resource_mode.get("battery_behavior", "keep")),
        )
        self._set_combo_data(
            self.high_load_behavior_box,
            str(resource_mode.get("high_load_behavior", "keep")),
        )
        self.cpu_load_threshold_spin.setValue(float(resource_mode.get("cpu_load_threshold", 0.85)))
        self.gpu_load_threshold_spin.setValue(float(resource_mode.get("gpu_load_threshold", 85.0)))
        self.sustained_seconds_spin.setValue(float(resource_mode.get("sustained_seconds", 15.0)))

    def refresh_notification_settings(self) -> None:
        notifications = self.config.get("notifications", {})
        self.notifications_enabled_check.setChecked(bool(notifications.get("enabled", True)))
        self.notify_switched_check.setChecked(
            bool(notifications.get("switched_wallpaper", True))
        )
        self.notify_failed_check.setChecked(bool(notifications.get("switching_failed", True)))
        self.notify_video_optimization_check.setChecked(
            bool(notifications.get("video_optimization", True))
        )
        self.notification_command_edit.setText(str(notifications.get("command", "notify-send")))
        self.notification_app_name_edit.setText(str(notifications.get("app_name", "Wallmux")))
        self.notification_icon_edit.setText(str(notifications.get("icon", "wallmux-gui")))
        self.notification_desktop_entry_edit.setText(
            str(notifications.get("desktop_entry", "wallmux-gui"))
        )

    def _pattern_lines(self, text_edit: QTextEdit) -> list[str]:
        return [
            line.strip()
            for line in text_edit.toPlainText().splitlines()
            if line.strip()
        ]

    def refresh_backend_settings(self) -> None:
        general = self.config.get("general", {})
        backend_rules = self.config.get("backend_rules", {})
        backend_fallbacks = self.config.get("backend_fallbacks", {})
        backends = self.config.get("backends", {})

        self._set_combo_data(
            self.all_monitor_mode_box,
            str(general.get("all_monitor_mode", "simultaneous")),
        )
        self.image_backend_default_box.setCurrentText(str(backend_rules.get("image", "awww")))
        self.gif_backend_default_box.setCurrentText(str(backend_rules.get("gif", "awww")))
        self.video_backend_default_box.setCurrentText(str(backend_rules.get("video", "mpvpaper")))
        self.awww_fallbacks_edit.setText(
            self._fallback_text(backend_fallbacks.get("awww", ["swww"]))
        )
        self.swww_fallbacks_edit.setText(self._fallback_text(backend_fallbacks.get("swww", [])))
        self.hyprpaper_fallbacks_edit.setText(
            self._fallback_text(backend_fallbacks.get("hyprpaper", []))
        )
        self.mpvpaper_fallbacks_edit.setText(
            self._fallback_text(backend_fallbacks.get("mpvpaper", []))
        )
        self.gslapper_fallbacks_edit.setText(
            self._fallback_text(backend_fallbacks.get("gslapper", []))
        )

        self._load_image_backend_settings("awww", backends.get("awww", {}))
        self._load_image_backend_settings("swww", backends.get("swww", {}))
        hyprpaper = backends.get("hyprpaper", {})
        self.hyprpaper_command_edit.setText(str(hyprpaper.get("command", "hyprctl")))
        self.hyprpaper_fit_mode_box.setCurrentText(str(hyprpaper.get("fit_mode", "cover")))
        mpvpaper = backends.get("mpvpaper", {})
        self.mpvpaper_command_edit.setText(str(mpvpaper.get("command", "mpvpaper")))
        self.mpvpaper_options_edit.setText(str(mpvpaper.get("options", "")))
        self._set_combo_data(
            self.mpvpaper_hwdec_box,
            str(mpvpaper.get("hardware_decoding", "automatic")),
        )
        gslapper = backends.get("gslapper", {})
        self.gslapper_command_edit.setText(str(gslapper.get("command", "gslapper")))

    def refresh_video_settings(self) -> None:
        video = self.config.get("video_optimization", {})
        auto_optimize = bool(video.get("auto_optimize", video.get("enabled", True)))
        self.video_opt_enabled_check.setChecked(auto_optimize)
        self.video_prefer_optimized_check.setChecked(bool(video.get("prefer_optimized", True)))
        self.video_prefer_optimized_check.setEnabled(False)
        self.video_opt_profile_box.setCurrentText(str(video.get("profile", "balanced")))
        self.video_cache_dir_edit.setText(str(configured_video_cache_dir(self.config)))
        self.video_codec_edit.setText(str(video.get("codec", "libx264")))
        self.video_codec_names_edit.setText(
            ", ".join(str(item) for item in video.get("codec_names", ["h264"]))
        )
        self.video_container_edit.setText(str(video.get("container", "mp4")))
        self.video_extension_edit.setText(str(video.get("extension", ".mp4")))
        self.video_max_width_spin.setValue(int(video.get("max_width", 2560)))
        self.video_max_height_spin.setValue(int(video.get("max_height", 1440)))
        self.video_max_bitrate_spin.setValue(
            max(1, int(video.get("max_bit_rate", 45_000_000)) // 1_000_000)
        )
        self.video_crf_spin.setValue(int(video.get("crf", 22)))
        self.video_preset_edit.setText(str(video.get("preset", "medium")))
        self.video_loop_friendly_check.setChecked(bool(video.get("loop_friendly", True)))
        self.video_loop_gop_spin.setValue(int(video.get("loop_gop_size", 60)))
        extra_args = video.get("extra_args", ["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
        if isinstance(extra_args, list):
            extra_args = " ".join(str(item) for item in extra_args)
        self.video_extra_args_edit.setText(str(extra_args))

    def refresh_cache_settings(self) -> None:
        cache = self.config.get("cache", {})
        self.cache_maintenance_check.setChecked(bool(cache.get("maintenance_enabled", True)))
        self._set_combo_data(
            self.cache_cleanup_policy_box,
            str(cache.get("cleanup_policy", "stale-only")),
        )
        self.cache_cleanup_interval_spin.setValue(
            int(cache.get("cleanup_interval_seconds", 86400))
        )
        self.cache_thumbnail_age_spin.setValue(int(cache.get("thumbnail_max_age_days", 60)))
        self.cache_video_limit_spin.setValue(int(cache.get("optimized_video_max_size_mb", 10240)))

    def refresh_cache_stats(self, *, append: bool = False) -> None:
        stats_text = format_cache_stats(cache_stats(self.config))
        if append and self.cache_stats_view.toPlainText():
            self.cache_stats_view.append("")
            self.cache_stats_view.append("Updated stats:")
            self.cache_stats_view.append(stats_text)
        else:
            self.cache_stats_view.setPlainText(stats_text)

    def _load_image_backend_settings(self, backend: str, backend_config: dict) -> None:
        if backend == "awww":
            command = self.awww_command_edit
            transition_type = self.awww_transition_type_box
            step = self.awww_transition_step_spin
            duration = self.awww_transition_duration_spin
            fps = self.awww_transition_fps_spin
            angle = self.awww_transition_angle_spin
            position = self.awww_transition_pos_edit
            invert_y = self.awww_invert_y_check
            bezier = self.awww_transition_bezier_edit
            wave = self.awww_transition_wave_edit
        else:
            command = self.swww_command_edit
            transition_type = self.swww_transition_type_box
            step = self.swww_transition_step_spin
            duration = self.swww_transition_duration_spin
            fps = self.swww_transition_fps_spin
            angle = self.swww_transition_angle_spin
            position = self.swww_transition_pos_edit
            invert_y = self.swww_invert_y_check
            bezier = self.swww_transition_bezier_edit
            wave = self.swww_transition_wave_edit

        command.setText(str(backend_config.get("command", backend)))
        transition_type.setCurrentText(str(backend_config.get("transition_type", "grow")))
        step.setValue(int(backend_config.get("transition_step", 90)))
        duration.setValue(float(backend_config.get("transition_duration", 0.8)))
        fps.setValue(int(backend_config.get("transition_fps", 60)))
        angle.setValue(float(backend_config.get("transition_angle", 45.0)))
        position.setText(str(backend_config.get("transition_pos", "center")))
        invert_y.setChecked(bool(backend_config.get("invert_y", False)))
        bezier.setText(str(backend_config.get("transition_bezier", ".54,0,.34,.99")))
        wave.setText(str(backend_config.get("transition_wave", "20,20")))

    def _fallback_values(self, edit: QLineEdit) -> list[str]:
        return [
            item.strip()
            for item in edit.text().split(",")
            if item.strip()
        ]

    def _fallback_text(self, value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return ""

    def _comma_values(self, text: str) -> list[str]:
        return [item.strip() for item in text.split(",") if item.strip()]

    def _transition_type_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(IMAGE_TRANSITIONS)
        return combo

    def _step_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 255)
        return spin

    def _duration_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 20.0)
        spin.setSingleStep(0.1)
        spin.setDecimals(2)
        return spin

    def _fps_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 240)
        return spin

    def _angle_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 360.0)
        spin.setSingleStep(5.0)
        spin.setDecimals(1)
        return spin

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def refresh_transition_settings(self) -> None:
        transitions = self.config.get("transitions", {})
        basic = transitions.get("basic", {})
        video_bridge = transitions.get("video_bridge", {})
        effects = transitions.get("effects", {})
        self.basic_transitions_check.setChecked(bool(basic.get("enabled", True)))
        self.video_poster_bridge_check.setChecked(
            bool(video_bridge.get("enabled", True))
        )
        self.video_poster_timestamp_spin.setValue(
            float(video_bridge.get("poster_timestamp_seconds", 0.0))
        )
        self.video_poster_settle_spin.setValue(
            float(video_bridge.get("poster_settle_seconds", 0.8))
        )
        self.video_start_settle_spin.setValue(
            float(basic.get("video_start_settle_seconds", 0.6))
        )
        self.fade_overlay_check.setChecked(bool(effects.get("fade_overlay", False)))
        self.fade_command_edit.setText(str(effects.get("fade_command", "")))
        self.screenshot_bridge_check.setChecked(bool(effects.get("screenshot_bridge", False)))
        self.screenshot_command_edit.setText(str(effects.get("screenshot_command", "")))
        self.quickshell_overlay_check.setChecked(bool(effects.get("quickshell_overlay", False)))
        self.quickshell_command_edit.setText(str(effects.get("quickshell_command", "")))
        quickshell_transitions = effects.get(
            "quickshell_transitions",
            ["image_to_video", "video_to_image", "video_to_video"],
        )
        self.quickshell_image_to_image_check.setChecked(
            "image_to_image" in quickshell_transitions
        )
        self.quickshell_image_to_video_check.setChecked(
            "image_to_video" in quickshell_transitions
        )
        self.quickshell_video_to_image_check.setChecked(
            "video_to_image" in quickshell_transitions
        )
        self.quickshell_video_to_video_check.setChecked(
            "video_to_video" in quickshell_transitions
        )
        self.transition_effect_timeout_spin.setValue(float(effects.get("timeout_seconds", 2.0)))

    def save_transition_settings(self) -> None:
        transitions = self.config.setdefault("transitions", {})
        transitions["basic"] = {
            "enabled": self.basic_transitions_check.isChecked(),
            "video_start_settle_seconds": self.video_start_settle_spin.value(),
        }
        transitions["video_bridge"] = {
            "enabled": self.video_poster_bridge_check.isChecked(),
            "poster_timestamp_seconds": self.video_poster_timestamp_spin.value(),
            "poster_settle_seconds": self.video_poster_settle_spin.value(),
        }
        transitions["effects"] = {
            "fade_overlay": self.fade_overlay_check.isChecked(),
            "fade_command": self.fade_command_edit.text(),
            "screenshot_bridge": self.screenshot_bridge_check.isChecked(),
            "screenshot_command": self.screenshot_command_edit.text(),
            "quickshell_overlay": self.quickshell_overlay_check.isChecked(),
            "quickshell_command": self.quickshell_command_edit.text(),
            "quickshell_transitions": [
                transition
                for transition, checkbox in (
                    ("image_to_image", self.quickshell_image_to_image_check),
                    ("image_to_video", self.quickshell_image_to_video_check),
                    ("video_to_image", self.quickshell_video_to_image_check),
                    ("video_to_video", self.quickshell_video_to_video_check),
                )
                if checkbox.isChecked()
            ],
            "timeout_seconds": self.transition_effect_timeout_spin.value(),
        }
        write_config(self.config, user_config_file())
        try:
            send_request({"command": "reload"})
        except DaemonUnavailable:
            pass
        self.status.showMessage("Transition effects saved", 5000)

    def refresh_hook_log(self) -> None:
        log_file = hook_log_file()
        if not log_file.exists():
            self.hook_log_view.setPlainText("No hook log yet.")
            return

        content = log_file.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        self.hook_log_view.setPlainText("\n".join(lines[-200:]))

    def toggle_zen_mode(self) -> None:
        self.set_zen_mode(not self.zen_mode)

    def set_zen_mode(self, enabled: bool, *, persist: bool = True) -> None:
        self.zen_mode = enabled
        self.zen_mode_check.blockSignals(True)
        self.zen_mode_check.setChecked(enabled)
        self.zen_mode_check.blockSignals(False)
        self.tabs.setCurrentIndex(0)
        self.tabs.tabBar().setVisible(not enabled)
        self.toolbar.setVisible(not enabled)
        self.side_panel.setVisible(not enabled)
        self.status.setVisible(not enabled)
        self.grid.setSpacing(8 if enabled else 0)
        self.grid.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if persist:
            self.config.setdefault("gui", {})["zen_mode"] = enabled
            write_config(self.config, user_config_file())

    def set_close_after_set(self, enabled: bool) -> None:
        self.config.setdefault("gui", {})["close_after_set"] = enabled
        write_config(self.config, user_config_file())

    def queue_thumbnail(self, item: WallpaperItem) -> None:
        key = str(item.path)
        if key in self.pending_thumbnails:
            return

        self.pending_thumbnails.add(key)
        task = ThumbnailTask(item, self.thumbnail_size)
        self.thumbnail_tasks[key] = task
        task.signals.loaded.connect(self.apply_thumbnail)
        task.signals.failed.connect(self.finish_thumbnail)
        self.thread_pool.start(task)

    def refresh_video_cache_marker(self, item: WallpaperItem) -> None:
        if item.wallpaper_type is not WallpaperType.VIDEO:
            return
        key = str(item.path)
        if cached_optimized_video_for_source(item.path, self.config) is None:
            return
        self.video_optimize_state[key] = {
            "status": "done",
            "percent": 100.0,
            "message": "cached",
        }
        self.update_video_item_icon(key)

    def apply_thumbnail(self, source_path: str, thumbnail_path: str) -> None:
        self.finish_thumbnail(source_path)
        pixmap = QPixmap(thumbnail_path)
        if pixmap.isNull():
            return

        self.thumbnail_pixmaps[source_path] = pixmap
        icon = QIcon(self._video_overlay_pixmap(source_path, pixmap))
        for index in range(self.grid.count()):
            widget_item = self.grid.item(index)
            item = widget_item.data(Qt.ItemDataRole.UserRole)
            if str(item.path) == source_path:
                widget_item.setIcon(icon)

        if self.selected_item is not None and str(self.selected_item.path) == source_path:
            self._set_preview_pixmap(pixmap)

    def finish_thumbnail(self, source_path: str) -> None:
        self.pending_thumbnails.discard(source_path)
        self.thumbnail_tasks.pop(source_path, None)

    def update_video_item_icon(self, source_path: str) -> None:
        pixmap = self.thumbnail_pixmaps.get(source_path)
        if pixmap is None:
            return
        icon = QIcon(self._video_overlay_pixmap(source_path, pixmap))
        for index in range(self.grid.count()):
            widget_item = self.grid.item(index)
            item = widget_item.data(Qt.ItemDataRole.UserRole)
            if str(item.path) == source_path:
                widget_item.setIcon(icon)

    def _video_overlay_pixmap(self, source_path: str, pixmap: QPixmap) -> QPixmap:
        state = self.video_optimize_state.get(source_path)
        if not state:
            return pixmap
        overlay = QPixmap(pixmap)
        painter = QPainter(overlay)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        status = state.get("status")
        if status in {"queued", "running"}:
            percent = state.get("percent")
            width = overlay.width()
            bar_width = width if percent is None else int(width * (float(percent) / 100.0))
            pen_bg = QPen(QColor("#101827"))
            pen_bg.setWidth(6)
            pen_fg = QPen(QColor("#2563ff"))
            pen_fg.setWidth(6)
            y = max(4, overlay.height() - 5)
            painter.setPen(pen_bg)
            painter.drawLine(0, y, width, y)
            painter.setPen(pen_fg)
            painter.drawLine(0, y, bar_width, y)
        elif status == "done":
            size = max(28, int(min(overlay.width(), overlay.height()) * 0.24))
            left = max(6, int(size * 0.25))
            top = max(6, int(size * 0.18))
            pen_shadow = QPen(QColor("#020617"))
            pen_shadow.setWidth(max(6, size // 6))
            pen_shadow.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen_shadow.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen_fg = QPen(QColor("#22c55e"))
            pen_fg.setWidth(max(4, size // 9))
            pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen_fg.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            points = [
                (left, top + int(size * 0.55)),
                (left + int(size * 0.32), top + int(size * 0.88)),
                (left + int(size * 0.95), top + int(size * 0.15)),
            ]
            for pen in (pen_shadow, pen_fg):
                painter.setPen(pen)
                painter.drawLine(*points[0], *points[1])
                painter.drawLine(*points[1], *points[2])
        elif status == "failed":
            painter.setPen(QPen(QColor("#ef4444"), 3))
            painter.drawText(8, 26, "!")
        painter.end()
        return overlay

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
        profile_picker = PROFILE_PICKER_ARG in sys.argv
        argv = [
            arg
            for arg in sys.argv
            if arg not in {THEME_DEBUG_ARG, PROFILE_PICKER_ARG}
        ]

        QApplication.setDesktopSettingsAware(True)
        _add_system_qt_plugin_paths()
        app = QApplication(argv)
        app.setApplicationName(APP_ID)
        app.setApplicationDisplayName("Wallmux")
        app.setDesktopFileName(APP_ID)
        app.setWindowIcon(_app_icon(app))

        if theme_debug:
            _print_theme_debug(app)
            return 0

        if profile_picker:
            run_profile_picker_dialog(None)
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
    print(f"application name: {app.applicationName()}")
    print(f"desktop file name: {app.desktopFileName()}")
    print(f"style: {app.style().objectName()}")
    print(f"available styles: {', '.join(QStyleFactory.keys())}")
    print("library paths:")
    for path in QApplication.libraryPaths():
        print(f"  {path}")


def _app_icon(app: QApplication) -> QIcon:
    icon = QIcon.fromTheme("wallmux-gui")
    if not icon.isNull():
        return icon
    icon = QIcon.fromTheme("wallmux")
    if not icon.isNull():
        return icon
    return app.style().standardIcon(QStyle.SP_DesktopIcon)


def _set_wallpaper_detached(
    request: dict,
    file: Path,
    monitor: str | None,
    backend: str,
    all_monitor_mode: str,
) -> None:
    """Finish a close-after-set request without touching Qt objects."""
    try:
        response = send_request(request)
        if not response.get("ok"):
            raise WallmuxError(response.get("error", "unknown daemon error"))
        return
    except DaemonUnavailable:
        pass
    except WallmuxError:
        return

    config = load_config()
    effective_config = effective_config_for_profile(config)
    try:
        if monitor == ALL_MONITORS:
            results = set_wallpaper_for_all(
                file,
                config=effective_config,
                backend_override=backend,
                mode=all_monitor_mode,
            )
        else:
            results = [
                set_wallpaper(
                    file,
                    monitor or "",
                    config=effective_config,
                    backend_override=backend,
                )
            ]
    except (ValueError, WallmuxError) as error:
        notify_switch_failed(config, error)
        return
    notify_wallpaper_switched(config, results)


def _control_wallmuxd(action: str) -> tuple[bool, str]:
    if action == "start":
        if _daemon_socket_running():
            return True, "wallmuxd is already running"
        service = _systemd_service_state()
        if service["unit_found"]:
            ok, message = _systemctl_user("start")
            if ok:
                return True, "wallmuxd service start requested"
            if service["active"]:
                return False, message
        return _start_standalone_wallmuxd()

    if action == "stop":
        service = _systemd_service_state()
        messages = []
        if service["active"]:
            ok, message = _systemctl_user("stop")
            if not ok:
                return False, message
            messages.append("wallmuxd service stop requested")
        pids = _wallmuxd_pids()
        if pids:
            _terminate_wallmuxd_pids(pids)
            messages.append(f"stopped standalone wallmuxd process(es): {', '.join(map(str, pids))}")
        if messages:
            return True, "; ".join(messages)
        return True, "wallmuxd is not running"

    if action == "restart":
        service = _systemd_service_state()
        if service["active"]:
            ok, message = _systemctl_user("restart")
            if ok:
                return True, "wallmuxd service restart requested"
            return False, message
        pids = _wallmuxd_pids()
        if pids:
            _terminate_wallmuxd_pids(pids)
        if service["unit_found"]:
            ok, message = _systemctl_user("start")
            if ok:
                return True, "wallmuxd service start requested"
        return _start_standalone_wallmuxd()

    return False, f"unknown daemon action: {action}"


def _daemon_process_status_lines() -> list[str]:
    service = _systemd_service_state()
    pids = _wallmuxd_pids()
    service_state = "unavailable"
    if service["unit_found"]:
        service_state = "active" if service["active"] else "inactive"
    process_state = ", ".join(str(pid) for pid in pids) if pids else "not running"
    return [
        "Daemon Control",
        f"systemd service: {service_state}",
        f"standalone process pids: {process_state}",
    ]


def _systemd_service_state() -> dict[str, bool]:
    result = subprocess.run(
        ["systemctl", "--user", "show", "wallmux.service", "--property=LoadState,ActiveState"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"unit_found": False, "active": False}
    values = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    load_state = values.get("LoadState", "")
    active_state = values.get("ActiveState", "")
    return {
        "unit_found": load_state not in {"", "not-found"},
        "active": active_state == "active",
    }


def _systemctl_user(action: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["systemctl", "--user", action, "wallmux.service"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, f"systemctl --user {action} wallmux.service succeeded"
    return False, result.stderr.strip() or result.stdout.strip() or "systemctl failed"


def _start_standalone_wallmuxd() -> tuple[bool, str]:
    executable = shutil.which("wallmuxd")
    if executable is None:
        return False, "wallmux.service is not installed and wallmuxd was not found in PATH"
    try:
        subprocess.Popen(
            [executable],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        return False, str(error)
    return True, "standalone wallmuxd started"


def _wallmuxd_pids() -> list[int]:
    result = subprocess.run(
        ["pgrep", "-x", "wallmuxd"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    pids = []
    for line in result.stdout.splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return pids


def _terminate_wallmuxd_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue


def _daemon_socket_running() -> bool:
    try:
        send_request({"command": "state"}, timeout_seconds=0.2)
    except DaemonUnavailable:
        return False
    return True


def _state_value(data: dict, key: str) -> str:
    value = data.get(key)
    if value in (None, ""):
        return "unavailable; restart wallmuxd after upgrading Wallmux"
    return str(value)


def _format_seconds(value) -> str:
    if value is None:
        return "unavailable; restart wallmuxd after upgrading Wallmux"
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return str(value)


def _video_progress_text(progress) -> str:
    percent = progress.percent
    percent_text = "?" if percent is None else f"{percent:.1f}%"
    size_text = _format_bytes(progress.total_size)
    speed = f" {progress.speed}" if progress.speed else ""
    return f"{percent_text} {size_text}{speed}"


def _format_bytes(value) -> str:
    if value is None:
        return "unknown"
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return str(value)


def _help_marker(tooltip: str) -> QLabel:
    label = QLabel("?")
    label.setToolTip(tooltip)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedSize(18, 18)
    label.setStyleSheet(
        "QLabel { border: 1px solid palette(mid); border-radius: 9px; "
        "font-weight: 600; color: palette(text); }"
    )
    return label


def _form_label(text: str, tooltip: str) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(QLabel(text))
    layout.addWidget(_help_marker(tooltip))
    layout.addStretch(1)
    return widget


def _profile_entry_label(entry: dict) -> str:
    name = str(entry.get("name", ""))
    category = str(entry.get("category", ""))
    subcategory = str(entry.get("subcategory", ""))
    if category and name == subcategory:
        return f"{category} / {name}"
    parts = [
        category,
        subcategory,
        name,
    ]
    return " / ".join(part for part in parts if part) or "unnamed"


def _profile_tree_label(entry: dict, *, active: bool = False) -> str:
    name = str(entry.get("name", "")) or "unnamed"
    category = str(entry.get("category", ""))
    label = name if category else _profile_entry_label(entry)
    return f"* {label}" if active else label


def _profile_entry_is_active(entry: dict, profiles: dict) -> bool:
    return (
        entry.get("name") == profiles.get("active")
        and str(entry.get("category", "")) == str(profiles.get("active_category", ""))
        and str(entry.get("subcategory", "")) == str(profiles.get("active_subcategory", ""))
    )


def _normalize_profile_color(value: str) -> str:
    color = QColor(value.strip())
    return color.name() if color.isValid() else ""


def _profile_color_icon(value: str) -> QIcon:
    color = QColor(value)
    if not color.isValid():
        return QIcon()
    pixmap = QPixmap(16, 16)
    pixmap.fill(color)
    return QIcon(pixmap)


def _apply_profile_swatch(item: QTreeWidgetItem, value: str) -> None:
    item.setIcon(0, _profile_color_icon(value))


def _profile_tree_item_row(item: QTreeWidgetItem) -> int:
    value = item.data(0, Qt.ItemDataRole.UserRole)
    return -1 if value is None else int(value)


def _reload_daemon_quietly(_profile=None) -> None:
    try:
        send_request({"command": "reload"})
    except DaemonUnavailable:
        pass


def run_profile_picker_dialog(
    parent: QWidget | None,
    config: dict | None = None,
) -> tuple[bool, str]:
    config = config or load_config()
    profiles = list_profiles(config)
    if not profiles:
        QMessageBox.information(parent, "Wallmux", "No profiles are configured.")
        return False, ""

    dialog = QDialog(parent)
    dialog.setWindowTitle("Wallmux Profiles")
    dialog.setWindowFlag(Qt.WindowType.Dialog, True)
    dialog.resize(460, 520)
    layout = QVBoxLayout(dialog)

    search = QLineEdit()
    search.setPlaceholderText("Search profiles")
    layout.addWidget(search)

    tree = QTreeWidget()
    tree.setMinimumSize(420, 380)
    tree.setHeaderHidden(True)
    tree.setUniformRowHeights(True)
    layout.addWidget(tree)

    hint = QLabel("Enter switches selected profile")
    hint.setStyleSheet("color: palette(mid);")
    layout.addWidget(hint)

    active = get_active_profile(config)
    _populate_profile_picker_tree(tree, profiles, active)
    _select_first_profile_picker_item(tree)

    buttons = QHBoxLayout()
    switch_button = QPushButton("Switch")
    cancel_button = QPushButton("Cancel")
    buttons.addStretch(1)
    buttons.addWidget(switch_button)
    buttons.addWidget(cancel_button)
    layout.addLayout(buttons)

    def accept_selection() -> None:
        _accept_profile_picker_selection(dialog, tree)

    search.installEventFilter(_ProfilePickerSearchFilter(search, tree, accept_selection))
    switch_button.clicked.connect(accept_selection)
    cancel_button.clicked.connect(dialog.reject)
    tree.itemActivated.connect(lambda _item, _column: accept_selection())
    search.textChanged.connect(lambda text: _filter_profile_picker_tree(tree, text))
    search.returnPressed.connect(accept_selection)
    search.setFocus()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False, ""

    profile = _profile_from_picker_tree(tree)
    if profile is None:
        return False, ""
    try:
        switch_profile(
            profile.name,
            category=profile.category,
            subcategory=profile.subcategory,
            config=config,
            after_write=_reload_daemon_quietly,
        )
    except ValueError as error:
        QMessageBox.critical(parent, "Wallmux", str(error))
        return False, ""

    return True, profile.label


class _ProfilePickerSearchFilter(QObject):
    def __init__(self, parent: QObject, tree: QTreeWidget, accept_selection) -> None:
        super().__init__(parent)
        self.tree = tree
        self.accept_selection = accept_selection

    def eventFilter(self, watched: QObject, event) -> bool:
        if event.type() != event.Type.KeyPress:
            return super().eventFilter(watched, event)
        key = event.key()
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.accept_selection()
            return True
        if key in {
            Qt.Key.Key_Down,
            Qt.Key.Key_Up,
            Qt.Key.Key_PageDown,
            Qt.Key.Key_PageUp,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        }:
            _move_profile_picker_selection(self.tree, key)
            return True
        return super().eventFilter(watched, event)


def _accept_profile_picker_selection(dialog: QDialog, tree: QTreeWidget) -> None:
    if _profile_from_picker_tree(tree) is not None:
        dialog.accept()


def _profile_from_picker_tree(tree: QTreeWidget):
    selected = tree.currentItem()
    if selected is None:
        _select_first_profile_picker_item(tree)
        selected = tree.currentItem()
    if selected is None:
        return None
    profile = selected.data(0, Qt.ItemDataRole.UserRole)
    if profile is not None:
        return profile
    selected_child = _first_visible_profile_child(selected)
    if selected_child is None:
        return None
    tree.setCurrentItem(selected_child)
    return selected_child.data(0, Qt.ItemDataRole.UserRole)


def _populate_profile_picker_tree(tree: QTreeWidget, profiles: list, active) -> None:
    parent_items: dict[str, QTreeWidgetItem] = {}
    pending_selection: QTreeWidgetItem | None = None
    for profile in profiles:
        if profile.category:
            continue
        item = _profile_picker_item(profile, active=active and profile == active)
        tree.addTopLevelItem(item)
        parent_items[profile.name] = item
        if active and profile == active:
            pending_selection = item

    for profile in profiles:
        if not profile.category:
            continue
        parent_item = parent_items.get(profile.category)
        if parent_item is None:
            parent_item = QTreeWidgetItem([profile.category])
            parent_item.setData(0, Qt.ItemDataRole.UserRole, None)
            tree.addTopLevelItem(parent_item)
            parent_items[profile.category] = parent_item
        child = _profile_picker_item(profile, active=active and profile == active)
        parent_item.addChild(child)
        parent_item.setExpanded(True)
        if active and profile == active:
            pending_selection = child

    tree.expandAll()
    if pending_selection is not None:
        tree.setCurrentItem(pending_selection)


def _profile_picker_item(profile, *, active: bool = False) -> QTreeWidgetItem:
    label = profile.name if profile.category else profile.label
    if active:
        label = f"* {label}"
    item = QTreeWidgetItem([label])
    item.setData(0, Qt.ItemDataRole.UserRole, profile)
    item.setToolTip(0, profile.label)
    _apply_profile_swatch(item, profile.color)
    return item


def _filter_profile_picker_tree(tree: QTreeWidget, query: str) -> None:
    normalized = query.casefold().strip()
    first_match: QTreeWidgetItem | None = None
    for top_index in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(top_index)
        top_matches = _profile_picker_item_matches(top, normalized)
        visible_child_count = 0
        for child_index in range(top.childCount()):
            child = top.child(child_index)
            child_matches = _profile_picker_item_matches(child, normalized)
            child.setHidden(not child_matches)
            if child_matches:
                visible_child_count += 1
                first_match = first_match or child
        visible = not normalized or top_matches or visible_child_count > 0
        top.setHidden(not visible)
        top.setExpanded(bool(normalized) or visible_child_count > 0)
        if visible and top_matches:
            first_match = first_match or top

    if first_match is not None:
        tree.setCurrentItem(first_match)


def _profile_picker_item_matches(item: QTreeWidgetItem, query: str) -> bool:
    if not query:
        return True
    profile = item.data(0, Qt.ItemDataRole.UserRole)
    haystack = item.text(0)
    if profile is not None:
        haystack = f"{profile.name} {profile.category} {profile.subcategory} {profile.label}"
    return query in haystack.casefold()


def _select_first_profile_picker_item(tree: QTreeWidget) -> None:
    if tree.currentItem() is not None:
        return
    for top_index in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(top_index)
        if top.data(0, Qt.ItemDataRole.UserRole) is not None:
            tree.setCurrentItem(top)
            return
        child = _first_visible_profile_child(top)
        if child is not None:
            tree.setCurrentItem(child)
            return


def _move_profile_picker_selection(tree: QTreeWidget, key: int) -> None:
    items = _visible_profile_picker_items(tree)
    if not items:
        return
    current = tree.currentItem()
    try:
        index = items.index(current)
    except ValueError:
        index = 0

    if key == Qt.Key.Key_Down:
        index = min(index + 1, len(items) - 1)
    elif key == Qt.Key.Key_Up:
        index = max(index - 1, 0)
    elif key == Qt.Key.Key_PageDown:
        index = min(index + 8, len(items) - 1)
    elif key == Qt.Key.Key_PageUp:
        index = max(index - 8, 0)
    elif key == Qt.Key.Key_Home:
        index = 0
    elif key == Qt.Key.Key_End:
        index = len(items) - 1

    tree.setCurrentItem(items[index])
    tree.scrollToItem(items[index])


def _visible_profile_picker_items(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    items: list[QTreeWidgetItem] = []
    for top_index in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(top_index)
        if top.isHidden():
            continue
        if top.data(0, Qt.ItemDataRole.UserRole) is not None:
            items.append(top)
        for child_index in range(top.childCount()):
            child = top.child(child_index)
            if not child.isHidden() and child.data(0, Qt.ItemDataRole.UserRole) is not None:
                items.append(child)
    return items


def _first_visible_profile_child(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
    for child_index in range(item.childCount()):
        child = item.child(child_index)
        if not child.isHidden() and child.data(0, Qt.ItemDataRole.UserRole) is not None:
            return child
    return None


if __name__ == "__main__":
    raise SystemExit(main())
