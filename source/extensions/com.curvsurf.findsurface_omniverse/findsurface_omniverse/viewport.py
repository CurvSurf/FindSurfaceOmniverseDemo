import math
import numbers
from ctypes import c_uint8

import carb
import carb.input
import omni.appwindow
import omni.ui as ui
from omni.ui import scene as sc

from . import app_config
from .camera import PROJECTION_ORTHOGRAPHIC, PROJECTION_PERSPECTIVE, OrbitCamera, add, cross, dot, mul, normalize, sub
from .native_picking import NativePointPicker
from .surface_preview import (
    SURFACE_SOLID_COLOR,
    SURFACE_WIRE_COLOR,
    SURFACE_WIRE_THICKNESS,
    build_surface_preview_mesh,
    mesh_bounds,
)


LEFT_BUTTON = 0
RIGHT_BUTTON = 1
MIDDLE_BUTTON = 2
POINT_CHUNK_SIZE = 100000
PROBE_CIRCLE_SEGMENTS = 64
PROBE_CIRCLE_COLOR = [0.86, 0.48, 1.0, 0.95]
PROBE_CIRCLE_POINT_SIZE = 2.0
SEED_RADIUS_CIRCLE_COLOR = [1.0, 1.0, 1.0, 0.9]
SEED_RADIUS_CIRCLE_POINT_SIZE = 1.8
SELECTED_POINT_CLOUD_COLOR = [0.16, 0.17, 0.19, 1.0]
SELECTED_SURFACE_SOLID_COLOR = [1.0, 0.72, 0.18, 0.16]
SELECTED_SURFACE_WIRE_COLOR = [1.0, 0.78, 0.16, 1.0]
SELECTED_SURFACE_WIRE_THICKNESS = 4.0
INLIER_NEGATIVE_COLOR = [0.0, 0.22, 1.0, 1.0]
INLIER_ZERO_COLOR = [1.0, 1.0, 0.0, 1.0]
INLIER_POSITIVE_COLOR = [1.0, 0.02, 0.0, 1.0]
INLIER_NEAR_COLOR = INLIER_ZERO_COLOR
INLIER_FAR_COLOR = INLIER_POSITIVE_COLOR
INLIER_DISTANCE_HISTOGRAM_MIN_BINS = 23
INLIER_DISTANCE_HISTOGRAM_MAX_BINS = 47
INLIER_DISTANCE_HISTOGRAM_BINS = 35
INLIER_DISTANCE_HISTOGRAM_OUTLIER_SIGMA = 3.0
ORIENTATION_WIDGET_SIZE = 92
ORIENTATION_AXIS_LENGTH = 0.58
ORIENTATION_GIZMO_RADIUS = 0.68
ORIENTATION_GIZMO_HIT_PADDING = 10.0
ORIENTATION_GIZMO_DEGREES_PER_PIXEL = 0.75
ORIENTATION_GIZMO_SEGMENTS = 72
ORIENTATION_GIZMO_COLORS = {
    "horizontal": [0.25, 0.95, 0.25, 0.82],
    "vertical": [1.0, 0.12, 0.10, 0.82],
    "roll": [0.2, 0.45, 1.0, 0.82],
}
ORIENTATION_GIZMO_HOVER_BLEND = 0.38
ORIENTATION_GIZMO_ACTIVE_COLOR = [0.96, 0.97, 1.0, 1.0]
ORIENTATION_GIZMO_AXIS_INDEX = {
    "vertical": 0,
    "horizontal": 1,
    "roll": 2,
}
ORIENTATION_GIZMO_AXES = {
    "vertical": [1.0, 0.0, 0.0],
    "horizontal": [0.0, 1.0, 0.0],
    "roll": [0.0, 0.0, 1.0],
}
ORIENTATION_AXIS_COLORS = (
    ([1.0, 0.12, 0.10, 1.0], [ORIENTATION_AXIS_LENGTH, 0.0, 0.0]),
    ([0.25, 0.95, 0.25, 1.0], [0.0, ORIENTATION_AXIS_LENGTH, 0.0]),
    ([0.2, 0.45, 1.0, 1.0], [0.0, 0.0, ORIENTATION_AXIS_LENGTH]),
)
SCALE_RULER_WIDTH = 100.0
SCALE_RULER_HEIGHT = 10.0
SCALE_RULER_LEFT_MARGIN = 18.0
SCALE_RULER_BOTTOM_MARGIN = ORIENTATION_WIDGET_SIZE + 44.0
SCALE_RULER_LABEL_HEIGHT = 20.0
SCALE_RULER_LABEL_WIDTH = 128.0
SCALE_RULER_LABEL_MIN_WIDTH = 66.0
SCALE_RULER_LABEL_CHAR_WIDTH = 6.7
SCALE_RULER_LABEL_EXTRA_WIDTH = 10.0
SCALE_RULER_LABEL_GAP = 4.0
SCALE_RULER_MIN_MARGIN = 8.0
SCALE_RULER_HIT_PADDING = 8.0
SCALE_RULER_HOVER_PADDING = 8.0
SCALE_RULER_HOVER_BACKGROUND_COLOR = 0x24FFFFFF
SCALE_RULER_HOVER_BORDER_RADIUS = 6
SCALE_RULER_COLOR = [1.0, 1.0, 1.0, 0.94]
SCALE_RULER_THICKNESS = 2.0
VIEWPORT_OVERLAY_MARGIN = 14
DATA_OVERLAY_WIDTH = 282
DATA_OVERLAY_HEIGHT = 74
DATA_OVERLAY_TEXT_PADDING = 12
HOVER_DETECTION_OVERLAY_WIDTH = 310
HOVER_DETECTION_OVERLAY_HEIGHT = 196
HOVER_DETECTION_ICON_SIZE = 24
HOVER_DETECTION_HISTOGRAM_WIDTH = 286
HOVER_DETECTION_HISTOGRAM_HEIGHT = 48
HOVER_DETECTION_HISTOGRAM_BAR_MAX_HEIGHT = 34
HOVER_DETECTION_HISTOGRAM_SPACING = 2


class _ViewportCameraModel(sc.AbstractManipulatorModel):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def invalidate_camera(self):
        self._item_changed("projection")
        self._item_changed("view")

    def get_as_floats(self, item):
        if item == self.get_item("projection"):
            return self._viewport.projection_matrix()
        if item == self.get_item("view"):
            return self._viewport.view_matrix()
        return []


class _OrientationCameraModel(sc.AbstractManipulatorModel):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def invalidate_camera(self):
        self._item_changed("projection")
        self._item_changed("view")

    def get_as_floats(self, item):
        if item == self.get_item("projection"):
            near = 0.1
            far = 10.0
            return [
                1.35,
                0.0,
                0.0,
                0.0,
                0.0,
                1.35,
                0.0,
                0.0,
                0.0,
                0.0,
                -2.0 / (far - near),
                0.0,
                0.0,
                0.0,
                -(far + near) / (far - near),
                1.0,
            ]
        if item == self.get_item("view"):
            return self._viewport.orientation_view_matrix()
        return []


class _PickOverlay(sc.Manipulator):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def on_build(self):
        if self._viewport.point_cloud:
            self._viewport._draw_pick_markers()
            self._viewport._draw_probe_circle()
            self._viewport._draw_seed_radius_circle()


class _SurfaceOverlay(sc.Manipulator):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def on_build(self):
        self._viewport._draw_surfaces()


class _InlierOverlay(sc.Manipulator):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def on_build(self):
        self._viewport._draw_inliers()


class _OrientationOverlay(sc.Manipulator):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def on_build(self):
        self._viewport._draw_orientation_widget()


class _ScaleRulerOverlay(sc.Manipulator):
    def __init__(self, viewport):
        super().__init__()
        self._viewport = viewport

    def on_build(self):
        self._viewport._draw_scale_ruler()


