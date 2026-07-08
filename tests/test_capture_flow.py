import importlib.util
import gc
import math
import os
import sys
import types
import unittest
import weakref
from tempfile import TemporaryDirectory
from pathlib import Path
from threading import Lock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.findsurface.bootstrap"
APP_ROOT = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
)


def install_omni_stubs():
    carb = types.ModuleType("carb")
    carb_input = types.ModuleType("carb.input")
    carb_input.KEYBOARD_MODIFIER_FLAG_CONTROL = 1
    carb_input.KEYBOARD_MODIFIER_FLAG_SHIFT = 2
    carb_input.KEYBOARD_MODIFIER_FLAG_ALT = 4
    carb.log_error = lambda message: None
    carb.log_warn = lambda message: None
    carb.log_info = lambda message: None
    carb.input = carb_input
    sys.modules.setdefault("carb", carb)
    sys.modules.setdefault("carb.input", carb_input)

    omni = types.ModuleType("omni")
    ext = types.ModuleType("omni.ext")
    ext.IExt = object
    kit = types.ModuleType("omni.kit")
    actions = types.ModuleType("omni.kit.actions")
    actions_core = types.ModuleType("omni.kit.actions.core")
    actions_core.get_action_registry = lambda: types.SimpleNamespace(
        register_action=lambda *args, **kwargs: None,
        deregister_action=lambda *args, **kwargs: None,
    )
    app = types.ModuleType("omni.kit.app")
    app.get_app = lambda: types.SimpleNamespace()
    app.GLOBAL_EVENT_POST_QUIT = "omni.kit.app:post_quit"
    app.GLOBAL_EVENT_PRE_SHUTDOWN = "omni.kit.app:pre_shutdown"
    menu = types.ModuleType("omni.kit.menu")
    menu_utils = types.ModuleType("omni.kit.menu.utils")
    menu_utils.MenuItemDescription = lambda *args, **kwargs: types.SimpleNamespace()
    menu_utils.add_menu_items = lambda *args, **kwargs: None
    menu_utils.remove_menu_items = lambda *args, **kwargs: None
    window = types.ModuleType("omni.kit.window")
    filepicker = types.ModuleType("omni.kit.window.filepicker")
    filepicker.FilePickerDialog = object
    ui = types.ModuleType("omni.ui")

    omni.ext = ext
    omni.kit = kit
    omni.ui = ui
    kit.actions = actions
    kit.app = app
    kit.menu = menu
    kit.window = window
    actions.core = actions_core
    menu.utils = menu_utils
    window.filepicker = filepicker

    sys.modules.setdefault("omni", omni)
    sys.modules.setdefault("omni.ext", ext)
    sys.modules.setdefault("omni.kit", kit)
    sys.modules.setdefault("omni.kit.actions", actions)
    sys.modules.setdefault("omni.kit.actions.core", actions_core)
    sys.modules.setdefault("omni.kit.app", app)
    sys.modules.setdefault("omni.kit.menu", menu)
    sys.modules.setdefault("omni.kit.menu.utils", menu_utils)
    sys.modules.setdefault("omni.kit.window", window)
    sys.modules.setdefault("omni.kit.window.filepicker", filepicker)
    sys.modules.setdefault("omni.ui", ui)


def load_app_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


install_omni_stubs()
app_pkg = types.ModuleType("findsurface_omniverse")
app_pkg.__path__ = [str(APP_ROOT)]
sys.path.insert(0, str(EXTENSION_ROOT))
sys.modules.setdefault("findsurface_omniverse", app_pkg)

camera = load_app_module("findsurface_omniverse.camera", "camera.py")
surface_preview = load_app_module("findsurface_omniverse.surface_preview", "surface_preview.py")
from findsurface.bootstrap import native  # noqa: E402

app_state = load_app_module("findsurface_omniverse.app_state", "app_state.py")
detection = types.SimpleNamespace(
    DETECTION_TYPES=native.DETECTION_TYPES,
    DetectionOptions=native.DetectionOptions,
    PointCloudState=app_state.PointCloudState,
    StateTransaction=app_state.StateTransaction,
    TRANSACTION_APPLY_DETECTION=app_state.TRANSACTION_APPLY_DETECTION,
    TRANSACTION_CANCEL_DETECTION=app_state.TRANSACTION_CANCEL_DETECTION,
    TRANSACTION_CAMERA_CHANGE=app_state.TRANSACTION_CAMERA_CHANGE,
    TRANSACTION_DELETE_GEOMETRY=app_state.TRANSACTION_DELETE_GEOMETRY,
    TRANSACTION_GEOMETRY_VISIBILITY=app_state.TRANSACTION_GEOMETRY_VISIBILITY,
    TRANSACTION_GLOBAL_VISIBILITY=app_state.TRANSACTION_GLOBAL_VISIBILITY,
    TRANSACTION_PARAMETER_CHANGE=app_state.TRANSACTION_PARAMETER_CHANGE,
    TRANSACTION_RESET_DETECTION=app_state.TRANSACTION_RESET_DETECTION,
)
point_cloud = types.ModuleType("findsurface.bootstrap.point_cloud")
point_cloud.load_point_cloud = lambda path: None


class PointCloudSizeError(ValueError):
    pass


class ImportCanceledError(RuntimeError):
    pass


class ImportCancelToken:
    def __init__(self):
        self.canceled = False

    def cancel(self):
        self.canceled = True

    def is_canceled(self):
        return self.canceled


point_cloud.ImportOptions = lambda **kwargs: types.SimpleNamespace(
    max_points=kwargs.get("max_points", 200000),
    target_points=kwargs.get("target_points", 100000),
    overflow_policy=kwargs.get("overflow_policy", "ask"),
    include_mesh_vertices=kwargs.get("include_mesh_vertices", False),
    retain_sampled_source_indices=kwargs.get("retain_sampled_source_indices", False),
    max_source_index_mapping_points=kwargs.get("max_source_index_mapping_points", 200000),
)
point_cloud.ImportCanceledError = ImportCanceledError
point_cloud.ImportCancelToken = ImportCancelToken
point_cloud.PointCloudSizeError = PointCloudSizeError
point_cloud.SUPPORTED_EXTENSIONS = {".xyz", ".pts", ".ptx", ".ply", ".pcd", ".obj", ".usd", ".usda", ".usdc"}


class PointCloudData:
    def __init__(self, path, points, metadata=None):
        self.path = path
        self.points = list(points)
        self.metadata = dict(metadata or {})

    @property
    def count(self):
        return len(self.points)


point_cloud.PointCloudData = PointCloudData
sys.modules["findsurface.bootstrap.app_point_cloud"] = point_cloud
sys.modules["findsurface.bootstrap.point_cloud"] = point_cloud
sys.modules["findsurface_omniverse.point_cloud"] = point_cloud
viewport = types.ModuleType("findsurface.bootstrap.viewport")
viewport.PointCloudViewport = object
sys.modules["findsurface.bootstrap.viewport"] = viewport
sys.modules["findsurface_omniverse.viewport"] = viewport
extension = load_app_module("findsurface_omniverse.extension", "extension.py")
workspace = sys.modules["findsurface_omniverse.workspace"]


class Label:
    def __init__(self):
        self.text = ""


class Button:
    def __init__(self):
        self.enabled = False
        self.text = ""
        self.image_url = ""
        self.selected = False
        self.checked = False


class UiContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RangeSlider:
    __slots__ = ("min", "max", "enabled", "dragging")

    def __init__(self, enabled=True, dragging=False):
        self.min = None
        self.max = None
        self.enabled = enabled
        self.dragging = dragging


class Subscription:
    def __init__(self, callbacks, callback):
        self._callbacks = callbacks
        self._callback = callback

    def unsubscribe(self):
        if self._callback in self._callbacks:
            self._callbacks.remove(self._callback)


class FloatModel:
    def __init__(self, value):
        self.as_float = float(value)
        self.editing = False
        self._value_callbacks = []

    @property
    def as_int(self):
        return int(self.as_float)

    def set_value(self, value):
        self.as_float = float(value)
        for callback in list(self._value_callbacks):
            callback(self)

    def is_editing(self):
        return bool(self.editing)

    def subscribe_value_changed_fn(self, callback):
        self._value_callbacks.append(callback)
        return Subscription(self._value_callbacks, callback)


class IntModel:
    def __init__(self, value):
        self.as_int = int(value)
        self.editing = False

    def set_value(self, value):
        self.as_int = int(value)

    def get_value_as_int(self):
        return self.as_int

    def is_editing(self):
        return bool(self.editing)


class ComboModel:
    def __init__(self, index):
        self._value_model = IntModel(index)
        self._item_callbacks = []

    def get_item_value_model(self):
        return self._value_model

    def add_item_changed_fn(self, callback):
        self._item_callbacks.append(callback)
        return Subscription(self._item_callbacks, callback)

    def set_value(self, index):
        self._value_model.set_value(index)
        for callback in list(self._item_callbacks):
            callback(self, None)


class ComboBox:
    calls = []

    def __init__(self, index, *items, **kwargs):
        self.index = index
        self.items = tuple(items)
        self.kwargs = dict(kwargs)
        self.model = ComboModel(index)
        ComboBox.calls.append(self)


extension.ui.SimpleFloatModel = FloatModel
extension.ui.SimpleIntModel = IntModel


class Viewport:
    def __init__(self):
        self.surfaces = []
        self.active_mask = None
        self.pick_markers = None
        self.point_cloud = None
        self.camera = camera.OrbitCamera()
        self.point_size = 3.0
        self.point_color = [0.8, 0.8, 0.8, 1.0]
        self.selected_point_color = [1.0, 0.0, 0.0, 1.0]
        self.inlier_negative_color = [0.0, 0.2, 1.0, 1.0]
        self.inlier_zero_color = [0.0, 1.0, 0.0, 1.0]
        self.inlier_positive_color = [1.0, 0.2, 0.0, 1.0]
        self.inlier_negative_sigma = -2.0
        self.inlier_positive_sigma = 2.0
        self.surface_color = [0.2, 0.7, 1.0, 0.35]
        self.surface_wire_color = [1.0, 1.0, 1.0, 1.0]
        self.outlier_points_visible = True
        self.surface_meshes_visible = True
        self.inlier_points_visible = True
        self.pick_nearest_on_probe_miss = True
        self.probe_radius_px = 6.0
        self.seed_radius = 0.15
        self.picking_enabled = True
        self.draw_count = 0
        self.poll_hover_pick_count = 0
        self.clear_hover_pick_count = 0
        self.retroactive_pick_index = None
        self.retroactive_pick_active = False
        self.selected_result_id = None
        self.focused_result_id = None
        self.data_overlay = None
        self.hover_detection_overlay = None

    def set_surfaces(self, surfaces):
        self.surfaces = list(surfaces)

    def clear_surfaces(self):
        self.surfaces = []

    def set_active_mask(self, active_mask):
        self.active_mask = list(active_mask)

    def set_point_cloud(self, point_cloud, active_mask):
        self.point_cloud = point_cloud
        self.active_mask = list(active_mask)

    def set_pick_markers(self, hover_index=None, selected_index=None):
        self.pick_markers = (hover_index, selected_index)

    def set_retroactive_pick_index(self, index):
        self.retroactive_pick_index = index

    def set_retroactive_pick_active(self, active):
        self.retroactive_pick_active = bool(active)

    def set_data_overlay(self, **kwargs):
        self.data_overlay = dict(kwargs)

    def set_hover_detection_overlay(self, **kwargs):
        self.hover_detection_overlay = dict(kwargs)

    def set_result_visibility(self, result_id, mesh_visible=None, inliers_visible=None):
        for result in self.surfaces:
            if result.id != result_id:
                continue
            if mesh_visible is not None:
                result.mesh_visible = bool(mesh_visible)
            if inliers_visible is not None:
                result.inliers_visible = bool(inliers_visible)

    def set_selected_result(self, result_id):
        self.selected_result_id = result_id
        return True

    def focus_result(self, result_id):
        self.focused_result_id = result_id
        return any(result.id == result_id for result in self.surfaces)

    def set_global_visibility(self, outlier_points=None, surface_meshes=None, inlier_points=None):
        if outlier_points is not None:
            self.outlier_points_visible = bool(outlier_points)
        if surface_meshes is not None:
            self.surface_meshes_visible = bool(surface_meshes)
        if inlier_points is not None:
            self.inlier_points_visible = bool(inlier_points)

    def set_point_size(self, size):
        self.point_size = float(size)

    def set_point_color(self, color):
        self.point_color = list(color)

    def set_selected_point_color(self, color):
        self.selected_point_color = list(color)

    def set_inlier_colors(
        self,
        negative_color=None,
        zero_color=None,
        positive_color=None,
        negative_sigma=None,
        positive_sigma=None,
    ):
        if negative_color is not None:
            self.inlier_negative_color = list(negative_color)
        if zero_color is not None:
            self.inlier_zero_color = list(zero_color)
        if positive_color is not None:
            self.inlier_positive_color = list(positive_color)
        if negative_sigma is not None:
            self.inlier_negative_sigma = float(negative_sigma)
        if positive_sigma is not None:
            self.inlier_positive_sigma = float(positive_sigma)

    def set_surface_color(self, color):
        self.surface_color = list(color)

    def set_surface_wire_color(self, color):
        self.surface_wire_color = list(color)

    def set_pick_nearest_on_probe_miss(self, enabled):
        self.pick_nearest_on_probe_miss = bool(enabled)

    def set_probe_radius(self, radius_px):
        self.probe_radius_px = float(radius_px)

    def set_seed_radius(self, radius):
        self.seed_radius = float(radius)

    def set_picking_enabled(self, enabled):
        self.picking_enabled = bool(enabled)

    def draw(self):
        self.draw_count += 1

    def poll_hover_pick(self):
        self.poll_hover_pick_count += 1

    def _clear_hover_pick(self):
        self.clear_hover_pick_count += 1

    def set_projection_mode(self, mode):
        self.camera.set_projection_mode(mode)


def make_extension():
    ext = extension.FindSurfaceBootstrapExtension.__new__(extension.FindSurfaceBootstrapExtension)
    ext._state = detection.PointCloudState(
        types.SimpleNamespace(
            count=4,
            points=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            metadata={},
        )
    )
    ext._hover_index = 0
    ext._selected_index = 1
    ext._auto_detect_result = None
    ext._auto_detect_source = None
    ext._last_successful_auto_detect_result = None
    ext._last_successful_auto_detect_key = None
    ext._retroactive_pick_index = None
    ext._auto_detect_lock = Lock()
    ext._auto_detect_busy = False
    ext._auto_detect_key = None
    ext._auto_detect_pending = None
    ext._auto_detect_deferred = None
    ext._auto_detect_request_token = 0
    ext._auto_detect_display_deadline = None
    ext._auto_detect_overlay_suppressed = False
    ext._viewport = Viewport()
    ext._shutdown_observers = []
    ext._update_task = None
    ext._dock_task = None
    ext._geometry_refresh_task = None
    ext._transactions_refresh_task = None
    ext._findsurface_refresh_task = None
    ext._parameter_pad_refresh_task = None
    ext._active_count_label = Label()
    ext._hover_index_label = Label()
    ext._selected_index_label = Label()
    ext._result_label = Label()
    ext._status_label = Label()
    ext._dirty_label = Label()
    ext._dataset_label = Label()
    ext._point_count_label = Label()
    ext._dataset_name = "cloud.xyz"
    ext._capture_button = Button()
    ext._toolbar_capture_button = Button()
    ext._toolbar_undo_button = Button()
    ext._redo_button = Button()
    ext._tutorial_button = Button()
    ext._export_button = Button()
    ext._geometry_histogram_bin_counts = {}
    ext._geometry_histogram_cache_result = None
    ext._geometry_histogram_cache_key = None
    ext._geometry_histogram_cache_value = None
    ext._detection_type = "Auto"
    ext._models = {}
    ext._range_edit_models = {}
    ext._range_edit_dirty = set()
    ext._model_subscriptions = []
    ext._range_sliders = {}
    ext._model_subscription_keys = set()
    ext._parameter_pad_rects = {}
    ext._parameter_pad_positions = {}
    ext._parameter_pad_handle_spacers = {}
    ext._parameter_pad_frame = None
    ext._parameter_pad_value_labels = {}
    ext._parameter_pad_axes = dict(extension.FindSurfaceBootstrapExtension.PARAMETER_PAD_DEFAULT_AXES)
    ext._parameter_pad_axis_models = {}
    ext._parameter_pad_axis_options = {}
    ext._syncing_parameter_pad_axis_models = set()
    ext._active_parameter_pad = None
    ext._syncing_models = False
    ext._file_dialog = None
    ext._load_workspace_dialog = None
    ext._save_workspace_dialog = None
    ext._export_geometries_dialog = None
    ext._export_options_dialog = None
    ext._export_include_visualization_meshes = False
    ext._recent_file_directories = {}
    ext._load_error_dialog = None
    ext._point_limit_dialog = None
    ext._unsaved_changes_dialog = None
    ext._geometry_action_dialog = None
    ext._sample_target_model = None
    ext._pending_oversized_import_path = None
    ext._pending_oversized_import_error = None
    ext._import_lock = Lock()
    ext._import_busy = False
    ext._import_request_token = 0
    ext._import_cancel_token = None
    ext._import_pending = None
    ext._import_progress = None
    ext._import_progress_dialog = None
    ext._import_progress_label = None
    ext._last_import_progress_text = None
    ext._is_dirty = False
    ext._pending_unsaved_action = None
    ext._save_dialog_continue_after = None
    ext._workspace_path = None
    ext._deferred_destroy_tasks = []
    ext._allow_shutdown_once = False
    ext._app_shutting_down = False
    ext._runtime_resources_released = False
    ext._content_dirty = False
    ext._display_camera_dirty = False
    ext._saved_display_camera_settings = None
    ext._windows = {}
    ext._menu_items = {}
    ext._registered_actions = []
    ext._keyboard = None
    ext._keyboard_input = None
    ext._keyboard_subscription = None
    ext._geometries_summary_label = None
    ext._transaction_summary_label = None
    ext._geometry_collapsed = {}
    ext._hovered_histogram_bin = None
    ext._hovered_histogram_bin_key = None
    ext._hovered_histogram_result_id = None
    ext._hovered_histogram_display_index = 0
    ext._hovered_histogram_display_count = 0
    ext._hovered_histogram_mouse_x = None
    ext._hovered_histogram_mouse_y = None
    ext._histogram_status_regions = []
    ext._histogram_status_labels = {}
    ext._histogram_status_key = None
    ext._hovered_geometry_id = None
    ext._status_message = "No data loaded"
    ext._save_button = Button()
    ext._undo_button = Button()
    ext._toolbar_detection_buttons = {}
    ext._toolbar_projection_buttons = {}
    ext._visibility_buttons = {}
    ext._viewport_tab_bar_hidden_by_default = False
    return ext


def install_detection_parameter_models(ext):
    ext._models.update(
        {
            "seed_radius": FloatModel(0.15),
            "measurement_accuracy": FloatModel(0.003),
            "mean_distance": FloatModel(0.05),
            "radial_expansion": IntModel(5),
            "lateral_extension": IntModel(5),
        }
    )
    ext._sync_parameter_transaction_baseline()


def install_detection_parameter_pad_models(ext):
    install_detection_parameter_models(ext)
    for name, (_label, value, minimum, maximum) in extension.FindSurfaceBootstrapExtension.RANGE_PARAMETER_DEFAULTS.items():
        ext._models[f"{name}_min"] = FloatModel(minimum)
        ext._models[f"{name}_max"] = FloatModel(maximum)
        ext._models[f"{name}_slider_index"] = IntModel(
            extension.FindSurfaceBootstrapExtension._range_slider_index_for_value(ext, value, minimum, maximum)
        )
    ext._sync_parameter_transaction_baseline()


def install_display_models(ext):
    ext._models.update(
        {
            "point_size": FloatModel(ext._viewport.point_size),
            "point_r": FloatModel(0.25),
            "point_g": FloatModel(0.5),
            "point_b": FloatModel(0.75),
            "point_a": FloatModel(0.8),
            "point_brightness": FloatModel(1.2),
            "selected_point_r": FloatModel(0.95),
            "selected_point_g": FloatModel(0.25),
            "selected_point_b": FloatModel(0.1),
            "selected_point_a": FloatModel(0.9),
            "selected_point_brightness": FloatModel(1.0),
            "inlier_negative_r": FloatModel(0.1),
            "inlier_negative_g": FloatModel(0.2),
            "inlier_negative_b": FloatModel(0.8),
            "inlier_negative_a": FloatModel(0.85),
            "inlier_negative_brightness": FloatModel(1.0),
            "inlier_zero_r": FloatModel(0.1),
            "inlier_zero_g": FloatModel(0.8),
            "inlier_zero_b": FloatModel(0.25),
            "inlier_zero_a": FloatModel(0.9),
            "inlier_zero_brightness": FloatModel(1.0),
            "inlier_positive_r": FloatModel(0.9),
            "inlier_positive_g": FloatModel(0.4),
            "inlier_positive_b": FloatModel(0.1),
            "inlier_positive_a": FloatModel(0.95),
            "inlier_positive_brightness": FloatModel(1.0),
            "inlier_negative_sigma": FloatModel(-1.5),
            "inlier_positive_sigma": FloatModel(2.5),
            "surface_r": FloatModel(0.2),
            "surface_g": FloatModel(0.65),
            "surface_b": FloatModel(0.9),
            "surface_a": FloatModel(0.4),
            "surface_brightness": FloatModel(1.0),
            "surface_wire_r": FloatModel(0.95),
            "surface_wire_g": FloatModel(0.9),
            "surface_wire_b": FloatModel(0.55),
            "surface_wire_a": FloatModel(1.0),
            "surface_wire_brightness": FloatModel(1.0),
            "histogram_tooltip_background_r": FloatModel(1.0),
            "histogram_tooltip_background_g": FloatModel(1.0),
            "histogram_tooltip_background_b": FloatModel(1.0),
            "histogram_tooltip_background_a": FloatModel(0.88),
            "histogram_tooltip_background_brightness": FloatModel(1.0),
            "histogram_tooltip_text_r": FloatModel(0.04),
            "histogram_tooltip_text_g": FloatModel(0.04),
            "histogram_tooltip_text_b": FloatModel(0.04),
            "histogram_tooltip_text_a": FloatModel(1.0),
            "histogram_tooltip_text_brightness": FloatModel(1.0),
        }
    )


