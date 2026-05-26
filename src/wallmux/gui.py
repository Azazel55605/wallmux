"""PySide6 GUI entry point."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import traceback
from pathlib import Path

from wallmux.backends.routing import compatible_backends
from wallmux.core.config import load_config, user_config_file, write_config
from wallmux.core.doctor import format_doctor_report, run_doctor
from wallmux.core.hooks import hook_log_file
from wallmux.core.ipc import DaemonUnavailable, send_request
from wallmux.core.library import WallpaperItem, filter_wallpapers, scan_wallpaper_dir
from wallmux.core.mime import WallpaperType
from wallmux.core.monitors import list_monitors
from wallmux.core.thumbnails import ensure_thumbnail
from wallmux.core.wallpaper import WallmuxError, set_wallpaper, set_wallpaper_for_all

try:
    from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
    from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
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
        self.thumbnail_tasks: dict[str, ThumbnailTask] = {}
        self.zen_mode = False
        self.daemon_running = False
        self.thumbnail_size = int(self.config.get("general", {}).get("thumbnail_size", 256))
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(min(4, max(2, self.thread_pool.maxThreadCount())))

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
        self.toolbar.addAction(open_action)
        self.toolbar.addAction(refresh_action)

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

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        self.settings_tabs = QTabWidget()
        outer.addWidget(self.settings_tabs)

        general_page, general_layout = self._settings_page()
        library_page, library_layout = self._settings_page()
        backend_page, backend_page_layout = self._settings_page()
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

        self.close_after_set_check = QCheckBox("Close after setting wallpaper")
        self.close_after_set_check.toggled.connect(self.set_close_after_set)
        general_form.addRow("", self.close_after_set_check)

        self.all_monitor_mode_box = QComboBox()
        self.all_monitor_mode_box.addItem("All at the same time", "simultaneous")
        self.all_monitor_mode_box.addItem("One by one", "sequential")
        general_form.addRow("All Monitors", self.all_monitor_mode_box)
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
        autoswitch_form.addRow("Interval", self.autoswitch_interval_spin)
        autoswitch_form.addRow("Next Wallpaper", self.autoswitch_mode_box)
        autoswitch_form.addRow("Target", self.autoswitch_target_box)
        autoswitch_form.addRow("Monitor", self.autoswitch_monitor_edit)
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
        inhibition_form.addRow("", self.inhibition_fullscreen_check)
        inhibition_form.addRow("Check Interval", self.inhibition_interval_spin)
        inhibition_form.addRow("Process Names", self.inhibition_process_names_edit)
        inhibition_form.addRow("Class Patterns", self.inhibition_class_patterns_edit)
        inhibition_form.addRow("Title Patterns", self.inhibition_title_patterns_edit)
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
        self.notification_command_edit = QLineEdit()
        self.notification_app_name_edit = QLineEdit()
        self.notification_icon_edit = QLineEdit()
        self.notification_desktop_entry_edit = QLineEdit()
        notifications_form.addRow("", self.notifications_enabled_check)
        notifications_form.addRow("", self.notify_switched_check)
        notifications_form.addRow("", self.notify_failed_check)
        notifications_form.addRow("Command", self.notification_command_edit)
        notifications_form.addRow("App Name", self.notification_app_name_edit)
        notifications_form.addRow("Icon", self.notification_icon_edit)
        notifications_form.addRow("Desktop Entry", self.notification_desktop_entry_edit)
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

        backend_group = QGroupBox("Backend Defaults")
        backend_layout = QVBoxLayout(backend_group)

        routing_form = QFormLayout()
        self.image_backend_default_box = QComboBox()
        self.image_backend_default_box.addItems(["awww", "swww", "hyprpaper"])
        self.gif_backend_default_box = QComboBox()
        self.gif_backend_default_box.addItems(["awww", "swww", "mpvpaper", "gslapper"])
        self.video_backend_default_box = QComboBox()
        self.video_backend_default_box.addItems(["mpvpaper", "gslapper"])
        routing_form.addRow("Images", self.image_backend_default_box)
        routing_form.addRow("GIFs", self.gif_backend_default_box)
        routing_form.addRow("Videos", self.video_backend_default_box)
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
        fallback_form.addRow("awww", self.awww_fallbacks_edit)
        fallback_form.addRow("swww", self.swww_fallbacks_edit)
        fallback_form.addRow("hyprpaper", self.hyprpaper_fallbacks_edit)
        fallback_form.addRow("mpvpaper", self.mpvpaper_fallbacks_edit)
        fallback_form.addRow("gSlapper", self.gslapper_fallbacks_edit)
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
        awww_form.addRow("Command", self.awww_command_edit)
        awww_form.addRow("Transition", self.awww_transition_type_box)
        awww_form.addRow("Step", self.awww_transition_step_spin)
        awww_form.addRow("Duration", self.awww_transition_duration_spin)
        awww_form.addRow("FPS", self.awww_transition_fps_spin)
        awww_form.addRow("Angle", self.awww_transition_angle_spin)
        awww_form.addRow("Position", self.awww_transition_pos_edit)
        awww_form.addRow("", self.awww_invert_y_check)
        awww_form.addRow("Bezier", self.awww_transition_bezier_edit)
        awww_form.addRow("Wave", self.awww_transition_wave_edit)
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
        swww_form.addRow("Command", self.swww_command_edit)
        swww_form.addRow("Transition", self.swww_transition_type_box)
        swww_form.addRow("Step", self.swww_transition_step_spin)
        swww_form.addRow("Duration", self.swww_transition_duration_spin)
        swww_form.addRow("FPS", self.swww_transition_fps_spin)
        swww_form.addRow("Angle", self.swww_transition_angle_spin)
        swww_form.addRow("Position", self.swww_transition_pos_edit)
        swww_form.addRow("", self.swww_invert_y_check)
        swww_form.addRow("Bezier", self.swww_transition_bezier_edit)
        swww_form.addRow("Wave", self.swww_transition_wave_edit)
        swww_box = QGroupBox("swww")
        swww_box.setLayout(swww_form)
        backend_layout.addWidget(swww_box)

        self.hyprpaper_command_edit = QLineEdit()
        self.hyprpaper_fit_mode_box = QComboBox()
        self.hyprpaper_fit_mode_box.setEditable(True)
        self.hyprpaper_fit_mode_box.addItems(["cover", "contain", "tile"])
        hyprpaper_form = QFormLayout()
        hyprpaper_form.addRow("Command", self.hyprpaper_command_edit)
        hyprpaper_form.addRow("Fit mode", self.hyprpaper_fit_mode_box)
        hyprpaper_box = QGroupBox("hyprpaper")
        hyprpaper_box.setLayout(hyprpaper_form)
        backend_layout.addWidget(hyprpaper_box)

        self.mpvpaper_command_edit = QLineEdit()
        self.mpvpaper_options_edit = QLineEdit()
        mpvpaper_form = QFormLayout()
        mpvpaper_form.addRow("Command", self.mpvpaper_command_edit)
        mpvpaper_form.addRow("Options", self.mpvpaper_options_edit)
        mpvpaper_box = QGroupBox("mpvpaper")
        mpvpaper_box.setLayout(mpvpaper_form)
        backend_layout.addWidget(mpvpaper_box)

        self.gslapper_command_edit = QLineEdit()
        gslapper_form = QFormLayout()
        gslapper_form.addRow("Command", self.gslapper_command_edit)
        gslapper_box = QGroupBox("gSlapper")
        gslapper_box.setLayout(gslapper_form)
        backend_layout.addWidget(gslapper_box)

        save_backend_button = QPushButton("Save Backend Defaults")
        save_backend_button.clicked.connect(self.save_backend_settings)
        backend_layout.addWidget(save_backend_button)
        backend_page_layout.addWidget(backend_group)
        backend_page_layout.addStretch(1)

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
        self.basic_image_bridge_check = QCheckBox("Set image before stopping video")
        self.fade_overlay_check = QCheckBox("Fade overlay")
        self.screenshot_bridge_check = QCheckBox("Screenshot bridge")
        self.quickshell_overlay_check = QCheckBox("QuickShell overlay")
        self.fade_command_edit = QLineEdit()
        self.screenshot_command_edit = QLineEdit()
        self.quickshell_command_edit = QLineEdit()
        self.transition_effect_timeout_spin = QDoubleSpinBox()
        self.transition_effect_timeout_spin.setRange(0.1, 30.0)
        self.transition_effect_timeout_spin.setSingleStep(0.5)
        self.transition_effect_timeout_spin.setDecimals(1)

        transition_form.addRow("", self.basic_transitions_check)
        transition_form.addRow("", self.basic_image_bridge_check)
        transition_form.addRow("", self.fade_overlay_check)
        transition_form.addRow("Fade Command", self.fade_command_edit)
        transition_form.addRow("", self.screenshot_bridge_check)
        transition_form.addRow("Screenshot Command", self.screenshot_command_edit)
        transition_form.addRow("", self.quickshell_overlay_check)
        transition_form.addRow("QuickShell Command", self.quickshell_command_edit)
        transition_form.addRow("Effect Timeout", self.transition_effect_timeout_spin)
        transition_group = QGroupBox("Transition Effects")
        transition_group.setLayout(transition_form)
        transitions_layout.addWidget(transition_group)

        save_transitions_button = QPushButton("Save Transition Effects")
        save_transitions_button.clicked.connect(self.save_transition_settings)
        transitions_layout.addWidget(save_transitions_button)
        transitions_layout.addStretch(1)

        self.settings_tabs.addTab(general_page, "General")
        self.settings_tabs.addTab(library_page, "Library")
        self.settings_tabs.addTab(backend_page, "Backends")
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
        dirs = self.config.get("general", {}).get("wallpaper_dirs", [])
        for raw_dir in dirs:
            path = Path(raw_dir).expanduser()
            if path.exists() and path.is_dir():
                self.load_folder(path)
                return
        self.populate_grid()

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
        self.items = scan_wallpaper_dir(
            folder,
            backend_rules=self.config.get("backend_rules", {}),
        )
        self.populate_grid()
        self.status.showMessage(f"{len(self.items)} wallpapers in {folder}", 5000)
        self.grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def closeEvent(self, event) -> None:
        self.thread_pool.waitForDone(1000)
        super().closeEvent(event)

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

        try:
            response = send_request(request)
            if not response.get("ok"):
                raise WallmuxError(response.get("error", "unknown daemon error"))
            self._show_set_results(response["results"])
            self._close_after_successful_set()
        except DaemonUnavailable:
            try:
                if monitor == ALL_MONITORS:
                    results = set_wallpaper_for_all(
                        self.selected_item.path,
                        config=self.config,
                        backend_override=backend,
                        mode=all_monitor_mode,
                    )
                else:
                    result = set_wallpaper(
                        self.selected_item.path,
                        monitor or self.monitor_box.currentText(),
                        config=self.config,
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
            self._close_after_successful_set()
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
            "fullscreen": self.inhibition_fullscreen_check.isChecked(),
            "process_names": self._pattern_lines(self.inhibition_process_names_edit),
            "class_patterns": self._pattern_lines(self.inhibition_class_patterns_edit),
            "title_patterns": self._pattern_lines(self.inhibition_title_patterns_edit),
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
        self.refresh_backend_settings()
        self.refresh_autoswitch_settings()
        self.refresh_inhibition_settings()
        self.refresh_notification_settings()
        self.refresh_transition_settings()

    def refresh_gui_settings(self) -> None:
        gui = self.config.get("gui", {})
        self.close_after_set_check.blockSignals(True)
        self.close_after_set_check.setChecked(bool(gui.get("close_after_set", False)))
        self.close_after_set_check.blockSignals(False)

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
                lines.extend(self._format_state_response(response))

        lines.append("")
        lines.append("Dependencies")
        lines.append(format_doctor_report(run_doctor(video_only=True)))
        self.state_view.setPlainText("\n".join(lines))

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
                f"paused video pids: {inhibition.get('paused_video_pids', [])}",
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
        self.inhibition_enabled_check.setChecked(bool(inhibition.get("enabled", True)))
        self.inhibition_interval_spin.setValue(
            float(inhibition.get("check_interval_seconds", 5.0))
        )
        self.inhibition_pause_autoswitch_check.setChecked(
            bool(inhibition.get("pause_autoswitch", True))
        )
        self.inhibition_pause_videos_check.setChecked(bool(inhibition.get("pause_videos", True)))
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

    def refresh_notification_settings(self) -> None:
        notifications = self.config.get("notifications", {})
        self.notifications_enabled_check.setChecked(bool(notifications.get("enabled", True)))
        self.notify_switched_check.setChecked(
            bool(notifications.get("switched_wallpaper", True))
        )
        self.notify_failed_check.setChecked(bool(notifications.get("switching_failed", True)))
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
        gslapper = backends.get("gslapper", {})
        self.gslapper_command_edit.setText(str(gslapper.get("command", "gslapper")))

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
        effects = transitions.get("effects", {})
        self.basic_transitions_check.setChecked(bool(basic.get("enabled", True)))
        self.basic_image_bridge_check.setChecked(
            bool(basic.get("set_image_before_stopping_video", True))
        )
        self.fade_overlay_check.setChecked(bool(effects.get("fade_overlay", False)))
        self.fade_command_edit.setText(str(effects.get("fade_command", "")))
        self.screenshot_bridge_check.setChecked(bool(effects.get("screenshot_bridge", False)))
        self.screenshot_command_edit.setText(str(effects.get("screenshot_command", "")))
        self.quickshell_overlay_check.setChecked(bool(effects.get("quickshell_overlay", False)))
        self.quickshell_command_edit.setText(str(effects.get("quickshell_command", "")))
        self.transition_effect_timeout_spin.setValue(float(effects.get("timeout_seconds", 2.0)))

    def save_transition_settings(self) -> None:
        transitions = self.config.setdefault("transitions", {})
        transitions["basic"] = {
            "enabled": self.basic_transitions_check.isChecked(),
            "set_image_before_stopping_video": self.basic_image_bridge_check.isChecked(),
        }
        transitions["effects"] = {
            "fade_overlay": self.fade_overlay_check.isChecked(),
            "fade_command": self.fade_command_edit.text(),
            "screenshot_bridge": self.screenshot_bridge_check.isChecked(),
            "screenshot_command": self.screenshot_command_edit.text(),
            "quickshell_overlay": self.quickshell_overlay_check.isChecked(),
            "quickshell_command": self.quickshell_command_edit.text(),
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

    def _close_after_successful_set(self) -> None:
        if self.close_after_set_check.isChecked():
            self.close()

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
        self.thumbnail_tasks.pop(source_path, None)

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
        app.setApplicationName(APP_ID)
        app.setApplicationDisplayName("Wallmux")
        app.setDesktopFileName(APP_ID)
        app.setWindowIcon(_app_icon(app))

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


if __name__ == "__main__":
    raise SystemExit(main())