class PointCloudViewport:
    def __init__(
        self,
        on_camera_changed=None,
        on_hover_changed=None,
        on_seed_selected=None,
        input_blocked_fn=None,
        config=None,
    ):
        config = config or {}
        self.camera = OrbitCamera(app_config.config_value(config, ("camera",), {}))
        self.point_cloud = None
        self.active_mask = None
        self._active_mask_buffer = None
        self.point_color = app_config.config_rgba(config, ("display", "point_color"), [1.0, 1.0, 1.0, 1.0])
        self.selected_point_color = app_config.config_rgba(config, ("display", "selected_point_color"), SELECTED_POINT_CLOUD_COLOR)
        self.surface_color = app_config.config_rgba(config, ("display", "surface_color"), SURFACE_SOLID_COLOR)
        self.surface_wire_color = app_config.config_rgba(config, ("display", "surface_wire_color"), SURFACE_WIRE_COLOR)
        self.inlier_negative_color = app_config.config_rgba(config, ("display", "inlier_negative_color"), INLIER_NEGATIVE_COLOR)
        self.inlier_zero_color = app_config.config_rgba(config, ("display", "inlier_zero_color"), INLIER_ZERO_COLOR)
        self.inlier_positive_color = app_config.config_rgba(config, ("display", "inlier_positive_color"), INLIER_POSITIVE_COLOR)
        self.inlier_near_color = self.inlier_zero_color
        self.inlier_far_color = self.inlier_positive_color
        self.inlier_negative_sigma = app_config.config_float(config, ("display", "inlier_negative_sigma"), -1.0, -3.0, -0.5)
        self.inlier_positive_sigma = app_config.config_float(config, ("display", "inlier_positive_sigma"), 1.0, 0.5, 3.0)
        self.point_size = app_config.config_float(config, ("display", "point_size"), 1.0, 1.0)
        self.inlier_color = [1.0, 0.62, 0.12, 1.0]
        self.outlier_points_visible = app_config.config_bool(config, ("display", "global_visibility", "outlier_points"), True)
        self.surface_meshes_visible = app_config.config_bool(config, ("display", "global_visibility", "surface_meshes"), True)
        self.inlier_points_visible = app_config.config_bool(config, ("display", "global_visibility", "inlier_points"), True)
        self.hover_index = None
        self.selected_index = None
        self.selected_result_id = None
        self.retroactive_pick_index = None
        self.retroactive_pick_active = False
        self.picking_enabled = True
        self.probe_radius_px = app_config.config_float(config, ("picking", "probe_radius_px"), 6.0, 1.0)
        self.pick_nearest_on_probe_miss = app_config.config_bool(config, ("picking", "pick_nearest_on_probe_miss"), True)
        self.seed_radius = app_config.config_float(
            config,
            ("detection", "range_parameters", "seed_radius", "value"),
            0.15,
            0.0,
        )
        self.surface_results = []
        self._surface_meshes = self._build_surface_meshes()
        self._inlier_chunk_cache = {}
        self._inlier_point_chunks = []
        self._camera_model = _ViewportCameraModel(self)
        self._orientation_camera_model = _OrientationCameraModel(self)
        self._scene_view = None
        self._orientation_view = None
        self._orientation_input_rect = None
        self._orientation_overlay = None
        self._scale_ruler_overlay = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False
        self._data_overlay_labels = {}
        self._data_overlay_state = {}
        self._hover_detection_overlay_frame = None
        self._hover_detection_overlay_state = {"visible": False}
        self._orientation_hover_axis = None
        self._surface_overlay = None
        self._inlier_overlay = None
        self._pick_overlay = None
        self._scale_ruler_overlay = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False
        self._input_rect = None
        self._input = None
        self._mouse = None
        self._app_window = None
        self._ui_scale = 1.0
        self._drag = None
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        self._mouse_over_input_rect = False
        self._click_pick_index = None
        self._on_camera_changed = on_camera_changed
        self._on_hover_changed = on_hover_changed
        self._on_seed_selected = on_seed_selected
        self._input_blocked_fn = input_blocked_fn
        self._native_picker = self._create_native_picker()
        self._destroyed = False
        self._scene_resources_released = False
        self._fit_camera_to_surfaces()

    def build(self):
        with ui.ZStack():
            ui.Rectangle(style={"background_color": 0xFF17191D})
            self._scene_view = sc.SceneView(
                self._camera_model,
                aspect_ratio_policy=sc.AspectRatioPolicy.STRETCH,
            )
            self._build_data_overlay()
            self._build_hover_detection_overlay()
            self._build_scale_ruler_label()
            self._input_rect = ui.Rectangle(
                style={"background_color": 0x00000000},
                opaque_for_mouse_events=True,
                mouse_pressed_fn=self._on_mouse_pressed,
                mouse_moved_fn=self._on_mouse_moved,
                mouse_released_fn=self._on_mouse_released,
                mouse_wheel_fn=self._on_mouse_wheel,
                mouse_hovered_fn=self._on_mouse_hovered,
            )
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=ORIENTATION_WIDGET_SIZE + 24):
                    ui.Spacer(width=18)
                    with ui.ZStack(width=ORIENTATION_WIDGET_SIZE, height=ORIENTATION_WIDGET_SIZE):
                        ui.Rectangle(style={"background_color": 0x661B1E24, "border_radius": 6})
                        self._orientation_view = sc.SceneView(
                            self._orientation_camera_model,
                            aspect_ratio_policy=sc.AspectRatioPolicy.STRETCH,
                        )
                        self._orientation_input_rect = ui.Rectangle(
                            style={"background_color": 0x00000000},
                            opaque_for_mouse_events=True,
                            mouse_pressed_fn=self._on_orientation_mouse_pressed,
                            mouse_moved_fn=self._on_orientation_mouse_moved,
                            mouse_released_fn=self._on_orientation_mouse_released,
                            mouse_hovered_fn=self._on_orientation_mouse_hovered,
                        )
                    ui.Spacer()
                ui.Spacer(height=14)
        self._init_mouse_polling()
        self._rebuild_orientation_widget()
        self._rebuild_scene()

    def set_point_cloud(self, point_cloud, active_mask=None):
        if self._destroyed:
            return
        self.point_cloud = point_cloud
        self.active_mask = active_mask
        self._set_active_mask_buffer(active_mask, point_cloud.count if point_cloud else 0)
        self._inlier_chunk_cache = {}
        self._inlier_point_chunks = self._build_inlier_point_chunks()
        self.hover_index = None
        self.selected_index = None
        self.selected_result_id = None
        self.retroactive_pick_index = None
        self.retroactive_pick_active = False
        self._orientation_hover_axis = None
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        self._mouse_over_input_rect = False
        self._click_pick_index = None
        if point_cloud:
            self.camera.fit(point_cloud.bounds_min, point_cloud.bounds_max)
        self._rebuild_scene()
        self._notify_camera_changed()

    def clear(self):
        if self._destroyed:
            return
        self.point_cloud = None
        self.active_mask = None
        self._active_mask_buffer = None
        self._inlier_chunk_cache = {}
        self._inlier_point_chunks = []
        self.hover_index = None
        self.selected_index = None
        self.selected_result_id = None
        self.retroactive_pick_index = None
        self.retroactive_pick_active = False
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        self._mouse_over_input_rect = False
        self._click_pick_index = None
        self._fit_camera_to_surfaces()
        self._rebuild_scene()
        self._notify_camera_changed()

    def release_scene_resources(self, clear_scene=True):
        self._scene_resources_released = True
        self._on_camera_changed = None
        self._on_hover_changed = None
        self._on_seed_selected = None
        self._input_blocked_fn = None
        self.point_cloud = None
        self.active_mask = None
        self._active_mask_buffer = None
        self.surface_results = []
        self.selected_result_id = None
        self._surface_meshes = []
        self._inlier_chunk_cache = {}
        self._inlier_point_chunks = []
        self.hover_index = None
        self.selected_index = None
        self.retroactive_pick_index = None
        self.retroactive_pick_active = False
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        self._drag = None
        self._click_pick_index = None
        if clear_scene and self._scene_view:
            try:
                self._scene_view.scene.clear()
            except Exception:
                pass
        if clear_scene and self._orientation_view:
            try:
                self._orientation_view.scene.clear()
            except Exception:
                pass
        self._pick_overlay = None
        self._surface_overlay = None
        self._inlier_overlay = None
        self._scale_ruler_overlay = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False
        self._orientation_overlay = None
        self._scale_ruler_overlay = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False
        self._data_overlay_labels = {}
        self._hover_detection_overlay_frame = None
        self._orientation_hover_axis = None
        self._input = None
        self._mouse = None
        self._app_window = None
        self._native_picker = None

    def destroy(self, clear_scene=True):
        if self._destroyed:
            return
        scene_resources_were_released = getattr(self, "_scene_resources_released", False)
        scene_views = (self._scene_view, self._orientation_view)
        if not scene_resources_were_released:
            self.release_scene_resources(clear_scene=clear_scene)
        self._destroyed = True
        for scene_view in scene_views:
            if scene_view and hasattr(scene_view, "destroy"):
                try:
                    scene_view.destroy()
                except Exception:
                    pass
        self._scene_view = None
        self._orientation_view = None
        if self._camera_model:
            self._camera_model._viewport = None
        if self._orientation_camera_model:
            self._orientation_camera_model._viewport = None
        self._camera_model = None
        self._orientation_camera_model = None
        self._input_rect = None
        self._orientation_input_rect = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False
        self._data_overlay_labels = {}
        self._hover_detection_overlay_frame = None
        self._orientation_hover_axis = None
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        self._scale_ruler_position = None
        self._scale_ruler_hovered = False

    def set_data_overlay(
        self,
        dataset_name=None,
        active_count=None,
        point_count=None,
        removed_count=None,
        hover_index=None,
        selected_index=None,
    ):
        if self._destroyed:
            return
        self._data_overlay_state = {
            "dataset_name": dataset_name,
            "active_count": active_count,
            "point_count": point_count,
            "removed_count": removed_count,
            "hover_index": hover_index,
            "selected_index": selected_index,
        }
        self._refresh_data_overlay()

    def set_hover_detection_overlay(self, visible=False, result_type=None, rows=None, histogram=None, icon_path=None):
        if self._destroyed:
            return
        self._hover_detection_overlay_state = {
            "visible": bool(visible),
            "result_type": result_type,
            "rows": list(rows or []),
            "histogram": histogram,
            "icon_path": icon_path,
        }
        self._refresh_hover_detection_overlay()

    def set_active_mask(self, active_mask):
        if self._destroyed:
            return
        self.active_mask = active_mask
        self._set_active_mask_buffer(active_mask, self.point_cloud.count if self.point_cloud else 0)
        self._rebuild_scene()

    def set_pick_markers(self, hover_index=None, selected_index=None):
        if self._destroyed:
            return
        had_selection = self.selected_index is not None
        self.selected_index = selected_index
        self.hover_index = None if self.selected_index is not None else hover_index
        if had_selection != (self.selected_index is not None):
            self._rebuild_scene()
        else:
            self._refresh_pick_overlay()

    def set_retroactive_pick_index(self, index):
        if self._destroyed:
            return
        index = None if index is None else int(index)
        if index == self.retroactive_pick_index:
            return
        self.retroactive_pick_index = index
        self._refresh_pick_overlay()

    def set_retroactive_pick_active(self, active):
        if self._destroyed:
            return
        active = bool(active)
        if active == self.retroactive_pick_active:
            return
        self.retroactive_pick_active = active
        self._refresh_pick_overlay()

    def set_picking_enabled(self, enabled):
        self.picking_enabled = bool(enabled)
        self._click_pick_index = None
        if not self.picking_enabled:
            self._clear_hover_pick()

    def set_probe_radius(self, radius_px):
        self.probe_radius_px = max(1.0, float(radius_px))
        if self.picking_enabled and self._last_hover_mouse:
            self.update_hover_pick(*self._last_hover_mouse)

    def set_pick_nearest_on_probe_miss(self, enabled):
        self.pick_nearest_on_probe_miss = bool(enabled)
        if self.picking_enabled and self._last_hover_mouse:
            self.update_hover_pick(*self._last_hover_mouse)

    def set_seed_radius(self, radius):
        self.seed_radius = max(0.0, float(radius))
        self._refresh_pick_overlay()

    def set_surfaces(self, results):
        self.surface_results = list(results or [])
        if self.selected_result_id and not self._find_surface_result(self.selected_result_id):
            self.selected_result_id = None
        self._surface_meshes = self._build_surface_meshes()
        self._inlier_point_chunks = self._build_inlier_point_chunks()
        if not self.point_cloud:
            self._fit_camera_to_surfaces()
        if self._surface_overlay or self._inlier_overlay:
            self._refresh_surface_overlay()
            self._refresh_inlier_overlay()
            self.draw()
        else:
            self._rebuild_scene()
        self._notify_camera_changed()

    def clear_surfaces(self):
        self.set_surfaces([])

    def set_global_visibility(self, outlier_points=None, surface_meshes=None, inlier_points=None):
        rebuild_scene = False
        refresh_surfaces = False
        refresh_inliers = False
        if outlier_points is not None and self.outlier_points_visible != bool(outlier_points):
            self.outlier_points_visible = bool(outlier_points)
            rebuild_scene = True
        if surface_meshes is not None and self.surface_meshes_visible != bool(surface_meshes):
            self.surface_meshes_visible = bool(surface_meshes)
            self._surface_meshes = self._build_surface_meshes()
            refresh_surfaces = True
        if inlier_points is not None and self.inlier_points_visible != bool(inlier_points):
            self.inlier_points_visible = bool(inlier_points)
            self._inlier_point_chunks = self._build_inlier_point_chunks()
            refresh_inliers = True
        if rebuild_scene:
            self._rebuild_scene()
            return
        if refresh_surfaces:
            self._refresh_surface_overlay()
        if refresh_inliers:
            self._refresh_inlier_overlay()
        if refresh_surfaces or refresh_inliers:
            self.draw()

    def set_result_visibility(self, result_id, mesh_visible=None, inliers_visible=None):
        changed = False
        for result in self.surface_results:
            if getattr(result, "id", None) != result_id:
                continue
            if mesh_visible is not None and getattr(result, "mesh_visible", True) != bool(mesh_visible):
                setattr(result, "mesh_visible", bool(mesh_visible))
                changed = True
            if inliers_visible is not None and getattr(result, "inliers_visible", True) != bool(inliers_visible):
                setattr(result, "inliers_visible", bool(inliers_visible))
                changed = True
        if not changed:
            return
        self._surface_meshes = self._build_surface_meshes()
        self._inlier_point_chunks = self._build_inlier_point_chunks()
        self._refresh_surface_overlay()
        self._refresh_inlier_overlay()
        self.draw()

    def set_selected_result(self, result_id):
        result_id = None if result_id is None else str(result_id)
        if result_id and not self._find_surface_result(result_id):
            result_id = None
        if result_id == self.selected_result_id:
            return False
        self.selected_result_id = result_id
        self._surface_meshes = self._build_surface_meshes()
        self._refresh_surface_overlay()
        self.draw()
        return True

    def focus_result(self, result_id):
        bounds = self.result_bounds(result_id)
        if not bounds:
            return False
        self._notify_camera_changed("begin")
        self.camera.fit(bounds[0], bounds[1])
        self.draw()
        self._notify_camera_changed("commit")
        return True

    def result_bounds(self, result_id):
        result = self._find_surface_result(result_id)
        if not result:
            return None
        mesh = build_surface_preview_mesh(result, solid_color=self.surface_color)
        if mesh:
            bounds = mesh_bounds([mesh])
            if bounds:
                return bounds
        return self._result_inlier_bounds(result)

    def set_point_color(self, color):
        self.point_color = _rgba(color, fallback=self.point_color)
        self._rebuild_scene()

    def set_selected_point_color(self, color):
        self.selected_point_color = _rgba(color, fallback=self.selected_point_color)
        self._rebuild_scene()

    def set_point_size(self, size):
        self.point_size = max(1.0, float(size))
        self._rebuild_scene()

    def set_inlier_colors(
        self,
        negative_color=None,
        zero_color=None,
        positive_color=None,
        negative_sigma=None,
        positive_sigma=None,
        near_color=None,
        far_color=None,
    ):
        if near_color is not None and zero_color is None:
            zero_color = near_color
        if far_color is not None and positive_color is None:
            positive_color = far_color
        if negative_color is not None:
            self.inlier_negative_color = _rgba(negative_color, fallback=self.inlier_negative_color)
        if zero_color is not None:
            self.inlier_zero_color = _rgba(zero_color, fallback=self.inlier_zero_color)
        if positive_color is not None:
            self.inlier_positive_color = _rgba(positive_color, fallback=self.inlier_positive_color)
        if negative_sigma is not None:
            self.inlier_negative_sigma = _negative_sigma(negative_sigma)
        if positive_sigma is not None:
            self.inlier_positive_sigma = _positive_sigma(positive_sigma)
        self.inlier_near_color = self.inlier_zero_color
        self.inlier_far_color = self.inlier_positive_color
        self._inlier_chunk_cache = {}
        self._inlier_point_chunks = self._build_inlier_point_chunks()
        self._refresh_inlier_overlay()

    def set_surface_color(self, color):
        self.surface_color = _rgba(color, fallback=self.surface_color)
        self._surface_meshes = self._build_surface_meshes()
        self._refresh_surface_overlay()

    def set_surface_wire_color(self, color):
        self.surface_wire_color = _rgba(color, fallback=self.surface_wire_color)
        self._refresh_surface_overlay()

    def draw(self):
        if self._destroyed:
            return
        self._camera_model.invalidate_camera()
        self._orientation_camera_model.invalidate_camera()
        if self._orientation_overlay:
            self._orientation_overlay.invalidate()
        self._refresh_scale_ruler_label()
        if self._scale_ruler_overlay:
            self._scale_ruler_overlay.invalidate()
        if self._pick_overlay:
            self._pick_overlay.invalidate()
        if self._scale_ruler_overlay:
            self._scale_ruler_overlay.invalidate()
        self._refresh_scale_ruler_label()

    def set_projection_mode(self, mode):
        self.camera.set_projection_mode(mode)
        self.draw()
        self._notify_camera_changed()

    def set_fov_degrees(self, fov_degrees):
        self.camera.set_fov_degrees(fov_degrees)
        self.draw()
        self._notify_camera_changed()

    def poll_hover_pick(self):
        if self._destroyed:
            return
        if not self._input or not self._mouse:
            self._init_mouse_polling()
        if not self._input or not self._mouse:
            return
        x, y = self._poll_mouse_position()
        if x is None:
            return
        if self._input_blocked(x, y):
            self._set_scale_ruler_hovered(False)
            if self._last_hover_mouse or self.hover_index is not None:
                self._clear_hover_pick()
            return
        if self._poll_orientation_hover(x, y):
            self._set_scale_ruler_hovered(False)
            return
        if self._scale_ruler_hit_test(x, y):
            self._set_scale_ruler_hovered(True)
            if self._last_hover_mouse or self.hover_index is not None:
                self._clear_hover_pick()
            return
        self._set_scale_ruler_hovered(False)
        if not self.picking_enabled or not self._has_scene_content() or self._drag or not self._input_rect:
            return
        if self._last_polled_mouse == (x, y):
            return
        self._last_polled_mouse = (x, y)
        if self._is_screen_point_inside(x, y):
            self._mouse_over_input_rect = True
            self.update_hover_pick(x, y)
        elif self._mouse_over_input_rect or self._last_hover_mouse:
            self._mouse_over_input_rect = False
            self._clear_hover_pick()

    def _rebuild_scene(self):
        if self._destroyed or not self._scene_view:
            return
        self._scene_view.scene.clear()
        self._pick_overlay = None
        self._surface_overlay = None
        self._inlier_overlay = None
        self._scale_ruler_overlay = None
        if not self._has_scene_content():
            with self._scene_view.scene:
                self._scale_ruler_overlay = _ScaleRulerOverlay(self)
            self.draw()
            return

        color = self._point_cloud_color()

        with self._scene_view.scene:
            if self.point_cloud and self.outlier_points_visible:
                chunk = []
                for index, point in enumerate(self.point_cloud.points):
                    if self.active_mask is not None and index < len(self.active_mask) and not self.active_mask[index]:
                        continue
                    chunk.append(point)
                    if len(chunk) >= POINT_CHUNK_SIZE:
                        sc.Points(chunk, sizes=[self.point_size] * len(chunk), colors=[color] * len(chunk))
                        chunk = []
                if chunk:
                    sc.Points(chunk, sizes=[self.point_size] * len(chunk), colors=[color] * len(chunk))
            self._surface_overlay = _SurfaceOverlay(self)
            if self.point_cloud:
                self._inlier_overlay = _InlierOverlay(self)
            if self.point_cloud:
                self._draw_bounding_box()
                self._pick_overlay = _PickOverlay(self)
            self._scale_ruler_overlay = _ScaleRulerOverlay(self)
        self.draw()

    def _rebuild_orientation_widget(self):
        if self._destroyed or not self._orientation_view:
            return
        self._orientation_view.scene.clear()
        with self._orientation_view.scene:
            self._orientation_overlay = _OrientationOverlay(self)
        self.draw()

    def _refresh_pick_overlay(self):
        if self._pick_overlay:
            self._pick_overlay.invalidate()
        elif self.point_cloud:
            self._rebuild_scene()

    def _refresh_surface_overlay(self):
        if self._surface_overlay:
            self._surface_overlay.invalidate()
        elif self._surface_meshes:
            self._rebuild_scene()

    def _refresh_inlier_overlay(self):
        if self._inlier_overlay:
            self._inlier_overlay.invalidate()
        elif self._inlier_point_chunks and self.point_cloud:
            self._rebuild_scene()

    def _build_surface_meshes(self):
        if not self.surface_meshes_visible:
            return []
        meshes = []
        for result in self.surface_results:
            if not getattr(result, "mesh_visible", True):
                continue
            result_id = getattr(result, "id", None)
            selected = self.selected_result_id is not None and result_id == self.selected_result_id
            mesh = build_surface_preview_mesh(
                result,
                solid_color=SELECTED_SURFACE_SOLID_COLOR if selected else self.surface_color,
            )
            if mesh:
                mesh.result_id = result_id
                mesh.selected = selected
                meshes.append(mesh)
        return meshes

    def _build_inlier_point_chunks(self):
        if not self.point_cloud or not self.inlier_points_visible:
            return []

        active_cache_keys = set()
        chunks = []
        color_key = (
            tuple(self.inlier_negative_color),
            tuple(self.inlier_zero_color),
            tuple(self.inlier_positive_color),
            round(float(self.inlier_negative_sigma), 6),
            round(float(self.inlier_positive_sigma), 6),
            tuple(self.inlier_color),
        )
        for result in self.surface_results:
            if not getattr(result, "inliers_visible", True):
                continue
            cache_key = (
                id(result),
                len(result.inlier_indices),
                repr(getattr(result, "parameters", None)),
                repr(getattr(result, "seed_position", None)),
                bool(getattr(result, "inliers_visible", True)),
                color_key,
            )
            active_cache_keys.add(cache_key)
            result_chunks = self._inlier_chunk_cache.get(cache_key)
            if result_chunks is None:
                result_chunks = self._build_result_inlier_chunks(result)
                self._inlier_chunk_cache[cache_key] = result_chunks
            chunks.extend(result_chunks)

        for cache_key in list(self._inlier_chunk_cache):
            if cache_key not in active_cache_keys:
                del self._inlier_chunk_cache[cache_key]
        return chunks

    def _build_result_inlier_chunks(self, result):
        chunks = []
        points = []
        distance_fn = _surface_distance_function(result)
        distances = []
        for index in result.inlier_indices:
            if index < 0 or index >= self.point_cloud.count:
                continue
            point = self.point_cloud.points[index]
            points.append(point)
            if distance_fn:
                distances.append(float(distance_fn(point)))

        if distance_fn:
            sigma = _standard_deviation(distances)
            colors = [
                _inlier_distance_color(
                    distance,
                    sigma,
                    self.inlier_negative_color,
                    self.inlier_zero_color,
                    self.inlier_positive_color,
                    self.inlier_negative_sigma,
                    self.inlier_positive_sigma,
                )
                for distance in distances
            ]
        else:
            colors = [list(self.inlier_color) for _point in points]

        chunk_points = []
        chunk_colors = []
        for point, color in zip(points, colors):
            chunk_points.append(point)
            chunk_colors.append(color)
            if len(chunk_points) >= POINT_CHUNK_SIZE:
                chunks.append((chunk_points, chunk_colors))
                chunk_points = []
                chunk_colors = []
        if chunk_points:
            chunks.append((chunk_points, chunk_colors))
        return chunks

    def _fit_camera_to_surfaces(self):
        bounds = mesh_bounds(self._surface_meshes)
        if bounds:
            self.camera.fit(bounds[0], bounds[1])

    def _has_scene_content(self):
        return bool(self.point_cloud or self._surface_meshes)

    def _draw_surfaces(self):
        for mesh in self._surface_meshes:
            if mesh.points and mesh.vertex_counts and mesh.vertex_indices:
                sc.PolygonMesh(mesh.points, mesh.colors, mesh.vertex_counts, mesh.vertex_indices)
            selected = bool(getattr(mesh, "selected", False))
            wire_color = SELECTED_SURFACE_WIRE_COLOR if selected else self.surface_wire_color
            wire_thickness = SELECTED_SURFACE_WIRE_THICKNESS if selected else SURFACE_WIRE_THICKNESS
            for line in mesh.wire_lines:
                if len(line) >= 2:
                    sc.Curve(
                        line,
                        colors=[wire_color],
                        thicknesses=[wire_thickness],
                        curve_type=sc.Curve.CurveType.LINEAR,
                    )

    def _find_surface_result(self, result_id):
        for result in self.surface_results:
            if getattr(result, "id", None) == result_id:
                return result
        return None

    def _result_inlier_bounds(self, result):
        if not self.point_cloud:
            return None
        points = []
        point_count = getattr(self.point_cloud, "count", len(getattr(self.point_cloud, "points", []) or []))
        source_points = getattr(self.point_cloud, "points", None) or []
        for index in getattr(result, "inlier_indices", []) or []:
            if 0 <= index < point_count:
                points.append(source_points[index])
        if not points:
            seed = getattr(result, "seed_position", None)
            if seed is None:
                return None
            points = [seed]
        return (
            [min(float(point[axis]) for point in points) for axis in range(3)],
            [max(float(point[axis]) for point in points) for axis in range(3)],
        )

    def _draw_inliers(self):
        if not self.point_cloud or not self._inlier_point_chunks:
            return
        size = max(self.point_size + 1.5, 3.0)
        for points, colors in self._inlier_point_chunks:
            sc.Points(points, sizes=[size] * len(points), colors=colors)

    def _point_cloud_color(self):
        if self.selected_index is not None:
            return list(self.selected_point_color)
        return list(self.point_color)

    def _draw_pick_markers(self):
        marker_points = []
        marker_colors = []
        marker_sizes = []
        for index, color, size in (
            (self._display_hover_index(), [1.0, 0.05, 0.05, 1.0], max(self.point_size + 3.0, 7.0)),
            (self.selected_index, [0.0, 1.0, 0.2, 1.0], max(self.point_size + 5.0, 10.0)),
        ):
            if index is None or index < 0 or index >= self.point_cloud.count:
                continue
            if self.active_mask is not None and index < len(self.active_mask) and not self.active_mask[index]:
                continue
            marker_points.append(self.point_cloud.points[index])
            marker_colors.append(color)
            marker_sizes.append(size)
        if marker_points:
            sc.Points(marker_points, colors=marker_colors, sizes=marker_sizes)

    def _display_hover_index(self):
        retroactive_index = self._valid_retroactive_pick_index()
        if self.selected_index is None and self.retroactive_pick_active and retroactive_index is not None:
            return retroactive_index
        return self.hover_index

    def _draw_probe_circle(self):
        if not self.picking_enabled or self._drag or not self._last_hover_mouse:
            return
        width, height = self._viewport_size()
        pixel_scale = self._pixel_scale(width, height)
        if pixel_scale <= 1.0e-8:
            return
        local_x, local_y = self._local_mouse(*self._last_hover_mouse)
        center = self._orthographic_screen_plane_point(local_x, local_y, width, height, pixel_scale)
        radius = self.probe_radius_px / pixel_scale
        self._draw_camera_plane_circle(
            center,
            radius,
            PROBE_CIRCLE_COLOR,
            point_size=PROBE_CIRCLE_POINT_SIZE,
            thickness=2.0,
        )

    def _draw_seed_radius_circle(self):
        spec = self._seed_radius_circle_spec()
        if not spec:
            return
        center, radius = spec
        self._draw_camera_plane_circle(
            center,
            radius,
            SEED_RADIUS_CIRCLE_COLOR,
            point_size=SEED_RADIUS_CIRCLE_POINT_SIZE,
            thickness=1.5,
        )

    def _draw_camera_plane_circle(self, center, radius, color, point_size=2.0, thickness=2.0):
        if radius <= 1.0e-8:
            return
        points = []
        for index in range(PROBE_CIRCLE_SEGMENTS + 1):
            angle = 6.283185307179586 * index / PROBE_CIRCLE_SEGMENTS
            points.append(
                add(
                    center,
                    add(
                        mul(self.camera.right, radius * math.cos(angle)),
                        mul(self.camera.up, radius * math.sin(angle)),
                    ),
                )
            )
        sc.Curve(
            points,
            colors=[color],
            thicknesses=[thickness],
            curve_type=sc.Curve.CurveType.LINEAR,
        )
        sc.Points(
            points[:-1],
            colors=[color] * PROBE_CIRCLE_SEGMENTS,
            sizes=[point_size] * PROBE_CIRCLE_SEGMENTS,
        )

    def _build_data_overlay(self):
        self._data_overlay_labels = {}
        with ui.VStack():
            with ui.HStack(height=DATA_OVERLAY_HEIGHT + VIEWPORT_OVERLAY_MARGIN):
                ui.Spacer(width=VIEWPORT_OVERLAY_MARGIN)
                with ui.ZStack(width=DATA_OVERLAY_WIDTH, height=DATA_OVERLAY_HEIGHT):
                    rectangle = getattr(ui, "Rectangle", None)
                    if rectangle:
                        rectangle(style=self._viewport_overlay_panel_style())
                    with ui.VStack(width=DATA_OVERLAY_WIDTH, height=DATA_OVERLAY_HEIGHT, spacing=0):
                        ui.Spacer(height=8)
                        self._build_data_overlay_label("count", 24, self._data_overlay_count_label_style())
                        self._build_data_overlay_label("file", 19, self._viewport_overlay_label_style())
                        self._build_data_overlay_label("removed", 18, self._viewport_overlay_label_style())
                        ui.Spacer()
                ui.Spacer()
            ui.Spacer()
        self._refresh_data_overlay()

    def _build_data_overlay_label(self, name, height, style):
        with ui.HStack(height=height, spacing=0):
            ui.Spacer(width=DATA_OVERLAY_TEXT_PADDING)
            self._data_overlay_labels[name] = ui.Label(
                "",
                width=DATA_OVERLAY_WIDTH - DATA_OVERLAY_TEXT_PADDING * 2,
                height=height,
                style=style,
            )
            ui.Spacer(width=DATA_OVERLAY_TEXT_PADDING)

    def _refresh_data_overlay(self):
        labels = getattr(self, "_data_overlay_labels", None) or {}
        if not labels:
            return False
        state = getattr(self, "_data_overlay_state", None) or {}
        point_count = self._overlay_int_value(state.get("point_count"), self._point_cloud_count())
        active_count = self._overlay_int_value(state.get("active_count"), self._active_point_count(point_count))
        removed_count = self._overlay_int_value(state.get("removed_count"), max(0, point_count - active_count))
        dataset_name = str(state.get("dataset_name") or "").strip()
        if not dataset_name or dataset_name == "None":
            dataset_name = "No file loaded"
        values = {
            "count": f"{active_count:,} / {point_count:,} pts",
            "file": dataset_name,
            "removed": f"Removed: {removed_count:,} pts",
        }
        for name, text in values.items():
            label = labels.get(name)
            if label is None:
                continue
            try:
                label.text = text
            except Exception:
                pass
        return True

    def _build_hover_detection_overlay(self):
        frame_factory = getattr(ui, "Frame", None)
        with ui.VStack():
            ui.Spacer()
            with ui.HStack(height=HOVER_DETECTION_OVERLAY_HEIGHT + VIEWPORT_OVERLAY_MARGIN):
                ui.Spacer()
                if frame_factory:
                    self._hover_detection_overlay_frame = frame_factory(
                        width=HOVER_DETECTION_OVERLAY_WIDTH,
                        height=HOVER_DETECTION_OVERLAY_HEIGHT,
                    )
                else:
                    self._hover_detection_overlay_frame = None
                ui.Spacer(width=VIEWPORT_OVERLAY_MARGIN)
            ui.Spacer(height=VIEWPORT_OVERLAY_MARGIN)
        self._refresh_hover_detection_overlay()

    def _refresh_hover_detection_overlay(self):
        frame = getattr(self, "_hover_detection_overlay_frame", None)
        if frame is None:
            return False
        state = getattr(self, "_hover_detection_overlay_state", None) or {}
        visible = bool(state.get("visible"))
        self._set_widget_visible(frame, visible)
        if hasattr(frame, "clear"):
            try:
                frame.clear()
            except Exception:
                pass
        if not visible:
            return True
        try:
            with frame:
                self._build_hover_detection_overlay_body(state)
        except Exception as exc:
            carb.log_warn(f"Failed to refresh hover detection overlay: {exc}")
            return False
        return True

    def _build_hover_detection_overlay_body(self, state):
        rectangle = getattr(ui, "Rectangle", None)
        with ui.ZStack(width=HOVER_DETECTION_OVERLAY_WIDTH, height=HOVER_DETECTION_OVERLAY_HEIGHT):
            if rectangle:
                rectangle(style=self._viewport_overlay_panel_style())
            with ui.VStack(width=HOVER_DETECTION_OVERLAY_WIDTH, height=HOVER_DETECTION_OVERLAY_HEIGHT, spacing=0):
                ui.Spacer(height=8)
                with ui.HStack(height=28, spacing=8):
                    ui.Spacer(width=10)
                    self._build_hover_detection_type_icon(state)
                    ui.Label("Hover preview", height=24, style=self._hover_detection_title_style())
                    ui.Spacer()
                for label, value in list(state.get("rows") or [])[:5]:
                    with ui.HStack(height=18, spacing=6):
                        ui.Spacer(width=12)
                        ui.Label(str(label), width=78, style=self._viewport_overlay_dim_label_style())
                        ui.Label(
                            str(value),
                            width=HOVER_DETECTION_OVERLAY_WIDTH - 110,
                            style=self._viewport_overlay_label_style(),
                        )
                histogram = state.get("histogram")
                if histogram:
                    ui.Spacer(height=5)
                    self._build_hover_detection_histogram(histogram)
                ui.Spacer()

    def _build_hover_detection_type_icon(self, state):
        icon_path = state.get("icon_path")
        image_factory = getattr(ui, "Image", None)
        if icon_path and image_factory:
            image_kwargs = {
                "width": HOVER_DETECTION_ICON_SIZE,
                "height": HOVER_DETECTION_ICON_SIZE,
            }
            alignment = getattr(getattr(ui, "Alignment", None), "CENTER", None)
            fill_policy = getattr(getattr(ui, "FillPolicy", None), "PRESERVE_ASPECT_FIT", None)
            if alignment is not None:
                image_kwargs["alignment"] = alignment
            if fill_policy is not None:
                image_kwargs["fill_policy"] = fill_policy
            image_factory(icon_path, **image_kwargs)
            return
        label = str(state.get("result_type") or "?")[:5]
        ui.Label(label, width=HOVER_DETECTION_ICON_SIZE + 18, height=24, style=self._hover_detection_type_fallback_style())

    def _build_hover_detection_histogram(self, histogram):
        rectangle = getattr(ui, "Rectangle", None)
        bins = list(histogram.get("bins") or [])
        if not bins:
            return
        max_count = max(1, int(histogram.get("max_bin_count") or 0))
        chart_width = HOVER_DETECTION_HISTOGRAM_WIDTH
        chart_height = HOVER_DETECTION_HISTOGRAM_HEIGHT
        spacing = HOVER_DETECTION_HISTOGRAM_SPACING
        bar_widths = _histogram_bar_widths(len(bins), chart_width, spacing)
        axis_y = HOVER_DETECTION_HISTOGRAM_BAR_MAX_HEIGHT + 5
        with ui.HStack(height=chart_height, spacing=0):
            ui.Spacer(width=12)
            with ui.ZStack(width=chart_width, height=chart_height):
                if rectangle:
                    rectangle(style=self._hover_detection_histogram_box_style())
                    with ui.VStack(width=chart_width, height=chart_height, spacing=0):
                        ui.Spacer(height=axis_y)
                        rectangle(width=chart_width, height=1, style={"background_color": 0x99FFFFFF})
                        ui.Spacer()
                    zero_offset = self._histogram_fraction_offset(histogram.get("zero_fraction", 0.5), chart_width)
                    with ui.HStack(width=chart_width, height=chart_height, spacing=0):
                        ui.Spacer(width=max(0.0, float(zero_offset) - 0.5))
                        rectangle(width=1, height=axis_y + 3, style={"background_color": 0x99FFFFFF})
                        ui.Spacer()
                with ui.HStack(width=chart_width, height=chart_height, spacing=spacing):
                    for bin_info, bar_width in zip(bins, bar_widths):
                        count = int(bin_info.get("count", 0) or 0)
                        bar_height = 0
                        if count > 0:
                            bar_height = max(2, int(HOVER_DETECTION_HISTOGRAM_BAR_MAX_HEIGHT * count / max_count))
                        with ui.VStack(width=bar_width, height=chart_height, spacing=0):
                            ui.Spacer(height=max(0, HOVER_DETECTION_HISTOGRAM_BAR_MAX_HEIGHT - bar_height + 4))
                            if rectangle and bar_height:
                                rectangle(
                                    width=bar_width,
                                    height=bar_height,
                                    style={"background_color": _rgba_to_ui_color(bin_info.get("color"))},
                                )
                            elif bar_height:
                                ui.Label("", width=bar_width, height=bar_height)
                            ui.Spacer()
                with ui.VStack(width=chart_width, height=chart_height, spacing=0):
                    ui.Spacer(height=axis_y + 2)
                    with ui.HStack(width=chart_width, height=6, spacing=0):
                        mean_offset = self._histogram_fraction_offset(histogram.get("mean_fraction", 0.5), chart_width)
                        marker_width = 8
                        mean_left = max(0, min(chart_width - marker_width, mean_offset - marker_width // 2))
                        ui.Spacer(width=mean_left)
                        self._hover_detection_histogram_mean_marker()
                        ui.Spacer(width=max(0, chart_width - mean_left - marker_width))
                    ui.Spacer()
            ui.Spacer(width=12)

    def _hover_detection_histogram_mean_marker(self):
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

    def _point_cloud_count(self):
        point_cloud = getattr(self, "point_cloud", None)
        return getattr(point_cloud, "count", 0) if point_cloud else 0

    def _active_point_count(self, point_count):
        if not self.active_mask:
            return int(point_count or 0)
        return sum(1 for index, active in enumerate(self.active_mask) if index < point_count and active)

    def _overlay_int_value(self, value, fallback=0):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            try:
                return max(0, int(fallback))
            except (TypeError, ValueError):
                return 0

    def _set_widget_visible(self, widget, visible):
        try:
            widget.visible = bool(visible)
        except Exception:
            pass

    def _viewport_overlay_panel_style(self):
        return {
            "background_color": 0x991B1E24,
            "border_color": 0x88FFFFFF,
            "border_width": 1,
            "border_radius": 5,
        }

    def _data_overlay_count_label_style(self):
        return {
            "color": 0xF8FFFFFF,
            "font_size": 20,
        }

    def _hover_detection_title_style(self):
        return {
            "color": 0xF8FFFFFF,
            "font_size": 16,
        }

    def _viewport_overlay_label_style(self):
        return {
            "color": 0xE8FFFFFF,
            "font_size": 13,
        }

    def _viewport_overlay_dim_label_style(self):
        return {
            "color": 0xB8FFFFFF,
            "font_size": 12,
        }

    def _hover_detection_type_fallback_style(self):
        return {
            "color": 0xF8FFFFFF,
            "font_size": 12,
        }

    def _hover_detection_histogram_box_style(self):
        return {
            "background_color": 0x331B1E24,
            "border_color": 0x66FFFFFF,
            "border_width": 1,
            "border_radius": 3,
        }

    def _histogram_fraction_offset(self, fraction, width):
        return _histogram_fraction_offset(fraction, width)

    def _build_scale_ruler_label(self):
        self._scale_ruler_frame = None
        self._scale_ruler_label = None
        self._scale_ruler_label_left_spacer = None
        self._scale_ruler_label_top_spacer = None
        frame_factory = getattr(ui, "Frame", None)
        if frame_factory:
            self._scale_ruler_frame = frame_factory()
            self._refresh_scale_ruler_label()
            return
        with ui.VStack(spacing=0):
            self._scale_ruler_label_top_spacer = ui.Spacer(height=0)
            with ui.HStack(height=SCALE_RULER_LABEL_HEIGHT, spacing=0):
                self._scale_ruler_label_left_spacer = ui.Spacer(width=SCALE_RULER_LEFT_MARGIN)
                self._scale_ruler_label = ui.Label(
                    "",
                    width=SCALE_RULER_LABEL_WIDTH,
                    height=SCALE_RULER_LABEL_HEIGHT,
                    style=self._scale_ruler_label_style(),
                )
                ui.Spacer()
            ui.Spacer()
        self._refresh_scale_ruler_label()

    def _scale_ruler_label_style(self):
        return {
            "color": 0xF0FFFFFF,
            "font_size": 13,
        }

    def _refresh_scale_ruler_label(self):
        spec = self._scale_ruler_spec()
        text = spec["label"] if spec else ""
        if getattr(self, "_scale_ruler_frame", None) is not None:
            return self._rebuild_scale_ruler_label_frame(spec, text)
        label = getattr(self, "_scale_ruler_label", None)
        if label is None:
            return False
        self._refresh_scale_ruler_label_position(spec)
        try:
            if spec:
                self._set_widget_dimension(label, "width", spec["label_width"])
            label.text = text
            return True
        except Exception:
            return False

    def _rebuild_scale_ruler_label_frame(self, spec, text):
        frame = getattr(self, "_scale_ruler_frame", None)
        if frame is None:
            return False
        if hasattr(frame, "clear"):
            try:
                frame.clear()
            except Exception:
                pass
        self._scale_ruler_label = None
        if spec is None:
            return True
        try:
            with frame:
                self._build_scale_ruler_label_body(spec, text)
            return True
        except Exception as exc:
            carb.log_warn(f"Failed to refresh scale ruler label: {exc}")
            return False

    def _build_scale_ruler_label_body(self, spec, text):
        panel = self._scale_ruler_panel_spec(spec)
        with ui.VStack(spacing=0):
            ui.Spacer(height=panel["top"])
            with ui.HStack(height=panel["height"], spacing=0):
                ui.Spacer(width=panel["left"])
                with ui.ZStack(width=panel["width"], height=panel["height"]):
                    rectangle = getattr(ui, "Rectangle", None)
                    if rectangle and self._is_scale_ruler_visual_active():
                        rectangle(style=self._scale_ruler_hover_background_style())
                    with ui.VStack(width=panel["width"], height=panel["height"], spacing=0):
                        ui.Spacer(height=panel["label_y"])
                        with ui.HStack(height=SCALE_RULER_LABEL_HEIGHT, spacing=0):
                            ui.Spacer(width=panel["label_x"])
                            self._scale_ruler_label = ui.Label(
                                text,
                                width=spec["label_width"],
                                height=SCALE_RULER_LABEL_HEIGHT,
                                style=self._scale_ruler_label_style(),
                            )
                            ui.Spacer()
                        ui.Spacer()
                ui.Spacer()
            ui.Spacer()

    def _scale_ruler_hover_background_style(self):
        return {
            "background_color": SCALE_RULER_HOVER_BACKGROUND_COLOR,
            "border_radius": SCALE_RULER_HOVER_BORDER_RADIUS,
        }

    def _scale_ruler_spec(self, width=None, height=None, ruler_width_px=SCALE_RULER_WIDTH):
        if self.camera.projection_mode != PROJECTION_ORTHOGRAPHIC:
            return None
        if width is None or height is None:
            width, height = self._viewport_size()
        pixel_scale = self._pixel_scale(width, height)
        if pixel_scale <= 1.0e-8:
            return None
        ruler_width_px = max(1.0, float(ruler_width_px))
        world_length = ruler_width_px / pixel_scale
        if world_length <= 1.0e-12:
            return None
        label = self._format_scale_ruler_value(world_length)
        label_width = self._scale_ruler_label_width(label)
        left, baseline = self._scale_ruler_anchor(width, height, ruler_width_px, label_width=label_width)
        top = baseline - SCALE_RULER_HEIGHT
        right = left + ruler_width_px
        label_top = max(0.0, top - SCALE_RULER_LABEL_GAP - SCALE_RULER_LABEL_HEIGHT)
        significand_text, exponent_text = f"{world_length:.1e}".split("e")
        exponent = int(exponent_text)
        significand = float(significand_text)
        tick_unit = 10.0**exponent
        tick_count = max(1, int(math.floor(significand)))
        tick_offsets = [
            ruler_width_px * (tick_unit * index) / world_length
            for index in range(1, tick_count + 1)
            if tick_unit * index <= world_length * (1.0 + 1.0e-9)
        ]
        return {
            "world_length": world_length,
            "label": label,
            "label_width": label_width,
            "tick_offsets": tick_offsets,
            "pixel_scale": pixel_scale,
            "width": float(width),
            "height": float(height),
            "ruler_width_px": ruler_width_px,
            "left": left,
            "right": right,
            "top": top,
            "baseline": baseline,
            "label_left": left,
            "label_top": label_top,
        }

    def _scale_ruler_label_width(self, text):
        estimated = len(str(text)) * SCALE_RULER_LABEL_CHAR_WIDTH + SCALE_RULER_LABEL_EXTRA_WIDTH
        return max(SCALE_RULER_LABEL_MIN_WIDTH, min(SCALE_RULER_LABEL_WIDTH, estimated))

    def _scale_ruler_anchor(self, width, height, ruler_width_px=SCALE_RULER_WIDTH, label_width=None):
        if self._scale_ruler_position is None:
            left = SCALE_RULER_LEFT_MARGIN
            baseline = float(height) - SCALE_RULER_BOTTOM_MARGIN
        else:
            left, baseline = self._scale_ruler_position
        return self._clamp_scale_ruler_anchor(left, baseline, width, height, ruler_width_px, label_width=label_width)

    def _scale_ruler_panel_spec(self, spec):
        padding = SCALE_RULER_HOVER_PADDING
        left = max(0.0, min(spec["left"], spec["label_left"]) - padding)
        top = max(0.0, min(spec["top"], spec["label_top"]) - padding)
        right = min(float(spec["width"]), max(spec["right"], spec["label_left"] + spec["label_width"]) + padding)
        bottom = min(float(spec["height"]), spec["baseline"] + padding)
        if right <= left:
            right = min(float(spec["width"]), left + 1.0)
        if bottom <= top:
            bottom = min(float(spec["height"]), top + 1.0)
        return {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "width": max(1.0, right - left),
            "height": max(1.0, bottom - top),
            "label_x": max(0.0, spec["label_left"] - left),
            "label_y": max(0.0, spec["label_top"] - top),
        }

    def _clamp_scale_ruler_anchor(self, left, baseline, width, height, ruler_width_px=SCALE_RULER_WIDTH, label_width=None):
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        ruler_width_px = max(1.0, float(ruler_width_px))
        label_width = SCALE_RULER_LABEL_WIDTH if label_width is None else max(1.0, float(label_width))
        margin = min(SCALE_RULER_MIN_MARGIN, max(0.0, width - 1.0))
        overlay_width = max(ruler_width_px, label_width)
        max_left = max(0.0, width - overlay_width - margin)
        min_left = min(margin, max_left)
        left = max(min_left, min(max_left, float(left)))

        max_baseline = max(SCALE_RULER_HEIGHT, height - SCALE_RULER_MIN_MARGIN)
        min_baseline = SCALE_RULER_MIN_MARGIN + SCALE_RULER_LABEL_HEIGHT + SCALE_RULER_LABEL_GAP + SCALE_RULER_HEIGHT
        min_baseline = min(min_baseline, max_baseline)
        baseline = max(min_baseline, min(max_baseline, float(baseline)))
        return left, baseline

    def _set_scale_ruler_position(self, left, baseline, width=None, height=None, ruler_width_px=SCALE_RULER_WIDTH):
        if width is None or height is None:
            width, height = self._viewport_size()
        ruler_width_px = max(1.0, float(ruler_width_px))
        label_width = None
        pixel_scale = self._pixel_scale(width, height)
        if pixel_scale > 1.0e-8:
            label_width = self._scale_ruler_label_width(self._format_scale_ruler_value(ruler_width_px / pixel_scale))
        left, baseline = self._clamp_scale_ruler_anchor(
            left,
            baseline,
            width,
            height,
            ruler_width_px,
            label_width=label_width,
        )
        self._scale_ruler_position = (left, baseline)
        self._refresh_scale_ruler_label()
        if self._scale_ruler_overlay:
            self._scale_ruler_overlay.invalidate()
        return left, baseline

    def _refresh_scale_ruler_label_position(self, spec=None):
        if spec is None:
            spec = self._scale_ruler_spec()
        if spec is None:
            return False
        left_updated = self._set_widget_dimension(
            getattr(self, "_scale_ruler_label_left_spacer", None),
            "width",
            spec["label_left"],
        )
        top_updated = self._set_widget_dimension(
            getattr(self, "_scale_ruler_label_top_spacer", None),
            "height",
            spec["label_top"],
        )
        return bool(left_updated or top_updated)

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

    def _scale_ruler_hit_test(self, x, y):
        spec = self._scale_ruler_spec()
        if spec is None:
            return False
        local_x, local_y = self._local_mouse(x, y)
        panel = self._scale_ruler_panel_spec(spec)
        padding = max(0.0, SCALE_RULER_HIT_PADDING - SCALE_RULER_HOVER_PADDING)
        return (
            panel["left"] - padding <= local_x <= panel["right"] + padding
            and panel["top"] - padding <= local_y <= panel["bottom"] + padding
        )

    def _set_scale_ruler_hovered(self, hovered):
        hovered = bool(hovered)
        if hovered == self._scale_ruler_hovered:
            return False
        self._scale_ruler_hovered = hovered
        self._refresh_scale_ruler_label()
        return True

    def _format_scale_ruler_value(self, value):
        value = float(value)
        magnitude = abs(value)
        if 0.001 <= magnitude < 10000.0:
            text = f"{value:.3f}".rstrip("0").rstrip(".")
        else:
            text = f"{value:.2e}"
        return f"{text} units"

    def _draw_scale_ruler(self):
        spec = self._scale_ruler_spec()
        if spec is None:
            return
        width = spec["width"]
        height = spec["height"]
        pixel_scale = spec["pixel_scale"]
        left = spec["left"]
        baseline = spec["baseline"]
        top = spec["top"]
        right = spec["right"]

        def point(local_x, local_y):
            return self._orthographic_screen_plane_point(local_x, local_y, width, height, pixel_scale)

        sc.Line(point(left, baseline), point(right, baseline), color=SCALE_RULER_COLOR, thickness=SCALE_RULER_THICKNESS)
        for offset in [0.0, *spec["tick_offsets"], spec["ruler_width_px"]]:
            x = left + max(0.0, min(spec["ruler_width_px"], float(offset)))
            sc.Line(point(x, top), point(x, baseline), color=SCALE_RULER_COLOR, thickness=SCALE_RULER_THICKNESS)

    def _seed_radius_circle_spec(self):
        if not self.picking_enabled or not self.point_cloud or self.seed_radius <= 1.0e-8:
            return None

        selected_point = self._active_point(self.selected_index)
        if selected_point is not None:
            return selected_point, self.seed_radius

        if self._drag or not self._last_hover_mouse:
            return None

        width, height = self._viewport_size()
        local_x, local_y = self._local_mouse(*self._last_hover_mouse)
        if self.camera.projection_mode == PROJECTION_PERSPECTIVE:
            hover_point = self._active_point(self.hover_index)
            if hover_point is None:
                return None
            depth = self._point_depth(hover_point, width, height)
            if depth <= 1.0e-8:
                return None
            return self._perspective_screen_plane_point(local_x, local_y, width, height, depth), self.seed_radius

        pixel_scale = self._pixel_scale(width, height)
        if pixel_scale <= 1.0e-8:
            return None
        return self._orthographic_screen_plane_point(local_x, local_y, width, height, pixel_scale), self.seed_radius

    def _active_point(self, index):
        if index is None or index < 0 or index >= self.point_cloud.count:
            return None
        if self.active_mask is not None and index < len(self.active_mask) and not self.active_mask[index]:
            return None
        return self.point_cloud.points[index]

    def _valid_retroactive_pick_index(self):
        if not self.point_cloud:
            return None
        index = self.retroactive_pick_index
        return index if self._active_point(index) is not None else None

    def _orthographic_screen_plane_point(self, local_x, local_y, width, height, pixel_scale):
        offset_x = (local_x - width * 0.5) / pixel_scale
        offset_y = (height * 0.5 - local_y) / pixel_scale
        return add(self.camera.center, add(mul(self.camera.right, offset_x), mul(self.camera.up, offset_y)))

    def _perspective_screen_plane_point(self, local_x, local_y, width, height, depth):
        focal_px = self._perspective_focal_pixels(height)
        if focal_px <= 1.0e-8:
            return None
        aspect = width / max(height, 1.0)
        origin = self.camera.perspective_position(aspect)
        offset_x = (local_x - width * 0.5) * depth / focal_px
        offset_y = (height * 0.5 - local_y) * depth / focal_px
        return add(origin, add(mul(self.camera.forward, depth), add(mul(self.camera.right, offset_x), mul(self.camera.up, offset_y))))

    def _point_depth(self, point, width, height):
        aspect = width / max(height, 1.0)
        origin = self.camera.perspective_position(aspect)
        return dot(sub(point, origin), self.camera.forward)

    def _perspective_focal_pixels(self, height):
        return height * 0.5 / max(math.tan(math.radians(self.camera.fov_degrees) * 0.5), 1.0e-8)

    def _draw_bounding_box(self):
        bounds_min = self.point_cloud.bounds_min
        bounds_max = self.point_cloud.bounds_max
        x0, y0, z0 = bounds_min
        x1, y1, z1 = bounds_max
        corners = [
            [x0, y0, z0],
            [x1, y0, z0],
            [x1, y1, z0],
            [x0, y1, z0],
            [x0, y0, z1],
            [x1, y0, z1],
            [x1, y1, z1],
            [x0, y1, z1],
        ]
        color = [0.55, 0.62, 0.72, 1.0]
        for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)):
            sc.Line(corners[a], corners[b], color=color, thickness=1.0)

    def _draw_orientation_widget(self):
        self._draw_orientation_rotation_gizmo()
        origin = [0.0, 0.0, 0.0]
        for index, (color, endpoint) in enumerate(ORIENTATION_AXIS_COLORS):
            color = self._orientation_axis_color(index, color)
            thickness = 4.2 if self._is_orientation_visual_active(index=index) else 3.0
            point_size = 10.0 if self._is_orientation_visual_active(index=index) else 8.0
            sc.Line(origin, endpoint, color=color, thickness=thickness)
            sc.Points([endpoint], colors=[color], sizes=[point_size])
        sc.Points([origin], colors=[[0.92, 0.92, 0.9, 1.0]], sizes=[5.0])

    def _draw_orientation_rotation_gizmo(self):
        curve = getattr(sc, "Curve", None)
        if not callable(curve):
            return
        curve_type = getattr(getattr(curve, "CurveType", None), "LINEAR", None)
        for axis in ("horizontal", "vertical", "roll"):
            points = self._orientation_gizmo_arc_points(axis)
            kwargs = {
                "colors": [self._orientation_gizmo_color(axis)],
                "thicknesses": [self._orientation_gizmo_thickness(axis)],
            }
            if curve_type is not None:
                kwargs["curve_type"] = curve_type
            curve(points, **kwargs)

    def _orientation_gizmo_color(self, axis):
        if self._is_orientation_visual_active(axis=axis, active_only=True):
            return list(ORIENTATION_GIZMO_ACTIVE_COLOR)
        color = ORIENTATION_GIZMO_COLORS[axis]
        if self._is_orientation_visual_active(axis=axis):
            return _blend_rgba(color, ORIENTATION_GIZMO_ACTIVE_COLOR, ORIENTATION_GIZMO_HOVER_BLEND)
        return list(color)

    def _orientation_axis_color(self, index, color):
        if self._is_orientation_visual_active(index=index, active_only=True):
            return list(ORIENTATION_GIZMO_ACTIVE_COLOR)
        if self._is_orientation_visual_active(index=index):
            return _blend_rgba(color, ORIENTATION_GIZMO_ACTIVE_COLOR, ORIENTATION_GIZMO_HOVER_BLEND)
        return list(color)

    def _orientation_gizmo_thickness(self, axis):
        if self._is_orientation_visual_active(axis=axis, active_only=True):
            return 3.8
        if self._is_orientation_visual_active(axis=axis):
            return 3.0
        return 2.0

    def _is_orientation_visual_active(self, axis=None, index=None, active_only=False):
        active_axis = self._drag.get("axis") if self._is_orientation_gizmo_drag() else None
        if axis is None and index is not None:
            axis = next((name for name, axis_index in ORIENTATION_GIZMO_AXIS_INDEX.items() if axis_index == index), None)
        if active_axis == axis:
            return True
        if active_only:
            return False
        return self._orientation_hover_axis == axis

    def _orientation_gizmo_arc_points(self, axis):
        radius = ORIENTATION_GIZMO_RADIUS
        points = []
        for index in range(ORIENTATION_GIZMO_SEGMENTS + 1):
            angle = math.tau * index / ORIENTATION_GIZMO_SEGMENTS
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            if axis == "horizontal":
                point = [radius * cos_a, 0.0, radius * sin_a]
            elif axis == "vertical":
                point = [0.0, radius * cos_a, radius * sin_a]
            else:
                point = [radius * cos_a, radius * sin_a, 0.0]
            points.append(point)
        return points

    def projection_matrix(self):
        width, height = self._viewport_size()
        aspect = width / max(height, 1.0)
        near, far = self._clip_planes(width, height)
        if self.camera.projection_mode == PROJECTION_PERSPECTIVE:
            f = 1.0 / max(math.tan(math.radians(self.camera.fov_degrees) * 0.5), 1.0e-8)
            return [
                f / max(aspect, 1.0e-8),
                0.0,
                0.0,
                0.0,
                0.0,
                f,
                0.0,
                0.0,
                0.0,
                0.0,
                -(far + near) / (far - near),
                -1.0,
                0.0,
                0.0,
                -(2.0 * far * near) / (far - near),
                0.0,
            ]

        fit_size = self.camera.visible_fit_size()
        if width <= height:
            visible_width = fit_size
            visible_height = fit_size / max(aspect, 1.0e-8)
        else:
            visible_height = fit_size
            visible_width = fit_size * aspect

        return [
            2.0 / visible_width,
            0.0,
            0.0,
            0.0,
            0.0,
            2.0 / visible_height,
            0.0,
            0.0,
            0.0,
            0.0,
            -2.0 / (far - near),
            0.0,
            0.0,
            0.0,
            -(far + near) / (far - near),
            1.0,
        ]

    def view_matrix(self):
        return self._view_matrix(self._view_position())

    def orientation_view_matrix(self):
        return self._view_matrix(mul(self.camera.forward, -2.0))

    def _view_matrix(self, position):
        right = self.camera.right
        up = self.camera.up
        backward = mul(self.camera.forward, -1.0)
        return [
            right[0],
            up[0],
            backward[0],
            0.0,
            right[1],
            up[1],
            backward[1],
            0.0,
            right[2],
            up[2],
            backward[2],
            0.0,
            -dot(right, position),
            -dot(up, position),
            -dot(backward, position),
            1.0,
        ]

    def _view_position(self):
        width, height = self._viewport_size()
        aspect = width / max(height, 1.0)
        if self.camera.projection_mode == PROJECTION_PERSPECTIVE:
            return self.camera.perspective_position(aspect)
        return self.camera.position

    def _clip_planes(self, width, height):
        aspect = width / max(height, 1.0)
        if self.camera.projection_mode == PROJECTION_PERSPECTIVE:
            distance = self.camera.perspective_distance(aspect)
            near = max(distance * 0.001, 1.0e-5)
            far = max(distance + self.camera.diameter * 8.0, near + 1.0)
            return near, far
        return 1.0e-3, max(self.camera.diameter * 8.0, 1.0)

    def _viewport_size(self):
        if not self._input_rect:
            return 1200.0, 800.0
        return max(1.0, float(self._input_rect.computed_width)), max(1.0, float(self._input_rect.computed_height))

    def _viewport_center(self):
        if not self._input_rect:
            return 600.0, 400.0
        return (
            self._input_rect.screen_position_x + self._input_rect.computed_width * 0.5,
            self._input_rect.screen_position_y + self._input_rect.computed_height * 0.5,
        )

    def _local_mouse(self, x, y):
        if not self._input_rect:
            return x, y
        return x - self._input_rect.screen_position_x, y - self._input_rect.screen_position_y

    def _orientation_local_mouse(self, x, y):
        rect = self._orientation_input_rect
        if not rect:
            return x, y
        return x - rect.screen_position_x, y - rect.screen_position_y

    def _is_screen_point_inside(self, x, y):
        if not self._input_rect:
            return False
        left = self._input_rect.screen_position_x
        top = self._input_rect.screen_position_y
        return left <= x < left + self._input_rect.computed_width and top <= y < top + self._input_rect.computed_height

    def _is_orientation_screen_point_inside(self, x, y):
        rect = self._orientation_input_rect
        if not rect:
            return False
        left = rect.screen_position_x
        top = rect.screen_position_y
        return left <= x < left + rect.computed_width and top <= y < top + rect.computed_height

    def _orientation_widget_size(self):
        rect = self._orientation_input_rect
        if not rect:
            return float(ORIENTATION_WIDGET_SIZE), float(ORIENTATION_WIDGET_SIZE)
        return max(1.0, float(rect.computed_width)), max(1.0, float(rect.computed_height))

    def _pixel_scale(self, width, height):
        return min(width, height) * self.camera.zoom / max(self.camera.diameter, 1.0e-8)

    def _on_mouse_pressed(self, x, y, button, modifier):
        if self._input_blocked(x, y):
            self._clear_hover_pick()
            return
        if not self._has_scene_content():
            return
        modifier = modifier or 0
        alt_pick = self._modifier_has_alt(modifier)
        self.set_retroactive_pick_active(alt_pick)
        if button == LEFT_BUTTON and not (modifier & carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL):
            if self._begin_scale_ruler_drag(x, y):
                return
        if button == MIDDLE_BUTTON:
            mode = "pan"
        elif button == RIGHT_BUTTON or (button == LEFT_BUTTON and modifier & carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL):
            mode = "roll"
        elif button == LEFT_BUTTON:
            mode = "pending_orbit"
        else:
            return
        allow_nearest_fallback = self.selected_index is None
        self._click_pick_index = None
        if mode == "pending_orbit" and self.picking_enabled:
            if alt_pick:
                self._click_pick_index = self._valid_retroactive_pick_index()
            else:
                self._click_pick_index = self._pick_at(x, y, allow_nearest_fallback=allow_nearest_fallback)
        self._drag = {"mode": mode, "x": x, "y": y}
        self._notify_camera_changed("begin")
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        self.hover_index = None
        if self._on_hover_changed:
            self._on_hover_changed(None)
        self._refresh_pick_overlay()
        if mode == "pending_orbit":
            self._drag["start_orientation"] = list(self.camera.orientation)
            self._drag["start_x"] = x
            self._drag["start_y"] = y
            self._drag["start_right"] = self.camera.right
            self._drag["start_up"] = self.camera.up

    def _begin_scale_ruler_drag(self, x, y):
        spec = self._scale_ruler_spec()
        if spec is None or not self._scale_ruler_hit_test(x, y):
            return False
        local_x, local_y = self._local_mouse(x, y)
        self._click_pick_index = None
        self._drag = {
            "mode": "scale_ruler",
            "x": x,
            "y": y,
            "grab_x": local_x - spec["left"],
            "grab_y": local_y - spec["baseline"],
            "ruler_width_px": spec["ruler_width_px"],
        }
        self._set_scale_ruler_hovered(True)
        self._clear_hover_pick()
        return True

    def _preview_scale_ruler_drag(self, x, y):
        if not self._is_scale_ruler_drag():
            return
        local_x, local_y = self._local_mouse(x, y)
        ruler_width_px = self._drag.get("ruler_width_px", SCALE_RULER_WIDTH)
        left = local_x - self._drag.get("grab_x", 0.0)
        baseline = local_y - self._drag.get("grab_y", 0.0)
        self._set_scale_ruler_position(left, baseline, ruler_width_px=ruler_width_px)
        self._drag["x"] = x
        self._drag["y"] = y

    def _on_orientation_mouse_pressed(self, x, y, button, modifier):
        if self._input_blocked(x, y):
            self._set_orientation_hover_axis(None)
            return
        if button != LEFT_BUTTON:
            return
        axis = self._orientation_gizmo_axis_at(x, y)
        if axis is None:
            return
        ring_vector = self._orientation_gizmo_ring_vector(axis, x, y)
        if ring_vector is None:
            return
        self._set_orientation_hover_axis(axis)
        self._clear_hover_pick()
        self._click_pick_index = None
        self._drag = {
            "mode": "orientation_gizmo",
            "axis": axis,
            "x": x,
            "y": y,
            "start_x": x,
            "start_y": y,
            "start_orientation": list(self.camera.orientation),
            "start_camera_right": self.camera.right,
            "start_camera_up": self.camera.up,
            "start_ring_vector": ring_vector,
            "last_degrees": 0.0,
        }
        self._notify_camera_changed("begin")
        self._refresh_orientation_overlay()

    def _on_orientation_mouse_moved(self, x, y, button, modifier):
        if self._input_blocked(x, y):
            self._set_orientation_hover_axis(None)
            return
        if not self._is_orientation_gizmo_drag():
            self._set_orientation_hover_axis(self._orientation_gizmo_axis_at(x, y))
            return
        self._preview_orientation_gizmo_drag(x, y)

    def _on_orientation_mouse_released(self, x, y, button, modifier):
        if self._input_blocked(x, y) and not self._is_orientation_gizmo_drag():
            self._set_orientation_hover_axis(None)
            return
        if not self._is_orientation_gizmo_drag():
            return
        if button == LEFT_BUTTON:
            self._preview_orientation_gizmo_drag(x, y)
            self._notify_camera_changed("commit")
            self._drag = None
            self._set_orientation_hover_axis(self._orientation_gizmo_axis_at(x, y))
            self._refresh_orientation_overlay()

    def _on_orientation_mouse_hovered(self, hovered):
        if hovered and self._input_blocked():
            self._set_orientation_hover_axis(None)
            return
        if not hovered and not self._is_orientation_gizmo_drag():
            self._set_orientation_hover_axis(None)

    def _poll_orientation_hover(self, x, y):
        if self._is_orientation_gizmo_drag():
            return True
        if self._is_orientation_screen_point_inside(x, y):
            self._set_orientation_hover_axis(self._orientation_gizmo_axis_at(x, y))
            if self._last_hover_mouse or self.hover_index is not None:
                self._clear_hover_pick()
            return True
        if self._orientation_hover_axis is not None:
            self._set_orientation_hover_axis(None)
        return False

    def _set_orientation_hover_axis(self, axis):
        if axis == self._orientation_hover_axis:
            return
        self._orientation_hover_axis = axis
        self._refresh_orientation_overlay()

    def _refresh_orientation_overlay(self):
        if self._orientation_overlay:
            self._orientation_overlay.invalidate()
        elif self._orientation_view and not self._destroyed:
            self._rebuild_orientation_widget()

    def _is_orientation_gizmo_drag(self):
        return bool(self._drag and self._drag.get("mode") == "orientation_gizmo")

    def _is_scale_ruler_drag(self):
        return bool(self._drag and self._drag.get("mode") == "scale_ruler")

    def _is_scale_ruler_visual_active(self):
        return bool(self._scale_ruler_hovered or self._is_scale_ruler_drag())

    def _orientation_gizmo_axis_at(self, x, y):
        local_x, local_y = self._orientation_local_mouse(x, y)
        padding = ORIENTATION_GIZMO_HIT_PADDING
        candidates = []
        for axis in ("horizontal", "vertical", "roll"):
            distance = self._orientation_gizmo_screen_distance(axis, local_x, local_y)
            if distance <= padding:
                candidates.append((axis, distance))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[1])
        return candidates[0][0]

    def _orientation_gizmo_screen_distance(self, axis, local_x, local_y):
        points = [self._orientation_gizmo_project_point(point) for point in self._orientation_gizmo_arc_points(axis)]
        return min(
            _point_segment_distance_2d(local_x, local_y, points[index], points[index + 1])
            for index in range(len(points) - 1)
        )

    def _orientation_gizmo_project_point(self, point):
        width, height = self._orientation_widget_size()
        center_x = width * 0.5
        center_y = height * 0.5
        pixel_scale = min(width, height) * 0.38 / max(ORIENTATION_GIZMO_RADIUS, 1.0e-8)
        return (
            center_x + dot(point, self.camera.right) * pixel_scale,
            center_y - dot(point, self.camera.up) * pixel_scale,
        )

    def _preview_orientation_gizmo_drag(self, x, y):
        if not self._is_orientation_gizmo_drag():
            return
        degrees = self._orientation_gizmo_drag_degrees(x, y)
        if degrees is None:
            return
        if abs(degrees - self._drag.get("last_degrees", 0.0)) <= 1.0e-8:
            return
        self.camera.orientation = list(self._drag["start_orientation"])
        axis = self._drag["axis"]
        if axis == "horizontal":
            rotation_axis = ORIENTATION_GIZMO_AXES["horizontal"]
            applied_degrees = degrees
        elif axis == "vertical":
            rotation_axis = ORIENTATION_GIZMO_AXES["vertical"]
            applied_degrees = degrees
        else:
            rotation_axis = ORIENTATION_GIZMO_AXES["roll"]
            applied_degrees = degrees
        self.camera.rotate_orientation_degrees(rotation_axis, applied_degrees)
        self._drag["last_degrees"] = degrees
        self._drag["x"] = x
        self._drag["y"] = y
        self.draw()
        self._notify_camera_changed("change")

    def _orientation_gizmo_drag_degrees(self, x, y):
        axis = self._drag["axis"]
        current = self._orientation_gizmo_ring_vector(
            axis,
            x,
            y,
            reference_vector=self._drag["start_ring_vector"],
            camera_right=self._drag["start_camera_right"],
            camera_up=self._drag["start_camera_up"],
        )
        if current is None:
            return None
        start = self._drag["start_ring_vector"]
        rotation_axis = ORIENTATION_GIZMO_AXES[axis]
        cross_value = cross(start, current)
        sin_value = dot(rotation_axis, cross_value)
        cos_value = dot(start, current)
        return math.degrees(math.atan2(sin_value, cos_value))

    def _orientation_gizmo_ring_vector(self, axis, x, y, reference_vector=None, camera_right=None, camera_up=None):
        width, height = self._orientation_widget_size()
        center_x = width * 0.5
        center_y = height * 0.5
        local_x, local_y = self._orientation_local_mouse(x, y)
        pixel_scale = min(width, height) * 0.38 / max(ORIENTATION_GIZMO_RADIUS, 1.0e-8)
        screen = (
            (local_x - center_x) / max(pixel_scale, 1.0e-8),
            -(local_y - center_y) / max(pixel_scale, 1.0e-8),
        )
        basis_u, basis_v = self._orientation_gizmo_basis(axis)
        proj_u = self._orientation_gizmo_project_direction(basis_u, camera_right=camera_right, camera_up=camera_up)
        proj_v = self._orientation_gizmo_project_direction(basis_v, camera_right=camera_right, camera_up=camera_up)
        det = proj_u[0] * proj_v[1] - proj_v[0] * proj_u[1]
        if abs(det) > 1.0e-8:
            coeff_u = (screen[0] * proj_v[1] - proj_v[0] * screen[1]) / det
            coeff_v = (proj_u[0] * screen[1] - screen[0] * proj_u[1]) / det
            vector = normalize(add(mul(basis_u, coeff_u), mul(basis_v, coeff_v)), None)
        else:
            vector = self._orientation_gizmo_edge_on_ring_vector(screen, basis_u, basis_v, proj_u, proj_v, reference_vector)
        if vector is None or dot(vector, vector) <= 1.0e-8:
            return None
        return vector

    def _orientation_gizmo_basis(self, axis):
        if axis == "horizontal":
            return [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]
        if axis == "vertical":
            return [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]
        return [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]

    def _orientation_gizmo_project_direction(self, vector, camera_right=None, camera_up=None):
        camera_right = camera_right or self.camera.right
        camera_up = camera_up or self.camera.up
        return (dot(vector, camera_right), -dot(vector, camera_up))

    def _orientation_gizmo_edge_on_ring_vector(self, screen, basis_u, basis_v, proj_u, proj_v, reference_vector=None):
        len_u = proj_u[0] * proj_u[0] + proj_u[1] * proj_u[1]
        len_v = proj_v[0] * proj_v[0] + proj_v[1] * proj_v[1]
        if len_u >= len_v and len_u > 1.0e-8:
            coeff_u = max(-1.0, min(1.0, (screen[0] * proj_u[0] + screen[1] * proj_u[1]) / len_u))
            sign_v = self._orientation_gizmo_hidden_sign(basis_v, reference_vector)
            coeff_v = sign_v * math.sqrt(max(0.0, 1.0 - coeff_u * coeff_u))
        elif len_v > 1.0e-8:
            coeff_v = max(-1.0, min(1.0, (screen[0] * proj_v[0] + screen[1] * proj_v[1]) / len_v))
            sign_u = self._orientation_gizmo_hidden_sign(basis_u, reference_vector)
            coeff_u = sign_u * math.sqrt(max(0.0, 1.0 - coeff_v * coeff_v))
        else:
            return None
        return normalize(add(mul(basis_u, coeff_u), mul(basis_v, coeff_v)), None)

    def _orientation_gizmo_hidden_sign(self, hidden_basis, reference_vector=None):
        if reference_vector is None:
            return 1.0
        return -1.0 if dot(reference_vector, hidden_basis) < 0.0 else 1.0

    def _on_mouse_moved(self, x, y, button, modifier):
        if self._input_blocked(x, y):
            self._set_scale_ruler_hovered(False)
            self._clear_hover_pick()
            return
        self.set_retroactive_pick_active(self._modifier_has_alt(modifier))
        if self._is_orientation_gizmo_drag():
            self._preview_orientation_gizmo_drag(x, y)
            return
        if self._is_scale_ruler_drag():
            self._preview_scale_ruler_drag(x, y)
            return
        if not self._has_scene_content():
            return
        if not self._drag:
            if self._scale_ruler_hit_test(x, y):
                self._set_scale_ruler_hovered(True)
                self._clear_hover_pick()
                return
            self._set_scale_ruler_hovered(False)
            self.update_hover_pick(x, y)
            return
        last_x = self._drag["x"]
        last_y = self._drag["y"]
        dx = x - last_x
        dy = y - last_y
        if self._drag["mode"] == "pending_orbit":
            total_dx = x - self._drag["start_x"]
            total_dy = y - self._drag["start_y"]
            if total_dx * total_dx + total_dy * total_dy < 9.0:
                return
            self._drag["mode"] = "orbit"
        if self._drag["mode"] == "orbit":
            self.camera.orbit_screen_drag(
                self._drag["start_orientation"],
                self._drag["start_right"],
                self._drag["start_up"],
                x - self._drag["start_x"],
                y - self._drag["start_y"],
            )
        elif self._drag["mode"] == "roll":
            center_x, center_y = self._viewport_center()
            self.camera.roll_pixels(center_x, center_y, last_x, last_y, x, y)
        elif self._drag["mode"] == "pan":
            width, height = self._viewport_size()
            self.camera.pan_pixels(dx, dy, self._pixel_scale(width, height))
        self._drag["x"] = x
        self._drag["y"] = y
        self.draw()
        self._notify_camera_changed("change")

    def _on_mouse_released(self, x, y, button, modifier):
        if self._input_blocked(x, y) and not self._drag:
            self._clear_hover_pick()
            return
        self.set_retroactive_pick_active(self._modifier_has_alt(modifier))
        if self._is_orientation_gizmo_drag():
            if button == LEFT_BUTTON:
                self._preview_orientation_gizmo_drag(x, y)
            self._notify_camera_changed("commit")
            self._drag = None
            self._click_pick_index = None
            self._refresh_orientation_overlay()
            return
        if self._is_scale_ruler_drag():
            if button == LEFT_BUTTON:
                self._preview_scale_ruler_drag(x, y)
            self._drag = None
            self._click_pick_index = None
            self.set_retroactive_pick_active(False)
            self._set_scale_ruler_hovered(self._scale_ruler_hit_test(x, y))
            return
        if self._drag and self._drag["mode"] == "pending_orbit" and button == LEFT_BUTTON:
            if not self.picking_enabled:
                self._notify_camera_changed("commit")
                self._drag = None
                self._click_pick_index = None
                return
            picked = self._click_pick_index
            had_selection = self.selected_index is not None
            self.selected_index = picked
            self._drag = None
            self._click_pick_index = None
            self._notify_camera_changed("commit")
            if self._on_seed_selected:
                self._on_seed_selected(picked)
            self.update_hover_pick(x, y)
            if had_selection != (self.selected_index is not None):
                self._rebuild_scene()
            return
        camera_drag = bool(self._drag and self._drag.get("mode") in ("orbit", "roll", "pan"))
        self._drag = None
        self._click_pick_index = None
        if camera_drag:
            self._notify_camera_changed("commit")

    def _on_mouse_hovered(self, hovered):
        if hovered and self._input_blocked():
            self._mouse_over_input_rect = False
            self._set_scale_ruler_hovered(False)
            self._clear_hover_pick()
            return
        self._mouse_over_input_rect = bool(hovered)
        if not hovered:
            self.set_retroactive_pick_active(False)
            self._set_scale_ruler_hovered(False)
            self._clear_hover_pick()
            self._last_polled_mouse = None

    def _pick_at(self, x, y, allow_nearest_fallback=True):
        if not self.point_cloud:
            return None
        fallback_to_nearest = bool(self.pick_nearest_on_probe_miss and allow_nearest_fallback)
        local_x, local_y = self._local_mouse(x, y)
        if (
            self.camera.projection_mode == PROJECTION_ORTHOGRAPHIC
            and self._native_picker
            and getattr(self.point_cloud, "point_buffer", None) is not None
        ):
            return self._native_picker.pick_orthographic(
                self.point_cloud.point_buffer,
                self._active_mask_buffer,
                self.point_cloud.count,
                self.camera,
                self._viewport_size(),
                (local_x, local_y),
                self.probe_radius_px,
                fallback_to_nearest=fallback_to_nearest,
            )
        if self.camera.projection_mode == PROJECTION_PERSPECTIVE:
            if self._native_picker and getattr(self.point_cloud, "point_buffer", None) is not None:
                return self._native_picker.pick_perspective(
                    self.point_cloud.point_buffer,
                    self._active_mask_buffer,
                    self.point_cloud.count,
                    self.camera,
                    self._viewport_size(),
                    (local_x, local_y),
                    self.probe_radius_px,
                    self._view_position(),
                    fallback_to_nearest=fallback_to_nearest,
                )
        return None

    def update_hover_pick(self, x, y):
        if not self.picking_enabled:
            self._clear_hover_pick()
            return
        self._last_hover_mouse = (x, y)
        if self.selected_index is not None:
            if self.hover_index is not None:
                self.hover_index = None
                if self._on_hover_changed:
                    self._on_hover_changed(None)
            self._refresh_pick_overlay()
            return
        picked = self._pick_at(x, y)
        changed = picked != self.hover_index
        self.hover_index = picked
        if changed and self._on_hover_changed:
            self._on_hover_changed(picked)
        self._refresh_pick_overlay()

    def _clear_hover_pick(self):
        self._last_hover_mouse = None
        self._last_polled_mouse = None
        if self.hover_index is None:
            self._refresh_pick_overlay()
            return
        self.hover_index = None
        if self._on_hover_changed:
            self._on_hover_changed(None)
        self._refresh_pick_overlay()

    def _on_mouse_wheel(self, *args):
        if self._input_blocked(*self._event_screen_position(args)):
            self._clear_hover_pick()
            return
        if not self._has_scene_content():
            return
        self._clear_hover_pick()
        delta = None
        for value in reversed(args):
            if isinstance(value, numbers.Real):
                value = float(value)
                if abs(value) > 1.0e-8:
                    delta = value
                    break
        if delta is None:
            return
        self._zoom_steps(delta)

    def _event_screen_position(self, args):
        values = []
        for value in args or ():
            if isinstance(value, numbers.Real):
                values.append(float(value))
        if len(values) >= 3:
            return values[0], values[1]
        return (None, None)

    def _input_blocked(self, x=None, y=None):
        callback = self._input_blocked_fn
        if not callable(callback):
            return False
        try:
            return bool(callback(x, y))
        except TypeError:
            try:
                return bool(callback())
            except Exception:
                return False
        except Exception:
            return False

    def _zoom_steps(self, delta):
        if not self._has_scene_content() or abs(delta) < 1.0e-8:
            return
        self._notify_camera_changed("begin")
        self.camera.zoom_steps(delta)
        self.draw()
        self._notify_camera_changed("commit")

    def _notify_camera_changed(self, phase="commit"):
        if self._on_camera_changed:
            try:
                self._on_camera_changed(phase)
            except TypeError:
                if phase == "begin":
                    self._legacy_camera_change_sent = False
                    return
                if phase == "commit" and getattr(self, "_legacy_camera_change_sent", False):
                    self._legacy_camera_change_sent = False
                    return
                self._on_camera_changed()
                self._legacy_camera_change_sent = phase == "change"

    def _init_mouse_polling(self):
        try:
            self._app_window = omni.appwindow.get_default_app_window()
            self._input = carb.input.acquire_input_interface()
            self._mouse = self._app_window.get_mouse() if self._app_window else None
            self._ui_scale = max(1.0e-8, float(self._app_window.get_ui_scale())) if self._app_window else 1.0
        except Exception:
            self._app_window = None
            self._input = None
            self._mouse = None
            self._ui_scale = 1.0

    def _poll_mouse_position(self):
        if not self._input or not self._mouse:
            return None, None
        x, y = self._input.get_mouse_coords_pixel(self._mouse)
        if self._ui_scale > 1.0e-8:
            x = float(x) / self._ui_scale
            y = float(y) / self._ui_scale
        return float(x), float(y)

    def _set_active_mask_buffer(self, active_mask, point_count):
        if point_count <= 0:
            self._active_mask_buffer = None
            return
        if active_mask is None:
            self._active_mask_buffer = (c_uint8 * point_count)(*([1] * point_count))
            return
        self._active_mask_buffer = (c_uint8 * point_count)(
            *[1 if index < len(active_mask) and active_mask[index] else 0 for index in range(point_count)]
        )

    def _create_native_picker(self):
        try:
            return NativePointPicker()
        except Exception as exc:
            carb.log_warn(f"Native point picker unavailable, using Python fallback: {exc}")
            return None

    def _modifier_has_alt(self, modifier):
        if modifier is None:
            return False
        alt_flags = (
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_ALT", 4),
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_LEFT_ALT", 0),
            getattr(carb.input, "KEYBOARD_MODIFIER_FLAG_RIGHT_ALT", 0),
        )
        try:
            value = int(modifier)
        except Exception:
            return False
        return any(flag and value & int(flag) for flag in alt_flags)