class CaptureFlowTests(unittest.TestCase):
    def install_geometry_dialog_stubs(self, ext):
        created_windows = []
        created_buttons = []

        class Window:
            def __init__(self, title, **kwargs):
                self.title = title
                self.kwargs = dict(kwargs)
                self.frame = UiContext()
                self.visible = True
                self.destroyed = False
                created_windows.append(self)

            def destroy(self):
                self.destroyed = True

        def make_button(label, **kwargs):
            button = types.SimpleNamespace(label=label, kwargs=dict(kwargs), clicked_fn=kwargs.get("clicked_fn"))
            created_buttons.append(button)
            return button

        previous = {
            "Window": getattr(extension.ui, "Window", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Label": getattr(extension.ui, "Label", None),
            "Button": getattr(extension.ui, "Button", None),
        }
        extension.ui.Window = Window
        extension.ui.VStack = lambda **kwargs: UiContext()
        extension.ui.HStack = lambda **kwargs: UiContext()
        extension.ui.Spacer = lambda **kwargs: None
        extension.ui.Label = lambda *args, **kwargs: None
        extension.ui.Button = make_button
        ext._defer_window_destroy = lambda window: setattr(window, "visible", False)
        return created_windows, created_buttons, previous

    def restore_ui_stubs(self, previous):
        for name, value in previous.items():
            if value is None:
                delattr(extension.ui, name)
            else:
                setattr(extension.ui, name, value)

    def test_sample_target_step_is_one_hundred(self):
        self.assertEqual(extension.SAMPLE_TARGET_STEP, 100)

    def test_range_parameter_endpoint_input_rounds_to_four_decimal_places(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(0.00123456),
            "measurement_accuracy": FloatModel(0.02),
            "measurement_accuracy_max": FloatModel(0.098765),
        }

        ext._on_range_parameter_changed("measurement_accuracy_min")

        self.assertEqual(ext._models["measurement_accuracy_min"].as_float, 0.00123456)

        ext._on_range_endpoint_edit_finished("measurement_accuracy_min")

        self.assertEqual(ext._models["measurement_accuracy_min"].as_float, 0.0012)
        self.assertEqual(ext._models["measurement_accuracy_max"].as_float, 0.0988)
        self.assertEqual(ext._models["measurement_accuracy"].as_float, 0.02)
        self.assertEqual(slider.min, 0)
        self.assertEqual(slider.max, 10)

    def test_range_parameter_endpoint_input_keeps_positive_ordered_bounds(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(-1.0),
            "measurement_accuracy": FloatModel(10.0),
            "measurement_accuracy_max": FloatModel(0.0),
        }

        ext._on_range_endpoint_edit_finished("measurement_accuracy_max")

        self.assertEqual(ext._models["measurement_accuracy_min"].as_float, 0.0001)
        self.assertEqual(ext._models["measurement_accuracy"].as_float, 0.0001)
        self.assertEqual(ext._models["measurement_accuracy_max"].as_float, 0.0001)
        self.assertEqual(slider.min, 0)
        self.assertEqual(slider.max, 0)
        self.assertFalse(slider.enabled)

    def test_range_parameter_slider_uses_integer_index_steps(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(1.0),
            "measurement_accuracy": FloatModel(4.0),
            "measurement_accuracy_max": FloatModel(11.0),
        }

        ext._on_range_parameter_changed("measurement_accuracy_min")

        self.assertEqual(slider.min, 0)
        self.assertEqual(slider.max, 10)
        self.assertTrue(slider.enabled)

    def test_range_parameter_slider_uses_minimum_value_step_for_small_ranges(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(0.0002),
            "measurement_accuracy": FloatModel(0.0004),
            "measurement_accuracy_max": FloatModel(0.0007),
        }

        ext._on_range_parameter_changed("measurement_accuracy_min")

        self.assertEqual(slider.min, 0)
        self.assertEqual(slider.max, 5)
        self.assertEqual(ext._range_slider_value_for_index(3, 0.0002, 0.0007), 0.0005)

    def test_range_parameter_slider_uses_one_tenth_step_when_range_is_large_enough(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(0.0002),
            "measurement_accuracy": FloatModel(0.0006),
            "measurement_accuracy_max": FloatModel(0.0022),
        }

        ext._on_range_parameter_changed("measurement_accuracy_min")

        self.assertEqual(slider.min, 0)
        self.assertEqual(slider.max, 10)
        self.assertAlmostEqual(ext._range_slider_value_for_index(3, 0.0002, 0.0022), 0.0008)

    def test_range_parameter_slider_index_updates_value(self):
        ext = make_extension()
        ext._range_sliders = {}
        changed = []
        ext._on_detection_settings_changed = lambda name=None: changed.append(name)
        ext._models = {
            "measurement_accuracy_min": FloatModel(1.0),
            "measurement_accuracy": FloatModel(1.0),
            "measurement_accuracy_max": FloatModel(11.0),
            "measurement_accuracy_slider_index": IntModel(4),
        }

        ext._on_range_parameter_changed("measurement_accuracy_slider_index")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 5.0)
        self.assertEqual(changed, ["measurement_accuracy"])

    def test_range_parameter_direct_value_syncs_slider_index_without_snapping(self):
        ext = make_extension()
        ext._range_sliders = {}
        ext._models = {
            "measurement_accuracy_min": FloatModel(1.0),
            "measurement_accuracy": FloatModel(4.6),
            "measurement_accuracy_max": FloatModel(11.0),
            "measurement_accuracy_slider_index": IntModel(0),
        }

        ext._on_range_parameter_changed("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 4.6)
        self.assertEqual(ext._models["measurement_accuracy_slider_index"].as_int, 4)

    def test_range_parameter_value_change_clamps_without_resnapping(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._models = {
            "measurement_accuracy_min": FloatModel(1.0),
            "measurement_accuracy": FloatModel(4.49),
            "measurement_accuracy_max": FloatModel(11.0),
        }

        ext._on_range_parameter_changed("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 4.49)

        ext._models["measurement_accuracy"].set_value(12.0)
        ext._on_range_parameter_changed("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 11.0)

    def test_range_parameter_direct_value_input_clamps_without_rounding(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        changed = []
        ext._on_detection_settings_changed = lambda name=None: changed.append(name)
        ext._models = {
            "measurement_accuracy_min": FloatModel(1.0),
            "measurement_accuracy": FloatModel(4.123456),
            "measurement_accuracy_max": FloatModel(10.0),
        }
        value_model = ext._range_edit_model("measurement_accuracy")
        value_model.editing = True

        ext._on_detection_parameter_edit_finished("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 4.123456)
        self.assertEqual(changed, [])

        value_model.set_value(12.3456)
        ext._on_detection_parameter_edit_finished("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 4.123456)
        self.assertEqual(changed, [])

        value_model.editing = False
        ext._on_detection_parameter_edit_finished("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 10.0)
        self.assertEqual(ext._models["measurement_accuracy_min"].as_float, 1.0)
        self.assertEqual(ext._models["measurement_accuracy_max"].as_float, 10.0)
        self.assertEqual(changed, ["measurement_accuracy"])

    def test_range_parameter_direct_value_input_clamps_to_minimum_floor(self):
        ext = make_extension()
        slider = RangeSlider()
        ext._range_sliders = {"measurement_accuracy": slider}
        ext._on_detection_settings_changed = lambda name=None: None
        ext._models = {
            "measurement_accuracy_min": FloatModel(0.0001),
            "measurement_accuracy": FloatModel(0.003),
            "measurement_accuracy_max": FloatModel(1.0),
        }
        value_model = ext._range_edit_model("measurement_accuracy")
        value_model.editing = True
        value_model.set_value(0.00005)

        ext._on_detection_parameter_edit_finished("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 0.003)

        value_model.editing = False
        ext._on_detection_parameter_edit_finished("measurement_accuracy")

        self.assertEqual(ext._models["measurement_accuracy"].as_float, 0.0001)

    def test_range_parameter_format_uses_four_decimal_places(self):
        ext = make_extension()

        self.assertEqual(ext._format_range_parameter_value(12345.678), "12345.6780")
        self.assertEqual(float(ext._format_range_parameter_value(0.00123456)), 0.0012)
        self.assertEqual(ext._round_range_endpoint(0.00004), 0.0001)

    def test_range_parameter_model_uses_simple_float_model(self):
        ext = make_extension()
        model = ext._new_range_float_model(0.00123456)

        self.assertIsInstance(model, FloatModel)
        self.assertEqual(model.as_float, 0.00123456)

    def test_range_parameter_slider_index_model_uses_simple_int_model(self):
        ext = make_extension()
        model = ext._new_range_slider_index_model(3)

        self.assertIsInstance(model, IntModel)
        self.assertEqual(model.as_int, 3)

    def test_range_parameter_group_style_draws_framed_section(self):
        ext = make_extension()
        style = ext._range_parameter_group_style()

        self.assertIn("background_color", style)
        self.assertIn("border_color", style)
        self.assertEqual(style["background_color"], 0x0)
        self.assertEqual(style["border_color"], extension.FindSurfaceBootstrapExtension.PARAMETER_GROUP_BORDER_COLOR)
        self.assertEqual(style["border_width"], 1)
        self.assertEqual(style["border_radius"], 4)
        self.assertNotIn("padding", style)
        self.assertEqual(extension.FindSurfaceBootstrapExtension.RANGE_PARAMETER_GROUP_PADDING, 8)
        self.assertEqual(extension.FindSurfaceBootstrapExtension.PARAMETER_GROUP_BORDER_COLOR, 0xFFE6E6E6)

    def test_range_parameter_value_field_stays_next_to_label(self):
        ext = make_extension()
        ext._models = {
            "measurement_accuracy": FloatModel(0.003),
            "measurement_accuracy_min": FloatModel(0.001),
            "measurement_accuracy_max": FloatModel(0.05),
            "measurement_accuracy_slider_index": IntModel(0),
        }
        ext._parameter_control_mouse_kwargs = lambda _name: {}
        labels = []
        fields = []
        previous = {
            "ZStack": getattr(extension.ui, "ZStack", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Label": getattr(extension.ui, "Label", None),
            "FloatField": getattr(extension.ui, "FloatField", None),
            "FloatDrag": getattr(extension.ui, "FloatDrag", None),
            "IntSlider": getattr(extension.ui, "IntSlider", None),
        }

        def make_float_field(**kwargs):
            fields.append(dict(kwargs))
            return types.SimpleNamespace()

        def make_int_slider(**kwargs):
            slider = RangeSlider()
            slider.min = kwargs.get("min")
            slider.max = kwargs.get("max")
            return slider

        try:
            extension.ui.ZStack = lambda **kwargs: UiContext()
            extension.ui.Rectangle = lambda **kwargs: None
            extension.ui.VStack = lambda **kwargs: UiContext()
            extension.ui.HStack = lambda **kwargs: UiContext()
            extension.ui.Spacer = lambda **kwargs: None
            extension.ui.Label = lambda text, **kwargs: labels.append((text, dict(kwargs)))
            extension.ui.FloatField = make_float_field
            extension.ui.FloatDrag = make_float_field
            extension.ui.IntSlider = make_int_slider

            ext._range_float_row("Measurement\nAccuracy", "measurement_accuracy")
        finally:
            self.restore_ui_stubs(previous)

        value_label = next(kwargs for text, kwargs in labels if text == "Measurement Accuracy:")
        self.assertEqual(value_label["width"], ext.RANGE_PARAMETER_VALUE_LABEL_WIDTH)
        self.assertEqual(fields[0]["width"], ext.RANGE_PARAMETER_FIELD_WIDTH)

    def test_workspace_save_and_load_round_trip_updates_dirty_state(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            measurement_accuracy=0.02,
            rms_error=0.001,
            parameters={"normal": (0.0, 0.0, 1.0)},
        )
        ext._state.apply_result(result)
        ext._set_dirty(True)
        ext._viewport.set_global_visibility(outlier_points=False, surface_meshes=False, inlier_points=False)
        ext._viewport.camera.set_projection_mode(camera.PROJECTION_PERSPECTIVE)

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            self.assertFalse(ext._is_dirty)
            self.assertEqual(ext._workspace_path, path)

            restored = make_extension()
            restored._load_workspace_from_path(path)

            self.assertFalse(restored._is_dirty)
            self.assertEqual(restored._workspace_path, path)
            self.assertEqual(restored._state.point_count, 4)
            self.assertEqual(len(restored._state.results), 1)
            self.assertEqual(restored._viewport.surfaces[0].id, "Plane_001")
            self.assertFalse(restored._viewport.outlier_points_visible)
            self.assertFalse(restored._viewport.surface_meshes_visible)
            self.assertFalse(restored._viewport.inlier_points_visible)
            self.assertEqual(restored._viewport.camera.projection_mode, camera.PROJECTION_PERSPECTIVE)

    def test_load_workspace_failure_shows_error_dialog_and_keeps_picker_open(self):
        ext = make_extension()
        windows, buttons, previous = self.install_geometry_dialog_stubs(ext)

        class Picker:
            def __init__(self):
                self.visible = True

            def hide(self):
                self.visible = False

        picker = Picker()
        ext._load_workspace_dialog = picker
        ext._load_workspace_from_path = lambda path: (_ for _ in ()).throw(
            workspace.WorkspaceError("Expected a workspace USD, but found geometry_export.")
        )

        try:
            ext._on_load_workspace_accepted("foo.usda", r"C:\tmp")

            self.assertEqual(windows[-1].title, "Load Workspace Failed")
            self.assertIs(ext._load_error_dialog, windows[-1])
            self.assertTrue(picker.visible)
            self.assertIn("Load failed: Expected a workspace USD", ext._status_message)
            self.assertEqual(buttons[-1].label, "OK")

            buttons[-1].clicked_fn()

            self.assertIsNone(ext._load_error_dialog)
            self.assertFalse(windows[-1].visible)
        finally:
            self.restore_ui_stubs(previous)

    def test_file_dialogs_open_from_recent_directory_for_each_operation(self):
        ext = make_extension()
        ext._recent_file_directories = {
            extension.FILE_DIALOG_IMPORT_POINTS: r"C:\clouds",
            extension.FILE_DIALOG_LOAD_WORKSPACE: r"D:\workspaces",
            extension.FILE_DIALOG_SAVE_WORKSPACE: r"E:\saves",
            extension.FILE_DIALOG_EXPORT_GEOMETRIES: r"F:\exports",
        }
        dialogs = []
        previous_file_picker = extension.FilePickerDialog

        class Picker:
            def __init__(self, title, **kwargs):
                self.title = title
                self.kwargs = dict(kwargs)
                self.current_directories = []
                self.visible = False
                dialogs.append(self)

            def set_current_directory(self, directory):
                self.current_directories.append(directory)

            def show(self):
                self.visible = True

            def hide(self):
                self.visible = False

        extension.FilePickerDialog = Picker
        try:
            ext._show_import_points_dialog_unchecked()
            ext._show_load_workspace_dialog_unchecked()
            ext._show_save_workspace_dialog()
            ext._open_export_file_dialog(False)

            self.assertEqual(dialogs[0].kwargs["current_directory"], r"C:\clouds")
            self.assertEqual(dialogs[1].kwargs["current_directory"], r"D:\workspaces")
            self.assertEqual(dialogs[2].kwargs["current_directory"], r"E:\saves")
            self.assertEqual(dialogs[3].kwargs["current_directory"], r"F:\exports")
            self.assertEqual(dialogs[0].current_directories[-1], r"C:\clouds")
            self.assertEqual(dialogs[1].current_directories[-1], r"D:\workspaces")
            self.assertEqual(dialogs[2].current_directories[-1], r"E:\saves")
            self.assertEqual(dialogs[3].current_directories[-1], r"F:\exports")
        finally:
            extension.FilePickerDialog = previous_file_picker

    def test_reused_file_dialog_applies_updated_recent_directory_before_show(self):
        ext = make_extension()

        class Picker:
            def __init__(self):
                self.current_directories = []
                self.shown = 0

            def set_current_directory(self, directory):
                self.current_directories.append(directory)

            def show(self):
                self.shown += 1

        ext._file_dialog = Picker()
        ext._recent_file_directories = {extension.FILE_DIALOG_IMPORT_POINTS: r"C:\new_clouds"}

        ext._show_import_points_dialog_unchecked()

        self.assertEqual(ext._file_dialog.current_directories, [r"C:\new_clouds"])
        self.assertEqual(ext._file_dialog.shown, 1)

    def test_file_dialogs_fall_back_to_preset_directories_without_recent_paths(self):
        ext = make_extension()
        ext._recent_file_directories = {}
        ext._app_config = {
            "preset_file_directories": {
                extension.FILE_DIALOG_IMPORT_POINTS: "data/presets/pointclouds",
                extension.FILE_DIALOG_LOAD_WORKSPACE: "data/presets/workspaces",
            }
        }
        extension_root = ext._extension_root()

        self.assertEqual(
            ext._recent_file_directory(extension.FILE_DIALOG_IMPORT_POINTS),
            os.path.normpath(os.path.join(extension_root, "data", "presets", "pointclouds")),
        )
        self.assertEqual(
            ext._recent_file_directory(extension.FILE_DIALOG_LOAD_WORKSPACE),
            os.path.normpath(os.path.join(extension_root, "data", "presets", "workspaces")),
        )
        self.assertIsNone(ext._recent_file_directory(extension.FILE_DIALOG_SAVE_WORKSPACE))

    def test_accepted_file_paths_update_recent_directories_by_operation(self):
        ext = make_extension()
        ext._file_dialog = types.SimpleNamespace(hide=lambda: None)
        ext._load_workspace_dialog = types.SimpleNamespace(hide=lambda: None)
        ext._save_workspace_dialog = types.SimpleNamespace(hide=lambda: None)
        ext._export_geometries_dialog = types.SimpleNamespace(hide=lambda: None)
        ext._begin_import_points = lambda *args, **kwargs: None
        ext._load_workspace_from_path = lambda path: None
        ext._save_workspace_to_path = lambda path: True
        ext._export_geometries_to_path = lambda path: True

        ext._on_import_points_accepted("cloud.xyz", r"C:\clouds")
        ext._on_load_workspace_accepted("workspace.usda", r"D:\workspaces")
        ext._on_save_workspace_accepted("saved", r"E:\saves")
        ext._on_export_geometries_accepted("exported", r"F:\exports")

        self.assertEqual(ext._recent_file_directories[extension.FILE_DIALOG_IMPORT_POINTS], r"C:\clouds")
        self.assertEqual(ext._recent_file_directories[extension.FILE_DIALOG_LOAD_WORKSPACE], r"D:\workspaces")
        self.assertEqual(ext._recent_file_directories[extension.FILE_DIALOG_SAVE_WORKSPACE], r"E:\saves")
        self.assertEqual(ext._recent_file_directories[extension.FILE_DIALOG_EXPORT_GEOMETRIES], r"F:\exports")

    def test_remembered_file_dialog_directory_is_written_to_app_config(self):
        ext = make_extension()
        written = []
        previous_write = extension.app_config.write_app_config
        ext._app_config = {"recent_file_directories": {}}
        ext._app_config_path = r"C:\settings\app_defaults.json"
        extension.app_config.write_app_config = lambda path, config: written.append((path, dict(config)))
        try:
            ext._remember_file_dialog_directory(extension.FILE_DIALOG_IMPORT_POINTS, r"C:\clouds\cloud.xyz")
        finally:
            extension.app_config.write_app_config = previous_write

        self.assertEqual(ext._recent_file_directories[extension.FILE_DIALOG_IMPORT_POINTS], r"C:\clouds")
        self.assertEqual(ext._app_config["recent_file_directories"][extension.FILE_DIALOG_IMPORT_POINTS], r"C:\clouds")
        self.assertEqual(written[0][0], r"C:\settings\app_defaults.json")

    def test_workspace_load_fully_restores_saved_camera_state(self):
        ext = make_extension()
        ext._viewport.camera.set_projection_mode(camera.PROJECTION_PERSPECTIVE)
        ext._viewport.camera.center = [10.0, -5.0, 2.5]
        ext._viewport.camera.set_direction_up([0.25, -0.5, -1.0], [0.0, 1.0, 0.0])
        ext._viewport.camera.zoom = 3.25
        ext._viewport.camera.diameter = 12.5
        ext._viewport.camera.set_fov_degrees(62.0)

        expected_camera = {
            "projection_mode": ext._viewport.camera.projection_mode,
            "center": list(ext._viewport.camera.center),
            "orientation": list(ext._viewport.camera.orientation),
            "zoom": ext._viewport.camera.zoom,
            "diameter": ext._viewport.camera.diameter,
            "fov_degrees": ext._viewport.camera.fov_degrees,
        }

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            restored = make_extension()
            restored._load_workspace_from_path(path)

        restored_camera = restored._viewport.camera
        self.assertEqual(restored_camera.projection_mode, expected_camera["projection_mode"])
        self.assertEqual(restored_camera.center, expected_camera["center"])
        self.assertEqual(restored_camera.orientation, expected_camera["orientation"])
        self.assertEqual(restored_camera.zoom, expected_camera["zoom"])
        self.assertEqual(restored_camera.diameter, expected_camera["diameter"])
        self.assertEqual(restored_camera.fov_degrees, expected_camera["fov_degrees"])
        self.assertFalse(restored._is_dirty)

    def test_workspace_load_restores_camera_transaction_for_undo(self):
        ext = make_extension()
        ext._clear_dirty_tracking()
        original_orientation = list(ext._viewport.camera.orientation)

        ext._rotate_camera_step("horizontal", 10.0)

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            restored = make_extension()
            restored._load_workspace_from_path(path)

            self.assertTrue(restored._state.can_undo)
            self.assertEqual(restored._state.transaction_log[-1].event_type, detection.TRANSACTION_CAMERA_CHANGE)

            restored._undo_last()

            self.assertEqual(restored._viewport.camera.orientation, original_orientation)
            self.assertTrue(restored._state.can_redo)

    def test_settings_snapshot_prefers_numeric_values_for_bool_capable_models(self):
        class BoolCapableFloatModel(FloatModel):
            @property
            def as_bool(self):
                return bool(self.as_float)

        class BoolCapableIntModel(IntModel):
            @property
            def as_bool(self):
                return bool(self.as_int)

        ext = make_extension()
        ext._models = {
            "surface_r": BoolCapableFloatModel(0.2),
            "surface_g": BoolCapableFloatModel(0.65),
            "surface_a": BoolCapableFloatModel(0.4),
            "inlier_negative_r": BoolCapableFloatModel(0.0),
            "point_size": BoolCapableFloatModel(7.5),
            "radial_expansion": BoolCapableIntModel(7),
            "measurement_accuracy_slider_index": BoolCapableIntModel(3),
            "auto_detect": types.SimpleNamespace(as_bool=False),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
        }

        snapshot = ext._settings_snapshot()

        self.assertEqual(snapshot["surface_r"], 0.2)
        self.assertEqual(snapshot["surface_g"], 0.65)
        self.assertEqual(snapshot["surface_a"], 0.4)
        self.assertEqual(snapshot["inlier_negative_r"], 0.0)
        self.assertEqual(snapshot["point_size"], 7.5)
        self.assertEqual(snapshot["radial_expansion"], 7)
        self.assertEqual(snapshot["measurement_accuracy_slider_index"], 3)
        self.assertFalse(snapshot["auto_detect"])
        self.assertTrue(snapshot["sticky_auto_preview"])

    def test_workspace_load_ignores_legacy_boolean_numeric_settings(self):
        ext = make_extension()
        install_display_models(ext)
        ext._models["radial_expansion"] = IntModel(5)
        ext._on_display_settings_changed()
        original_surface = list(ext._viewport.surface_color)
        original_negative = list(ext._viewport.inlier_negative_color)
        original_point_size = ext._viewport.point_size

        ext._apply_workspace_settings(
            {
                "surface_r": True,
                "surface_g": True,
                "surface_b": True,
                "surface_a": True,
                "inlier_negative_r": False,
                "inlier_negative_g": True,
                "inlier_negative_b": True,
                "point_size": True,
                "radial_expansion": True,
                "inlier_points_visible": False,
            }
        )

        self.assertEqual(ext._viewport.surface_color, original_surface)
        self.assertEqual(ext._viewport.inlier_negative_color, original_negative)
        self.assertEqual(ext._viewport.point_size, original_point_size)
        self.assertEqual(ext._models["radial_expansion"].as_int, 5)
        self.assertFalse(ext._viewport.inlier_points_visible)

    def test_workspace_load_fully_restores_saved_display_settings(self):
        ext = make_extension()
        install_display_models(ext)
        ext._models["point_size"].set_value(7.5)
        ext._on_display_settings_changed()
        ext._viewport.set_global_visibility(outlier_points=False, surface_meshes=False, inlier_points=False)

        expected_models = {name: model.as_float for name, model in ext._models.items()}
        expected_display = {
            "point_size": ext._viewport.point_size,
            "point_color": list(ext._viewport.point_color),
            "selected_point_color": list(ext._viewport.selected_point_color),
            "inlier_negative_color": list(ext._viewport.inlier_negative_color),
            "inlier_zero_color": list(ext._viewport.inlier_zero_color),
            "inlier_positive_color": list(ext._viewport.inlier_positive_color),
            "inlier_negative_sigma": ext._viewport.inlier_negative_sigma,
            "inlier_positive_sigma": ext._viewport.inlier_positive_sigma,
            "surface_color": list(ext._viewport.surface_color),
            "surface_wire_color": list(ext._viewport.surface_wire_color),
            "outlier_points_visible": ext._viewport.outlier_points_visible,
            "surface_meshes_visible": ext._viewport.surface_meshes_visible,
            "inlier_points_visible": ext._viewport.inlier_points_visible,
        }

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            restored = make_extension()
            install_display_models(restored)
            restored._load_workspace_from_path(path)

        for name, value in expected_models.items():
            self.assertEqual(restored._models[name].as_float, value)
        self.assertEqual(restored._viewport.point_size, expected_display["point_size"])
        self.assertEqual(restored._viewport.point_color, expected_display["point_color"])
        self.assertEqual(restored._viewport.selected_point_color, expected_display["selected_point_color"])
        self.assertEqual(restored._viewport.inlier_negative_color, expected_display["inlier_negative_color"])
        self.assertEqual(restored._viewport.inlier_zero_color, expected_display["inlier_zero_color"])
        self.assertEqual(restored._viewport.inlier_positive_color, expected_display["inlier_positive_color"])
        self.assertEqual(restored._viewport.inlier_negative_sigma, expected_display["inlier_negative_sigma"])
        self.assertEqual(restored._viewport.inlier_positive_sigma, expected_display["inlier_positive_sigma"])
        self.assertEqual(restored._viewport.surface_color, expected_display["surface_color"])
        self.assertEqual(restored._viewport.surface_wire_color, expected_display["surface_wire_color"])
        self.assertFalse(restored._viewport.outlier_points_visible)
        self.assertFalse(restored._viewport.surface_meshes_visible)
        self.assertFalse(restored._viewport.inlier_points_visible)
        self.assertFalse(restored._is_dirty)

    def test_workspace_load_restores_visibility_transaction_for_undo(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
        ext._clear_dirty_tracking()
        ext._toggle_global_visibility("outliers")

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            restored = make_extension()
            restored._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
            restored._load_workspace_from_path(path)

            self.assertFalse(restored._viewport.outlier_points_visible)
            self.assertTrue(restored._state.can_undo)

            restored._undo_last()

            self.assertTrue(restored._viewport.outlier_points_visible)
            self.assertTrue(restored._is_dirty)
            self.assertTrue(restored._state.can_redo)

    def test_state_command_routes_detection_transactions_through_shared_dirty_path(self):
        ext = make_extension()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )

        record = ext._run_state_command(lambda: ext._state.apply_result(result))

        self.assertEqual(record.result_id, "Plane_001")
        self.assertTrue(ext._is_dirty)
        self.assertTrue(ext._content_dirty)
        self.assertFalse(ext._display_camera_dirty)
        self.assertEqual(queued, [True])
        self.assertEqual(ext._state.transaction_log[-1].event_type, detection.TRANSACTION_APPLY_DETECTION)
        self.assertTrue(ext._undo_button.enabled)

    def test_state_change_command_routes_display_dirty_without_content_dirty(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)
        before = ext._global_visibility_state()
        ext._viewport.set_global_visibility(outlier_points=False)
        after = ext._global_visibility_state()

        transaction = ext._record_state_change_command(detection.TRANSACTION_GLOBAL_VISIBILITY, before, after)

        self.assertEqual(transaction.event_type, detection.TRANSACTION_GLOBAL_VISIBILITY)
        self.assertTrue(ext._is_dirty)
        self.assertFalse(ext._content_dirty)
        self.assertTrue(ext._display_camera_dirty)
        self.assertEqual(queued, [True])
        self.assertFalse(ext._visibility_buttons["outliers"].selected)

    def test_state_change_command_ignores_noop_payloads(self):
        ext = make_extension()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        transaction = ext._record_state_change_command(
            detection.TRANSACTION_PARAMETER_CHANGE,
            {"seed_radius": 0.15},
            {"seed_radius": 0.15},
        )

        self.assertIsNone(transaction)
        self.assertFalse(ext._is_dirty)
        self.assertEqual(queued, [])
        self.assertEqual(ext._state.transaction_log, [])

    def test_detection_parameter_change_is_undoable(self):
        ext = make_extension()
        install_detection_parameter_models(ext)
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        ext._models["seed_radius"].set_value(0.25)
        ext._on_detection_settings_changed("seed_radius")

        self.assertTrue(ext._is_dirty)
        self.assertEqual(queued, [True])
        self.assertEqual(len(ext._state.transaction_log), 1)
        self.assertEqual(ext._state.transaction_log[0].event_type, detection.TRANSACTION_PARAMETER_CHANGE)
        self.assertEqual(ext._state.transaction_log[0].state_before["seed_radius"], 0.15)
        self.assertEqual(ext._state.transaction_log[0].state_after["seed_radius"], 0.25)
        self.assertEqual(ext._viewport.seed_radius, 0.25)

        ext._undo_last()

        self.assertEqual(ext._models["seed_radius"].as_float, 0.15)
        self.assertEqual(ext._viewport.seed_radius, 0.15)
        self.assertTrue(ext._state.can_redo)

        ext._redo_last()

        self.assertEqual(ext._models["seed_radius"].as_float, 0.25)
        self.assertEqual(ext._viewport.seed_radius, 0.25)

    def test_detection_type_change_is_undoable(self):
        ext = make_extension()
        install_detection_parameter_models(ext)
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        ext._set_detection_type("Plane")

        self.assertEqual(ext._detection_type, "Plane")
        self.assertEqual(queued, [True])
        self.assertEqual(ext._state.transaction_log[0].event_type, detection.TRANSACTION_PARAMETER_CHANGE)

        ext._undo_last()

        self.assertEqual(ext._detection_type, "Auto")
        self.assertTrue(ext._state.can_redo)

        ext._redo_last()

        self.assertEqual(ext._detection_type, "Plane")

    def test_int_slider_parameter_commits_once_on_release(self):
        ext = make_extension()
        install_detection_parameter_models(ext)
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        ext._on_parameter_control_pressed("lateral_extension")
        ext._models["lateral_extension"].set_value(6)
        ext._on_detection_parameter_value_changed("lateral_extension")
        ext._models["lateral_extension"].set_value(8)
        ext._on_detection_parameter_value_changed("lateral_extension")
        ext._update_once()
        ext._update_once()

        self.assertEqual(ext._state.transaction_log, [])
        self.assertEqual(queued, [])

        ext._on_detection_parameter_edit_finished("lateral_extension")

        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.state_before["lateral_extension"], 5)
        self.assertEqual(transaction.state_after["lateral_extension"], 8)
        self.assertEqual(queued, [True])

    def test_parameter_pad_float_pair_commits_once_on_release(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)
        size = ext.PARAMETER_PAD_SIZE

        ext._on_parameter_pad_pressed("measurement_accuracy", "mean_distance", size, 0)
        ext._on_parameter_pad_moved("measurement_accuracy", "mean_distance", size * 0.5, size * 0.5)

        self.assertEqual(ext._state.transaction_log, [])
        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.0255)
        self.assertAlmostEqual(ext._models["mean_distance"].as_float, 0.03)

        ext._on_parameter_pad_released("measurement_accuracy", "mean_distance", size * 0.5, size * 0.5)

        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.event_type, detection.TRANSACTION_PARAMETER_CHANGE)
        self.assertEqual(transaction.state_before["measurement_accuracy"], 0.003)
        self.assertEqual(transaction.state_before["mean_distance"], 0.05)
        self.assertAlmostEqual(transaction.state_after["measurement_accuracy"], 0.0255)
        self.assertAlmostEqual(transaction.state_after["mean_distance"], 0.03)
        self.assertEqual(queued, [True])

    def test_parameter_pad_int_pair_snaps_applied_values_only(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        ext._clear_dirty_tracking()
        size = ext.PARAMETER_PAD_SIZE

        ext._on_parameter_pad_pressed("lateral_extension", "radial_expansion", size * 0.66, size * (1.0 - 0.24))

        self.assertEqual(ext._parameter_pad_positions["lateral_extension:radial_expansion"], (0.66, 0.24))
        self.assertEqual(ext._models["lateral_extension"].as_int, 7)
        self.assertEqual(ext._models["radial_expansion"].as_int, 2)
        self.assertEqual(ext._state.transaction_log, [])

        ext._on_parameter_pad_released("lateral_extension", "radial_expansion", size * 0.66, size * (1.0 - 0.24))

        self.assertNotIn("lateral_extension:radial_expansion", ext._parameter_pad_positions)
        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.state_before["lateral_extension"], 5)
        self.assertEqual(transaction.state_before["radial_expansion"], 5)
        self.assertEqual(transaction.state_after["lateral_extension"], 7)
        self.assertEqual(transaction.state_after["radial_expansion"], 2)

    def test_parameter_pad_axis_options_exclude_other_axis(self):
        ext = make_extension()

        self.assertEqual(ext._parameter_pad_axis_parameter("x"), "mean_distance")
        self.assertEqual(ext._parameter_pad_axis_parameter("y"), "measurement_accuracy")
        self.assertNotIn("measurement_accuracy", ext._parameter_pad_axis_options_for("x"))
        self.assertNotIn("mean_distance", ext._parameter_pad_axis_options_for("y"))

    def test_parameter_pad_dropdown_builds_combobox_with_filtered_items(self):
        ext = make_extension()
        previous_hstack = getattr(extension.ui, "HStack", None)
        previous_label = getattr(extension.ui, "Label", None)
        previous_button = getattr(extension.ui, "Button", None)
        previous_combo_box = getattr(extension.ui, "ComboBox", None)
        ComboBox.calls = []
        try:
            extension.ui.HStack = lambda **kwargs: UiContext()
            extension.ui.Label = lambda *args, **kwargs: None
            extension.ui.Button = lambda *args, **kwargs: None
            extension.ui.ComboBox = ComboBox

            ext._parameter_pad_axis_dropdown("y", width=ext.PARAMETER_PAD_CONTROL_WIDTH)

            self.assertEqual(len(ComboBox.calls), 1)
            combo = ComboBox.calls[0]
            self.assertEqual(combo.index, 0)
            self.assertIn("Measurement Accuracy", combo.items)
            self.assertNotIn("Mean Distance", combo.items)
            self.assertEqual(combo.kwargs["width"], ext.PARAMETER_PAD_CONTROL_WIDTH)
        finally:
            extension.ui.HStack = previous_hstack
            extension.ui.Label = previous_label
            extension.ui.Button = previous_button
            if previous_combo_box is None:
                delattr(extension.ui, "ComboBox")
            else:
                extension.ui.ComboBox = previous_combo_box

    def test_parameter_pad_combobox_model_updates_axis_selection(self):
        ext = make_extension()
        previous_hstack = getattr(extension.ui, "HStack", None)
        previous_label = getattr(extension.ui, "Label", None)
        previous_button = getattr(extension.ui, "Button", None)
        previous_combo_box = getattr(extension.ui, "ComboBox", None)
        ComboBox.calls = []
        queued = []
        ext._queue_findsurface_window_refresh = lambda: queued.append(True)
        try:
            extension.ui.HStack = lambda **kwargs: UiContext()
            extension.ui.Label = lambda *args, **kwargs: None
            extension.ui.Button = lambda *args, **kwargs: None
            extension.ui.ComboBox = ComboBox

            ext._parameter_pad_axis_dropdown("y", width=ext.PARAMETER_PAD_CONTROL_WIDTH)
            options = ext._parameter_pad_axis_options_for("y")
            target_index = options.index("seed_radius")
            ComboBox.calls[0].model.set_value(target_index)

            self.assertEqual(ext._parameter_pad_axes["y"], "seed_radius")
            self.assertEqual(queued, [True])
        finally:
            extension.ui.HStack = previous_hstack
            extension.ui.Label = previous_label
            extension.ui.Button = previous_button
            if previous_combo_box is None:
                delattr(extension.ui, "ComboBox")
            else:
                extension.ui.ComboBox = previous_combo_box

    def test_parameter_pad_user_axis_change_is_applied_while_models_are_syncing(self):
        ext = make_extension()
        previous_hstack = getattr(extension.ui, "HStack", None)
        previous_label = getattr(extension.ui, "Label", None)
        previous_button = getattr(extension.ui, "Button", None)
        previous_combo_box = getattr(extension.ui, "ComboBox", None)
        ComboBox.calls = []
        queued = []
        ext._queue_findsurface_window_refresh = lambda: queued.append(True)
        try:
            extension.ui.HStack = lambda **kwargs: UiContext()
            extension.ui.Label = lambda *args, **kwargs: None
            extension.ui.Button = lambda *args, **kwargs: None
            extension.ui.ComboBox = ComboBox

            ext._parameter_pad_axis_dropdown("y", width=ext.PARAMETER_PAD_CONTROL_WIDTH)
            options = ext._parameter_pad_axis_options_for("y")
            target_index = options.index("seed_radius")
            ext._syncing_models = True

            ComboBox.calls[0].model.set_value(target_index)

            self.assertEqual(ext._parameter_pad_axes["y"], "seed_radius")
            self.assertEqual(queued, [True])
        finally:
            ext._syncing_models = False
            extension.ui.HStack = previous_hstack
            extension.ui.Label = previous_label
            extension.ui.Button = previous_button
            if previous_combo_box is None:
                delattr(extension.ui, "ComboBox")
            else:
                extension.ui.ComboBox = previous_combo_box

    def test_parameter_pad_axis_model_sync_does_not_reapply_programmatic_change(self):
        ext = make_extension()
        ext._parameter_pad_axes = {"x": "mean_distance", "y": "seed_radius"}
        options = ext._parameter_pad_axis_options_for("y")
        model = ComboModel(options.index("measurement_accuracy"))
        ext._parameter_pad_axis_models["y"] = model
        ext._subscribe_parameter_pad_axis_model("y", model)

        ext._sync_parameter_pad_axis_model("y")

        self.assertEqual(ext._parameter_pad_axes["y"], "seed_radius")
        self.assertEqual(model.get_item_value_model().as_int, options.index("seed_radius"))

    def test_parameter_pad_axis_subscription_prefers_value_changed_api(self):
        ext = make_extension()
        calls = []

        class DualApiModel:
            def subscribe_value_changed_fn(self, callback):
                calls.append("value")
                return types.SimpleNamespace(unsubscribe=lambda: None)

            def subscribe_item_changed_fn(self, callback):
                calls.append("item")
                return types.SimpleNamespace(unsubscribe=lambda: None)

        model = DualApiModel()

        self.assertTrue(ext._subscribe_parameter_pad_axis_model("y", model))
        self.assertEqual(calls, ["value"])

    def test_parameter_pad_axis_change_keeps_axes_distinct(self):
        ext = make_extension()
        ext._parameter_pad_axes = {"x": "mean_distance", "y": "measurement_accuracy"}
        ext._parameter_pad_axis_options["y"] = ext._parameter_pad_axis_options_for("y")
        ext._parameter_pad_axis_models["y"] = IntModel(
            ext._parameter_pad_axis_options["y"].index("seed_radius")
        )
        queued = []
        ext._queue_findsurface_window_refresh = lambda: queued.append(True)

        ext._on_parameter_pad_axis_changed("y")

        self.assertEqual(ext._parameter_pad_axes["y"], "seed_radius")
        self.assertNotEqual(ext._parameter_pad_axes["x"], ext._parameter_pad_axes["y"])
        self.assertNotIn(ext._parameter_pad_axes["y"], ext._parameter_pad_axis_options_for("x"))
        self.assertEqual(queued, [True])

    def test_parameter_pad_axis_change_queues_row_refresh_during_ui_event(self):
        ext = make_extension()
        ext._parameter_pad_axes = {"x": "mean_distance", "y": "measurement_accuracy"}
        ext._parameter_pad_axis_options["y"] = ext._parameter_pad_axis_options_for("y")
        ext._parameter_pad_axis_models["y"] = IntModel(
            ext._parameter_pad_axis_options["y"].index("seed_radius")
        )
        ext._parameter_pad_frame = UiContext()
        queued = []
        refreshed = []
        ext._queue_parameter_pad_row_refresh = lambda: queued.append(True)
        ext._refresh_parameter_pad_row = lambda: refreshed.append(True)

        ext._on_parameter_pad_axis_changed("y")

        self.assertEqual(ext._parameter_pad_axes["y"], "seed_radius")
        self.assertEqual(queued, [True])
        self.assertEqual(refreshed, [])

    def test_parameter_pad_drag_uses_current_axes_before_row_refresh(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        size = ext.PARAMETER_PAD_SIZE
        ext._parameter_pad_axes = {"x": "seed_radius", "y": "mean_distance"}
        ext._parameter_pad_rects["measurement_accuracy:mean_distance"] = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=size,
            computed_height=size,
        )
        old_accuracy = ext._models["measurement_accuracy"].as_float
        old_seed_radius = ext._models["seed_radius"].as_float

        ext._on_parameter_pad_pressed("measurement_accuracy", "mean_distance", size, 0)

        self.assertEqual(ext._active_parameter_pad, "seed_radius:mean_distance")
        self.assertEqual(ext._models["measurement_accuracy"].as_float, old_accuracy)
        self.assertNotEqual(ext._models["seed_radius"].as_float, old_seed_radius)

    def test_parameter_pad_handle_spacers_update_during_drag(self):
        ext = make_extension()
        horizontal = types.SimpleNamespace(width=0.0)
        vertical = types.SimpleNamespace(height=0.0)
        ext._parameter_pad_handle_spacers["measurement_accuracy:mean_distance"] = (horizontal, vertical)

        self.assertTrue(ext._update_parameter_pad_handle("measurement_accuracy", "mean_distance", 0.25, 0.75))

        expected = (ext.PARAMETER_PAD_SIZE - ext.PARAMETER_PAD_HANDLE_SIZE) * 0.25
        self.assertAlmostEqual(horizontal.width, expected)
        self.assertAlmostEqual(vertical.height, expected)

    def test_parameter_pad_handle_uses_pixel_lengths_when_available(self):
        ext = make_extension()
        previous_pixel = getattr(extension.ui, "Pixel", None)
        horizontal = types.SimpleNamespace(width=None)
        vertical = types.SimpleNamespace(height=None)
        ext._parameter_pad_handle_spacers["measurement_accuracy:mean_distance"] = (horizontal, vertical)
        try:
            extension.ui.Pixel = lambda value: ("px", value)

            self.assertTrue(ext._update_parameter_pad_handle("measurement_accuracy", "mean_distance", 0.5, 0.25))

            max_offset = ext.PARAMETER_PAD_SIZE - ext.PARAMETER_PAD_HANDLE_SIZE
            self.assertEqual(horizontal.width, ("px", max_offset * 0.5))
            self.assertEqual(vertical.height, ("px", max_offset * 0.75))
        finally:
            if previous_pixel is None:
                delattr(extension.ui, "Pixel")
            else:
                extension.ui.Pixel = previous_pixel

    def test_parameter_pad_value_labels_update_during_drag(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        ext._parameter_pad_value_labels = {"x": Label(), "y": Label()}

        self.assertTrue(ext._apply_parameter_pad_normalized("measurement_accuracy", "mean_distance", 0.5, 0.5))

        self.assertEqual(ext._parameter_pad_value_labels["x"].text, "0.0255")
        self.assertEqual(ext._parameter_pad_value_labels["y"].text, "0.0300")

    def test_parameter_pad_mouse_coordinates_clamp_to_panel(self):
        ext = make_extension()

        self.assertEqual(ext._parameter_pad_normalized_from_mouse(-10, 200, 100, 100), (0.0, 0.0))
        self.assertEqual(ext._parameter_pad_normalized_from_mouse(150, -25, 100, 100), (1.0, 1.0))

    def test_parameter_pad_handle_syncs_after_parameter_undo(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        ext._clear_dirty_tracking()
        horizontal = types.SimpleNamespace(width=0.0)
        vertical = types.SimpleNamespace(height=0.0)
        ext._parameter_pad_handle_spacers["mean_distance:measurement_accuracy"] = (horizontal, vertical)
        size = ext.PARAMETER_PAD_SIZE

        ext._on_parameter_pad_pressed("mean_distance", "measurement_accuracy", size, 0)
        ext._on_parameter_pad_released("mean_distance", "measurement_accuracy", size, 0)

        max_offset = ext.PARAMETER_PAD_SIZE - ext.PARAMETER_PAD_HANDLE_SIZE
        self.assertAlmostEqual(horizontal.width, max_offset)
        self.assertAlmostEqual(vertical.height, 0.0)
        self.assertEqual(len(ext._state.transaction_log), 1)

        ext._undo_last()

        expected_v = (0.003 - 0.001) / (0.05 - 0.001)
        self.assertAlmostEqual(horizontal.width, max_offset)
        self.assertAlmostEqual(vertical.height, (1.0 - expected_v) * max_offset)

    def test_parameter_pad_handle_syncs_while_slider_value_model_is_editing(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        horizontal = types.SimpleNamespace(width=0.0)
        vertical = types.SimpleNamespace(height=0.0)
        ext._parameter_pad_axes = {"x": "measurement_accuracy", "y": "mean_distance"}
        ext._parameter_pad_handle_spacers["measurement_accuracy:mean_distance"] = (horizontal, vertical)
        ext._models["measurement_accuracy"].editing = True

        ext._models["measurement_accuracy"].set_value(0.0255)
        ext._on_detection_parameter_value_changed("measurement_accuracy")

        max_offset = ext.PARAMETER_PAD_SIZE - ext.PARAMETER_PAD_HANDLE_SIZE
        self.assertAlmostEqual(horizontal.width, max_offset * 0.5)

    def test_parameter_pad_handle_syncs_after_range_slider_moves(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        horizontal = types.SimpleNamespace(width=0.0)
        vertical = types.SimpleNamespace(height=0.0)
        ext._parameter_pad_axes = {"x": "measurement_accuracy", "y": "mean_distance"}
        ext._parameter_pad_handle_spacers["measurement_accuracy:mean_distance"] = (horizontal, vertical)

        target_value = 0.0255
        index = ext._range_slider_index_for_value(target_value, 0.001, 0.05)
        ext._models["measurement_accuracy_slider_index"].set_value(index)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")

        max_offset = ext.PARAMETER_PAD_SIZE - ext.PARAMETER_PAD_HANDLE_SIZE
        self.assertAlmostEqual(horizontal.width, max_offset * 0.5)

    def test_parameter_pad_frame_refreshes_after_range_slider_moves(self):
        ext = make_extension()
        install_detection_parameter_pad_models(ext)
        built = []
        queued = []

        class Frame(UiContext):
            def __init__(self):
                self.clear_count = 0

            def clear(self):
                self.clear_count += 1

        frame = Frame()
        ext._parameter_pad_axes = {"x": "measurement_accuracy", "y": "mean_distance"}
        ext._parameter_pad_frame = frame
        ext._parameter_pad_row = lambda: built.append(True)
        ext._queue_parameter_pad_row_refresh = lambda: queued.append(True)

        target_value = 0.0255
        index = ext._range_slider_index_for_value(target_value, 0.001, 0.05)
        ext._models["measurement_accuracy_slider_index"].set_value(index)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")

        self.assertEqual(frame.clear_count, 0)
        self.assertEqual(built, [])
        self.assertEqual(queued, [True])

        ext._refresh_parameter_pad_row()

        self.assertEqual(frame.clear_count, 1)
        self.assertEqual(built, [True])

    def test_range_slider_parameter_change_updates_one_open_transaction(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        ext._models["measurement_accuracy_slider_index"].set_value(3)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")
        self.assertEqual(len(ext._state.transaction_log), 0)
        self.assertEqual(queued, [])

        ext._models["measurement_accuracy_slider_index"].set_value(7)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")

        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.008)
        self.assertEqual(len(ext._state.transaction_log), 0)

        ext._on_detection_parameter_edit_finished("measurement_accuracy_slider_index")

        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.event_type, detection.TRANSACTION_PARAMETER_CHANGE)
        self.assertEqual(transaction.state_before["measurement_accuracy"], 0.003)
        self.assertEqual(transaction.state_after["measurement_accuracy"], 0.008)
        self.assertEqual(queued, [True])

    def test_detection_type_undo_preserves_committed_slider_parameter(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["measurement_accuracy_slider_index"].set_value(7)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")
        ext._on_detection_parameter_edit_finished("measurement_accuracy_slider_index")
        ext._set_detection_type("Plane")

        self.assertEqual(len(ext._state.transaction_log), 2)
        self.assertEqual(ext._detection_type, "Plane")
        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.008)

        ext._undo_last()

        self.assertEqual(ext._detection_type, "Auto")
        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.008)

        ext._undo_last()

        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.003)
        self.assertEqual(ext._models["measurement_accuracy_slider_index"].as_int, 2)

    def test_range_slider_noop_edit_removes_open_parameter_transaction(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["measurement_accuracy_slider_index"].set_value(7)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")
        ext._models["measurement_accuracy_slider_index"].set_value(2)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")
        ext._on_detection_parameter_edit_finished("measurement_accuracy_slider_index")

        self.assertEqual(ext._state.transaction_log, [])
        self.assertFalse(ext._state.can_undo)

    def test_unobserved_range_slider_model_change_is_detected_and_saved(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)

        ext._models["measurement_accuracy_slider_index"].set_value(7)
        ext._sync_parameter_transaction_from_models(finalize=True)

        self.assertAlmostEqual(ext._models["measurement_accuracy"].as_float, 0.008)
        self.assertTrue(ext._is_dirty)
        self.assertTrue(ext._state.can_undo)
        self.assertEqual(queued, [True])
        self.assertAlmostEqual(ext._settings_snapshot()["measurement_accuracy"], 0.008)
        self.assertEqual(ext._settings_snapshot()["measurement_accuracy_slider_index"], 7)

    def test_unobserved_range_bounds_change_is_detected_and_saved(self):
        ext = make_extension()
        ext._models.update(
            {
                "seed_radius_min": FloatModel(0.05),
                "seed_radius": FloatModel(0.15),
                "seed_radius_max": FloatModel(0.50),
                "seed_radius_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["seed_radius_min"].set_value(0.10)
        ext._models["seed_radius_max"].set_value(0.70)
        ext._sync_parameter_transaction_from_models(finalize=True)

        self.assertTrue(ext._state.can_undo)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.state_before["seed_radius_min"], 0.05)
        self.assertEqual(transaction.state_after["seed_radius_min"], 0.10)
        self.assertEqual(transaction.state_after["seed_radius_max"], 0.70)
        self.assertEqual(ext._settings_snapshot()["seed_radius_min"], 0.10)
        self.assertEqual(ext._settings_snapshot()["seed_radius_max"], 0.70)

    def test_direct_range_value_edit_commits_and_restores_group_state(self):
        ext = make_extension()
        ext._models.update(
            {
                "mean_distance_min": FloatModel(0.01),
                "mean_distance": FloatModel(0.05),
                "mean_distance_max": FloatModel(0.10),
                "mean_distance_slider_index": IntModel(4),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["mean_distance"].set_value(0.08)
        ext._on_range_parameter_changed("mean_distance")
        ext._on_detection_parameter_edit_finished("mean_distance")

        self.assertEqual(len(ext._state.transaction_log), 1)
        self.assertAlmostEqual(ext._models["mean_distance"].as_float, 0.08)
        self.assertEqual(ext._models["mean_distance_slider_index"].as_int, 8)

        ext._undo_last()

        self.assertAlmostEqual(ext._models["mean_distance"].as_float, 0.05)
        self.assertAlmostEqual(ext._models["mean_distance_min"].as_float, 0.01)
        self.assertAlmostEqual(ext._models["mean_distance_max"].as_float, 0.10)
        self.assertEqual(ext._models["mean_distance_slider_index"].as_int, 4)

        ext._redo_last()

        self.assertAlmostEqual(ext._models["mean_distance"].as_float, 0.08)
        self.assertEqual(ext._models["mean_distance_slider_index"].as_int, 8)

    def test_direct_range_bounds_edit_commits_and_restores_group_state(self):
        ext = make_extension()
        ext._models.update(
            {
                "seed_radius_min": FloatModel(0.05),
                "seed_radius": FloatModel(0.15),
                "seed_radius_max": FloatModel(0.50),
                "seed_radius_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["seed_radius_min"].set_value(0.10)
        ext._models["seed_radius_max"].set_value(0.70)
        ext._on_range_endpoint_edit_finished("seed_radius_min")

        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.state_after["seed_radius_min"], 0.10)
        self.assertEqual(transaction.state_after["seed_radius_max"], 0.70)
        self.assertAlmostEqual(transaction.state_after["seed_radius"], ext._models["seed_radius"].as_float)
        self.assertNotEqual(transaction.state_after["seed_radius_slider_index"], 0)

        ext._undo_last()

        self.assertAlmostEqual(ext._models["seed_radius_min"].as_float, 0.05)
        self.assertAlmostEqual(ext._models["seed_radius"].as_float, 0.15)
        self.assertAlmostEqual(ext._models["seed_radius_max"].as_float, 0.50)
        self.assertEqual(ext._models["seed_radius_slider_index"].as_int, 2)

    def test_range_bounds_edit_adds_transaction_without_mutating_previous_transactions(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._models["measurement_accuracy_slider_index"].set_value(7)
        ext._on_range_parameter_changed("measurement_accuracy_slider_index")
        ext._on_detection_parameter_edit_finished("measurement_accuracy_slider_index")

        self.assertEqual(len(ext._state.transaction_log), 1)
        first_before = dict(ext._state.transaction_log[0].state_before)
        first_after = dict(ext._state.transaction_log[0].state_after)

        ext._range_edit_model("measurement_accuracy_min").set_value(0.002)
        ext._range_edit_model("measurement_accuracy_max").set_value(0.020)
        ext._on_range_endpoint_edit_finished("measurement_accuracy_min")

        self.assertEqual(len(ext._state.transaction_log), 2)
        self.assertEqual(ext._state.transaction_log[0].state_before, first_before)
        self.assertEqual(ext._state.transaction_log[0].state_after, first_after)
        self.assertEqual(ext._state.transaction_log[1].state_before, first_after)
        self.assertEqual(ext._state.transaction_log[1].state_after["measurement_accuracy_min"], 0.002)
        self.assertEqual(ext._state.transaction_log[1].state_after["measurement_accuracy_max"], 0.020)

    def test_range_bounds_drag_commits_once_without_noop_transaction(self):
        ext = make_extension()
        ext._models.update(
            {
                "measurement_accuracy_min": FloatModel(0.001),
                "measurement_accuracy": FloatModel(0.003),
                "measurement_accuracy_max": FloatModel(0.011),
                "measurement_accuracy_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()

        ext._on_parameter_control_pressed("measurement_accuracy_min")
        minimum_model = ext._range_edit_model("measurement_accuracy_min")
        minimum_model.set_value(0.0047)
        minimum_model.set_value(0.0048)
        ext._update_once()
        ext._update_once()

        self.assertEqual(ext._state.transaction_log, [])

        ext._on_detection_parameter_edit_finished("measurement_accuracy_min")
        ext._on_range_endpoint_edit_finished("measurement_accuracy_min")

        self.assertEqual(len(ext._state.transaction_log), 1)
        transaction = ext._state.transaction_log[0]
        self.assertEqual(transaction.event_type, detection.TRANSACTION_PARAMETER_CHANGE)
        self.assertNotEqual(transaction.state_before, transaction.state_after)
        self.assertEqual(transaction.state_after["measurement_accuracy_min"], 0.0048)

    def test_direct_range_text_edit_waits_until_edit_finished_to_commit(self):
        ext = make_extension()
        ext._models.update(
            {
                "seed_radius_min": FloatModel(0.05),
                "seed_radius": FloatModel(0.15),
                "seed_radius_max": FloatModel(0.50),
                "seed_radius_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()
        value_model = ext._range_edit_model("seed_radius")
        value_model.editing = True
        requests = []
        ext._request_auto_detect = lambda: requests.append(True)

        value_model.set_value(0.2)
        ext._on_detection_parameter_edit_finished("seed_radius")
        value_model.set_value(0.25)
        ext._on_detection_parameter_edit_finished("seed_radius")
        ext._update_once()
        ext._update_once()

        self.assertEqual(ext._state.transaction_log, [])
        self.assertEqual(requests, [])

        self.assertEqual(ext._models["seed_radius"].as_float, 0.15)

        value_model.editing = False
        ext._on_detection_parameter_edit_finished("seed_radius")

        self.assertEqual(len(ext._state.transaction_log), 1)
        self.assertEqual(requests, [True])
        self.assertEqual(ext._state.transaction_log[0].state_before["seed_radius"], 0.15)
        self.assertEqual(ext._state.transaction_log[0].state_after["seed_radius"], 0.25)

    def test_direct_range_text_draft_is_not_reset_when_model_does_not_report_editing(self):
        ext = make_extension()
        ext._models.update(
            {
                "seed_radius_min": FloatModel(0.05),
                "seed_radius": FloatModel(0.15),
                "seed_radius_max": FloatModel(0.50),
                "seed_radius_slider_index": IntModel(2),
            }
        )
        install_detection_parameter_models(ext)
        ext._sync_parameter_transaction_baseline()
        ext._clear_dirty_tracking()
        value_model = ext._range_edit_model("seed_radius")
        requests = []
        ext._request_auto_detect = lambda: requests.append(True)

        value_model.set_value(0.25)
        ext._update_once()
        ext._update_once()

        self.assertEqual(value_model.as_float, 0.25)
        self.assertEqual(ext._models["seed_radius"].as_float, 0.15)
        self.assertEqual(ext._state.transaction_log, [])
        self.assertEqual(requests, [])

        ext._on_detection_parameter_edit_finished("seed_radius")

        self.assertEqual(ext._models["seed_radius"].as_float, 0.25)
        self.assertEqual(len(ext._state.transaction_log), 1)
        self.assertEqual(requests, [True])

    def test_parameter_transaction_detail_shows_changed_values(self):
        ext = make_extension()
        transaction = detection.StateTransaction(
            detection.TRANSACTION_PARAMETER_CHANGE,
            0,
            0,
            state_before={
                "detection_type": "Auto",
                "measurement_accuracy": 0.003,
                "measurement_accuracy_slider_index": 2,
            },
            state_after={
                "detection_type": "Auto",
                "measurement_accuracy": 0.008,
                "measurement_accuracy_slider_index": 7,
            },
        )

        self.assertEqual(ext._transaction_title(3, transaction), "3. Parameter: Measurement Accuracy")
        self.assertEqual(ext._transaction_detail(transaction), "Measurement Accuracy: 0.003 -> 0.008")

    def test_workspace_load_restores_parameter_transaction_for_undo(self):
        ext = make_extension()
        install_detection_parameter_models(ext)
        ext._clear_dirty_tracking()
        ext._models["measurement_accuracy"].set_value(0.01)
        ext._on_detection_settings_changed("measurement_accuracy")

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "workspace.usda")

            self.assertTrue(ext._save_workspace_to_path(path))

            restored = make_extension()
            install_detection_parameter_models(restored)
            restored._load_workspace_from_path(path)

            self.assertEqual(restored._models["measurement_accuracy"].as_float, 0.01)
            self.assertTrue(restored._state.can_undo)

            restored._undo_last()

            self.assertEqual(restored._models["measurement_accuracy"].as_float, 0.003)
            self.assertTrue(restored._is_dirty)
            self.assertTrue(restored._state.can_redo)

    def test_export_geometries_writes_geometry_export_payload(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            parameters={
                "origin": (1.5, 0.0, 0.0),
                "x_axis": (1.0, 0.0, 0.0),
                "y_axis": (0.0, 1.0, 0.0),
                "z_axis": (0.0, 0.0, 1.0),
                "normal": (0.0, 0.0, 1.0),
                "width": 1.0,
                "height": 1.0,
            },
        )
        ext._state.apply_result(result)
        ext._export_include_visualization_meshes = True

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "geometries.usda")

            self.assertTrue(ext._export_geometries_to_path(path))
            payload = workspace._read_payload(path)

        self.assertEqual(payload["kind"], workspace.USD_KIND_GEOMETRY_EXPORT)
        self.assertTrue(payload["includes_visualization_meshes"])
        self.assertEqual(payload["results"][0]["id"], "Plane_001")
        self.assertEqual(payload["results"][0]["inlier_points"], [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        self.assertIn("visualization_mesh", payload["results"][0])
        self.assertGreater(len(payload["results"][0]["visualization_mesh"]["points"]), 0)

    def test_export_geometries_can_write_data_only_payload(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Sphere_001",
            type="Sphere",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1],
            active_generation=ext._state.generation,
            parameters={"center": (1.0, 0.0, 0.0), "radius": 1.0},
        )
        ext._state.apply_result(result)

        with TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "geometries.usda")

            self.assertTrue(ext._export_geometries_to_path(path))
            payload = workspace._read_payload(path)

        self.assertFalse(payload["includes_visualization_meshes"])
        self.assertNotIn("visualization_mesh", payload["results"][0])

    def test_geometry_visibility_toggles_mark_dirty_and_update_viewport(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()

        ext._toggle_geometry_mesh("Plane_001")
        ext._toggle_geometry_inliers("Plane_001")

        self.assertFalse(result.mesh_visible)
        self.assertFalse(result.inliers_visible)
        self.assertTrue(ext._is_dirty)

    def test_bulk_geometry_visibility_is_undoable_for_all_results(self):
        ext = make_extension()
        results = [
            surface_preview.SurfaceResult(
                id="Plane_001",
                type="Plane",
                seed_position=(0.0, 0.0, 0.0),
                seed_index=0,
                inlier_indices=[0],
                active_generation=ext._state.generation,
            ),
            surface_preview.SurfaceResult(
                id="Sphere_001",
                type="Sphere",
                seed_position=(1.0, 0.0, 0.0),
                seed_index=1,
                inlier_indices=[1],
                active_generation=ext._state.generation,
            ),
        ]
        for result in results:
            ext._state.apply_result(result)
        ext._sync_detection_surfaces()
        before_length = len(ext._state.transaction_log)

        ext._set_all_geometry_visibility("mesh_visible", False)

        self.assertTrue(all(not result.mesh_visible for result in results))
        self.assertEqual(len(ext._state.transaction_log), before_length + 1)
        self.assertEqual(ext._state.transaction_log[-1].event_type, detection.TRANSACTION_GEOMETRY_VISIBILITY)
        self.assertIsNone(ext._state.transaction_log[-1].result_id)

        ext._undo_last()

        self.assertTrue(all(result.mesh_visible for result in results))

        ext._redo_last()

        self.assertTrue(all(not result.mesh_visible for result in results))

        ext._set_all_geometry_visibility("inliers_visible", False)

        self.assertTrue(all(not result.inliers_visible for result in results))

    def test_empty_geometries_window_disables_header_controls(self):
        ext = make_extension()
        buttons = []
        previous = {
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Button": getattr(extension.ui, "Button", None),
            "Image": getattr(extension.ui, "Image", None),
            "Label": getattr(extension.ui, "Label", None),
            "ZStack": getattr(extension.ui, "ZStack", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "ScrollingFrame": getattr(extension.ui, "ScrollingFrame", None),
        }

        def make_button(label="", **kwargs):
            button = types.SimpleNamespace(label=label, kwargs=dict(kwargs), enabled=True)
            buttons.append(button)
            return button

        try:
            extension.ui.VStack = lambda *args, **kwargs: UiContext()
            extension.ui.HStack = lambda *args, **kwargs: UiContext()
            extension.ui.Spacer = lambda *args, **kwargs: None
            extension.ui.Button = make_button
            extension.ui.Image = None
            extension.ui.Label = lambda *args, **kwargs: None
            extension.ui.ZStack = None
            extension.ui.Rectangle = None
            extension.ui.ScrollingFrame = None
            ext._build_geometries_content = lambda: None

            ext._build_geometries_window()
        finally:
            self.restore_ui_stubs(previous)

        self.assertEqual(
            [button.kwargs.get("tooltip") for button in buttons],
            [
                "Show All Meshes",
                "Hide All Meshes",
                "Show All Inliers",
                "Hide All Inliers",
                "Expand all geometries",
                "Collapse all geometries",
            ],
        )
        self.assertTrue(all(button.kwargs.get("width") == 24 for button in buttons))
        self.assertTrue(all(button.kwargs.get("height") == 22 for button in buttons))
        self.assertTrue(all(button.enabled is False for button in buttons))

    def test_geometries_window_adds_bulk_visibility_controls_before_expand_controls(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        buttons = []
        previous = {
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Button": getattr(extension.ui, "Button", None),
            "Image": getattr(extension.ui, "Image", None),
            "Label": getattr(extension.ui, "Label", None),
            "ZStack": getattr(extension.ui, "ZStack", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "ScrollingFrame": getattr(extension.ui, "ScrollingFrame", None),
        }

        def make_button(label="", **kwargs):
            button = types.SimpleNamespace(label=label, kwargs=dict(kwargs), enabled=True)
            buttons.append(button)
            return button

        try:
            extension.ui.VStack = lambda *args, **kwargs: UiContext()
            extension.ui.HStack = lambda *args, **kwargs: UiContext()
            extension.ui.Spacer = lambda *args, **kwargs: None
            extension.ui.Button = make_button
            extension.ui.Image = None
            extension.ui.Label = lambda *args, **kwargs: None
            extension.ui.ZStack = None
            extension.ui.Rectangle = None
            extension.ui.ScrollingFrame = None
            ext._build_geometries_content = lambda: None

            ext._build_geometries_window()
        finally:
            self.restore_ui_stubs(previous)

        self.assertEqual(
            [button.kwargs.get("tooltip") for button in buttons[:6]],
            [
                "Show All Meshes",
                "Hide All Meshes",
                "Show All Inliers",
                "Hide All Inliers",
                "Expand all geometries",
                "Collapse all geometries",
            ],
        )
        self.assertTrue(all(button.kwargs.get("width") == 24 for button in buttons[:6]))
        self.assertTrue(all(button.kwargs.get("height") == 22 for button in buttons[:6]))
        self.assertTrue(all(button.enabled is True for button in buttons[:6]))

    def test_geometries_header_text_button_disables_frame_text_and_hit_area(self):
        ext = make_extension()
        buttons = []
        labels = []
        rectangles = []
        zstacks = []
        previous = {
            "ZStack": getattr(extension.ui, "ZStack", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "Label": getattr(extension.ui, "Label", None),
            "Button": getattr(extension.ui, "Button", None),
        }

        def make_zstack(*args, **kwargs):
            zstacks.append(dict(kwargs))
            return UiContext()

        def make_rectangle(**kwargs):
            rectangle = types.SimpleNamespace(enabled=True, kwargs=dict(kwargs))
            rectangles.append(rectangle)
            return rectangle

        def make_label(text="", **kwargs):
            label = types.SimpleNamespace(text=text, enabled=True, kwargs=dict(kwargs))
            labels.append(label)
            return label

        def make_button(label="", **kwargs):
            button = types.SimpleNamespace(label=label, enabled=True, kwargs=dict(kwargs))
            buttons.append(button)
            return button

        try:
            extension.ui.ZStack = make_zstack
            extension.ui.Rectangle = make_rectangle
            extension.ui.Label = make_label
            extension.ui.Button = make_button

            control = ext._geometries_header_text_button(
                "+",
                tooltip="Expand all geometries",
                clicked_fn=lambda: None,
                enabled=False,
            )
        finally:
            self.restore_ui_stubs(previous)

        self.assertIs(control._button, buttons[0])
        self.assertEqual(labels[0].text, "+")
        self.assertEqual(zstacks[0]["width"], 24)
        self.assertEqual(zstacks[0]["height"], 22)
        self.assertEqual(rectangles[0].kwargs["style_type_name_override"], "ToolBar.ButtonFrame")
        self.assertEqual(buttons[0].kwargs["style_type_name_override"], "ToolBar.ButtonHit")
        self.assertFalse(buttons[0].enabled)
        self.assertFalse(labels[0].enabled)
        self.assertFalse(rectangles[0].enabled)

    def test_geometries_content_uses_collapsable_frames_and_image_controls(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        buttons = []
        images = []
        rectangles = []
        frames = []
        vstacks = []
        previous = {
            "CollapsableFrame": getattr(extension.ui, "CollapsableFrame", None),
            "ZStack": getattr(extension.ui, "ZStack", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "Button": getattr(extension.ui, "Button", None),
            "Image": getattr(extension.ui, "Image", None),
            "Label": getattr(extension.ui, "Label", None),
        }

        def make_context(*args, **kwargs):
            return UiContext()

        def make_vstack(*args, **kwargs):
            vstacks.append(dict(kwargs))
            return UiContext()

        def make_zstack(*args, **kwargs):
            return UiContext()

        class CollapsableFrame(UiContext):
            def __init__(self, title, **kwargs):
                self.title = title
                self.kwargs = dict(kwargs)
                self.collapsed_changed_fn = None
                frames.append(self)

            def set_collapsed_changed_fn(self, callback):
                self.collapsed_changed_fn = callback

        def make_button(label="", **kwargs):
            button = types.SimpleNamespace(label=label, kwargs=dict(kwargs))
            buttons.append(button)
            return button

        def make_image(path, **kwargs):
            image = types.SimpleNamespace(source_url=path, image_url=path, kwargs=dict(kwargs))
            images.append(image)
            return image

        def make_rectangle(**kwargs):
            rectangles.append(dict(kwargs))
            return types.SimpleNamespace()

        try:
            extension.ui.CollapsableFrame = CollapsableFrame
            extension.ui.ZStack = make_zstack
            extension.ui.VStack = make_vstack
            extension.ui.HStack = make_context
            extension.ui.Spacer = lambda *args, **kwargs: None
            extension.ui.Rectangle = make_rectangle
            extension.ui.Button = make_button
            extension.ui.Image = make_image
            extension.ui.Label = lambda *args, **kwargs: None

            ext._build_geometries_content()
        finally:
            self.restore_ui_stubs(previous)

        labels = [button.label for button in buttons]
        image_urls = [image.source_url for image in images]
        fields = ext._geometry_result_fields(result)
        expected_item_height = (
            ext.GEOMETRY_ITEM_BUTTON_ROW_HEIGHT
            + len(fields) * ext.GEOMETRY_FIELD_ROW_HEIGHT
            + len(fields) * ext.GEOMETRY_ITEM_ROW_SPACING
        )

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].title, "Plane_001 (Plane)")
        self.assertEqual(frames[0].kwargs["collapsed"], False)
        self.assertEqual(frames[0].kwargs["height"], 0)
        self.assertIsNotNone(frames[0].collapsed_changed_fn)
        frames[0].collapsed_changed_fn(True)
        self.assertTrue(ext._is_geometry_collapsed("Plane_001"))
        self.assertNotIn("- Plane_001 (Plane)", labels)
        self.assertNotIn("+ Plane_001 (Plane)", labels)
        self.assertNotIn("Focus", labels)
        self.assertNotIn("Mesh On", labels)
        self.assertNotIn("Inliers On", labels)
        self.assertNotIn("Delete", labels)
        self.assertNotIn("Cancel", labels)
        self.assertTrue(any("center-focus.svg" in url for url in image_urls))
        self.assertTrue(any("visibility_mesh_on.svg" in url for url in image_urls))
        self.assertTrue(any("visibility_inliers_on.svg" in url for url in image_urls))
        self.assertTrue(any("delete.svg" in url for url in image_urls))
        self.assertTrue(any("arrow-back-up.svg" in url for url in image_urls))
        self.assertEqual(ext._geometry_item_height(fields, None, result.id), expected_item_height)
        self.assertIn({"height": 0, "spacing": 0}, vstacks)
        toolbar_rectangles = [
            rectangle for rectangle in rectangles if rectangle.get("style_type_name_override") == "ToolBar.ButtonFrame"
        ]
        field_rectangles = [
            rectangle
            for rectangle in rectangles
            if rectangle.get("style", {}).get("background_color") == ext._geometry_field_cell_style()["background_color"]
        ]
        self.assertTrue(toolbar_rectangles)
        self.assertTrue(field_rectangles)

    def test_collapsed_geometry_section_uses_collapsable_frame_without_border(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._geometry_collapsed = {"Plane_001": True}
        buttons = []
        rectangles = []
        frames = []
        previous = {
            "CollapsableFrame": getattr(extension.ui, "CollapsableFrame", None),
            "ZStack": getattr(extension.ui, "ZStack", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "Button": getattr(extension.ui, "Button", None),
            "Label": getattr(extension.ui, "Label", None),
        }

        class CollapsableFrame(UiContext):
            def __init__(self, title, **kwargs):
                self.title = title
                self.kwargs = dict(kwargs)
                self.collapsed_changed_fn = None
                frames.append(self)

            def set_collapsed_changed_fn(self, callback):
                self.collapsed_changed_fn = callback

        def make_button(label="", **kwargs):
            button = types.SimpleNamespace(label=label, kwargs=dict(kwargs))
            buttons.append(button)
            return button

        def make_rectangle(**kwargs):
            rectangles.append(dict(kwargs))
            return types.SimpleNamespace()

        try:
            extension.ui.CollapsableFrame = CollapsableFrame
            extension.ui.ZStack = lambda *args, **kwargs: UiContext()
            extension.ui.VStack = lambda *args, **kwargs: UiContext()
            extension.ui.HStack = lambda *args, **kwargs: UiContext()
            extension.ui.Spacer = lambda *args, **kwargs: None
            extension.ui.Rectangle = make_rectangle
            extension.ui.Button = make_button
            extension.ui.Label = lambda *args, **kwargs: None

            ext._build_geometries_content()
        finally:
            self.restore_ui_stubs(previous)

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].title, "Plane_001 (Plane)")
        self.assertEqual(frames[0].kwargs["collapsed"], True)
        self.assertIsNotNone(frames[0].collapsed_changed_fn)
        frames[0].collapsed_changed_fn(False)
        self.assertFalse(ext._is_geometry_collapsed("Plane_001"))
        self.assertNotIn("+ Plane_001 (Plane)", [button.label for button in buttons])
        self.assertTrue(
            all(rectangle.get("style", {}).get("border_color") != 0xFFFFFFFF for rectangle in rectangles)
        )

    def test_geometry_fields_render_scalar_and_vector_cells(self):
        ext = make_extension()
        labels = []
        hstacks = []
        rectangles = []
        previous = {
            "ZStack": getattr(extension.ui, "ZStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "Label": getattr(extension.ui, "Label", None),
        }

        def make_label(text="", **kwargs):
            labels.append((str(text), dict(kwargs)))
            return types.SimpleNamespace()

        def make_hstack(*args, **kwargs):
            hstacks.append(dict(kwargs))
            return UiContext()

        def make_rectangle(**kwargs):
            rectangles.append(dict(kwargs))
            return types.SimpleNamespace()

        try:
            extension.ui.ZStack = lambda *args, **kwargs: UiContext()
            extension.ui.HStack = make_hstack
            extension.ui.Rectangle = make_rectangle
            extension.ui.Label = make_label

            ext._build_geometry_fields([
                ext._geometry_scalar_field("Type", "Plane"),
                ext._geometry_vector_field("Position", (1.0, 2.0, 3.0)),
            ])
        finally:
            self.restore_ui_stubs(previous)

        label_texts = [text for text, _kwargs in labels]
        self.assertIn("Type", label_texts)
        self.assertIn("Plane", label_texts)
        self.assertIn("Position", label_texts)
        self.assertIn("X", label_texts)
        self.assertIn("Y", label_texts)
        self.assertIn("Z", label_texts)
        self.assertIn("1", label_texts)
        self.assertIn("2", label_texts)
        self.assertIn("3", label_texts)
        self.assertTrue(all(hstack.get("height") == ext.GEOMETRY_FIELD_ROW_HEIGHT for hstack in hstacks))
        self.assertTrue(any(kwargs.get("width") == ext.GEOMETRY_FIELD_LABEL_WIDTH for _text, kwargs in labels))
        self.assertTrue(
            any(
                rectangle.get("style", {}).get("background_color")
                == ext._geometry_field_cell_style()["background_color"]
                for rectangle in rectangles
            )
        )

    def test_geometry_visibility_toggle_is_undoable(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()

        ext._toggle_geometry_mesh("Plane_001")

        self.assertFalse(result.mesh_visible)
        self.assertEqual(ext._state.transaction_log[-1].event_type, detection.TRANSACTION_GEOMETRY_VISIBILITY)

        ext._undo_last()

        self.assertTrue(result.mesh_visible)
        self.assertTrue(ext._state.can_redo)

        ext._redo_last()

        self.assertFalse(result.mesh_visible)

    def test_geometry_header_hover_updates_viewport_highlight_state(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()

        ext._on_geometry_header_hovered("Plane_001", True)

        self.assertEqual(ext._hovered_geometry_id, "Plane_001")
        self.assertEqual(ext._viewport.selected_result_id, "Plane_001")

        ext._on_geometry_header_hovered("Plane_001", False)

        self.assertIsNone(ext._hovered_geometry_id)
        self.assertIsNone(ext._viewport.selected_result_id)

    def test_focus_geometry_result_fits_viewport_without_persistent_highlight(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()

        ext._focus_geometry_result("Plane_001")

        self.assertIsNone(ext._hovered_geometry_id)
        self.assertIsNone(ext._viewport.selected_result_id)
        self.assertEqual(ext._viewport.focused_result_id, "Plane_001")
        self.assertEqual(ext._status_message, "Focused geometry: Plane_001")

    def test_hovered_geometry_clears_when_result_is_removed(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()
        ext._on_geometry_header_hovered("Plane_001", True)

        ext._delete_geometry_result("Plane_001")

        self.assertIsNone(ext._hovered_geometry_id)
        self.assertIsNone(ext._viewport.selected_result_id)

    def test_geometry_histogram_bin_count_steps_by_odd_values_with_minimum(self):
        ext = make_extension()
        refreshes = []
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)

        self.assertEqual(ext._geometry_histogram_bin_count("Plane_001"), 35)

        ext._adjust_geometry_histogram_bins("Plane_001", 2)
        self.assertEqual(ext._geometry_histogram_bin_count("Plane_001"), 37)

        for _index in range(10):
            ext._adjust_geometry_histogram_bins("Plane_001", 2)
        self.assertEqual(ext._geometry_histogram_bin_count("Plane_001"), 47)

        for _index in range(20):
            ext._adjust_geometry_histogram_bins("Plane_001", -2)
        self.assertEqual(ext._geometry_histogram_bin_count("Plane_001"), 23)
        self.assertEqual(len(refreshes), 18)

    def test_geometry_histogram_bar_widths_fill_fixed_chart_width(self):
        ext = make_extension()

        for bin_count in (23, 35, 47):
            widths = ext._histogram_bar_widths(bin_count, ext.HISTOGRAM_CHART_WIDTH, ext.HISTOGRAM_BAR_SPACING)
            total_width = sum(widths) + ext.HISTOGRAM_BAR_SPACING * (bin_count - 1)
            middle_index = bin_count // 2
            middle_center = sum(widths[:middle_index]) + ext.HISTOGRAM_BAR_SPACING * middle_index + widths[middle_index] * 0.5

            self.assertEqual(len(widths), bin_count)
            self.assertAlmostEqual(total_width, ext.HISTOGRAM_CHART_WIDTH)
            self.assertAlmostEqual(middle_center, ext.HISTOGRAM_CHART_WIDTH * 0.5)

    def test_geometry_histogram_details_toggle_is_per_geometry(self):
        ext = make_extension()
        refreshes = []
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)

        self.assertFalse(ext._geometry_histogram_details_visible("Plane_001"))

        ext._toggle_geometry_histogram_details("Plane_001")

        self.assertTrue(ext._geometry_histogram_details_visible("Plane_001"))
        self.assertFalse(ext._geometry_histogram_details_visible("Sphere_001"))
        self.assertEqual(refreshes, [True])

    def test_geometry_histogram_display_offset_maps_chart_bounds(self):
        ext = make_extension()

        self.assertEqual(ext._histogram_display_offset(0.0), 0)
        self.assertEqual(ext._histogram_display_offset(1.0), ext.HISTOGRAM_CHART_WIDTH - 1)

    def test_geometry_histogram_bin_tooltip_summarizes_count_share(self):
        ext = make_extension()

        tooltip = ext._histogram_bin_tooltip(
            {
                "count": 51,
                "percent": 0.52,
                "center": 0.000086,
                "sigma_offset": 2.0,
            }
        )

        self.assertEqual(tooltip, "Count: 51pts. (0.52%)")

    def test_geometry_histogram_bin_tooltip_handles_zero_sigma_offset(self):
        ext = make_extension()

        tooltip = ext._histogram_bin_tooltip(
            {
                "count": 0,
                "percent": 0.0,
                "center": 0.0,
                "sigma_offset": None,
            }
        )

        self.assertIn("Count: 0pts. (0.00%)", tooltip)
        self.assertNotIn("Value:", tooltip)

    def test_geometry_histogram_status_hit_uses_chart_position_without_refresh(self):
        ext = make_extension()
        refreshes = []
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)
        chart = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=300.0,
            computed_height=70.0,
        )
        ext._histogram_status_regions = [
            {
                "chart": chart,
                "result_id": "Plane_001",
                "bins": (
                    {"bin_info": {"count": 1}, "display_x": 0.0, "width": 100.0},
                    {"bin_info": {"count": 2}, "display_x": 100.0, "width": 100.0},
                    {"bin_info": {"count": 3}, "display_x": 200.0, "width": 100.0},
                ),
            }
        ]

        hit = ext._histogram_status_hit_at(225.0, 60.0)

        self.assertEqual(hit["result_id"], "Plane_001")
        self.assertEqual(hit["bin_info"]["count"], 2)
        self.assertIsNone(ext._histogram_status_hit_at(99.0, 60.0))
        self.assertEqual(refreshes, [])

    def test_geometry_histogram_status_poll_updates_fixed_label_text(self):
        ext = make_extension()
        refreshes = []
        left_label = Label()
        right_label = Label()
        chart = types.SimpleNamespace(
            screen_position_x=10.0,
            screen_position_y=20.0,
            computed_width=300.0,
            computed_height=70.0,
        )
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)
        ext._viewport._poll_mouse_position = lambda: (35.0, 30.0)
        ext._histogram_status_labels = {"Plane_001": {"left": left_label, "right": right_label}}
        ext._histogram_status_regions = [
            {
                "chart": chart,
                "result_id": "Plane_001",
                "bins": (
                    {
                        "bin_info": {
                            "count": 7,
                            "percent": 12.5,
                            "center": 0.00042,
                            "sigma_offset": 1.0,
                        },
                        "display_x": 0.0,
                        "width": 50.0,
                    },
                ),
            }
        ]

        ext._poll_histogram_status()

        self.assertEqual(left_label.text, "Count: 7pts. (12.50%)")
        self.assertEqual(right_label.text, "")
        self.assertEqual(refreshes, [])

        ext._viewport._poll_mouse_position = lambda: (400.0, 30.0)
        ext._poll_histogram_status()

        self.assertEqual(left_label.text, "")
        self.assertEqual(right_label.text, "")
        self.assertEqual(refreshes, [])

    def test_geometry_histogram_tooltip_width_fits_content(self):
        ext = make_extension()

        short_width = ext._histogram_tooltip_width("Count: 1pts.")
        long_width = ext._histogram_tooltip_width("Count: 12,345pts. (100.00%)")

        self.assertLess(short_width, ext.HISTOGRAM_TOOLTIP_WIDTH)
        self.assertGreater(long_width, short_width)

    def test_geometry_histogram_tooltip_position_follows_mouse_inside_chart(self):
        ext = make_extension()

        self.assertEqual(ext._histogram_tooltip_left(60, 130), 65)
        self.assertEqual(ext._histogram_tooltip_top(10, 42), 15)
        self.assertLess(ext._histogram_tooltip_left(285, 130), 285)
        self.assertLess(ext._histogram_tooltip_top(65, 42), 65)

    def test_geometry_histogram_tooltip_styles_use_configured_colors(self):
        ext = make_extension()
        install_display_models(ext)
        ext._models["histogram_tooltip_background_a"].set_value(0.5)
        ext._models["histogram_tooltip_text_r"].set_value(0.2)
        ext._models["histogram_tooltip_text_g"].set_value(0.4)
        ext._models["histogram_tooltip_text_b"].set_value(0.6)

        self.assertEqual(ext._histogram_tooltip_box_style()["background_color"], 0x80FFFFFF)
        self.assertEqual(ext._histogram_tooltip_label_style()["color"], 0xFF996633)

    def test_geometry_histogram_bin_hover_tracks_result_specific_tooltip(self):
        ext = make_extension()
        refreshes = []
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)
        bin_info = {"start": 0.0, "end": 1.0, "count": 51, "center": 0.5}

        ext._on_histogram_bin_hovered(True, bin_info, "Plane_001", 2, 11, 30, 10)

        self.assertEqual(ext._hovered_histogram_result_id, "Plane_001")
        self.assertEqual(ext._hovered_histogram_bin["count"], 51)
        self.assertEqual(ext._hovered_histogram_display_index, 2)
        self.assertEqual(ext._hovered_histogram_mouse_x, 35.0)

        ext._on_histogram_bin_moved(bin_info, "Plane_001", 2, 11, 30, 10, None, 4, 20)

        self.assertEqual(ext._hovered_histogram_mouse_x, 34.0)
        self.assertEqual(ext._hovered_histogram_mouse_y, 20.0)

        ext._on_histogram_bin_hovered(False, bin_info, "Plane_001", 2, 11, 30, 10)

        self.assertIsNone(ext._hovered_histogram_bin)
        self.assertEqual(refreshes, [True, True, True])

    def test_scientific_metric_uses_two_significant_digits(self):
        ext = make_extension()

        self.assertEqual(ext._format_scientific_metric(0.0001234), "1.2e-04")
        self.assertEqual(ext._format_scientific_metric(-0.0456), "-4.6e-02")
        self.assertEqual(ext._format_scientific_metric(0.0), "0.0e+00")
        self.assertEqual(ext._format_scientific_metric(None), "n/a")

    def test_geometry_scroll_position_capture_and_restore_uses_scroll_y(self):
        ext = make_extension()
        scroll = types.SimpleNamespace(scroll_y=42.5)
        ext._geometries_scrolling_frame = scroll

        ext._capture_geometries_scroll_position()
        scroll.scroll_y = 0.0
        ext._restore_geometries_scroll_position()

        self.assertEqual(scroll.scroll_y, 42.5)

    def test_side_panel_minimum_width_is_applied_to_windows(self):
        ext = make_extension()
        window = types.SimpleNamespace()

        min_width = extension.FindSurfaceBootstrapExtension.SIDE_PANEL_MIN_WIDTH
        self.assertTrue(ext._set_window_minimum_size(window, min_width))

        self.assertEqual(window.min_width, min_width)
        self.assertEqual(window.minimum_width, min_width)

    def test_build_windows_uses_default_side_panel_width_and_hides_transactions(self):
        ext = make_extension()
        created = {}

        class Frame(UiContext):
            def __init__(self):
                self.build_fn = None

            def set_build_fn(self, value):
                self.build_fn = value

        class Window:
            def __init__(self, title, **kwargs):
                self.title = title
                self.width = kwargs.get("width")
                self.height = kwargs.get("height")
                self.flags = kwargs.get("flags")
                self.frame = Frame()
                self.visible = True
                created[title] = self

        original_window = getattr(extension.ui, "Window", None)
        original_workspace = getattr(extension.ui, "Workspace", None)
        original_no_scrollbar = getattr(extension.ui, "WINDOW_FLAGS_NO_SCROLLBAR", None)
        had_no_scrollbar = hasattr(extension.ui, "WINDOW_FLAGS_NO_SCROLLBAR")
        cls = extension.FindSurfaceBootstrapExtension
        patched_methods = {
            "_create_toolbar_window": cls._create_toolbar_window,
            "_build_toolbar": cls._build_toolbar,
            "_build_status_bar": cls._build_status_bar,
            "_build_viewport": cls._build_viewport,
            "_build_findsurface_window": cls._build_findsurface_window,
            "_build_settings_window": cls._build_settings_window,
            "_build_camera_window": cls._build_camera_window,
            "_build_geometries_window": cls._build_geometries_window,
            "_build_transactions_window": cls._build_transactions_window,
            "_build_tutorial_window": cls._build_tutorial_window,
            "_build_debug_group_box_window": cls._build_debug_group_box_window,
            "_diagnostic_group_box_window": cls._diagnostic_group_box_window,
            "_refresh_detection_panel": cls._refresh_detection_panel,
            "_refresh_toolbar_state": cls._refresh_toolbar_state,
            "_refresh_window_title": cls._refresh_window_title,
        }
        try:
            extension.ui.Window = Window
            extension.ui.Workspace = types.SimpleNamespace(set_show_window_fn=lambda *args, **kwargs: None)
            extension.ui.WINDOW_FLAGS_NO_SCROLLBAR = 1
            cls._create_toolbar_window = lambda self: Window(self.WINDOW_TOOLBAR, width=1200, height=44)
            cls._build_toolbar = lambda self: None
            cls._build_status_bar = lambda self: None
            cls._build_viewport = lambda self: None
            cls._build_findsurface_window = lambda self: None
            cls._build_settings_window = lambda self: None
            cls._build_camera_window = lambda self: None
            cls._build_geometries_window = lambda self: None
            cls._build_transactions_window = lambda self: None
            cls._build_tutorial_window = lambda self: None
            cls._build_debug_group_box_window = lambda self: None
            cls._diagnostic_group_box_window = lambda self: False
            cls._refresh_detection_panel = lambda self: None
            cls._refresh_toolbar_state = lambda self: None
            cls._refresh_window_title = lambda self: None

            ext._build_windows()
        finally:
            if original_window is None:
                delattr(extension.ui, "Window")
            else:
                extension.ui.Window = original_window
            if original_workspace is None:
                delattr(extension.ui, "Workspace")
            else:
                extension.ui.Workspace = original_workspace
            if had_no_scrollbar:
                extension.ui.WINDOW_FLAGS_NO_SCROLLBAR = original_no_scrollbar
            else:
                delattr(extension.ui, "WINDOW_FLAGS_NO_SCROLLBAR")
            for name, method in patched_methods.items():
                setattr(cls, name, method)

        side_windows = [
            extension.FindSurfaceBootstrapExtension.WINDOW_FINDSURFACE,
            extension.FindSurfaceBootstrapExtension.WINDOW_GEOMETRIES,
            extension.FindSurfaceBootstrapExtension.WINDOW_CAMERA,
            extension.FindSurfaceBootstrapExtension.WINDOW_SETTINGS,
            extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS,
        ]
        expected_width = extension.FindSurfaceBootstrapExtension.SIDE_PANEL_DEFAULT_WIDTH
        self.assertEqual(expected_width, 348)
        self.assertEqual(expected_width, extension.FindSurfaceBootstrapExtension.SIDE_PANEL_MIN_WIDTH)
        self.assertAlmostEqual(
            extension.FindSurfaceBootstrapExtension.SIDE_PANEL_DOCK_RATIO,
            (expected_width / extension.FindSurfaceBootstrapExtension.VIEWPORT_DEFAULT_WIDTH)
            * (expected_width / extension.FindSurfaceBootstrapExtension.SIDE_PANEL_MEASURED_WIDTH_AT_DEFAULT_RATIO),
        )
        self.assertEqual([created[title].width for title in side_windows], [expected_width] * len(side_windows))
        self.assertEqual([title for title in created if title in side_windows], side_windows)
        self.assertFalse(created[extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS].visible)

    def test_settings_window_places_picking_before_collapsed_color_group(self):
        ext = make_extension()
        ext._models["probe_radius"] = FloatModel(ext._viewport.probe_radius_px)
        events = []

        class BoolModel:
            def __init__(self, value):
                self.as_bool = bool(value)
                self.as_int = int(bool(value))

        class GroupContext:
            def __init__(self, title, **kwargs):
                self.title = title
                self.kwargs = dict(kwargs)

            def __enter__(self):
                events.append(("group", self.title, self.kwargs))
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class CollapsableFrame(GroupContext):
            def __init__(self, title, **kwargs):
                super().__init__(title, **kwargs)
                events.append(("collapsable", title, dict(kwargs)))

        class StackContext:
            def __init__(self, **kwargs):
                self.kwargs = dict(kwargs)

            def __enter__(self):
                events.append(("vstack", self.kwargs))
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        previous = {
            "SimpleBoolModel": getattr(extension.ui, "SimpleBoolModel", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Label": getattr(extension.ui, "Label", None),
            "CheckBox": getattr(extension.ui, "CheckBox", None),
            "CollapsableFrame": getattr(extension.ui, "CollapsableFrame", None),
        }
        original_bordered_group = extension.BorderedGroupView
        try:
            extension.ui.SimpleBoolModel = BoolModel
            extension.ui.VStack = lambda **kwargs: StackContext(**kwargs)
            extension.ui.HStack = lambda **kwargs: UiContext()
            extension.ui.Spacer = lambda **kwargs: None
            extension.ui.Label = lambda text, **kwargs: events.append(("label", text, dict(kwargs)))
            extension.ui.CheckBox = lambda **kwargs: events.append(("checkbox", dict(kwargs)))
            extension.ui.CollapsableFrame = CollapsableFrame
            extension.BorderedGroupView = GroupContext
            ext._float_row = lambda label, *args, **kwargs: events.append(("float", label, dict(kwargs)))
            ext._color_header = lambda *args, **kwargs: events.append(("color_header", dict(kwargs)))
            ext._color_controls = lambda label, prefix, **kwargs: events.append(("color", label, prefix))
            ext._sticky_preview_timeout_row = lambda: events.append(("sticky_timeout",))
            ext._subscribe_model = lambda name, callback: None

            ext._build_settings_window()
        finally:
            for name, value in previous.items():
                if value is None:
                    delattr(extension.ui, name)
                else:
                    setattr(extension.ui, name, value)
            extension.BorderedGroupView = original_bordered_group

        point_index = events.index(("label", "Point Rendering", {"height": 22}))
        size_index = next(index for index, event in enumerate(events) if event[:2] == ("float", "Size"))
        picking_index = next(index for index, event in enumerate(events) if event[:2] == ("group", "Picking"))
        colors_index = next(index for index, event in enumerate(events) if event[:2] == ("collapsable", "Colors"))
        color_stack_index = next(
            index for index, event in enumerate(events[colors_index + 1 :], start=colors_index + 1)
            if event[:1] == ("vstack",)
        )
        outlier_index = next(index for index, event in enumerate(events) if event[:2] == ("group", "Outlier Points"))

        self.assertLess(point_index, size_index)
        self.assertLess(size_index, picking_index)
        self.assertLess(picking_index, colors_index)
        self.assertLess(colors_index, color_stack_index)
        self.assertLess(color_stack_index, outlier_index)
        self.assertLess(colors_index, outlier_index)
        self.assertEqual(events[colors_index][2]["collapsed"], True)
        self.assertEqual(events[color_stack_index][1]["height"], 0)

    def test_delete_geometry_keeps_inliers_removed(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)

        ext._delete_geometry_result("Plane_001")

        self.assertEqual(ext._state.results, [])
        self.assertEqual(ext._state.active_mask, [True, False, False, True])
        self.assertEqual(ext._viewport.active_mask, [True, False, False, True])
        self.assertEqual(ext._viewport.surfaces, [])
        self.assertTrue(ext._is_dirty)

    def test_cancel_geometry_restores_inliers(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)

        ext._cancel_geometry_result("Plane_001")

        self.assertEqual(ext._state.results, [])
        self.assertEqual(ext._state.active_mask, [True, True, True, True])
        self.assertEqual(ext._viewport.active_mask, [True, True, True, True])
        self.assertTrue(ext._is_dirty)

    def test_delete_geometry_button_requests_confirmation_before_mutating(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()
        windows, buttons, previous = self.install_geometry_dialog_stubs(ext)
        try:
            ext._request_delete_geometry_result("Plane_001")

            self.assertEqual([window.title for window in windows], ["Delete Geometry"])
            self.assertEqual(ext._state.results, [result])
            self.assertEqual(ext._state.active_mask, [True, False, False, True])
            self.assertFalse(ext._is_dirty)
            self.assertIn("confirmation", ext._status_label.text)

            delete_button = next(button for button in buttons if button.label == "Delete")
            delete_button.clicked_fn()

            self.assertIsNone(ext._geometry_action_dialog)
            self.assertFalse(windows[0].visible)
            self.assertEqual(ext._state.results, [])
            self.assertEqual(ext._state.active_mask, [True, False, False, True])
            self.assertTrue(ext._is_dirty)
            self.assertIn("Deleted geometry: Plane_001", ext._status_label.text)
        finally:
            self.restore_ui_stubs(previous)

    def test_cancel_geometry_button_restores_inliers_after_confirmation(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        ext._sync_detection_surfaces()
        windows, buttons, previous = self.install_geometry_dialog_stubs(ext)
        try:
            ext._request_cancel_geometry_result("Plane_001")

            self.assertEqual([window.title for window in windows], ["Cancel Detection"])
            self.assertEqual(ext._state.results, [result])
            self.assertEqual(ext._state.active_mask, [True, False, False, True])

            cancel_button = next(button for button in buttons if button.label == "Cancel Detection")
            cancel_button.clicked_fn()

            self.assertIsNone(ext._geometry_action_dialog)
            self.assertFalse(windows[0].visible)
            self.assertEqual(ext._state.results, [])
            self.assertEqual(ext._state.active_mask, [True, True, True, True])
            self.assertTrue(ext._is_dirty)
            self.assertIn("Canceled detection: Plane_001", ext._status_label.text)
        finally:
            self.restore_ui_stubs(previous)

    def test_geometry_action_confirmation_can_be_dismissed(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._state.apply_result(result)
        windows, buttons, previous = self.install_geometry_dialog_stubs(ext)
        try:
            ext._request_delete_geometry_result("Plane_001")
            keep_button = next(button for button in buttons if button.label == "Keep Geometry")
            keep_button.clicked_fn()

            self.assertIsNone(ext._geometry_action_dialog)
            self.assertFalse(windows[0].visible)
            self.assertEqual(ext._state.results, [result])
            self.assertEqual(ext._state.active_mask, [True, False, False, True])
            self.assertFalse(ext._is_dirty)
            self.assertIn("Geometry action canceled.", ext._status_label.text)
        finally:
            self.restore_ui_stubs(previous)

    def test_dirty_guard_defers_action_until_discard(self):
        ext = make_extension()
        ext._is_dirty = True
        calls = []
        dialogs = []
        ext._show_unsaved_changes_dialog = lambda label, action: dialogs.append((label, action))

        guarded = ext._guard_unsaved_changes("import another point cloud", lambda: calls.append("ran"))

        self.assertFalse(guarded)
        self.assertEqual(calls, [])
        self.assertEqual(dialogs[0][0], "import another point cloud")

    def test_discard_unsaved_changes_runs_pending_action(self):
        ext = make_extension()
        ext._is_dirty = True
        calls = []
        ext._pending_unsaved_action = lambda: calls.append("ran")

        ext._discard_unsaved_changes()

        self.assertFalse(ext._is_dirty)
        self.assertEqual(calls, ["ran"])
        self.assertIsNone(ext._pending_unsaved_action)

    def test_dirty_state_is_visible_in_toolbar_dataset_and_title_only(self):
        ext = make_extension()

        ext._set_dirty(True)

        self.assertEqual(ext._dirty_label.text, "")
        self.assertEqual(ext._dataset_label.text, "cloud.xyz *")
        self.assertTrue(ext._save_button.enabled)

    def test_app_window_title_tracks_workspace_filename_and_dirty_state(self):
        ext = make_extension()
        viewport_window = types.SimpleNamespace(title="Viewport", name="Viewport")
        ext._windows = {extension.FindSurfaceBootstrapExtension.WINDOW_VIEWPORT: viewport_window}
        app_titles = []
        app_window = types.SimpleNamespace(set_title=lambda title: app_titles.append(title))
        appwindow_module = types.ModuleType("omni.appwindow")
        appwindow_module.get_default_app_window = lambda: app_window
        previous_appwindow_module = sys.modules.get("omni.appwindow")
        previous_omni_appwindow = getattr(extension.omni, "appwindow", None)
        previous_omni_path = getattr(extension.omni, "__path__", None)
        try:
            extension.omni.__path__ = []
            sys.modules["omni.appwindow"] = appwindow_module
            extension.omni.appwindow = appwindow_module
            ext._workspace_path = r"C:\tmp\workspace.usda"

            ext._set_dirty(True)

            self.assertEqual(app_titles[-1], "FindSurface Omniverse v1.0.0: workspace.usda*")
            self.assertEqual(viewport_window.title, "Viewport")
            self.assertEqual(viewport_window.name, "Viewport")

            ext._set_dirty(False)

            self.assertEqual(app_titles[-1], "FindSurface Omniverse v1.0.0: workspace.usda")
            self.assertEqual(viewport_window.title, "Viewport")
            self.assertEqual(viewport_window.name, "Viewport")
        finally:
            if previous_appwindow_module is None:
                sys.modules.pop("omni.appwindow", None)
            else:
                sys.modules["omni.appwindow"] = previous_appwindow_module
            if previous_omni_appwindow is None:
                try:
                    delattr(extension.omni, "appwindow")
                except AttributeError:
                    pass
            else:
                extension.omni.appwindow = previous_omni_appwindow
            if previous_omni_path is None:
                try:
                    delattr(extension.omni, "__path__")
                except AttributeError:
                    pass
            else:
                extension.omni.__path__ = previous_omni_path

    def test_app_window_title_updates_native_window_when_available(self):
        ext = make_extension()
        native_window = object()
        native_titles = []
        fallback_titles = []

        class Windowing:
            def set_window_title(self, window, title):
                native_titles.append((window, title))

        app_window = types.SimpleNamespace(
            get_window=lambda: native_window,
            set_title=lambda title: fallback_titles.append(title),
        )
        appwindow_module = types.ModuleType("omni.appwindow")
        appwindow_module.get_default_app_window = lambda: app_window
        windowing_module = types.ModuleType("carb.windowing")
        windowing_module.acquire_windowing_interface = lambda: Windowing()
        previous_appwindow_module = sys.modules.get("omni.appwindow")
        previous_windowing_module = sys.modules.get("carb.windowing")
        previous_omni_appwindow = getattr(extension.omni, "appwindow", None)
        previous_omni_path = getattr(extension.omni, "__path__", None)
        previous_carb_windowing = getattr(extension.carb, "windowing", None)
        previous_carb_path = getattr(extension.carb, "__path__", None)
        try:
            extension.omni.__path__ = []
            extension.carb.__path__ = []
            sys.modules["omni.appwindow"] = appwindow_module
            sys.modules["carb.windowing"] = windowing_module
            extension.omni.appwindow = appwindow_module
            ext._workspace_path = r"C:\tmp\workspace.usda"

            ext._set_dirty(True)

            self.assertEqual(
                native_titles[-1],
                (native_window, "FindSurface Omniverse v1.0.0: workspace.usda*"),
            )
            self.assertEqual(fallback_titles, [])
        finally:
            if previous_appwindow_module is None:
                sys.modules.pop("omni.appwindow", None)
            else:
                sys.modules["omni.appwindow"] = previous_appwindow_module
            if previous_windowing_module is None:
                sys.modules.pop("carb.windowing", None)
            else:
                sys.modules["carb.windowing"] = previous_windowing_module
            if previous_omni_appwindow is None:
                try:
                    delattr(extension.omni, "appwindow")
                except AttributeError:
                    pass
            else:
                extension.omni.appwindow = previous_omni_appwindow
            if previous_omni_path is None:
                try:
                    delattr(extension.omni, "__path__")
                except AttributeError:
                    pass
            else:
                extension.omni.__path__ = previous_omni_path
            if previous_carb_windowing is None:
                try:
                    delattr(extension.carb, "windowing")
                except AttributeError:
                    pass
            else:
                extension.carb.windowing = previous_carb_windowing
            if previous_carb_path is None:
                try:
                    delattr(extension.carb, "__path__")
                except AttributeError:
                    pass
            else:
                extension.carb.__path__ = previous_carb_path

    def test_status_bar_shows_latest_action_without_feature_or_preview_summary(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoSelected_Sphere_001",
            type="Sphere",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=ext._selected_index,
            inlier_indices=[0, 1],
            active_generation=ext._state.generation,
            rms_error=0.02,
            parameters={"radius": 1.5},
        )
        ext._detection_type = "Auto"
        ext._auto_detect_result = preview
        ext._auto_detect_source = "selected"

        ext._set_status("Ready")

        self.assertEqual(ext._status_label.text, "Ready")
        self.assertNotIn("Feature: Auto", ext._status_label.text)
        self.assertNotIn("Auto: Sphere", ext._status_label.text)
        self.assertNotIn("r=1.5", ext._status_label.text)
        self.assertNotIn("rms=0.02", ext._status_label.text)

    def test_status_bar_uses_concise_auto_preview_action(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoSelected_Sphere_001",
            type="Sphere",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=ext._selected_index,
            inlier_indices=[0, 1],
            active_generation=ext._state.generation,
            rms_error=0.02,
            parameters={"radius": 1.5},
        )
        ext._auto_detect_result = preview
        ext._auto_detect_source = "selected"

        ext._set_status(ext._detection_result_status("Auto preview", preview))

        self.assertEqual(ext._status_label.text, "Auto preview AutoSelected_Sphere_001")
        self.assertNotIn("Auto: Sphere", ext._status_label.text)
        self.assertNotIn("rms=0.02", ext._status_label.text)

    def test_shutdown_releases_scene_resources_when_app_is_quitting(self):
        ext = make_extension()
        calls = []

        class ShutdownViewport:
            def release_scene_resources(self, clear_scene=True):
                calls.append(("release", clear_scene))

            def destroy(self, clear_scene=True):
                calls.append(("destroy", clear_scene))

        ext._viewport = ShutdownViewport()
        ext._app_shutting_down = True

        ext._release_runtime_resources_for_shutdown()
        ext._destroy_runtime_resources_for_shutdown()

        self.assertEqual(calls, [("release", True), ("destroy", True)])

    def test_model_subscription_cleanup_unsubscribes_before_clearing(self):
        ext = make_extension()
        calls = []

        ext._model_subscriptions = [
            types.SimpleNamespace(unsubscribe=lambda: calls.append("unsubscribe")),
            types.SimpleNamespace(reset=lambda: calls.append("reset")),
            object(),
        ]

        ext._clear_model_subscriptions()

        self.assertEqual(calls, ["unsubscribe", "reset"])
        self.assertEqual(ext._model_subscriptions, [])

    def test_shutdown_clears_ui_frames_before_releasing_viewport_references(self):
        ext = make_extension()
        calls = []

        class Frame:
            def set_build_fn(self, value):
                calls.append(("set_build_fn", value))

            def clear(self):
                calls.append(("clear",))

        class Window:
            def __init__(self):
                self.frame = Frame()
                self.visible = True

            def destroy(self):
                calls.append(("destroy_window",))

        class ShutdownViewport:
            def release_scene_resources(self, clear_scene=True):
                calls.append(("release", clear_scene))

            def destroy(self, clear_scene=True):
                calls.append(("destroy_viewport", clear_scene))

        original_workspace = getattr(extension.ui, "Workspace", None)
        original_spacer = getattr(extension.ui, "Spacer", None)
        try:
            extension.ui.Workspace = types.SimpleNamespace(
                set_show_window_fn=lambda title, value: calls.append(("show_fn", title, value))
            )
            extension.ui.Spacer = lambda **kwargs: calls.append(("spacer", kwargs))
            ext._viewport = ShutdownViewport()
            ext._windows = {"Viewport": Window()}

            ext.on_shutdown()
        finally:
            if original_workspace is None:
                delattr(extension.ui, "Workspace")
            else:
                extension.ui.Workspace = original_workspace
            if original_spacer is None:
                delattr(extension.ui, "Spacer")
            else:
                extension.ui.Spacer = original_spacer

        self.assertIn(("set_build_fn", None), calls)
        self.assertIn(("clear",), calls)
        self.assertIn(("destroy_viewport", True), calls)
        self.assertLess(calls.index(("clear",)), calls.index(("destroy_viewport", True)))
        self.assertLess(calls.index(("destroy_viewport", True)), calls.index(("destroy_window",)))

    def test_background_coroutines_hold_only_weak_extension_reference(self):
        def make_background_coroutines():
            ext = make_extension()
            ref = weakref.ref(ext)
            return (
                extension._run_update_loop(ref),
                extension._dock_windows_after_update(ref),
                extension._refresh_geometries_window_after_update(ref),
                ref,
            )

        update_loop, dock_windows, refresh_geometries, ref = make_background_coroutines()
        try:
            gc.collect()
            self.assertIsNone(ref())
        finally:
            update_loop.close()
            dock_windows.close()
            refresh_geometries.close()

    def test_toolbar_state_marks_selected_detection_and_projection(self):
        ext = make_extension()
        ext._toolbar_detection_buttons = {name: Button() for name in detection.DETECTION_TYPES}
        ext._toolbar_projection_buttons = {
            extension.PROJECTION_ORTHOGRAPHIC: Button(),
            extension.PROJECTION_PERSPECTIVE: Button(),
        }

        ext._set_detection_type("Sphere")
        ext._set_projection_mode(extension.PROJECTION_PERSPECTIVE)

        self.assertTrue(ext._toolbar_detection_buttons["Sphere"].selected)
        self.assertFalse(ext._toolbar_detection_buttons["Plane"].selected)
        self.assertTrue(ext._toolbar_projection_buttons[extension.PROJECTION_PERSPECTIVE].selected)
        self.assertFalse(ext._toolbar_projection_buttons[extension.PROJECTION_ORTHOGRAPHIC].selected)

    def test_tutorial_toolbar_button_is_disabled_while_overlay_visible(self):
        ext = make_extension()
        ext._windows[extension.FindSurfaceBootstrapExtension.WINDOW_TUTORIAL] = types.SimpleNamespace(visible=False)

        ext._refresh_toolbar_state()
        self.assertTrue(ext._tutorial_button.enabled)

        ext._show_tutorial_overlay()
        self.assertFalse(ext._tutorial_button.enabled)

        ext._toggle_window(extension.FindSurfaceBootstrapExtension.WINDOW_TUTORIAL)
        self.assertTrue(ext._tutorial_button.enabled)

    def test_tutorial_window_uses_document_style_sections(self):
        ext = make_extension()
        labels = []
        rectangles = []
        zstacks = []
        spacers = []
        previous = {
            "ZStack": getattr(extension.ui, "ZStack", None),
            "VStack": getattr(extension.ui, "VStack", None),
            "HStack": getattr(extension.ui, "HStack", None),
            "Spacer": getattr(extension.ui, "Spacer", None),
            "Rectangle": getattr(extension.ui, "Rectangle", None),
            "Label": getattr(extension.ui, "Label", None),
        }

        def make_context(*args, **kwargs):
            return UiContext()

        def make_zstack(*args, **kwargs):
            zstacks.append(dict(kwargs))
            return UiContext()

        def make_rectangle(**kwargs):
            rectangles.append(dict(kwargs))
            return types.SimpleNamespace()

        try:
            extension.ui.ZStack = make_zstack
            extension.ui.VStack = make_context
            extension.ui.HStack = make_context
            extension.ui.Spacer = lambda *args, **kwargs: spacers.append(dict(kwargs))
            extension.ui.Rectangle = make_rectangle
            extension.ui.Label = lambda text, **kwargs: labels.append((text, dict(kwargs)))

            ext._build_tutorial_window()
        finally:
            self.restore_ui_stubs(previous)

        label_text = [text for text, _kwargs in labels]
        self.assertIn("Mouse", label_text)
        self.assertIn("Detection Workflow", label_text)
        self.assertIn("Keyboard", label_text)
        self.assertIn("Orbit / Roll", label_text)
        self.assertIn("Capture", label_text)
        self.assertIn("Types", label_text)
        self.assertEqual(len(zstacks), 3)
        self.assertEqual(
            [kwargs.get("style") for kwargs in rectangles],
            [ext._tutorial_section_style()] * 3,
        )
        self.assertEqual(
            sum(1 for kwargs in spacers if kwargs.get("width") == ext.TUTORIAL_SECTION_HORIZONTAL_PADDING),
            6,
        )

    def test_hide_dock_tab_bar_turns_off_tab_visibility(self):
        ext = make_extension()
        window = types.SimpleNamespace(dock_tab_bar_visible=True)

        self.assertTrue(ext._hide_dock_tab_bar(window))

        self.assertFalse(window.dock_tab_bar_visible)

    def test_viewport_tab_bar_is_hidden_once_by_default(self):
        ext = make_extension()
        window = types.SimpleNamespace(dock_tab_bar_visible=True)
        ext._windows = {extension.FindSurfaceBootstrapExtension.WINDOW_VIEWPORT: window}

        ext._hide_viewport_tab_bar_by_default()
        window.dock_tab_bar_visible = True
        ext._hide_viewport_tab_bar_by_default()

        self.assertTrue(ext._viewport_tab_bar_hidden_by_default)
        self.assertTrue(window.dock_tab_bar_visible)

    def test_initial_docking_focuses_findsurface_tab(self):
        ext = make_extension()
        previous_dock_position = getattr(extension.ui, "DockPosition", None)
        extension.ui.DockPosition = types.SimpleNamespace(TOP="top", BOTTOM="bottom", RIGHT="right", SAME="same")
        calls = []

        class Window:
            def __init__(self, name):
                self.name = name
                self.dock_tab_bar_visible = True

            def dock_in(self, target, position, ratio):
                calls.append(("dock", self.name, getattr(target, "name", None), position, ratio))

            def focus(self):
                calls.append(("focus", self.name))

        try:
            ext._windows = {
                extension.FindSurfaceBootstrapExtension.WINDOW_TOOLBAR: Window("Toolbar"),
                extension.FindSurfaceBootstrapExtension.WINDOW_STATUS_BAR: Window("Status Bar"),
                extension.FindSurfaceBootstrapExtension.WINDOW_VIEWPORT: Window("Viewport"),
                extension.FindSurfaceBootstrapExtension.WINDOW_FINDSURFACE: Window("FindSurface"),
                extension.FindSurfaceBootstrapExtension.WINDOW_SETTINGS: Window("Settings"),
                extension.FindSurfaceBootstrapExtension.WINDOW_CAMERA: Window("Camera"),
                extension.FindSurfaceBootstrapExtension.WINDOW_GEOMETRIES: Window("Geometries"),
                extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS: Window("Transactions"),
            }

            ext._dock_windows_now()

            self.assertIn(("focus", "FindSurface"), calls)
            self.assertFalse(
                ext._windows[extension.FindSurfaceBootstrapExtension.WINDOW_VIEWPORT].dock_tab_bar_visible
            )
            self.assertIn(
                (
                    "dock",
                    "FindSurface",
                    "Viewport",
                    "right",
                    extension.FindSurfaceBootstrapExtension.SIDE_PANEL_DOCK_RATIO,
                ),
                calls,
            )
            self.assertGreater(
                calls.index(("focus", "FindSurface")),
                calls.index(("dock", "Transactions", "FindSurface", "same", 0.5)),
            )
            self.assertLess(
                calls.index(("dock", "Geometries", "FindSurface", "same", 0.5)),
                calls.index(("dock", "Camera", "FindSurface", "same", 0.5)),
            )
            self.assertLess(
                calls.index(("dock", "Camera", "FindSurface", "same", 0.5)),
                calls.index(("dock", "Settings", "FindSurface", "same", 0.5)),
            )
            self.assertLess(
                calls.index(("dock", "Settings", "FindSurface", "same", 0.5)),
                calls.index(("dock", "Transactions", "FindSurface", "same", 0.5)),
            )
        finally:
            if previous_dock_position is None:
                delattr(extension.ui, "DockPosition")
            else:
                extension.ui.DockPosition = previous_dock_position

    def test_showing_transactions_redocks_it_as_side_panel_tab(self):
        ext = make_extension()
        previous_dock_position = getattr(extension.ui, "DockPosition", None)
        extension.ui.DockPosition = types.SimpleNamespace(SAME="same")
        calls = []

        class Window:
            def __init__(self, name, visible=True):
                self.name = name
                self.visible = visible

            def dock_in(self, target, position, ratio):
                calls.append(("dock", self.name, getattr(target, "name", None), position, ratio))

            def focus(self):
                calls.append(("focus", self.name))

        try:
            ext._windows = {
                extension.FindSurfaceBootstrapExtension.WINDOW_FINDSURFACE: Window("FindSurface"),
                extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS: Window("Transactions", visible=False),
            }
            ext._queue_side_panel_tab_dock = lambda title: calls.append(("queue", title))

            ext._toggle_window(extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS)

            self.assertTrue(ext._windows[extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS].visible)
            self.assertIn(("dock", "Transactions", "FindSurface", "same", 0.5), calls)
            self.assertIn(("focus", "Transactions"), calls)
            self.assertIn(("queue", extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS), calls)
        finally:
            if previous_dock_position is None:
                delattr(extension.ui, "DockPosition")
            else:
                extension.ui.DockPosition = previous_dock_position

    def test_initial_hidden_transactions_dock_restores_hidden_state(self):
        ext = make_extension()
        previous_dock_position = getattr(extension.ui, "DockPosition", None)
        extension.ui.DockPosition = types.SimpleNamespace(SAME="same")
        calls = []

        class Window:
            def __init__(self, name, visible=True):
                self.name = name
                self.visible = visible

            def dock_in(self, target, position, ratio):
                calls.append(("dock", self.name, getattr(target, "name", None), position, ratio, self.visible))

        try:
            transactions = Window("Transactions", visible=False)
            ext._windows = {
                extension.FindSurfaceBootstrapExtension.WINDOW_FINDSURFACE: Window("FindSurface"),
                extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS: transactions,
            }

            self.assertTrue(ext._dock_side_panel_tab(extension.FindSurfaceBootstrapExtension.WINDOW_TRANSACTIONS))

            self.assertFalse(transactions.visible)
            self.assertEqual(calls, [("dock", "Transactions", "FindSurface", "same", 0.5, True)])
        finally:
            if previous_dock_position is None:
                delattr(extension.ui, "DockPosition")
            else:
                extension.ui.DockPosition = previous_dock_position

    def test_global_visibility_toggle_updates_viewport_and_dirty_state(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}

        ext._toggle_global_visibility("outliers")
        ext._toggle_global_visibility("meshes")
        ext._toggle_global_visibility("inliers")

        self.assertFalse(ext._viewport.outlier_points_visible)
        self.assertFalse(ext._viewport.surface_meshes_visible)
        self.assertFalse(ext._viewport.inlier_points_visible)
        self.assertTrue(ext._is_dirty)
        self.assertIn("visibility_outliers_off", ext._visibility_buttons["outliers"].image_url)
        self.assertIn("visibility_mesh_off", ext._visibility_buttons["meshes"].image_url)
        self.assertIn("visibility_inliers_off", ext._visibility_buttons["inliers"].image_url)
        self.assertFalse(ext._visibility_buttons["outliers"].selected)
        self.assertFalse(ext._visibility_buttons["meshes"].selected)
        self.assertFalse(ext._visibility_buttons["inliers"].selected)
        self.assertFalse(ext._visibility_buttons["outliers"].checked)
        self.assertFalse(ext._visibility_buttons["meshes"].checked)
        self.assertFalse(ext._visibility_buttons["inliers"].checked)

    def test_global_visibility_toggle_is_undoable_without_content_dirty(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
        ext._clear_dirty_tracking()

        ext._toggle_global_visibility("outliers")

        self.assertFalse(ext._viewport.outlier_points_visible)
        self.assertTrue(ext._is_dirty)
        self.assertEqual(ext._state.transaction_log[-1].event_type, detection.TRANSACTION_GLOBAL_VISIBILITY)

        ext._undo_last()

        self.assertTrue(ext._viewport.outlier_points_visible)
        self.assertFalse(ext._is_dirty)
        self.assertTrue(ext._state.can_redo)

        ext._redo_last()

        self.assertFalse(ext._viewport.outlier_points_visible)
        self.assertTrue(ext._is_dirty)

    def test_display_dirty_state_clears_when_returned_to_saved_visibility(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
        ext._clear_dirty_tracking()

        ext._toggle_global_visibility("outliers")

        self.assertTrue(ext._is_dirty)

        ext._toggle_global_visibility("outliers")

        self.assertFalse(ext._is_dirty)

    def test_display_dirty_state_does_not_clear_content_dirty(self):
        ext = make_extension()
        ext._visibility_buttons = {"outliers": Button(), "meshes": Button(), "inliers": Button()}
        ext._clear_dirty_tracking()
        ext._apply_dirty_scope("content")

        ext._toggle_global_visibility("outliers")
        ext._toggle_global_visibility("outliers")

        self.assertTrue(ext._is_dirty)

    def test_camera_dirty_state_clears_when_returned_to_saved_orientation(self):
        ext = make_extension()
        saved_orientation = list(ext._viewport.camera.orientation)
        ext._clear_dirty_tracking()

        self.assertTrue(ext._rotate_camera_step("horizontal", 1.0))
        self.assertTrue(ext._is_dirty)

        ext._viewport.camera.orientation = saved_orientation
        ext._sync_camera_models()

        self.assertFalse(ext._is_dirty)

    def test_update_loop_suppresses_hover_pick_when_file_dialog_is_visible(self):
        ext = make_extension()
        ext._save_workspace_dialog = types.SimpleNamespace(visible=True)

        ext._update_once()

        self.assertEqual(ext._viewport.poll_hover_pick_count, 0)
        self.assertEqual(ext._viewport.clear_hover_pick_count, 1)
        self.assertFalse(ext._viewport.picking_enabled)

    def test_update_loop_suppresses_hover_pick_for_each_file_dialog(self):
        for name in (
            "_file_dialog",
            "_load_workspace_dialog",
            "_save_workspace_dialog",
            "_export_geometries_dialog",
        ):
            with self.subTest(name=name):
                ext = make_extension()
                setattr(ext, name, types.SimpleNamespace(_window=types.SimpleNamespace(visible=True)))

                ext._update_once()

                self.assertEqual(ext._viewport.poll_hover_pick_count, 0)
                self.assertEqual(ext._viewport.clear_hover_pick_count, 1)
                self.assertFalse(ext._viewport.picking_enabled)

    def test_dialog_visibility_checks_nested_window_after_false_visible_attr(self):
        ext = make_extension()
        ext._file_dialog = types.SimpleNamespace(visible=False, _window=types.SimpleNamespace(visible=True))

        ext._update_once()

        self.assertEqual(ext._viewport.poll_hover_pick_count, 0)
        self.assertEqual(ext._viewport.clear_hover_pick_count, 1)
        self.assertFalse(ext._viewport.picking_enabled)

    def test_update_loop_polls_hover_pick_when_file_dialog_is_hidden(self):
        ext = make_extension()
        ext._save_workspace_dialog = types.SimpleNamespace(visible=False)

        ext._update_once()

        self.assertEqual(ext._viewport.poll_hover_pick_count, 1)
        self.assertEqual(ext._viewport.clear_hover_pick_count, 0)
        self.assertTrue(ext._viewport.picking_enabled)

    def test_update_loop_reenables_viewport_picking_after_dialog_hides(self):
        ext = make_extension()
        ext._viewport.picking_enabled = False
        ext._save_workspace_dialog = types.SimpleNamespace(visible=False)

        ext._update_once()

        self.assertTrue(ext._viewport.picking_enabled)
        self.assertEqual(ext._viewport.poll_hover_pick_count, 1)

    def test_toolbar_style_draws_button_borders_and_disabled_icon_tint(self):
        ext = make_extension()

        style = ext._toolbar_style()

        self.assertEqual(style["ToolBar.ButtonFrame"]["border_width"], 1)
        self.assertIn("border_color", style["ToolBar.ButtonFrame"])
        self.assertEqual(style["ToolBar.ButtonHit"]["border_width"], 0)
        self.assertIn("ToolBar.ButtonIcon:disabled", style)
        self.assertNotEqual(
            style["ToolBar.ButtonIcon"]["color"],
            style["ToolBar.ButtonIcon:disabled"]["color"],
        )

    def test_toolbar_icon_path_uses_app_extension_data_folder(self):
        ext = make_extension()

        path = Path(ext._toolbar_icon_path("folder-open.svg"))

        self.assertEqual(path.name, "folder-open.svg")
        self.assertEqual(path.parent.name, "findsurface")
        self.assertEqual(path.parent.parent.name, "icons")
        self.assertEqual(path.parent.parent.parent.name, "data")
        self.assertEqual(path.parent.parent.parent.parent.name, "com.curvsurf.findsurface_omniverse")
        self.assertTrue(path.exists())

    def test_toolbar_axis_change_rebuilds_for_vertical_layout(self):
        ext = make_extension()
        previous_axis = getattr(extension.ui, "ToolBarAxis", None)
        extension.ui.ToolBarAxis = types.SimpleNamespace(X="x", Y="y")
        rebuilds = []
        try:
            ext._toolbar_axis = ext._toolbar_axis_x()
            ext._windows[extension.FindSurfaceBootstrapExtension.WINDOW_TOOLBAR] = types.SimpleNamespace(
                frame=types.SimpleNamespace(rebuild=lambda: rebuilds.append("rebuild"))
            )

            self.assertFalse(ext._is_toolbar_vertical())

            ext._on_toolbar_axis_changed(ext._toolbar_axis_y())

            self.assertTrue(ext._is_toolbar_vertical())
            self.assertEqual(rebuilds, ["rebuild"])
        finally:
            if previous_axis is None:
                delattr(extension.ui, "ToolBarAxis")
            else:
                extension.ui.ToolBarAxis = previous_axis

    def test_toolbar_buttons_are_compact_square_icons_with_readable_text_fallback(self):
        ext_cls = extension.FindSurfaceBootstrapExtension

        self.assertEqual(ext_cls.TOOLBAR_BUTTON_SIZE, 38)
        self.assertEqual(ext_cls.TOOLBAR_ICON_SIZE, 22)
        self.assertGreater(ext_cls.TOOLBAR_TEXT_BUTTON_WIDTH, ext_cls.TOOLBAR_BUTTON_SIZE)
        self.assertGreater(ext_cls.TOOLBAR_VISIBILITY_ICON_SIZE, ext_cls.TOOLBAR_LARGE_ICON_SIZE)

    def test_camera_preset_top_sets_direction_and_up(self):
        ext = make_extension()
        ext._set_camera_preset("top")

        self.assertAlmostEqual(ext._viewport.camera.forward[0], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.forward[1], -1.0)
        self.assertAlmostEqual(ext._viewport.camera.forward[2], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.up[0], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.up[1], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.up[2], -1.0)

    def test_camera_rotation_step_rotates_horizontally_around_up_axis(self):
        ext = make_extension()
        start_up = list(ext._viewport.camera.up)
        start_forward = list(ext._viewport.camera.forward)

        self.assertTrue(ext._rotate_camera_step("horizontal", 1.0))

        expected_x = math.sin(math.radians(1.0))
        expected_z = -math.cos(math.radians(1.0))
        self.assertAlmostEqual(ext._viewport.camera.forward[0], expected_x)
        self.assertAlmostEqual(ext._viewport.camera.forward[1], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.forward[2], expected_z)
        self.assertEqual(start_up, ext._viewport.camera.up)
        self.assertNotEqual(start_forward, ext._viewport.camera.forward)
        self.assertEqual(ext._viewport.draw_count, 1)
        self.assertTrue(ext._is_dirty)
        self.assertEqual(ext._state.transaction_log[-1].event_type, detection.TRANSACTION_CAMERA_CHANGE)

    def test_camera_rotation_step_is_undoable(self):
        ext = make_extension()
        ext._clear_dirty_tracking()
        start_orientation = list(ext._viewport.camera.orientation)

        ext._rotate_camera_step("horizontal", 1.0)

        self.assertTrue(ext._state.can_undo)
        self.assertTrue(ext._display_camera_dirty)

        ext._undo_last()

        self.assertEqual(ext._viewport.camera.orientation, start_orientation)
        self.assertFalse(ext._is_dirty)
        self.assertTrue(ext._state.can_redo)

        ext._redo_last()

        self.assertNotEqual(ext._viewport.camera.orientation, start_orientation)
        self.assertTrue(ext._is_dirty)

    def test_camera_change_callback_commits_complete_drag_as_one_transaction(self):
        ext = make_extension()
        ext._clear_dirty_tracking()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)
        start_orientation = list(ext._viewport.camera.orientation)

        ext._on_camera_changed("begin")
        ext._viewport.camera.rotate_orientation_degrees(ext._viewport.camera.up, 1.0)
        ext._on_camera_changed("change")
        ext._viewport.camera.rotate_orientation_degrees(ext._viewport.camera.up, 2.0)
        ext._on_camera_changed("change")
        ext._on_camera_changed("commit")

        self.assertEqual(len(ext._state.transaction_log), 1)
        self.assertEqual(ext._state.transaction_log[0].event_type, detection.TRANSACTION_CAMERA_CHANGE)
        self.assertEqual(queued, [True])

        ext._undo_last()

        self.assertEqual(ext._viewport.camera.orientation, start_orientation)

    def test_camera_rotation_step_rotates_vertically_around_right_axis(self):
        ext = make_extension()

        self.assertTrue(ext._rotate_camera_step("vertical", 10.0))

        expected_y = math.sin(math.radians(10.0))
        expected_z = -math.cos(math.radians(10.0))
        self.assertAlmostEqual(ext._viewport.camera.forward[0], 0.0)
        self.assertAlmostEqual(ext._viewport.camera.forward[1], expected_y)
        self.assertAlmostEqual(ext._viewport.camera.forward[2], expected_z)
        self.assertEqual(ext._viewport.draw_count, 1)
        self.assertTrue(ext._is_dirty)

    def test_arrow_shortcuts_rotate_camera_with_deterministic_modifier_steps(self):
        ext = make_extension()
        rotations = []
        ext._rotate_camera_step = lambda axis, degrees: rotations.append((axis, degrees)) or True

        self.assertTrue(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ARROW_RIGHT", modifiers=0)))
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="ARROW_LEFT",
                    modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT,
                )
            )
        )
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="ARROW_UP",
                    modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL,
                )
            )
        )
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="ARROW_DOWN",
                    modifiers=(
                        extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL
                        | extension.carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT
                    ),
                )
            )
        )

        self.assertEqual(
            rotations,
            [
                ("horizontal", 1.0),
                ("horizontal", -10.0),
                ("vertical", 0.05),
                ("vertical", -0.05),
            ],
        )

    def test_arrow_shortcut_key_repeat_keeps_rotating_camera(self):
        ext = make_extension()
        rotations = []
        ext._rotate_camera_step = lambda axis, degrees: rotations.append((axis, degrees)) or True

        self.assertTrue(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_REPEAT", input="ARROW_RIGHT", modifiers=0)))
        self.assertTrue(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_DOWN_REPEAT", input="ARROW_RIGHT", modifiers=0)))

        self.assertEqual(rotations, [("horizontal", 1.0), ("horizontal", 1.0)])

    def test_arrow_shortcuts_do_not_rotate_while_text_input_is_editing(self):
        ext = make_extension()
        rotations = []
        ext._rotate_camera_step = lambda axis, degrees: rotations.append((axis, degrees)) or True

        handled = ext._handle_shortcut_event(
            types.SimpleNamespace(type="KEY_PRESS", input="ARROW_RIGHT", modifiers=0, keyboard_captured=True)
        )

        self.assertFalse(handled)
        self.assertEqual(rotations, [])

    def test_post_quit_cancels_shutdown_when_dirty(self):
        ext = make_extension()
        ext._is_dirty = True
        shown = []
        consumed = []
        original_get_app = extension.omni.kit.app.get_app
        try:
            extension.omni.kit.app.get_app = lambda: types.SimpleNamespace(
                try_cancel_shutdown=lambda reason: True,
            )
            ext._show_unsaved_changes_dialog = lambda label, action: shown.append((label, action))

            ext._on_post_quit(types.SimpleNamespace(consume=lambda: consumed.append(True)))
        finally:
            extension.omni.kit.app.get_app = original_get_app

        self.assertEqual(shown[0][0], "exit FindSurface")
        self.assertEqual(consumed, [True])

    def test_import_size_error_shows_sampling_confirmation(self):
        ext = make_extension()
        calls = []
        error = PointCloudSizeError("too large")
        ext._show_point_limit_dialog = lambda full_path, error: calls.append((full_path, error))

        with ext._import_lock:
            ext._import_request_token = 3
            ext._import_busy = True
            ext._import_pending = (3, "C:/tmp/cloud.xyz", None, error, "Importing")
        ext._apply_import_pending()

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][0].endswith("cloud.xyz"))

    def test_sample_pending_import_uses_selected_target_count(self):
        ext = make_extension()
        ext._pending_oversized_import_path = "C:/tmp/cloud.xyz"
        ext._pending_oversized_import_error = types.SimpleNamespace(max_points=200000, target_points=100000)
        ext._sample_target_model = types.SimpleNamespace(as_int=150000)
        calls = []
        ext._begin_import_points = lambda full_path, options, action_label="Importing": calls.append(
            (full_path, options, action_label)
        )

        ext._sample_pending_oversized_import()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1].target_points, 150000)
        self.assertEqual(calls[0][1].overflow_policy, "sample")
        self.assertEqual(calls[0][2], "Sampling")

    def test_canceled_import_pending_result_does_not_replace_active_cloud(self):
        ext = make_extension()
        original_cloud = ext._state.cloud
        with ext._import_lock:
            ext._import_request_token = 4
            ext._import_busy = True
            ext._import_pending = (
                4,
                "C:/tmp/cloud.xyz",
                types.SimpleNamespace(count=1, points=[[9.0, 9.0, 9.0]], metadata={}),
                extension.ImportCanceledError("Import canceled."),
                "Importing",
            )

        ext._apply_import_pending()

        self.assertIs(ext._state.cloud, original_cloud)
        self.assertIn("Import canceled", ext._status_label.text)

    def test_imported_point_cloud_uses_dataset_command_post_processing(self):
        ext = make_extension()
        ext._is_dirty = True
        ext._content_dirty = True
        ext._display_camera_dirty = True
        calls = []
        ext._refresh_detection_panel = lambda: calls.append("detection")
        ext._queue_geometries_window_refresh = lambda: calls.append("geometries")
        ext._queue_transactions_window_refresh = lambda: calls.append("transactions")
        ext._refresh_toolbar_state = lambda: calls.append("toolbar")
        ext._sync_parameter_transaction_baseline = lambda: calls.append("baseline")
        cloud = types.SimpleNamespace(
            count=2,
            points=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            metadata={},
        )

        result = ext._apply_imported_point_cloud("C:/tmp/new.xyz", cloud)

        self.assertTrue(result)
        self.assertIs(ext._state.cloud, cloud)
        self.assertIsNone(ext._workspace_path)
        self.assertEqual(ext._dataset_name, "new.xyz")
        self.assertFalse(ext._is_dirty)
        self.assertFalse(ext._content_dirty)
        self.assertFalse(ext._display_camera_dirty)
        self.assertIn("detection", calls)
        self.assertIn("geometries", calls)
        self.assertIn("transactions", calls)
        self.assertIn("toolbar", calls)
        self.assertIn("baseline", calls)

    def test_selected_sample_target_allows_values_down_to_one_hundred(self):
        ext = make_extension()
        ext._sample_target_model = types.SimpleNamespace(as_int=100)
        error = types.SimpleNamespace(max_points=200000, target_points=100000)

        self.assertEqual(ext._selected_sample_target(error), 100)

    def test_capture_requires_selected_preview(self):
        ext = make_extension()
        hover_preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._auto_detect_result = hover_preview
        ext._auto_detect_source = "hover"

        ext._refresh_detection_panel()

        self.assertFalse(ext._can_capture_selected_preview())
        self.assertFalse(ext._capture_button.enabled)

    def test_detection_panel_updates_viewport_data_overlay(self):
        ext = make_extension()

        ext._refresh_detection_panel()

        self.assertEqual(
            ext._viewport.data_overlay,
            {
                "dataset_name": "cloud.xyz",
                "active_count": 4,
                "point_count": 4,
                "removed_count": 0,
                "hover_index": 0,
                "selected_index": 1,
            },
        )

    def test_hover_preview_updates_viewport_detection_overlay(self):
        ext = make_extension()
        ext._selected_index = None
        ext._hover_index = 1
        hover_preview = surface_preview.SurfaceResult(
            id="AutoHover_Sphere_001",
            type="Sphere",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            rms_error=0.0012,
            parameters={"center": [1.0, 0.0, 0.0], "radius": 0.5},
        )
        ext._auto_detect_result = hover_preview
        ext._auto_detect_source = "hover"

        previous_builder = getattr(extension.viewport_module, "build_inlier_distance_histogram", None)
        extension.viewport_module.build_inlier_distance_histogram = lambda *args, **kwargs: {
            "max_bin_count": 2,
            "zero_fraction": 0.5,
            "bins": [{"count": 2, "color": [1.0, 0.0, 0.0, 1.0]}],
        }
        try:
            ext._refresh_detection_panel()
        finally:
            if previous_builder is None:
                delattr(extension.viewport_module, "build_inlier_distance_histogram")
            else:
                extension.viewport_module.build_inlier_distance_histogram = previous_builder

        overlay = ext._viewport.hover_detection_overlay
        self.assertTrue(overlay["visible"])
        self.assertEqual(overlay["result_type"], "Sphere")
        self.assertTrue(overlay["icon_path"].endswith("detect_sphere.svg"))
        self.assertIn(("Seed Index", "1"), overlay["rows"])
        self.assertIn(("Inliers", "2 pts"), overlay["rows"])
        self.assertNotIn("Axis", dict(overlay["rows"]))
        self.assertNotIn("Normal", dict(overlay["rows"]))
        self.assertIsNotNone(overlay["histogram"])

    def test_sticky_hover_preview_reuses_histogram_for_same_result(self):
        ext = make_extension()
        ext._models["sticky_auto_preview"] = types.SimpleNamespace(as_bool=True)
        ext._selected_index = None
        ext._hover_index = 1
        hover_preview = surface_preview.SurfaceResult(
            id="AutoHover_Sphere_001",
            type="Sphere",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            rms_error=0.0012,
            parameters={"center": [1.0, 0.0, 0.0], "radius": 0.5},
        )
        ext._auto_detect_result = hover_preview
        ext._auto_detect_source = "hover"

        calls = []

        def histogram_builder(*args, **kwargs):
            calls.append((args, kwargs))
            return {
                "max_bin_count": 2,
                "zero_fraction": 0.5,
                "bins": [{"count": 2, "color": [1.0, 0.0, 0.0, 1.0]}],
            }

        previous_builder = getattr(extension.viewport_module, "build_inlier_distance_histogram", None)
        extension.viewport_module.build_inlier_distance_histogram = histogram_builder
        try:
            ext._refresh_detection_panel()
            ext._hover_index = 2
            ext._refresh_detection_panel()
            ext._geometry_histogram_bin_counts[hover_preview.id] = 37
            ext._refresh_detection_panel()
        finally:
            if previous_builder is None:
                delattr(extension.viewport_module, "build_inlier_distance_histogram")
            else:
                extension.viewport_module.build_inlier_distance_histogram = previous_builder

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["bin_count"], 35)
        self.assertEqual(calls[1][1]["bin_count"], 37)

    def test_selected_preview_updates_viewport_detection_overlay(self):
        ext = make_extension()
        ext._selected_index = 1
        selected_preview = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            rms_error=0.0012,
            parameters={"origin": [1.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0], "width": 1.0, "height": 2.0},
        )
        ext._auto_detect_result = selected_preview
        ext._auto_detect_source = "selected"

        previous_builder = getattr(extension.viewport_module, "build_inlier_distance_histogram", None)
        extension.viewport_module.build_inlier_distance_histogram = lambda *args, **kwargs: {
            "max_bin_count": 2,
            "zero_fraction": 0.5,
            "mean_fraction": 0.5,
            "bins": [{"count": 2, "color": [1.0, 0.0, 0.0, 1.0]}],
        }
        try:
            ext._refresh_detection_panel()
        finally:
            if previous_builder is None:
                delattr(extension.viewport_module, "build_inlier_distance_histogram")
            else:
                extension.viewport_module.build_inlier_distance_histogram = previous_builder

        overlay = ext._viewport.hover_detection_overlay
        self.assertTrue(overlay["visible"])
        self.assertEqual(overlay["result_type"], "Plane")
        self.assertIn(("Seed Index", "1"), overlay["rows"])
        self.assertIn(("Normal", "(0, 0, 1)"), overlay["rows"])
        self.assertIn(("Inliers", "2 pts"), overlay["rows"])
        self.assertIsNotNone(overlay["histogram"])

    def test_cylinder_preview_overlay_includes_axis(self):
        ext = make_extension()
        ext._selected_index = None
        ext._hover_index = 1
        hover_preview = surface_preview.SurfaceResult(
            id="AutoHover_Cylinder_001",
            type="Cylinder",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            rms_error=0.0012,
            parameters={"center": [1.0, 0.0, 0.0], "axis": [0.0, 1.0, 0.0], "radius": 0.5, "height": 2.0},
        )
        ext._auto_detect_result = hover_preview
        ext._auto_detect_source = "hover"

        ext._refresh_detection_panel()

        overlay = ext._viewport.hover_detection_overlay
        self.assertTrue(overlay["visible"])
        self.assertEqual(overlay["result_type"], "Cylinder")
        self.assertIn(("Axis", "(0, 1, 0)"), overlay["rows"])
        self.assertIn(("Size", "r=0.5 h=2"), overlay["rows"])

    def test_detection_settings_apply_nearest_probe_miss_pick_option(self):
        ext = make_extension()
        ext._models = {
            "probe_radius": types.SimpleNamespace(as_float=4.0),
            "seed_radius": types.SimpleNamespace(as_float=0.15),
            "pick_nearest_on_probe_miss": types.SimpleNamespace(as_bool=False),
            "auto_detect": types.SimpleNamespace(as_bool=True),
        }
        ext._request_auto_detect = lambda: None

        ext._on_detection_settings_changed("pick_nearest_on_probe_miss")

        self.assertFalse(ext._viewport.pick_nearest_on_probe_miss)

    def test_capture_applies_selected_preview_to_active_mask_and_results(self):
        ext = make_extension()
        selected_preview = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._auto_detect_result = selected_preview
        ext._auto_detect_source = "selected"

        ext._refresh_detection_panel()
        self.assertTrue(ext._capture_button.enabled)

        ext._capture_selected_preview()

        self.assertTrue(ext._is_dirty)
        self.assertFalse(ext._capture_button.enabled)
        self.assertEqual(ext._state.active_mask, [True, False, False, True])
        self.assertEqual(ext._state.results, [selected_preview])
        self.assertIsNone(ext._selected_index)
        self.assertIsNone(ext._hover_index)
        self.assertEqual(ext._viewport.active_mask, [True, False, False, True])
        self.assertEqual(ext._viewport.pick_markers, (None, None))
        self.assertEqual(ext._viewport.surfaces, [selected_preview])
        self.assertIn("Captured Plane_1", ext._status_label.text)

    def test_confirmed_geometry_names_use_type_local_counters(self):
        ext = make_extension()
        first_plane = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1],
            active_generation=ext._state.generation,
        )
        sphere = surface_preview.SurfaceResult(
            id="AutoSelected_Sphere_001",
            type="Sphere",
            seed_position=(2.0, 0.0, 0.0),
            seed_index=2,
            inlier_indices=[2],
            active_generation=ext._state.generation,
        )
        second_plane = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_002",
            type="Plane",
            seed_position=(3.0, 0.0, 0.0),
            seed_index=3,
            inlier_indices=[3],
            active_generation=ext._state.generation,
        )

        ext._apply_confirmed_result(first_plane)
        ext._apply_confirmed_result(sphere)
        ext._apply_confirmed_result(second_plane)

        self.assertEqual([result.id for result in ext._state.results], ["Plane_1", "Sphere_1", "Plane_2"])

    def test_geometry_numbering_uses_max_existing_number_after_delete(self):
        ext = make_extension()
        for result_id in ("Plane_1", "Plane_2", "Plane_3"):
            ext._state.apply_result(
                surface_preview.SurfaceResult(
                    id=result_id,
                    type="Plane",
                    seed_position=(0.0, 0.0, 0.0),
                    seed_index=0,
                    inlier_indices=[],
                    active_generation=ext._state.generation,
                )
            )
        ext._sync_detection_surfaces()

        ext._delete_geometry_result("Plane_2")
        ext._apply_confirmed_result(
            surface_preview.SurfaceResult(
                id="AutoSelected_Plane_004",
                type="Plane",
                seed_position=(1.0, 0.0, 0.0),
                seed_index=1,
                inlier_indices=[1],
                active_generation=ext._state.generation,
            )
        )

        self.assertEqual([result.id for result in ext._state.results], ["Plane_1", "Plane_3", "Plane_4"])

    def test_geometry_numbering_reuses_removed_highest_number_after_cancel(self):
        ext = make_extension()
        for result_id in ("Plane_1", "Plane_2", "Plane_3"):
            ext._state.apply_result(
                surface_preview.SurfaceResult(
                    id=result_id,
                    type="Plane",
                    seed_position=(0.0, 0.0, 0.0),
                    seed_index=0,
                    inlier_indices=[],
                    active_generation=ext._state.generation,
                )
            )
        ext._sync_detection_surfaces()

        ext._cancel_geometry_result("Plane_3")
        ext._apply_confirmed_result(
            surface_preview.SurfaceResult(
                id="AutoSelected_Plane_003",
                type="Plane",
                seed_position=(1.0, 0.0, 0.0),
                seed_index=1,
                inlier_indices=[1],
                active_generation=ext._state.generation,
            )
        )

        self.assertEqual([result.id for result in ext._state.results], ["Plane_1", "Plane_2", "Plane_3"])

    def test_geometry_collapsed_state_toggles_by_result_id(self):
        ext = make_extension()
        refreshes = []
        ext._queue_geometries_window_refresh = lambda: refreshes.append(True)

        ext._toggle_geometry_collapsed("Plane_1")
        self.assertTrue(ext._is_geometry_collapsed("Plane_1"))

        ext._toggle_geometry_collapsed("Plane_1")
        self.assertFalse(ext._is_geometry_collapsed("Plane_1"))
        self.assertEqual(refreshes, [True, True])

    def test_stale_selected_preview_is_not_capturable(self):
        ext = make_extension()
        stale_preview = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1],
            active_generation=ext._state.generation + 1,
        )
        ext._auto_detect_result = stale_preview
        ext._auto_detect_source = "selected"

        ext._refresh_detection_panel()

        self.assertFalse(ext._can_capture_selected_preview())
        self.assertFalse(ext._capture_button.enabled)

    def test_run_detection_failure_clears_preview_inliers(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._auto_detect_result = preview
        ext._auto_detect_source = "selected"
        ext._provider = types.SimpleNamespace(detect=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no fit")))
        ext._read_options = lambda: detection.DetectionOptions()
        ext._auto_detect_disabled_reason = None
        ext._sync_detection_surfaces()

        self.assertEqual(ext._viewport.surfaces, [preview])

        ext._run_detection()

        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertEqual(ext._viewport.surfaces, [])
        self.assertIn("Detection failed", ext._status_label.text)
        self.assertIn("rms=n/a", ext._status_label.text)
        self.assertIn("no fit", ext._status_label.text)

    def test_run_detection_orients_plane_normal_toward_camera(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            parameters={
                "origin": (0.0, 0.0, 0.0),
                "x_axis": (1.0, 0.0, 0.0),
                "y_axis": (0.0, 1.0, 0.0),
                "z_axis": (0.0, 0.0, -1.0),
                "normal": (0.0, 0.0, -1.0),
                "upper_left": (0.0, 1.0, 0.0),
                "upper_right": (1.0, 1.0, 0.0),
                "lower_left": (0.0, 0.0, 0.0),
                "lower_right": (1.0, 0.0, 0.0),
            },
        )
        ext._provider = types.SimpleNamespace(detect=lambda *args, **kwargs: result)
        ext._read_options = lambda: detection.DetectionOptions()
        ext._auto_detect_disabled_reason = None

        ext._run_detection()

        params = ext._state.results[0].parameters
        self.assertEqual(params["z_axis"], [0.0, 0.0, 1.0])
        self.assertEqual(params["normal"], [0.0, 0.0, 1.0])
        self.assertEqual(params["y_axis"], [0.0, -1.0, 0.0])
        self.assertEqual(params["upper_left"], (0.0, 0.0, 0.0))
        self.assertEqual(params["upper_right"], (1.0, 0.0, 0.0))
        self.assertEqual(params["lower_left"], (0.0, 1.0, 0.0))
        self.assertEqual(params["lower_right"], (1.0, 1.0, 0.0))

    def test_detection_status_is_concise_action_and_result_id(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
            rms_error=0.00123,
            parameters={"width": 2.5, "height": 1.25},
        )

        text = ext._detection_result_status("Auto preview", result)

        self.assertEqual(text, "Auto preview Plane_001")
        self.assertNotIn("w=2.5 h=1.25", text)
        self.assertNotIn("rms=0.00123", text)
        self.assertNotIn("inliers=2", text)

    def test_geometry_fields_format_vector_components_and_lengths(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Cylinder_1",
            type="Cylinder",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0, 1],
            active_generation=ext._state.generation,
            rms_error=0.00123,
            parameters={
                "axis": (0.0, 1.0, 0.0),
                "radius": 1.23456,
                "height": 0.0014,
                "center": (1.0, 2.0, 3.0),
            },
        )

        fields = ext._geometry_result_fields(result)
        fields_by_label = {field["label"]: field for field in fields}

        self.assertEqual(
            [(field["label"], field["value"]) for field in fields[:3]],
            [("Name", "Cylinder_1"), ("Type", "Cylinder"), ("Seed Index", "0")],
        )
        self.assertEqual(fields_by_label["RMS error"]["value"], "1.2e-03")
        self.assertEqual(fields_by_label["Axis"]["kind"], "vector3")
        self.assertEqual(fields_by_label["Axis"]["components"], ("0", "1", "0"))
        self.assertNotIn("lat", ext._geometry_field_value_text(fields_by_label["Axis"]))
        self.assertNotIn("lon", ext._geometry_field_value_text(fields_by_label["Axis"]))
        self.assertEqual(fields_by_label["Radius"]["value"], "1.235")
        self.assertEqual(fields_by_label["Length"]["value"], "0.001")

    def test_geometry_plane_normal_formats_vector_components(self):
        ext = make_extension()
        result = surface_preview.SurfaceResult(
            id="Plane_1",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[],
            active_generation=ext._state.generation,
            parameters={
                "normal": (0.0, 0.0, 1.0),
                "width": 2.0,
                "height": 3.0,
                "origin": (0.0, 0.0, 0.0),
            },
        )

        fields = ext._geometry_result_fields(result)
        fields_by_label = {field["label"]: field for field in fields}

        self.assertNotIn("Axis", fields_by_label)
        self.assertEqual(fields_by_label["Normal"]["kind"], "vector3")
        self.assertEqual(fields_by_label["Normal"]["components"], ("0", "0", "1"))
        self.assertNotIn("lat", ext._geometry_field_value_text(fields_by_label["Normal"]))
        self.assertNotIn("lon", ext._geometry_field_value_text(fields_by_label["Normal"]))
        self.assertEqual(fields_by_label["Width"]["value"], "2.000")
        self.assertEqual(fields_by_label["Height"]["value"], "3.000")

    def test_failure_status_extracts_rms_error(self):
        ext = make_extension()

        text = ext._detection_failure_status(
            "Auto FindSurface failed",
            "FindSurface did not return a valid result. result_type=0, rms_error=0.0456",
        )

        self.assertIn("Auto FindSurface failed", text)
        self.assertIn("rms=0.0456", text)

    def test_failure_status_distinguishes_invalid_seed(self):
        ext = make_extension()

        text = ext._detection_failure_status("Detection failed", ValueError("Seed index is outside the point cloud."))

        self.assertIn("invalid seed", text)
        self.assertIn("Seed index is outside the point cloud", text)

    def test_native_unavailable_status_distinguishes_missing_dll(self):
        ext = make_extension()

        text = ext._native_unavailable_status(FileNotFoundError("FindSurface.dll"))

        self.assertIn("missing DLL", text)
        self.assertIn("FindSurface.dll", text)

    def test_auto_detect_request_clears_previous_preview_before_new_result(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)
        ext._sync_detection_surfaces()

        self.assertEqual(ext._viewport.surfaces, [preview])

        ext._hover_index = 1
        ext._request_auto_detect()

        self.assertEqual(ext._viewport.surfaces, [])
        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertEqual(len(starts), 1)

    def test_auto_detect_request_defers_hover_changes_while_busy(self):
        ext = make_extension()
        running_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = 0
        ext._auto_detect_key = running_key
        ext._auto_detect_busy = True
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)
        ext._sync_detection_surfaces()

        ext._hover_index = 2
        ext._request_auto_detect()

        self.assertEqual(ext._auto_detect_key, running_key)
        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertEqual(ext._auto_detect_result, preview)
        self.assertEqual(starts, [])
        self.assertIsNotNone(ext._auto_detect_deferred)
        self.assertEqual(ext._auto_detect_deferred[0][2], 2)

    def test_auto_detect_request_ignores_missing_hover_while_busy(self):
        ext = make_extension()
        running_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = None
        ext._auto_detect_key = running_key
        ext._auto_detect_busy = True
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()

        ext._request_auto_detect()

        self.assertEqual(ext._auto_detect_key, running_key)
        self.assertEqual(ext._auto_detect_result, preview)
        self.assertEqual(ext._auto_detect_source, "hover")

    def test_imported_point_cloud_invalidates_in_flight_auto_detect(self):
        ext = make_extension()
        running_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_key = running_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (running_key, "hover", None, "late result")
        ext._auto_detect_deferred = (running_key, "hover", ext._state, 0, detection.DetectionOptions())
        previous_token = ext._auto_detect_request_token
        cloud = types.SimpleNamespace(
            count=2,
            points=[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            metadata={},
        )

        ext._apply_imported_point_cloud("C:/tmp/new.xyz", cloud)

        self.assertFalse(ext._auto_detect_busy)
        self.assertIsNone(ext._auto_detect_key)
        self.assertIsNone(ext._auto_detect_pending)
        self.assertIsNone(ext._auto_detect_deferred)
        self.assertGreater(ext._auto_detect_request_token, previous_token)

    def test_stale_auto_detect_worker_result_is_dropped_after_invalidation(self):
        ext = make_extension()
        key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        token = ext._auto_detect_request_token
        preview = surface_preview.SurfaceResult(
            id="Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._auto_detect_key = key
        ext._auto_detect_busy = True
        ext._provider = types.SimpleNamespace(detect=lambda *args, **kwargs: preview)

        ext._invalidate_auto_detect_requests()
        ext._auto_detect_worker(key, "hover", ext._state, 0, detection.DetectionOptions(), token)

        self.assertIsNone(ext._auto_detect_pending)
        self.assertIsNone(ext._auto_detect_key)
        self.assertFalse(ext._auto_detect_busy)

    def test_shutdown_suppresses_new_auto_detect_requests(self):
        ext = make_extension()
        ext._app_shutting_down = True
        ext._selected_index = None
        ext._hover_index = 0
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}
        ext._provider = types.SimpleNamespace()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)

        ext._request_auto_detect()

        self.assertEqual(starts, [])
        self.assertIsNone(ext._auto_detect_key)

    def test_completed_hover_preview_displays_even_after_hover_moves(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
            parameters={
                "origin": (0.0, 0.0, 0.0),
                "x_axis": (1.0, 0.0, 0.0),
                "y_axis": (0.0, 1.0, 0.0),
                "z_axis": (0.0, 0.0, -1.0),
            },
        )
        key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._selected_index = None
        ext._hover_index = 2
        ext._auto_detect_key = key
        ext._auto_detect_pending = (key, "hover", preview, None)
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }

        ext._apply_auto_detect_pending()

        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertEqual(preview.parameters["z_axis"], [0.0, 0.0, 1.0])
        self.assertEqual(preview.parameters["y_axis"], [0.0, -1.0, 0.0])

    def test_pending_auto_detect_result_starts_deferred_hover_after_apply(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        running_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._selected_index = None
        ext._hover_index = 2
        ext._auto_detect_key = running_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (running_key, "hover", preview, None)
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)

        ext._request_auto_detect()
        ext._apply_auto_detect_pending()

        self.assertNotEqual(ext._auto_detect_key, running_key)
        self.assertEqual(ext._auto_detect_key[2], 2)
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][3], 2)
        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertTrue(ext._auto_detect_busy)

    def test_sticky_auto_preview_keeps_previous_result_after_failed_detection(self):
        ext = make_extension()
        previous = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        failed_key = (id(ext._state), ext._state.generation, 2, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._selected_index = None
        ext._hover_index = 2
        ext._auto_detect_result = previous
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = failed_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (failed_key, "hover", None, "no fit")
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }
        ext._sync_detection_surfaces()

        ext._apply_auto_detect_pending()

        self.assertEqual(ext._auto_detect_result, previous)
        self.assertEqual(ext._viewport.surfaces, [previous])
        self.assertTrue(ext._viewport.hover_detection_overlay["visible"])
        self.assertIn("Auto FindSurface failed", ext._status_label.text)

    def test_selected_preview_sticky_timeout_matches_overlay_and_surface(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._selected_index = 1
        ext._hover_index = None
        ext._auto_detect_result = preview
        ext._auto_detect_source = "selected"
        ext._auto_detect_key = (id(ext._state), ext._state.generation, 1, "selected", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=500),
        }
        ext._provider = types.SimpleNamespace()
        ext._sync_detection_surfaces()
        ext._refresh_detection_panel()

        ext._clear_selected_seed()

        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertTrue(ext._viewport.hover_detection_overlay["visible"])

        ext._expire_auto_detect_preview()

        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertTrue(ext._viewport.hover_detection_overlay["visible"])
        self.assertIsNotNone(ext._auto_detect_display_deadline)

        ext._auto_detect_display_deadline = 0.0
        ext._expire_auto_detect_preview()

        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertEqual(ext._viewport.surfaces, [])
        self.assertFalse(ext._viewport.hover_detection_overlay["visible"])

    def test_selected_auto_detect_reuses_matching_successful_hover_preview(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = 1
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = (id(ext._state), ext._state.generation, 1, "hover", "Auto", 1.0, 0.02, 0.05, 5, 5)
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)
        ext._sync_detection_surfaces()

        ext._on_seed_selected(1)

        self.assertEqual(starts, [])
        self.assertEqual(ext._auto_detect_result, preview)
        self.assertEqual(ext._auto_detect_source, "selected")
        self.assertEqual(ext._auto_detect_key[2], 1)
        self.assertEqual(ext._auto_detect_key[3], "selected")
        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertTrue(ext._viewport.hover_detection_overlay["visible"])

    def test_alt_selected_seed_reuses_last_successful_preview_after_timeout(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        key = (id(ext._state), ext._state.generation, 1, "hover", "Auto", 1.0, 0.02, 0.05, 5, 5)
        ext._selected_index = None
        ext._hover_index = 1
        ext._auto_detect_key = key
        ext._auto_detect_pending = (key, "hover", preview, None)
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=500),
        }
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)

        ext._apply_auto_detect_pending()
        ext._hover_index = None
        ext._auto_detect_display_deadline = 0.0
        ext._expire_auto_detect_preview()

        self.assertIsNone(ext._auto_detect_result)
        self.assertEqual(ext._retroactive_pick_index, 1)
        self.assertEqual(ext._last_successful_auto_detect_result, preview)

        ext._on_seed_selected(1)

        self.assertEqual(starts, [])
        self.assertEqual(ext._auto_detect_result, preview)
        self.assertEqual(ext._auto_detect_source, "selected")
        self.assertEqual(ext._auto_detect_key[2], 1)
        self.assertEqual(ext._auto_detect_key[3], "selected")
        self.assertEqual(ext._viewport.surfaces, [preview])
        self.assertTrue(ext._viewport.hover_detection_overlay["visible"])

    def test_busy_hover_defers_clicked_selected_seed_and_runs_after_apply(self):
        ext = make_extension()
        running_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = 0
        ext._auto_detect_key = running_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (running_key, "hover", preview, None)
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)

        ext._on_seed_selected(2)

        self.assertIsNotNone(ext._auto_detect_deferred)
        self.assertEqual(ext._auto_detect_deferred[0][2], 2)
        self.assertEqual(ext._auto_detect_deferred[1], "selected")

        ext._apply_auto_detect_pending()

        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][1], "selected")
        self.assertEqual(starts[0][3], 2)
        self.assertTrue(ext._auto_detect_busy)

    def test_sticky_auto_preview_clears_selected_result_after_failed_detection(self):
        ext = make_extension()
        previous = surface_preview.SurfaceResult(
            id="AutoSelected_Plane_001",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=ext._state.generation,
        )
        failed_key = (id(ext._state), ext._state.generation, 1, "selected", "Auto", 0.3, 0.003, 0.05, 5, 5)
        ext._selected_index = 1
        ext._hover_index = None
        ext._auto_detect_result = previous
        ext._auto_detect_source = "selected"
        ext._auto_detect_key = failed_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (failed_key, "selected", None, "no fit")
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }
        ext._sync_detection_surfaces()

        ext._apply_auto_detect_pending()

        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertEqual(ext._viewport.surfaces, [])
        self.assertIn("Auto FindSurface failed", ext._status_label.text)

    def test_non_sticky_auto_preview_clears_previous_result_after_failed_detection(self):
        ext = make_extension()
        previous = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        failed_key = (id(ext._state), ext._state.generation, 2, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._selected_index = None
        ext._hover_index = 2
        ext._auto_detect_result = previous
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = failed_key
        ext._auto_detect_busy = True
        ext._auto_detect_pending = (failed_key, "hover", None, "no fit")
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}

        ext._apply_auto_detect_pending()

        self.assertIsNone(ext._auto_detect_result)
        self.assertEqual(ext._viewport.surfaces, [])

    def test_sticky_auto_preview_timeout_clears_visible_result(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = None
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_display_deadline = 0.0
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=3000),
        }
        ext._sync_detection_surfaces()

        ext._expire_auto_detect_preview()

        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertIsNone(ext._auto_detect_key)
        self.assertEqual(ext._viewport.surfaces, [])

    def test_sticky_auto_preview_does_not_timeout_while_hovering_same_seed(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = 0
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_display_deadline = 0.0
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=500),
        }
        ext._sync_detection_surfaces()

        ext._expire_auto_detect_preview()

        self.assertEqual(ext._auto_detect_result, preview)
        self.assertIsNone(ext._auto_detect_display_deadline)
        self.assertEqual(ext._viewport.surfaces, [preview])

    def test_sticky_auto_preview_starts_timeout_after_hover_leaves_seed(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._hover_index = None
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._auto_detect_key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_display_deadline = None
        ext._models = {
            "auto_detect": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview": types.SimpleNamespace(as_bool=True),
            "sticky_auto_preview_timeout_ms": types.SimpleNamespace(as_int=500),
        }
        ext._sync_detection_surfaces()

        ext._expire_auto_detect_preview()

        self.assertEqual(ext._auto_detect_result, preview)
        self.assertIsNotNone(ext._auto_detect_display_deadline)
        self.assertEqual(ext._viewport.surfaces, [preview])

    def test_auto_detect_surfaces_only_include_current_successful_preview(self):
        ext = make_extension()
        empty_preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[],
            active_generation=ext._state.generation,
        )
        stale_preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_002",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation + 1,
        )
        current_preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_003",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._auto_detect_source = "hover"

        ext._auto_detect_result = empty_preview
        ext._sync_detection_surfaces()
        self.assertEqual(ext._viewport.surfaces, [])

        ext._auto_detect_result = stale_preview
        ext._sync_detection_surfaces()
        self.assertEqual(ext._viewport.surfaces, [])

        ext._auto_detect_result = current_preview
        ext._sync_detection_surfaces()
        self.assertEqual(ext._viewport.surfaces, [current_preview])

    def test_auto_detect_success_updates_status_with_preview_metrics(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Sphere_001",
            type="Sphere",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
            rms_error=0.02,
            parameters={"radius": 1.5},
        )
        ext._selected_index = None
        key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_key = key
        ext._auto_detect_pending = (key, "hover", preview, None)
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}

        ext._apply_auto_detect_pending()

        self.assertEqual(ext._status_label.text, "Auto preview AutoHover_Sphere_001")
        self.assertNotIn("Feature: Auto", ext._status_label.text)
        self.assertNotIn("Auto: Sphere", ext._status_label.text)
        self.assertNotIn("r=1.5", ext._status_label.text)
        self.assertNotIn("rms=0.02", ext._status_label.text)
        self.assertEqual(ext._retroactive_pick_index, 0)
        self.assertEqual(ext._viewport.retroactive_pick_index, 0)

    def test_auto_detect_failure_updates_status_with_rms(self):
        ext = make_extension()
        key = (id(ext._state), ext._state.generation, 0, "hover", "Auto", 0.15, 0.003, 0.05, 5, 5)
        ext._auto_detect_key = key
        ext._auto_detect_pending = (
            key,
            "hover",
            None,
            "FindSurface did not return a valid result. result_type=0, rms_error=0.0789",
        )
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=True)}

        ext._apply_auto_detect_pending()

        self.assertIn("Auto FindSurface failed", ext._status_label.text)
        self.assertIn("rms=0.0789", ext._status_label.text)

    def test_hover_change_does_not_re_detect_when_selected_seed_is_active(self):
        ext = make_extension()
        requests = []
        ext._request_auto_detect = lambda: requests.append(True)

        ext._on_hover_changed(2)

        self.assertEqual(ext._hover_index, 2)
        self.assertEqual(requests, [])

    def test_hover_preview_toggle_disables_hover_auto_detect_only(self):
        ext = make_extension()
        preview = surface_preview.SurfaceResult(
            id="AutoHover_Plane_001",
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=0,
            inlier_indices=[0],
            active_generation=ext._state.generation,
        )
        ext._selected_index = None
        ext._auto_detect_result = preview
        ext._auto_detect_source = "hover"
        ext._models = {"auto_detect": types.SimpleNamespace(as_bool=False)}
        ext._provider = types.SimpleNamespace()
        ext._read_options = lambda: detection.DetectionOptions()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)
        ext._sync_detection_surfaces()

        ext._on_hover_changed(2)

        self.assertEqual(starts, [])
        self.assertIsNone(ext._auto_detect_result)
        self.assertIsNone(ext._auto_detect_source)
        self.assertEqual(ext._viewport.surfaces, [])

    def test_selected_auto_detect_runs_when_hover_preview_toggle_is_off(self):
        ext = make_extension()
        ext._models = {
            "probe_radius": types.SimpleNamespace(as_float=6.0),
            "seed_radius": types.SimpleNamespace(as_float=0.15),
            "measurement_accuracy": types.SimpleNamespace(as_float=0.003),
            "mean_distance": types.SimpleNamespace(as_float=0.05),
            "radial_expansion": types.SimpleNamespace(as_int=5),
            "lateral_extension": types.SimpleNamespace(as_int=5),
            "auto_detect": types.SimpleNamespace(as_bool=False),
        }
        ext._provider = types.SimpleNamespace()
        starts = []
        ext._start_auto_detect_worker = lambda *args: starts.append(args)

        ext._on_detection_settings_changed("seed_radius")

        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][1], "selected")
        self.assertEqual(starts[0][3], 1)

    def test_alt_keyboard_events_toggle_retroactive_pick_marker(self):
        ext = make_extension()

        ext._on_keyboard_event(
            types.SimpleNamespace(type="KEY_PRESS", input="LEFT_ALT", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_ALT)
        )
        self.assertTrue(ext._viewport.retroactive_pick_active)

        ext._on_keyboard_event(types.SimpleNamespace(type="KEY_RELEASE", input="LEFT_ALT", modifiers=0))
        self.assertFalse(ext._viewport.retroactive_pick_active)

    def test_shortcuts_clear_selection_and_choose_detection_type(self):
        ext = make_extension()
        auto_detect_requests = []
        ext._request_auto_detect = lambda: auto_detect_requests.append(True)

        self.assertTrue(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ESCAPE", modifiers=0)))

        self.assertIsNone(ext._selected_index)
        self.assertEqual(ext._viewport.pick_markers, (0, None))

        self.assertFalse(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="KEY_3", modifiers=0)))
        self.assertEqual(ext._detection_type, "Auto")

        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="KEY_3",
                    modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL,
                )
            )
        )
        self.assertEqual(ext._detection_type, "Cylinder")

        self.assertFalse(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="GRAVE_ACCENT", modifiers=0)))
        self.assertEqual(ext._detection_type, "Cylinder")

        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="GRAVE_ACCENT",
                    modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL,
                )
            )
        )
        self.assertEqual(ext._detection_type, "Auto")
        self.assertGreaterEqual(len(auto_detect_requests), 3)

    def test_escape_dismisses_tutorial_before_clearing_selection(self):
        ext = make_extension()
        ext._selected_index = 1
        tutorial = types.SimpleNamespace(visible=True)
        ext._windows[extension.FindSurfaceBootstrapExtension.WINDOW_TUTORIAL] = tutorial

        handled = ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ESCAPE", modifiers=0))

        self.assertTrue(handled)
        self.assertFalse(tutorial.visible)
        self.assertEqual(ext._selected_index, 1)

    def test_escape_dismisses_unsaved_changes_before_clearing_selection(self):
        ext = make_extension()
        ext._selected_index = 1
        ext._pending_unsaved_action = lambda: None
        ext._unsaved_changes_dialog = types.SimpleNamespace(visible=True)

        handled = ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ESCAPE", modifiers=0))

        self.assertTrue(handled)
        self.assertIsNone(ext._unsaved_changes_dialog)
        self.assertIsNone(ext._pending_unsaved_action)
        self.assertEqual(ext._selected_index, 1)

    def test_escape_dismisses_export_options_before_clearing_selection(self):
        ext = make_extension()
        ext._selected_index = 1
        ext._export_options_dialog = types.SimpleNamespace(visible=True)

        handled = ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ESCAPE", modifiers=0))

        self.assertTrue(handled)
        self.assertIsNone(ext._export_options_dialog)
        self.assertEqual(ext._selected_index, 1)

    def test_escape_cancels_save_dialog_before_clearing_selection(self):
        ext = make_extension()
        ext._selected_index = 1
        ext._save_dialog_continue_after = lambda: None

        class SaveDialog:
            visible = True

            def hide(self):
                self.visible = False

        ext._save_workspace_dialog = SaveDialog()

        handled = ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="ESCAPE", modifiers=0))

        self.assertTrue(handled)
        self.assertFalse(ext._save_workspace_dialog.visible)
        self.assertIsNone(ext._save_dialog_continue_after)
        self.assertEqual(ext._selected_index, 1)

    def test_shortcuts_ignore_events_captured_by_text_input(self):
        ext = make_extension()
        ext._detection_type = "Auto"
        ext._request_auto_detect = lambda: None

        handled = ext._handle_shortcut_event(
            types.SimpleNamespace(type="KEY_PRESS", input="KEY_3", modifiers=0, ui_keyboard_capture=True)
        )

        self.assertFalse(handled)
        self.assertEqual(ext._detection_type, "Auto")

    def test_shortcuts_ignore_events_with_ui_keyboard_capture_flag(self):
        ext = make_extension()
        ext._detection_type = "Auto"
        ext._request_auto_detect = lambda: None
        extension.ui.Widget = types.SimpleNamespace(FLAG_WANT_CAPTURE_KEYBOARD=1 << 4)

        handled = ext._handle_shortcut_event(
            types.SimpleNamespace(type="KEY_PRESS", input="KEY_3", modifiers=0, flags=1 << 4)
        )

        self.assertFalse(handled)
        self.assertEqual(ext._detection_type, "Auto")

    def test_feature_type_shortcuts_require_control_modifier(self):
        ext = make_extension()
        ext._detection_type = "Auto"
        ext._request_auto_detect = lambda: None

        self.assertFalse(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input="KEY_4", modifiers=0)))
        self.assertEqual(ext._detection_type, "Auto")

        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="KEY_4",
                    modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL,
                )
            )
        )
        self.assertEqual(ext._detection_type, "Cone")

    def test_control_backtick_shortcut_accepts_physical_key_names(self):
        for key_name in (
            "KEY_GRAVE",
            "KEY_GRAVE_ACCENT",
            "GRAVE",
            "GRAVE_ACCENT",
            "BACKQUOTE",
            "BACK_QUOTE",
            "BACK_APOSTROPHE",
            "OEM_3",
            "OEM3",
            "QUOTELEFT",
            "`",
        ):
            with self.subTest(key_name=key_name):
                ext = make_extension()
                ext._detection_type = "Plane"
                requests = []
                ext._request_auto_detect = lambda: requests.append(True)

                self.assertFalse(ext._handle_shortcut_event(types.SimpleNamespace(type="KEY_PRESS", input=key_name, modifiers=0)))

                handled = ext._handle_shortcut_event(
                    types.SimpleNamespace(
                        type="KEY_PRESS",
                        input=key_name,
                        modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL,
                    )
                )

                self.assertTrue(handled)
                self.assertEqual(ext._detection_type, "Auto")
                self.assertEqual(requests, [True])

    def test_control_backtick_shortcut_accepts_control_boolean_names(self):
        for control_name in ("control", "ctrl", "is_ctrl_down", "is_control_down", "control_down", "ctrl_down"):
            with self.subTest(control_name=control_name):
                ext = make_extension()
                ext._detection_type = "Plane"
                ext._request_auto_detect = lambda: None
                event = types.SimpleNamespace(type="KEY_PRESS", input="BACKQUOTE", modifiers=0)
                setattr(event, control_name, True)

                self.assertTrue(ext._handle_shortcut_event(event))
                self.assertEqual(ext._detection_type, "Auto")

    def test_shortcuts_dispatch_control_save_undo_and_capture(self):
        ext = make_extension()
        calls = []
        ext._undo_last = lambda: calls.append("undo")
        ext._redo_last = lambda: calls.append("redo")
        ext._save_workspace = lambda: calls.append("save")
        ext._can_capture_selected_preview = lambda: True
        ext._capture_selected_preview = lambda: calls.append("capture")

        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(type="KEY_PRESS", input="Z", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL)
            )
        )
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(
                    type="KEY_PRESS",
                    input="Z",
                    modifiers=(
                        extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL
                        | extension.carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT
                    ),
                )
            )
        )
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(type="KEY_PRESS", input="S", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL)
            )
        )
        self.assertTrue(
            ext._handle_shortcut_event(
                types.SimpleNamespace(type="KEY_PRESS", input="C", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL)
            )
        )
        self.assertFalse(
            ext._handle_shortcut_event(
                types.SimpleNamespace(type="KEY_RELEASE", input="S", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL)
            )
        )

        self.assertEqual(calls, ["undo", "redo", "save", "capture"])

    def test_undo_and_redo_buttons_follow_transaction_state(self):
        ext = make_extension()

        ext._refresh_toolbar_state()

        self.assertFalse(ext._toolbar_undo_button.enabled)
        self.assertFalse(ext._undo_button.enabled)
        self.assertFalse(ext._redo_button.enabled)

        ext._state.apply_result(
            surface_preview.SurfaceResult(
                id="Plane_1",
                type="Plane",
                seed_position=(1.0, 0.0, 0.0),
                inlier_indices=[1],
            )
        )
        ext._refresh_toolbar_state()

        self.assertTrue(ext._toolbar_undo_button.enabled)
        self.assertTrue(ext._undo_button.enabled)
        self.assertFalse(ext._redo_button.enabled)

        ext._state.undo_last()
        ext._refresh_toolbar_state()

        self.assertFalse(ext._toolbar_undo_button.enabled)
        self.assertFalse(ext._undo_button.enabled)
        self.assertTrue(ext._redo_button.enabled)

    def test_export_button_requires_captured_geometry(self):
        ext = make_extension()

        ext._refresh_toolbar_state()

        self.assertFalse(ext._export_button.enabled)

        ext._state.apply_result(
            surface_preview.SurfaceResult(
                id="Plane_1",
                type="Plane",
                seed_position=(1.0, 0.0, 0.0),
                inlier_indices=[1],
            )
        )
        ext._refresh_toolbar_state()

        self.assertTrue(ext._export_button.enabled)

        ext._state.undo_last()
        ext._refresh_toolbar_state()

        self.assertFalse(ext._export_button.enabled)

    def test_build_menus_adds_edit_undo_redo_reset(self):
        ext = make_extension()
        ext._ext_id = "com.findsurface.bootstrap"
        captured = {}
        original_description = extension.MenuItemDescription
        original_add = extension.omni.kit.menu.utils.add_menu_items
        try:
            extension.MenuItemDescription = lambda **kwargs: types.SimpleNamespace(**kwargs)
            extension.omni.kit.menu.utils.add_menu_items = (
                lambda items, menu_name, priority=None: captured.setdefault(menu_name, items)
            )

            ext._build_menus()
        finally:
            extension.MenuItemDescription = original_description
            extension.omni.kit.menu.utils.add_menu_items = original_add

        self.assertEqual([item.name for item in captured["Edit"]], ["Undo", "Redo", "Reset"])
        self.assertEqual(
            [item.name for item in captured["File"]],
            ["Load", "Save", "Save As...", "", "Import Points", "Export Geometries", "Close"],
        )
        self.assertEqual(
            [item.name for item in captured["Window"][3:8]],
            ["FindSurface", "Geometries", "Camera", "Settings", "Transactions"],
        )
        self.assertIn("Edit", ext._menu_items)

    def test_transaction_state_change_queues_window_refresh(self):
        ext = make_extension()
        queued = []
        ext._queue_transactions_window_refresh = lambda: queued.append(True)
        ext._refresh_transactions_window = lambda: self.fail("Transactions window refreshed synchronously")

        ext._after_transaction_index_changed()

        self.assertEqual(queued, [True])

    def test_shutdown_blocks_deferred_window_refresh_scheduling(self):
        ext = make_extension()
        ext._app_shutting_down = True
        ext._transactions_window_frame = lambda: object()
        ext._geometries_window_frame = lambda: object()
        original_ensure_future = extension.asyncio.ensure_future
        try:
            extension.asyncio.ensure_future = lambda task: self.fail("refresh task should not be scheduled")

            ext._queue_transactions_window_refresh()
            ext._queue_geometries_window_refresh()
        finally:
            extension.asyncio.ensure_future = original_ensure_future

        self.assertIsNone(ext._transactions_refresh_task)
        self.assertIsNone(ext._geometry_refresh_task)

    def test_clear_ui_references_drops_widget_callbacks(self):
        ext = make_extension()
        ext._toolbar_detection_buttons = {"Plane": Button()}
        ext._toolbar_projection_buttons = {"ortho": Button()}
        ext._visibility_buttons = {"inliers": Button()}
        ext._geometry_collapsed = {"Plane_1": True}

        ext._clear_ui_references()

        self.assertIsNone(ext._toolbar_undo_button)
        self.assertIsNone(ext._undo_button)
        self.assertIsNone(ext._redo_button)
        self.assertEqual(ext._toolbar_detection_buttons, {})
        self.assertEqual(ext._toolbar_projection_buttons, {})
        self.assertEqual(ext._visibility_buttons, {})
        self.assertEqual(ext._geometry_collapsed, {})

    def test_clear_ui_references_releases_toolbar_icon_images(self):
        ext = make_extension()
        released = []

        class Releasable:
            def release(self):
                released.append(id(self))

        save = Releasable()
        detection_button = Releasable()
        visibility_button = Releasable()
        ext._save_button = save
        ext._toolbar_detection_buttons = {"Plane": detection_button}
        ext._visibility_buttons = {"meshes": visibility_button}

        ext._clear_ui_references()

        self.assertEqual(set(released), {id(save), id(detection_button), id(visibility_button)})

    def test_control_capture_shortcut_requires_capturable_preview(self):
        ext = make_extension()
        calls = []
        ext._can_capture_selected_preview = lambda: False
        ext._capture_selected_preview = lambda: calls.append("capture")

        self.assertFalse(
            ext._handle_shortcut_event(
                types.SimpleNamespace(type="KEY_PRESS", input="C", modifiers=extension.carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL)
            )
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
