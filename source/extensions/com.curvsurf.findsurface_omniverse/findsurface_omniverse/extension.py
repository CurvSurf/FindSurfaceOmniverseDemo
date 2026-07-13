import asyncio
import inspect
import json
import math
import ntpath
import os
import time
import webbrowser
import weakref
from threading import Lock, Thread

import carb
import omni.ext
import omni.kit.actions.core
import omni.kit.app
import omni.kit.menu.utils
import omni.ui as ui
from omni.kit.menu.utils import MenuItemDescription
from omni.kit.window.filepicker import FilePickerDialog
try:
    from carb.eventdispatcher import get_eventdispatcher
except Exception:
    get_eventdispatcher = None

from . import app_config
from .app_state import (
    PointCloudState,
    TRANSACTION_APPLY_DETECTION,
    TRANSACTION_CANCEL_DETECTION,
    TRANSACTION_CAMERA_CHANGE,
    TRANSACTION_DELETE_GEOMETRY,
    TRANSACTION_GEOMETRY_VISIBILITY,
    TRANSACTION_GLOBAL_VISIBILITY,
    TRANSACTION_PARAMETER_CHANGE,
    TRANSACTION_RESET_DETECTION,
    pick_center_point,
)
from findsurface.bootstrap.core import DETECTION_TYPES, DetectionOptions, FindSurfaceDetector
from .point_cloud import (
    ImportCanceledError,
    ImportCancelToken,
    ImportOptions,
    PointCloudSizeError,
    SUPPORTED_EXTENSIONS,
    load_point_cloud,
)
from .camera import PROJECTION_ORTHOGRAPHIC, PROJECTION_PERSPECTIVE, dot, normalize, sub
from findsurface.bootstrap import usd_schema
from . import viewport as viewport_module
from findsurface.bootstrap.findsurface_window import (
    FindSurfaceWindowCallbacks,
    FindSurfaceWindowModels,
    build_findsurface_window,
)
from findsurface.bootstrap.ui_views import BorderedGroupView
from .viewport import PointCloudViewport
from .workspace import read_workspace, write_geometry_export, write_workspace


EXTENSION_ID = "com.curvsurf.findsurface_omniverse"
APP_WINDOW_TITLE = "FindSurface Omniverse v1.0.0"
SAMPLE_TARGET_MIN = 100
SAMPLE_TARGET_STEP = 100
FILE_DIALOG_IMPORT_POINTS = "import_points"
FILE_DIALOG_LOAD_WORKSPACE = "load_workspace"
FILE_DIALOG_SAVE_WORKSPACE = "save_workspace"
FILE_DIALOG_EXPORT_GEOMETRIES = "export_geometries"
FILE_DIALOG_DIRECTORY_KEYS = {
    FILE_DIALOG_IMPORT_POINTS,
    FILE_DIALOG_LOAD_WORKSPACE,
    FILE_DIALOG_SAVE_WORKSPACE,
    FILE_DIALOG_EXPORT_GEOMETRIES,
}
FILE_DIALOG_PRESET_DIRECTORY_DEFAULTS = {
    FILE_DIALOG_IMPORT_POINTS: ("data", "presets", "pointclouds"),
    FILE_DIALOG_LOAD_WORKSPACE: ("data", "presets", "workspaces"),
}
RELEASE_CONFIG_PATH = ("data", "release.json")


async def _destroy_window_after_update(window):
    try:
        await omni.kit.app.get_app().next_update_async()
        window.destroy()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        carb.log_warn(f"Deferred window destroy failed: {exc}")


def _live_extension(extension_ref):
    extension = extension_ref()
    if extension is None or getattr(extension, "_app_shutting_down", False):
        return None
    return extension


class _FallbackGeometryFrame:
    def __init__(self, title, collapsed=False, toggle_fn=None):
        self.title = title
        self.collapsed = bool(collapsed)
        self._toggle_fn = toggle_fn

    def __enter__(self):
        marker = "+" if self.collapsed else "-"
        ui.Button(
            f"{marker} {self.title}",
            height=FindSurfaceBootstrapExtension.GEOMETRY_HEADER_HEIGHT,
            clicked_fn=self._toggle_fn,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


async def _run_update_loop(extension_ref):
    while True:
        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        try:
            extension._update_once()
        finally:
            extension = None


async def _restore_window_layout_after_update(extension_ref, title):
    try:
        for _ in range(2):
            await omni.kit.app.get_app().next_update_async()
            extension = _live_extension(extension_ref)
            if extension is None:
                return
            extension = None

        extension = _live_extension(extension_ref)
        if extension is None or not extension._is_window_visible(title):
            return
        extension._restore_window_layout_state(title)
        extension._focus_window(extension._windows.get(title))
        extension = None
    except asyncio.CancelledError:
        raise
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            getattr(extension, "_pending_layout_restore_titles", set()).discard(title)
            extension._layout_restore_tasks = [
                task for task in getattr(extension, "_layout_restore_tasks", []) if not task.done()
            ]


async def _dock_windows_after_update(extension_ref):
    try:
        for _ in range(3):
            await omni.kit.app.get_app().next_update_async()
            extension = _live_extension(extension_ref)
            if extension is None:
                return
            extension = None

        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._dock_windows_now()
        extension = None

        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._hide_toolbar_tab_bars()
    except asyncio.CancelledError:
        raise
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            extension._dock_task = None
        extension = None


async def _refresh_geometries_window_after_update(extension_ref):
    try:
        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._refresh_geometries_window()
        extension = None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        carb.log_warn(f"Deferred Geometries window refresh failed: {exc}")
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            extension._geometry_refresh_task = None
        extension = None


async def _refresh_transactions_window_after_update(extension_ref):
    try:
        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._refresh_transactions_window()
        extension = None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        carb.log_warn(f"Deferred Transactions window refresh failed: {exc}")
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            extension._transactions_refresh_task = None
        extension = None


async def _refresh_findsurface_window_after_update(extension_ref):
    try:
        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._refresh_findsurface_window()
        extension = None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        carb.log_warn(f"Deferred FindSurface window refresh failed: {exc}")
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            extension._findsurface_refresh_task = None
        extension = None


async def _refresh_parameter_pad_row_after_update(extension_ref):
    try:
        await omni.kit.app.get_app().next_update_async()
        extension = _live_extension(extension_ref)
        if extension is None:
            return
        extension._refresh_parameter_pad_row()
        extension = None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        carb.log_warn(f"Deferred FindSurface 2D Pad refresh failed: {exc}")
    finally:
        extension = _live_extension(extension_ref)
        if extension is not None:
            extension._parameter_pad_refresh_task = None
        extension = None


class _ToolbarIconButton:
    def __init__(self, button, image, frame):
        self._button = button
        self._image = image
        self._frame = frame
        self._image_url = ""

    @property
    def enabled(self):
        return getattr(self._button, "enabled", True)

    @enabled.setter
    def enabled(self, value):
        value = bool(value)
        for widget in (self._button, self._image, self._frame):
            try:
                widget.enabled = value
            except Exception:
                pass

    @property
    def selected(self):
        return getattr(self._frame, "selected", False)

    @selected.setter
    def selected(self, value):
        value = bool(value)
        for widget in (self._button, self._frame):
            try:
                widget.selected = value
            except Exception:
                pass

    @property
    def checked(self):
        return getattr(self._frame, "checked", False)

    @checked.setter
    def checked(self, value):
        value = bool(value)
        for widget in (self._button, self._frame):
            try:
                widget.checked = value
            except Exception:
                pass

    @property
    def image_url(self):
        if self._image is None:
            return self._image_url
        return getattr(self._image, "source_url", getattr(self._image, "image_url", self._image_url))

    @image_url.setter
    def image_url(self, value):
        self._image_url = value or ""
        if self._image is None:
            return
        try:
            self._image.source_url = value
        except Exception:
            try:
                self._image.image_url = value
            except Exception:
                try:
                    self._image.url = value
                except Exception:
                    pass

    def release(self):
        for widget in (self._image, self._button, self._frame):
            if widget is None:
                continue
            try:
                widget.enabled = False
            except Exception:
                pass
            try:
                widget.selected = False
            except Exception:
                pass
            try:
                widget.checked = False
            except Exception:
                pass
            try:
                widget.source_url = ""
            except Exception:
                try:
                    widget.image_url = ""
                except Exception:
                    try:
                        widget.url = ""
                    except Exception:
                        pass
        self._image_url = ""
        self._button = None
        self._image = None
        self._frame = None

    @property
    def has_image(self):
        return self._image is not None

    def set_text(self, text):
        try:
            self._button.text = text
        except Exception:
            pass


class FindSurfaceBootstrapExtension(omni.ext.IExt):
    WINDOW_TOOLBAR = "Toolbar"
    WINDOW_STATUS_BAR = "Status Bar"
    WINDOW_VIEWPORT = "Viewport"
    WINDOW_FINDSURFACE = "FindSurface"
    WINDOW_SETTINGS = "Settings"
    WINDOW_CAMERA = "Camera"
    WINDOW_GEOMETRIES = "Geometries"
    WINDOW_TRANSACTIONS = "Transactions"
    WINDOW_TUTORIAL = "Tutorial Overlay"
    WINDOW_DEBUG_GROUP_BOX = "Debug Group Box"
    TOOLBAR_BUTTON_SIZE = 38
    TOOLBAR_TEXT_BUTTON_WIDTH = 56
    TOOLBAR_ICON_SIZE = 22
    TOOLBAR_LARGE_ICON_SIZE = 24
    TOOLBAR_VISIBILITY_ICON_SIZE = 28
    TOOLBAR_SEPARATOR_LENGTH = 24
    TOOLBAR_WINDOW_THICKNESS = 44
    RANGE_PARAMETER_MINIMUM = 1.0e-4
    RANGE_PARAMETER_MAXIMUM = 1.0e12
    RANGE_PARAMETER_VALUE_STEPS = 10
    RANGE_PARAMETER_MINIMUM_STEP = 0.0001
    RANGE_PARAMETER_FIELD_WIDTH = 76
    RANGE_PARAMETER_VALUE_LABEL_WIDTH = 124
    RANGE_PARAMETER_LABEL_WIDTH = 76
    RANGE_PARAMETER_LABEL_FONT_SIZE = 10
    RANGE_PARAMETER_GROUP_PADDING = 8
    PARAMETER_GROUP_BORDER_COLOR = 0xFFE6E6E6
    RANGE_PARAMETER_FORMAT = "%.4f"
    RANGE_PARAMETER_PRECISION = 4
    PARAMETER_PAD_SIZE = 156
    PARAMETER_PAD_HANDLE_SIZE = 12
    PARAMETER_PAD_CONTROL_WIDTH = 148
    PARAMETER_PAD_PARAMETERS = (
        "measurement_accuracy",
        "mean_distance",
        "seed_radius",
        "lateral_extension",
        "radial_expansion",
    )
    PARAMETER_PAD_INT_PARAMETERS = {"radial_expansion", "lateral_extension"}
    PARAMETER_PAD_DEFAULT_AXES = {"x": "mean_distance", "y": "measurement_accuracy"}
    HISTOGRAM_CHART_WIDTH = 300
    HISTOGRAM_CHART_HEIGHT = 70
    HISTOGRAM_BAR_MAX_HEIGHT = 42
    HISTOGRAM_BAR_SPACING = 2
    HISTOGRAM_PANEL_PADDING = 8
    HISTOGRAM_GRAPH_PADDING = 7
    HISTOGRAM_TOOLTIP_WIDTH = 190
    HISTOGRAM_TOOLTIP_HEIGHT = 42
    HISTOGRAM_TOOLTIP_MARGIN = 5
    HISTOGRAM_TOOLTIP_BACKGROUND_COLOR = [1.0, 1.0, 1.0, 0.88]
    HISTOGRAM_TOOLTIP_TEXT_COLOR = [0.04, 0.04, 0.04, 1.0]
    GEOMETRY_SECTION_PADDING = 6
    GEOMETRY_HEADER_HEIGHT = 24
    GEOMETRY_CONTENT_GAP = 4
    GEOMETRY_ICON_BUTTON_SIZE = 28
    GEOMETRY_ICON_SIZE = 20
    GEOMETRY_ITEM_ROW_SPACING = 4
    GEOMETRY_ITEM_BUTTON_ROW_HEIGHT = 28
    GEOMETRY_FIELD_ROW_HEIGHT = 20
    GEOMETRY_FIELD_LABEL_WIDTH = 104
    GEOMETRY_VECTOR_AXIS_WIDTH = 12
    GEOMETRY_VECTOR_VALUE_WIDTH = 48
    GEOMETRY_HISTOGRAM_COLLAPSED_HEIGHT = 164
    GEOMETRY_HISTOGRAM_EXPANDED_HEIGHT = 264
    TUTORIAL_SECTION_PADDING = 8
    TUTORIAL_SECTION_HORIZONTAL_PADDING = 12
    DEBUG_GROUP_BOX_STATUS_ROW_HEIGHT = 24
    TUTORIAL_SECTION_HEADER_HEIGHT = 22
    TUTORIAL_ROW_HEIGHT = 24
    TUTORIAL_LABEL_WIDTH = 88
    VIEWPORT_DEFAULT_WIDTH = 1200
    SIDE_PANEL_MIN_WIDTH = 348
    SIDE_PANEL_DEFAULT_WIDTH = SIDE_PANEL_MIN_WIDTH
    SIDE_PANEL_MEASURED_WIDTH_AT_DEFAULT_RATIO = 387
    SIDE_PANEL_DOCK_RATIO = (
        SIDE_PANEL_DEFAULT_WIDTH / VIEWPORT_DEFAULT_WIDTH
    ) * (SIDE_PANEL_DEFAULT_WIDTH / SIDE_PANEL_MEASURED_WIDTH_AT_DEFAULT_RATIO)
    RANGE_PARAMETER_DEFAULTS = {
        "measurement_accuracy": ("Measurement\nAccuracy", 0.003, 0.001, 0.05),
        "mean_distance": ("Mean\nDistance", 0.05, 0.01, 0.05),
        "seed_radius": ("Seed\nRadius", 0.15, 0.05, 0.50),
    }
    DETECTION_PARAMETER_NAMES = (
        "detection_type",
        "seed_radius",
        "measurement_accuracy",
        "mean_distance",
        "radial_expansion",
        "lateral_extension",
    )
    SETTINGS_BOOL_MODEL_NAMES = {
        "auto_detect",
        "pick_nearest_on_probe_miss",
        "sticky_auto_preview",
    }
    SETTINGS_INT_MODEL_NAMES = {
        "radial_expansion",
        "lateral_extension",
        "sticky_auto_preview_timeout_ms",
    }
    LENGTH_PARAMETER_KEYS = {
        "width",
        "height",
        "length",
        "radius",
        "bottom_radius",
        "top_radius",
        "major_radius",
        "mean_radius",
        "tube_radius",
    }

    def on_startup(self, ext_id):
        self._ext_id = ext_id
        self._register_usd_schema_plugin()
        self._app_config = self._load_app_config()
        self._apply_configured_defaults()
        self._recent_file_directories = self._load_recent_file_directories()
        self._loaded_path = None
        self._workspace_path = None
        self._dock_task = None
        self._update_task = None
        self._layout_restore_tasks = []
        self._geometry_refresh_task = None
        self._transactions_refresh_task = None
        self._findsurface_refresh_task = None
        self._parameter_pad_refresh_task = None
        self._file_dialog = None
        self._load_workspace_dialog = None
        self._save_workspace_dialog = None
        self._export_geometries_dialog = None
        self._export_options_dialog = None
        self._export_include_visualization_meshes = False
        self._load_error_dialog = None
        self._point_limit_dialog = None
        self._unsaved_changes_dialog = None
        self._geometry_action_dialog = None
        self._native_sdk_dialog = None
        self._native_sdk_dialog_shown = False
        self._pending_oversized_import_path = None
        self._pending_oversized_import_error = None
        self._sample_target_model = None
        self._import_lock = Lock()
        self._import_busy = False
        self._import_request_token = 0
        self._import_cancel_token = None
        self._import_pending = None
        self._import_progress = None
        self._import_progress_dialog = None
        self._import_progress_label = None
        self._last_import_progress_text = None
        self._deferred_destroy_tasks = []
        self._is_dirty = False
        self._content_dirty = False
        self._display_camera_dirty = False
        self._saved_display_camera_settings = None
        self._pending_unsaved_action = None
        self._save_dialog_continue_after = None
        self._allow_shutdown_once = False
        self._app_shutting_down = False
        self._shutdown_observers = []
        self._runtime_resources_released = False
        self._status_label = None
        self._status_message = "No data loaded"
        self._dataset_label = None
        self._dataset_name = "None"
        self._point_count_label = None
        self._dirty_label = None
        self._save_button = None
        self._export_button = None
        self._active_count_label = None
        self._hover_index_label = None
        self._selected_index_label = None
        self._capture_button = None
        self._toolbar_capture_button = None
        self._tutorial_button = None
        self._result_label = None
        self._geometries_summary_label = None
        self._transaction_summary_label = None
        self._undo_button = None
        self._redo_button = None
        self._toolbar_undo_button = None
        self._geometry_collapsed = {}
        self._geometry_histogram_bin_counts = {}
        self._geometry_histogram_cache_result = None
        self._geometry_histogram_cache_key = None
        self._geometry_histogram_cache_value = None
        self._geometry_histogram_details_expanded = {}
        self._hovered_histogram_bin = None
        self._hovered_histogram_bin_key = None
        self._hovered_histogram_result_id = None
        self._hovered_histogram_display_index = 0
        self._hovered_histogram_display_count = 0
        self._hovered_histogram_mouse_x = None
        self._hovered_histogram_mouse_y = None
        self._histogram_hit_regions = []
        self._histogram_status_regions = []
        self._histogram_status_labels = {}
        self._histogram_status_key = None
        self._hovered_geometry_id = None
        self._geometries_scrolling_frame = None
        self._geometries_scroll_y = 0.0
        self._geometries_last_scroll_y = None
        self._geometries_scroll_drag_active = False
        self._geometries_scroll_interaction_until = 0.0
        self._toolbar_inspect_button = None
        self._toolbar_detection_buttons = {}
        self._toolbar_projection_buttons = {}
        self._visibility_buttons = {}
        self._toolbar_axis = self._toolbar_axis_x()
        self._viewport_tab_bar_hidden_by_default = False
        self._state = None
        self._hover_index = None
        self._selected_index = None
        self._detection_type = self._configured_detection_type()
        self._detection_paused = False
        self._auto_detect_result = None
        self._auto_detect_source = None
        self._last_successful_auto_detect_result = None
        self._last_successful_auto_detect_key = None
        self._retroactive_pick_index = None
        self._auto_detect_lock = Lock()
        self._auto_detect_busy = False
        self._auto_detect_pending = None
        self._auto_detect_deferred = None
        self._auto_detect_key = None
        self._auto_detect_request_token = 0
        self._auto_detect_display_deadline = None
        self._auto_detect_overlay_suppressed = False
        self._auto_detect_disabled_reason = None
        self._models = {}
        self._range_edit_models = {}
        self._range_edit_dirty = set()
        self._range_sliders = {}
        self._model_subscription_keys = set()
        self._parameter_pad_rects = {}
        self._parameter_pad_positions = {}
        self._parameter_pad_handle_spacers = {}
        self._parameter_pad_frame = None
        self._parameter_pad_value_labels = {}
        self._parameter_pad_axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
        self._parameter_pad_axis_models = {}
        self._parameter_pad_axis_options = {}
        self._syncing_parameter_pad_axis_models = set()
        self._active_parameter_pad = None
        self._model_subscriptions = []
        self._syncing_models = False
        self._last_parameter_transaction_state = None
        self._suppress_parameter_transaction = False
        self._pending_camera_transaction_state = None
        self._suppress_camera_transaction = False
        self._pending_parameter_name = None
        self._pending_parameter_state_before = None
        self._pending_parameter_state_after = None
        self._pending_parameter_stable_updates = 0
        self._parameter_control_active = False
        self._range_parameters_commit_on_change = set()

        self._windows = {}
        self._menu_items = {}
        self._registered_actions = []
        self._window_visibility_changed_callback_id = None
        self._window_layout_state = {}
        self._pending_layout_restore_titles = set()
        self._keyboard = None
        self._keyboard_input = None
        self._keyboard_subscription = None
        self._provider = None
        self._viewport = None

        if self._diagnostic_skip_viewport():
            carb.log_warn("FindSurface diagnostic mode: skipping viewport and UI construction.")
            return

        self._provider = self._create_provider()
        self._viewport = PointCloudViewport(
            on_camera_changed=self._on_camera_changed,
            on_hover_changed=self._on_hover_changed,
            on_seed_selected=self._on_seed_selected,
            input_blocked_fn=self._is_viewport_input_blocked,
            config=self._config(),
        )

        self._register_shutdown_guard()
        self._register_actions()
        self._register_shortcuts()
        self._build_menus()
        self._build_windows()
        self._show_native_sdk_unavailable_dialog_if_needed()
        extension_ref = weakref.ref(self)
        self._dock_task = asyncio.ensure_future(_dock_windows_after_update(extension_ref))
        self._update_task = asyncio.ensure_future(_run_update_loop(extension_ref))

    def _register_usd_schema_plugin(self):
        try:
            if usd_schema.register_schema_plugin():
                carb.log_info("Registered FindSurface USD schema plugin.")
            else:
                carb.log_warn("FindSurface USD schema plugin was not registered; exports will keep fallback attributes.")
        except Exception as exc:
            carb.log_warn(f"FindSurface USD schema plugin registration failed: {exc}")

    def _load_app_config(self):
        config_path = None
        try:
            settings = carb.settings.get_settings()
            if hasattr(settings, "get"):
                config_path = settings.get("/findsurface/config/defaultsPath")
        except Exception:
            config_path = None
        try:
            config, path, created = app_config.load_app_config(config_path)
            self._app_config_path = path
            if created:
                carb.log_info(f"Created FindSurface app defaults file: {path}")
            return config
        except Exception as exc:
            carb.log_warn(f"Using built-in FindSurface app defaults: {exc}")
            return app_config.DEFAULT_APP_CONFIG

    def _apply_configured_defaults(self):
        self.RANGE_PARAMETER_DEFAULTS = app_config.range_parameter_defaults(
            self._config(),
            self.RANGE_PARAMETER_DEFAULTS,
            slider_steps=self.RANGE_PARAMETER_VALUE_STEPS,
            minimum_step=self.RANGE_PARAMETER_MINIMUM_STEP,
        )
        self.PARAMETER_PAD_DEFAULT_AXES = app_config.parameter_pad_default_axes(
            self._config(),
            self.PARAMETER_PAD_DEFAULT_AXES,
            self.PARAMETER_PAD_PARAMETERS,
        )

    def _configured_detection_type(self):
        detection_type = app_config.config_value(self._config(), ("detection", "detection_type"), "Auto")
        return detection_type if detection_type in DETECTION_TYPES else "Auto"

    def _config(self):
        return getattr(self, "_app_config", app_config.DEFAULT_APP_CONFIG)

    def _load_recent_file_directories(self):
        configured = app_config.config_value(self._config(), ("recent_file_directories",), {})
        if not isinstance(configured, dict):
            return {}
        directories = {}
        for key in FILE_DIALOG_DIRECTORY_KEYS:
            directory = self._resolve_extension_relative_directory(configured.get(key))
            if directory:
                directories[key] = directory
        return directories

    def _file_dialog_directory_kwargs(self, key):
        directory = self._recent_file_directory(key)
        return {"current_directory": directory} if directory else {}

    def _apply_file_dialog_directory(self, dialog, key):
        directory = self._recent_file_directory(key)
        if not directory or not dialog:
            return
        setter = getattr(dialog, "set_current_directory", None)
        if not callable(setter):
            return
        try:
            setter(directory)
        except Exception as exc:
            carb.log_warn(f"Failed to restore recent file dialog directory '{directory}': {exc}")

    def _recent_file_directory(self, key):
        directories = getattr(self, "_recent_file_directories", None)
        if not isinstance(directories, dict):
            directories = self._load_recent_file_directories()
            self._recent_file_directories = directories
        return directories.get(key) or self._preset_file_directory(key)

    def _preset_file_directory(self, key):
        defaults = FILE_DIALOG_PRESET_DIRECTORY_DEFAULTS.get(key)
        configured = app_config.config_value(self._config(), ("preset_file_directories", key), None)
        if configured:
            directory = self._resolve_extension_relative_directory(configured)
        elif defaults:
            directory = os.path.join(self._extension_root(), *defaults)
        else:
            return None
        return self._normalize_picker_directory(directory)

    def _resolve_extension_relative_directory(self, path):
        path = self._normalize_picker_directory(path)
        if not path or "://" in path or os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self._extension_root(), path))

    def _extension_root(self):
        return os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def _remember_file_dialog_directory(self, key, full_path):
        if key not in FILE_DIALOG_DIRECTORY_KEYS:
            return
        directory = self._directory_from_picker_path(full_path)
        if not directory:
            return
        directories = getattr(self, "_recent_file_directories", None)
        if not isinstance(directories, dict):
            directories = {}
            self._recent_file_directories = directories
        if directories.get(key) == directory:
            return
        directories[key] = directory
        config = getattr(self, "_app_config", None)
        if getattr(self, "_app_config_path", None) and isinstance(config, dict):
            config_directory = self._portable_picker_directory_config_value(directory)
            if config_directory is None:
                return
            recent = config.get("recent_file_directories")
            if not isinstance(recent, dict):
                recent = {}
                config["recent_file_directories"] = recent
            recent[key] = config_directory
            self._write_app_config()

    def _portable_picker_directory_config_value(self, directory):
        directory = self._normalize_picker_directory(directory)
        if not directory:
            return None
        if "://" in directory:
            return directory
        try:
            directory_abs = os.path.abspath(directory)
            root_abs = os.path.abspath(self._extension_root())
            if os.path.commonpath([directory_abs, root_abs]) != root_abs:
                return None
            relative = os.path.relpath(directory_abs, root_abs)
        except (OSError, ValueError):
            return None
        if relative == ".":
            return "."
        return os.path.normpath(relative).replace(os.sep, "/")

    def _write_app_config(self):
        config_path = getattr(self, "_app_config_path", None)
        config = getattr(self, "_app_config", None)
        if not config_path or not isinstance(config, dict):
            return
        try:
            app_config.write_app_config(config_path, config)
        except Exception as exc:
            carb.log_warn(f"Failed to save FindSurface app defaults: {exc}")

    def _directory_from_picker_path(self, path):
        path = self._normalize_picker_directory(path)
        if not path:
            return None
        if "://" in path:
            stripped = path.rstrip("/")
            root_end = stripped.find("://") + len("://")
            if len(stripped) <= root_end or "/" not in stripped[root_end:]:
                return path
            index = stripped.rfind("/")
            return stripped[:index] if index > root_end else stripped
        return os.path.dirname(path)

    def _normalize_picker_directory(self, path):
        if not isinstance(path, str):
            return None
        path = path.strip()
        if not path:
            return None
        if "://" in path:
            return path
        return os.path.normpath(path)

    def _diagnostic_skip_viewport(self):
        try:
            return bool(carb.settings.get_settings().get_as_bool("/findsurface/diagnostics/skipViewport"))
        except Exception:
            return False

    def _diagnostic_text_toolbar(self):
        try:
            return bool(carb.settings.get_settings().get_as_bool("/findsurface/diagnostics/textToolbar"))
        except Exception:
            return False

    def _diagnostic_group_box_window(self):
        try:
            return bool(carb.settings.get_settings().get_as_bool("/findsurface/diagnostics/groupBoxWindow"))
        except Exception:
            return False

    def _use_toolbar_image_icons(self):
        try:
            settings = carb.settings.get_settings()
            if hasattr(settings, "get"):
                configured = settings.get("/findsurface/toolbar/useImageIcons")
                if configured is None:
                    return True
            return bool(settings.get_as_bool("/findsurface/toolbar/useImageIcons"))
        except Exception:
            return True

    def on_shutdown(self):
        self._app_shutting_down = True

        for observer in self._shutdown_observers:
            observer.reset()
        self._shutdown_observers.clear()

        for task in self._deferred_destroy_tasks:
            task.cancel()
        self._deferred_destroy_tasks.clear()

        if self._update_task:
            self._update_task.cancel()
            self._update_task = None
        if self._dock_task:
            self._dock_task.cancel()
            self._dock_task = None
        for task in getattr(self, "_layout_restore_tasks", []):
            task.cancel()
        self._layout_restore_tasks = []
        self._pending_layout_restore_titles = set()
        if self._geometry_refresh_task:
            self._geometry_refresh_task.cancel()
            self._geometry_refresh_task = None
        if self._transactions_refresh_task:
            self._transactions_refresh_task.cancel()
            self._transactions_refresh_task = None
        if self._findsurface_refresh_task:
            self._findsurface_refresh_task.cancel()
            self._findsurface_refresh_task = None
        if self._parameter_pad_refresh_task:
            self._parameter_pad_refresh_task.cancel()
            self._parameter_pad_refresh_task = None

        self._unregister_shortcuts()
        self._unregister_actions()
        self._clear_model_subscriptions()
        self._clear_workspace_window_callbacks()
        self._release_toolbar_button_widgets()
        self._release_runtime_resources_for_shutdown()
        self._clear_all_window_frames()

        if self._file_dialog:
            self._file_dialog.destroy()
        self._file_dialog = None
        if self._load_workspace_dialog:
            self._load_workspace_dialog.destroy()
        self._load_workspace_dialog = None
        if self._save_workspace_dialog:
            self._save_workspace_dialog.destroy()
        self._save_workspace_dialog = None
        if self._export_geometries_dialog:
            self._export_geometries_dialog.destroy()
        self._export_geometries_dialog = None
        if self._export_options_dialog:
            self._export_options_dialog.destroy()
        self._export_options_dialog = None
        if self._load_error_dialog:
            self._load_error_dialog.destroy()
        self._load_error_dialog = None
        if self._point_limit_dialog:
            self._point_limit_dialog.destroy()
        self._point_limit_dialog = None
        if self._import_progress_dialog:
            self._import_progress_dialog.destroy()
        self._import_progress_dialog = None
        if self._unsaved_changes_dialog:
            self._unsaved_changes_dialog.destroy()
        self._unsaved_changes_dialog = None
        if self._geometry_action_dialog:
            self._geometry_action_dialog.destroy()
        self._geometry_action_dialog = None
        if self._native_sdk_dialog:
            self._native_sdk_dialog.destroy()
        self._native_sdk_dialog = None
        self._cancel_active_import(status=False)
        self._pending_oversized_import_path = None
        self._pending_oversized_import_error = None
        self._sample_target_model = None
        self._pending_unsaved_action = None
        self._save_dialog_continue_after = None
        self._workspace_path = None
        self._is_dirty = False
        self._content_dirty = False
        self._display_camera_dirty = False
        self._saved_display_camera_settings = None
        self._allow_shutdown_once = False

        self._state = None
        self._hover_index = None
        self._selected_index = None
        self._hovered_geometry_id = None
        self._auto_detect_result = None
        self._auto_detect_source = None
        self._retroactive_pick_index = None
        self._auto_detect_display_deadline = None
        self._auto_detect_overlay_suppressed = False
        self._invalidate_auto_detect_requests()

        self._destroy_runtime_resources_for_shutdown(clear_scene=True)

        for title, window in self._windows.items():
            try:
                window.destroy()
            except Exception as exc:
                carb.log_warn(f"FindSurface window destroy failed for {title}: {exc}")
        self._windows.clear()
        self._clear_ui_references()
        self._viewport = None
        self._provider = None
        self._models.clear()
        self._range_edit_models.clear()
        self._range_edit_dirty.clear()
        self._range_sliders.clear()
        self._model_subscription_keys.clear()
        self._parameter_pad_rects.clear()
        self._parameter_pad_positions.clear()
        self._parameter_pad_handle_spacers.clear()
        self._parameter_pad_frame = None
        self._parameter_pad_value_labels.clear()
        self._parameter_pad_axis_models.clear()
        self._parameter_pad_axis_options.clear()
        self._syncing_parameter_pad_axis_models.clear()
        self._active_parameter_pad = None

    def _unregister_actions(self):
        for menu_name, menu_items in self._menu_items.items():
            omni.kit.menu.utils.remove_menu_items(menu_items, menu_name)
        self._menu_items.clear()

        registry = omni.kit.actions.core.get_action_registry()
        for action_id in self._registered_actions:
            registry.deregister_action(self._ext_id, action_id)
        self._registered_actions.clear()

    def _clear_workspace_window_callbacks(self):
        workspace = getattr(ui, "Workspace", None)
        callback_id = getattr(self, "_window_visibility_changed_callback_id", None)
        if callback_id:
            remove_callback = getattr(workspace, "remove_window_visibility_changed_callback", None)
            if callable(remove_callback):
                try:
                    remove_callback(callback_id)
                except Exception as exc:
                    carb.log_warn(f"FindSurface workspace visibility callback cleanup failed: {exc}")
        self._window_visibility_changed_callback_id = None

        for title in list(getattr(self, "_windows", {}).keys()):
            try:
                ui.Workspace.set_show_window_fn(title, None)
            except Exception as exc:
                carb.log_warn(f"FindSurface workspace callback cleanup failed for {title}: {exc}")

    def _clear_all_window_frames(self):
        for title, window in self._windows.items():
            try:
                self._clear_window_frame(window)
            except Exception as exc:
                carb.log_warn(f"FindSurface window cleanup failed for {title}: {exc}")

    def _create_provider(self):
        try:
            provider = FindSurfaceDetector()
            self._auto_detect_disabled_reason = None
            return provider
        except FileNotFoundError as exc:
            self._auto_detect_disabled_reason = self._native_unavailable_status(exc)
            carb.log_warn(f"Native FindSurface provider unavailable: {exc}")
            return None
        except OSError as exc:
            self._auto_detect_disabled_reason = self._native_unavailable_status(exc)
            carb.log_warn(f"Native FindSurface provider unavailable: {exc}")
            return None
        except Exception as exc:
            self._auto_detect_disabled_reason = self._native_unavailable_status(exc)
            carb.log_warn(f"Native FindSurface provider unavailable: {exc}")
            return None

    def _show_native_sdk_unavailable_dialog_if_needed(self):
        if self._provider is not None or self._native_sdk_dialog_shown:
            return
        reason = self._auto_detect_disabled_reason or "native SDK library is unavailable"
        self._native_sdk_dialog_shown = True
        self._native_sdk_dialog = ui.Window("FindSurface SDK Library Missing", width=620, height=260)
        with self._native_sdk_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label(
                    "FindSurface cannot run detection because the native SDK library is missing or could not be loaded.",
                    word_wrap=True,
                )
                ui.Label(
                    "Download the matching FindSurface.dll or libFindSurface.so manually and place it in the documented native SDK folder.",
                    word_wrap=True,
                )
                ui.Label(f"Reason: {reason}", word_wrap=True)
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button("Open setup guide", width=150, clicked_fn=self._open_native_sdk_setup_guide)
                    ui.Button("OK", width=90, clicked_fn=self._close_native_sdk_dialog)
                    ui.Spacer(width=8)
        self._set_status(f"Native FindSurface unavailable: {reason}")

    def _open_native_sdk_setup_guide(self):
        url = self._native_sdk_setup_guide_url()
        if not url:
            carb.log_warn("Native SDK setup guide URL is not configured.")
            return
        try:
            if not webbrowser.open(url):
                carb.log_warn(f"Could not open native SDK setup guide: {url}")
        except Exception as exc:
            carb.log_warn(f"Could not open native SDK setup guide: {exc}")

    def _native_sdk_setup_guide_url(self):
        config = self._release_config()
        value = config.get("native_sdk_setup_guide_url") if isinstance(config, dict) else None
        return str(value).strip() if value else None

    def _release_config(self):
        path = os.path.join(self._extension_root(), *RELEASE_CONFIG_PATH)
        try:
            with open(path, "r", encoding="utf-8") as stream:
                config = json.load(stream)
        except OSError as exc:
            carb.log_warn(f"FindSurface release config could not be read: {exc}")
            return {}
        except json.JSONDecodeError as exc:
            carb.log_warn(f"FindSurface release config is invalid JSON: {exc}")
            return {}
        return config if isinstance(config, dict) else {}

    def _close_native_sdk_dialog(self):
        if self._native_sdk_dialog:
            self._defer_window_destroy(self._native_sdk_dialog)
            self._native_sdk_dialog = None

    def _native_unavailable_status(self, error):
        text = str(error or "")
        if isinstance(error, FileNotFoundError):
            return f"missing DLL ({text})"
        if isinstance(error, OSError):
            return f"SDK load failure ({text})"
        if "Unsupported FindSurface SDK platform" in text:
            return f"unsupported platform ({text})"
        return f"runtime detection failure ({text})" if text else "runtime detection failure"

    def _set_retroactive_pick_index(self, index):
        index = index if index is not None and self._is_active_index(index) else None
        self._retroactive_pick_index = index
        if index is None:
            self._last_successful_auto_detect_result = None
            self._last_successful_auto_detect_key = None
        viewport = getattr(self, "_viewport", None)
        if viewport and hasattr(viewport, "set_retroactive_pick_index"):
            viewport.set_retroactive_pick_index(index)

    def _set_retroactive_pick_active(self, active):
        viewport = getattr(self, "_viewport", None)
        if viewport and hasattr(viewport, "set_retroactive_pick_active"):
            viewport.set_retroactive_pick_active(active)

    def _register_shutdown_guard(self):
        if not get_eventdispatcher:
            return
        dispatcher = get_eventdispatcher()
        self._shutdown_observers.append(
            dispatcher.observe_event(
                event_name=omni.kit.app.GLOBAL_EVENT_POST_QUIT,
                on_event=self._on_post_quit,
                observer_name="FindSurface unsaved changes guard",
                order=-100,
            )
        )
        self._shutdown_observers.append(
            dispatcher.observe_event(
                event_name=omni.kit.app.GLOBAL_EVENT_PRE_SHUTDOWN,
                on_event=self._on_pre_shutdown,
                observer_name="FindSurface scene cleanup",
                order=-100,
            )
        )

    def _on_post_quit(self, event):
        if self._allow_shutdown_once or not self._is_dirty:
            self._app_shutting_down = True
            self._release_runtime_resources_for_shutdown()
            return
        canceled = False
        try:
            canceled = omni.kit.app.get_app().try_cancel_shutdown("FindSurface has unsaved changes.")
        except Exception as exc:
            carb.log_warn(f"Failed to cancel shutdown for unsaved changes: {exc}")
        if not canceled:
            self._app_shutting_down = True
            self._release_runtime_resources_for_shutdown()
            return
        try:
            event.consume()
        except Exception:
            pass
        self._show_unsaved_changes_dialog("exit FindSurface", self._discard_and_quit)

    def _on_pre_shutdown(self, event):
        self._app_shutting_down = True
        self._release_runtime_resources_for_shutdown()

    def _discard_and_quit(self):
        self._allow_shutdown_once = True
        self._app_shutting_down = True
        self._clear_dirty_tracking()
        self._release_runtime_resources_for_shutdown()
        omni.kit.app.get_app().post_quit(0)

    def _release_runtime_resources_for_shutdown(self):
        if self._runtime_resources_released:
            return
        self._runtime_resources_released = True
        if self._viewport:
            if hasattr(self._viewport, "release_scene_resources"):
                self._viewport.release_scene_resources(clear_scene=True)
            else:
                self._viewport.clear()
        self._state = None
        self._hover_index = None
        self._selected_index = None
        self._auto_detect_result = None
        self._auto_detect_source = None
        self._retroactive_pick_index = None
        self._auto_detect_deferred = None

    def _destroy_runtime_resources_for_shutdown(self, clear_scene=True):
        if self._viewport:
            self._viewport.destroy(clear_scene=clear_scene)

    def _clear_model_subscriptions(self):
        for subscription in self._model_subscriptions:
            try:
                if hasattr(subscription, "unsubscribe"):
                    subscription.unsubscribe()
                elif hasattr(subscription, "reset"):
                    subscription.reset()
            except Exception as exc:
                carb.log_warn(f"FindSurface model subscription cleanup failed: {exc}")
        self._model_subscriptions.clear()
        self._model_subscription_keys.clear()

    def _clear_ui_references(self, release_widgets=True):
        if release_widgets:
            self._release_toolbar_button_widgets()
        for name in (
            "_status_label",
            "_dataset_label",
            "_point_count_label",
            "_dirty_label",
            "_save_button",
            "_active_count_label",
            "_hover_index_label",
            "_selected_index_label",
            "_capture_button",
            "_toolbar_capture_button",
            "_toolbar_inspect_button",
            "_tutorial_button",
            "_result_label",
            "_geometries_summary_label",
            "_transaction_summary_label",
            "_undo_button",
            "_redo_button",
            "_toolbar_undo_button",
            "_projection_label",
        ):
            if hasattr(self, name):
                setattr(self, name, None)
        for name in (
            "_toolbar_detection_buttons",
            "_toolbar_projection_buttons",
            "_visibility_buttons",
            "_geometry_collapsed",
            "_geometry_histogram_bin_counts",
            "_geometry_histogram_details_expanded",
            "_histogram_hit_regions",
            "_histogram_status_regions",
            "_histogram_status_labels",
            "_parameter_pad_rects",
            "_parameter_pad_positions",
            "_parameter_pad_handle_spacers",
            "_parameter_pad_value_labels",
            "_parameter_pad_axis_models",
            "_parameter_pad_axis_options",
        ):
            value = getattr(self, name, None)
            if hasattr(value, "clear"):
                value.clear()
        self._active_parameter_pad = None
        self._parameter_pad_frame = None
        self._histogram_status_key = None

    def _release_toolbar_button_widgets(self):
        candidates = [
            getattr(self, "_save_button", None),
            getattr(self, "_capture_button", None),
            getattr(self, "_toolbar_capture_button", None),
            getattr(self, "_toolbar_inspect_button", None),
            getattr(self, "_tutorial_button", None),
            getattr(self, "_undo_button", None),
            getattr(self, "_redo_button", None),
            getattr(self, "_toolbar_undo_button", None),
        ]
        for mapping_name in ("_toolbar_detection_buttons", "_toolbar_projection_buttons", "_visibility_buttons"):
            mapping = getattr(self, mapping_name, None)
            if hasattr(mapping, "values"):
                candidates.extend(mapping.values())
        seen = set()
        for widget in candidates:
            if widget is None:
                continue
            identity = id(widget)
            if identity in seen:
                continue
            seen.add(identity)
            release = getattr(widget, "release", None)
            if callable(release):
                try:
                    release()
                except Exception:
                    pass

    def _clear_window_frame(self, window):
        try:
            window.visible = False
        except Exception:
            pass
        frame = getattr(window, "frame", None)
        if not frame:
            return
        try:
            if hasattr(frame, "set_build_fn"):
                frame.set_build_fn(None)
        except Exception:
            pass
        try:
            if hasattr(frame, "clear"):
                frame.clear()
        except Exception:
            pass
        try:
            with frame:
                ui.Spacer(width=1, height=1)
        except Exception:
            pass

    def _should_poll_hover_pick(self):
        return not self._is_modal_or_overlay_visible()

    def _is_viewport_input_blocked(self, x=None, y=None):
        return self._is_modal_or_overlay_visible()

    def _is_modal_or_overlay_visible(self):
        if self._is_file_dialog_visible():
            return True
        if self._is_window_visible(self.WINDOW_TUTORIAL):
            return True
        for name in (
            "_unsaved_changes_dialog",
            "_export_options_dialog",
            "_load_error_dialog",
            "_point_limit_dialog",
            "_import_progress_dialog",
            "_geometry_action_dialog",
            "_native_sdk_dialog",
        ):
            if self._dialog_is_visible(getattr(self, name, None)):
                return True
        return False

    def _current_mouse_position(self):
        viewport = getattr(self, "_viewport", None)
        poll_mouse = getattr(viewport, "_poll_mouse_position", None)
        if not callable(poll_mouse):
            return None
        try:
            x, y = poll_mouse()
        except Exception:
            return None
        if x is None or y is None:
            return None
        return float(x), float(y)

    def _is_point_over_blocking_window(self, x, y):
        for title, window in getattr(self, "_windows", {}).items():
            if title == self.WINDOW_VIEWPORT or not self._dialog_is_visible(window):
                continue
            if self._window_contains_screen_point(window, x, y):
                return True
        return False

    def _window_contains_screen_point(self, window, x, y):
        for source in (getattr(window, "frame", None), window):
            rect = self._screen_rect(source)
            if rect is None:
                continue
            left, top, width, height = rect
            if left <= float(x) < left + width and top <= float(y) < top + height:
                return True
        return False

    def _screen_rect(self, widget):
        if widget is None:
            return None
        left = self._first_numeric_attr(widget, ("screen_position_x", "position_x", "x"))
        top = self._first_numeric_attr(widget, ("screen_position_y", "position_y", "y"))
        width = self._first_numeric_attr(widget, ("computed_width", "width"))
        height = self._first_numeric_attr(widget, ("computed_height", "height"))
        if left is None or top is None or width is None or height is None:
            return None
        width = max(0.0, float(width))
        height = max(0.0, float(height))
        if width <= 0.0 or height <= 0.0:
            return None
        return float(left), float(top), width, height

    def _first_numeric_attr(self, obj, names):
        for name in names:
            try:
                value = getattr(obj, name)
            except Exception:
                continue
            numeric = self._numeric_ui_value(value)
            if numeric is not None:
                return numeric
        self._queue_geometries_window_refresh()

    def _numeric_ui_value(self, value):
        if callable(value):
            try:
                value = value()
            except Exception:
                return None
        for name in ("as_float", "as_int"):
            try:
                attribute = getattr(value, name)
            except Exception:
                continue
            if callable(attribute):
                try:
                    return float(attribute())
                except Exception:
                    continue
            try:
                return float(attribute)
            except Exception:
                continue
        try:
            return float(value)
        except Exception:
            return None

    def _is_file_dialog_visible(self):
        for name in (
            "_file_dialog",
            "_load_workspace_dialog",
            "_save_workspace_dialog",
            "_export_geometries_dialog",
        ):
            if self._dialog_is_visible(getattr(self, name, None)):
                return True
        return False

    def _dialog_is_visible(self, dialog):
        if dialog is None:
            return False
        try:
            dialog_window = getattr(dialog, "_window", None)
        except Exception:
            dialog_window = None
        for source in (dialog, dialog_window):
            if self._dialog_source_is_visible(source):
                return True
        return False

    def _dialog_source_is_visible(self, source):
        if source is None:
            return False
        for name in ("visible", "shown"):
            try:
                if bool(getattr(source, name)):
                    return True
            except Exception:
                pass
        for name in ("is_visible", "get_visible"):
            method = getattr(source, name, None)
            if callable(method):
                try:
                    if bool(method()):
                        return True
                except Exception:
                    pass
        return False

    def _clear_viewport_hover_pick(self):
        viewport = getattr(self, "_viewport", None)
        if not viewport:
            return
        set_scale_hovered = getattr(viewport, "_set_scale_ruler_hovered", None)
        if callable(set_scale_hovered):
            set_scale_hovered(False)
        set_orientation_axis = getattr(viewport, "_set_orientation_hover_axis", None)
        if callable(set_orientation_axis):
            set_orientation_axis(None)
        clear_hover = getattr(viewport, "_clear_hover_pick", None)
        if callable(clear_hover):
            clear_hover()
            return
        if self._hover_index is not None:
            self._on_hover_changed(None)

    def _sync_viewport_picking_enabled(self, enabled):
        viewport = getattr(self, "_viewport", None)
        if not viewport:
            return
        set_picking_enabled = getattr(viewport, "set_picking_enabled", None)
        if not callable(set_picking_enabled):
            return
        enabled = bool(enabled)
        try:
            current = getattr(viewport, "picking_enabled")
        except Exception:
            current = None
        if current is not None and bool(current) == enabled:
            return
        set_picking_enabled(enabled)

    def _update_once(self):
        if not self._viewport:
            return
        self._sync_parameter_transaction_from_models()
        self._poll_histogram_status()
        self._apply_import_progress()
        self._apply_import_pending()
        viewport_blocked = self._is_modal_or_overlay_visible()
        detection_paused = self._is_detection_paused()
        self._sync_viewport_picking_enabled(not viewport_blocked and not detection_paused)
        if not viewport_blocked and not detection_paused:
            self._viewport.poll_hover_pick()
        else:
            self._clear_viewport_hover_pick()
        self._apply_auto_detect_pending()
        self._expire_auto_detect_preview()
        self._capture_window_layout_state()

    def _register_actions(self):
        registry = omni.kit.actions.core.get_action_registry()
        actions = {
            "load_workspace": (self._show_load_workspace_dialog, "Load"),
            "save_workspace": (self._save_workspace, "Save"),
            "save_workspace_as": (self._show_save_workspace_dialog, "Save As"),
            "import_points": (self._show_import_points_dialog, "Import Points"),
            "export_geometries": (self._show_export_geometries_dialog, "Export Geometries"),
            "close": (self._request_close_dataset, "Close"),
            "undo": (self._undo_last, "Undo"),
            "redo": (self._redo_last, "Redo"),
            "reset_detection": (self._reset_detection, "Reset"),
            "toggle_toolbar": (lambda: self._toggle_window(self.WINDOW_TOOLBAR), "Toggle Toolbar"),
            "toggle_status_bar": (lambda: self._toggle_window(self.WINDOW_STATUS_BAR), "Toggle Status Bar"),
            "toggle_viewport": (lambda: self._toggle_window(self.WINDOW_VIEWPORT), "Toggle Viewport"),
            "toggle_findsurface": (lambda: self._toggle_window(self.WINDOW_FINDSURFACE), "Toggle FindSurface"),
            "toggle_settings": (lambda: self._toggle_window(self.WINDOW_SETTINGS), "Toggle Settings"),
            "toggle_camera": (lambda: self._toggle_window(self.WINDOW_CAMERA), "Toggle Camera"),
            "toggle_geometries": (lambda: self._toggle_window(self.WINDOW_GEOMETRIES), "Toggle Geometries"),
            "toggle_transactions": (lambda: self._toggle_window(self.WINDOW_TRANSACTIONS), "Toggle Transactions"),
            "show_tutorial": (self._show_tutorial_overlay, "Show Tutorial Overlay"),
            "toggle_tutorial": (lambda: self._toggle_window(self.WINDOW_TUTORIAL), "Toggle Tutorial Overlay"),
        }
        if self._diagnostic_group_box_window():
            actions["toggle_debug_group_box"] = (
                lambda: self._toggle_window(self.WINDOW_DEBUG_GROUP_BOX),
                "Toggle Debug Group Box",
            )

        for action_id, (callback, display_name) in actions.items():
            registry.register_action(
                self._ext_id,
                action_id,
                callback,
                display_name=display_name,
                description=display_name,
                tag="FindSurface",
            )
            self._registered_actions.append(action_id)

    def _register_shortcuts(self):
        try:
            import omni.appwindow

            app_window = omni.appwindow.get_default_app_window()
            self._keyboard_input = carb.input.acquire_input_interface()
            self._keyboard = app_window.get_keyboard() if app_window else None
            if not self._keyboard_input or not self._keyboard:
                return
            self._keyboard_subscription = self._keyboard_input.subscribe_to_keyboard_events(
                self._keyboard,
                self._on_keyboard_event,
            )
        except Exception as exc:
            self._keyboard = None
            self._keyboard_input = None
            self._keyboard_subscription = None
            carb.log_warn(f"FindSurface shortcuts unavailable: {exc}")

    def _unregister_shortcuts(self):
        if self._keyboard_subscription is None:
            return
        subscription = self._keyboard_subscription
        self._keyboard_subscription = None
        try:
            if hasattr(subscription, "unsubscribe"):
                subscription.unsubscribe()
            elif hasattr(subscription, "reset"):
                subscription.reset()
            elif self._keyboard_input and self._keyboard and hasattr(self._keyboard_input, "unsubscribe_to_keyboard_events"):
                self._keyboard_input.unsubscribe_to_keyboard_events(self._keyboard, subscription)
        except Exception as exc:
            carb.log_warn(f"FindSurface shortcut cleanup failed: {exc}")
        finally:
            self._keyboard = None
            self._keyboard_input = None

    def _on_keyboard_event(self, event):
        self._sync_retroactive_pick_active_from_keyboard(event)
        if self._is_key_press_event(event) and self._handle_shortcut_event(event):
            try:
                event.consume()
            except Exception:
                pass
        return True

    def _sync_retroactive_pick_active_from_keyboard(self, event):
        if self._event_is_alt_key(event):
            event_type = str(getattr(event, "type", "")).upper()
            self._set_retroactive_pick_active("RELEASE" not in event_type and "UP" not in event_type)
            return
        modifiers = self._event_modifier_value(event)
        if modifiers is not None:
            self._set_retroactive_pick_active(self._modifier_value_has_alt(modifiers))

    def _handle_shortcut_event(self, event):
        if not self._is_key_press_event(event):
            return False
        key = self._event_key_name(event)
        if key == "ESCAPE" and self._dismiss_modal_or_overlay():
            return True
        if self._is_text_input_editing(event):
            return False
        ctrl = self._event_has_control(event)
        shift = self._event_has_shift(event)
        if ctrl and shift and key == "Z":
            self._redo_last()
            return True
        if ctrl and key == "Z":
            self._undo_last()
            return True
        if ctrl and key == "S":
            self._save_workspace()
            return True
        if ctrl and key == "C":
            if self._can_capture_selected_preview():
                self._capture_selected_preview()
                return True
            return False
        if ctrl and key == "BACKTICK":
            self._set_detection_type("Auto")
            return True
        if ctrl and key in ("1", "2", "3", "4", "5"):
            self._set_detection_type(DETECTION_TYPES[int(key)])
            return True
        if key in ("ARROW_LEFT", "ARROW_RIGHT", "ARROW_UP", "ARROW_DOWN"):
            step = self._camera_shortcut_step_degrees(ctrl=ctrl, shift=shift)
            sign = -1.0 if key in ("ARROW_LEFT", "ARROW_DOWN") else 1.0
            axis = "horizontal" if key in ("ARROW_LEFT", "ARROW_RIGHT") else "vertical"
            return self._rotate_camera_step(axis, sign * step)
        if ctrl:
            return False
        if key == "ESCAPE":
            self._clear_selected_seed()
            return True
        if key == "BACKTICK":
            return False
        if key in ("1", "2", "3", "4", "5"):
            return False
        return False

    def _dismiss_modal_or_overlay(self):
        for name, cancel in (
            ("_save_workspace_dialog", self._cancel_save_workspace_dialog),
            ("_file_dialog", None),
            ("_load_workspace_dialog", None),
            ("_export_geometries_dialog", None),
        ):
            dialog = getattr(self, name, None)
            if not self._dialog_is_visible(dialog):
                continue
            if callable(cancel):
                cancel()
            else:
                self._hide_dialog(dialog)
            return True
        if self._is_window_visible(self.WINDOW_TUTORIAL):
            self._show_window(self.WINDOW_TUTORIAL, False)
            return True
        if self._dialog_is_visible(getattr(self, "_unsaved_changes_dialog", None)):
            self._cancel_unsaved_changes()
            return True
        if self._dialog_is_visible(getattr(self, "_export_options_dialog", None)):
            self._cancel_export_options_dialog()
            return True
        if self._dialog_is_visible(getattr(self, "_load_error_dialog", None)):
            self._close_load_error_dialog()
            return True
        if self._dialog_is_visible(getattr(self, "_point_limit_dialog", None)):
            self._cancel_pending_oversized_import()
            return True
        if self._dialog_is_visible(getattr(self, "_import_progress_dialog", None)):
            self._cancel_active_import()
            return True
        if self._dialog_is_visible(getattr(self, "_geometry_action_dialog", None)):
            self._cancel_geometry_action()
            return True
        if self._dialog_is_visible(getattr(self, "_native_sdk_dialog", None)):
            self._close_native_sdk_dialog()
            return True
        return False

    def _hide_dialog(self, dialog):
        if dialog is None:
            return
        hide = getattr(dialog, "hide", None)
        if callable(hide):
            hide()
            return
        try:
            dialog_window = getattr(dialog, "_window", None)
        except Exception:
            dialog_window = None
        for source in (dialog, dialog_window):
            if source is None:
                continue
            try:
                source.visible = False
            except Exception:
                pass

    def _is_text_input_editing(self, event):
        for name in (
            "ui_keyboard_capture",
            "keyboard_captured",
            "capture_keyboard",
            "want_capture_keyboard",
            "wants_keyboard_capture",
        ):
            value = getattr(event, name, None)
            if value is not None:
                return bool(value() if callable(value) else value)
        for name in ("flags", "input_flags", "event_flags"):
            if self._has_ui_keyboard_capture_flag(getattr(event, name, None)):
                return True
        return False

    def _has_ui_keyboard_capture_flag(self, flags):
        if flags is None:
            return False
        capture_flags = []
        for owner in (ui, getattr(ui, "Widget", None)):
            if not owner:
                continue
            for name in ("FLAG_WANT_CAPTURE_KEYBOARD", "WANT_CAPTURE_KEYBOARD"):
                value = getattr(owner, name, None)
                if value is not None:
                    capture_flags.append(value)
        for flag in capture_flags:
            try:
                if int(flags) & int(flag):
                    return True
            except Exception:
                if flags == flag:
                    return True
        return False

    def _is_key_press_event(self, event):
        event_type = str(getattr(event, "type", "")).upper()
        if "RELEASE" in event_type:
            return False
        if not event_type:
            return True
        return "PRESS" in event_type or "DOWN" in event_type or "REPEAT" in event_type

    def _event_key_name(self, event):
        value = getattr(event, "input", None)
        if value is None:
            value = getattr(event, "key", None)
        if value is None:
            return ""
        keyboard_input = getattr(carb.input, "KeyboardInput", object())
        for name in (
            "ESCAPE",
            "Z",
            "S",
            "C",
            "LEFT",
            "RIGHT",
            "UP",
            "DOWN",
            "ARROW_LEFT",
            "ARROW_RIGHT",
            "ARROW_UP",
            "ARROW_DOWN",
            "LEFT_ARROW",
            "RIGHT_ARROW",
            "UP_ARROW",
            "DOWN_ARROW",
            "GRAVE",
            "GRAVE_ACCENT",
            "ACCENT_GRAVE",
            "BACKTICK",
            "BACKQUOTE",
            "BACK_QUOTE",
            "BACK_APOSTROPHE",
            "OEM_3",
            "OEM3",
            "QUOTELEFT",
            "TILDE",
        ):
            enum_value = getattr(keyboard_input, name, None)
            if enum_value is not None and value == enum_value:
                return self._normalize_shortcut_key_name(name)
        text = str(value).split(".")[-1].upper()
        return self._normalize_shortcut_key_name(text)

    def _normalize_shortcut_key_name(self, text):
        text = str(text).split(".")[-1].upper()
        if text in ("KEY_ESCAPE", "ESC"):
            return "ESCAPE"
        if text.startswith("KEY_"):
            text = text[4:]
        if text.startswith("NUM_"):
            text = text[4:]
        if text.startswith("DIGIT_"):
            text = text[6:]
        if text in ("LEFT", "KEY_LEFT", "ARROWLEFT", "ARROW_LEFT", "LEFT_ARROW"):
            return "ARROW_LEFT"
        if text in ("RIGHT", "KEY_RIGHT", "ARROWRIGHT", "ARROW_RIGHT", "RIGHT_ARROW"):
            return "ARROW_RIGHT"
        if text in ("UP", "KEY_UP", "ARROWUP", "ARROW_UP", "UP_ARROW"):
            return "ARROW_UP"
        if text in ("DOWN", "KEY_DOWN", "ARROWDOWN", "ARROW_DOWN", "DOWN_ARROW"):
            return "ARROW_DOWN"
        if text in (
            "GRAVE",
            "GRAVE_ACCENT",
            "ACCENT_GRAVE",
            "BACKTICK",
            "BACKQUOTE",
            "BACK_QUOTE",
            "BACK_APOSTROPHE",
            "QUOTELEFT",
            "OEM_3",
            "OEM3",
            "`",
            "TILDE",
            "KEY_GRAVE_ACCENT",
            "KEY_BACKQUOTE",
        ):
            return "BACKTICK"
        return text

    def _event_is_alt_key(self, event):
        value = getattr(event, "input", None)
        if value is None:
            value = getattr(event, "key", None)
        if value is None:
            return False
        keyboard_input = getattr(carb.input, "KeyboardInput", object())
        for name in ("ALT", "LEFT_ALT", "RIGHT_ALT", "MENU", "LEFT_MENU", "RIGHT_MENU"):
            enum_value = getattr(keyboard_input, name, None)
            if enum_value is not None and value == enum_value:
                return True
        text = str(value).split(".")[-1].upper()
        if text.startswith("KEY_"):
            text = text[4:]
        return text in ("ALT", "LEFT_ALT", "RIGHT_ALT", "MENU", "LEFT_MENU", "RIGHT_MENU")

    def _event_modifier_value(self, event):
        for name in ("modifiers", "modifier", "keyboard_modifiers"):
            value = getattr(event, name, None)
            if value is not None:
                return value
        return None

    def _modifier_value_has_alt(self, modifiers):
        alt_flags = (
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_ALT", 4),
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_LEFT_ALT", 0),
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_RIGHT_ALT", 0),
        )
        try:
            value = int(modifiers)
        except Exception:
            return False
        return any(flag and value & int(flag) for flag in alt_flags)

    def _event_has_control(self, event):
        for name in (
            "control",
            "ctrl",
            "is_ctrl_down",
            "is_control_down",
            "control_down",
            "ctrl_down",
            "control_pressed",
            "ctrl_pressed",
        ):
            value = getattr(event, name, None)
            if value is not None:
                return bool(value() if callable(value) else value)
        modifiers = self._event_modifier_value(event)
        try:
            control_flag = getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_CONTROL", 0)
            return bool(int(modifiers) & int(control_flag))
        except Exception:
            return False

    def _event_has_shift(self, event):
        for name in (
            "shift",
            "is_shift_down",
            "shift_down",
            "shift_pressed",
        ):
            value = getattr(event, name, None)
            if value is not None:
                return bool(value() if callable(value) else value)
        modifiers = self._event_modifier_value(event)
        try:
            shift_flag = getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_SHIFT", 0)
            return bool(int(modifiers) & int(shift_flag))
        except Exception:
            return False

    def _camera_shortcut_step_degrees(self, ctrl=False, shift=False):
        if ctrl:
            return 0.05
        if shift:
            return 10.0
        return 1.0

    def _build_menus(self):
        file_menu = [
            MenuItemDescription(name="Load", onclick_action=(self._ext_id, "load_workspace")),
            MenuItemDescription(name="Save", onclick_action=(self._ext_id, "save_workspace")),
            MenuItemDescription(name="Save As...", onclick_action=(self._ext_id, "save_workspace_as")),
            MenuItemDescription(name=""),
            MenuItemDescription(name="Import Points", onclick_action=(self._ext_id, "import_points")),
            MenuItemDescription(name="Export Geometries", onclick_action=(self._ext_id, "export_geometries")),
            MenuItemDescription(name="Close", onclick_action=(self._ext_id, "close")),
        ]
        edit_menu = [
            MenuItemDescription(name="Undo", onclick_action=(self._ext_id, "undo")),
            MenuItemDescription(name="Redo", onclick_action=(self._ext_id, "redo")),
            MenuItemDescription(name="Reset", onclick_action=(self._ext_id, "reset_detection")),
        ]
        window_menu = [
            MenuItemDescription(
                name="Toolbar",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_TOOLBAR),
                onclick_action=(self._ext_id, "toggle_toolbar"),
            ),
            MenuItemDescription(
                name="Status Bar",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_STATUS_BAR),
                onclick_action=(self._ext_id, "toggle_status_bar"),
            ),
            MenuItemDescription(
                name="Viewport",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_VIEWPORT),
                onclick_action=(self._ext_id, "toggle_viewport"),
            ),
            MenuItemDescription(
                name="FindSurface",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_FINDSURFACE),
                onclick_action=(self._ext_id, "toggle_findsurface"),
            ),
            MenuItemDescription(
                name="Geometries",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_GEOMETRIES),
                onclick_action=(self._ext_id, "toggle_geometries"),
            ),
            MenuItemDescription(
                name="Camera",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_CAMERA),
                onclick_action=(self._ext_id, "toggle_camera"),
            ),
            MenuItemDescription(
                name="Settings",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_SETTINGS),
                onclick_action=(self._ext_id, "toggle_settings"),
            ),
            MenuItemDescription(
                name="Transactions",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_TRANSACTIONS),
                onclick_action=(self._ext_id, "toggle_transactions"),
            ),
            MenuItemDescription(
                name="Tutorial Overlay",
                ticked=True,
                ticked_fn=lambda: self._is_window_visible(self.WINDOW_TUTORIAL),
                onclick_action=(self._ext_id, "toggle_tutorial"),
            ),
        ]
        if self._diagnostic_group_box_window():
            window_menu.append(
                MenuItemDescription(
                    name="Debug Group Box",
                    ticked=True,
                    ticked_fn=lambda: self._is_window_visible(self.WINDOW_DEBUG_GROUP_BOX),
                    onclick_action=(self._ext_id, "toggle_debug_group_box"),
                )
            )

        omni.kit.menu.utils.add_menu_items(file_menu, "File", -100)
        omni.kit.menu.utils.add_menu_items(edit_menu, "Edit", -95)
        omni.kit.menu.utils.add_menu_items(window_menu, "Window", -90)
        self._menu_items["File"] = file_menu
        self._menu_items["Edit"] = edit_menu
        self._menu_items["Window"] = window_menu

    def _build_windows(self):
        self._windows[self.WINDOW_TOOLBAR] = self._create_toolbar_window()
        self._windows[self.WINDOW_TOOLBAR].frame.set_build_fn(self._build_toolbar)
        with self._windows[self.WINDOW_TOOLBAR].frame:
            self._build_toolbar()

        self._windows[self.WINDOW_STATUS_BAR] = ui.Window(
            self.WINDOW_STATUS_BAR,
            width=1200,
            height=24,
            flags=self._tool_window_flags(),
        )
        with self._windows[self.WINDOW_STATUS_BAR].frame:
            self._build_status_bar()

        viewport_flags = ui.WINDOW_FLAGS_NO_SCROLLBAR
        if hasattr(ui, "WINDOW_FLAGS_NO_SCROLL_WITH_MOUSE"):
            viewport_flags |= ui.WINDOW_FLAGS_NO_SCROLL_WITH_MOUSE
        self._windows[self.WINDOW_VIEWPORT] = ui.Window(
            self.WINDOW_VIEWPORT,
            width=1200,
            height=800,
            flags=viewport_flags,
        )
        with self._windows[self.WINDOW_VIEWPORT].frame:
            self._build_viewport()

        self._windows[self.WINDOW_FINDSURFACE] = ui.Window(
            self.WINDOW_FINDSURFACE,
            width=self.SIDE_PANEL_DEFAULT_WIDTH,
            height=800,
        )
        self._set_window_minimum_size(self._windows[self.WINDOW_FINDSURFACE], self.SIDE_PANEL_MIN_WIDTH)
        with self._windows[self.WINDOW_FINDSURFACE].frame:
            self._build_findsurface_window()

        self._windows[self.WINDOW_GEOMETRIES] = ui.Window(
            self.WINDOW_GEOMETRIES,
            width=self.SIDE_PANEL_DEFAULT_WIDTH,
            height=640,
        )
        self._set_window_minimum_size(self._windows[self.WINDOW_GEOMETRIES], self.SIDE_PANEL_MIN_WIDTH)
        with self._windows[self.WINDOW_GEOMETRIES].frame:
            self._build_geometries_window()

        self._windows[self.WINDOW_CAMERA] = ui.Window(
            self.WINDOW_CAMERA,
            width=self.SIDE_PANEL_DEFAULT_WIDTH,
            height=520,
        )
        self._set_window_minimum_size(self._windows[self.WINDOW_CAMERA], self.SIDE_PANEL_MIN_WIDTH)
        with self._windows[self.WINDOW_CAMERA].frame:
            self._build_camera_window()

        self._windows[self.WINDOW_SETTINGS] = ui.Window(
            self.WINDOW_SETTINGS,
            width=self.SIDE_PANEL_DEFAULT_WIDTH,
            height=520,
        )
        self._set_window_minimum_size(self._windows[self.WINDOW_SETTINGS], self.SIDE_PANEL_MIN_WIDTH)
        with self._windows[self.WINDOW_SETTINGS].frame:
            self._build_settings_window()

        self._windows[self.WINDOW_TRANSACTIONS] = ui.Window(
            self.WINDOW_TRANSACTIONS,
            width=self.SIDE_PANEL_DEFAULT_WIDTH,
            height=520,
        )
        self._set_window_minimum_size(self._windows[self.WINDOW_TRANSACTIONS], self.SIDE_PANEL_MIN_WIDTH)
        with self._windows[self.WINDOW_TRANSACTIONS].frame:
            self._build_transactions_window()
        self._windows[self.WINDOW_TRANSACTIONS].visible = False

        self._windows[self.WINDOW_TUTORIAL] = ui.Window(self.WINDOW_TUTORIAL, width=460, height=420)
        with self._windows[self.WINDOW_TUTORIAL].frame:
            self._build_tutorial_window()
        self._windows[self.WINDOW_TUTORIAL].visible = False

        if self._diagnostic_group_box_window():
            self._windows[self.WINDOW_DEBUG_GROUP_BOX] = ui.Window(
                self.WINDOW_DEBUG_GROUP_BOX,
                width=self.SIDE_PANEL_DEFAULT_WIDTH,
                height=360,
            )
            self._set_window_minimum_size(self._windows[self.WINDOW_DEBUG_GROUP_BOX], self.SIDE_PANEL_MIN_WIDTH)
            with self._windows[self.WINDOW_DEBUG_GROUP_BOX].frame:
                self._build_debug_group_box_window()

        for title in self._windows:
            ui.Workspace.set_show_window_fn(title, lambda visible, window_title=title: self._show_window(window_title, visible))
        self._register_window_visibility_changed_callback()
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._refresh_window_title()

    def _register_window_visibility_changed_callback(self):
        workspace = getattr(ui, "Workspace", None)
        register = getattr(workspace, "set_window_visibility_changed_callback", None)
        if not callable(register) or self._window_visibility_changed_callback_id is not None:
            return
        try:
            self._window_visibility_changed_callback_id = register(self._on_window_visibility_changed)
        except Exception as exc:
            carb.log_warn(f"FindSurface window visibility callback registration failed: {exc}")

    def _set_window_minimum_size(self, window, min_width, min_height=None):
        if window is None:
            return False
        applied = False
        for method_name in ("set_min_size", "set_minimum_size"):
            method = getattr(window, method_name, None)
            if callable(method):
                try:
                    method(min_width, min_height or 0)
                    applied = True
                    break
                except Exception:
                    pass
        for name in ("min_width", "minimum_width"):
            try:
                setattr(window, name, min_width)
                applied = True
            except Exception:
                pass
        if min_height is not None:
            for name in ("min_height", "minimum_height"):
                try:
                    setattr(window, name, min_height)
                    applied = True
                except Exception:
                    pass
        return applied

    def _create_toolbar_window(self):
        toolbar_cls = getattr(ui, "ToolBar", None)
        if toolbar_cls is None:
            return ui.Window(
                self.WINDOW_TOOLBAR,
                width=1200,
                height=self.TOOLBAR_WINDOW_THICKNESS,
                flags=self._tool_window_flags(),
            )
        return toolbar_cls(
            self.WINDOW_TOOLBAR,
            axis=self._toolbar_axis_x(),
            axis_changed_fn=self._on_toolbar_axis_changed,
            width=1200,
            height=self.TOOLBAR_WINDOW_THICKNESS,
            flags=self._tool_window_flags(),
        )

    def _toolbar_axis_x(self):
        return getattr(getattr(ui, "ToolBarAxis", None), "X", None)

    def _toolbar_axis_y(self):
        return getattr(getattr(ui, "ToolBarAxis", None), "Y", None)

    def _is_toolbar_vertical(self):
        return self._toolbar_axis is not None and self._toolbar_axis == self._toolbar_axis_y()

    def _on_toolbar_axis_changed(self, axis):
        self._toolbar_axis = axis
        toolbar = self._windows.get(self.WINDOW_TOOLBAR)
        if toolbar and getattr(toolbar, "frame", None):
            toolbar.frame.rebuild()

    def _build_toolbar(self):
        vertical = self._is_toolbar_vertical()
        layout_cls = ui.VStack if vertical else ui.HStack
        layout_size = {"width": 0} if vertical else {"height": 0}
        with layout_cls(
            spacing=2,
            style=self._toolbar_style(),
            style_type_name_override="ToolBar",
            **layout_size,
        ):
            self._toolbar_edge_spacer()
            self._toolbar_icon_button("folder-open.svg", "Load workspace", self._show_load_workspace_dialog)
            self._save_button = self._toolbar_icon_button(
                "device-floppy.svg", "Save workspace (Ctrl+S)", self._save_workspace
            )
            self._save_button.enabled = self._is_dirty
            self._toolbar_icon_button("file-import.svg", "Import points", self._show_import_points_dialog)
            self._export_button = self._toolbar_icon_button(
                "file-export.svg", "Export geometries", self._show_export_geometries_dialog
            )
            self._export_button.enabled = False
            self._toolbar_separator()
            self._toolbar_capture_button = self._toolbar_icon_button(
                "aperture.svg", "Capture selected preview", self._capture_selected_preview
            )
            self._toolbar_capture_button.enabled = False
            self._toolbar_undo_button = self._toolbar_icon_button(
                "arrow-back-up.svg", "Undo last detection action (Ctrl+Z)", self._undo_last
            )
            self._toolbar_icon_button("restore.svg", "Reset detection", self._reset_detection)
            self._toolbar_separator()
            self._toolbar_projection_buttons[PROJECTION_PERSPECTIVE] = self._toolbar_icon_button(
                "projection_persp.svg",
                "Perspective projection",
                clicked_fn=lambda: self._set_projection_mode(PROJECTION_PERSPECTIVE),
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_projection_buttons[PROJECTION_ORTHOGRAPHIC] = self._toolbar_icon_button(
                "projection_ortho.svg",
                "Orthographic projection",
                clicked_fn=lambda: self._set_projection_mode(PROJECTION_ORTHOGRAPHIC),
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_icon_button(
                "view_top.svg",
                "Top camera preset",
                lambda: self._set_camera_preset("top"),
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_icon_button(
                "view_front.svg",
                "Front camera preset",
                lambda: self._set_camera_preset("front"),
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_icon_button(
                "view_side.svg",
                "Side camera preset",
                lambda: self._set_camera_preset("side"),
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_separator()
            self._toolbar_inspect_button = self._toolbar_icon_button(
                "pointer.svg",
                "Inspect geometries",
                clicked_fn=self._set_inspect_mode,
                image_size=self.TOOLBAR_LARGE_ICON_SIZE,
            )
            self._toolbar_gap()
            for detection_type in DETECTION_TYPES:
                icon_name = f"detect_{detection_type.lower()}.svg"
                shortcut = "Ctrl+`" if detection_type == "Auto" else f"Ctrl+{DETECTION_TYPES.index(detection_type)}"
                self._toolbar_detection_buttons[detection_type] = self._toolbar_icon_button(
                    icon_name,
                    f"{detection_type} detection ({shortcut})",
                    clicked_fn=lambda value=detection_type: self._set_detection_type(value),
                    image_size=self.TOOLBAR_LARGE_ICON_SIZE,
                )
            self._toolbar_separator()
            self._visibility_buttons["outliers"] = self._toolbar_icon_button(
                "visibility_outliers_on.svg",
                "Toggle outlier points",
                clicked_fn=lambda: self._toggle_global_visibility("outliers"),
                image_size=self.TOOLBAR_VISIBILITY_ICON_SIZE,
            )
            self._visibility_buttons["meshes"] = self._toolbar_icon_button(
                "visibility_mesh_on.svg",
                "Toggle surface meshes",
                clicked_fn=lambda: self._toggle_global_visibility("meshes"),
                image_size=self.TOOLBAR_VISIBILITY_ICON_SIZE,
            )
            self._visibility_buttons["inliers"] = self._toolbar_icon_button(
                "visibility_inliers_on.svg",
                "Toggle inlier points",
                clicked_fn=lambda: self._toggle_global_visibility("inliers"),
                image_size=self.TOOLBAR_VISIBILITY_ICON_SIZE,
            )
            self._toolbar_separator()
            self._tutorial_button = self._toolbar_icon_button("help.svg", "Show tutorial", self._show_tutorial_overlay)
            self._refresh_toolbar_state()
            ui.Spacer()

    def _toolbar_icon_button(self, icon_name, tooltip, clicked_fn, image_size=None):
        if self._diagnostic_text_toolbar() or not self._use_toolbar_image_icons():
            button = ui.Button(
                self._diagnostic_toolbar_label(icon_name),
                width=self.TOOLBAR_TEXT_BUTTON_WIDTH,
                height=self.TOOLBAR_BUTTON_SIZE,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
                style_type_name_override="ToolBar.ButtonHit",
            )
            return _ToolbarIconButton(button, None, button)
        image_size = image_size or self.TOOLBAR_ICON_SIZE
        icon_path = self._toolbar_icon_path(icon_name)
        offset = (self.TOOLBAR_BUTTON_SIZE - image_size) / 2
        image_kwargs = {
            "width": image_size,
            "height": image_size,
            "style_type_name_override": "ToolBar.ButtonIcon",
        }
        alignment = getattr(getattr(ui, "Alignment", None), "CENTER", None)
        fill_policy = getattr(getattr(ui, "FillPolicy", None), "PRESERVE_ASPECT_FIT", None)
        if alignment is not None:
            image_kwargs["alignment"] = alignment
        if fill_policy is not None:
            image_kwargs["fill_policy"] = fill_policy
        with ui.ZStack(
            width=self.TOOLBAR_BUTTON_SIZE,
            height=self.TOOLBAR_BUTTON_SIZE,
            content_clipping=True,
            style_type_name_override="ToolBar.ButtonCell",
        ):
            frame = ui.Rectangle(
                width=self.TOOLBAR_BUTTON_SIZE,
                height=self.TOOLBAR_BUTTON_SIZE,
                style_type_name_override="ToolBar.ButtonFrame",
            )
            with ui.VStack(
                width=self.TOOLBAR_BUTTON_SIZE,
                height=self.TOOLBAR_BUTTON_SIZE,
                spacing=0,
            ):
                ui.Spacer(height=offset)
                with ui.HStack(width=self.TOOLBAR_BUTTON_SIZE, height=image_size, spacing=0):
                    ui.Spacer(width=offset)
                    image = ui.Image(icon_path, **image_kwargs)
                    ui.Spacer()
                ui.Spacer()
            button = ui.Button(
                " ",
                width=self.TOOLBAR_BUTTON_SIZE,
                height=self.TOOLBAR_BUTTON_SIZE,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
                style_type_name_override="ToolBar.ButtonHit",
            )
        return _ToolbarIconButton(button, image, frame)

    def _diagnostic_toolbar_label(self, icon_name):
        icon_stem = os.path.splitext(icon_name)[0]
        labels = {
            "folder-open": "Load",
            "device-floppy": "Save",
            "file-import": "Imp",
            "file-export": "Exp",
            "aperture": "Cap",
            "arrow-back-up": "Undo",
            "restore": "Reset",
            "projection_persp": "Persp",
            "projection_ortho": "Ortho",
            "view_top": "Top",
            "view_front": "Front",
            "view_side": "Side",
            "detect_auto": "Auto",
            "detect_plane": "Plane",
            "detect_sphere": "Sphere",
            "detect_cylinder": "Cyl",
            "detect_cone": "Cone",
            "detect_torus": "Torus",
            "visibility_outliers_on": "Out+",
            "visibility_outliers_off": "Out-",
            "visibility_mesh_on": "Mesh+",
            "visibility_mesh_off": "Mesh-",
            "visibility_inliers_on": "In+",
            "visibility_inliers_off": "In-",
            "help": "Help",
        }
        return labels.get(icon_stem, icon_stem[:6])

    def _toolbar_style(self):
        return {
            "ToolBar": {"margin_height": 2},
            "ToolBar.ButtonCell": {"margin_width": 1, "padding": 0},
            "ToolBar.ButtonFrame": {
                "background_color": 0x0,
                "border_color": 0xFF7A7A7A,
                "border_radius": 2,
                "border_width": 1,
                "margin_width": 0,
                "padding": 0,
            },
            "ToolBar.ButtonFrame:hovered": {
                "background_color": 0xFF4A4A4A,
                "border_color": 0xFFB0B0B0,
            },
            "ToolBar.ButtonFrame:selected": {
                "background_color": 0xFF252525,
                "border_color": 0xFF181818,
            },
            "ToolBar.ButtonFrame:checked": {
                "background_color": 0xFF252525,
                "border_color": 0xFF181818,
            },
            "ToolBar.ButtonFrame:disabled": {
                "background_color": 0x0,
                "border_color": 0xFF4E4E4E,
            },
            "ToolBar.ButtonHit": {
                "background_color": 0x0,
                "border_color": 0x0,
                "border_width": 0,
                "margin_width": 0,
                "padding": 0,
            },
            "ToolBar.ButtonHit.Label": {"color": 0x0},
            "ToolBar.ButtonHit:hovered": {"background_color": 0x0, "border_color": 0x0},
            "ToolBar.ButtonHit:selected": {"background_color": 0x0, "border_color": 0x0},
            "ToolBar.ButtonHit:checked": {"background_color": 0x0, "border_color": 0x0},
            "ToolBar.ButtonHit:disabled": {"background_color": 0x0, "border_color": 0x0},
            "ToolBar.ButtonIcon": {"background_color": 0x0, "color": 0xFFFFFFFF},
            "ToolBar.ButtonIcon:disabled": {"color": 0xFF808080},
        }

    def _toolbar_icon_path(self, icon_name):
        icon_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "icons", "findsurface"))
        return os.path.join(icon_dir, icon_name)

    def _tool_window_flags(self):
        flags = ui.WINDOW_FLAGS_NO_SCROLLBAR
        if hasattr(ui, "WINDOW_FLAGS_NO_TITLE_BAR"):
            flags |= ui.WINDOW_FLAGS_NO_TITLE_BAR
        return flags

    def _build_status_bar(self):
        with ui.HStack(height=0, spacing=6):
            ui.Spacer(width=6)
            self._status_label = ui.Label("", height=22)
            ui.Spacer(width=6)
        self._refresh_status_bar()

    def _toolbar_edge_spacer(self):
        if self._is_toolbar_vertical():
            ui.Spacer(height=3)
        else:
            ui.Spacer(width=3)

    def _toolbar_separator(self):
        if self._is_toolbar_vertical():
            ui.Spacer(height=3)
            ui.Rectangle(width=self.TOOLBAR_SEPARATOR_LENGTH, height=1, style={"background_color": 0xFF4A4A4A})
            ui.Spacer(height=3)
        else:
            ui.Spacer(width=3)
            ui.Rectangle(width=1, height=self.TOOLBAR_SEPARATOR_LENGTH, style={"background_color": 0xFF4A4A4A})
            ui.Spacer(width=3)

    def _toolbar_gap(self):
        if self._is_toolbar_vertical():
            ui.Spacer(height=10)
        else:
            ui.Spacer(width=10)

    def _visibility_button_text(self, label, visible):
        return f"{label} On" if visible else f"{label} Off"

    def _build_viewport(self):
        self._viewport.build()

    def _build_findsurface_window(self):
        for name, (_label, value, minimum, maximum) in self.RANGE_PARAMETER_DEFAULTS.items():
            if name not in self._models:
                self._models[name] = self._new_range_float_model(value)
            if f"{name}_min" not in self._models:
                self._models[f"{name}_min"] = self._new_range_float_model(minimum)
            if f"{name}_max" not in self._models:
                self._models[f"{name}_max"] = self._new_range_float_model(maximum)
            if f"{name}_slider_index" not in self._models:
                self._models[f"{name}_slider_index"] = self._new_range_slider_index_model(
                    self._range_slider_index_for_value(value, minimum, maximum)
                )
            if name not in self._range_edit_models:
                self._init_range_edit_models(name)
        if "radial_expansion" not in self._models:
            self._models["radial_expansion"] = ui.SimpleIntModel(
                app_config.config_int(self._config(), ("detection", "radial_expansion"), 5, 0, 10)
            )
        if "lateral_extension" not in self._models:
            self._models["lateral_extension"] = ui.SimpleIntModel(
                app_config.config_int(self._config(), ("detection", "lateral_extension"), 5, 0, 10)
            )
        if "probe_radius" not in self._models:
            self._models["probe_radius"] = ui.SimpleFloatModel(self._viewport.probe_radius_px)
        if "auto_detect" not in self._models:
            self._models["auto_detect"] = ui.SimpleBoolModel(True)
        self._ensure_parameter_pad_axis_models()
        for name in self.RANGE_PARAMETER_DEFAULTS:
            self._subscribe_model(name, self._on_range_parameter_changed)
            self._subscribe_model(f"{name}_min", self._on_range_parameter_changed)
            self._subscribe_model(f"{name}_max", self._on_range_parameter_changed)
            self._subscribe_model(f"{name}_slider_index", self._on_range_parameter_changed)
            self._subscribe_range_edit_model_end_edit(f"{name}_min", self._on_range_endpoint_edit_finished)
            self._subscribe_range_edit_model_end_edit(f"{name}_max", self._on_range_endpoint_edit_finished)
            self._subscribe_range_edit_model_end_edit(name, self._on_detection_parameter_edit_finished)
            self._subscribe_model_end_edit(f"{name}_slider_index", self._on_detection_parameter_edit_finished)
        for name in ("radial_expansion", "lateral_extension"):
            self._subscribe_model_end_edit(name, self._on_detection_parameter_edit_finished)
            self._subscribe_model(name, self._on_detection_parameter_value_changed)
        for name in ("probe_radius", "auto_detect"):
            self._subscribe_model(name, self._on_detection_settings_changed)

        self._active_count_label = None
        self._hover_index_label = None
        self._selected_index_label = None
        self._dataset_label = None
        self._point_count_label = None
        self._capture_button = None
        self._undo_button = None
        self._redo_button = None
        self._result_label = None

        build_findsurface_window(
            FindSurfaceWindowModels(
                lateral_extension=self._models["lateral_extension"],
                radial_expansion=self._models["radial_expansion"],
            ),
            FindSurfaceWindowCallbacks(
                range_float_row=self._range_float_row,
                int_slider_row=self._int_slider_row,
                build_parameter_pad_row=self._build_parameter_pad_row_container,
            ),
        )

    def _build_settings_window(self):
        self._models["point_size"] = ui.SimpleFloatModel(self._viewport.point_size)
        self._init_color_models("point", self._viewport.point_color)
        self._init_color_models("selected_point", self._viewport.selected_point_color)
        self._init_color_models("inlier_negative", self._viewport.inlier_negative_color)
        self._init_color_models("inlier_zero", self._viewport.inlier_zero_color)
        self._init_color_models("inlier_positive", self._viewport.inlier_positive_color)
        self._models["inlier_negative_sigma"] = ui.SimpleFloatModel(self._viewport.inlier_negative_sigma)
        self._models["inlier_positive_sigma"] = ui.SimpleFloatModel(self._viewport.inlier_positive_sigma)
        self._init_color_models("surface", self._viewport.surface_color)
        self._init_color_models("surface_wire", self._viewport.surface_wire_color)
        self._init_color_models("histogram_tooltip_background", self.HISTOGRAM_TOOLTIP_BACKGROUND_COLOR)
        self._init_color_models("histogram_tooltip_text", self.HISTOGRAM_TOOLTIP_TEXT_COLOR)
        self._models["pick_nearest_on_probe_miss"] = ui.SimpleBoolModel(self._viewport.pick_nearest_on_probe_miss)
        self._models["sticky_auto_preview"] = ui.SimpleBoolModel(
            app_config.config_bool(self._config(), ("preview", "sticky_auto_preview"), True)
        )
        self._models["sticky_auto_preview_timeout_ms"] = ui.SimpleIntModel(
            app_config.config_int(self._config(), ("preview", "sticky_auto_preview_timeout_ms"), 500, 100, 60000)
        )

        with ui.VStack(spacing=6):
            ui.Spacer(height=8)
            ui.Label("Point Rendering", height=22)
            self._float_row("Size", self._models["point_size"], minimum=1.0, maximum=16.0)
            ui.Spacer(height=8)
            with BorderedGroupView("Picking", row_heights=(26, 26, 26, 26)):
                self._float_row("Probe px", self._models["probe_radius"], minimum=1.0, maximum=80.0)
                with ui.HStack(height=26, spacing=6):
                    ui.CheckBox(model=self._models["pick_nearest_on_probe_miss"], width=22)
                    ui.Label("Pick Nearest On Probe Miss")
                with ui.HStack(height=26, spacing=6):
                    ui.CheckBox(model=self._models["sticky_auto_preview"], width=22)
                    ui.Label("Sticky Auto Preview")
                self._sticky_preview_timeout_row()
            with self._settings_color_group():
                with ui.VStack(height=0, spacing=6):
                    with BorderedGroupView("Outlier Points", row_heights=(18, 26, 26)):
                        self._color_header()
                        self._color_controls("Points", "point")
                        self._color_controls("Selected", "selected_point")
                    with BorderedGroupView("Inlier Points", row_heights=(18, 26, 26, 26)):
                        self._color_header(include_sigma=True)
                        self._color_controls(
                            "Inlier -sigma",
                            "inlier_negative",
                            sigma_model=self._models["inlier_negative_sigma"],
                            sigma_min=-3.0,
                            sigma_max=-0.5,
                        )
                        self._color_controls("Inlier 0", "inlier_zero")
                        self._color_controls(
                            "Inlier +sigma",
                            "inlier_positive",
                            sigma_model=self._models["inlier_positive_sigma"],
                            sigma_min=0.5,
                            sigma_max=3.0,
                        )
                    with BorderedGroupView("Geometry Polygon", row_heights=(18, 26, 26)):
                        self._color_header()
                        self._color_controls("Surface", "surface")
                        self._color_controls("Wire", "surface_wire")
                    with BorderedGroupView("Histogram Tooltip", row_heights=(18, 26, 26)):
                        self._color_header()
                        self._color_controls("Tooltip Bg", "histogram_tooltip_background")
                        self._color_controls("Tooltip Text", "histogram_tooltip_text")
            ui.Spacer()

        self._subscribe_model("point_size", self._on_display_settings_changed)
        for prefix in (
            "point",
            "selected_point",
            "inlier_negative",
            "inlier_zero",
            "inlier_positive",
            "surface",
            "surface_wire",
            "histogram_tooltip_background",
            "histogram_tooltip_text",
        ):
            for channel in ("r", "g", "b", "a", "brightness"):
                self._subscribe_model(f"{prefix}_{channel}", self._on_display_settings_changed)
        self._subscribe_model("inlier_negative_sigma", self._on_display_settings_changed)
        self._subscribe_model("inlier_positive_sigma", self._on_display_settings_changed)
        self._subscribe_model("pick_nearest_on_probe_miss", self._on_detection_settings_changed)
        self._subscribe_model("sticky_auto_preview", self._on_detection_settings_changed)
        self._subscribe_model("sticky_auto_preview_timeout_ms", self._on_detection_settings_changed)

    def _settings_color_group(self):
        collapsable_frame_cls = getattr(ui, "CollapsableFrame", None)
        if collapsable_frame_cls:
            return collapsable_frame_cls("Colors", collapsed=True, height=0)
        return BorderedGroupView("Colors")

    def _build_camera_window(self):
        camera_model_names = (
            "center_x",
            "center_y",
            "center_z",
            "position_x",
            "position_y",
            "position_z",
            "direction_x",
            "direction_y",
            "direction_z",
            "up_x",
            "up_y",
            "up_z",
            "zoom",
            "fov",
        )
        for name in camera_model_names:
            self._models[name] = ui.SimpleFloatModel(0.0)
        self._models["zoom"].set_value(1.0)
        self._models["fov"].set_value(self._viewport.camera.fov_degrees)
        for name in camera_model_names:
            self._subscribe_model(name, self._on_camera_settings_changed)

        with ui.VStack(spacing=6):
            ui.Spacer(height=8)
            self._projection_label = None
            self._float_row("FOV", self._models["fov"], minimum=1.0, maximum=160.0)
            ui.Spacer(height=4)
            self._vector_row("Center", ("center_x", "center_y", "center_z"))
            self._vector_row("Position", ("position_x", "position_y", "position_z"))
            self._vector_row("Direction", ("direction_x", "direction_y", "direction_z"))
            self._vector_row("Up", ("up_x", "up_y", "up_z"))
            ui.Spacer(height=4)
            with BorderedGroupView("Rotate Control", row_heights=(54, 54)):
                self._camera_rotation_row("Horizontal deg", "horizontal")
                self._camera_rotation_row("Vertical deg", "vertical")
            ui.Spacer(height=4)
            self._float_row("Zoom Factor", self._models["zoom"], minimum=0.001, maximum=1000.0)
            ui.Button("Fit to Bounding Box", height=28, clicked_fn=self._fit_camera)
            ui.Spacer()
        self._sync_camera_models()

    def _camera_rotation_row(self, label, axis):
        steps = (-10.0, -1.0, -0.05, 0.05, 1.0, 10.0)
        with ui.VStack(height=54, spacing=2):
            ui.Label(label, height=20)
            with ui.HStack(height=28, spacing=4):
                for step in steps:
                    ui.Button(
                        self._camera_rotation_button_label(step),
                        width=42,
                        clicked_fn=lambda axis=axis, step=step: self._rotate_camera_step(axis, step),
                    )
                ui.Spacer()

    def _camera_rotation_button_label(self, degrees):
        sign = "+" if degrees > 0.0 else "-"
        magnitude = abs(float(degrees))
        return f"{sign}{magnitude:g}"

    def _build_geometries_window(self):
        self._histogram_hit_regions = []
        self._histogram_status_regions = []
        self._histogram_status_labels = {}
        self._histogram_status_key = None
        with ui.VStack(spacing=6):
            ui.Spacer(height=8)
            result_count = len(self._state.results) if self._state else 0
            has_results = result_count > 0
            with ui.HStack(height=22, spacing=4):
                self._geometries_summary_label = ui.Label(f"{result_count} detected geometries", height=22)
                ui.Spacer()
                self._geometries_header_icon_button(
                    "visibility_mesh_on.svg",
                    "Show All Meshes",
                    clicked_fn=lambda: self._set_all_geometry_visibility("mesh_visible", True),
                    fallback_label="M+",
                    enabled=has_results,
                )
                self._geometries_header_icon_button(
                    "visibility_mesh_off.svg",
                    "Hide All Meshes",
                    clicked_fn=lambda: self._set_all_geometry_visibility("mesh_visible", False),
                    fallback_label="M-",
                    enabled=has_results,
                )
                self._geometries_header_icon_button(
                    "visibility_inliers_on.svg",
                    "Show All Inliers",
                    clicked_fn=lambda: self._set_all_geometry_visibility("inliers_visible", True),
                    fallback_label="I+",
                    enabled=has_results,
                )
                self._geometries_header_icon_button(
                    "visibility_inliers_off.svg",
                    "Hide All Inliers",
                    clicked_fn=lambda: self._set_all_geometry_visibility("inliers_visible", False),
                    fallback_label="I-",
                    enabled=has_results,
                )
                self._geometries_header_text_button(
                    "+",
                    tooltip="Expand all geometries",
                    clicked_fn=self._expand_all_geometries,
                    enabled=has_results,
                )
                self._geometries_header_text_button(
                    "-",
                    tooltip="Collapse all geometries",
                    clicked_fn=self._collapse_all_geometries,
                    enabled=has_results,
                )
            if not result_count:
                ui.Label("No detected geometries.", word_wrap=True)
                ui.Spacer()
                return

            scrolling_frame = getattr(ui, "ScrollingFrame", None)
            if scrolling_frame:
                self._geometries_scrolling_frame = scrolling_frame()
                with self._geometries_scrolling_frame:
                    self._build_geometries_content()
            else:
                self._geometries_scrolling_frame = None
                self._build_geometries_content()

    def _build_geometries_content(self):
        with ui.VStack(spacing=6):
            for result in self._state.results:
                self._build_geometry_section(result)

    def _build_geometry_section(self, result):
        collapsed = self._is_geometry_collapsed(result.id)
        padding = self.GEOMETRY_SECTION_PADDING
        fields = self._geometry_result_fields(result)
        histogram = self._geometry_distance_histogram(result)
        item_height = self._geometry_item_height(fields, histogram, getattr(result, "id", ""))
        frame = self._geometry_collapsable_frame(result, collapsed)
        with frame:
            with ui.VStack(height=0, spacing=0):
                ui.Spacer(height=self.GEOMETRY_CONTENT_GAP)
                with ui.HStack(height=item_height, spacing=0):
                    ui.Spacer(width=padding)
                    self._build_geometry_item(result, fields=fields, histogram=histogram, histogram_computed=True)
                    ui.Spacer(width=padding)

    def _geometry_collapsable_frame(self, result, collapsed):
        title = f"{result.id} ({result.type})"
        frame_cls = getattr(ui, "CollapsableFrame", None)
        if frame_cls:
            frame = frame_cls(title, collapsed=bool(collapsed), height=0)
            if hasattr(frame, "set_collapsed_changed_fn"):
                frame.set_collapsed_changed_fn(
                    lambda next_collapsed, result_id=result.id: self._set_geometry_collapsed(
                        result_id,
                        next_collapsed,
                    )
                )
            return frame
        return _FallbackGeometryFrame(
            title,
            collapsed=bool(collapsed),
            toggle_fn=lambda result_id=result.id: self._toggle_geometry_collapsed(result_id),
        )

    def _geometry_item_height(self, fields, histogram=None, result_id=""):
        rows = [self.GEOMETRY_ITEM_BUTTON_ROW_HEIGHT]
        rows.extend(self.GEOMETRY_FIELD_ROW_HEIGHT for _field in fields)
        if histogram:
            rows.extend((self.GEOMETRY_CONTENT_GAP, self._geometry_histogram_panel_height(result_id)))
        return sum(rows) + max(0, len(rows) - 1) * self.GEOMETRY_ITEM_ROW_SPACING

    def _geometry_histogram_panel_height(self, result_id):
        if self._geometry_histogram_details_visible(result_id):
            return self.GEOMETRY_HISTOGRAM_EXPANDED_HEIGHT
        return self.GEOMETRY_HISTOGRAM_COLLAPSED_HEIGHT

    def _build_geometry_item(self, result, fields=None, histogram=None, histogram_computed=False):
        mesh_visible = getattr(result, "mesh_visible", True)
        inliers_visible = getattr(result, "inliers_visible", True)
        fields = list(fields if fields is not None else self._geometry_result_fields(result))
        if not histogram_computed:
            histogram = self._geometry_distance_histogram(result)
        item_height = self._geometry_item_height(fields, histogram, getattr(result, "id", ""))
        with ui.VStack(height=item_height, spacing=self.GEOMETRY_ITEM_ROW_SPACING):
            with ui.HStack(height=self.GEOMETRY_ITEM_BUTTON_ROW_HEIGHT, spacing=6):
                self._geometry_icon_button(
                    self._toolbar_icon_path("center-focus.svg"),
                    "Focus geometry in viewport",
                    clicked_fn=lambda result_id=result.id: self._focus_geometry_result(result_id),
                    fallback_label="Focus",
                )
                self._geometry_icon_button(
                    self._visibility_icon_path("meshes", mesh_visible),
                    "Hide surface mesh" if mesh_visible else "Show surface mesh",
                    clicked_fn=lambda result_id=result.id: self._toggle_geometry_mesh(result_id),
                    fallback_label=self._visibility_button_text("Mesh", mesh_visible),
                )
                self._geometry_icon_button(
                    self._visibility_icon_path("inliers", inliers_visible),
                    "Hide inlier points" if inliers_visible else "Show inlier points",
                    clicked_fn=lambda result_id=result.id: self._toggle_geometry_inliers(result_id),
                    fallback_label=self._visibility_button_text("Inliers", inliers_visible),
                )
                self._geometry_icon_button(
                    self._toolbar_icon_path("delete.svg"),
                    "Delete geometry and keep inliers removed",
                    clicked_fn=lambda result_id=result.id: self._request_delete_geometry_result(result_id),
                    fallback_label="Delete",
                )
                self._geometry_icon_button(
                    self._toolbar_icon_path("arrow-back-up.svg"),
                    "Cancel detection and restore inliers",
                    clicked_fn=lambda result_id=result.id: self._request_cancel_geometry_result(result_id),
                    fallback_label="Cancel",
                )
                ui.Spacer()
            self._build_geometry_fields(fields)
            self._build_geometry_distance_histogram(result, histogram=histogram, histogram_computed=True)

    def _build_geometry_fields(self, fields):
        for field in fields:
            if self._geometry_field_kind(field) == "vector3":
                self._build_geometry_vector_field(field)
            else:
                self._build_geometry_scalar_field(field)

    def _build_geometry_scalar_field(self, field):
        with ui.HStack(height=self.GEOMETRY_FIELD_ROW_HEIGHT, spacing=6):
            ui.Label(
                self._geometry_field_label(field),
                width=self.GEOMETRY_FIELD_LABEL_WIDTH,
                height=self.GEOMETRY_FIELD_ROW_HEIGHT,
                style=self._geometry_field_label_style(),
            )
            self._build_geometry_field_cell(self._geometry_field_value_text(field))

    def _build_geometry_vector_field(self, field):
        components = self._geometry_field_components(field)
        with ui.HStack(height=self.GEOMETRY_FIELD_ROW_HEIGHT, spacing=6):
            ui.Label(
                self._geometry_field_label(field),
                width=self.GEOMETRY_FIELD_LABEL_WIDTH,
                height=self.GEOMETRY_FIELD_ROW_HEIGHT,
                style=self._geometry_field_label_style(),
            )
            for axis_label, component in zip(("X", "Y", "Z"), components):
                ui.Label(
                    axis_label,
                    width=self.GEOMETRY_VECTOR_AXIS_WIDTH,
                    height=self.GEOMETRY_FIELD_ROW_HEIGHT,
                    style=self._geometry_field_axis_style(),
                )
                self._build_geometry_field_cell(component, width=self.GEOMETRY_VECTOR_VALUE_WIDTH)

    def _build_geometry_field_cell(self, value, width=None):
        kwargs = {"height": self.GEOMETRY_FIELD_ROW_HEIGHT}
        if width is not None:
            kwargs["width"] = width
        rectangle_cls = getattr(ui, "Rectangle", None)
        zstack_cls = getattr(ui, "ZStack", None)
        if rectangle_cls is not None and zstack_cls is not None:
            with zstack_cls(**kwargs):
                rectangle_cls(style=self._geometry_field_cell_style())
                ui.Label(str(value), height=self.GEOMETRY_FIELD_ROW_HEIGHT, style=self._geometry_field_value_style())
        else:
            ui.Label(str(value), **kwargs, style=self._geometry_field_value_style())

    def _geometry_field_label_style(self):
        return {
            "color": 0xFFB8B8B8,
            "font_size": 12,
        }

    def _geometry_field_axis_style(self):
        return {
            "color": 0xFF8FA8C8,
            "font_size": 11,
        }

    def _geometry_field_value_style(self):
        return {
            "color": 0xFFE8E8E8,
            "font_size": 12,
        }

    def _geometry_field_cell_style(self):
        return {
            "background_color": 0x181F232B,
            "border_radius": 3,
        }

    def _geometry_icon_button(self, image_path, tooltip, clicked_fn, fallback_label=None, image_size=None):
        button_size = self.GEOMETRY_ICON_BUTTON_SIZE
        image_cls = getattr(ui, "Image", None)
        rectangle_cls = getattr(ui, "Rectangle", None)
        if (
            self._diagnostic_text_toolbar()
            or not self._use_toolbar_image_icons()
            or image_cls is None
            or rectangle_cls is None
            or getattr(ui, "ZStack", None) is None
        ):
            return ui.Button(
                fallback_label or self._diagnostic_toolbar_label(os.path.basename(image_path or "")),
                width=button_size,
                height=button_size,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
            )
        image_size = image_size or self.GEOMETRY_ICON_SIZE
        offset = max(0, (button_size - image_size) / 2)
        image_kwargs = {
            "width": image_size,
            "height": image_size,
            "style_type_name_override": "ToolBar.ButtonIcon",
        }
        alignment = getattr(getattr(ui, "Alignment", None), "CENTER", None)
        fill_policy = getattr(getattr(ui, "FillPolicy", None), "PRESERVE_ASPECT_FIT", None)
        if alignment is not None:
            image_kwargs["alignment"] = alignment
        if fill_policy is not None:
            image_kwargs["fill_policy"] = fill_policy
        with ui.ZStack(
            width=button_size,
            height=button_size,
            content_clipping=True,
            style=self._toolbar_style(),
            style_type_name_override="ToolBar.ButtonCell",
        ):
            frame = rectangle_cls(
                width=button_size,
                height=button_size,
                style_type_name_override="ToolBar.ButtonFrame",
            )
            with ui.VStack(width=button_size, height=button_size, spacing=0):
                ui.Spacer(height=offset)
                with ui.HStack(width=button_size, height=image_size, spacing=0):
                    ui.Spacer(width=offset)
                    image = image_cls(image_path, **image_kwargs)
                    ui.Spacer()
                ui.Spacer()
            button = ui.Button(
                " ",
                width=button_size,
                height=button_size,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
                style_type_name_override="ToolBar.ButtonHit",
            )
        return _ToolbarIconButton(button, image, frame)

    def _geometries_header_icon_button(self, icon_name, tooltip, clicked_fn, fallback_label, enabled=True):
        width = 24
        height = 22
        image_size = 18
        image_cls = getattr(ui, "Image", None)
        rectangle_cls = getattr(ui, "Rectangle", None)
        if (
            self._diagnostic_text_toolbar()
            or not self._use_toolbar_image_icons()
            or image_cls is None
            or rectangle_cls is None
            or getattr(ui, "ZStack", None) is None
        ):
            button = ui.Button(
                fallback_label,
                width=width,
                height=height,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
            )
            self._set_widget_enabled(button, enabled)
            return button
        icon_path = self._toolbar_icon_path(icon_name)
        image_kwargs = {
            "width": image_size,
            "height": image_size,
            "style_type_name_override": "ToolBar.ButtonIcon",
        }
        alignment = getattr(getattr(ui, "Alignment", None), "CENTER", None)
        fill_policy = getattr(getattr(ui, "FillPolicy", None), "PRESERVE_ASPECT_FIT", None)
        if alignment is not None:
            image_kwargs["alignment"] = alignment
        if fill_policy is not None:
            image_kwargs["fill_policy"] = fill_policy
        horizontal_offset = max(0, (width - image_size) / 2)
        vertical_offset = max(0, (height - image_size) / 2)
        with ui.ZStack(
            width=width,
            height=height,
            content_clipping=True,
            style=self._toolbar_style(),
            style_type_name_override="ToolBar.ButtonCell",
        ):
            frame = rectangle_cls(
                width=width,
                height=height,
                style_type_name_override="ToolBar.ButtonFrame",
            )
            with ui.VStack(width=width, height=height, spacing=0):
                ui.Spacer(height=vertical_offset)
                with ui.HStack(width=width, height=image_size, spacing=0):
                    ui.Spacer(width=horizontal_offset)
                    image = image_cls(icon_path, **image_kwargs)
                    ui.Spacer()
                ui.Spacer()
            button = ui.Button(
                " ",
                width=width,
                height=height,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
                style_type_name_override="ToolBar.ButtonHit",
            )
        wrapped = _ToolbarIconButton(button, image, frame)
        self._set_widget_enabled(wrapped, enabled)
        return wrapped

    def _geometries_header_text_button(self, label, tooltip, clicked_fn, enabled=True):
        width = 24
        height = 22
        rectangle_cls = getattr(ui, "Rectangle", None)
        label_cls = getattr(ui, "Label", None)
        if (
            self._diagnostic_text_toolbar()
            or rectangle_cls is None
            or label_cls is None
            or getattr(ui, "ZStack", None) is None
        ):
            button = ui.Button(
                label,
                width=width,
                height=height,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
            )
            self._set_widget_enabled(button, enabled)
            return button
        label_kwargs = {
            "width": width,
            "height": height,
            "style_type_name_override": "ToolBar.ButtonIcon",
        }
        alignment = getattr(getattr(ui, "Alignment", None), "CENTER", None)
        if alignment is not None:
            label_kwargs["alignment"] = alignment
        with ui.ZStack(
            width=width,
            height=height,
            content_clipping=True,
            style=self._toolbar_style(),
            style_type_name_override="ToolBar.ButtonCell",
        ):
            frame = rectangle_cls(
                width=width,
                height=height,
                style_type_name_override="ToolBar.ButtonFrame",
            )
            text = label_cls(label, **label_kwargs)
            button = ui.Button(
                " ",
                width=width,
                height=height,
                tooltip=tooltip,
                clicked_fn=clicked_fn,
                style_type_name_override="ToolBar.ButtonHit",
            )
        wrapped = _ToolbarIconButton(button, text, frame)
        self._set_widget_enabled(wrapped, enabled)
        return wrapped

    def _build_geometry_distance_histogram(self, result, histogram=None, histogram_computed=False):
        if not histogram_computed:
            histogram = self._geometry_distance_histogram(result)
        if not histogram:
            return
        ui.Spacer(height=self.GEOMETRY_CONTENT_GAP)
        with ui.ZStack(height=self._geometry_histogram_panel_height(result.id)):
            rectangle = getattr(ui, "Rectangle", None)
            if rectangle:
                rectangle(style=self._geometry_histogram_box_style())
            with ui.VStack(spacing=4):
                ui.Spacer(height=self.HISTOGRAM_PANEL_PADDING)
                with ui.HStack(height=24, spacing=6):
                    ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)
                    ui.Button("-", width=24, clicked_fn=lambda result_id=result.id: self._adjust_geometry_histogram_bins(result_id, -2))
                    ui.Label(f"{histogram['bin_count']} bins", width=58)
                    ui.Button("+", width=24, clicked_fn=lambda result_id=result.id: self._adjust_geometry_histogram_bins(result_id, 2))
                    ui.Spacer()
                    ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)
                ui.Spacer(height=4)
                self._build_geometry_histogram_bars(histogram, result.id)
                with ui.HStack(height=116 if self._geometry_histogram_details_visible(result.id) else 24, spacing=0):
                    ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)
                    if self._geometry_histogram_details_visible(result.id):
                        self._build_geometry_histogram_details(histogram)
                    else:
                        ui.Spacer()
                    ui.Button(
                        "See less" if self._geometry_histogram_details_visible(result.id) else "See details",
                        width=82,
                        clicked_fn=lambda result_id=result.id: self._toggle_geometry_histogram_details(result_id),
                    )
                    ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)

    def _build_geometry_histogram_bars(self, histogram, result_id=None):
        rectangle = getattr(ui, "Rectangle", None)
        max_count = max(1, int(histogram.get("max_bin_count") or 0))
        bins = list(histogram["bins"])
        spacing = self.HISTOGRAM_BAR_SPACING
        bar_widths = self._histogram_bar_widths(len(bins), self.HISTOGRAM_CHART_WIDTH, spacing)
        chart_box_width = self.HISTOGRAM_CHART_WIDTH + self.HISTOGRAM_GRAPH_PADDING * 2
        chart_box_height = self.HISTOGRAM_CHART_HEIGHT + self.HISTOGRAM_GRAPH_PADDING * 2
        axis_y = self.HISTOGRAM_GRAPH_PADDING + self.HISTOGRAM_BAR_MAX_HEIGHT + 5
        zero_offset = self._histogram_display_offset(histogram.get("zero_fraction", 0.5))
        mean_offset = self._histogram_display_offset(histogram.get("mean_fraction", 0.5))
        status_bins = []
        with ui.HStack(height=chart_box_height, spacing=0):
            ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)
            with ui.ZStack(width=chart_box_width, height=chart_box_height):
                if rectangle:
                    rectangle(style=self._geometry_histogram_graph_box_style())
                with ui.HStack(width=chart_box_width, height=chart_box_height, spacing=0):
                    ui.Spacer(width=self.HISTOGRAM_GRAPH_PADDING)
                    chart_widget = ui.ZStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT)
                    with chart_widget:
                        if rectangle:
                            with ui.VStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT, spacing=0):
                                ui.Spacer(height=axis_y)
                                rectangle(width=self.HISTOGRAM_CHART_WIDTH, height=2, style={"background_color": 0xFF000000})
                                ui.Spacer()
                            with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT, spacing=0):
                                ui.Spacer(width=max(0, zero_offset - 1))
                                rectangle(width=2, height=axis_y + 2, style={"background_color": 0xFF000000})
                                ui.Spacer()
                        with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT, spacing=spacing):
                            display_count = len(bins)
                            display_x = 0
                            for display_index, (bin_info, bar_width) in enumerate(zip(bins, bar_widths)):
                                bar_height = 0
                                if int(bin_info.get("count", 0)) > 0:
                                    bar_height = max(
                                        2,
                                        int(self.HISTOGRAM_BAR_MAX_HEIGHT * float(bin_info.get("count", 0)) / max_count),
                                    )
                                with ui.ZStack(width=bar_width, height=self.HISTOGRAM_CHART_HEIGHT):
                                    with ui.VStack(width=bar_width, height=self.HISTOGRAM_CHART_HEIGHT, spacing=0):
                                        ui.Spacer(height=max(0, self.HISTOGRAM_BAR_MAX_HEIGHT - bar_height + 4))
                                        if rectangle and bar_height:
                                            rectangle(
                                                width=bar_width,
                                                height=bar_height,
                                                style={"background_color": self._rgba_to_ui_color(bin_info["color"])},
                                            )
                                        elif bar_height:
                                            ui.Label("", width=bar_width, height=bar_height)
                                        else:
                                            ui.Spacer(height=2)
                                    status_bins.append(
                                        {
                                            "bin_info": dict(bin_info),
                                            "display_x": float(display_x),
                                            "width": float(bar_width),
                                        }
                                    )
                                display_x += bar_width + spacing
                        if rectangle:
                            with ui.VStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT, spacing=0):
                                ui.Spacer(height=axis_y + 2)
                                with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH, height=6, spacing=0):
                                    ui.Spacer(width=max(0, mean_offset - 4))
                                    self._histogram_mean_marker()
                                    ui.Spacer()
                                ui.Spacer()
                    self._register_histogram_status_region(result_id, chart_widget, status_bins)
                    ui.Spacer(width=self.HISTOGRAM_GRAPH_PADDING)
                self._build_histogram_status_label(result_id)
            ui.Spacer(width=self.HISTOGRAM_PANEL_PADDING)

    def _build_histogram_status_label(self, result_id=None):
        status_height = self.HISTOGRAM_CHART_HEIGHT + self.HISTOGRAM_GRAPH_PADDING * 2
        with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH + self.HISTOGRAM_GRAPH_PADDING * 2, height=status_height, spacing=0):
            ui.Spacer(width=self.HISTOGRAM_GRAPH_PADDING)
            with ui.VStack(width=self.HISTOGRAM_CHART_WIDTH, height=status_height, spacing=0):
                ui.Spacer(height=status_height - 12)
                with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH, height=12, spacing=0):
                    ui.Spacer(width=6)
                    left_label = ui.Label(
                        "",
                        width=132,
                        height=12,
                        style=self._histogram_status_label_style(),
                    )
                    ui.Spacer()
                    right_label = ui.Label(
                        "",
                        width=142,
                        height=12,
                        style=self._histogram_status_label_style(),
                    )
                    ui.Spacer(width=2)
            ui.Spacer(width=self.HISTOGRAM_GRAPH_PADDING)
        if result_id is not None:
            self._histogram_status_labels[result_id] = {
                "left": left_label,
                "right": right_label,
            }
        return left_label, right_label

    def _register_histogram_status_region(self, result_id, chart_widget, bins):
        if result_id is None or chart_widget is None:
            return
        self._histogram_status_regions.append(
            {
                "chart": chart_widget,
                "result_id": result_id,
                "bins": tuple(bins or ()),
            }
        )

    def _poll_histogram_status(self):
        if self._histogram_status_blocked():
            self._set_histogram_status_text(None, "")
            return
        point = self._current_mouse_position()
        if point is None:
            self._set_histogram_status_text(None, "")
            return
        hit = self._histogram_status_hit_at(point[0], point[1])
        if hit is None:
            self._set_histogram_status_text(None, "")
            return
        self._set_histogram_status_text(hit.get("result_id"), self._histogram_bin_tooltip(hit.get("bin_info", {})))

    def _histogram_status_blocked(self):
        if getattr(self, "_geometries_scroll_drag_active", False):
            return True
        if self._is_modal_or_overlay_visible():
            return True
        return False

    def _histogram_status_hit_at(self, x, y):
        for region in getattr(self, "_histogram_status_regions", ()):
            rect = self._screen_rect(region.get("chart"))
            if rect is None:
                continue
            left, top, width, height = rect
            if not (left <= float(x) < left + width and top <= float(y) < top + height):
                continue
            local_x = max(0.0, min(width, float(x) - left))
            chart_x = local_x * float(self.HISTOGRAM_CHART_WIDTH) / max(width, 1.0)
            for bin_region in region.get("bins", ()):
                start = float(bin_region.get("display_x") or 0.0)
                end = start + max(0.0, float(bin_region.get("width") or 0.0))
                if start <= chart_x < end:
                    return {
                        "result_id": region.get("result_id"),
                        "bin_info": bin_region.get("bin_info") or {},
                    }
        return None

    def _set_histogram_status_text(self, result_id, text):
        text = str(text or "")
        key = (result_id, text)
        if getattr(self, "_histogram_status_key", None) == key:
            return False
        self._histogram_status_key = key
        updated = False
        left_text, right_text = self._histogram_status_text_parts(text)
        for label_result_id, labels in getattr(self, "_histogram_status_labels", {}).items():
            active = result_id is not None and label_result_id == result_id
            next_left = left_text if active else ""
            next_right = right_text if active else ""
            updated = self._set_label_text(labels.get("left"), next_left) or updated
            updated = self._set_label_text(labels.get("right"), next_right) or updated
        return updated

    def _histogram_status_text_parts(self, text):
        lines = str(text or "").splitlines()
        left = lines[0] if lines else ""
        right = lines[1] if len(lines) > 1 else ""
        if len(lines) > 2:
            right = " ".join(lines[1:])
        return left, right

    def _set_label_text(self, label, text):
        if label is None:
            return False
        try:
            if getattr(label, "text", None) == text:
                return False
            label.text = text
            return True
        except Exception:
            return False

    def _histogram_status_label_style(self):
        return {
            "color": 0xFFE6E6E6,
            "font_size": 10,
        }

    def _build_geometry_histogram_details(self, histogram):
        with ui.VStack(width=258, height=98, spacing=0):
            self._histogram_detail_row(
                "Samples Used",
                f"{histogram['count']:,} / {histogram.get('source_count', histogram['count']):,} "
                f"(unused: {histogram.get('excluded_count', 0):,})",
            )
            self._histogram_detail_row("Mean", self._format_scientific_metric(histogram["mean"]))
            self._histogram_detail_row("Std Dev", self._format_scientific_metric(histogram["sigma"]))
            self._histogram_detail_row("Minimum", self._format_metric(histogram["min"]))
            self._histogram_detail_row("Maximum", self._format_metric(histogram["max"]))
            ui.Spacer(height=self.HISTOGRAM_PANEL_PADDING)

    def _histogram_detail_row(self, name, value):
        with ui.HStack(height=18, spacing=6):
            ui.Label(name, width=92)
            ui.Label(str(value), width=160)

    def _histogram_bin_hit_region(
        self,
        bin_info,
        width,
        result_id=None,
        display_index=0,
        display_count=0,
        display_x=0,
    ):
        rectangle = getattr(ui, "Rectangle", None)
        hit_rect = None
        tooltip = self._histogram_bin_tooltip(bin_info)
        if rectangle:
            hit_rect = rectangle(
                width=width,
                height=self.HISTOGRAM_CHART_HEIGHT,
                style={"background_color": 0x00000000},
            )
        else:
            hit_rect = ui.Label(
                "",
                width=width,
                height=self.HISTOGRAM_CHART_HEIGHT,
            )
        self._histogram_hit_regions.append(
            {
                "rect": hit_rect,
                "bin_info": dict(bin_info),
                "result_id": result_id,
                "display_index": int(display_index or 0),
                "display_count": int(display_count or 0),
                "display_x": float(display_x or 0.0),
                "width": float(width or 0.0),
            }
        )

    def _poll_histogram_hover(self):
        if self._geometry_hover_events_blocked():
            self._clear_histogram_hover_state()
            return
        point = self._current_mouse_position()
        if point is None:
            self._clear_histogram_hover_state()
            return
        hit = self._histogram_hit_region_at(point[0], point[1])
        if hit is None:
            self._clear_histogram_hover_state()
            return
        bin_info = dict(hit["bin_info"])
        key = self._histogram_bin_hover_key(bin_info)
        result_id = hit.get("result_id")
        mouse_x, mouse_y = hit["mouse"]
        changed = (
            getattr(self, "_hovered_histogram_bin_key", None) != key
            or getattr(self, "_hovered_histogram_result_id", None) != result_id
            or abs(float(getattr(self, "_hovered_histogram_mouse_x", mouse_x) or 0.0) - mouse_x) > 1.0
            or abs(float(getattr(self, "_hovered_histogram_mouse_y", mouse_y) or 0.0) - mouse_y) > 1.0
        )
        if not changed:
            return
        self._hovered_histogram_bin = bin_info
        self._hovered_histogram_bin_key = key
        self._hovered_histogram_result_id = result_id
        self._hovered_histogram_display_index = int(hit.get("display_index") or 0)
        self._hovered_histogram_display_count = int(hit.get("display_count") or 0)
        self._hovered_histogram_mouse_x = mouse_x
        self._hovered_histogram_mouse_y = mouse_y
        self._refresh_histogram_tooltip_widgets()

    def _histogram_hit_region_at(self, x, y):
        for region in getattr(self, "_histogram_hit_regions", ()):
            rect = self._screen_rect(region.get("rect"))
            if rect is None:
                continue
            left, top, width, height = rect
            if not (left <= float(x) < left + width and top <= float(y) < top + height):
                continue
            local_x = max(0.0, min(width, float(x) - left))
            local_y = max(0.0, min(height, float(y) - top))
            display_x = float(region.get("display_x") or 0.0)
            region_width = max(1.0, float(region.get("width") or width or 1.0))
            return {
                **region,
                "mouse": (
                    max(0.0, min(float(self.HISTOGRAM_CHART_WIDTH), display_x + local_x * region_width / max(width, 1.0))),
                    max(0.0, min(float(self.HISTOGRAM_CHART_HEIGHT), local_y)),
                ),
            }
        self._queue_geometries_window_refresh()

    def _clear_histogram_hover_state(self):
        had_hover = getattr(self, "_hovered_histogram_bin", None) is not None
        self._hovered_histogram_bin = None
        self._hovered_histogram_bin_key = None
        self._hovered_histogram_result_id = None
        self._hovered_histogram_display_index = 0
        self._hovered_histogram_display_count = 0
        self._hovered_histogram_mouse_x = None
        self._hovered_histogram_mouse_y = None
        if had_hover:
            self._refresh_histogram_tooltip_widgets()
        return had_hover

    def _on_histogram_bin_hovered(
        self,
        hovered,
        bin_info,
        result_id=None,
        display_index=0,
        display_count=0,
        display_x=0,
        width=0,
    ):
        if hovered and self._geometry_hover_events_blocked():
            return
        key = self._histogram_bin_hover_key(bin_info)
        if hovered:
            self._hovered_histogram_bin = dict(bin_info)
            self._hovered_histogram_bin_key = key
            self._hovered_histogram_result_id = result_id
            self._hovered_histogram_display_index = int(display_index or 0)
            self._hovered_histogram_display_count = int(display_count or 0)
            self._hovered_histogram_mouse_x = self._histogram_default_mouse_x(display_x, width)
            self._hovered_histogram_mouse_y = self.HISTOGRAM_TOOLTIP_HEIGHT
        elif (
            getattr(self, "_hovered_histogram_bin_key", None) == key
            and getattr(self, "_hovered_histogram_result_id", None) == result_id
        ):
            self._hovered_histogram_bin = None
            self._hovered_histogram_bin_key = None
            self._hovered_histogram_result_id = None
            self._hovered_histogram_display_index = 0
            self._hovered_histogram_display_count = 0
            self._hovered_histogram_mouse_x = None
            self._hovered_histogram_mouse_y = None
        self._queue_geometries_window_refresh()

    def _on_histogram_bin_moved(
        self,
        bin_info,
        result_id=None,
        display_index=0,
        display_count=0,
        display_x=0,
        width=0,
        hit_rect=None,
        *args,
    ):
        if self._geometry_hover_events_blocked():
            return
        position = self._histogram_mouse_chart_position(args, hit_rect, display_x, width)
        if position is None:
            return
        self._hovered_histogram_bin = dict(bin_info)
        self._hovered_histogram_bin_key = self._histogram_bin_hover_key(bin_info)
        self._hovered_histogram_result_id = result_id
        self._hovered_histogram_display_index = int(display_index or 0)
        self._hovered_histogram_display_count = int(display_count or 0)
        self._hovered_histogram_mouse_x = position[0]
        self._hovered_histogram_mouse_y = position[1]
        self._queue_geometries_window_refresh()

    def _histogram_mouse_chart_position(self, args, hit_rect, display_x, width):
        position = self._mouse_position_from_args(args)
        if position is None:
            return None
        x, y = position
        width = max(1.0, float(width or 1.0))
        local_x = float(x)
        local_y = float(y)
        if not (0.0 <= local_x <= width):
            left = float(getattr(hit_rect, "screen_position_x", 0.0) or 0.0)
            local_x = float(x) - left
        if not (0.0 <= local_y <= self.HISTOGRAM_CHART_HEIGHT):
            top = float(getattr(hit_rect, "screen_position_y", 0.0) or 0.0)
            local_y = float(y) - top
        chart_x = max(0.0, min(float(self.HISTOGRAM_CHART_WIDTH), float(display_x or 0.0) + max(0.0, min(width, local_x))))
        chart_y = max(0.0, min(float(self.HISTOGRAM_CHART_HEIGHT), local_y))
        return chart_x, chart_y

    def _histogram_default_mouse_x(self, display_x, width):
        return max(0.0, min(float(self.HISTOGRAM_CHART_WIDTH), float(display_x or 0.0) + max(1.0, float(width or 1.0)) * 0.5))

    def _histogram_bin_hover_key(self, bin_info):
        return (
            round(float(bin_info.get("start", 0.0) or 0.0), 12),
            round(float(bin_info.get("end", 0.0) or 0.0), 12),
            int(bin_info.get("count", 0) or 0),
        )

    def _build_histogram_tooltip_overlay(self, result_id=None):
        rectangle = getattr(ui, "Rectangle", None)
        frame_factory = getattr(ui, "Frame", None)
        if frame_factory is None:
            return
        height = self.HISTOGRAM_TOOLTIP_HEIGHT
        width = self.HISTOGRAM_CHART_WIDTH - self.HISTOGRAM_TOOLTIP_MARGIN * 2
        with ui.VStack(width=self.HISTOGRAM_CHART_WIDTH, height=self.HISTOGRAM_CHART_HEIGHT, spacing=0):
            top_spacer = ui.Spacer(height=0)
            with ui.HStack(width=self.HISTOGRAM_CHART_WIDTH, height=height, spacing=0):
                left_spacer = ui.Spacer(width=0)
                frame = frame_factory(width=width, height=height)
                ui.Spacer()
            ui.Spacer()
        with frame:
            with ui.ZStack(width=width, height=height):
                if rectangle:
                    rectangle(style=self._histogram_tooltip_box_style())
                with ui.VStack(width=width, height=height, spacing=0):
                    ui.Spacer(height=5)
                    with ui.HStack(width=width, height=32, spacing=0):
                        ui.Spacer(width=8)
                        label = ui.Label(
                            "",
                            width=max(1, width - 16),
                            height=32,
                            style=self._histogram_tooltip_label_style(),
                        )
                        ui.Spacer(width=8)
                    ui.Spacer()
        self._histogram_tooltip_widgets[result_id] = {
            "frame": frame,
            "label": label,
            "top_spacer": top_spacer,
            "left_spacer": left_spacer,
            "width": width,
        }
        self._set_widget_visible(frame, False)

    def _refresh_histogram_tooltip_widgets(self):
        hovered_result_id = getattr(self, "_hovered_histogram_result_id", None)
        bin_info = getattr(self, "_hovered_histogram_bin", None)
        for result_id, widgets in getattr(self, "_histogram_tooltip_widgets", {}).items():
            visible = bool(bin_info and result_id == hovered_result_id)
            frame = widgets.get("frame")
            self._set_widget_visible(frame, visible)
            if not visible:
                continue
            tooltip = self._histogram_bin_tooltip(bin_info)
            width = self._histogram_tooltip_width(tooltip)
            height = self.HISTOGRAM_TOOLTIP_HEIGHT
            mouse_x = getattr(self, "_hovered_histogram_mouse_x", None)
            mouse_y = getattr(self, "_hovered_histogram_mouse_y", None)
            if mouse_x is None:
                display_index = max(0, int(getattr(self, "_hovered_histogram_display_index", 0) or 0))
                display_count = max(1, int(getattr(self, "_hovered_histogram_display_count", 0) or 0))
                mouse_x = self._histogram_default_mouse_x(
                    display_index * (self.HISTOGRAM_CHART_WIDTH / max(1, display_count)),
                    self.HISTOGRAM_CHART_WIDTH / max(1, display_count),
                )
            if mouse_y is None:
                mouse_y = self.HISTOGRAM_TOOLTIP_HEIGHT
            left = self._histogram_tooltip_left(mouse_x, width)
            top = self._histogram_tooltip_top(mouse_y, height)
            self._set_widget_dimension(widgets.get("left_spacer"), "width", left)
            self._set_widget_dimension(widgets.get("top_spacer"), "height", top)
            self._set_widget_dimension(frame, "width", width)
            label = widgets.get("label")
            if label is not None:
                try:
                    label.text = tooltip
                except Exception:
                    pass
                self._set_widget_dimension(label, "width", max(1, width - 16))

    def _set_widget_visible(self, widget, visible):
        if widget is None:
            return False
        try:
            widget.visible = bool(visible)
            return True
        except Exception:
            return False

    def _histogram_tooltip_width(self, tooltip):
        text = str(tooltip or "")
        line_length = max((len(line) for line in text.splitlines()), default=0)
        width = 18 + line_length * 6
        return max(118, min(self.HISTOGRAM_CHART_WIDTH - self.HISTOGRAM_TOOLTIP_MARGIN * 2, int(width)))

    def _histogram_tooltip_left(self, mouse_x, width):
        try:
            mouse_x = float(mouse_x)
        except (TypeError, ValueError):
            mouse_x = 0.0
        left = mouse_x + self.HISTOGRAM_TOOLTIP_MARGIN
        if left + width > self.HISTOGRAM_CHART_WIDTH - self.HISTOGRAM_TOOLTIP_MARGIN:
            left = mouse_x - width - self.HISTOGRAM_TOOLTIP_MARGIN
        return max(self.HISTOGRAM_TOOLTIP_MARGIN, min(self.HISTOGRAM_CHART_WIDTH - width - self.HISTOGRAM_TOOLTIP_MARGIN, int(round(left))))

    def _histogram_tooltip_top(self, mouse_y, height):
        try:
            mouse_y = float(mouse_y)
        except (TypeError, ValueError):
            mouse_y = 0.0
        top = mouse_y + self.HISTOGRAM_TOOLTIP_MARGIN
        if top + height > self.HISTOGRAM_CHART_HEIGHT - self.HISTOGRAM_TOOLTIP_MARGIN:
            top = mouse_y - height - self.HISTOGRAM_TOOLTIP_MARGIN
        return max(self.HISTOGRAM_TOOLTIP_MARGIN, min(self.HISTOGRAM_CHART_HEIGHT - height - self.HISTOGRAM_TOOLTIP_MARGIN, int(round(top))))

    def _histogram_bin_tooltip(self, bin_info):
        count = int(bin_info.get("count", 0) or 0)
        percent = self._format_histogram_percent(bin_info.get("percent", 0.0))
        return f"Count: {count:,}pts. ({percent})"

    def _format_histogram_percent(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "n/a"
        return f"{value:.2f}%"

    def _format_histogram_value(self, value):
        try:
            return f"{float(value):.1e}"
        except (TypeError, ValueError):
            return "n/a"

    def _format_histogram_sigma_probability(self, value):
        try:
            z = abs(float(value))
        except (TypeError, ValueError):
            return "n/a"
        probability = math.erf(z / math.sqrt(2.0)) * 100.0
        return f"{probability:.1f}%"

    def _histogram_tooltip_box_style(self):
        return {
            "background_color": self._rgba_to_ui_color(self._histogram_tooltip_background_color()),
            "border_color": 0xCC303030,
            "border_width": 1,
            "border_radius": 3,
        }

    def _histogram_tooltip_label_style(self):
        return {
            "color": self._rgba_to_ui_color(self._histogram_tooltip_text_color()),
            "font_size": 13,
        }

    def _histogram_tooltip_background_color(self):
        if self._has_color_models("histogram_tooltip_background"):
            return self._read_color("histogram_tooltip_background")
        return list(self.HISTOGRAM_TOOLTIP_BACKGROUND_COLOR)

    def _histogram_tooltip_text_color(self):
        if self._has_color_models("histogram_tooltip_text"):
            return self._read_color("histogram_tooltip_text")
        return list(self.HISTOGRAM_TOOLTIP_TEXT_COLOR)

    def _has_color_models(self, prefix):
        return all(f"{prefix}_{channel}" in self._models for channel in ("r", "g", "b", "a", "brightness"))

    def _geometry_histogram_box_style(self):
        return {
            "background_color": 0x221B1E24,
            "border_color": 0xFF5A5A5A,
            "border_width": 1,
            "border_radius": 3,
        }

    def _geometry_histogram_graph_box_style(self):
        return {
            "background_color": 0x22000000,
            "border_color": 0xFF2C2C2C,
            "border_width": 1,
            "border_radius": 2,
        }

    def _histogram_display_offset(self, fraction):
        try:
            fraction = float(fraction)
        except Exception:
            fraction = 0.5
        display_fraction = max(0.0, min(1.0, fraction))
        return max(
            0,
            min(
                self.HISTOGRAM_CHART_WIDTH - 1,
                int(math.floor(display_fraction * (self.HISTOGRAM_CHART_WIDTH - 1) + 0.5)),
            ),
        )

    def _histogram_bar_widths(self, count, chart_width, spacing):
        count = max(0, int(count or 0))
        if count <= 0:
            return []
        spacing_total = max(0, count - 1) * max(0, int(spacing or 0))
        available = max(float(count), float(chart_width) - spacing_total)
        width = available / count
        return [width for _index in range(count)]

    def _histogram_mean_marker(self):
        rectangle = getattr(ui, "Rectangle", None)
        if rectangle:
            widths = (2, 4, 6, 8)
            with ui.VStack(width=8, height=6, spacing=0):
                for width in widths:
                    with ui.HStack(width=8, height=1, spacing=0):
                        ui.Spacer(width=max(0, int((8 - width) * 0.5)))
                        rectangle(width=width, height=1, style={"background_color": 0xFFFFFFFF})
                        ui.Spacer()
        else:
            ui.Label("^", width=8, height=6)

    def _geometry_distance_histogram(self, result):
        state = getattr(self, "_state", None)
        point_cloud = getattr(state, "cloud", None)
        viewport = getattr(self, "_viewport", None)
        if point_cloud is None:
            return None
        histogram_builder = getattr(viewport_module, "build_inlier_distance_histogram", None)
        if not callable(histogram_builder):
            return None
        result_id = getattr(result, "id", "")
        bin_count = self._geometry_histogram_bin_count(result_id)
        native_picker = getattr(viewport, "_native_picker", None)
        negative_color = getattr(viewport, "inlier_negative_color", None)
        zero_color = getattr(viewport, "inlier_zero_color", None)
        positive_color = getattr(viewport, "inlier_positive_color", None)
        negative_sigma = getattr(viewport, "inlier_negative_sigma", -1.0)
        positive_sigma = getattr(viewport, "inlier_positive_sigma", 1.0)
        cache_key = self._geometry_distance_histogram_cache_key(
            histogram_builder,
            result,
            point_cloud,
            native_picker,
            bin_count,
            negative_color,
            zero_color,
            positive_color,
            negative_sigma,
            positive_sigma,
        )
        if (
            getattr(self, "_geometry_histogram_cache_result", None) is result
            and getattr(self, "_geometry_histogram_cache_key", None) == cache_key
        ):
            return getattr(self, "_geometry_histogram_cache_value", None)
        histogram = histogram_builder(
            point_cloud,
            result,
            bin_count=bin_count,
            native_picker=native_picker,
            negative_color=negative_color,
            zero_color=zero_color,
            positive_color=positive_color,
            negative_sigma=negative_sigma,
            positive_sigma=positive_sigma,
        )
        self._geometry_histogram_cache_result = result
        self._geometry_histogram_cache_key = cache_key
        self._geometry_histogram_cache_value = histogram
        return histogram

    def _geometry_distance_histogram_cache_key(
        self,
        histogram_builder,
        result,
        point_cloud,
        native_picker,
        bin_count,
        negative_color,
        zero_color,
        positive_color,
        negative_sigma,
        positive_sigma,
    ):
        point_buffer = getattr(point_cloud, "point_buffer", None)
        inlier_indices = getattr(result, "inlier_indices", None)
        try:
            inlier_count = len(inlier_indices) if inlier_indices is not None else 0
        except Exception:
            inlier_count = None
        return (
            id(histogram_builder),
            getattr(result, "active_generation", None),
            getattr(result, "seed_index", None),
            id(inlier_indices),
            inlier_count,
            id(point_cloud),
            getattr(point_cloud, "count", None),
            id(point_buffer),
            id(native_picker),
            bin_count,
            self._histogram_color_cache_key(negative_color),
            self._histogram_color_cache_key(zero_color),
            self._histogram_color_cache_key(positive_color),
            self._float_cache_key(negative_sigma),
            self._float_cache_key(positive_sigma),
        )

    def _histogram_color_cache_key(self, color):
        if color is None:
            return None
        try:
            return tuple(float(channel) for channel in color)
        except Exception:
            return id(color)

    def _float_cache_key(self, value):
        try:
            return float(value)
        except Exception:
            return value

    def _clear_geometry_distance_histogram_cache(self):
        self._geometry_histogram_cache_result = None
        self._geometry_histogram_cache_key = None
        self._geometry_histogram_cache_value = None

    def _rgba_to_ui_color(self, color):
        rgba = list(color or [1.0, 1.0, 1.0, 1.0])
        while len(rgba) < 4:
            rgba.append(1.0)
        channels = [max(0, min(255, int(round(float(channel) * 255.0)))) for channel in rgba[:4]]
        return (channels[3] << 24) | (channels[2] << 16) | (channels[1] << 8) | channels[0]

    def _geometry_histogram_bin_count(self, result_id):
        counts = getattr(self, "_geometry_histogram_bin_counts", None)
        if counts is None:
            self._geometry_histogram_bin_counts = {}
            counts = self._geometry_histogram_bin_counts
        value = counts.get(result_id, getattr(viewport_module, "INLIER_DISTANCE_HISTOGRAM_BINS", 35))
        return self._normalize_geometry_histogram_bin_count(value)

    def _normalize_geometry_histogram_bin_count(self, value):
        minimum = getattr(viewport_module, "INLIER_DISTANCE_HISTOGRAM_MIN_BINS", 23)
        maximum = getattr(viewport_module, "INLIER_DISTANCE_HISTOGRAM_MAX_BINS", 47)
        try:
            count = int(value)
        except Exception:
            count = getattr(viewport_module, "INLIER_DISTANCE_HISTOGRAM_BINS", 35)
        count = max(minimum, count)
        count = min(maximum, count)
        if count % 2 == 0:
            count += 1 if count < maximum else -1
        return count

    def _adjust_geometry_histogram_bins(self, result_id, delta):
        counts = getattr(self, "_geometry_histogram_bin_counts", None)
        if counts is None:
            self._geometry_histogram_bin_counts = {}
            counts = self._geometry_histogram_bin_counts
        current = self._geometry_histogram_bin_count(result_id)
        next_count = self._normalize_geometry_histogram_bin_count(current + int(delta))
        if next_count == current:
            return
        counts[result_id] = next_count
        self._queue_geometries_window_refresh()

    def _geometry_histogram_details_visible(self, result_id):
        expanded = getattr(self, "_geometry_histogram_details_expanded", None)
        return bool(expanded and expanded.get(result_id, False))

    def _toggle_geometry_histogram_details(self, result_id):
        expanded = getattr(self, "_geometry_histogram_details_expanded", None)
        if expanded is None:
            self._geometry_histogram_details_expanded = {}
            expanded = self._geometry_histogram_details_expanded
        expanded[result_id] = not self._geometry_histogram_details_visible(result_id)
        self._queue_geometries_window_refresh()

    def _build_transactions_window(self):
        with ui.VStack(spacing=6):
            ui.Spacer(height=8)
            count = len(self._state.transaction_log) if self._state else 0
            current = self._state.transaction_index if self._state else 0
            self._transaction_summary_label = ui.Label(f"State {current} / {count}", height=22)
            if not self._state:
                ui.Label("No point cloud is loaded.", word_wrap=True)
                ui.Spacer()
                return

            scrolling_frame = getattr(ui, "ScrollingFrame", None)
            if scrolling_frame:
                with scrolling_frame():
                    self._build_transactions_content()
            else:
                self._build_transactions_content()

    def _build_transactions_content(self):
        with ui.VStack(spacing=4):
            self._transaction_state_row(0, "Initial state", "Loaded point cloud state")
            for index, transaction in enumerate(self._state.transaction_log, start=1):
                self._transaction_state_row(
                    index,
                    self._transaction_title(index, transaction),
                    self._transaction_detail(transaction),
                )

    def _transaction_state_row(self, index, title, detail):
        current = bool(self._state and self._state.transaction_index == index)
        label = f"> {title}" if current else title
        button = ui.Button(label, height=28, clicked_fn=lambda value=index: self._go_to_transaction_index(value))
        try:
            button.enabled = not current
        except Exception:
            pass
        ui.Label(detail, height=20, word_wrap=True)

    def _transaction_title(self, index, transaction):
        if getattr(transaction, "event_type", "") == TRANSACTION_PARAMETER_CHANGE:
            label = self._parameter_transaction_label(transaction)
            return f"{index}. Parameter: {label}" if label else f"{index}. Parameter"
        action = {
            "detection_apply": "Apply",
            "delete_geometry": "Delete",
            "cancel_detection": "Cancel",
            "reset_detection": "Reset",
            "global_visibility": "Visibility",
            "geometry_visibility": "Geometry Visibility",
            "parameter_change": "Parameter",
            "camera_change": "Camera",
        }.get(getattr(transaction, "event_type", ""), getattr(transaction, "event_type", "Transaction"))
        result_id = getattr(transaction, "result_id", None)
        if result_id:
            return f"{index}. {action}: {result_id}"
        return f"{index}. {action}"

    def _transaction_detail(self, transaction):
        before = getattr(transaction, "generation_before", 0)
        after = getattr(transaction, "generation_after", 0)
        record = getattr(transaction, "detection_record", None)
        records = getattr(transaction, "detection_records", None) or []
        if record:
            return f"generation {before} -> {after}, inliers {len(getattr(record, 'removed_indices', []) or [])}"
        if records:
            return f"generation {before} -> {after}, cleared {len(records)} geometries"
        state_before = getattr(transaction, "state_before", None)
        state_after = getattr(transaction, "state_after", None)
        if getattr(transaction, "event_type", "") == TRANSACTION_PARAMETER_CHANGE:
            return self._parameter_transaction_detail(state_before, state_after)
        if state_before is not None or state_after is not None:
            changed = sorted(set((state_before or {}).keys()) | set((state_after or {}).keys()))
            return f"state fields: {', '.join(changed)}" if changed else "state change"
        return f"generation {before} -> {after}"

    def _parameter_transaction_label(self, transaction):
        state_before = getattr(transaction, "state_before", None)
        state_after = getattr(transaction, "state_after", None)
        changed = self._parameter_changed_fields(state_before, state_after)
        if not changed:
            return ""
        return self._parameter_field_label(changed[0], include_component=False)

    def _parameter_transaction_detail(self, state_before, state_after):
        changed = self._parameter_changed_fields(state_before, state_after)
        if not changed:
            return "parameter unchanged"
        fields = []
        for name in changed:
            before = (state_before or {}).get(name)
            after = (state_after or {}).get(name)
            fields.append(
                f"{self._parameter_field_label(name)}: "
                f"{self._format_parameter_value(before)} -> {self._format_parameter_value(after)}"
            )
        return "; ".join(fields)

    def _parameter_changed_fields(self, state_before, state_after):
        state_before = state_before or {}
        state_after = state_after or {}
        changed = [
            name
            for name in self._parameter_transaction_model_names()
            if state_before.get(name) != state_after.get(name)
        ]
        filtered = []
        for name in changed:
            if name.endswith("_slider_index"):
                base = name[: -len("_slider_index")]
                if base in changed:
                    continue
            filtered.append(name)
        return filtered

    def _parameter_field_label(self, name, include_component=True):
        component = None
        base = name
        if name.endswith("_slider_index"):
            base = name[: -len("_slider_index")]
            component = "slider"
        elif name.endswith("_min"):
            base = name[: -len("_min")]
            component = "min"
        elif name.endswith("_max"):
            base = name[: -len("_max")]
            component = "max"
        labels = {
            "detection_type": "Detection Type",
            "seed_radius": "Seed Radius",
            "measurement_accuracy": "Measurement Accuracy",
            "mean_distance": "Mean Distance",
            "radial_expansion": "Radial Expansion",
            "lateral_extension": "Lateral Extension",
        }
        label = labels.get(base, str(base).replace("_", " ").title())
        if include_component and component:
            return f"{label} {component}"
        return label

    def _format_parameter_value(self, value):
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def _is_geometry_collapsed(self, result_id):
        return bool(self._geometry_collapsed.get(result_id, False))

    def _toggle_geometry_collapsed(self, result_id):
        self._set_geometry_collapsed(result_id, not self._is_geometry_collapsed(result_id))
        self._queue_geometries_window_refresh()

    def _set_geometry_collapsed(self, result_id, collapsed):
        self._geometry_collapsed[result_id] = bool(collapsed)

    def _expand_all_geometries(self):
        self._set_all_geometries_collapsed(False)

    def _collapse_all_geometries(self):
        self._set_all_geometries_collapsed(True)

    def _set_all_geometries_collapsed(self, collapsed):
        if not self._state or not self._state.results:
            return
        self._geometry_collapsed = {
            result.id: bool(collapsed)
            for result in self._state.results
            if getattr(result, "id", None)
        }
        self._queue_geometries_window_refresh()

    def _set_all_geometry_visibility(self, field_name, visible):
        if field_name not in ("mesh_visible", "inliers_visible"):
            return
        if not self._state or not self._state.results:
            return
        before = self._all_geometry_visibility_state()
        visible = bool(visible)
        changed = False
        for result in self._state.results:
            result_id = getattr(result, "id", None)
            if not result_id:
                continue
            if bool(getattr(result, field_name, True)) == visible:
                continue
            self._set_geometry_visibility_field(result_id, field_name, visible)
            changed = True
        if not changed:
            return
        after = self._all_geometry_visibility_state()
        self._record_state_change_command(TRANSACTION_GEOMETRY_VISIBILITY, before, after)
        self._queue_geometries_window_refresh()

    def _build_tutorial_window(self):
        with ui.VStack(spacing=8):
            ui.Spacer(height=8)
            self._build_tutorial_section(
                "Mouse",
                (
                    ("Orbit / Roll", "Left drag orbits. Ctrl+left drag or right drag rolls."),
                    ("Pan / Zoom", "Middle drag pans. Mouse wheel zooms."),
                ),
            )
            self._build_tutorial_section(
                "Detection Workflow",
                (
                    ("Preview", "Hover a point to preview the probe circle."),
                    ("Seed", "Click a point to select the seed."),
                    ("Capture", "Capture selected preview with the toolbar or Ctrl+C."),
                ),
            )
            self._build_tutorial_section(
                "Keyboard",
                (
                    ("Clear / Undo", "Esc clears seed. Ctrl+Z undoes. Ctrl+Shift+Z redoes."),
                    ("Save", "Ctrl+S saves the workspace."),
                    ("Types", "Ctrl+` selects Auto. Ctrl+1-5 select Plane, Sphere, Cylinder, Cone, and Torus."),
                ),
            )
            ui.Spacer()

    def _build_tutorial_section(self, title, rows):
        height = self._tutorial_section_height(rows)
        zstack_cls = getattr(ui, "ZStack", None)
        rectangle_cls = getattr(ui, "Rectangle", None)
        if zstack_cls and rectangle_cls:
            with zstack_cls(height=height):
                rectangle_cls(height=height, style=self._tutorial_section_style())
                self._build_tutorial_section_content(title, rows, height)
            return
        self._build_tutorial_section_content(title, rows, height)

    def _build_tutorial_section_content(self, title, rows, height):
        with ui.HStack(height=height, spacing=0):
            ui.Spacer(width=self.TUTORIAL_SECTION_HORIZONTAL_PADDING)
            with ui.VStack(height=height, spacing=0):
                ui.Spacer(height=self.TUTORIAL_SECTION_PADDING)
                ui.Label(title, height=self.TUTORIAL_SECTION_HEADER_HEIGHT)
                ui.Spacer(height=2)
                for label, text in rows:
                    self._build_tutorial_row(label, text)
                ui.Spacer(height=self.TUTORIAL_SECTION_PADDING)
            ui.Spacer(width=self.TUTORIAL_SECTION_HORIZONTAL_PADDING)

    def _build_tutorial_row(self, label, text):
        with ui.HStack(height=self.TUTORIAL_ROW_HEIGHT, spacing=6):
            ui.Label(label, width=self.TUTORIAL_LABEL_WIDTH)
            ui.Label(text, word_wrap=True)

    def _tutorial_section_height(self, rows):
        return (
            self.TUTORIAL_SECTION_PADDING * 2
            + self.TUTORIAL_SECTION_HEADER_HEIGHT
            + 2
            + len(rows) * self.TUTORIAL_ROW_HEIGHT
        )

    def _tutorial_section_style(self):
        return {
            "background_color": 0x0,
            "border_color": self.PARAMETER_GROUP_BORDER_COLOR,
            "border_width": 1,
            "border_radius": 4,
        }

    def _build_debug_group_box_window(self):
        self._debug_group_box_models = self._new_debug_group_box_models()
        self._debug_group_status_label = None
        self._build_debug_group_box_content()

    def _build_debug_group_box_content(self):
        with ui.VStack(spacing=10):
            ui.Spacer(height=8)
            with BorderedGroupView(
                "Detection Inputs",
                row_count=4,
            ):
                self._build_debug_group_box_inputs()
            with BorderedGroupView(
                "Run State",
                row_heights=(
                    self.DEBUG_GROUP_BOX_STATUS_ROW_HEIGHT,
                    BorderedGroupView.DEFAULT_ROW_HEIGHT,
                    BorderedGroupView.DEFAULT_ROW_HEIGHT,
                ),
            ):
                self._build_debug_group_box_state()
            ui.Spacer()

    def _new_debug_group_box_models(self):
        model_cls = getattr(ui, "SimpleStringModel", None)
        models = {}
        for name, value in self._debug_group_box_defaults().items():
            models[name] = model_cls(value) if model_cls else value
        return models

    def _debug_group_box_defaults(self):
        return {
            "group_name": "Surface Candidate",
            "seed_index": "128",
            "surface_type": "Plane",
            "operator_note": "Debug note",
        }

    def _build_debug_group_box_inputs(self):
        self._debug_text_field_row("Group Name", "group_name")
        self._debug_text_field_row("Seed Index", "seed_index")
        self._debug_text_field_row("Surface Type", "surface_type")
        with ui.HStack(height=BorderedGroupView.DEFAULT_ROW_HEIGHT, spacing=6):
            ui.Button("Preview", clicked_fn=lambda: self._set_debug_group_status("Preview button clicked."))
            ui.Button("Capture", clicked_fn=lambda: self._set_debug_group_status("Capture button clicked."))

    def _build_debug_group_box_state(self):
        with ui.HStack(height=self.DEBUG_GROUP_BOX_STATUS_ROW_HEIGHT, spacing=6):
            ui.Label("Status", width=96)
            self._debug_group_status_label = ui.Label("Waiting for debug action.")
        self._debug_text_field_row("Note", "operator_note")
        with ui.HStack(height=BorderedGroupView.DEFAULT_ROW_HEIGHT, spacing=6):
            ui.Button("Apply", clicked_fn=lambda: self._set_debug_group_status("Apply button clicked."))
            ui.Button("Reset", clicked_fn=self._reset_debug_group_box_fields)

    def _debug_text_field_row(self, label, model_name):
        with ui.HStack(height=BorderedGroupView.DEFAULT_ROW_HEIGHT, spacing=6):
            ui.Label(label, width=96)
            field_cls = getattr(ui, "StringField", None)
            model = getattr(self, "_debug_group_box_models", {}).get(model_name)
            if field_cls and not isinstance(model, str):
                field_cls(model=model)
            else:
                ui.Label(self._debug_group_box_model_text(model_name))

    def _debug_group_box_model_text(self, model_name):
        model = getattr(self, "_debug_group_box_models", {}).get(model_name)
        if model is None:
            return ""
        for attribute in ("as_string", "as_str"):
            try:
                return str(getattr(model, attribute))
            except Exception:
                pass
        for method_name in ("get_value_as_string", "get_value"):
            method = getattr(model, method_name, None)
            if callable(method):
                try:
                    return str(method())
                except Exception:
                    pass
        return str(model)

    def _set_debug_group_status(self, text):
        label = getattr(self, "_debug_group_status_label", None)
        if label:
            label.text = text

    def _reset_debug_group_box_fields(self):
        models = getattr(self, "_debug_group_box_models", {})
        for name, value in self._debug_group_box_defaults().items():
            model = models.get(name)
            if isinstance(model, str):
                models[name] = value
                continue
            set_value = getattr(model, "set_value", None)
            if callable(set_value):
                try:
                    set_value(value)
                except Exception:
                    pass
        self._set_debug_group_status("Fields reset to defaults.")

    def _float_row(self, label, model, minimum=-100000.0, maximum=100000.0):
        with ui.HStack(height=26, spacing=6):
            ui.Label(label, width=72)
            ui.FloatDrag(model=model, min=minimum, max=maximum, step=0.01)

    def _vector_row(self, label, model_names):
        with ui.HStack(height=26, spacing=6):
            ui.Label(label, width=72)
            for name in model_names:
                ui.FloatDrag(model=self._models[name], min=-100000.0, max=100000.0, step=0.01)

    def _init_color_models(self, prefix, color):
        color = list(color or [1.0, 1.0, 1.0, 1.0])
        while len(color) < 4:
            color.append(1.0)
        self._models[f"{prefix}_r"] = ui.SimpleFloatModel(color[0])
        self._models[f"{prefix}_g"] = ui.SimpleFloatModel(color[1])
        self._models[f"{prefix}_b"] = ui.SimpleFloatModel(color[2])
        self._models[f"{prefix}_a"] = ui.SimpleFloatModel(color[3])
        self._models[f"{prefix}_brightness"] = ui.SimpleFloatModel(1.0)

    def _color_header(self, include_sigma=False):
        with ui.HStack(height=18, spacing=4):
            ui.Spacer(width=72)
            ui.Label("RGB", width=28)
            ui.Label("A", width=44)
            ui.Label("Br", width=50)
            if include_sigma:
                ui.Label("Sigma", width=58)

    def _color_controls(self, label, prefix, sigma_model=None, sigma_min=0.5, sigma_max=3.0):
        with ui.HStack(height=26, spacing=4):
            ui.Label(label, width=72)
            self._color_widget(prefix)
            ui.FloatDrag(
                model=self._models[f"{prefix}_a"],
                min=0.0,
                max=1.0,
                step=0.01,
                width=44,
            )
            ui.FloatDrag(
                model=self._models[f"{prefix}_brightness"],
                min=0.0,
                max=3.0,
                step=0.01,
                width=50,
            )
            if sigma_model is not None:
                ui.FloatDrag(
                    model=sigma_model,
                    min=sigma_min,
                    max=sigma_max,
                    step=0.1,
                    format="%.1f",
                    width=58,
                )
            else:
                ui.Spacer(width=58)

    def _color_widget(self, prefix):
        if not hasattr(ui, "ColorWidget"):
            for channel in ("r", "g", "b"):
                ui.FloatDrag(
                    model=self._models[f"{prefix}_{channel}"],
                    min=0.0,
                    max=1.0,
                    step=0.01,
                    width=44,
                )
            return
        widget = ui.ColorWidget(
            self._models[f"{prefix}_r"].as_float,
            self._models[f"{prefix}_g"].as_float,
            self._models[f"{prefix}_b"].as_float,
            width=28,
            height=22,
        )
        component_models = self._color_component_models(widget.model)
        if len(component_models) >= 3:
            for channel, model in zip(("r", "g", "b"), component_models[:3]):
                self._models[f"{prefix}_{channel}"] = model

    def _color_component_models(self, color_model):
        models = []
        try:
            items = color_model.get_item_children()
        except TypeError:
            items = color_model.get_item_children(None)
        for item in items:
            try:
                models.append(color_model.get_item_value_model(item))
            except TypeError:
                models.append(color_model.get_item_value_model(item, 0))
        return models

    def _range_float_row(self, label, name, framed=True):
        if not framed:
            self._range_float_row_content(label, name)
            return
        padding = self.RANGE_PARAMETER_GROUP_PADDING
        with ui.ZStack(height=76 + padding * 2):
            ui.Rectangle(style=self._range_parameter_group_style())
            with ui.VStack(height=76 + padding * 2, spacing=0):
                ui.Spacer(height=padding)
                with ui.HStack(height=76, spacing=0):
                    ui.Spacer(width=padding)
                    self._range_float_row_content(label, name)
                    ui.Spacer(width=padding)
                ui.Spacer(height=padding)

    def _range_float_row_content(self, label, name):
        minimum_model = self._range_edit_model(f"{name}_min")
        maximum_model = self._range_edit_model(f"{name}_max")
        value_model = self._range_edit_model(name)
        index_model = self._models[f"{name}_slider_index"]
        display_label = label.replace("\n", " ")
        with ui.VStack(height=76, spacing=2):
            with ui.HStack(height=24, spacing=6):
                ui.Label(f"{display_label}:", width=self.RANGE_PARAMETER_VALUE_LABEL_WIDTH, height=20)
                value_field = getattr(ui, "FloatField", ui.FloatDrag)
                value_field(
                    model=value_model,
                    step=self._range_slider_value_step(minimum_model.as_float, maximum_model.as_float),
                    format=self.RANGE_PARAMETER_FORMAT,
                    precision=self.RANGE_PARAMETER_PRECISION,
                    width=self.RANGE_PARAMETER_FIELD_WIDTH,
                )
            with ui.HStack(height=16, spacing=6):
                header_style = {"font_size": self.RANGE_PARAMETER_LABEL_FONT_SIZE}
                ui.Label("min", width=self.RANGE_PARAMETER_LABEL_WIDTH, height=16, style=header_style)
                ui.Spacer()
                ui.Label("max", width=self.RANGE_PARAMETER_LABEL_WIDTH, height=16, style=header_style)
            with ui.HStack(height=28, spacing=6):
                ui.FloatDrag(
                    model=minimum_model,
                    min=self.RANGE_PARAMETER_MINIMUM,
                    max=self.RANGE_PARAMETER_MAXIMUM,
                    step=self.RANGE_PARAMETER_MINIMUM_STEP,
                    format=self.RANGE_PARAMETER_FORMAT,
                    precision=self.RANGE_PARAMETER_PRECISION,
                    width=self.RANGE_PARAMETER_FIELD_WIDTH,
                    **self._parameter_control_mouse_kwargs(f"{name}_min"),
                )
                slider_count = self._range_slider_index_count(minimum_model.as_float, maximum_model.as_float)
                self._range_sliders[name] = ui.IntSlider(
                    model=index_model,
                    min=0,
                    max=slider_count,
                    step=1,
                    format="",
                    **self._parameter_control_mouse_kwargs(f"{name}_slider_index"),
                )
                self._range_sliders[name].enabled = maximum_model.as_float > minimum_model.as_float
                ui.FloatDrag(
                    model=maximum_model,
                    min=self.RANGE_PARAMETER_MINIMUM,
                    max=self.RANGE_PARAMETER_MAXIMUM,
                    step=self.RANGE_PARAMETER_MINIMUM_STEP,
                    format=self.RANGE_PARAMETER_FORMAT,
                    precision=self.RANGE_PARAMETER_PRECISION,
                    width=self.RANGE_PARAMETER_FIELD_WIDTH,
                    **self._parameter_control_mouse_kwargs(f"{name}_max"),
                )

    def _range_parameter_group_style(self):
        return {
            "background_color": 0x0,
            "border_color": self.PARAMETER_GROUP_BORDER_COLOR,
            "border_width": 1,
            "border_radius": 4,
        }

    def _int_row(self, label, model, minimum=0, maximum=10, framed=True, label_width=110, field_width=None, suffix=None):
        if not framed:
            self._int_row_content(
                label,
                model,
                minimum=minimum,
                maximum=maximum,
                label_width=label_width,
                field_width=field_width,
                suffix=suffix,
            )
            return
        padding = self.RANGE_PARAMETER_GROUP_PADDING
        with ui.ZStack(height=26 + padding * 2):
            ui.Rectangle(style=self._range_parameter_group_style())
            with ui.VStack(height=26 + padding * 2, spacing=0):
                ui.Spacer(height=padding)
                with ui.HStack(height=26, spacing=6):
                    ui.Spacer(width=padding)
                    self._int_row_content(
                        label,
                        model,
                        minimum=minimum,
                        maximum=maximum,
                        label_width=label_width,
                        field_width=field_width,
                        suffix=suffix,
                    )
                    ui.Spacer(width=padding)
                ui.Spacer(height=padding)

    def _int_row_content(self, label, model, minimum=0, maximum=10, label_width=110, field_width=None, suffix=None):
        with ui.HStack(height=26, spacing=6):
            ui.Label(label, width=label_width)
            kwargs = {"model": model, "min": minimum, "max": maximum, "step": 1}
            if field_width is not None:
                kwargs["width"] = field_width
            ui.IntDrag(**kwargs)
            if suffix:
                ui.Label(suffix, width=24)

    def _sticky_preview_timeout_row(self):
        with ui.HStack(height=26, spacing=6):
            ui.Label("Sticky Preview Timeout", width=150)
            ui.IntDrag(
                model=self._models["sticky_auto_preview_timeout_ms"],
                min=100,
                max=60000,
                step=1,
                width=60,
            )
            ui.Label("ms", width=24)

    def _int_slider_row(self, label, model, minimum=0, maximum=10, name=None, framed=True):
        int_slider = getattr(ui, "IntSlider", None)
        if int_slider is None:
            self._int_row(label, model, minimum=minimum, maximum=maximum, framed=framed)
            return
        if not framed:
            self._int_slider_row_content(label, model, int_slider, minimum=minimum, maximum=maximum, name=name)
            return
        padding = self.RANGE_PARAMETER_GROUP_PADDING
        with ui.ZStack(height=30 + padding * 2):
            ui.Rectangle(style=self._range_parameter_group_style())
            with ui.VStack(height=30 + padding * 2, spacing=0):
                ui.Spacer(height=padding)
                with ui.HStack(height=30, spacing=6):
                    ui.Spacer(width=padding)
                    self._int_slider_row_content(label, model, int_slider, minimum=minimum, maximum=maximum, name=name)
                    ui.Spacer(width=padding)
                ui.Spacer(height=padding)

    def _int_slider_row_content(self, label, model, int_slider, minimum=0, maximum=10, name=None):
        with ui.HStack(height=30, spacing=6):
            ui.Label(label, width=110)
            widget_kwargs = self._parameter_control_mouse_kwargs(name) if name else {}
            int_slider(model=model, min=minimum, max=maximum, step=1, **widget_kwargs)

    def _parameter_pad_row(self):
        x_name, y_name = self._parameter_pad_axis_pair()
        pad_key = self._parameter_pad_key(x_name, y_name)
        x_value = self._parameter_pad_model_value(x_name)
        y_value = self._parameter_pad_model_value(y_name)
        x_u, y_v = self._parameter_pad_display_position(x_name, y_name)
        handle_size = self.PARAMETER_PAD_HANDLE_SIZE
        handle_left = x_u * max(0, self.PARAMETER_PAD_SIZE - handle_size)
        handle_top = (1.0 - y_v) * max(0, self.PARAMETER_PAD_SIZE - handle_size)
        padding = self.RANGE_PARAMETER_GROUP_PADDING
        content_height = self.PARAMETER_PAD_SIZE + 58
        with ui.ZStack(height=content_height + padding * 2):
            ui.Rectangle(style=self._range_parameter_group_style())
            with ui.VStack(height=content_height + padding * 2, spacing=0):
                ui.Spacer(height=padding)
                with ui.HStack(height=content_height, spacing=0):
                    ui.Spacer(width=padding)
                    with ui.VStack(height=content_height, spacing=6):
                        with ui.HStack(height=self.PARAMETER_PAD_SIZE, spacing=8):
                            ui.Spacer()
                            with ui.VStack(width=self.PARAMETER_PAD_CONTROL_WIDTH, spacing=6):
                                self._parameter_pad_axis_dropdown("y", width=self.PARAMETER_PAD_CONTROL_WIDTH)
                                self._parameter_pad_value_labels["y"] = ui.Label(
                                    self._format_parameter_pad_value(y_name, y_value),
                                    height=18,
                                )
                                ui.Spacer()
                            with ui.ZStack(width=self.PARAMETER_PAD_SIZE, height=self.PARAMETER_PAD_SIZE):
                                ui.Rectangle(style=self._parameter_pad_style())
                                self._parameter_pad_center_guides()
                                with ui.VStack(width=self.PARAMETER_PAD_SIZE, height=self.PARAMETER_PAD_SIZE, spacing=0):
                                    vertical_spacer = ui.Spacer(height=handle_top)
                                    with ui.HStack(height=handle_size, spacing=0):
                                        horizontal_spacer = ui.Spacer(width=handle_left)
                                        ui.Rectangle(
                                            width=handle_size,
                                            height=handle_size,
                                            style=self._parameter_pad_handle_style(),
                                        )
                                rect = ui.Rectangle(
                                    style={"background_color": 0x00000000},
                                    opaque_for_mouse_events=True,
                                    mouse_pressed_fn=lambda *args, x=x_name, y=y_name: self._on_parameter_pad_pressed(x, y, *args),
                                    mouse_moved_fn=lambda *args, x=x_name, y=y_name: self._on_parameter_pad_moved(x, y, *args),
                                    mouse_released_fn=lambda *args, x=x_name, y=y_name: self._on_parameter_pad_released(x, y, *args),
                                )
                                self._parameter_pad_rects[pad_key] = rect
                                self._parameter_pad_handle_spacers[pad_key] = (horizontal_spacer, vertical_spacer)
                        with ui.HStack(height=48, spacing=8):
                            ui.Spacer()
                            with ui.VStack(width=self.PARAMETER_PAD_SIZE, spacing=4):
                                self._parameter_pad_axis_dropdown("x", width=self.PARAMETER_PAD_SIZE)
                                self._parameter_pad_value_labels["x"] = ui.Label(
                                    self._format_parameter_pad_value(x_name, x_value),
                                    height=18,
                                )
                    ui.Spacer(width=padding)
                ui.Spacer(height=padding)

    def _parameter_pad_axis_dropdown(self, axis, label=None, width=None):
        selected = self._parameter_pad_axis_parameter(axis)
        options = self._parameter_pad_axis_options_for(axis)
        selected_index = max(0, options.index(selected) if selected in options else 0)
        combo_box = getattr(ui, "ComboBox", None)
        width = width if width is not None else (self.PARAMETER_PAD_CONTROL_WIDTH if axis == "y" else self.PARAMETER_PAD_SIZE)
        with ui.HStack(height=24, spacing=0):
            if combo_box is None:
                ui.Button(
                    self._parameter_display_name(selected),
                    width=width,
                    clicked_fn=lambda current_axis=axis: self._cycle_parameter_pad_axis(current_axis),
                )
                return
            combo = combo_box(
                selected_index,
                *[self._parameter_display_name(option) for option in options],
                width=width,
            )
            model = getattr(combo, "model", None)
            if model is not None:
                self._parameter_pad_axis_models[axis] = model
                self._parameter_pad_axis_options[axis] = tuple(options)
                self._subscribe_parameter_pad_axis_model(axis, model)

    def _ensure_parameter_pad_axis_models(self):
        if not hasattr(self, "_parameter_pad_axes"):
            self._parameter_pad_axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
        if not hasattr(self, "_parameter_pad_axis_models"):
            self._parameter_pad_axis_models = {}
        if not hasattr(self, "_parameter_pad_axis_options"):
            self._parameter_pad_axis_options = {}
        self._ensure_distinct_parameter_pad_axes()
        for axis in ("x", "y"):
            self._parameter_pad_axis_model(axis)

    def _parameter_pad_axis_pair(self):
        self._ensure_distinct_parameter_pad_axes()
        return self._parameter_pad_axis_parameter("x"), self._parameter_pad_axis_parameter("y")

    def _parameter_pad_axis_parameter(self, axis):
        axes = getattr(self, "_parameter_pad_axes", None)
        if axes is None:
            axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
            self._parameter_pad_axes = axes
        value = axes.get(axis, self.PARAMETER_PAD_DEFAULT_AXES.get(axis))
        if value not in self.PARAMETER_PAD_PARAMETERS:
            value = self.PARAMETER_PAD_DEFAULT_AXES.get(axis, self.PARAMETER_PAD_PARAMETERS[0])
            axes[axis] = value
        return value

    def _other_parameter_pad_axis(self, axis):
        return "y" if axis == "x" else "x"

    def _parameter_pad_axis_options_for(self, axis):
        other = self._parameter_pad_axis_parameter(self._other_parameter_pad_axis(axis))
        options = [name for name in self.PARAMETER_PAD_PARAMETERS if name != other]
        current = self._parameter_pad_axis_parameter(axis)
        if current not in options:
            options.insert(0, current)
        if hasattr(self, "_parameter_pad_axis_options"):
            self._parameter_pad_axis_options[axis] = tuple(options)
        return tuple(options)

    def _parameter_pad_axis_model(self, axis):
        models = getattr(self, "_parameter_pad_axis_models", None)
        if models is None:
            models = {}
            self._parameter_pad_axis_models = models
        model = models.get(axis)
        if model is None:
            options = self._parameter_pad_axis_options_for(axis)
            selected = self._parameter_pad_axis_parameter(axis)
            model = ui.SimpleIntModel(max(0, options.index(selected) if selected in options else 0))
            models[axis] = model
            self._subscribe_parameter_pad_axis_model(axis, model)
        return model

    def _subscribe_parameter_pad_axis_model(self, axis, model):
        key = ("parameter_pad_axis", axis, id(model))
        if key in getattr(self, "_model_subscription_keys", set()):
            return False
        options = tuple(getattr(self, "_parameter_pad_axis_options", {}).get(axis, ()))
        if not options:
            options = self._parameter_pad_axis_options_for(axis)
        changed_fn = (
            lambda *args, current_axis=axis, current_model=model, current_options=options:
            self._on_parameter_pad_axis_changed(current_axis, current_model, current_options)
        )
        if hasattr(model, "add_item_changed_fn"):
            self._model_subscriptions.append(model.add_item_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        if hasattr(model, "subscribe_value_changed_fn"):
            self._model_subscriptions.append(model.subscribe_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        if hasattr(model, "add_value_changed_fn"):
            self._model_subscriptions.append(model.add_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        if hasattr(model, "subscribe_item_changed_fn"):
            self._model_subscriptions.append(model.subscribe_item_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        return False

    def _sync_parameter_pad_axis_model(self, axis):
        model = self._parameter_pad_axis_model(axis)
        options = self._parameter_pad_axis_options_for(axis)
        selected = self._parameter_pad_axis_parameter(axis)
        index = max(0, options.index(selected) if selected in options else 0)
        if self._combo_box_selected_index(model) == index:
            return
        syncing_axis_models = getattr(self, "_syncing_parameter_pad_axis_models", None)
        if syncing_axis_models is None:
            syncing_axis_models = set()
            self._syncing_parameter_pad_axis_models = syncing_axis_models
        sync_key = (axis, id(model))
        was_syncing = self._syncing_models
        self._syncing_models = True
        syncing_axis_models.add(sync_key)
        try:
            self._set_combo_box_selected_index(model, index)
        finally:
            syncing_axis_models.discard(sync_key)
            self._syncing_models = was_syncing

    def _on_parameter_pad_axis_changed(self, axis, model=None, options=None):
        if model is None:
            model = self._parameter_pad_axis_model(axis)
        sync_key = (axis, id(model))
        if sync_key in getattr(self, "_syncing_parameter_pad_axis_models", set()):
            return
        options = tuple(options) if options is not None else self._parameter_pad_axis_options_for(axis)
        if not options:
            return
        index = max(0, min(len(options) - 1, self._combo_box_selected_index(model)))
        self._parameter_pad_axes[axis] = options[index]
        self._ensure_distinct_parameter_pad_axes(preferred_axis=axis)
        for current_axis in ("x", "y"):
            self._sync_parameter_pad_axis_model(current_axis)
        self._active_parameter_pad = None
        self._parameter_pad_positions.clear()
        self._queue_parameter_pad_row_refresh()

    def _cycle_parameter_pad_axis(self, axis):
        options = self._parameter_pad_axis_options_for(axis)
        selected = self._parameter_pad_axis_parameter(axis)
        index = options.index(selected) if selected in options else 0
        self._parameter_pad_axes[axis] = options[(index + 1) % len(options)]
        self._ensure_distinct_parameter_pad_axes(preferred_axis=axis)
        self._queue_parameter_pad_row_refresh()

    def _ensure_distinct_parameter_pad_axes(self, preferred_axis=None):
        axes = getattr(self, "_parameter_pad_axes", None)
        if axes is None:
            axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
            self._parameter_pad_axes = axes
        for axis, fallback in self.PARAMETER_PAD_DEFAULT_AXES.items():
            if axes.get(axis) not in self.PARAMETER_PAD_PARAMETERS:
                axes[axis] = fallback
        if axes.get("x") != axes.get("y"):
            return
        axis_to_change = self._other_parameter_pad_axis(preferred_axis) if preferred_axis in ("x", "y") else "y"
        taken = axes.get(self._other_parameter_pad_axis(axis_to_change))
        for name in self.PARAMETER_PAD_PARAMETERS:
            if name != taken:
                axes[axis_to_change] = name
                return

    def _model_int_value(self, model):
        if hasattr(model, "as_int"):
            return int(model.as_int)
        if hasattr(model, "get_value_as_int"):
            return int(model.get_value_as_int())
        return int(model.get_value())

    def _combo_box_selected_index(self, model):
        for method_name in ("get_item_value_model", "get_value_model"):
            method = getattr(model, method_name, None)
            if not callable(method):
                continue
            try:
                value_model = method()
            except TypeError:
                try:
                    value_model = method(None)
                except Exception:
                    continue
            except Exception:
                continue
            try:
                return self._model_int_value(value_model)
            except Exception:
                pass
        try:
            return self._model_int_value(model)
        except Exception:
            return 0

    def _set_combo_box_selected_index(self, model, index):
        if hasattr(model, "set_value"):
            try:
                model.set_value(index)
                return True
            except Exception:
                pass
        for method_name in ("get_item_value_model", "get_value_model"):
            method = getattr(model, method_name, None)
            if not callable(method):
                continue
            try:
                value_model = method()
            except TypeError:
                try:
                    value_model = method(None)
                except Exception:
                    continue
            except Exception:
                continue
            if hasattr(value_model, "set_value"):
                try:
                    value_model.set_value(index)
                    return True
                except Exception:
                    pass
        return False

    def _refresh_findsurface_window(self):
        if getattr(self, "_app_shutting_down", False):
            return
        window = getattr(self, "_windows", {}).get(self.WINDOW_FINDSURFACE)
        frame = getattr(window, "frame", None) if window else None
        if not frame:
            return
        try:
            if hasattr(frame, "clear"):
                frame.clear()
            self._parameter_pad_rects.clear()
            self._parameter_pad_handle_spacers.clear()
            self._parameter_pad_frame = None
            with frame:
                self._build_findsurface_window()
            self._refresh_detection_panel()
        except Exception as exc:
            carb.log_warn(f"Failed to refresh FindSurface window: {exc}")

    def _queue_findsurface_window_refresh(self):
        if getattr(self, "_app_shutting_down", False):
            return
        window = getattr(self, "_windows", {}).get(self.WINDOW_FINDSURFACE)
        frame = getattr(window, "frame", None) if window else None
        if not frame:
            return
        task = getattr(self, "_findsurface_refresh_task", None)
        if task and not task.done():
            return
        self._findsurface_refresh_task = asyncio.ensure_future(
            _refresh_findsurface_window_after_update(weakref.ref(self))
        )

    def _build_parameter_pad_row_container(self):
        frame_factory = getattr(ui, "Frame", None)
        if frame_factory is None:
            self._parameter_pad_frame = None
            self._parameter_pad_row()
            return
        frame = frame_factory()
        self._parameter_pad_frame = frame
        with frame:
            self._parameter_pad_row()

    def _refresh_parameter_pad_row(self):
        if getattr(self, "_app_shutting_down", False):
            return False
        frame = getattr(self, "_parameter_pad_frame", None)
        if frame is None:
            self._queue_findsurface_window_refresh()
            return False
        try:
            if hasattr(frame, "clear"):
                frame.clear()
            self._parameter_pad_rects.clear()
            self._parameter_pad_handle_spacers.clear()
            with frame:
                self._parameter_pad_row()
            return True
        except Exception as exc:
            carb.log_warn(f"Failed to refresh FindSurface 2D Pad: {exc}")
            return False

    def _queue_parameter_pad_row_refresh(self):
        if getattr(self, "_app_shutting_down", False):
            return False
        frame = getattr(self, "_parameter_pad_frame", None)
        if frame is None:
            self._queue_findsurface_window_refresh()
            return False
        task = getattr(self, "_parameter_pad_refresh_task", None)
        if task and not task.done():
            return False
        self._parameter_pad_refresh_task = asyncio.ensure_future(
            _refresh_parameter_pad_row_after_update(weakref.ref(self))
        )
        return True

    def _parameter_pad_style(self):
        return {
            "background_color": 0x331B1E24,
            "border_color": 0xFF8C9098,
            "border_width": 1,
            "border_radius": 4,
        }

    def _parameter_pad_center_guides(self):
        guide_color = 0x448C9098
        center = int(self.PARAMETER_PAD_SIZE * 0.5)
        with ui.HStack(width=self.PARAMETER_PAD_SIZE, height=self.PARAMETER_PAD_SIZE, spacing=0):
            ui.Spacer(width=max(0, center - 1))
            ui.Rectangle(width=1, style={"background_color": guide_color})
            ui.Spacer()
        with ui.VStack(width=self.PARAMETER_PAD_SIZE, height=self.PARAMETER_PAD_SIZE, spacing=0):
            ui.Spacer(height=max(0, center - 1))
            ui.Rectangle(height=1, style={"background_color": guide_color})
            ui.Spacer()

    def _parameter_pad_handle_style(self):
        return {
            "background_color": 0xFFEFF4FF,
            "border_color": 0xFF111827,
            "border_width": 2,
            "border_radius": 3,
        }

    def _parameter_display_name(self, name):
        labels = {
            "measurement_accuracy": "Measurement Accuracy",
            "mean_distance": "Mean Distance",
            "seed_radius": "Seed Radius",
            "radial_expansion": "Radial Expansion",
            "lateral_extension": "Lateral Extension",
        }
        return labels.get(name, str(name).replace("_", " ").title())

    def _format_parameter_pad_value(self, name, value):
        if name in self.PARAMETER_PAD_INT_PARAMETERS:
            return str(int(round(float(value))))
        return self._format_range_parameter_value(value)

    def _parameter_pad_key(self, x_name, y_name):
        return f"{x_name}:{y_name}"

    def _parameter_pad_display_position(self, x_name, y_name):
        key = self._parameter_pad_key(x_name, y_name)
        if getattr(self, "_active_parameter_pad", None) == key:
            position = getattr(self, "_parameter_pad_positions", {}).get(key)
            if position is not None:
                return position
        return self._parameter_pad_normalized_for_model(x_name), self._parameter_pad_normalized_for_model(y_name)

    def _parameter_pad_changed_name(self, x_name, y_name):
        return x_name if x_name in self._parameter_transaction_model_names() else y_name

    def _parameter_pad_spec(self, name):
        if name in self.RANGE_PARAMETER_DEFAULTS:
            _label, _value, default_minimum, default_maximum = self.RANGE_PARAMETER_DEFAULTS[name]
            if f"{name}_min" in self._models and f"{name}_max" in self._models:
                minimum, maximum = self._range_bounds(name, round_endpoints=False)
            else:
                minimum, maximum = default_minimum, default_maximum
            return {
                "minimum": float(minimum),
                "maximum": float(maximum),
                "kind": "float",
            }
        if name in self.PARAMETER_PAD_INT_PARAMETERS:
            return {"minimum": 0.0, "maximum": 10.0, "kind": "int"}
        return {"minimum": 0.0, "maximum": 1.0, "kind": "float"}

    def _parameter_pad_model_value(self, name):
        if name in self.PARAMETER_PAD_INT_PARAMETERS:
            return float(self._model_int(name))
        return float(self._model_float(name))

    def _parameter_pad_normalized_for_model(self, name):
        spec = self._parameter_pad_spec(name)
        minimum = spec["minimum"]
        maximum = spec["maximum"]
        if maximum <= minimum:
            return 0.0
        value = self._parameter_pad_model_value(name)
        return self._clamp01((value - minimum) / (maximum - minimum))

    def _parameter_pad_value_from_normalized(self, name, normalized):
        spec = self._parameter_pad_spec(name)
        minimum = spec["minimum"]
        maximum = spec["maximum"]
        value = minimum + self._clamp01(normalized) * max(0.0, maximum - minimum)
        if spec["kind"] == "int":
            return int(round(value))
        return value

    def _parameter_pad_normalized_from_mouse(self, mouse_x, mouse_y, width, height):
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        return self._clamp01(float(mouse_x) / width), self._clamp01(1.0 - float(mouse_y) / height)

    def _clamp01(self, value):
        return max(0.0, min(1.0, float(value)))

    def _on_parameter_pad_pressed(self, x_name, y_name, *args):
        current_x, current_y = self._parameter_pad_event_axis_pair(x_name, y_name)
        self._active_parameter_pad = self._parameter_pad_key(current_x, current_y)
        self._on_parameter_control_pressed(self._parameter_pad_changed_name(current_x, current_y))
        self._apply_parameter_pad_mouse(
            current_x,
            current_y,
            *args,
            rect_key=self._parameter_pad_key(x_name, y_name),
        )

    def _on_parameter_pad_moved(self, x_name, y_name, *args):
        current_x, current_y = self._parameter_pad_event_axis_pair(x_name, y_name)
        current_key = self._parameter_pad_key(current_x, current_y)
        fallback_key = self._parameter_pad_key(x_name, y_name)
        if getattr(self, "_active_parameter_pad", None) not in (current_key, fallback_key):
            return
        self._apply_parameter_pad_mouse(current_x, current_y, *args, rect_key=fallback_key)

    def _on_parameter_pad_released(self, x_name, y_name, *args):
        current_x, current_y = self._parameter_pad_event_axis_pair(x_name, y_name)
        key = self._parameter_pad_key(current_x, current_y)
        fallback_key = self._parameter_pad_key(x_name, y_name)
        if getattr(self, "_active_parameter_pad", None) in (key, fallback_key):
            self._apply_parameter_pad_mouse(current_x, current_y, *args, rect_key=fallback_key)
        self._active_parameter_pad = None
        if hasattr(self, "_parameter_pad_positions"):
            self._parameter_pad_positions.pop(key, None)
            self._parameter_pad_positions.pop(fallback_key, None)
        self._on_detection_parameter_edit_finished(self._parameter_pad_changed_name(current_x, current_y))

    def _parameter_pad_event_axis_pair(self, fallback_x, fallback_y):
        try:
            current_x, current_y = self._parameter_pad_axis_pair()
        except Exception:
            return fallback_x, fallback_y
        fallback_key = self._parameter_pad_key(fallback_x, fallback_y)
        current_key = self._parameter_pad_key(current_x, current_y)
        if fallback_key == current_key:
            return fallback_x, fallback_y
        if fallback_key in getattr(self, "_parameter_pad_rects", {}):
            return current_x, current_y
        if fallback_key in getattr(self, "_parameter_pad_handle_spacers", {}):
            return current_x, current_y
        return fallback_x, fallback_y

    def _apply_parameter_pad_mouse(self, x_name, y_name, *args, rect_key=None):
        position = self._mouse_position_from_args(args)
        if position is None:
            return False
        rects = getattr(self, "_parameter_pad_rects", {})
        rect = rects.get(self._parameter_pad_key(x_name, y_name))
        if rect is None and rect_key is not None:
            rect = rects.get(rect_key)
        mouse_x, mouse_y, width, height = self._parameter_pad_local_mouse(rect, position[0], position[1])
        u, v = self._parameter_pad_normalized_from_mouse(mouse_x, mouse_y, width, height)
        return self._apply_parameter_pad_normalized(x_name, y_name, u, v)

    def _mouse_position_from_args(self, args):
        values = []
        for value in args:
            if isinstance(value, (int, float)):
                values.append(float(value))
                if len(values) == 2:
                    return tuple(values)
        return None

    def _parameter_pad_local_mouse(self, rect, screen_x, screen_y):
        width = self.PARAMETER_PAD_SIZE
        height = self.PARAMETER_PAD_SIZE
        if rect is None:
            return float(screen_x), float(screen_y), float(width), float(height)
        left = float(getattr(rect, "screen_position_x", 0.0))
        top = float(getattr(rect, "screen_position_y", 0.0))
        width = max(1.0, float(getattr(rect, "computed_width", width) or width))
        height = max(1.0, float(getattr(rect, "computed_height", height) or height))
        return float(screen_x) - left, float(screen_y) - top, width, height

    def _apply_parameter_pad_normalized(self, x_name, y_name, u, v):
        u = self._clamp01(u)
        v = self._clamp01(v)
        if hasattr(self, "_parameter_pad_positions"):
            self._parameter_pad_positions[self._parameter_pad_key(x_name, y_name)] = (u, v)
        self._update_parameter_pad_handle(x_name, y_name, u, v)
        changed = False
        was_syncing = self._syncing_models
        self._syncing_models = True
        try:
            changed = self._set_parameter_pad_value(x_name, u) or changed
            changed = self._set_parameter_pad_value(y_name, v) or changed
            for name in (x_name, y_name):
                if name in self.RANGE_PARAMETER_DEFAULTS:
                    minimum, maximum = self._range_bounds(name, round_endpoints=False)
                    self._sync_range_slider_index(name, value=self._models[name].as_float, minimum=minimum, maximum=maximum)
                    self._sync_range_edit_models(name)
        finally:
            self._syncing_models = was_syncing
        self._update_parameter_pad_value_labels(x_name, y_name)
        if changed:
            self._on_detection_parameter_value_changed(
                self._parameter_pad_changed_name(x_name, y_name),
                sync_parameter_pad=False,
            )
        return changed

    def _set_parameter_pad_value(self, name, normalized):
        if name not in self._models:
            return False
        value = self._parameter_pad_value_from_normalized(name, normalized)
        model = self._models[name]
        old_value = self._parameter_model_value(name, model)
        if name in self.PARAMETER_PAD_INT_PARAMETERS:
            value = int(value)
        if old_value == value:
            return False
        model.set_value(value)
        return True

    def _update_parameter_pad_handle(self, x_name, y_name, u, v):
        spacers = getattr(self, "_parameter_pad_handle_spacers", {}).get(self._parameter_pad_key(x_name, y_name))
        if not spacers:
            return False
        horizontal_spacer, vertical_spacer = spacers
        handle_size = self.PARAMETER_PAD_HANDLE_SIZE
        handle_left = self._clamp01(u) * max(0, self.PARAMETER_PAD_SIZE - handle_size)
        handle_top = (1.0 - self._clamp01(v)) * max(0, self.PARAMETER_PAD_SIZE - handle_size)
        self._set_widget_dimension(horizontal_spacer, "width", handle_left)
        self._set_widget_dimension(vertical_spacer, "height", handle_top)
        return True

    def _sync_parameter_pad_handle_from_models(self):
        try:
            x_name, y_name = self._parameter_pad_axis_pair()
        except Exception:
            return False
        if x_name not in self._models or y_name not in self._models:
            return False
        u = self._parameter_pad_normalized_for_model(x_name)
        v = self._parameter_pad_normalized_for_model(y_name)
        if hasattr(self, "_parameter_pad_positions"):
            self._parameter_pad_positions[self._parameter_pad_key(x_name, y_name)] = (u, v)
        updated = self._update_parameter_pad_handle(x_name, y_name, u, v)
        self._update_parameter_pad_value_labels(x_name, y_name)
        return updated

    def _sync_parameter_pad_for_changed_parameter(self, changed):
        if getattr(self, "_active_parameter_pad", None):
            return False
        name = self._range_parameter_name(changed) or changed
        if name not in self.PARAMETER_PAD_PARAMETERS:
            return False
        try:
            x_name, y_name = self._parameter_pad_axis_pair()
        except Exception:
            return False
        if name not in (x_name, y_name):
            return False
        updated = self._sync_parameter_pad_handle_from_models()
        self._queue_parameter_pad_row_refresh()
        return updated

    def _update_parameter_pad_value_labels(self, x_name=None, y_name=None):
        if x_name is None or y_name is None:
            try:
                x_name, y_name = self._parameter_pad_axis_pair()
            except Exception:
                return False
        labels = getattr(self, "_parameter_pad_value_labels", {})
        updated = False
        for axis, name in (("x", x_name), ("y", y_name)):
            label = labels.get(axis)
            if label is None or name not in self._models:
                continue
            try:
                label.text = self._format_parameter_pad_value(name, self._parameter_pad_model_value(name))
                updated = True
            except Exception:
                pass
        return updated

    def _set_widget_dimension(self, widget, attribute, value):
        if widget is None:
            return False
        length_value = self._ui_pixel(value)
        try:
            setattr(widget, attribute, length_value)
            return True
        except Exception:
            pass
        try:
            model = getattr(widget, attribute)
            if hasattr(model, "set_value"):
                model.set_value(length_value)
                return True
        except Exception:
            pass
        if length_value is not value:
            try:
                setattr(widget, attribute, value)
                return True
            except Exception:
                pass
            try:
                model = getattr(widget, attribute)
                if hasattr(model, "set_value"):
                    model.set_value(value)
                    return True
            except Exception:
                pass
        return False

    def _ui_pixel(self, value):
        pixel = getattr(ui, "Pixel", None)
        if callable(pixel):
            try:
                return pixel(float(value))
            except Exception:
                pass
        return value

    def _parameter_control_mouse_kwargs(self, name):
        return {
            "mouse_pressed_fn": lambda *args, changed=name: self._on_parameter_control_pressed(changed),
            "mouse_released_fn": lambda *args, changed=name: self._on_detection_parameter_edit_finished(changed),
        }

    def _on_parameter_control_pressed(self, changed=None):
        self._parameter_control_active = True

    def _subscribe_model(self, name, callback):
        key = ("value", name, getattr(callback, "__name__", repr(callback)))
        if key in getattr(self, "_model_subscription_keys", set()):
            return False
        changed_fn = lambda model, changed=name, cb=callback: cb(changed)
        model = self._models[name]
        if hasattr(model, "subscribe_value_changed_fn"):
            self._model_subscriptions.append(model.subscribe_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        elif hasattr(model, "add_value_changed_fn"):
            self._model_subscriptions.append(model.add_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        return False

    def _subscribe_model_end_edit(self, name, callback):
        key = ("end_edit", name, getattr(callback, "__name__", repr(callback)))
        if key in getattr(self, "_model_subscription_keys", set()):
            return False
        changed_fn = lambda model, changed=name, cb=callback: cb(changed)
        model = self._models[name]
        if hasattr(model, "subscribe_end_edit_fn"):
            self._model_subscriptions.append(model.subscribe_end_edit_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        elif hasattr(model, "add_end_edit_fn"):
            self._model_subscriptions.append(model.add_end_edit_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        return False

    def _subscribe_range_edit_model_end_edit(self, name, callback):
        key = ("range_end_edit", name, getattr(callback, "__name__", repr(callback)))
        if key in getattr(self, "_model_subscription_keys", set()):
            return False
        model = self._range_edit_model(name)
        changed_fn = lambda edited_model, changed=name, cb=callback: cb(changed)
        if hasattr(model, "subscribe_end_edit_fn"):
            self._model_subscriptions.append(model.subscribe_end_edit_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        if hasattr(model, "add_end_edit_fn"):
            self._model_subscriptions.append(model.add_end_edit_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        return False

    def _subscribe_range_edit_model_value_changed(self, name, model):
        key = ("range_value", name)
        if key in getattr(self, "_model_subscription_keys", set()):
            return False
        changed_fn = lambda edited_model, changed=name: self._on_range_edit_model_value_changed(changed)
        if hasattr(model, "subscribe_value_changed_fn"):
            self._model_subscriptions.append(model.subscribe_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        if hasattr(model, "add_value_changed_fn"):
            self._model_subscriptions.append(model.add_value_changed_fn(changed_fn))
            self._model_subscription_keys.add(key)
            return True
        return False

    def _on_range_edit_model_value_changed(self, changed):
        if self._syncing_models:
            return
        if not self._range_parameter_name(changed):
            return
        self._range_edit_dirty.add(changed)

    def _init_range_edit_models(self, name):
        for model_name in (name, f"{name}_min", f"{name}_max"):
            model = self._new_range_float_model(self._models[model_name].as_float)
            self._range_edit_models[model_name] = model
            self._subscribe_range_edit_model_value_changed(model_name, model)

    def _range_edit_model(self, name):
        model = self._range_edit_models.get(name)
        if model is None:
            source = self._models.get(name)
            value = getattr(source, "as_float", 0.0)
            model = self._new_range_float_model(value)
            self._range_edit_models[name] = model
            self._subscribe_range_edit_model_value_changed(name, model)
        return model

    def _dock_windows_now(self):
        toolbar = self._windows.get(self.WINDOW_TOOLBAR)
        status_bar = self._windows.get(self.WINDOW_STATUS_BAR)
        viewport = self._windows.get(self.WINDOW_VIEWPORT)
        panel = self._windows.get(self.WINDOW_FINDSURFACE)
        if viewport and toolbar:
            toolbar.dock_in(viewport, ui.DockPosition.TOP, 0.08)
            self._hide_dock_tab_bar(toolbar)
        if viewport and status_bar:
            status_bar.dock_in(viewport, ui.DockPosition.BOTTOM, 0.035)
            self._hide_dock_tab_bar(status_bar)
        if viewport and panel:
            panel.dock_in(viewport, ui.DockPosition.RIGHT, self.SIDE_PANEL_DOCK_RATIO)
        geometries = self._windows.get(self.WINDOW_GEOMETRIES)
        camera = self._windows.get(self.WINDOW_CAMERA)
        settings = self._windows.get(self.WINDOW_SETTINGS)
        debug_group_box = self._windows.get(self.WINDOW_DEBUG_GROUP_BOX)
        if panel and geometries:
            self._dock_side_panel_tab(self.WINDOW_GEOMETRIES)
        if panel and camera:
            self._dock_side_panel_tab(self.WINDOW_CAMERA)
        if panel and settings:
            self._dock_side_panel_tab(self.WINDOW_SETTINGS)
        if panel:
            self._dock_side_panel_tab(self.WINDOW_TRANSACTIONS)
        if panel and debug_group_box:
            debug_group_box.dock_in(panel, ui.DockPosition.SAME, 0.5)
        if panel:
            self._focus_window(panel)
        self._hide_viewport_tab_bar_by_default()
        self._hide_toolbar_tab_bars()

    def _side_panel_tab_titles(self):
        return (
            self.WINDOW_GEOMETRIES,
            self.WINDOW_CAMERA,
            self.WINDOW_SETTINGS,
            self.WINDOW_TRANSACTIONS,
        )

    def _dock_side_panel_tab(self, title, focus=False, restore_visible=None):
        if title not in self._side_panel_tab_titles():
            return False
        panel = self._windows.get(self.WINDOW_FINDSURFACE)
        window = self._windows.get(title)
        if not panel or not window:
            return False
        original_visible = bool(getattr(window, "visible", True))
        try:
            window.visible = True
            window.dock_in(panel, ui.DockPosition.SAME, 0.5)
        except Exception:
            return False
        finally:
            if restore_visible is None:
                restore_visible = original_visible
            try:
                window.visible = bool(restore_visible)
            except Exception:
                pass
        if focus:
            self._focus_window(window)
        return True

    def _hide_toolbar_tab_bars(self):
        toolbar = self._windows.get(self.WINDOW_TOOLBAR)
        status_bar = self._windows.get(self.WINDOW_STATUS_BAR)
        self._hide_dock_tab_bar(toolbar)
        self._hide_dock_tab_bar(status_bar)

    def _hide_viewport_tab_bar_by_default(self):
        if self._viewport_tab_bar_hidden_by_default:
            return
        viewport = self._windows.get(self.WINDOW_VIEWPORT)
        if self._hide_dock_tab_bar(viewport):
            self._viewport_tab_bar_hidden_by_default = True

    def _focus_window(self, window):
        try:
            window.focus()
        except Exception:
            pass

    def _hide_dock_tab_bar(self, window):
        if not window:
            return False
        try:
            window.dock_tab_bar_visible = False
            return True
        except Exception:
            return False

    def _show_load_workspace_dialog(self):
        self._guard_unsaved_changes("load another workspace", self._show_load_workspace_dialog_unchecked)

    def _show_load_workspace_dialog_unchecked(self):
        if not self._load_workspace_dialog:
            self._load_workspace_dialog = FilePickerDialog(
                "Load Workspace",
                width=960,
                height=620,
                apply_button_label="Load",
                click_apply_handler=self._on_load_workspace_accepted,
                click_cancel_handler=lambda filename, dirname: self._load_workspace_dialog.hide(),
                item_filter_options=["FindSurface workspace USD", "All files"],
                item_filter_fn=self._filter_workspace_item,
                **self._file_dialog_directory_kwargs(FILE_DIALOG_LOAD_WORKSPACE),
            )
            self._load_workspace_dialog.hide()
        self._apply_file_dialog_directory(self._load_workspace_dialog, FILE_DIALOG_LOAD_WORKSPACE)
        self._load_workspace_dialog.show()

    def _filter_workspace_item(self, item):
        if not item or item.is_folder:
            return True
        dialog = self._load_workspace_dialog or self._save_workspace_dialog or self._export_geometries_dialog
        if dialog and getattr(dialog, "current_filter_option", 0) == 1:
            return True
        return os.path.splitext(item.path)[1].lower() in {".usd", ".usda", ".usdc"}

    def _on_load_workspace_accepted(self, filename, dirname):
        if not filename:
            return
        full_path = self._path_from_picker(filename, dirname)
        try:
            self._load_workspace_from_path(full_path)
        except Exception as exc:
            self._set_status(f"Load failed: {exc}")
            self._show_load_error_dialog(full_path, exc)
            carb.log_error(f"FindSurface failed to load workspace '{full_path}': {exc}")
            return
        self._remember_file_dialog_directory(FILE_DIALOG_LOAD_WORKSPACE, full_path)
        if self._load_workspace_dialog:
            self._load_workspace_dialog.hide()

    def _show_load_error_dialog(self, full_path, error):
        if self._load_error_dialog:
            self._defer_window_destroy(self._load_error_dialog)
            self._load_error_dialog = None
        filename = os.path.basename(full_path) or str(full_path or "")
        detail = str(error or "Unknown error")
        self._load_error_dialog = ui.Window("Load Workspace Failed", width=540, height=190)
        with self._load_error_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label("The selected file could not be loaded as a FindSurface workspace.", word_wrap=True)
                ui.Label(f"{filename}: {detail}", word_wrap=True)
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button("OK", width=90, clicked_fn=self._close_load_error_dialog)
                    ui.Spacer(width=8)

    def _close_load_error_dialog(self):
        if self._load_error_dialog:
            self._defer_window_destroy(self._load_error_dialog)
            self._load_error_dialog = None

    def _load_workspace_from_path(self, full_path):
        document = read_workspace(full_path)

        def command():
            self._invalidate_auto_detect_requests()
            self._workspace_path = full_path
            self._loaded_path = document.point_cloud.metadata.get("source_path") or full_path
            self._state = document.state
            self._geometry_collapsed = {}
            self._geometry_histogram_bin_counts = {}
            self._geometry_histogram_details_expanded = {}
            self._hovered_geometry_id = None
            self._detection_type = document.detection_type if document.detection_type in DETECTION_TYPES else "Auto"
            self._hover_index = None
            self._selected_index = None
            self._auto_detect_result = None
            self._auto_detect_source = None
            self._set_retroactive_pick_index(None)
            self._viewport.set_surfaces(self._state.results)
            self._viewport.set_point_cloud(document.point_cloud, self._state.active_mask)
            self._apply_workspace_settings(document.metadata.get("settings") or {})
            self._set_status(f"Loaded workspace: {os.path.basename(full_path)}")
            self._set_dataset(os.path.basename(full_path))
            self._set_point_count(self._state.point_count)
            return True

        return self._run_dataset_command(command)

    def _save_workspace(self):
        if not self._state:
            self._set_status("Import or load a point cloud before saving.")
            return False
        if not self._workspace_path:
            self._show_save_workspace_dialog()
            return False
        return self._save_workspace_to_path(self._workspace_path)

    def _show_save_workspace_dialog(self, continue_after=None):
        if not self._state:
            self._set_status("Import or load a point cloud before saving.")
            return
        self._save_dialog_continue_after = continue_after
        if not self._save_workspace_dialog:
            self._save_workspace_dialog = FilePickerDialog(
                "Save Workspace",
                width=960,
                height=620,
                apply_button_label="Save",
                click_apply_handler=self._on_save_workspace_accepted,
                click_cancel_handler=lambda filename, dirname: self._cancel_save_workspace_dialog(),
                item_filter_options=["FindSurface workspace USD", "All files"],
                item_filter_fn=self._filter_workspace_item,
                **self._file_dialog_directory_kwargs(FILE_DIALOG_SAVE_WORKSPACE),
            )
            self._save_workspace_dialog.hide()
        self._apply_file_dialog_directory(self._save_workspace_dialog, FILE_DIALOG_SAVE_WORKSPACE)
        self._save_workspace_dialog.show()

    def _cancel_save_workspace_dialog(self):
        self._save_dialog_continue_after = None
        if self._save_workspace_dialog:
            self._save_workspace_dialog.hide()

    def _on_save_workspace_accepted(self, filename, dirname):
        if not filename:
            return
        full_path = self._ensure_usda_extension(self._path_from_picker(filename, dirname))
        continue_after = self._save_dialog_continue_after
        self._save_dialog_continue_after = None
        if not self._save_workspace_to_path(full_path):
            return
        self._remember_file_dialog_directory(FILE_DIALOG_SAVE_WORKSPACE, full_path)
        if self._save_workspace_dialog:
            self._save_workspace_dialog.hide()
        if continue_after:
            continue_after()

    def _save_workspace_to_path(self, full_path):
        self._sync_parameter_transaction_from_models(finalize=True)
        try:
            write_workspace(full_path, self._state, detection_type=self._detection_type, settings=self._settings_snapshot())
        except Exception as exc:
            self._set_status(f"Save failed: {exc}")
            carb.log_error(f"FindSurface failed to save workspace '{full_path}': {exc}")
            return False
        self._workspace_path = full_path
        self._remember_file_dialog_directory(FILE_DIALOG_SAVE_WORKSPACE, full_path)
        self._set_dataset(os.path.basename(full_path))
        self._clear_dirty_tracking()
        self._set_status(f"Saved workspace: {os.path.basename(full_path)}")
        return True

    def _show_export_geometries_dialog(self):
        if not self._state or not self._state.results:
            self._set_status("Detect at least one geometry before exporting.")
            return
        self._show_export_options_dialog()

    def _show_export_options_dialog(self):
        if self._export_options_dialog:
            self._defer_window_destroy(self._export_options_dialog)
            self._export_options_dialog = None
        self._export_options_dialog = ui.Window("Export Options", width=460, height=180)
        with self._export_options_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label("Choose the geometry export payload.", word_wrap=True)
                ui.Label("Visualization meshes make the export easier to inspect in apps without FindSurface schema support.", word_wrap=True)
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button("Data Only", width=110, clicked_fn=lambda: self._open_export_file_dialog(False))
                    ui.Button("Include Meshes", width=130, clicked_fn=lambda: self._open_export_file_dialog(True))
                    ui.Button("Cancel", width=90, clicked_fn=self._cancel_export_options_dialog)
                    ui.Spacer(width=8)
        self._set_status("Choose export options.")

    def _open_export_file_dialog(self, include_visualization_meshes):
        self._export_include_visualization_meshes = bool(include_visualization_meshes)
        self._cancel_export_options_dialog()
        if not self._export_geometries_dialog:
            self._export_geometries_dialog = FilePickerDialog(
                "Export Geometries",
                width=960,
                height=620,
                apply_button_label="Export",
                click_apply_handler=self._on_export_geometries_accepted,
                click_cancel_handler=lambda filename, dirname: self._export_geometries_dialog.hide(),
                item_filter_options=["FindSurface geometry USD", "All files"],
                item_filter_fn=self._filter_workspace_item,
                **self._file_dialog_directory_kwargs(FILE_DIALOG_EXPORT_GEOMETRIES),
            )
            self._export_geometries_dialog.hide()
        self._apply_file_dialog_directory(self._export_geometries_dialog, FILE_DIALOG_EXPORT_GEOMETRIES)
        self._export_geometries_dialog.show()

    def _cancel_export_options_dialog(self):
        if self._export_options_dialog:
            self._defer_window_destroy(self._export_options_dialog)
            self._export_options_dialog = None

    def _on_export_geometries_accepted(self, filename, dirname):
        if not filename:
            return
        full_path = self._ensure_usda_extension(self._path_from_picker(filename, dirname))
        if self._export_geometries_to_path(full_path):
            self._remember_file_dialog_directory(FILE_DIALOG_EXPORT_GEOMETRIES, full_path)
            self._export_geometries_dialog.hide()

    def _export_geometries_to_path(self, full_path):
        try:
            write_geometry_export(
                full_path,
                self._state,
                include_visualization_meshes=self._export_include_visualization_meshes,
            )
        except Exception as exc:
            self._set_status(f"Export failed: {exc}")
            carb.log_error(f"FindSurface failed to export geometries '{full_path}': {exc}")
            return False
        detail = " with visualization meshes" if self._export_include_visualization_meshes else ""
        self._set_status(f"Exported geometries{detail}: {os.path.basename(full_path)}")
        return True

    def _path_from_picker(self, filename, dirname):
        return os.path.normpath(os.path.join(dirname or "", filename))

    def _ensure_usda_extension(self, path):
        if os.path.splitext(path)[1]:
            return path
        return f"{path}.usda"

    def _settings_snapshot(self):
        snapshot = {}
        for name, model in self._models.items():
            try:
                value = self._settings_model_value(name, model)
            except Exception:
                continue
            if value is not None:
                snapshot[name] = value
        snapshot["parameter_pad_axes"] = self._parameter_pad_axes_settings_snapshot()
        snapshot["outlier_points_visible"] = bool(getattr(self._viewport, "outlier_points_visible", True))
        snapshot["surface_meshes_visible"] = bool(getattr(self._viewport, "surface_meshes_visible", True))
        snapshot["inlier_points_visible"] = bool(getattr(self._viewport, "inlier_points_visible", True))
        camera = getattr(self._viewport, "camera", None)
        if camera:
            snapshot["camera"] = {
                "projection_mode": camera.projection_mode,
                "center": list(camera.center),
                "orientation": list(camera.orientation),
                "zoom": float(camera.zoom),
                "diameter": float(camera.diameter),
                "fov_degrees": float(camera.fov_degrees),
            }
        return snapshot

    def _settings_model_value(self, name, model):
        if name in self.SETTINGS_BOOL_MODEL_NAMES:
            if hasattr(model, "as_bool"):
                return bool(model.as_bool)
            if hasattr(model, "get_value_as_bool"):
                return bool(model.get_value_as_bool())
        if self._is_int_settings_model_name(name):
            if hasattr(model, "as_int"):
                return int(model.as_int)
            if hasattr(model, "get_value_as_int"):
                return int(model.get_value_as_int())
        if hasattr(model, "as_float"):
            return float(model.as_float)
        if hasattr(model, "get_value_as_float"):
            return float(model.get_value_as_float())
        if hasattr(model, "as_int"):
            return int(model.as_int)
        if hasattr(model, "get_value_as_int"):
            return int(model.get_value_as_int())
        if hasattr(model, "as_bool"):
            return bool(model.as_bool)
        if hasattr(model, "get_value_as_bool"):
            return bool(model.get_value_as_bool())
        return None

    def _is_int_settings_model_name(self, name):
        return name in self.SETTINGS_INT_MODEL_NAMES or name.endswith("_slider_index")

    def _apply_workspace_settings(self, settings):
        if not settings:
            return
        self._syncing_models = True
        try:
            for name, value in settings.items():
                model = self._models.get(name)
                if model is not None and hasattr(model, "set_value"):
                    if self._is_legacy_boolean_numeric_setting(name, value):
                        continue
                    model.set_value(value)
        finally:
            self._syncing_models = False
        camera_settings = settings.get("camera") or {}
        camera = getattr(self._viewport, "camera", None)
        if camera and camera_settings:
            camera.projection_mode = camera_settings.get("projection_mode", camera.projection_mode)
            camera.center = list(camera_settings.get("center", camera.center))
            camera.orientation = list(camera_settings.get("orientation", camera.orientation))
            camera.zoom = float(camera_settings.get("zoom", camera.zoom))
            camera.diameter = float(camera_settings.get("diameter", camera.diameter))
            camera.set_fov_degrees(camera_settings.get("fov_degrees", camera.fov_degrees))
        if hasattr(self._viewport, "set_global_visibility"):
            self._viewport.set_global_visibility(
                outlier_points=settings.get("outlier_points_visible", getattr(self._viewport, "outlier_points_visible", True)),
                surface_meshes=settings.get("surface_meshes_visible", getattr(self._viewport, "surface_meshes_visible", True)),
                inlier_points=settings.get("inlier_points_visible", getattr(self._viewport, "inlier_points_visible", True)),
            )
        if "point_size" in self._models and hasattr(self._viewport, "set_point_size"):
            self._on_display_settings_changed()
        if "probe_radius" in self._models:
            self._on_detection_settings_changed()
        self._apply_parameter_pad_axes_settings(settings.get("parameter_pad_axes"))
        self._sync_parameter_pad_after_settings()
        self._sync_camera_models()

    def _parameter_pad_axes_settings_snapshot(self):
        axes = getattr(self, "_parameter_pad_axes", None)
        if not isinstance(axes, dict):
            axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
        result = {}
        for axis in ("x", "y"):
            value = axes.get(axis)
            if value in self.PARAMETER_PAD_PARAMETERS:
                result[axis] = value
        return result

    def _apply_parameter_pad_axes_settings(self, axes):
        if not isinstance(axes, dict):
            return False
        if not hasattr(self, "_parameter_pad_axes") or not isinstance(self._parameter_pad_axes, dict):
            self._parameter_pad_axes = dict(self.PARAMETER_PAD_DEFAULT_AXES)
        changed = False
        for axis in ("x", "y"):
            value = axes.get(axis)
            if value not in self.PARAMETER_PAD_PARAMETERS:
                continue
            if self._parameter_pad_axes.get(axis) != value:
                self._parameter_pad_axes[axis] = value
                changed = True
        self._ensure_distinct_parameter_pad_axes()
        for axis in ("x", "y"):
            self._sync_parameter_pad_axis_model(axis)
        return changed

    def _sync_parameter_pad_after_settings(self):
        self._active_parameter_pad = None
        if hasattr(self, "_parameter_pad_positions"):
            self._parameter_pad_positions.clear()
        self._sync_parameter_pad_handle_from_models()
        self._queue_parameter_pad_row_refresh()

    def _is_legacy_boolean_numeric_setting(self, name, value):
        if name in self.SETTINGS_BOOL_MODEL_NAMES:
            return False
        if not isinstance(value, bool):
            return False
        return self._is_int_settings_model_name(name) or name in self._models

    def _show_import_points_dialog(self):
        self._guard_unsaved_changes("import another point cloud", self._show_import_points_dialog_unchecked)

    def _show_import_points_dialog_unchecked(self):
        if not self._file_dialog:
            self._file_dialog = FilePickerDialog(
                "Import Points",
                width=960,
                height=620,
                apply_button_label="Import",
                click_apply_handler=self._on_import_points_accepted,
                click_cancel_handler=lambda filename, dirname: self._file_dialog.hide(),
                item_filter_options=["Point data", "All files"],
                item_filter_fn=self._filter_file_item,
                **self._file_dialog_directory_kwargs(FILE_DIALOG_IMPORT_POINTS),
            )
            self._file_dialog.hide()
        self._apply_file_dialog_directory(self._file_dialog, FILE_DIALOG_IMPORT_POINTS)
        self._file_dialog.show()

    def _filter_file_item(self, item):
        if not item or item.is_folder:
            return True
        if self._file_dialog and self._file_dialog.current_filter_option == 1:
            return True
        return os.path.splitext(item.path)[1].lower() in SUPPORTED_EXTENSIONS

    def _on_import_points_accepted(self, filename, dirname):
        if not filename:
            return
        full_path = os.path.normpath(os.path.join(dirname or "", filename))
        self._remember_file_dialog_directory(FILE_DIALOG_IMPORT_POINTS, full_path)
        self._begin_import_points(full_path, self._import_options(), action_label="Importing")
        if self._file_dialog:
            self._file_dialog.hide()

    def _show_point_limit_dialog(self, full_path, error):
        self._pending_oversized_import_path = full_path
        self._pending_oversized_import_error = error
        if self._file_dialog:
            self._file_dialog.hide()
        if self._point_limit_dialog:
            self._defer_window_destroy(self._point_limit_dialog)
            self._point_limit_dialog = None

        source_count = error.source_point_count
        max_points = error.max_points or ImportOptions().max_points
        target_min = min(SAMPLE_TARGET_MIN, max_points)
        target_points = max(target_min, min(error.target_points or ImportOptions().target_points, max_points))
        self._sample_target_model = ui.SimpleIntModel(target_points)
        if source_count:
            detail = (
                f"The selected point cloud has {source_count:,} points, "
                f"which exceeds the {max_points:,} point limit."
            )
        else:
            detail = f"The selected point cloud exceeds the {max_points:,} point limit."

        self._point_limit_dialog = ui.Window("Point Cloud Size Limit", width=560, height=230)
        with self._point_limit_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label(detail, word_wrap=True)
                ui.Label(
                    "Choose how many points to keep, then sample uniformly or cancel the import.",
                    word_wrap=True,
                )
                with ui.HStack(height=30, spacing=8):
                    ui.Label("Sample points", width=110)
                    ui.IntDrag(
                        model=self._sample_target_model,
                        min=target_min,
                        max=max_points,
                        step=SAMPLE_TARGET_STEP,
                    )
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button("Sample", width=110, clicked_fn=self._sample_pending_oversized_import)
                    ui.Button("Cancel", width=110, clicked_fn=self._cancel_pending_oversized_import)
                    ui.Spacer(width=8)
        self._set_status(f"Import needs confirmation: {os.path.basename(full_path)} exceeds the point limit.")

    def _sample_pending_oversized_import(self):
        full_path = self._pending_oversized_import_path
        error = self._pending_oversized_import_error
        if not full_path:
            self._cancel_pending_oversized_import()
            return
        target_points = self._selected_sample_target(error)
        self._close_point_limit_dialog()
        self._begin_import_points(
            full_path,
            self._import_options(
                max_points=error.max_points or None,
                target_points=target_points,
                overflow_policy="sample",
            ),
            action_label="Sampling",
        )

    def _cancel_pending_oversized_import(self):
        full_path = self._pending_oversized_import_path
        self._close_point_limit_dialog()
        if full_path:
            self._set_status(f"Import canceled: {os.path.basename(full_path)} exceeds the point limit.")

    def _close_point_limit_dialog(self):
        self._pending_oversized_import_path = None
        self._pending_oversized_import_error = None
        self._sample_target_model = None
        if self._point_limit_dialog:
            self._defer_window_destroy(self._point_limit_dialog)
            self._point_limit_dialog = None

    def _defer_window_destroy(self, window):
        try:
            window.visible = False
        except Exception:
            pass
        self._deferred_destroy_tasks = [task for task in self._deferred_destroy_tasks if not task.done()]
        self._deferred_destroy_tasks.append(asyncio.ensure_future(_destroy_window_after_update(window)))

    def _selected_sample_target(self, error):
        max_points = error.max_points or ImportOptions().max_points
        minimum = min(SAMPLE_TARGET_MIN, max_points)
        model = self._sample_target_model
        if model is None:
            value = error.target_points or ImportOptions().target_points
        elif hasattr(model, "as_int"):
            value = model.as_int
        elif hasattr(model, "get_value_as_int"):
            value = model.get_value_as_int()
        else:
            value = model.get_value()
        return max(minimum, min(max_points, int(value)))

    def _import_options(self, max_points=None, target_points=None, overflow_policy=None):
        sample_seed = app_config.config_value(self._config(), ("import", "sample_seed"), None)
        if sample_seed is not None:
            try:
                sample_seed = int(sample_seed)
            except (TypeError, ValueError):
                sample_seed = None
        defaults = ImportOptions()
        return ImportOptions(
            max_points=max_points
            or app_config.config_int(self._config(), ("import", "max_points"), defaults.max_points, 1),
            target_points=target_points
            or app_config.config_int(self._config(), ("import", "target_points"), defaults.target_points, 1),
            overflow_policy=overflow_policy
            or str(app_config.config_value(self._config(), ("import", "overflow_policy"), defaults.overflow_policy)),
            sample_seed=sample_seed,
            include_mesh_vertices=app_config.config_bool(
                self._config(),
                ("import", "include_mesh_vertices"),
                defaults.include_mesh_vertices,
            ),
            retain_sampled_source_indices=app_config.config_bool(
                self._config(),
                ("import", "retain_sampled_source_indices"),
                defaults.retain_sampled_source_indices,
            ),
            max_source_index_mapping_points=app_config.config_int(
                self._config(),
                ("import", "max_source_index_mapping_points"),
                defaults.max_source_index_mapping_points,
                0,
            ),
        )

    def _begin_import_points(self, full_path, options, action_label="Importing"):
        if self._is_import_busy():
            self._set_status("Import already in progress. Cancel it before starting another import.")
            return False
        cancel_token = ImportCancelToken()
        with self._import_lock:
            self._import_request_token = getattr(self, "_import_request_token", 0) + 1
            request_token = self._import_request_token
            self._import_cancel_token = cancel_token
            self._import_busy = True
            self._import_pending = None
            self._import_progress = None
            self._last_import_progress_text = None
        self._show_import_progress_dialog(action_label, full_path)
        self._set_status(f"{action_label}: {os.path.basename(full_path)}")
        Thread(
            target=self._import_worker,
            args=(request_token, full_path, options, cancel_token, action_label),
            daemon=True,
        ).start()
        return True

    def _is_import_busy(self):
        lock = getattr(self, "_import_lock", None)
        if not lock:
            return False
        with lock:
            return bool(getattr(self, "_import_busy", False))

    def _import_worker(self, request_token, full_path, options, cancel_token, action_label):
        point_cloud = None
        error = None

        def on_progress(progress):
            with self._import_lock:
                if request_token == self._import_request_token:
                    self._import_progress = progress

        try:
            point_cloud = self._load_point_cloud(
                full_path,
                options,
                progress_callback=on_progress,
                cancel_token=cancel_token,
            )
        except Exception as exc:
            error = exc

        with self._import_lock:
            if request_token != self._import_request_token:
                return
            self._import_pending = (request_token, full_path, point_cloud, error, action_label)

    def _apply_import_progress(self):
        lock = getattr(self, "_import_lock", None)
        if not lock:
            return
        with lock:
            progress = self._import_progress
        if not progress:
            return
        text = self._format_import_progress(progress)
        if not text or text == getattr(self, "_last_import_progress_text", None):
            return
        self._last_import_progress_text = text
        self._set_import_progress_text(text)
        self._set_status(text)

    def _apply_import_pending(self):
        lock = getattr(self, "_import_lock", None)
        if not lock:
            return
        with lock:
            pending = self._import_pending
            if pending is None:
                return
            self._import_pending = None
            self._import_busy = False
            self._import_cancel_token = None
            self._import_progress = None
        request_token, full_path, point_cloud, error, action_label = pending
        if request_token != getattr(self, "_import_request_token", None):
            return
        if isinstance(error, ImportCanceledError):
            self._close_import_progress_dialog()
            self._set_status(f"Import canceled: {os.path.basename(full_path)}")
            return
        if isinstance(error, PointCloudSizeError):
            self._close_import_progress_dialog()
            self._show_point_limit_dialog(full_path, error)
            return
        if error is not None:
            self._close_import_progress_dialog()
            self._set_status(f"Import failed: {error}")
            carb.log_error(f"FindSurface failed to import '{full_path}': {error}")
            return
        if point_cloud is None:
            self._close_import_progress_dialog()
            self._set_status(f"Import failed: no point cloud was loaded from {os.path.basename(full_path)}")
            return
        final_status = f"Final viewport load: {os.path.basename(full_path)}"
        self._set_import_progress_text(final_status)
        self._set_status(final_status)
        self._apply_imported_point_cloud(full_path, point_cloud)
        self._close_import_progress_dialog()

    def _show_import_progress_dialog(self, action_label, full_path):
        if self._import_progress_dialog:
            self._defer_window_destroy(self._import_progress_dialog)
            self._import_progress_dialog = None
        self._import_progress_label = None
        try:
            self._import_progress_dialog = ui.Window("Point Cloud Import", width=500, height=150)
            with self._import_progress_dialog.frame:
                with ui.VStack(spacing=8):
                    ui.Spacer(height=8)
                    self._import_progress_label = ui.Label(
                        f"{action_label}: {os.path.basename(full_path)}",
                        word_wrap=True,
                    )
                    ui.Spacer(height=8)
                    with ui.HStack(height=32, spacing=8):
                        ui.Spacer()
                        ui.Button("Cancel", width=110, clicked_fn=self._cancel_active_import)
                        ui.Spacer(width=8)
        except Exception as exc:
            self._import_progress_dialog = None
            self._import_progress_label = None
            carb.log_warn(f"Failed to show import progress dialog: {exc}")

    def _set_import_progress_text(self, text):
        label = getattr(self, "_import_progress_label", None)
        if label is not None:
            try:
                label.text = text
            except Exception:
                pass

    def _close_import_progress_dialog(self):
        self._import_progress_label = None
        if self._import_progress_dialog:
            self._defer_window_destroy(self._import_progress_dialog)
            self._import_progress_dialog = None

    def _cancel_active_import(self, status=True):
        lock = getattr(self, "_import_lock", None)
        if not lock:
            return False
        with lock:
            cancel_token = getattr(self, "_import_cancel_token", None)
            busy = bool(getattr(self, "_import_busy", False))
        if not busy or cancel_token is None:
            return False
        cancel_token.cancel()
        if status:
            self._set_status("Canceling import...")
            self._set_import_progress_text("Canceling import...")
        return True

    def _format_import_progress(self, progress):
        path = getattr(progress, "path", None)
        basename = os.path.basename(path) if path else "point cloud"
        phase = getattr(progress, "phase", "")
        current = getattr(progress, "current", None)
        total = getattr(progress, "total", None)
        labels = {
            "counting": "Counting points",
            "parsing": "Parsing points",
            "sampling": "Sampling points",
            "finalizing": "Preparing point cloud",
        }
        label = labels.get(phase, "Importing")
        if current is not None and total:
            return f"{label}: {basename} ({int(current):,} / {int(total):,})"
        if current is not None:
            return f"{label}: {basename} ({int(current):,})"
        return f"{label}: {basename}"

    def _load_point_cloud(self, path, options, progress_callback=None, cancel_token=None):
        try:
            parameters = inspect.signature(load_point_cloud).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_options = len(parameters) != 1
        if accepts_options:
            kwargs = {}
            accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
            if accepts_kwargs or "progress_callback" in parameters:
                kwargs["progress_callback"] = progress_callback
            if accepts_kwargs or "cancel_token" in parameters:
                kwargs["cancel_token"] = cancel_token
            if kwargs:
                return load_point_cloud(path, options, **kwargs)
            return load_point_cloud(path, options)
        return load_point_cloud(path)

    def _apply_imported_point_cloud(self, full_path, point_cloud):
        def command():
            self._invalidate_auto_detect_requests()
            self._loaded_path = full_path
            self._workspace_path = None
            self._state = PointCloudState(point_cloud)
            self._geometry_collapsed = {}
            self._geometry_histogram_bin_counts = {}
            self._geometry_histogram_details_expanded = {}
            self._hovered_geometry_id = None
            self._hover_index = None
            self._selected_index = None
            self._auto_detect_result = None
            self._auto_detect_source = None
            self._set_retroactive_pick_index(None)
            self._viewport.set_surfaces([])
            self._viewport.set_point_cloud(point_cloud, self._state.active_mask)
            status = f"Imported: {os.path.basename(full_path)}"
            source_count = point_cloud.metadata.get("source_point_count")
            if source_count and source_count != point_cloud.count:
                status += f" ({point_cloud.count:,} / {source_count:,} sampled)"
            self._set_status(status)
            self._set_dataset(os.path.basename(full_path))
            self._set_point_count(point_cloud.count)
            carb.log_info(f"FindSurface imported {point_cloud.count} points from: {full_path}")
            return True

        return self._run_dataset_command(command)

    def _request_close_dataset(self):
        self._guard_unsaved_changes("close the current point cloud", self._close_dataset)

    def _close_dataset(self):
        def command():
            self._invalidate_auto_detect_requests()
            self._loaded_path = None
            self._workspace_path = None
            self._state = None
            self._geometry_collapsed = {}
            self._geometry_histogram_bin_counts = {}
            self._geometry_histogram_details_expanded = {}
            self._hovered_geometry_id = None
            self._hover_index = None
            self._selected_index = None
            self._auto_detect_result = None
            self._auto_detect_source = None
            self._set_retroactive_pick_index(None)
            self._viewport.clear()
            self._set_status("No data loaded")
            self._set_dataset("None")
            self._set_point_count(0)
            return True

        return self._run_dataset_command(command)

    def _guard_unsaved_changes(self, action_label, continue_fn):
        if not self._is_dirty:
            continue_fn()
            return True
        self._show_unsaved_changes_dialog(action_label, continue_fn)
        return False

    def _show_unsaved_changes_dialog(self, action_label, continue_fn):
        self._pending_unsaved_action = continue_fn
        if self._unsaved_changes_dialog:
            self._defer_window_destroy(self._unsaved_changes_dialog)
            self._unsaved_changes_dialog = None
        self._unsaved_changes_dialog = ui.Window("Unsaved Changes", width=500, height=180)
        with self._unsaved_changes_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label("The current workspace has unsaved changes.", word_wrap=True)
                ui.Label(
                    f"Save changes before you {action_label}, discard them, or cancel.",
                    word_wrap=True,
                )
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button("Save", width=90, clicked_fn=self._save_unsaved_changes)
                    ui.Button("Save As", width=100, clicked_fn=self._save_unsaved_changes_as)
                    ui.Button("Discard", width=110, clicked_fn=self._discard_unsaved_changes)
                    ui.Button("Cancel", width=110, clicked_fn=self._cancel_unsaved_changes)
                    ui.Spacer(width=8)
        self._set_status("Unsaved changes need confirmation.")

    def _save_unsaved_changes(self):
        action = self._pending_unsaved_action
        if not action:
            self._close_unsaved_changes_dialog()
            return
        if not self._workspace_path:
            self._save_unsaved_changes_as()
            return
        if self._save_workspace_to_path(self._workspace_path):
            self._close_unsaved_changes_dialog()
            action()

    def _save_unsaved_changes_as(self):
        action = self._pending_unsaved_action
        self._close_unsaved_changes_dialog()
        self._show_save_workspace_dialog(action)

    def _discard_unsaved_changes(self):
        action = self._pending_unsaved_action
        self._close_unsaved_changes_dialog()
        self._clear_dirty_tracking()
        if action:
            action()

    def _cancel_unsaved_changes(self):
        self._close_unsaved_changes_dialog()
        self._set_status("Canceled because the current workspace has unsaved changes.")

    def _close_unsaved_changes_dialog(self):
        self._pending_unsaved_action = None
        if self._unsaved_changes_dialog:
            self._defer_window_destroy(self._unsaved_changes_dialog)
            self._unsaved_changes_dialog = None

    def _set_dirty(self, dirty=True):
        self._is_dirty = bool(dirty)
        self._refresh_dirty_indicator()

    def _clear_dirty_tracking(self):
        self._content_dirty = False
        self._display_camera_dirty = False
        self._saved_display_camera_settings = (
            self._normalized_settings_value(self._display_camera_settings_snapshot()) if self._state else None
        )
        self._set_dirty(False)

    def _mark_content_dirty(self):
        if self._state:
            self._content_dirty = True
            self._set_dirty(True)

    def _refresh_tracked_dirty_state(self):
        self._set_dirty(bool(getattr(self, "_content_dirty", False) or getattr(self, "_display_camera_dirty", False)))

    def _update_display_camera_dirty(self):
        if not self._state:
            return
        saved_settings = getattr(self, "_saved_display_camera_settings", None)
        if saved_settings is None:
            self._display_camera_dirty = True
        else:
            current_settings = self._normalized_settings_value(self._display_camera_settings_snapshot())
            self._display_camera_dirty = current_settings != saved_settings
        self._refresh_tracked_dirty_state()

    def _apply_dirty_scope(self, scope):
        if scope == "content":
            self._mark_content_dirty()
        elif scope == "display_camera":
            self._update_display_camera_dirty()

    def _run_dataset_command(self, command_fn, reset_dirty=True):
        result = command_fn()
        if result is not False:
            self._after_dataset_command_applied(reset_dirty=reset_dirty)
        return result

    def _after_dataset_command_applied(self, reset_dirty=True):
        self._refresh_detection_panel()
        self._queue_geometries_window_refresh()
        self._queue_transactions_window_refresh()
        self._refresh_toolbar_state()
        if self._state:
            self._sync_parameter_transaction_baseline()
        if reset_dirty:
            self._clear_dirty_tracking()

    def _run_state_command(self, command_fn, dirty_scope=None):
        if not self._state:
            return None
        before_index = self._state.transaction_index
        before_length = len(self._state.transaction_log)
        result = command_fn()
        transaction = self._latest_transaction_after(before_index, before_length)
        if transaction:
            self._after_state_command_recorded(transaction, dirty_scope=dirty_scope)
        return result

    def _record_state_change_command(self, event_type, state_before, state_after, result_id=None, dirty_scope=None):
        if not self._state:
            return None
        transaction = self._state.record_state_change(event_type, state_before, state_after, result_id=result_id)
        if transaction:
            self._after_state_command_recorded(transaction, dirty_scope=dirty_scope)
        return transaction

    def _latest_transaction_after(self, before_index, before_length):
        if not self._state:
            return None
        if self._state.transaction_index <= before_index or len(self._state.transaction_log) <= before_length:
            return None
        return self._state.transaction_log[self._state.transaction_index - 1]

    def _after_state_command_recorded(self, transaction, dirty_scope=None):
        scope = dirty_scope or self._dirty_scope_for_transaction(transaction)
        self._apply_dirty_scope(scope)
        self._refresh_toolbar_state()
        self._queue_transactions_window_refresh()

    def _dirty_scope_for_transaction(self, transaction):
        event_type = getattr(transaction, "event_type", None)
        if event_type in (
            TRANSACTION_APPLY_DETECTION,
            TRANSACTION_DELETE_GEOMETRY,
            TRANSACTION_CANCEL_DETECTION,
            TRANSACTION_RESET_DETECTION,
            TRANSACTION_GEOMETRY_VISIBILITY,
            TRANSACTION_PARAMETER_CHANGE,
        ):
            return "content"
        if event_type == TRANSACTION_GLOBAL_VISIBILITY:
            return "display_camera"
        if event_type == TRANSACTION_CAMERA_CHANGE:
            return "display_camera"
        return None

    def _camera_transaction_state(self):
        camera = getattr(getattr(self, "_viewport", None), "camera", None)
        if camera is None:
            return None
        return self._normalized_settings_value(
            {
                "projection_mode": camera.projection_mode,
                "center": list(camera.center),
                "orientation": list(camera.orientation),
                "zoom": float(camera.zoom),
                "diameter": float(camera.diameter),
                "fov_degrees": float(camera.fov_degrees),
            }
        )

    def _record_camera_change(self, state_before, state_after=None):
        if state_before is None:
            return None
        if state_after is None:
            state_after = self._camera_transaction_state()
        return self._record_state_change_command(
            TRANSACTION_CAMERA_CHANGE,
            state_before,
            state_after,
            dirty_scope="display_camera",
        )

    def _commit_camera_change(self, change_fn):
        state_before = self._camera_transaction_state()
        self._suppress_camera_transaction = True
        try:
            result = change_fn()
        finally:
            self._suppress_camera_transaction = False
        self._sync_camera_models()
        self._record_camera_change(state_before)
        return result

    def _on_camera_changed(self, phase="commit"):
        if getattr(self, "_suppress_camera_transaction", False):
            self._sync_camera_models()
            return
        phase = phase or "commit"
        if phase == "begin":
            self._pending_camera_transaction_state = self._camera_transaction_state()
            self._sync_camera_models()
            return
        if phase == "change":
            self._sync_camera_models()
            return
        state_before = getattr(self, "_pending_camera_transaction_state", None)
        self._pending_camera_transaction_state = None
        self._sync_camera_models()
        if state_before is not None:
            self._record_camera_change(state_before)

    def _apply_camera_state(self, state):
        camera = getattr(getattr(self, "_viewport", None), "camera", None)
        if camera is None or not isinstance(state, dict):
            return False
        self._suppress_camera_transaction = True
        try:
            camera.projection_mode = state.get("projection_mode", camera.projection_mode)
            camera.center = list(state.get("center", camera.center))
            camera.orientation = list(state.get("orientation", camera.orientation))
            camera.zoom = float(state.get("zoom", camera.zoom))
            camera.diameter = float(state.get("diameter", camera.diameter))
            camera.set_fov_degrees(state.get("fov_degrees", camera.fov_degrees))
            if hasattr(self._viewport, "draw"):
                self._viewport.draw()
            self._sync_camera_models()
        finally:
            self._suppress_camera_transaction = False
        return True

    def _display_camera_settings_snapshot(self):
        settings = self._settings_snapshot()
        snapshot = {}
        for name, value in settings.items():
            if self._is_display_camera_setting_name(name):
                snapshot[name] = value
        return snapshot

    def _is_display_camera_setting_name(self, name):
        if name == "camera":
            return True
        if name in ("point_size", "inlier_negative_sigma", "inlier_positive_sigma"):
            return True
        if name in ("outlier_points_visible", "surface_meshes_visible", "inlier_points_visible"):
            return True
        return name.startswith(
            (
                "point_",
                "selected_point_",
                "inlier_negative_",
                "inlier_zero_",
                "inlier_positive_",
                "surface_",
                "surface_wire_",
                "histogram_tooltip_",
            )
        )

    def _normalized_settings_value(self, value):
        if isinstance(value, float):
            return round(value, 12)
        if isinstance(value, list):
            return [self._normalized_settings_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._normalized_settings_value(item) for item in value)
        if isinstance(value, dict):
            return {key: self._normalized_settings_value(value[key]) for key in sorted(value)}
        return value

    def _parameter_transaction_state(self):
        state = {"detection_type": self._detection_type}
        for name in self._parameter_transaction_model_names():
            if name == "detection_type":
                continue
            model = self._models.get(name)
            if model is None:
                continue
            state[name] = self._parameter_model_value(name, model)
        return self._normalized_settings_value(state)

    def _parameter_model_value(self, name, model):
        if name.endswith("_slider_index") or name in ("radial_expansion", "lateral_extension"):
            if hasattr(model, "as_int"):
                return int(model.as_int)
            if hasattr(model, "get_value_as_int"):
                return int(model.get_value_as_int())
            return int(model.get_value())
        if hasattr(model, "as_float"):
            return float(model.as_float)
        if hasattr(model, "get_value_as_float"):
            return float(model.get_value_as_float())
        return float(model.get_value())

    def _parameter_transaction_model_names(self):
        names = ["detection_type"]
        for name in self.RANGE_PARAMETER_DEFAULTS:
            names.extend((name, f"{name}_min", f"{name}_max", f"{name}_slider_index"))
        names.extend(("radial_expansion", "lateral_extension"))
        return tuple(names)

    def _parameter_state_changed_name(self, state_before, state_after):
        for name in self._parameter_transaction_model_names():
            if (state_before or {}).get(name) != (state_after or {}).get(name):
                return name
        return None

    def _sync_parameter_transaction_baseline(self):
        self._last_parameter_transaction_state = self._parameter_transaction_state()

    def _range_parameter_group_state(self, name):
        required = (name, f"{name}_min", f"{name}_max", f"{name}_slider_index")
        if any(model_name not in self._models for model_name in required):
            return {}
        return {
            f"{name}_min": float(self._models[f"{name}_min"].as_float),
            f"{name}_max": float(self._models[f"{name}_max"].as_float),
            name: float(self._models[name].as_float),
            f"{name}_slider_index": int(self._model_int(f"{name}_slider_index")),
        }

    def _record_parameter_change(self, changed=None, state_before=None, keep_open=False):
        if not self._state or self._syncing_models:
            return None
        if changed not in self._parameter_transaction_model_names():
            return None
        state_after = self._parameter_transaction_state()
        if state_before is None:
            state_before = getattr(self, "_last_parameter_transaction_state", None)
        if state_before is None:
            self._last_parameter_transaction_state = state_after
            return None
        if state_before == state_after and getattr(self, "_pending_parameter_state_before", None) is None:
            return None
        if keep_open:
            pending_name = getattr(self, "_pending_parameter_name", None)
            if pending_name is not None and pending_name != changed:
                self._finalize_pending_parameter_change()
                state_before = getattr(self, "_last_parameter_transaction_state", None)
            if state_before == state_after:
                return None
            if getattr(self, "_pending_parameter_state_before", None) is None:
                self._pending_parameter_state_before = state_before
            self._pending_parameter_name = changed
            self._pending_parameter_state_after = state_after
            self._pending_parameter_stable_updates = 0
            return None
        self._finalize_pending_parameter_change()
        state_before = getattr(self, "_last_parameter_transaction_state", None)
        transaction = self._record_state_change_command(TRANSACTION_PARAMETER_CHANGE, state_before, state_after)
        self._last_parameter_transaction_state = state_after
        return transaction

    def _finalize_pending_parameter_change(self):
        state_before = getattr(self, "_pending_parameter_state_before", None)
        state_after = getattr(self, "_pending_parameter_state_after", None)
        transaction = None
        if state_before is not None and state_after is not None:
            if state_before == state_after:
                self._last_parameter_transaction_state = self._normalized_settings_value(state_before)
            else:
                transaction = self._record_state_change_command(
                    TRANSACTION_PARAMETER_CHANGE,
                    state_before,
                    state_after,
                )
                self._last_parameter_transaction_state = self._normalized_settings_value(state_after)
        self._pending_parameter_state_before = None
        self._pending_parameter_state_after = None
        self._pending_parameter_name = None
        self._pending_parameter_stable_updates = 0
        return transaction

    def _on_detection_parameter_value_changed(self, changed=None, sync_parameter_pad=True):
        changed = self._range_parameter_name(changed) or changed
        if sync_parameter_pad:
            self._sync_parameter_pad_for_changed_parameter(changed)
        if changed and self._model_is_editing(changed):
            return
        self._suppress_parameter_transaction = True
        try:
            self._on_detection_settings_changed(changed)
        finally:
            self._suppress_parameter_transaction = False
        self._record_parameter_change(changed, keep_open=True)
        if getattr(self, "_pending_parameter_state_before", None) is not None:
            self._apply_dirty_scope("content")

    def _on_detection_parameter_edit_finished(self, changed=None):
        if self._syncing_models:
            return
        original_changed = changed
        if original_changed and self._model_is_editing(original_changed):
            return
        self._parameter_control_active = False
        changed = self._range_parameter_name(changed) or changed
        if changed in self.RANGE_PARAMETER_DEFAULTS:
            self._commit_range_parameter_edit(changed)
            return
        if getattr(self, "_pending_parameter_state_before", None) is None:
            transaction = self._record_parameter_change(changed)
            return
        self._finalize_pending_parameter_change()

    def _sync_parameter_transaction_from_models(self, finalize=False):
        if not self._state or self._syncing_models:
            return None
        if self._any_parameter_model_editing():
            return None
        baseline = getattr(self, "_last_parameter_transaction_state", None)
        if baseline is None:
            self._sync_parameter_transaction_baseline()
            return None
        if self._any_range_edit_model_dirty():
            return None
        if getattr(self, "_parameter_control_active", False):
            return None
        pending_after = getattr(self, "_pending_parameter_state_after", None)
        compare_state = pending_after if pending_after is not None else baseline
        self._sync_range_model_dependencies(compare_state)
        current = self._parameter_transaction_state()
        if current == compare_state:
            if finalize:
                self._finalize_pending_parameter_change()
            elif pending_after is not None and not getattr(self, "_parameter_control_active", False):
                self._pending_parameter_stable_updates += 1
                if self._pending_parameter_stable_updates >= 2:
                    self._finalize_pending_parameter_change()
            return None
        changed = self._parameter_state_changed_name(compare_state, current)
        changed = self._range_parameter_name(changed) or changed
        self._suppress_parameter_transaction = True
        try:
            self._on_detection_settings_changed(changed)
        finally:
            self._suppress_parameter_transaction = False
        transaction = self._record_parameter_change(changed, keep_open=not finalize)
        if not finalize:
            self._apply_dirty_scope("content")
        if finalize:
            self._finalize_pending_parameter_change()
        return transaction

    def _any_parameter_model_editing(self):
        for name in self._parameter_transaction_model_names():
            if name == "detection_type":
                continue
            if self._model_is_editing(name):
                return True
        return False

    def _model_is_editing(self, name):
        model = self._range_edit_models.get(name) or self._models.get(name)
        if model is None:
            return False
        method = getattr(model, "is_editing", None)
        if callable(method):
            try:
                return bool(method())
            except Exception:
                return False
        return bool(getattr(model, "editing", False))

    def _any_range_edit_model_dirty(self):
        return bool(getattr(self, "_range_edit_dirty", set()))

    def _range_edit_model_dirty(self, name):
        if name not in self.RANGE_PARAMETER_DEFAULTS:
            return False
        return any(model_name in self._range_edit_dirty for model_name in (name, f"{name}_min", f"{name}_max"))

    def _sync_range_model_dependencies(self, previous_state):
        if self._syncing_models:
            return
        was_syncing = self._syncing_models
        self._syncing_models = True
        try:
            for name in self.RANGE_PARAMETER_DEFAULTS:
                required = (name, f"{name}_min", f"{name}_max", f"{name}_slider_index")
                if any(model_name not in self._models for model_name in required):
                    continue
                value_name = name
                slider_name = f"{name}_slider_index"
                current_value = self._models[name].as_float
                current_slider = self._model_int(slider_name)
                previous_value = (previous_state or {}).get(value_name)
                previous_slider = (previous_state or {}).get(slider_name)
                minimum, maximum = self._range_bounds(name, round_endpoints=False)
                self._set_range_slider_bounds(name, minimum, maximum)
                if previous_slider is not None and current_slider != previous_slider and current_value == previous_value:
                    value = self._range_slider_value_for_index(current_slider, minimum, maximum)
                    self._models[name].set_value(value)
                else:
                    value = self._normalized_range_value(name)
                    if value != current_value:
                        self._models[name].set_value(value)
                    self._sync_range_slider_index(name, value=value, minimum=minimum, maximum=maximum)
        finally:
            self._syncing_models = was_syncing
        for name in self.RANGE_PARAMETER_DEFAULTS:
            self._sync_range_edit_models(name)

    def _on_display_settings_changed(self, changed=None):
        if self._syncing_models:
            return
        if changed == "point_size" or changed is None:
            self._viewport.set_point_size(self._models["point_size"].as_float)
        if changed is None or changed.startswith("point_"):
            self._viewport.set_point_color(self._read_color("point"))
        if changed is None or changed.startswith("selected_point_"):
            self._viewport.set_selected_point_color(self._read_color("selected_point"))
        if changed is None or changed.startswith("inlier_"):
            self._viewport.set_inlier_colors(
                negative_color=self._read_color("inlier_negative"),
                zero_color=self._read_color("inlier_zero"),
                positive_color=self._read_color("inlier_positive"),
                negative_sigma=self._model_float("inlier_negative_sigma"),
                positive_sigma=self._model_float("inlier_positive_sigma"),
            )
        if changed is None or changed.startswith("surface_"):
            self._viewport.set_surface_color(self._read_color("surface"))
            self._viewport.set_surface_wire_color(self._read_color("surface_wire"))
        if changed is None or changed.startswith("histogram_tooltip_"):
            self._queue_geometries_window_refresh()
        if changed is None or changed.startswith("inlier_"):
            self._refresh_viewport_overlays()
        self._apply_dirty_scope("display_camera")

    def _read_color(self, prefix):
        brightness = max(0.0, self._model_float(f"{prefix}_brightness"))
        return [
            max(0.0, min(1.0, self._model_float(f"{prefix}_r") * brightness)),
            max(0.0, min(1.0, self._model_float(f"{prefix}_g") * brightness)),
            max(0.0, min(1.0, self._model_float(f"{prefix}_b") * brightness)),
            max(0.0, min(1.0, self._model_float(f"{prefix}_a"))),
        ]

    def _model_float(self, name):
        model = self._models[name]
        if hasattr(model, "as_float"):
            return model.as_float
        if hasattr(model, "get_value_as_float"):
            return model.get_value_as_float()
        return float(model.get_value())

    def _model_int(self, name):
        model = self._models[name]
        if hasattr(model, "as_int"):
            return model.as_int
        if hasattr(model, "get_value_as_int"):
            return model.get_value_as_int()
        return int(model.get_value())

    def _on_range_parameter_changed(self, changed):
        if self._syncing_models:
            return
        name = self._range_parameter_name(changed)
        if not name:
            return

        if changed in (f"{name}_min", f"{name}_max"):
            minimum, maximum = self._range_bounds(name, round_endpoints=False)
            value = self._normalized_range_value(name)
            self._syncing_models = True
            try:
                if value != self._models[name].as_float:
                    self._models[name].set_value(value)
                self._set_range_slider_bounds(name, minimum, maximum)
                self._sync_range_slider_index(name, value=value, minimum=minimum, maximum=maximum)
            finally:
                self._syncing_models = False
            self._sync_range_edit_models(name)
            self._sync_parameter_pad_for_changed_parameter(name)
            return

        if changed == f"{name}_slider_index":
            minimum, maximum = self._range_bounds(name, round_endpoints=False)
            value = self._range_slider_value_for_index(self._model_int(changed), minimum, maximum)
            old_value = self._models[name].as_float
            if value != old_value:
                self._syncing_models = True
                try:
                    self._models[name].set_value(value)
                finally:
                    self._syncing_models = False
                self._sync_range_edit_models(name)
                self._sync_parameter_pad_for_changed_parameter(name)
                self._on_detection_parameter_value_changed(name, sync_parameter_pad=False)
            else:
                self._sync_parameter_pad_for_changed_parameter(name)
            return

        minimum, maximum = self._range_bounds(name, round_endpoints=False)
        value = self._normalized_range_value(name)
        self._syncing_models = True
        try:
            if value != self._models[name].as_float:
                self._models[name].set_value(value)
            self._sync_range_slider_index(name, value=value, minimum=minimum, maximum=maximum)
        finally:
            self._syncing_models = False
        self._sync_range_edit_models(name)
        self._sync_parameter_pad_for_changed_parameter(name)

    def _sync_range_edit_models(self, name):
        if name not in self.RANGE_PARAMETER_DEFAULTS:
            return
        was_syncing = self._syncing_models
        self._syncing_models = True
        try:
            for model_name in (name, f"{name}_min", f"{name}_max"):
                edit_model = self._range_edit_models.get(model_name)
                source_model = self._models.get(model_name)
                if edit_model is not None and source_model is not None:
                    edit_model.set_value(source_model.as_float)
                    self._range_edit_dirty.discard(model_name)
        finally:
            self._syncing_models = was_syncing

    def _commit_range_edit_models(self, name):
        if name not in self.RANGE_PARAMETER_DEFAULTS:
            return False
        minimum_name = f"{name}_min"
        maximum_name = f"{name}_max"
        minimum = self._range_edit_model(minimum_name).as_float
        maximum = self._range_edit_model(maximum_name).as_float
        value = self._range_edit_model(name).as_float

        was_syncing = self._syncing_models
        self._syncing_models = True
        try:
            self._models[minimum_name].set_value(minimum)
            self._models[maximum_name].set_value(maximum)
            minimum, maximum = self._range_bounds(name, round_endpoints=False)
            self._set_range_slider_bounds(name, minimum, maximum)
            value = max(minimum, min(maximum, max(self.RANGE_PARAMETER_MINIMUM, value)))
            old_value = self._models[name].as_float
            if value != old_value:
                self._models[name].set_value(value)
            self._sync_range_slider_index(name, value=value, minimum=minimum, maximum=maximum)
        finally:
            self._syncing_models = was_syncing
        self._sync_range_edit_models(name)
        return True

    def _on_range_endpoint_edit_finished(self, changed):
        if self._syncing_models:
            return
        if changed and self._model_is_editing(changed):
            return
        name = self._range_parameter_name(changed)
        if not name:
            return
        self._commit_range_parameter_edit(name)

    def _commit_range_parameter_edit(self, name):
        if self._syncing_models:
            return
        if not name or name not in self.RANGE_PARAMETER_DEFAULTS:
            return
        self._commit_range_edit_models(name)

        minimum, maximum = self._range_bounds(name, round_endpoints=True)
        value = max(minimum, min(maximum, max(self.RANGE_PARAMETER_MINIMUM, self._models[name].as_float)))

        was_syncing = self._syncing_models
        self._syncing_models = True
        try:
            self._models[f"{name}_min"].set_value(minimum)
            self._models[f"{name}_max"].set_value(maximum)
            self._set_range_slider_bounds(name, minimum, maximum)
            self._models[name].set_value(value)
            self._sync_range_slider_index(name, value=value, minimum=minimum, maximum=maximum)
        finally:
            self._syncing_models = was_syncing
        self._sync_range_edit_models(name)

        if self._parameter_transaction_state() != getattr(self, "_last_parameter_transaction_state", None):
            self._on_detection_parameter_value_changed(name)
            self._finalize_pending_parameter_change()

    def _on_detection_settings_changed(self, changed=None):
        if self._syncing_models:
            return
        if "probe_radius" in self._models:
            self._viewport.set_probe_radius(self._models["probe_radius"].as_float)
        if "seed_radius" in self._models:
            self._viewport.set_seed_radius(self._models["seed_radius"].as_float)
        if "pick_nearest_on_probe_miss" in self._models and hasattr(self._viewport, "set_pick_nearest_on_probe_miss"):
            self._viewport.set_pick_nearest_on_probe_miss(self._models["pick_nearest_on_probe_miss"].as_bool)
        if changed == "auto_detect" and not self._is_auto_detect_enabled():
            self._clear_hover_auto_detect_preview()
        elif changed in ("sticky_auto_preview", "sticky_auto_preview_timeout_ms"):
            self._refresh_sticky_auto_preview_policy(changed)
        else:
            self._request_auto_detect()
        if changed and self._state:
            transaction = None
            if not getattr(self, "_suppress_parameter_transaction", False):
                transaction = self._record_parameter_change(changed)
            if not transaction:
                self._apply_dirty_scope("content")

    def _is_detection_paused(self):
        return bool(getattr(self, "_detection_paused", False))

    def _set_inspect_mode(self):
        if self._is_detection_paused():
            return
        self._sync_parameter_transaction_from_models(finalize=True)
        self._finalize_pending_parameter_change()
        self._detection_paused = True
        self._selected_index = None
        self._clear_viewport_hover_pick()
        if getattr(self, "_viewport", None):
            self._viewport.set_pick_markers(None, None)
        self._clear_auto_detect_preview()
        self._sync_detection_surfaces()
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._set_status("Detection paused: inspecting geometries")

    def _resume_detection(self):
        if not self._is_detection_paused():
            return False
        self._detection_paused = False
        self._sync_viewport_picking_enabled(not self._is_modal_or_overlay_visible())
        return True

    def _set_detection_type(self, detection_type):
        was_paused = self._resume_detection()
        if detection_type == self._detection_type and not was_paused:
            return
        self._sync_parameter_transaction_from_models(finalize=True)
        self._finalize_pending_parameter_change()
        state_before = self._parameter_transaction_state()
        if detection_type != self._detection_type:
            self._detection_type = detection_type
            self._record_parameter_change("detection_type", state_before=state_before)
        self._set_status(f"Detection type: {detection_type}")
        self._refresh_toolbar_state()
        self._request_auto_detect()

    def _read_options(self):
        options = DetectionOptions(
            detection_type=self._detection_type,
            seed_radius=self._models["seed_radius"].as_float,
            measurement_accuracy=self._models["measurement_accuracy"].as_float,
            mean_distance=self._models["mean_distance"].as_float,
            radial_expansion=self._models["radial_expansion"].as_int,
            lateral_extension=self._models["lateral_extension"].as_int,
        )
        options.validate()
        return options

    def _range_parameter_name(self, changed):
        if changed in self.RANGE_PARAMETER_DEFAULTS:
            return changed
        for name in self.RANGE_PARAMETER_DEFAULTS:
            if changed in (f"{name}_min", f"{name}_max", f"{name}_slider_index"):
                return name
        return None

    def _new_range_float_model(self, value):
        return ui.SimpleFloatModel(float(value))

    def _new_range_slider_index_model(self, value):
        return ui.SimpleIntModel(int(value))

    def _set_range_slider_bounds(self, name, minimum, maximum):
        slider = self._range_sliders.get(name)
        if slider is not None:
            slider.min = 0
            slider.max = self._range_slider_index_count(minimum, maximum)
            slider.enabled = maximum > minimum

    def _range_bounds(self, name, round_endpoints):
        raw_minimum = self._models[f"{name}_min"].as_float
        raw_maximum = self._models[f"{name}_max"].as_float
        minimum = max(self.RANGE_PARAMETER_MINIMUM, raw_minimum)
        maximum = max(self.RANGE_PARAMETER_MINIMUM, raw_maximum)
        if round_endpoints:
            minimum = self._round_range_endpoint(minimum)
            maximum = self._round_range_endpoint(maximum)
        if minimum > maximum:
            if raw_minimum >= raw_maximum:
                maximum = minimum
            else:
                minimum = maximum
        return minimum, maximum

    def _range_slider_step(self, minimum, maximum):
        return self._range_slider_value_step(minimum, maximum)

    def _range_slider_value_step(self, minimum, maximum):
        interval = max(float(maximum) - float(minimum), 0.0)
        if interval < self.RANGE_PARAMETER_MINIMUM_STEP * self.RANGE_PARAMETER_VALUE_STEPS:
            return self.RANGE_PARAMETER_MINIMUM_STEP
        return interval / self.RANGE_PARAMETER_VALUE_STEPS

    def _range_slider_index_count(self, minimum, maximum):
        interval = max(float(maximum) - float(minimum), 0.0)
        if interval <= 0.0:
            return 0
        step = self._range_slider_value_step(minimum, maximum)
        if step <= 0.0:
            return 0
        return max(1, int(round(interval / step)))

    def _range_slider_value_for_index(self, index, minimum, maximum):
        minimum = float(minimum)
        maximum = float(maximum)
        count = self._range_slider_index_count(minimum, maximum)
        if count <= 0:
            return max(self.RANGE_PARAMETER_MINIMUM, minimum)
        index = max(0, min(count, int(index)))
        if index == count:
            return maximum
        value = minimum + self._range_slider_value_step(minimum, maximum) * index
        return max(minimum, min(maximum, value))

    def _range_slider_index_for_value(self, value, minimum, maximum):
        minimum = float(minimum)
        maximum = float(maximum)
        count = self._range_slider_index_count(minimum, maximum)
        if count <= 0:
            return 0
        value = float(value)
        if value <= minimum:
            return 0
        if value >= maximum:
            return count
        step = self._range_slider_value_step(minimum, maximum)
        if step <= 0.0:
            return 0
        return max(0, min(count, int(round((value - minimum) / step))))

    def _sync_range_slider_index(self, name, value=None, minimum=None, maximum=None):
        model = self._models.get(f"{name}_slider_index")
        if model is None:
            return
        if value is None:
            value = self._models[name].as_float
        if minimum is None or maximum is None:
            minimum, maximum = self._range_bounds(name, round_endpoints=False)
        index = self._range_slider_index_for_value(value, minimum, maximum)
        current = self._model_int(f"{name}_slider_index")
        if index != current:
            model.set_value(index)
        self._set_slider_widget_value(self._range_sliders.get(name), index)

    def _set_slider_widget_value(self, slider, value):
        if slider is None:
            return False
        value = int(value)
        for method_name in ("set_value", "set_value_as_int"):
            method = getattr(slider, method_name, None)
            if callable(method):
                try:
                    method(value)
                    return True
                except Exception:
                    pass
        for attr_name in ("model", "value_model"):
            try:
                value_model = getattr(slider, attr_name)
            except Exception:
                continue
            if hasattr(value_model, "set_value"):
                try:
                    value_model.set_value(value)
                    return True
                except Exception:
                    pass
        for attr_name in ("value", "as_int"):
            try:
                setattr(slider, attr_name, value)
                return True
            except Exception:
                pass
        return False

    def _normalized_range_value(self, name):
        minimum, maximum = self._range_bounds(name, round_endpoints=False)
        value = max(self.RANGE_PARAMETER_MINIMUM, self._models[name].as_float)
        return max(minimum, min(maximum, value))

    def _round_range_endpoint(self, value):
        return max(self.RANGE_PARAMETER_MINIMUM, float(self._format_range_parameter_value(value)))

    def _format_range_parameter_value(self, value):
        return f"{float(value):.4f}"

    def _is_auto_detect_enabled(self):
        return not self._is_detection_paused()

    def _is_auto_detect_source_enabled(self, source):
        if self._is_detection_paused():
            return False
        if source == "hover":
            return self._is_auto_detect_enabled()
        return source == "selected"

    def _is_sticky_auto_preview_enabled(self):
        model = self._models.get("sticky_auto_preview")
        return bool(model and getattr(model, "as_bool", False))

    def _sticky_auto_preview_timeout_seconds(self):
        model = self._models.get("sticky_auto_preview_timeout_ms")
        if not model:
            return 3.0
        if hasattr(model, "as_int"):
            value = model.as_int
        elif hasattr(model, "get_value_as_int"):
            value = model.get_value_as_int()
        else:
            value = int(model.get_value())
        return max(0.1, float(value) / 1000.0)

    def _refresh_sticky_auto_preview_policy(self, changed=None):
        if self._is_sticky_auto_preview_enabled() and self._auto_detect_result is not None:
            self._auto_detect_display_deadline = self._sticky_auto_preview_deadline(self._auto_detect_result)
        elif not self._is_sticky_auto_preview_enabled():
            self._auto_detect_display_deadline = None
        self._sync_detection_surfaces()
        self._refresh_detection_panel()
        self._refresh_status_bar()

    def _sticky_auto_preview_deadline(self, result):
        if not self._is_sticky_auto_preview_enabled():
            return None
        if self._auto_detect_result_matches_current_seed(result):
            return None
        return time.monotonic() + self._sticky_auto_preview_timeout_seconds()

    def _sticky_auto_preview_matches_current_hover(self, result):
        return self._auto_detect_result_matches_current_seed(result)

    def _auto_detect_result_matches_current_seed(self, result):
        if result is None:
            return False
        seed_index = getattr(result, "seed_index", None)
        source = getattr(self, "_auto_detect_source", None)
        if source == "selected":
            return (
                seed_index is not None
                and seed_index == self._selected_index
                and self._is_active_index(self._selected_index)
            )
        if source == "hover":
            return (
                seed_index is not None
                and self._selected_index is None
                and seed_index == self._hover_index
                and self._is_active_index(self._hover_index)
            )
        return False

    def _on_hover_changed(self, index):
        if self._is_detection_paused():
            self._hover_index = None
            self._clear_auto_detect_preview()
            self._refresh_detection_panel()
            return
        self._hover_index = index
        self._refresh_detection_panel()
        if self._selected_index is not None and self._is_active_index(self._selected_index):
            return
        self._request_auto_detect()

    def _on_seed_selected(self, index):
        if self._is_detection_paused():
            self._clear_auto_detect_preview()
            return
        self._selected_index = index
        self._refresh_detection_panel()
        self._request_auto_detect()

    def _pick_center_seed(self):
        if self._is_detection_paused():
            self._set_status("Choose a detection type before picking a seed.")
            return
        if not self._state:
            self._set_status("Import a point cloud before picking a seed.")
            return
        index = pick_center_point(self._state)
        self._selected_index = index
        self._viewport.set_pick_markers(self._hover_index, self._selected_index)
        self._refresh_detection_panel()
        self._request_auto_detect()
        self._set_status(f"Selected point near cloud center: {index}" if index is not None else "No active points remain.")

    def _clear_selected_seed(self):
        if self._selected_index is None:
            self._set_status("No selected point to clear.")
            return
        self._selected_index = None
        self._viewport.set_pick_markers(self._hover_index, None)
        self._refresh_detection_panel()
        self._request_auto_detect()
        self._set_status("Cleared selected point.")

    def _effective_seed(self):
        if not self._state:
            return None, None
        if self._selected_index is not None and self._is_active_index(self._selected_index):
            return self._selected_index, "selected"
        if self._hover_index is not None and self._is_active_index(self._hover_index):
            return self._hover_index, "hover"
        return None, None

    def _request_auto_detect(self):
        if getattr(self, "_app_shutting_down", False):
            return
        if self._is_detection_paused():
            self._clear_auto_detect_preview()
            return
        if not self._state:
            self._clear_auto_detect_preview()
            return
        provider = getattr(self, "_provider", None)
        if not provider:
            self._clear_auto_detect_preview()
            disabled_reason = getattr(self, "_auto_detect_disabled_reason", None)
            if disabled_reason:
                self._set_status(f"Native FindSurface unavailable: {disabled_reason}")
            return
        seed_index, source = self._effective_seed()
        if seed_index is None:
            with self._auto_detect_lock:
                if self._auto_detect_busy:
                    return
            if not self._is_sticky_auto_preview_enabled():
                self._clear_auto_detect_preview()
            return
        if not self._is_auto_detect_source_enabled(source):
            if source == "hover":
                self._clear_hover_auto_detect_preview()
            return
        try:
            options = self._read_options()
        except Exception as exc:
            self._clear_auto_detect_preview()
            self._set_status(str(exc))
            return

        if source == "selected" and self._reuse_auto_detect_result_for_selected_seed(seed_index, options):
            return

        key = self._auto_detect_request_key(seed_index, source, options)
        should_start = False
        request_token = None
        with self._auto_detect_lock:
            if key == self._auto_detect_key:
                return
            if self._auto_detect_busy:
                self._auto_detect_deferred = (key, source, self._state, seed_index, options)
                return
            self._auto_detect_key = key
            self._auto_detect_busy = True
            self._auto_detect_deferred = None
            request_token = self._auto_detect_request_token
            should_start = True
        if not self._is_sticky_auto_preview_enabled():
            self._clear_visible_auto_detect_preview()
        if should_start:
            self._start_auto_detect_worker(key, source, self._state, seed_index, options, request_token)

    def _reuse_auto_detect_result_for_selected_seed(self, seed_index, options):
        result, source_key = self._last_successful_auto_detect_result_for_seed(seed_index)
        if result is None:
            return False
        if not self._auto_detect_key_matches_seed_and_options(source_key, seed_index, options):
            return False
        key = self._auto_detect_request_key(seed_index, "selected", options)
        with self._auto_detect_lock:
            self._auto_detect_request_token = getattr(self, "_auto_detect_request_token", 0) + 1
            self._auto_detect_key = key
            self._auto_detect_pending = None
            self._auto_detect_deferred = None
            self._auto_detect_busy = False
        self._auto_detect_result = result
        self._auto_detect_source = "selected"
        self._last_successful_auto_detect_result = result
        self._last_successful_auto_detect_key = key
        self._auto_detect_overlay_suppressed = False
        self._auto_detect_display_deadline = self._sticky_auto_preview_deadline(result)
        self._sync_detection_surfaces()
        self._refresh_detection_panel()
        self._set_status(self._detection_result_status("Auto preview", result))
        return True

    def _last_successful_auto_detect_result_for_seed(self, seed_index):
        result = self._auto_detect_result
        if (
            self._auto_detect_source in ("hover", "selected")
            and self._is_successful_auto_detect_result_for_seed(result, seed_index)
        ):
            return result, self._auto_detect_key
        result = getattr(self, "_last_successful_auto_detect_result", None)
        if self._is_successful_auto_detect_result_for_seed(result, seed_index):
            return result, getattr(self, "_last_successful_auto_detect_key", None)
        return None, None

    def _is_successful_auto_detect_result_for_seed(self, result, seed_index):
        if not self._state or result is None:
            return False
        if getattr(result, "active_generation", None) != self._state.generation:
            return False
        if getattr(result, "seed_index", None) != seed_index:
            return False
        if not getattr(result, "inlier_indices", None):
            return False
        return self._is_active_index(seed_index)

    def _auto_detect_key_matches_seed_and_options(self, key, seed_index, options):
        if not key or not self._state:
            return False
        if key[0] != id(self._state) or key[1] != self._state.generation or key[2] != seed_index:
            return False
        return key[4:] == (
            options.detection_type,
            options.seed_radius,
            options.measurement_accuracy,
            options.mean_distance,
            options.radial_expansion,
            options.lateral_extension,
        )

    def _start_auto_detect_worker(self, key, source, state, seed_index, options, request_token=None):
        if request_token is None:
            with self._auto_detect_lock:
                request_token = self._auto_detect_request_token
        Thread(target=self._auto_detect_worker, args=(key, source, state, seed_index, options, request_token), daemon=True).start()

    def _auto_detect_request_key(self, seed_index, source, options):
        return (
            id(self._state),
            self._state.generation,
            seed_index,
            source,
            options.detection_type,
            options.seed_radius,
            options.measurement_accuracy,
            options.mean_distance,
            options.radial_expansion,
            options.lateral_extension,
        )

    def _auto_detect_worker(self, key, source, state, seed_index, options, request_token=None):
        if getattr(self, "_app_shutting_down", False):
            return
        result = None
        error = None
        try:
            result = self._provider.detect(
                state.points,
                seed_index,
                options,
                active_mask=state.active_mask,
                active_generation=key[1],
            )
            result.active_generation = key[1]
            result.id = f"Auto{source.capitalize()}_{result.id}"
        except Exception as exc:
            error = exc
        with self._auto_detect_lock:
            if (
                getattr(self, "_app_shutting_down", False)
                or request_token != self._auto_detect_request_token
                or key != self._auto_detect_key
            ):
                return
            self._auto_detect_pending = (key, source, result, error)

    def _apply_auto_detect_pending(self):
        if getattr(self, "_app_shutting_down", False):
            with self._auto_detect_lock:
                self._auto_detect_pending = None
                self._auto_detect_deferred = None
                self._auto_detect_busy = False
            return
        with self._auto_detect_lock:
            pending = self._auto_detect_pending
            self._auto_detect_pending = None
            current_key = self._auto_detect_key
        if not pending:
            return
        key, source, result, error = pending
        try:
            if not self._state:
                return
            if key != current_key or not self._is_auto_detect_source_enabled(source):
                return
            if key[0] != id(self._state) or key[1] != self._state.generation:
                return
            if error or result is None:
                if source == "selected" or not self._is_sticky_auto_preview_enabled():
                    self._clear_visible_auto_detect_preview()
                else:
                    self._auto_detect_overlay_suppressed = False
                    self._auto_detect_display_deadline = self._sticky_auto_preview_deadline(self._auto_detect_result)
                    self._sync_detection_surfaces()
                    self._refresh_detection_panel()
                self._set_status(self._detection_failure_status("Auto FindSurface failed", error))
                return
            self._orient_result_to_camera(result)
            self._auto_detect_result = result
            self._auto_detect_source = source
            self._last_successful_auto_detect_result = result
            self._last_successful_auto_detect_key = key
            self._auto_detect_overlay_suppressed = False
            self._auto_detect_display_deadline = self._sticky_auto_preview_deadline(result)
            self._set_retroactive_pick_index(getattr(result, "seed_index", None))
            self._sync_detection_surfaces()
            self._refresh_detection_panel()
            self._set_status(self._detection_result_status("Auto preview", result))
        finally:
            with self._auto_detect_lock:
                self._auto_detect_busy = False
            self._start_deferred_auto_detect(key)

    def _clear_auto_detect_preview(self):
        self._invalidate_auto_detect_requests()
        self._clear_visible_auto_detect_preview()

    def _invalidate_auto_detect_requests(self):
        with self._auto_detect_lock:
            self._auto_detect_request_token = getattr(self, "_auto_detect_request_token", 0) + 1
            self._auto_detect_key = None
            self._auto_detect_pending = None
            self._auto_detect_deferred = None
            self._auto_detect_busy = False
        self._last_successful_auto_detect_result = None
        self._last_successful_auto_detect_key = None

    def _clear_hover_auto_detect_preview(self):
        with self._auto_detect_lock:
            if self._auto_detect_key and self._auto_detect_key[3] == "hover":
                self._auto_detect_key = None
            if self._auto_detect_pending and self._auto_detect_pending[1] == "hover":
                self._auto_detect_pending = None
            if self._auto_detect_deferred and self._auto_detect_deferred[1] == "hover":
                self._auto_detect_deferred = None
        if self._auto_detect_source == "hover":
            self._clear_visible_auto_detect_preview()

    def _start_deferred_auto_detect(self, completed_key):
        if getattr(self, "_app_shutting_down", False):
            return
        with self._auto_detect_lock:
            deferred = self._auto_detect_deferred
            self._auto_detect_deferred = None
            if not deferred or self._auto_detect_busy:
                return
        key, source, state, seed_index, options = deferred
        if key == completed_key:
            return
        if not self._is_auto_detect_source_enabled(source) or not self._is_current_auto_detect_request(key, source, state, seed_index):
            return
        with self._auto_detect_lock:
            if self._auto_detect_busy:
                self._auto_detect_deferred = deferred
                return
            self._auto_detect_key = key
            self._auto_detect_busy = True
            request_token = self._auto_detect_request_token
        if not self._is_sticky_auto_preview_enabled():
            self._clear_visible_auto_detect_preview()
        self._start_auto_detect_worker(key, source, state, seed_index, options, request_token)

    def _is_current_auto_detect_request(self, key, source, state, seed_index):
        if not self._state or state is not self._state:
            return False
        if key[0] != id(self._state) or key[1] != self._state.generation:
            return False
        current_seed, current_source = self._effective_seed()
        if current_seed != seed_index or current_source != source:
            return False
        try:
            options = self._read_options()
        except Exception:
            return False
        return key == self._auto_detect_request_key(seed_index, source, options)

    def _clear_visible_auto_detect_preview(self):
        self._clear_geometry_distance_histogram_cache()
        self._auto_detect_result = None
        self._auto_detect_source = None
        self._auto_detect_display_deadline = None
        self._auto_detect_overlay_suppressed = False
        self._sync_detection_surfaces()
        self._refresh_detection_panel()
        self._refresh_status_bar()

    def _expire_auto_detect_preview(self):
        if not self._is_sticky_auto_preview_enabled():
            return
        result = self._auto_detect_result
        if result is None:
            return
        if self._auto_detect_result_matches_current_seed(result):
            self._auto_detect_display_deadline = None
            return
        deadline = self._auto_detect_display_deadline
        if deadline is None:
            self._auto_detect_display_deadline = self._sticky_auto_preview_deadline(result)
            return
        if time.monotonic() < deadline:
            return
        with self._auto_detect_lock:
            if self._auto_detect_busy:
                return
            self._auto_detect_key = None
        self._clear_visible_auto_detect_preview()

    def _run_detection(self):
        if not self._state:
            self._set_status("Import a point cloud before running detection.")
            return
        if not self._provider:
            self._set_status(f"Native FindSurface unavailable: {self._auto_detect_disabled_reason}")
            return
        seed_index, _source = self._effective_seed()
        if seed_index is None:
            self._set_status("Pick a seed point before running detection.")
            return
        try:
            result = self._provider.detect(
                self._state.points,
                seed_index,
                self._read_options(),
                active_mask=self._state.active_mask,
                active_generation=self._state.generation,
            )
            result.active_generation = self._state.generation
            self._orient_result_to_camera(result)
            self._apply_confirmed_result(result)
            self._set_status(self._detection_result_status("Detected", result))
        except Exception as exc:
            carb.log_error(f"FindSurface detection failed: {exc}")
            self._clear_auto_detect_preview()
            self._set_status(self._detection_failure_status("Detection failed", exc))

    def _capture_selected_preview(self):
        if not self._state:
            self._set_status("No point cloud is loaded.")
            return
        if not self._can_capture_selected_preview():
            self._set_status("Select a point and wait for its detection preview before capturing.")
            return
        result = self._auto_detect_result
        self._apply_confirmed_result(result)
        self._set_status(self._detection_result_status("Captured", result))

    def _can_capture_selected_preview(self):
        if not self._state or self._selected_index is None or not self._is_active_index(self._selected_index):
            return False
        result = self._auto_detect_result
        if not result or self._auto_detect_source != "selected":
            return False
        if getattr(result, "seed_index", None) != self._selected_index:
            return False
        return getattr(result, "active_generation", None) == self._state.generation

    def _orient_result_to_camera(self, result):
        if getattr(result, "type", None) != "Plane":
            return
        params = getattr(result, "parameters", None)
        if not isinstance(params, dict):
            return
        normal = params.get("z_axis", params.get("normal"))
        origin = params.get("origin", getattr(result, "seed_position", None))
        camera_position = self._camera_position()
        if normal is None or origin is None or camera_position is None:
            return
        normal = normalize(normal, [0.0, 0.0, 1.0])
        direction_to_camera = sub(camera_position, origin)
        if dot(normal, direction_to_camera) >= 0.0:
            params["z_axis"] = normal
            if "normal" in params:
                params["normal"] = normal
            return
        self._flip_plane_orientation(params, normal)

    def _flip_plane_orientation(self, params, normal):
        flipped_normal = [-normal[index] for index in range(3)]
        params["z_axis"] = flipped_normal
        if "normal" in params:
            params["normal"] = flipped_normal
        if "y_axis" in params:
            y_axis = normalize(params["y_axis"], [0.0, 1.0, 0.0])
            params["y_axis"] = [-y_axis[index] for index in range(3)]
        if all(key in params for key in ("upper_left", "upper_right", "lower_left", "lower_right")):
            upper_left = params["upper_left"]
            upper_right = params["upper_right"]
            lower_left = params["lower_left"]
            lower_right = params["lower_right"]
            params["upper_left"] = lower_left
            params["upper_right"] = lower_right
            params["lower_left"] = upper_left
            params["lower_right"] = upper_right
        corners = params.get("corners")
        if isinstance(corners, list) and len(corners) == 4:
            params["corners"] = [corners[3], corners[2], corners[1], corners[0]]

    def _camera_position(self):
        camera = getattr(getattr(self, "_viewport", None), "camera", None)
        if camera is None:
            return None
        try:
            return list(camera.position)
        except Exception:
            return None

    def _apply_confirmed_result(self, result):
        result.id = self._state.next_result_id(result.type)
        self._run_state_command(lambda: self._state.apply_result(result))
        self._hover_index = None
        self._selected_index = None
        self._set_retroactive_pick_index(None)
        self._clear_auto_detect_preview()
        self._sync_detection_surfaces()
        self._viewport.set_active_mask(self._state.active_mask)
        self._viewport.set_pick_markers(None, None)
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._queue_geometries_window_refresh()

    def _undo_last(self):
        if not self._state:
            self._set_status("No point cloud is loaded.")
            return
        self._sync_parameter_transaction_from_models(finalize=True)
        transaction = self._state.transaction_log[self._state.transaction_index - 1] if self._state.can_undo else None
        result = self._state.undo_last()
        applied_state = self._apply_transaction_state(transaction, use_after=False)
        if result or self._transaction_marks_content_dirty(transaction):
            self._apply_dirty_scope("content")
        elif applied_state:
            self._apply_dirty_scope("display_camera")
        self._after_transaction_index_changed()
        self._set_status(self._undo_status(transaction, result))

    def _redo_last(self):
        if not self._state:
            self._set_status("No point cloud is loaded.")
            return
        self._sync_parameter_transaction_from_models(finalize=True)
        transaction = self._state.transaction_log[self._state.transaction_index] if self._state.can_redo else None
        result = self._state.redo_last()
        applied_state = self._apply_transaction_state(transaction, use_after=True)
        if result or self._transaction_marks_content_dirty(transaction):
            self._apply_dirty_scope("content")
        elif applied_state:
            self._apply_dirty_scope("display_camera")
        self._after_transaction_index_changed()
        self._set_status(self._redo_status(transaction, result))

    def _go_to_transaction_index(self, index):
        if not self._state:
            self._set_status("No point cloud is loaded.")
            return
        index = max(0, min(len(self._state.transaction_log), int(index)))
        changed = False
        content_dirty = False
        display_dirty = False
        while self._state.transaction_index > index:
            transaction = self._state.transaction_log[self._state.transaction_index - 1]
            result = self._state.undo_last()
            applied_state = self._apply_transaction_state(transaction, use_after=False)
            content_dirty = content_dirty or bool(result) or self._transaction_marks_content_dirty(transaction)
            display_dirty = display_dirty or applied_state
            changed = True
        while self._state.transaction_index < index:
            transaction = self._state.transaction_log[self._state.transaction_index]
            result = self._state.redo_last()
            applied_state = self._apply_transaction_state(transaction, use_after=True)
            content_dirty = content_dirty or bool(result) or self._transaction_marks_content_dirty(transaction)
            display_dirty = display_dirty or applied_state
            changed = True
        if changed:
            if content_dirty:
                self._apply_dirty_scope("content")
            elif display_dirty:
                self._apply_dirty_scope("display_camera")
        self._after_transaction_index_changed()
        self._set_status(f"Transaction state: {self._state.transaction_index} / {len(self._state.transaction_log)}")

    def _undo_status(self, transaction, result):
        if result:
            return f"Undid {result.id}."
        if transaction:
            return f"Undid {self._transaction_action_label(transaction)}."
        return "No detection action to undo."

    def _redo_status(self, transaction, result):
        if result:
            return f"Redid {result.id}."
        if transaction:
            return f"Redid {self._transaction_action_label(transaction)}."
        return "No detection action to redo."

    def _transaction_action_label(self, transaction):
        labels = {
            TRANSACTION_GLOBAL_VISIBILITY: "visibility change",
            TRANSACTION_GEOMETRY_VISIBILITY: "geometry visibility change",
            TRANSACTION_PARAMETER_CHANGE: "parameter change",
            TRANSACTION_CAMERA_CHANGE: "camera change",
        }
        return labels.get(getattr(transaction, "event_type", ""), "transaction")

    def _transaction_marks_content_dirty(self, transaction):
        return self._dirty_scope_for_transaction(transaction) == "content"

    def _apply_transaction_state(self, transaction, use_after):
        if not transaction:
            return False
        state = getattr(transaction, "state_after" if use_after else "state_before", None)
        if state is None:
            return False
        event_type = getattr(transaction, "event_type", "")
        if event_type == TRANSACTION_GLOBAL_VISIBILITY:
            self._apply_global_visibility_state(state)
            return True
        if event_type == TRANSACTION_GEOMETRY_VISIBILITY:
            return self._apply_geometry_visibility_state(getattr(transaction, "result_id", None), state)
        if event_type == TRANSACTION_PARAMETER_CHANGE:
            self._apply_parameter_state(state)
            return True
        if event_type == TRANSACTION_CAMERA_CHANGE:
            return self._apply_camera_state(state)
        return False

    def _apply_parameter_state(self, state):
        detection_type = state.get("detection_type")
        if detection_type in DETECTION_TYPES:
            self._detection_type = detection_type
        self._syncing_models = True
        try:
            applied_range_names = set()
            for name in self.RANGE_PARAMETER_DEFAULTS:
                if self._apply_range_parameter_group_state(name, state):
                    applied_range_names.update((name, f"{name}_min", f"{name}_max", f"{name}_slider_index"))
            for name in self._parameter_transaction_model_names():
                if name == "detection_type" or name in applied_range_names or name not in state:
                    continue
                model = self._models.get(name)
                if model is not None and hasattr(model, "set_value"):
                    model.set_value(state[name])
        finally:
            self._syncing_models = False
        self._sync_range_model_dependencies(state)
        self._sync_parameter_transaction_baseline()
        self._pending_parameter_name = None
        self._pending_parameter_state_before = None
        self._pending_parameter_state_after = None
        if "seed_radius" in self._models:
            self._viewport.set_seed_radius(self._models["seed_radius"].as_float)
        self._sync_parameter_pad_handle_from_models()
        self._refresh_toolbar_state()

    def _apply_range_parameter_group_state(self, name, state):
        required = (name, f"{name}_min", f"{name}_max", f"{name}_slider_index")
        if any(model_name not in self._models for model_name in required):
            return False
        minimum_name = f"{name}_min"
        maximum_name = f"{name}_max"
        slider_name = f"{name}_slider_index"
        minimum = state.get(minimum_name, self._models[minimum_name].as_float)
        maximum = state.get(maximum_name, self._models[maximum_name].as_float)
        value = state.get(name, self._models[name].as_float)
        slider_index = state.get(slider_name)
        self._models[minimum_name].set_value(float(minimum))
        self._models[maximum_name].set_value(float(maximum))
        self._set_range_slider_bounds(name, float(minimum), float(maximum))
        self._models[name].set_value(float(value))
        if slider_index is None:
            self._sync_range_slider_index(name, value=float(value), minimum=float(minimum), maximum=float(maximum))
        else:
            self._models[slider_name].set_value(int(slider_index))
        self._sync_range_edit_models(name)
        return True

    def _after_transaction_index_changed(self):
        self._set_retroactive_pick_index(None)
        self._clear_auto_detect_preview()
        self._sync_detection_surfaces()
        self._viewport.set_active_mask(self._state.active_mask)
        self._viewport.set_pick_markers(None, None)
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._queue_geometries_window_refresh()
        self._queue_transactions_window_refresh()

    def _reset_detection(self):
        if not self._state:
            self._set_status("No point cloud is loaded.")
            return
        self._run_state_command(lambda: self._state.reset())
        self._hover_index = None
        self._selected_index = None
        self._set_retroactive_pick_index(None)
        self._clear_auto_detect_preview()
        self._sync_detection_surfaces()
        self._viewport.set_active_mask(self._state.active_mask)
        self._viewport.set_pick_markers(None, None)
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._queue_geometries_window_refresh()
        self._set_status("Detection results reset.")

    def _toggle_geometry_mesh(self, result_id):
        result = self._find_result(result_id)
        if not result:
            self._set_status(f"Geometry not found: {result_id}")
            return
        before = self._geometry_visibility_state(result)
        visible = not getattr(result, "mesh_visible", True)
        self._set_geometry_visibility_field(result_id, "mesh_visible", visible)
        self._record_geometry_visibility_change(result_id, before)
        self._queue_geometries_window_refresh()

    def _toggle_geometry_inliers(self, result_id):
        result = self._find_result(result_id)
        if not result:
            self._set_status(f"Geometry not found: {result_id}")
            return
        before = self._geometry_visibility_state(result)
        visible = not getattr(result, "inliers_visible", True)
        self._set_geometry_visibility_field(result_id, "inliers_visible", visible)
        self._record_geometry_visibility_change(result_id, before)
        self._queue_geometries_window_refresh()

    def _on_geometry_header_hovered(self, result_id, hovered):
        if hovered and self._geometry_hover_events_blocked():
            return
        if hovered:
            self._set_hovered_geometry_result(result_id)
        elif result_id == getattr(self, "_hovered_geometry_id", None):
            self._clear_hovered_geometry()

    def _set_hovered_geometry_result(self, result_id):
        if result_id and not self._find_result(result_id):
            self._clear_hovered_geometry()
            return
        if result_id == getattr(self, "_hovered_geometry_id", None):
            return
        self._hovered_geometry_id = result_id
        if hasattr(self._viewport, "set_selected_result"):
            self._viewport.set_selected_result(result_id)

    def _focus_geometry_result(self, result_id):
        result = self._find_result(result_id)
        if not result:
            self._clear_hovered_geometry()
            self._set_status(f"Geometry not found: {result_id}")
            return
        focused = False
        if hasattr(self._viewport, "focus_result"):
            focused = bool(self._viewport.focus_result(result_id))
        self._sync_camera_models()
        self._queue_geometries_window_refresh()
        if focused:
            self._set_status(f"Focused geometry: {result_id}")
        else:
            self._set_status(f"Geometry has no viewport bounds: {result_id}")

    def _clear_hovered_geometry(self):
        self._hovered_geometry_id = None
        if hasattr(self._viewport, "set_selected_result"):
            self._viewport.set_selected_result(None)

    def _record_geometry_visibility_change(self, result_id, before):
        result = self._find_result(result_id)
        if not result:
            return
        after = self._geometry_visibility_state(result)
        self._record_state_change_command(
            TRANSACTION_GEOMETRY_VISIBILITY,
            before,
            after,
            result_id=result_id,
        )

    def _geometry_visibility_state(self, result):
        return {
            "mesh_visible": bool(getattr(result, "mesh_visible", True)),
            "inliers_visible": bool(getattr(result, "inliers_visible", True)),
        }

    def _all_geometry_visibility_state(self):
        if not self._state:
            return {"results": {}}
        return {
            "results": {
                result.id: self._geometry_visibility_state(result)
                for result in self._state.results
                if getattr(result, "id", None)
            }
        }

    def _set_geometry_visibility_field(self, result_id, field_name, visible):
        if field_name not in ("mesh_visible", "inliers_visible"):
            return
        keyword = "mesh_visible" if field_name == "mesh_visible" else "inliers_visible"
        kwargs = {keyword: bool(visible)}
        if hasattr(self._viewport, "set_result_visibility"):
            self._viewport.set_result_visibility(result_id, **kwargs)
        else:
            result = self._find_result(result_id)
            if not result:
                return
            setattr(result, field_name, bool(visible))
            self._sync_detection_surfaces()

    def _apply_geometry_visibility_state(self, result_id, state):
        if result_id is None and isinstance(state.get("results"), dict):
            changed = False
            for current_result_id, visibility_state in state.get("results", {}).items():
                if self._apply_geometry_visibility_state(current_result_id, visibility_state):
                    changed = True
            if changed:
                self._queue_geometries_window_refresh()
            return changed
        result = self._find_result(result_id)
        if not result:
            return False
        mesh_visible = state.get("mesh_visible", getattr(result, "mesh_visible", True))
        inliers_visible = state.get("inliers_visible", getattr(result, "inliers_visible", True))
        if hasattr(self._viewport, "set_result_visibility"):
            self._viewport.set_result_visibility(
                result_id,
                mesh_visible=mesh_visible,
                inliers_visible=inliers_visible,
            )
        else:
            setattr(result, "mesh_visible", bool(mesh_visible))
            setattr(result, "inliers_visible", bool(inliers_visible))
            self._sync_detection_surfaces()
        self._queue_geometries_window_refresh()
        return True

    def _request_delete_geometry_result(self, result_id):
        if not self._find_result(result_id):
            self._set_status(f"Geometry not found: {result_id}")
            return
        self._show_geometry_action_confirmation(
            result_id=result_id,
            action_label="Delete",
            title="Delete Geometry",
            detail="Delete this geometry entry. Its inlier points stay removed from the active point set.",
        )

    def _request_cancel_geometry_result(self, result_id):
        if not self._find_result(result_id):
            self._set_status(f"Geometry not found: {result_id}")
            return
        self._show_geometry_action_confirmation(
            result_id=result_id,
            action_label="Cancel Detection",
            title="Cancel Detection",
            detail="Cancel this detection and restore its inlier points to the active point set.",
        )

    def _show_geometry_action_confirmation(self, result_id, action_label, title, detail):
        if self._geometry_action_dialog:
            self._defer_window_destroy(self._geometry_action_dialog)
            self._geometry_action_dialog = None
        self._geometry_action_dialog = ui.Window(title, width=500, height=180)
        with self._geometry_action_dialog.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=8)
                ui.Label(f"{action_label} {result_id}?", word_wrap=True)
                ui.Label(detail, word_wrap=True)
                ui.Spacer(height=8)
                with ui.HStack(height=32, spacing=8):
                    ui.Spacer()
                    ui.Button(
                        action_label,
                        width=140,
                        clicked_fn=lambda action=action_label, value=result_id: self._confirm_geometry_action(action, value),
                    )
                    ui.Button("Keep Geometry", width=130, clicked_fn=self._cancel_geometry_action)
                    ui.Spacer(width=8)
        self._set_status(f"{action_label} needs confirmation: {result_id}")

    def _confirm_geometry_action(self, action_label, result_id):
        self._close_geometry_action_dialog()
        if action_label == "Delete":
            self._delete_geometry_result(result_id)
        else:
            self._cancel_geometry_result(result_id)

    def _cancel_geometry_action(self):
        self._close_geometry_action_dialog()
        self._set_status("Geometry action canceled.")

    def _close_geometry_action_dialog(self):
        if self._geometry_action_dialog:
            self._defer_window_destroy(self._geometry_action_dialog)
            self._geometry_action_dialog = None

    def _delete_geometry_result(self, result_id):
        if not self._state:
            return
        result = self._run_state_command(lambda: self._state.remove_result(result_id, restore_inliers=False))
        if not result:
            self._set_status(f"Geometry not found: {result_id}")
            return
        self._after_geometry_result_changed()
        self._set_status(f"Deleted geometry: {result_id}")

    def _cancel_geometry_result(self, result_id):
        if not self._state:
            return
        result = self._run_state_command(lambda: self._state.remove_result(result_id, restore_inliers=True))
        if not result:
            self._set_status(f"Geometry not found: {result_id}")
            return
        self._after_geometry_result_changed()
        self._set_status(f"Canceled detection: {result_id}")

    def _after_geometry_result_changed(self):
        self._hover_index = None
        self._selected_index = None
        if self._hovered_geometry_id and not self._find_result(self._hovered_geometry_id):
            self._clear_hovered_geometry()
        self._set_retroactive_pick_index(None)
        self._clear_auto_detect_preview()
        self._sync_detection_surfaces()
        self._viewport.set_active_mask(self._state.active_mask)
        self._viewport.set_pick_markers(None, None)
        self._refresh_detection_panel()
        self._refresh_toolbar_state()
        self._queue_geometries_window_refresh()

    def _find_result(self, result_id):
        if not self._state:
            return None
        for result in self._state.results:
            if result.id == result_id:
                return result
        return None

    def _sync_detection_surfaces(self):
        if not self._state:
            self._hovered_geometry_id = None
            self._viewport.clear_surfaces()
            return
        surfaces = list(self._state.results)
        if self._is_displayable_auto_detect_result(self._auto_detect_result):
            surfaces.append(self._auto_detect_result)
        self._viewport.set_surfaces(surfaces)

    def _is_displayable_auto_detect_result(self, result):
        if self._is_detection_paused():
            return False
        if not self._state or result is None:
            return False
        if getattr(result, "active_generation", None) != self._state.generation:
            return False
        if not getattr(result, "inlier_indices", None):
            return False
        seed_index = getattr(result, "seed_index", None)
        if not self._is_active_index(seed_index):
            return False
        if self._auto_detect_source == "selected":
            return self._auto_detect_result_matches_current_seed(result) or self._is_sticky_auto_preview_enabled()
        if self._auto_detect_source == "hover":
            if not self._is_auto_detect_enabled():
                return False
            return self._auto_detect_result_matches_current_seed(result) or self._is_sticky_auto_preview_enabled()
        return False

    def _is_active_index(self, index):
        return bool(self._state and 0 <= index < self._state.point_count and self._state.active_mask[index])

    def _detection_result_status(self, prefix, result):
        return f"{prefix} {result.id}"

    def _detection_failure_status(self, prefix, error):
        text = str(error or "")
        rms = self._extract_rms_error(text)
        category = self._detection_failure_category(error, text)
        details = []
        if category:
            details.append(category)
        details.append(f"rms={self._format_metric(rms)}")
        if text:
            details.append(text)
        return f"{prefix}: {', '.join(details)}"

    def _detection_failure_category(self, error, text):
        if isinstance(error, ValueError) and "seed" in text.lower():
            return "invalid seed"
        if "supports up to" in text or "point limit" in text.lower():
            return "unsupported point count"
        if "did not return a valid result" in text or "returned no inlier" in text:
            return "runtime detection failure"
        if text:
            return "native detection failed"
        return "native detection failed"

    def _refresh_viewport_overlays(self):
        viewport = getattr(self, "_viewport", None)
        if not viewport:
            return
        data_setter = getattr(viewport, "set_data_overlay", None)
        if callable(data_setter):
            data_setter(**self._viewport_data_overlay())
        detection_setter = getattr(viewport, "set_hover_detection_overlay", None)
        if callable(detection_setter):
            detection_setter(**self._viewport_hover_detection_overlay())

    def _viewport_data_overlay(self):
        state = getattr(self, "_state", None)
        if state:
            active_count = state.active_count
            point_count = state.point_count
            removed_count = state.removed_count
        else:
            active_count = point_count = removed_count = 0
        return {
            "dataset_name": getattr(self, "_dataset_name", None),
            "active_count": active_count,
            "point_count": point_count,
            "removed_count": removed_count,
            "hover_index": self._overlay_active_index(getattr(self, "_hover_index", None)),
            "selected_index": self._overlay_active_index(getattr(self, "_selected_index", None)),
        }

    def _overlay_active_index(self, index):
        if index is None:
            return None
        return index if self._is_active_index(index) else None

    def _viewport_hover_detection_overlay(self):
        result = getattr(self, "_auto_detect_result", None)
        if getattr(self, "_auto_detect_overlay_suppressed", False):
            return {"visible": False}
        if getattr(self, "_auto_detect_source", None) not in ("hover", "selected"):
            return {"visible": False}
        if not self._is_displayable_auto_detect_result(result):
            return {"visible": False}
        return {
            "visible": True,
            "result_type": getattr(result, "type", None),
            "rows": self._hover_detection_overlay_rows(result),
            "histogram": self._geometry_distance_histogram(result),
            "icon_path": self._detection_type_icon_path(getattr(result, "type", None)),
        }

    def _hover_detection_overlay_rows(self, result):
        rows = []
        seed_index = self._format_seed_index(getattr(result, "seed_index", None))
        if seed_index is not None:
            rows.append(("Seed Index", seed_index))
        rows.extend([
            ("Inliers", f"{len(getattr(result, 'inlier_indices', []) or []):,} pts"),
            ("RMS", self._format_scientific_metric(getattr(result, "rms_error", None))),
            ("Pos", self._format_vector(self._geometry_position(result))),
        ])
        orientation_summary = self._surface_orientation_summary(result)
        if orientation_summary:
            rows.append(orientation_summary)
        size_summary = self._surface_size_summary(result)
        if size_summary:
            rows.append(("Size", size_summary))
        return rows

    def _detection_type_icon_path(self, detection_type):
        if detection_type not in DETECTION_TYPES:
            return None
        return self._toolbar_icon_path(f"detect_{str(detection_type).lower()}.svg")

    def _surface_orientation_summary(self, result):
        params = getattr(result, "parameters", None) or {}
        result_type = getattr(result, "type", "")
        if result_type == "Plane":
            normal = params.get("normal", params.get("z_axis"))
            if normal is not None:
                return ("Normal", self._format_vector(normal))
        if result_type in ("Cylinder", "Cone", "Torus"):
            axis = self._geometry_axis(result)
            if axis is not None:
                return ("Axis", self._format_vector(axis))
        return None

    def _surface_size_summary(self, result):
        params = getattr(result, "parameters", None) or {}
        result_type = getattr(result, "type", "")
        if result_type == "Plane":
            return self._size_fields(params, ("width", "height"))
        if result_type == "Sphere":
            return self._size_fields(params, ("radius",))
        if result_type == "Cylinder":
            return self._size_fields(params, ("radius", "height"))
        if result_type == "Cone":
            return self._size_fields(params, ("bottom_radius", "top_radius", "height"))
        if result_type == "Torus":
            return self._size_fields(params, ("major_radius", "tube_radius", "sweep_angle"))
        return ""

    def _size_fields(self, params, names):
        labels = {
            "width": "w",
            "height": "h",
            "radius": "r",
            "bottom_radius": "r0",
            "top_radius": "r1",
            "major_radius": "R",
            "tube_radius": "r",
            "sweep_angle": "sweep",
        }
        fields = []
        for name in names:
            if name in params:
                fields.append(f"{labels.get(name, name)}={self._format_metric(params[name])}")
        return " ".join(fields)

    def _format_metric(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "n/a"
        if abs(value) >= 1000.0 or (0.0 < abs(value) < 0.001):
            return f"{value:.3e}"
        return f"{value:.4g}"

    def _format_scientific_metric(self, value):
        try:
            return f"{float(value):.1e}"
        except (TypeError, ValueError):
            return "n/a"

    def _extract_rms_error(self, text):
        marker = "rms_error="
        if marker not in text:
            return None
        value = text.split(marker, 1)[1].split()[0].rstrip(".,;)")
        try:
            return float(value)
        except ValueError:
            return None

    def _refresh_detection_panel(self):
        if self._active_count_label:
            if self._state:
                self._active_count_label.text = f"{self._state.active_count:,} active / {self._state.removed_count:,} removed"
            else:
                self._active_count_label.text = "0 active / 0 removed"
        if self._hover_index_label:
            self._hover_index_label.text = f"Hover: {self._hover_index}" if self._hover_index is not None else "Hover: none"
        if self._selected_index_label:
            self._selected_index_label.text = (
                f"Selected: {self._selected_index}" if self._selected_index is not None else "Selected: none"
            )
        if self._result_label:
            if self._state and self._state.results:
                self._result_label.text = "Results:\n" + "\n".join(
                    f"{result.id}: {result.type}, inliers={len(result.inlier_indices)}, rms={result.rms_error:.4f}"
                    for result in self._state.results
                )
            else:
                self._result_label.text = "Results: none"
        can_capture = self._can_capture_selected_preview()
        for button in (self._capture_button, getattr(self, "_toolbar_capture_button", None)):
            if button:
                button.enabled = can_capture
        can_undo = bool(self._state and self._state.can_undo)
        can_redo = bool(self._state and self._state.can_redo)
        for button in (getattr(self, "_undo_button", None), getattr(self, "_toolbar_undo_button", None)):
            if button:
                button.enabled = can_undo
        if getattr(self, "_redo_button", None):
            self._redo_button.enabled = can_redo
        self._refresh_viewport_overlays()

    def _refresh_geometries_window(self):
        frame = self._geometries_window_frame()
        if not frame:
            return
        try:
            if hasattr(frame, "clear"):
                frame.clear()
            with frame:
                self._build_geometries_window()
            self._restore_geometries_scroll_position()
        except Exception as exc:
            carb.log_warn(f"Failed to refresh Geometries window: {exc}")

    def _queue_geometries_window_refresh(self):
        if getattr(self, "_app_shutting_down", False):
            return
        if not self._geometries_window_frame():
            return
        self._capture_geometries_scroll_position()
        task = getattr(self, "_geometry_refresh_task", None)
        if task and not task.done():
            return
        self._geometry_refresh_task = asyncio.ensure_future(_refresh_geometries_window_after_update(weakref.ref(self)))

    def _geometries_window_frame(self):
        windows = getattr(self, "_windows", {})
        window = windows.get(self.WINDOW_GEOMETRIES) if windows else None
        return getattr(window, "frame", None) if window else None

    def _capture_geometries_scroll_position(self):
        scrolling_frame = getattr(self, "_geometries_scrolling_frame", None)
        value = self._read_scroll_position(scrolling_frame)
        if value is not None:
            self._geometries_scroll_y = value

    def _update_geometries_scroll_interaction(self):
        value = self._read_scroll_position(getattr(self, "_geometries_scrolling_frame", None))
        if value is None:
            self._geometries_last_scroll_y = None
            return
        previous = getattr(self, "_geometries_last_scroll_y", None)
        self._geometries_last_scroll_y = value
        if previous is not None and abs(value - previous) > 0.25:
            self._note_geometries_scroll_interaction()

    def _note_geometries_scroll_interaction(self, duration=0.18):
        self._geometries_scroll_interaction_until = max(
            getattr(self, "_geometries_scroll_interaction_until", 0.0),
            time.monotonic() + float(duration),
        )

    def _geometry_hover_events_blocked(self):
        return False

    def _on_geometries_scroll_pressed(self, *args):
        self._geometries_scroll_drag_active = True
        self._note_geometries_scroll_interaction(duration=0.5)
        self._clear_geometries_hover_state()

    def _on_geometries_scroll_moved(self, *args):
        if getattr(self, "_geometries_scroll_drag_active", False):
            self._note_geometries_scroll_interaction(duration=0.5)

    def _on_geometries_scroll_released(self, *args):
        self._geometries_scroll_drag_active = False
        self._note_geometries_scroll_interaction(duration=0.12)
        self._queue_geometries_window_refresh()

    def _clear_geometries_hover_state(self):
        if getattr(self, "_hovered_geometry_id", None) is not None:
            self._clear_hovered_geometry()
        self._clear_histogram_hover_state()
        self._set_histogram_status_text(None, "")

    def _restore_geometries_scroll_position(self):
        scrolling_frame = getattr(self, "_geometries_scrolling_frame", None)
        value = getattr(self, "_geometries_scroll_y", None)
        if scrolling_frame is not None and value is not None:
            self._write_scroll_position(scrolling_frame, value)

    def _read_scroll_position(self, scrolling_frame):
        if scrolling_frame is None:
            return None
        for name in ("scroll_y", "scroll_offset_y", "scroll_y_offset"):
            try:
                value = getattr(scrolling_frame, name)
            except Exception:
                continue
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if hasattr(value, "as_float"):
                value = value.as_float
            try:
                return float(value)
            except Exception:
                continue
        return None

    def _write_scroll_position(self, scrolling_frame, value):
        for name in ("scroll_y", "scroll_offset_y", "scroll_y_offset"):
            try:
                current = getattr(scrolling_frame, name)
            except Exception:
                continue
            try:
                if hasattr(current, "set_value"):
                    current.set_value(float(value))
                else:
                    setattr(scrolling_frame, name, float(value))
                return True
            except Exception:
                continue
        return False

    def _refresh_transactions_window(self):
        if getattr(self, "_app_shutting_down", False):
            return
        frame = self._transactions_window_frame()
        if not frame:
            return
        try:
            if hasattr(frame, "clear"):
                frame.clear()
            with frame:
                self._build_transactions_window()
        except Exception as exc:
            carb.log_warn(f"Failed to refresh Transactions window: {exc}")

    def _queue_transactions_window_refresh(self):
        if getattr(self, "_app_shutting_down", False):
            return
        if not self._transactions_window_frame():
            return
        task = getattr(self, "_transactions_refresh_task", None)
        if task and not task.done():
            return
        self._transactions_refresh_task = asyncio.ensure_future(
            _refresh_transactions_window_after_update(weakref.ref(self))
        )

    def _transactions_window_frame(self):
        windows = getattr(self, "_windows", {})
        window = windows.get(self.WINDOW_TRANSACTIONS) if windows else None
        return getattr(window, "frame", None) if window else None

    def _geometry_result_fields(self, result):
        params = getattr(result, "parameters", {}) or {}
        fields = [
            self._geometry_scalar_field("Name", result.id),
            self._geometry_scalar_field("Type", result.type),
        ]
        seed_index = self._format_seed_index(getattr(result, "seed_index", None))
        if seed_index is not None:
            fields.append(self._geometry_scalar_field("Seed Index", seed_index))
        fields.extend([
            self._geometry_scalar_field("RMS error", self._format_scientific_metric(getattr(result, "rms_error", None))),
            self._geometry_vector_field("Position", self._geometry_position(result)),
        ])
        axis = self._geometry_axis(result)
        if axis is not None and result.type != "Plane":
            fields.append(self._geometry_vector_field("Axis", axis))
        normal = params.get("normal", params.get("z_axis"))
        if result.type == "Plane" and normal is not None:
            fields.append(self._geometry_vector_field("Normal", normal))
        for label, key in self._geometry_metric_fields(result.type):
            if key in params:
                fields.append(self._geometry_scalar_field(label, self._format_geometry_metric(key, params[key])))
        fields.append(self._geometry_scalar_field("Inlier point count", f"{len(getattr(result, 'inlier_indices', []) or []):,}"))
        return fields

    def _geometry_scalar_field(self, label, value):
        return {
            "kind": "scalar",
            "label": str(label),
            "value": str(value),
        }

    def _geometry_vector_field(self, label, value):
        return {
            "kind": "vector3",
            "label": str(label),
            "components": self._format_vector_components(value),
        }

    def _geometry_field_label(self, field):
        if isinstance(field, dict):
            return str(field.get("label", ""))
        try:
            return str(field[0])
        except Exception:
            return ""

    def _geometry_field_kind(self, field):
        if isinstance(field, dict):
            return str(field.get("kind", "scalar"))
        return "scalar"

    def _geometry_field_value_text(self, field):
        if isinstance(field, dict):
            if self._geometry_field_kind(field) == "vector3":
                return "(" + ", ".join(self._geometry_field_components(field)) + ")"
            return str(field.get("value", ""))
        try:
            return str(field[1])
        except Exception:
            return ""

    def _geometry_field_components(self, field):
        if isinstance(field, dict):
            components = field.get("components")
            if components is not None:
                formatted_components = [str(component) for component in list(components)[:3]]
                while len(formatted_components) < 3:
                    formatted_components.append("n/a")
                return tuple(formatted_components)
            return self._format_vector_components(field.get("value"))
        try:
            return self._format_vector_components(field[1])
        except Exception:
            return ("n/a", "n/a", "n/a")

    def _format_seed_index(self, seed_index):
        try:
            seed_index = int(seed_index)
        except (TypeError, ValueError):
            return None
        if seed_index < 0:
            return None
        return str(seed_index)

    def _geometry_metric_fields(self, result_type):
        if result_type == "Plane":
            return (("Width", "width"), ("Height", "height"))
        if result_type == "Sphere":
            return (("Radius", "radius"),)
        if result_type == "Cylinder":
            return (("Radius", "radius"), ("Length", "height"))
        if result_type == "Cone":
            return (
                ("Top radius", "top_radius"),
                ("Bottom radius", "bottom_radius"),
                ("Length", "height"),
                ("Vertex angle", "vertex_angle"),
            )
        if result_type == "Torus":
            return (
                ("Mean radius", "major_radius"),
                ("Tube radius", "tube_radius"),
                ("Sweep angle", "sweep_angle"),
            )
        return ()

    def _geometry_position(self, result):
        params = getattr(result, "parameters", {}) or {}
        for key in ("center", "origin", "position"):
            if key in params:
                return params[key]
        start = params.get("bottom", params.get("start"))
        end = params.get("top", params.get("end"))
        if start is not None and end is not None:
            return [(float(start[index]) + float(end[index])) * 0.5 for index in range(3)]
        return getattr(result, "seed_position", None)

    def _geometry_axis(self, result):
        params = getattr(result, "parameters", {}) or {}
        if "axis" in params:
            return params["axis"]
        if "z_axis" in params:
            return params["z_axis"]
        start = params.get("bottom", params.get("start"))
        end = params.get("top", params.get("end"))
        if start is not None and end is not None:
            return [float(end[index]) - float(start[index]) for index in range(3)]
        return None

    def _format_vector(self, value):
        if value is None:
            return "n/a"
        try:
            return "(" + ", ".join(self._format_metric(value[index]) for index in range(3)) + ")"
        except Exception:
            return "n/a"

    def _format_vector_components(self, value):
        if value is None:
            return ("n/a", "n/a", "n/a")
        try:
            return tuple(self._format_metric(value[index]) for index in range(3))
        except Exception:
            return ("n/a", "n/a", "n/a")

    def _format_direction_vector(self, value):
        return self._format_vector(value)

    def _format_geometry_metric(self, key, value):
        if key in self.LENGTH_PARAMETER_KEYS:
            return self._format_length_metric(value)
        return self._format_metric(value)

    def _format_length_metric(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "n/a"
        return f"{value:.3f}"

    def _on_camera_settings_changed(self, changed=None):
        if self._syncing_models:
            return
        def apply_change():
            camera = self._viewport.camera
            camera.center = [
                self._models["center_x"].as_float,
                self._models["center_y"].as_float,
                self._models["center_z"].as_float,
            ]
            camera.zoom = max(0.001, self._models["zoom"].as_float)
            camera.set_fov_degrees(self._models["fov"].as_float)
            position = [
                self._models["position_x"].as_float,
                self._models["position_y"].as_float,
                self._models["position_z"].as_float,
            ]
            direction = [
                self._models["direction_x"].as_float,
                self._models["direction_y"].as_float,
                self._models["direction_z"].as_float,
            ]
            up = [
                self._models["up_x"].as_float,
                self._models["up_y"].as_float,
                self._models["up_z"].as_float,
            ]
            if changed and changed.startswith("position_"):
                camera.set_position(position)
            elif changed and (changed.startswith("direction_") or changed.startswith("up_")):
                camera.set_direction_up(direction, up)
            self._viewport.draw()

        self._commit_camera_change(apply_change)

    def _set_projection_mode(self, mode):
        self._commit_camera_change(lambda: self._viewport.set_projection_mode(mode))
        self._refresh_toolbar_state()

    def _set_camera_preset(self, preset):
        def apply_change():
            if self._viewport.point_cloud:
                point_cloud = self._viewport.point_cloud
                self._viewport.camera.fit(point_cloud.bounds_min, point_cloud.bounds_max)
            presets = {
                "top": ([0.0, -1.0, 0.0], [0.0, 0.0, -1.0]),
                "front": ([0.0, 0.0, -1.0], [0.0, 1.0, 0.0]),
                "side": ([-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
            }
            direction, up = presets.get(preset, presets["front"])
            self._viewport.camera.set_direction_up(direction, up)
            self._viewport.draw()

        self._commit_camera_change(apply_change)
        self._set_status(f"Camera preset: {preset.capitalize()}")

    def _rotate_camera_step(self, axis, degrees):
        viewport = getattr(self, "_viewport", None)
        camera = getattr(viewport, "camera", None)
        if camera is None:
            return False
        rotation_axis = camera.up if axis == "horizontal" else camera.right
        applied_degrees = -degrees if axis == "horizontal" else degrees
        if not hasattr(camera, "rotate_orientation_degrees"):
            return False

        def apply_change():
            camera.rotate_orientation_degrees(rotation_axis, applied_degrees)
            if hasattr(viewport, "draw"):
                viewport.draw()

        self._commit_camera_change(apply_change)
        self._set_status(f"Camera {axis} rotation: {degrees:g} deg")
        return True

    def _fit_camera(self):
        if self._viewport.point_cloud:
            def apply_change():
                point_cloud = self._viewport.point_cloud
                self._viewport.camera.fit(point_cloud.bounds_min, point_cloud.bounds_max)
                self._viewport.draw()

            self._commit_camera_change(apply_change)

    def _sync_camera_models(self):
        if "center_x" not in self._models:
            self._apply_dirty_scope("display_camera")
            return
        camera = self._viewport.camera
        position = self._viewport._view_position()
        direction = camera.forward
        up = camera.up
        projection_label = getattr(self, "_projection_label", None)
        if projection_label:
            projection_label.text = "Mode: Perspective" if camera.projection_mode == PROJECTION_PERSPECTIVE else "Mode: Orthographic"
        self._refresh_toolbar_state()
        values = {
            "center_x": camera.center[0],
            "center_y": camera.center[1],
            "center_z": camera.center[2],
            "position_x": position[0],
            "position_y": position[1],
            "position_z": position[2],
            "direction_x": direction[0],
            "direction_y": direction[1],
            "direction_z": direction[2],
            "up_x": up[0],
            "up_y": up[1],
            "up_z": up[2],
            "zoom": camera.zoom,
            "fov": camera.fov_degrees,
        }
        self._syncing_models = True
        try:
            for name, value in values.items():
                self._models[name].set_value(float(value))
        finally:
            self._syncing_models = False
        self._apply_dirty_scope("display_camera")

    def _set_status(self, text):
        self._status_message = text
        self._refresh_status_bar()

    def _refresh_status_bar(self):
        if self._dirty_label:
            self._dirty_label.text = ""
        if self._status_label:
            self._status_label.text = self._status_bar_text()

    def _status_bar_text(self):
        return str(self._status_message or "")

    def _set_dataset(self, text):
        self._dataset_name = text
        self._refresh_dirty_indicator()
        self._refresh_viewport_overlays()

    def _refresh_dirty_indicator(self):
        suffix = " *" if self._is_dirty else ""
        if self._dataset_label:
            self._dataset_label.text = f"{self._dataset_name}{suffix}"
        self._refresh_status_bar()
        self._refresh_toolbar_state()
        self._refresh_window_title()

    def _refresh_window_title(self):
        title = self._window_title_text()
        self._set_app_window_title(title)

    def _window_title_text(self):
        document_name = self._title_document_name()
        if not document_name:
            return APP_WINDOW_TITLE
        dirty_suffix = "*" if self._is_dirty else ""
        return f"{APP_WINDOW_TITLE}: {document_name}{dirty_suffix}"

    def _title_document_name(self):
        if self._workspace_path:
            return ntpath.basename(os.path.basename(self._workspace_path))
        if self._dataset_name and self._dataset_name != "None":
            return self._dataset_name
        return None

    def _set_app_window_title(self, title):
        try:
            import omni.appwindow
        except Exception:
            return
        try:
            app_window = omni.appwindow.get_default_app_window()
        except Exception:
            return
        if not app_window:
            return
        if self._set_native_window_title(app_window, title):
            return
        for method_name in ("set_title", "set_window_title"):
            method = getattr(app_window, method_name, None)
            if callable(method):
                try:
                    method(title)
                    return
                except Exception:
                    pass
        self._assign_window_title(app_window, title)

    def _set_native_window_title(self, app_window, title):
        try:
            import importlib

            windowing_module = importlib.import_module("carb.windowing")
        except Exception:
            return False
        window = self._native_window_from_app_window(app_window)
        if not window:
            return False
        try:
            windowing = windowing_module.acquire_windowing_interface()
        except Exception:
            return False
        if not windowing:
            return False
        try:
            windowing.set_window_title(window, title)
            return True
        except Exception:
            return False

    def _native_window_from_app_window(self, app_window):
        for method_name in ("get_window", "getWindow"):
            method = getattr(app_window, method_name, None)
            if callable(method):
                try:
                    window = method()
                except Exception:
                    window = None
                if window:
                    return window
        for attribute in ("window", "_window"):
            try:
                window = getattr(app_window, attribute)
            except Exception:
                window = None
            if window:
                return window
        return None

    def _assign_window_title(self, window, title):
        for attribute in ("title", "window_title"):
            try:
                setattr(window, attribute, title)
                return True
            except Exception:
                pass
        return False

    def _set_point_count(self, count):
        if self._point_count_label:
            self._point_count_label.text = f"{count:,} points"
        self._refresh_viewport_overlays()

    def _on_window_visibility_changed(self, title, visible):
        if getattr(self, "_app_shutting_down", False):
            return
        windows = getattr(self, "_windows", None)
        if not windows or title not in windows:
            return
        self._sync_window_menu_item(title, visible)
        if title == self.WINDOW_TUTORIAL:
            self._refresh_toolbar_state()

    def _capture_window_layout_state(self, title=None):
        titles = (title,) if title else tuple(getattr(self, "_windows", {}).keys())
        captured = False
        for window_title in titles:
            if window_title in getattr(self, "_pending_layout_restore_titles", set()):
                continue
            window = self._windows.get(window_title)
            if not window or not bool(getattr(window, "visible", False)):
                continue
            try:
                state = {
                    "docked": bool(getattr(window, "docked", False)),
                    "dock_id": getattr(window, "dock_id", None),
                    "dock_order": getattr(window, "dock_order", None),
                    "position_x": getattr(window, "position_x", None),
                    "position_y": getattr(window, "position_y", None),
                    "width": getattr(window, "width", None),
                    "height": getattr(window, "height", None),
                }
            except Exception:
                continue
            self._window_layout_state[window_title] = state
            captured = True
        return captured

    def _restore_window_layout_state(self, title):
        window = self._windows.get(title)
        state = self._window_layout_state.get(title)
        if not window or not state:
            return False
        restored = False
        try:
            was_docked = bool(state.get("docked"))
            is_docked = bool(getattr(window, "docked", False))
            if was_docked and is_docked and state.get("dock_order") is not None:
                window.dock_order = self._dock_order_to_restore(window, state.get("dock_order"))
                restored = True
            elif not was_docked and is_docked:
                undock = getattr(window, "undock", None)
                if callable(undock):
                    undock()
                    restored = True
        except Exception as exc:
            carb.log_warn(f"FindSurface window layout restore failed for {title}: {exc}")

        if not bool(state.get("docked")) or not bool(getattr(window, "docked", False)):
            for attr_name in ("position_x", "position_y", "width", "height"):
                value = state.get(attr_name)
                if value is None:
                    continue
                try:
                    setattr(window, attr_name, value)
                    restored = True
                except Exception:
                    pass
        return restored

    def _dock_order_to_restore(self, window, saved_order):
        try:
            order = int(saved_order)
        except Exception:
            return saved_order
        order = max(0, order)
        workspace = getattr(ui, "Workspace", None)
        get_docked_windows = getattr(workspace, "get_docked_windows", None)
        if not callable(get_docked_windows):
            return order
        try:
            dock_id = getattr(window, "dock_id", None)
            docked_windows = get_docked_windows(dock_id) if dock_id is not None else None
        except Exception:
            docked_windows = None
        try:
            docked_count = len(docked_windows)
        except Exception:
            docked_count = 0
        if docked_count <= 0:
            return order
        return min(order, docked_count - 1)

    def _queue_window_layout_restore(self, title):
        if getattr(self, "_app_shutting_down", False) or title not in self._windows:
            return False
        try:
            self._layout_restore_tasks = [
                task for task in getattr(self, "_layout_restore_tasks", []) if not task.done()
            ]
            self._pending_layout_restore_titles.add(title)
            task = asyncio.ensure_future(_restore_window_layout_after_update(weakref.ref(self), title))
            self._layout_restore_tasks.append(task)
            return True
        except Exception:
            return False

    def _sync_window_menu_item(self, title, visible):
        for item in self._menu_items.get("Window", []):
            if getattr(item, "name", None) == title:
                try:
                    item.ticked = bool(visible)
                except Exception:
                    pass
                break
        self._refresh_menu_items("Window")

    def _refresh_menu_items(self, menu_name):
        menu_utils = omni.kit.menu.utils
        for method_name in ("refresh_menu_items", "refresh_menu", "rebuild_menus", "rebuild_menu"):
            method = getattr(menu_utils, method_name, None)
            if not callable(method):
                continue
            try:
                method(menu_name)
            except TypeError:
                try:
                    method()
                except Exception:
                    continue
            except Exception:
                continue
            return

    def _toggle_window(self, title):
        window = self._windows.get(title)
        if window:
            visible = not window.visible
            if not visible:
                self._capture_window_layout_state(title)
            window.visible = visible
            self._sync_window_menu_item(title, visible)
            if visible:
                self._restore_window_layout_state(title)
                self._queue_window_layout_restore(title)
                self._focus_window(window)
        if title == self.WINDOW_TUTORIAL:
            self._refresh_toolbar_state()

    def _show_tutorial_overlay(self):
        self._show_window(self.WINDOW_TUTORIAL, True)

    def _toggle_global_visibility(self, target):
        before = self._global_visibility_state()
        if target == "outliers":
            value = not getattr(self._viewport, "outlier_points_visible", True)
            self._viewport.set_global_visibility(outlier_points=value)
        elif target == "meshes":
            value = not getattr(self._viewport, "surface_meshes_visible", True)
            self._viewport.set_global_visibility(surface_meshes=value)
        elif target == "inliers":
            value = not getattr(self._viewport, "inlier_points_visible", True)
            self._viewport.set_global_visibility(inlier_points=value)
        else:
            return
        self._record_global_visibility_change(before)

    def _global_visibility_state(self):
        viewport = getattr(self, "_viewport", None)
        return {
            "outlier_points_visible": bool(getattr(viewport, "outlier_points_visible", True)),
            "surface_meshes_visible": bool(getattr(viewport, "surface_meshes_visible", True)),
            "inlier_points_visible": bool(getattr(viewport, "inlier_points_visible", True)),
        }

    def _record_global_visibility_change(self, before):
        if not self._state:
            return
        after = self._global_visibility_state()
        self._record_state_change_command(TRANSACTION_GLOBAL_VISIBILITY, before, after)

    def _apply_global_visibility_state(self, state):
        if hasattr(self._viewport, "set_global_visibility"):
            self._viewport.set_global_visibility(
                outlier_points=state.get("outlier_points_visible", getattr(self._viewport, "outlier_points_visible", True)),
                surface_meshes=state.get("surface_meshes_visible", getattr(self._viewport, "surface_meshes_visible", True)),
                inlier_points=state.get("inlier_points_visible", getattr(self._viewport, "inlier_points_visible", True)),
            )
        self._refresh_toolbar_state()

    def _refresh_toolbar_state(self):
        if getattr(self, "_save_button", None):
            self._save_button.enabled = bool(self._is_dirty and self._state)
        if getattr(self, "_export_button", None):
            self._export_button.enabled = bool(self._state and self._state.results)
        can_undo = bool(self._state and self._state.can_undo)
        can_redo = bool(self._state and self._state.can_redo)
        for button in (getattr(self, "_undo_button", None), getattr(self, "_toolbar_undo_button", None)):
            if button:
                button.enabled = can_undo
        if getattr(self, "_redo_button", None):
            self._redo_button.enabled = can_redo
        if getattr(self, "_tutorial_button", None):
            self._tutorial_button.enabled = not self._is_window_visible(self.WINDOW_TUTORIAL)
        camera = getattr(getattr(self, "_viewport", None), "camera", None)
        projection = getattr(camera, "projection_mode", PROJECTION_ORTHOGRAPHIC)
        for mode, button in getattr(self, "_toolbar_projection_buttons", {}).items():
            self._set_button_selected(button, mode == projection)
        if getattr(self, "_toolbar_inspect_button", None):
            self._set_button_selected(self._toolbar_inspect_button, self._is_detection_paused())
        for detection_type, button in getattr(self, "_toolbar_detection_buttons", {}).items():
            self._set_button_selected(button, not self._is_detection_paused() and detection_type == self._detection_type)
        viewport = getattr(self, "_viewport", None)
        visibility = {
            "outliers": getattr(viewport, "outlier_points_visible", True),
            "meshes": getattr(viewport, "surface_meshes_visible", True),
            "inliers": getattr(viewport, "inlier_points_visible", True),
        }
        for name, visible in visibility.items():
            button = getattr(self, "_visibility_buttons", {}).get(name)
            if button:
                self._set_button_image(button, self._visibility_icon_path(name, visible))
                self._set_button_selected(button, False)

    def _visibility_icon_path(self, name, visible):
        icon_names = {
            "outliers": "visibility_outliers",
            "meshes": "visibility_mesh",
            "inliers": "visibility_inliers",
        }
        state = "on" if visible else "off"
        return self._toolbar_icon_path(f"{icon_names[name]}_{state}.svg")

    def _set_button_text(self, button, text):
        try:
            button.text = text
        except Exception:
            pass

    def _set_button_selected(self, button, selected):
        for attr in ("selected", "checked"):
            try:
                setattr(button, attr, bool(selected))
            except Exception:
                pass

    def _set_button_image(self, button, image_url):
        try:
            button.image_url = image_url
            if hasattr(button, "has_image") and not button.has_image:
                button.set_text(self._diagnostic_toolbar_label(os.path.basename(image_url)))
        except Exception:
            pass

    def _set_widget_enabled(self, widget, enabled):
        try:
            widget.enabled = bool(enabled)
        except Exception:
            pass

    def _show_window(self, title, visible):
        window = self._windows.get(title)
        if window:
            if not visible:
                self._capture_window_layout_state(title)
            window.visible = visible
            self._sync_window_menu_item(title, visible)
            if visible:
                self._restore_window_layout_state(title)
                self._queue_window_layout_restore(title)
                self._focus_window(window)
        if title == self.WINDOW_TUTORIAL:
            self._refresh_toolbar_state()

    def _is_window_visible(self, title):
        window = self._windows.get(title)
        return bool(window and window.visible)