def _histogram_bar_widths(count, chart_width, spacing):
    count = max(0, int(count or 0))
    if count <= 0:
        return []
    spacing_total = max(0, count - 1) * max(0, int(spacing or 0))
    available = max(float(count), float(chart_width) - spacing_total)
    width = available / count
    return [width for _index in range(count)]


def _histogram_fraction_offset(fraction, width):
    width = max(1, int(width or 1))
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        fraction = 0.5
    display_fraction = max(0.0, min(1.0, fraction))
    return max(0, min(width - 1, int(math.floor(display_fraction * (width - 1) + 0.5))))


def _rgba_to_ui_color(color):
    rgba = _rgba(color, fallback=[1.0, 1.0, 1.0, 1.0])
    channels = [max(0, min(255, int(round(float(channel) * 255.0)))) for channel in rgba[:4]]
    return (channels[3] << 24) | (channels[2] << 16) | (channels[1] << 8) | channels[0]


def _rgba(color, fallback=None):
    source = list(color or fallback or [1.0, 1.0, 1.0, 1.0])
    while len(source) < 4:
        source.append(1.0)
    return [max(0.0, min(1.0, float(source[index]))) for index in range(4)]


def _blend_rgba(color, target, amount):
    color = _rgba(color)
    target = _rgba(target)
    amount = max(0.0, min(1.0, float(amount)))
    return [color[index] + (target[index] - color[index]) * amount for index in range(4)]


def _point_segment_distance_2d(x, y, start, end):
    sx, sy = start
    ex, ey = end
    vx = ex - sx
    vy = ey - sy
    wx = x - sx
    wy = y - sy
    length_sq = vx * vx + vy * vy
    if length_sq <= 1.0e-12:
        return math.sqrt(wx * wx + wy * wy)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / length_sq))
    px = sx + vx * t
    py = sy + vy * t
    dx = x - px
    dy = y - py
    return math.sqrt(dx * dx + dy * dy)


def _negative_sigma(value):
    value = -abs(float(value))
    return max(-3.0, min(-0.5, value))


def _positive_sigma(value):
    value = abs(float(value))
    return max(0.5, min(3.0, value))


def _standard_deviation(values):
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(max(0.0, variance))


def build_inlier_distance_histogram(
    point_cloud,
    result,
    bin_count=INLIER_DISTANCE_HISTOGRAM_BINS,
    native_picker=None,
    negative_color=None,
    zero_color=None,
    positive_color=None,
    negative_sigma=-1.0,
    positive_sigma=1.0,
):
    return _native_inlier_distance_histogram(
        native_picker,
        point_cloud,
        result,
        bin_count,
        negative_color,
        zero_color,
        positive_color,
        negative_sigma,
        positive_sigma,
    )


def _native_inlier_distance_histogram(
    native_picker,
    point_cloud,
    result,
    bin_count,
    negative_color,
    zero_color,
    positive_color,
    negative_sigma,
    positive_sigma,
):
    builder = getattr(native_picker, "build_inlier_distance_histogram", None)
    point_buffer = getattr(point_cloud, "point_buffer", None)
    if not callable(builder) or point_buffer is None:
        return None
    spec = _surface_distance_native_spec(result)
    if spec is None:
        return None
    surface_type, surface_params = spec
    histogram = builder(
        point_buffer,
        getattr(point_cloud, "count", 0),
        getattr(result, "inlier_indices", []) or [],
        surface_type,
        surface_params,
        bin_count,
        measurement_accuracy=getattr(result, "measurement_accuracy", 0.0),
        rms_error=getattr(result, "rms_error", 0.0),
    )
    if histogram is None:
        return None
    sigma = histogram.get("sigma", 0.0)
    for bin_info in histogram.get("bins", []) or []:
        bin_info["color"] = _inlier_distance_color(
            bin_info.get("center", 0.0),
            sigma,
            negative_color,
            zero_color,
            positive_color,
            negative_sigma,
            positive_sigma,
        )
    return histogram


def _inlier_distance_color(
    distance,
    sigma,
    negative_color=None,
    zero_color=None,
    positive_color=None,
    negative_sigma=-1.0,
    positive_sigma=1.0,
):
    negative_color = _rgba(negative_color, fallback=INLIER_NEGATIVE_COLOR)
    zero_color = _rgba(zero_color, fallback=INLIER_ZERO_COLOR)
    positive_color = _rgba(positive_color, fallback=INLIER_POSITIVE_COLOR)
    if sigma <= 1.0e-12:
        return zero_color
    negative_boundary = _negative_sigma(negative_sigma) * sigma
    positive_boundary = _positive_sigma(positive_sigma) * sigma
    distance = float(distance)
    epsilon = max(sigma * 1.0e-9, 1.0e-12)
    if distance <= negative_boundary + epsilon:
        return negative_color
    if distance >= positive_boundary - epsilon:
        return positive_color
    if abs(distance) <= epsilon:
        return zero_color
    if distance < 0.0:
        return _oklab_lerp(negative_color, zero_color, (distance - negative_boundary) / -negative_boundary)
    return _oklab_lerp(zero_color, positive_color, distance / positive_boundary)


def _oklab_lerp(start_color, end_color, t):
    t = max(0.0, min(1.0, float(t)))
    start_lab = _srgb_to_oklab(start_color[:3])
    end_lab = _srgb_to_oklab(end_color[:3])
    lab = [
        start_lab[channel] * (1.0 - t) + end_lab[channel] * t
        for channel in range(3)
    ]
    rgb = _oklab_to_srgb(lab)
    alpha = start_color[3] * (1.0 - t) + end_color[3] * t
    return [rgb[0], rgb[1], rgb[2], max(0.0, min(1.0, alpha))]


def _srgb_to_oklab(rgb):
    r, g, b = [_srgb_to_linear(channel) for channel in rgb]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_ = _signed_cuberoot(l)
    m_ = _signed_cuberoot(m)
    s_ = _signed_cuberoot(s)
    return [
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    ]


def _oklab_to_srgb(lab):
    l, a, b = lab
    l_ = l + 0.3963377774 * a + 0.2158037573 * b
    m_ = l - 0.1055613458 * a - 0.0638541728 * b
    s_ = l - 0.0894841775 * a - 1.2914855480 * b
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    rgb = [
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ]
    return [max(0.0, min(1.0, _linear_to_srgb(channel))) for channel in rgb]


def _srgb_to_linear(channel):
    channel = max(0.0, min(1.0, float(channel)))
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(channel):
    channel = max(0.0, min(1.0, float(channel)))
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * (channel ** (1.0 / 2.4)) - 0.055


def _signed_cuberoot(value):
    if value < 0.0:
        return -((-value) ** (1.0 / 3.0))
    return value ** (1.0 / 3.0)


def _surface_distance_function(result):
    params = getattr(result, "parameters", {}) or {}
    result_type = getattr(result, "type", None)
    if result_type == "Plane":
        origin = params.get("origin")
        normal = params.get("z_axis")
        if origin is None or normal is None:
            return None
        normal = _unit(normal, [0.0, 0.0, 1.0])
        return lambda point: dot(_sub(point, origin), normal)

    if result_type == "Sphere":
        center = params.get("center", params.get("origin"))
        radius = params.get("radius")
        if center is None or radius is None:
            return None
        radius = float(radius)
        return lambda point: _length(_sub(point, center)) - radius

    if result_type == "Cylinder":
        endpoints = _axis_endpoints(params, getattr(result, "seed_position", (0.0, 0.0, 0.0)))
        radius = params.get("radius")
        if endpoints is None or radius is None:
            return None
        start, end = endpoints
        axis = _unit(_sub(end, start), [0.0, 0.0, 1.0])
        radius = float(radius)

        def cylinder_distance(point):
            offset = _sub(point, start)
            axial = dot(offset, axis)
            radial = _length(_sub(offset, _mul(axis, axial)))
            return radial - radius

        return cylinder_distance

    if result_type == "Cone":
        endpoints = _axis_endpoints(params, getattr(result, "seed_position", (0.0, 0.0, 0.0)))
        if endpoints is None:
            return None
        start, end = endpoints
        start_radius = float(params.get("start_radius", params.get("bottom_radius", 0.0)))
        end_radius = float(params.get("end_radius", params.get("top_radius", 0.0)))
        height = max(_length(_sub(end, start)), 1.0e-12)
        axis = _unit(_sub(end, start), [0.0, 0.0, 1.0])
        slope = (end_radius - start_radius) / height
        denominator = math.sqrt(slope * slope + 1.0)

        def cone_distance(point):
            offset = _sub(point, start)
            axial = dot(offset, axis)
            radial = _length(_sub(offset, _mul(axis, axial)))
            return (radial - (slope * axial + start_radius)) / denominator

        return cone_distance

    if result_type == "Torus":
        center = params.get("center", params.get("origin"))
        axis = params.get("axis", params.get("z_axis"))
        major_radius = params.get("major_radius", params.get("mean_radius"))
        tube_radius = params.get("tube_radius", params.get("minor_radius"))
        if center is None or axis is None or major_radius is None or tube_radius is None:
            return None
        axis = _unit(axis, [0.0, 0.0, 1.0])
        major_radius = abs(float(major_radius))
        tube_radius = abs(float(tube_radius))

        def torus_distance(point):
            offset = _sub(point, center)
            axial = dot(offset, axis)
            radial = _length(_sub(offset, _mul(axis, axial)))
            return math.sqrt((radial - major_radius) ** 2 + axial * axial) - tube_radius

        return torus_distance

    return None


def _surface_distance_native_spec(result):
    params = getattr(result, "parameters", {}) or {}
    result_type = getattr(result, "type", None)
    if result_type == "Plane":
        origin = params.get("origin")
        normal = params.get("z_axis")
        if origin is None or normal is None:
            return None
        return 1, list(origin[:3]) + list(normal[:3])

    if result_type == "Sphere":
        center = params.get("center", params.get("origin"))
        radius = params.get("radius")
        if center is None or radius is None:
            return None
        return 2, list(center[:3]) + [float(radius)]

    if result_type == "Cylinder":
        endpoints = _axis_endpoints(params, getattr(result, "seed_position", (0.0, 0.0, 0.0)))
        radius = params.get("radius")
        if endpoints is None or radius is None:
            return None
        start, end = endpoints
        return 3, list(start[:3]) + list(end[:3]) + [float(radius)]

    if result_type == "Cone":
        endpoints = _axis_endpoints(params, getattr(result, "seed_position", (0.0, 0.0, 0.0)))
        if endpoints is None:
            return None
        start, end = endpoints
        start_radius = float(params.get("start_radius", params.get("bottom_radius", 0.0)))
        end_radius = float(params.get("end_radius", params.get("top_radius", 0.0)))
        return 4, list(start[:3]) + list(end[:3]) + [start_radius, end_radius]

    if result_type == "Torus":
        center = params.get("center", params.get("origin"))
        axis = params.get("axis", params.get("z_axis"))
        major_radius = params.get("major_radius", params.get("mean_radius"))
        tube_radius = params.get("tube_radius", params.get("minor_radius"))
        if center is None or axis is None or major_radius is None or tube_radius is None:
            return None
        return 5, list(center[:3]) + list(axis[:3]) + [float(major_radius), float(tube_radius)]

    return None


def _axis_endpoints(params, fallback_center):
    start = params.get("start", params.get("bottom"))
    end = params.get("end", params.get("top"))
    if start is not None and end is not None:
        return start, end
    center = params.get("center", params.get("origin", fallback_center))
    axis = _unit(params.get("axis", params.get("z_axis", [0.0, 0.0, 1.0])), [0.0, 0.0, 1.0])
    height = float(params.get("height", 0.0))
    if height <= 1.0e-12:
        return None
    return _add(center, _mul(axis, -height * 0.5)), _add(center, _mul(axis, height * 0.5))


def _add(a, b):
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _mul(a, scale):
    return [a[0] * scale, a[1] * scale, a[2] * scale]


def _length(a):
    return math.sqrt(dot(a, a))


def _unit(a, fallback):
    size = _length(a)
    if size <= 1.0e-12:
        return list(fallback)
    return [a[0] / size, a[1] / size, a[2] / size]
