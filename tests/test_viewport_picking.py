import importlib.util
import math
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    carb_input.KEYBOARD_MODIFIER_FLAG_ALT = 4
    carb.log_warn = lambda message: None
    carb.input = carb_input
    sys.modules.setdefault("carb", carb)
    sys.modules.setdefault("carb.input", carb_input)

    omni = types.ModuleType("omni")
    appwindow = types.ModuleType("omni.appwindow")
    appwindow.get_default_app_window = lambda: None
    ui = types.ModuleType("omni.ui")
    scene = types.ModuleType("omni.ui.scene")

    class AbstractManipulatorModel:
        def __init__(self):
            pass

        def get_item(self, name):
            return name

        def _item_changed(self, item):
            pass

    class Manipulator:
        def __init__(self):
            pass

        def invalidate(self):
            pass

    scene.AbstractManipulatorModel = AbstractManipulatorModel
    scene.Manipulator = Manipulator
    scene.AspectRatioPolicy = types.SimpleNamespace(STRETCH=0)
    scene.SceneView = object
    scene.Points = lambda *args, **kwargs: None
    curve = lambda *args, **kwargs: None
    curve.CurveType = types.SimpleNamespace(LINEAR=0)
    scene.Curve = curve
    scene.PolygonMesh = lambda *args, **kwargs: None
    scene.Line = lambda *args, **kwargs: None
    ui.scene = scene
    omni.appwindow = appwindow
    omni.ui = ui
    sys.modules.setdefault("omni", omni)
    sys.modules.setdefault("omni.appwindow", appwindow)
    sys.modules.setdefault("omni.ui", ui)
    sys.modules.setdefault("omni.ui.scene", scene)


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


install_omni_stubs()
app_pkg = types.ModuleType("findsurface_omniverse")
app_pkg.__path__ = [str(APP_ROOT)]
sys.modules.setdefault("findsurface_omniverse", app_pkg)

load_module("findsurface_omniverse.camera", "camera.py")
viewport = load_module("findsurface_omniverse.viewport", "viewport.py")


class ViewportPickingTests(unittest.TestCase):
    def _make_view(self, on_camera_changed=None, on_hover_changed=None, on_seed_selected=None):
        view = viewport.PointCloudViewport(
            on_camera_changed=on_camera_changed,
            on_hover_changed=on_hover_changed,
            on_seed_selected=on_seed_selected,
        )
        view.point_cloud = types.SimpleNamespace(
            count=2,
            points=[[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]],
            point_buffer=None,
            bounds_min=[-1.0, -1.0, -1.0],
            bounds_max=[1.0, 1.0, 1.0],
        )
        view.active_mask = [True, True]
        return view

    def test_default_probe_radius_is_six_pixels(self):
        view = viewport.PointCloudViewport()

        self.assertEqual(view.probe_radius_px, 6.0)

    def test_destroy_releases_scene_views(self):
        view = viewport.PointCloudViewport()
        calls = []

        class Scene:
            def clear(self):
                calls.append("clear")

        class SceneView:
            def __init__(self):
                self.scene = Scene()

            def destroy(self):
                calls.append("destroy")

        view._scene_view = SceneView()
        view._orientation_view = SceneView()

        view.destroy(clear_scene=True)

        self.assertEqual(calls, ["clear", "clear", "destroy", "destroy"])
        self.assertIsNone(view._scene_view)
        self.assertIsNone(view._orientation_view)

    def test_destroy_releases_scene_views_even_when_scene_was_already_cleared(self):
        view = viewport.PointCloudViewport()
        calls = []

        class Scene:
            def clear(self):
                calls.append("clear")

        class SceneView:
            def __init__(self):
                self.scene = Scene()

            def destroy(self):
                calls.append("destroy")

        view._scene_view = SceneView()
        view._orientation_view = SceneView()

        view.destroy(clear_scene=False)

        self.assertEqual(calls, ["destroy", "destroy"])
        self.assertIsNone(view._scene_view)
        self.assertIsNone(view._orientation_view)

    def test_destroy_releases_scene_views_after_runtime_resource_release(self):
        view = viewport.PointCloudViewport()
        calls = []

        class Scene:
            def clear(self):
                calls.append("clear")

        class SceneView:
            def __init__(self):
                self.scene = Scene()

            def destroy(self):
                calls.append("destroy")

        view._scene_view = SceneView()
        view._orientation_view = SceneView()

        view.release_scene_resources(clear_scene=True)
        view.destroy(clear_scene=True)

        self.assertEqual(calls, ["clear", "clear", "destroy", "destroy"])
        self.assertIsNone(view._scene_view)
        self.assertIsNone(view._orientation_view)

    def test_orientation_overlay_refresh_invalidates_existing_overlay_without_rebuilding_scene(self):
        view = viewport.PointCloudViewport()
        calls = []
        view._orientation_view = types.SimpleNamespace(scene=types.SimpleNamespace(clear=lambda: calls.append("clear")))
        view._orientation_overlay = types.SimpleNamespace(invalidate=lambda: calls.append("invalidate"))

        view._refresh_orientation_overlay()

        self.assertEqual(calls, ["invalidate"])

    def test_left_click_selects_hover_candidate_from_press_time(self):
        selected = []
        view = self._make_view(on_seed_selected=selected.append)
        view.hover_index = 0
        view._pick_at = lambda x, y, **kwargs: 0 if x == 500.0 else 1

        view._on_mouse_pressed(500.0, 500.0, viewport.LEFT_BUTTON, 0)
        view._on_mouse_released(501.0, 500.0, viewport.LEFT_BUTTON, 0)

        self.assertEqual(view.selected_index, 0)
        self.assertEqual(selected, [0])

    def test_alt_left_click_selects_latest_successful_detection_seed(self):
        selected = []
        view = self._make_view(on_seed_selected=selected.append)
        view.set_retroactive_pick_index(1)
        view._pick_at = lambda *args, **kwargs: 0

        view._on_mouse_pressed(500.0, 500.0, viewport.LEFT_BUTTON, viewport.carb.input.KEYBOARD_MODIFIER_FLAG_ALT)
        view._on_mouse_released(500.0, 500.0, viewport.LEFT_BUTTON, viewport.carb.input.KEYBOARD_MODIFIER_FLAG_ALT)

        self.assertEqual(view.selected_index, 1)
        self.assertEqual(selected, [1])

    def test_alt_hover_marker_uses_retroactive_seed_without_changing_logical_hover(self):
        hovered = []
        view = self._make_view(on_hover_changed=hovered.append)
        view.set_retroactive_pick_index(1)
        view.set_retroactive_pick_active(True)
        view._pick_at = lambda *args, **kwargs: 0

        view.update_hover_pick(250.0, 150.0)

        self.assertEqual(view.hover_index, 0)
        self.assertEqual(view._display_hover_index(), 1)
        self.assertEqual(hovered, [0])

    def test_pick_at_uses_nearest_fallback_when_enabled(self):
        view = self._make_view()
        view.point_cloud.point_buffer = object()
        calls = []
        class Picker:
            def pick_orthographic(self, *args, **kwargs):
                calls.append(kwargs.get("fallback_to_nearest"))
                return 1 if kwargs.get("fallback_to_nearest") else None

        view._native_picker = Picker()

        picked = view._pick_at(500.0, 500.0)

        self.assertEqual(picked, 1)
        self.assertEqual(calls, [True])

    def test_selected_seed_click_disables_nearest_fallback(self):
        view = self._make_view()
        view.point_cloud.point_buffer = object()
        view.selected_index = 0
        calls = []
        class Picker:
            def pick_orthographic(self, *args, **kwargs):
                calls.append(kwargs.get("fallback_to_nearest"))
                return 1 if kwargs.get("fallback_to_nearest") else None

        view._native_picker = Picker()

        view._on_mouse_pressed(500.0, 500.0, viewport.LEFT_BUTTON, 0)

        self.assertIsNone(view._click_pick_index)
        self.assertEqual(calls, [False])

    def test_poll_hover_pick_updates_when_mouse_position_changes_inside_viewport(self):
        hovered = []
        view = self._make_view(on_hover_changed=hovered.append)
        view._input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (250.0, 150.0))
        view._pick_at = lambda x, y: 1

        view.poll_hover_pick()

        self.assertEqual(view.hover_index, 1)
        self.assertEqual(view._last_hover_mouse, (250.0, 150.0))
        self.assertEqual(hovered, [1])

    def test_polled_mouse_pixels_are_converted_to_ui_scaled_coordinates(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._ui_scale = 2.0
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (500.0, 250.0))

        x, y = view._poll_mouse_position()

        self.assertEqual((x, y), (250.0, 125.0))
        self.assertEqual(view._local_mouse(x, y), (150.0, 75.0))

    def test_poll_hover_pick_clears_hover_when_cursor_leaves_viewport(self):
        hovered = []
        view = self._make_view(on_hover_changed=hovered.append)
        view._input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (600.0, 150.0))
        view.hover_index = 1
        view._last_hover_mouse = (250.0, 150.0)
        view._mouse_over_input_rect = True

        view.poll_hover_pick()

        self.assertIsNone(view.hover_index)
        self.assertIsNone(view._last_hover_mouse)
        self.assertEqual(hovered, [None])

    def test_projection_switch_preserves_independent_zoom_scale(self):
        view = self._make_view()
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        initial_zoom = view.camera.zoom

        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)
        view._zoom_steps(1.0)
        view.set_projection_mode(viewport.PROJECTION_ORTHOGRAPHIC)
        view._zoom_steps(-1.0)
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)

        self.assertAlmostEqual(view.camera.zoom, initial_zoom)

    def test_camera_fit_uses_oblique_default_view_without_changing_fit_distance(self):
        view = self._make_view()
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])

        position = view.camera.position
        distance = math.sqrt(sum((position[index] - view.camera.center[index]) ** 2 for index in range(3)))

        self.assertLess(view.camera.forward[0], 0.0)
        self.assertLess(view.camera.forward[1], 0.0)
        self.assertLess(view.camera.forward[2], 0.0)
        self.assertGreater(position[0], view.camera.center[0])
        self.assertGreater(position[1], view.camera.center[1])
        self.assertGreater(position[2], view.camera.center[2])
        self.assertAlmostEqual(distance, max(view.camera.diameter, 1.0) * 2.0)

    def test_left_drag_orbit_direction_matches_drag_direction(self):
        view = self._make_view()
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        start_forward_x = view.camera.forward[0]

        view._on_mouse_pressed(100.0, 100.0, viewport.LEFT_BUTTON, 0)
        view._on_mouse_moved(130.0, 100.0, viewport.LEFT_BUTTON, 0)

        self.assertGreater(view.camera.forward[0], start_forward_x)

    def test_orientation_widget_draws_three_rotation_arcs(self):
        view = self._make_view()
        calls = []
        original_curve = viewport.sc.Curve

        def curve(points, **kwargs):
            calls.append((points, kwargs))

        curve.CurveType = types.SimpleNamespace(LINEAR=0)
        try:
            viewport.sc.Curve = curve
            view._draw_orientation_widget()
        finally:
            viewport.sc.Curve = original_curve

        self.assertEqual(len(calls), 3)
        self.assertTrue(all(len(points) == viewport.ORIENTATION_GIZMO_SEGMENTS + 1 for points, kwargs in calls))
        self.assertTrue(all(kwargs["curve_type"] == 0 for points, kwargs in calls))

    def test_orientation_gizmo_arcs_live_in_local_axis_planes(self):
        view = self._make_view()

        horizontal = view._orientation_gizmo_arc_points("horizontal")
        vertical = view._orientation_gizmo_arc_points("vertical")
        roll = view._orientation_gizmo_arc_points("roll")

        self.assertTrue(all(point[1] == 0.0 for point in horizontal))
        self.assertTrue(all(point[0] == 0.0 for point in vertical))
        self.assertTrue(all(point[2] == 0.0 for point in roll))

    def test_orientation_gizmo_hit_targets_select_rotation_axis(self):
        view = self._make_view()
        view._orientation_input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=viewport.ORIENTATION_WIDGET_SIZE,
            computed_height=viewport.ORIENTATION_WIDGET_SIZE,
        )
        center_x = 100.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5
        center_y = 50.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5
        radius = viewport.ORIENTATION_WIDGET_SIZE * 0.38

        self.assertEqual(view._orientation_gizmo_axis_at(center_x + radius * 0.5, center_y), "horizontal")
        self.assertEqual(view._orientation_gizmo_axis_at(center_x, center_y - radius * 0.5), "vertical")
        diagonal = radius / math.sqrt(2.0)
        self.assertEqual(view._orientation_gizmo_axis_at(center_x + diagonal, center_y + diagonal), "roll")
        self.assertIsNone(view._orientation_gizmo_axis_at(center_x + radius + 30.0, center_y + radius + 30.0))

    def test_orientation_gizmo_hover_updates_highlight_axis(self):
        view = self._make_view()
        invalidations = []
        view._orientation_overlay = types.SimpleNamespace(invalidate=lambda: invalidations.append(True))
        view._orientation_input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=viewport.ORIENTATION_WIDGET_SIZE,
            computed_height=viewport.ORIENTATION_WIDGET_SIZE,
        )
        center_x = 100.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5
        center_y = 50.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5

        view._on_orientation_mouse_moved(center_x + 20.0, center_y, viewport.LEFT_BUTTON, 0)
        self.assertEqual(view._orientation_hover_axis, "horizontal")

        view._on_orientation_mouse_hovered(False)
        self.assertIsNone(view._orientation_hover_axis)
        self.assertEqual(len(invalidations), 2)

    def test_poll_hover_pick_updates_orientation_gizmo_hover_before_point_pick(self):
        view = self._make_view()
        view._orientation_input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=viewport.ORIENTATION_WIDGET_SIZE,
            computed_height=viewport.ORIENTATION_WIDGET_SIZE,
        )
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (146.0, 96.0))
        view._pick_at = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("orientation hover should not point-pick"))

        view.poll_hover_pick()

        self.assertEqual(view._orientation_hover_axis, "horizontal")

    def test_poll_hover_pick_clears_orientation_gizmo_hover_when_cursor_leaves(self):
        view = self._make_view()
        view._orientation_hover_axis = "horizontal"
        view._orientation_input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=viewport.ORIENTATION_WIDGET_SIZE,
            computed_height=viewport.ORIENTATION_WIDGET_SIZE,
        )
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (20.0, 20.0))
        view._pick_at = lambda x, y: None

        view.poll_hover_pick()

        self.assertIsNone(view._orientation_hover_axis)

    def test_orientation_gizmo_hover_and_active_colors_highlight_selected_axis(self):
        view = self._make_view()
        curves = []
        lines = []
        points = []
        original_curve = viewport.sc.Curve
        original_line = viewport.sc.Line
        original_points = viewport.sc.Points

        def curve(points_arg, **kwargs):
            curves.append(kwargs)

        curve.CurveType = types.SimpleNamespace(LINEAR=0)
        try:
            viewport.sc.Curve = curve
            viewport.sc.Line = lambda *args, **kwargs: lines.append(kwargs)
            viewport.sc.Points = lambda *args, **kwargs: points.append(kwargs)

            view._orientation_hover_axis = "horizontal"
            view._draw_orientation_widget()
            hover_curve_color = curves[0]["colors"][0]
            hover_axis_color = lines[1]["color"]

            curves.clear()
            lines.clear()
            view._drag = {"mode": "orientation_gizmo", "axis": "horizontal"}
            view._draw_orientation_widget()
            active_curve_color = curves[0]["colors"][0]
            active_axis_color = lines[1]["color"]
        finally:
            viewport.sc.Curve = original_curve
            viewport.sc.Line = original_line
            viewport.sc.Points = original_points

        self.assertNotEqual(hover_curve_color, viewport.ORIENTATION_GIZMO_COLORS["horizontal"])
        self.assertEqual(active_curve_color, viewport.ORIENTATION_GIZMO_ACTIVE_COLOR)
        self.assertNotEqual(hover_axis_color, viewport.ORIENTATION_AXIS_COLORS[1][0])
        self.assertEqual(active_axis_color, viewport.ORIENTATION_GIZMO_ACTIVE_COLOR)

    def test_orientation_gizmo_horizontal_drag_rotates_camera_and_skips_picking(self):
        changed = []
        view = self._make_view(on_camera_changed=lambda: changed.append(True))
        view._orientation_input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=viewport.ORIENTATION_WIDGET_SIZE,
            computed_height=viewport.ORIENTATION_WIDGET_SIZE,
        )
        view._pick_at = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("orientation gizmo should not pick"))
        draws = []
        view.draw = lambda: draws.append(True)
        center_x = 100.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5
        center_y = 50.0 + viewport.ORIENTATION_WIDGET_SIZE * 0.5
        start_x = center_x + 24.0

        view._on_orientation_mouse_pressed(start_x, center_y, viewport.LEFT_BUTTON, 0)
        view._on_orientation_mouse_moved(start_x + 20.0, center_y, viewport.LEFT_BUTTON, 0)
        view._on_orientation_mouse_released(start_x + 20.0, center_y, viewport.LEFT_BUTTON, 0)

        self.assertIsNone(view._drag)
        self.assertLess(view.camera.forward[0], 0.0)
        self.assertEqual(len(draws), 1)
        self.assertEqual(len(changed), 1)

    def test_orientation_gizmo_drag_moves_grabbed_ring_position_with_cursor(self):
        cases = (
            ("horizontal", 20.0, 0.0, 12.0, 0.0, 0, -1),
            ("vertical", 0.0, -20.0, 0.0, -12.0, 1),
            ("roll", 24.72, -24.72, -8.0, -8.0, 1),
        )
        for case in cases:
            axis, start_dx, start_dy, move_dx, move_dy, component, *direction = case
            with self.subTest(axis=axis):
                view = self._make_view()
                view._orientation_input_rect = types.SimpleNamespace(
                    screen_position_x=0.0,
                    screen_position_y=0.0,
                    computed_width=viewport.ORIENTATION_WIDGET_SIZE,
                    computed_height=viewport.ORIENTATION_WIDGET_SIZE,
                )
                view.draw = lambda: None
                center_x = viewport.ORIENTATION_WIDGET_SIZE * 0.5
                center_y = viewport.ORIENTATION_WIDGET_SIZE * 0.5
                start_x = center_x + start_dx
                start_y = center_y + start_dy
                grabbed = view._orientation_gizmo_ring_vector(axis, start_x, start_y)
                before = view._orientation_gizmo_project_point(grabbed)[component]

                view._on_orientation_mouse_pressed(start_x, start_y, viewport.LEFT_BUTTON, 0)
                view._on_mouse_moved(start_x + move_dx, start_y + move_dy, viewport.LEFT_BUTTON, 0)

                after = view._orientation_gizmo_project_point(grabbed)[component]
                direction = direction[0] if direction else 1
                if component == 0 and direction > 0:
                    self.assertGreater(after, before)
                elif component == 0:
                    self.assertLess(after, before)
                else:
                    self.assertLess(after, before)

    def test_perspective_center_plane_scale_matches_orthographic_zoom(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(computed_width=800.0, computed_height=600.0)
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        view.camera.zoom = 2.5
        view.camera.set_fov_degrees(60.0)
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)

        aspect = 800.0 / 600.0
        focal_px = 600.0 * 0.5 / math.tan(math.radians(60.0) * 0.5)
        perspective_scale_at_center = focal_px / view.camera.perspective_distance(aspect)

        self.assertAlmostEqual(perspective_scale_at_center, view._pixel_scale(800.0, 600.0))

    def test_scale_ruler_uses_orthographic_world_units_per_pixel(self):
        view = self._make_view()
        view.camera.diameter = 4.0
        view.camera.zoom = 2.0
        view.set_projection_mode(viewport.PROJECTION_ORTHOGRAPHIC)

        spec = view._scale_ruler_spec(width=800.0, height=600.0, ruler_width_px=100.0)

        self.assertAlmostEqual(spec["pixel_scale"], 300.0)
        self.assertAlmostEqual(spec["world_length"], 1.0 / 3.0)
        self.assertEqual(spec["label"], "0.333 units")
        self.assertEqual([round(value, 1) for value in spec["tick_offsets"]], [30.0, 60.0, 90.0])

    def test_scale_ruler_is_hidden_in_perspective_projection(self):
        view = self._make_view()
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)

        self.assertIsNone(view._scale_ruler_spec(width=800.0, height=600.0))

    def test_scale_ruler_draws_fixed_screen_width_ticks(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.diameter = 4.0
        view.camera.zoom = 2.0
        lines = []
        original_line = viewport.sc.Line

        try:
            viewport.sc.Line = lambda start, end, **kwargs: lines.append((start, end, kwargs))
            view._draw_scale_ruler()
        finally:
            viewport.sc.Line = original_line

        self.assertEqual(len(lines), 6)
        baseline = lines[0]
        self.assertAlmostEqual(viewport._length(viewport.sub(baseline[1], baseline[0])), 1.0 / 3.0)
        self.assertTrue(all(call[2]["color"] == viewport.SCALE_RULER_COLOR for call in lines))

    def test_scale_ruler_hit_test_uses_current_overlay_position(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.diameter = 4.0
        view.camera.zoom = 2.0
        spec = view._scale_ruler_spec(width=800.0, height=600.0)

        self.assertTrue(view._scale_ruler_hit_test(100.0 + spec["left"] + 40.0, 50.0 + spec["top"] + 3.0))
        self.assertFalse(view._scale_ruler_hit_test(100.0 + spec["right"] + 80.0, 50.0 + spec["baseline"] + 80.0))

        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)

        self.assertFalse(view._scale_ruler_hit_test(100.0 + spec["left"] + 40.0, 50.0 + spec["top"] + 3.0))

    def test_scale_ruler_plain_left_drag_repositions_overlay_without_camera_or_pick(self):
        camera_events = []
        view = self._make_view(on_camera_changed=camera_events.append)
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.diameter = 4.0
        view.camera.zoom = 2.0
        view._pick_at = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scale drag should not pick"))
        start = view._scale_ruler_spec(width=800.0, height=600.0)

        view._on_mouse_pressed(start["left"] + 45.0, start["baseline"] - 4.0, viewport.LEFT_BUTTON, 0)
        view._on_mouse_moved(start["left"] + 145.0, start["baseline"] - 54.0, viewport.LEFT_BUTTON, 0)
        view._on_mouse_released(start["left"] + 145.0, start["baseline"] - 54.0, viewport.LEFT_BUTTON, 0)

        moved = view._scale_ruler_spec(width=800.0, height=600.0)
        self.assertAlmostEqual(moved["left"], start["left"] + 100.0)
        self.assertAlmostEqual(moved["baseline"], start["baseline"] - 50.0)
        self.assertIsNone(view._drag)
        self.assertEqual(camera_events, [])

    def test_scale_ruler_drag_clamps_inside_viewport_and_moves_label(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=320.0,
            computed_height=220.0,
        )
        view._scale_ruler_label = types.SimpleNamespace(text="")
        view._scale_ruler_label_left_spacer = types.SimpleNamespace(width=None)
        view._scale_ruler_label_top_spacer = types.SimpleNamespace(height=None)

        view._set_scale_ruler_position(500.0, 500.0, width=320.0, height=220.0)
        spec = view._scale_ruler_spec(width=320.0, height=220.0)

        self.assertLessEqual(spec["right"], 320.0)
        self.assertLessEqual(spec["label_left"] + spec["label_width"], 320.0)
        self.assertLessEqual(spec["baseline"], 220.0)
        self.assertEqual(view._scale_ruler_label_left_spacer.width, spec["label_left"])
        self.assertEqual(view._scale_ruler_label_top_spacer.height, spec["label_top"])
        self.assertEqual(view._scale_ruler_label.text, spec["label"])

    def test_scale_ruler_hover_panel_keeps_right_padding_tight_for_short_labels(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.diameter = 4.0
        view.camera.zoom = 2.0

        spec = view._scale_ruler_spec(width=800.0, height=600.0)
        panel = view._scale_ruler_panel_spec(spec)

        self.assertLess(spec["label_width"], viewport.SCALE_RULER_LABEL_WIDTH)
        self.assertAlmostEqual(panel["right"] - spec["right"], viewport.SCALE_RULER_HOVER_PADDING)

    def test_scale_ruler_position_refresh_rebuilds_label_frame_at_current_position(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )

        class Frame:
            def __init__(self):
                self.clear_count = 0

            def clear(self):
                self.clear_count += 1

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        frame = Frame()
        calls = []
        view._scale_ruler_frame = frame
        view._build_scale_ruler_label_body = lambda spec, text: calls.append((spec["label_left"], spec["label_top"], text))

        view._set_scale_ruler_position(120.0, 360.0, width=800.0, height=600.0)

        spec = view._scale_ruler_spec(width=800.0, height=600.0)
        self.assertGreater(frame.clear_count, 0)
        self.assertEqual(calls[-1], (spec["label_left"], spec["label_top"], spec["label"]))

    def test_scale_ruler_hover_state_refreshes_label_frame(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )

        class Frame:
            def clear(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        visual_states = []
        view._scale_ruler_frame = Frame()
        view._build_scale_ruler_label_body = lambda spec, text: visual_states.append(view._is_scale_ruler_visual_active())

        self.assertTrue(view._set_scale_ruler_hovered(True))
        self.assertTrue(view._set_scale_ruler_hovered(False))

        self.assertEqual(visual_states[-2:], [True, False])

    def test_disabled_picking_skips_hover_polling(self):
        hovered = []
        view = self._make_view(on_hover_changed=hovered.append)
        view.set_picking_enabled(False)
        view._input_rect = types.SimpleNamespace(
            screen_position_x=100.0,
            screen_position_y=50.0,
            computed_width=400.0,
            computed_height=300.0,
        )
        view._mouse = object()
        view._input = types.SimpleNamespace(get_mouse_coords_pixel=lambda mouse: (250.0, 150.0))
        view._pick_at = lambda x, y: 1

        view.poll_hover_pick()

        self.assertIsNone(view.hover_index)
        self.assertEqual(hovered, [])

    def test_disabled_picking_does_not_change_selection_on_click(self):
        selected = []
        view = self._make_view(on_seed_selected=selected.append)
        view.selected_index = 1
        view.set_picking_enabled(False)
        view._pick_at = lambda x, y: 0

        view._on_mouse_pressed(500.0, 500.0, viewport.LEFT_BUTTON, 0)
        view._on_mouse_released(500.0, 500.0, viewport.LEFT_BUTTON, 0)

        self.assertEqual(view.selected_index, 1)
        self.assertEqual(selected, [])

    def test_perspective_pick_uses_native_picker_when_point_buffer_exists(self):
        calls = []
        view = self._make_view()
        view.point_cloud.point_buffer = object()
        view._active_mask_buffer = object()
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)
        view._native_picker = types.SimpleNamespace(
            pick_perspective=lambda *args, **kwargs: calls.append((args, kwargs)) or 1,
        )

        picked = view._pick_at(500.0, 500.0)

        self.assertEqual(picked, 1)
        self.assertEqual(len(calls), 1)

    def test_perspective_seed_radius_follows_cursor_at_hover_depth(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        view.camera.set_fov_degrees(60.0)
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)
        view.seed_radius = 0.25
        view.hover_index = 0
        view._last_hover_mouse = (500.0, 250.0)

        center, radius = view._seed_radius_circle_spec()

        aspect = 800.0 / 600.0
        origin = view.camera.perspective_position(aspect)
        depth = viewport.dot(viewport.sub(view.point_cloud.points[0], origin), view.camera.forward)
        focal_px = 600.0 * 0.5 / math.tan(math.radians(60.0) * 0.5)
        offset_x = (500.0 - 400.0) * depth / focal_px
        offset_y = (300.0 - 250.0) * depth / focal_px
        expected = viewport.add(
            origin,
            viewport.add(
                viewport.mul(view.camera.forward, depth),
                viewport.add(viewport.mul(view.camera.right, offset_x), viewport.mul(view.camera.up, offset_y)),
            ),
        )
        self.assertEqual(len(center), 3)
        for index in range(3):
            self.assertAlmostEqual(center[index], expected[index])
        self.assertEqual(radius, 0.25)

    def test_seed_radius_uses_selected_point_as_fixed_center(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)
        view.seed_radius = 0.2
        view.hover_index = 0
        view.selected_index = 1
        view._last_hover_mouse = (500.0, 250.0)

        center, radius = view._seed_radius_circle_spec()

        self.assertEqual(center, [0.5, 0.0, 0.0])
        self.assertEqual(radius, 0.2)

    def test_perspective_seed_radius_waits_for_hover_or_selection_depth(self):
        view = self._make_view()
        view._input_rect = types.SimpleNamespace(
            screen_position_x=0.0,
            screen_position_y=0.0,
            computed_width=800.0,
            computed_height=600.0,
        )
        view.camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        view.set_projection_mode(viewport.PROJECTION_PERSPECTIVE)
        view._last_hover_mouse = (500.0, 250.0)

        self.assertIsNone(view._seed_radius_circle_spec())

    def test_surface_updates_refresh_overlays_without_rebuilding_point_cloud_scene(self):
        class Overlay:
            def __init__(self):
                self.invalidations = 0

            def invalidate(self):
                self.invalidations += 1

        view = self._make_view()
        surface_overlay = Overlay()
        inlier_overlay = Overlay()
        view._surface_overlay = surface_overlay
        view._inlier_overlay = inlier_overlay
        rebuilds = []
        view._rebuild_scene = lambda: rebuilds.append(True)

        view.set_surfaces([types.SimpleNamespace(type="Unknown", inlier_indices=[0, 1, 99])])

        self.assertEqual(rebuilds, [])
        self.assertEqual(surface_overlay.invalidations, 1)
        self.assertEqual(inlier_overlay.invalidations, 1)
        points, colors = view._inlier_point_chunks[0]
        self.assertEqual(points, [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])
        self.assertEqual(colors, [view.inlier_color, view.inlier_color])

    def test_selected_result_rebuilds_surface_mesh_with_highlight_style(self):
        view = self._make_view()
        result = types.SimpleNamespace(id="Plane_1", type="Plane", seed_position=[0.0, 0.0, 0.0], inlier_indices=[])
        calls = []
        original_builder = viewport.build_surface_preview_mesh

        def build_mesh(surface, solid_color=None):
            calls.append((surface.id, solid_color))
            return types.SimpleNamespace(
                points=[[0.0, 0.0, 0.0]],
                colors=[],
                vertex_counts=[],
                vertex_indices=[],
                wire_lines=[],
            )

        try:
            viewport.build_surface_preview_mesh = build_mesh
            view.set_surfaces([result])
            changed = view.set_selected_result("Plane_1")
        finally:
            viewport.build_surface_preview_mesh = original_builder

        self.assertTrue(changed)
        self.assertEqual(view.selected_result_id, "Plane_1")
        self.assertEqual(calls[-1], ("Plane_1", viewport.SELECTED_SURFACE_SOLID_COLOR))
        self.assertTrue(view._surface_meshes[0].selected)
        self.assertEqual(view._surface_meshes[0].result_id, "Plane_1")

    def test_focus_result_fits_camera_to_result_bounds(self):
        view = self._make_view()
        result = types.SimpleNamespace(id="Sphere_1", type="Sphere", seed_position=[0.0, 0.0, 0.0], inlier_indices=[])
        original_builder = viewport.build_surface_preview_mesh
        original_bounds = viewport.mesh_bounds

        def build_mesh(surface, solid_color=None):
            return types.SimpleNamespace(
                points=[[2.0, 3.0, 4.0], [4.0, 7.0, 10.0]],
                colors=[],
                vertex_counts=[],
                vertex_indices=[],
                wire_lines=[],
            )

        def bounds(meshes):
            points = [point for mesh in meshes for point in mesh.points]
            return (
                [min(point[axis] for point in points) for axis in range(3)],
                [max(point[axis] for point in points) for axis in range(3)],
            )

        try:
            viewport.build_surface_preview_mesh = build_mesh
            viewport.mesh_bounds = bounds
            view.set_surfaces([result])
            focused = view.focus_result("Sphere_1")
        finally:
            viewport.build_surface_preview_mesh = original_builder
            viewport.mesh_bounds = original_bounds

        self.assertTrue(focused)
        self.assertEqual(view.camera.center, [3.0, 5.0, 7.0])

    def test_draw_inliers_uses_distinct_overlay_points(self):
        view = self._make_view()
        view._inlier_point_chunks = [
            (
                [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]],
                [viewport.INLIER_NEAR_COLOR, viewport.INLIER_FAR_COLOR],
            )
        ]
        calls = []
        original_points = viewport.sc.Points
        viewport.sc.Points = lambda points, **kwargs: calls.append((points, kwargs))
        try:
            view._draw_inliers()
        finally:
            viewport.sc.Points = original_points

        self.assertEqual(calls[0][0], [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])
        self.assertEqual(calls[0][1]["colors"], [viewport.INLIER_NEAR_COLOR, viewport.INLIER_FAR_COLOR])
        self.assertGreater(calls[0][1]["sizes"][0], view.point_size)

    def test_inlier_colors_interpolate_signed_distance_by_actual_standard_deviation(self):
        view = self._make_view()
        view.point_cloud.points = [
            [0.9, 0.0, 0.0],
            [0.95, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.05, 0.0, 0.0],
            [1.1, 0.0, 0.0],
        ]
        view.point_cloud.count = 5
        result = types.SimpleNamespace(
            type="Sphere",
            seed_position=[0.0, 0.0, 0.0],
            inlier_indices=[0, 1, 2, 3, 4],
            measurement_accuracy=999.0,
            parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
        )

        chunks = view._build_result_inlier_chunks(result)

        colors = chunks[0][1]
        self.assertEqual(colors[0], viewport.INLIER_NEGATIVE_COLOR)
        self.assertNotEqual(colors[1], viewport.INLIER_NEGATIVE_COLOR)
        self.assertEqual(colors[2], viewport.INLIER_ZERO_COLOR)
        self.assertNotEqual(colors[3], viewport.INLIER_POSITIVE_COLOR)
        self.assertEqual(colors[4], viewport.INLIER_POSITIVE_COLOR)

    def test_selected_point_cloud_uses_dark_base_color(self):
        view = self._make_view()

        self.assertEqual(view._point_cloud_color(), view.point_color)
        view.selected_index = 1

        self.assertEqual(view._point_cloud_color(), viewport.SELECTED_POINT_CLOUD_COLOR)

    def test_selection_presence_change_rebuilds_point_cloud_scene(self):
        view = self._make_view()
        rebuilds = []
        pick_refreshes = []
        view._rebuild_scene = lambda: rebuilds.append(True)
        view._refresh_pick_overlay = lambda: pick_refreshes.append(True)

        view.set_pick_markers(hover_index=0, selected_index=1)
        view.set_pick_markers(hover_index=1, selected_index=0)
        view.set_pick_markers(hover_index=1, selected_index=None)

        self.assertEqual(rebuilds, [True, True])
        self.assertEqual(pick_refreshes, [True])

    def test_selected_point_suppresses_hover_pick_updates(self):
        hovered = []
        view = self._make_view(on_hover_changed=hovered.append)
        view.selected_index = 1
        view.hover_index = 0
        pick_calls = []
        view._pick_at = lambda x, y: pick_calls.append((x, y)) or 0

        view.update_hover_pick(200.0, 150.0)

        self.assertEqual(pick_calls, [])
        self.assertIsNone(view.hover_index)
        self.assertEqual(hovered, [None])
        self.assertEqual(view._last_hover_mouse, (200.0, 150.0))

    def test_set_pick_markers_clears_hover_when_selected_marker_exists(self):
        view = self._make_view()

        view.set_pick_markers(hover_index=0, selected_index=1)

        self.assertIsNone(view.hover_index)
        self.assertEqual(view.selected_index, 1)

    def test_inlier_color_setter_rebuilds_cached_distance_colors(self):
        view = self._make_view()
        view.point_cloud.points = [[1.0, 0.0, 0.0]]
        view.surface_results = [
            types.SimpleNamespace(
                type="Sphere",
                seed_position=[0.0, 0.0, 0.0],
                inlier_indices=[0],
                measurement_accuracy=0.1,
                parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
            )
        ]

        view.set_inlier_colors(
            negative_color=[0.0, 0.0, 1.0, 0.6],
            zero_color=[0.2, 0.8, 0.9, 0.7],
            positive_color=[1.0, 0.0, 0.0, 0.9],
        )

        self.assertEqual(view._inlier_point_chunks[0][1][0], [0.2, 0.8, 0.9, 0.7])

    def test_inlier_sigma_setter_rebuilds_cached_distance_colors(self):
        view = self._make_view()
        view.point_cloud.points = [
            [0.9, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.1, 0.0, 0.0],
        ]
        view.point_cloud.count = 3
        view.surface_results = [
            types.SimpleNamespace(
                type="Sphere",
                seed_position=[0.0, 0.0, 0.0],
                inlier_indices=[0, 1, 2],
                measurement_accuracy=999.0,
                parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
            )
        ]

        view.set_inlier_colors()
        default_color = view._inlier_point_chunks[0][1][0]
        view.set_inlier_colors(negative_sigma=-2.0)

        self.assertEqual(default_color, viewport.INLIER_NEGATIVE_COLOR)
        self.assertNotEqual(view._inlier_point_chunks[0][1][0], viewport.INLIER_NEGATIVE_COLOR)

    def test_inlier_distance_color_uses_custom_sigma_boundaries(self):
        color = viewport._inlier_distance_color(-0.1, 0.1, negative_sigma=-2.0, positive_sigma=2.0)

        self.assertNotEqual(color, viewport.INLIER_NEGATIVE_COLOR)
        self.assertEqual(viewport._inlier_distance_color(-0.2, 0.1, negative_sigma=-2.0), viewport.INLIER_NEGATIVE_COLOR)
        self.assertEqual(viewport._inlier_distance_color(0.2, 0.1, positive_sigma=2.0), viewport.INLIER_POSITIVE_COLOR)

    def test_inlier_distance_histogram_requires_native_picker(self):
        point_cloud = types.SimpleNamespace(points=[[1.0, 0.0, 0.0]], count=1)
        result = types.SimpleNamespace(
            type="Sphere",
            inlier_indices=[0],
            parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
        )

        self.assertIsNone(viewport.build_inlier_distance_histogram(point_cloud, result, bin_count=23))

    def test_inlier_distance_histogram_adds_representative_colors_to_native_bins(self):
        class NativePicker:
            def build_inlier_distance_histogram(self, *args, **kwargs):
                return {
                    "count": 3,
                    "source_count": 3,
                    "excluded_count": 0,
                    "bin_count": 23,
                    "min": -0.1,
                    "max": 0.1,
                    "mean": 0.0,
                    "sigma": 0.1,
                    "source_sigma": 0.1,
                    "range_min": -0.3,
                    "range_max": 0.3,
                    "mean_fraction": 0.5,
                    "zero_fraction": 0.5,
                    "negative_count": 1,
                    "zero_count": 1,
                    "positive_count": 1,
                    "max_bin_count": 1,
                    "bins": [
                        {"start": -0.30, "end": -0.25, "center": -0.275, "count": 1},
                        {"start": -0.01, "end": 0.01, "center": 0.0, "count": 1},
                        {"start": 0.25, "end": 0.30, "center": 0.275, "count": 1},
                    ],
                }

        point_cloud = types.SimpleNamespace(
            point_buffer=object(),
            count=3,
        )
        result = types.SimpleNamespace(
            type="Sphere",
            inlier_indices=[0, 1, 2],
            measurement_accuracy=999.0,
            parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
        )

        histogram = viewport.build_inlier_distance_histogram(
            point_cloud,
            result,
            bin_count=23,
            native_picker=NativePicker(),
        )

        self.assertEqual(histogram["count"], 3)
        self.assertAlmostEqual(histogram["range_min"], -3.0 * histogram["sigma"])
        self.assertAlmostEqual(histogram["range_max"], 3.0 * histogram["sigma"])
        self.assertEqual(histogram["bins"][0]["color"], viewport.INLIER_NEGATIVE_COLOR)
        self.assertEqual(histogram["bins"][1]["color"], viewport.INLIER_ZERO_COLOR)
        self.assertEqual(histogram["bins"][2]["color"], viewport.INLIER_POSITIVE_COLOR)

    def test_inlier_distance_histogram_uses_native_fast_path_when_point_buffer_exists(self):
        class NativePicker:
            def __init__(self):
                self.calls = []

            def build_inlier_distance_histogram(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return {
                    "count": 1,
                    "source_count": 1,
                    "excluded_count": 0,
                    "bin_count": 23,
                    "min": 0.0,
                    "max": 0.0,
                    "mean": 0.0,
                    "sigma": 0.0,
                    "source_sigma": 0.0,
                    "range_min": -1.0e-6,
                    "range_max": 1.0e-6,
                    "mean_fraction": 0.5,
                    "zero_fraction": 0.5,
                    "negative_count": 0,
                    "zero_count": 1,
                    "positive_count": 0,
                    "max_bin_count": 1,
                    "bins": [
                        {
                            "start": -1.0e-6,
                            "end": 1.0e-6,
                            "center": 0.0,
                            "count": 1,
                            "fraction": 1.0,
                            "percent": 100.0,
                            "sigma_offset": None,
                        }
                    ],
                }

        picker = NativePicker()
        point_cloud = types.SimpleNamespace(
            points=[[0.0, 0.0, 0.0]],
            point_buffer=object(),
            count=1,
        )
        result = types.SimpleNamespace(
            type="Sphere",
            inlier_indices=[0],
            parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
        )

        histogram = viewport.build_inlier_distance_histogram(point_cloud, result, native_picker=picker)

        self.assertEqual(histogram["count"], 1)
        self.assertEqual(histogram["bins"][0]["color"], viewport.INLIER_ZERO_COLOR)
        self.assertEqual(len(picker.calls), 1)
        args, kwargs = picker.calls[0]
        self.assertIs(args[0], point_cloud.point_buffer)
        self.assertEqual(args[1], 1)
        self.assertEqual(args[2], [0])
        self.assertEqual(args[3], 2)
        self.assertEqual(args[4], [0.0, 0.0, 0.0, 1.0])

    def test_hover_detection_histogram_draws_mean_marker(self):
        view = self._make_view()
        rectangles = []
        spacers = []
        widths = viewport._histogram_bar_widths(
            35,
            viewport.HOVER_DETECTION_HISTOGRAM_WIDTH,
            viewport.HOVER_DETECTION_HISTOGRAM_SPACING,
        )
        middle_index = len(widths) // 2
        middle_center = (
            sum(widths[:middle_index])
            + viewport.HOVER_DETECTION_HISTOGRAM_SPACING * middle_index
            + widths[middle_index] * 0.5
        )

        self.assertAlmostEqual(middle_center, viewport.HOVER_DETECTION_HISTOGRAM_WIDTH * 0.5)

        class UiContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        original_hstack = getattr(viewport.ui, "HStack", None)
        original_vstack = getattr(viewport.ui, "VStack", None)
        original_zstack = getattr(viewport.ui, "ZStack", None)
        original_spacer = getattr(viewport.ui, "Spacer", None)
        original_rectangle = getattr(viewport.ui, "Rectangle", None)
        original_label = getattr(viewport.ui, "Label", None)
        try:
            viewport.ui.HStack = lambda **kwargs: UiContext()
            viewport.ui.VStack = lambda **kwargs: UiContext()
            viewport.ui.ZStack = lambda **kwargs: UiContext()
            viewport.ui.Spacer = lambda **kwargs: spacers.append(dict(kwargs))
            viewport.ui.Label = lambda *args, **kwargs: None
            viewport.ui.Rectangle = lambda **kwargs: rectangles.append(dict(kwargs))

            view._build_hover_detection_histogram(
                {
                    "max_bin_count": 2,
                    "zero_fraction": 0.5,
                    "mean_fraction": 0.0,
                    "bins": [
                        {"count": 1, "color": viewport.INLIER_NEGATIVE_COLOR},
                        {"count": 2, "color": viewport.INLIER_POSITIVE_COLOR},
                    ],
                }
            )
        finally:
            if original_hstack is None:
                delattr(viewport.ui, "HStack")
            else:
                viewport.ui.HStack = original_hstack
            if original_vstack is None:
                delattr(viewport.ui, "VStack")
            else:
                viewport.ui.VStack = original_vstack
            if original_zstack is None:
                delattr(viewport.ui, "ZStack")
            else:
                viewport.ui.ZStack = original_zstack
            if original_spacer is None:
                delattr(viewport.ui, "Spacer")
            else:
                viewport.ui.Spacer = original_spacer
            if original_rectangle is None:
                delattr(viewport.ui, "Rectangle")
            else:
                viewport.ui.Rectangle = original_rectangle
            if original_label is None:
                delattr(viewport.ui, "Label")
            else:
                viewport.ui.Label = original_label

        marker_rectangles = [
            rectangle
            for rectangle in rectangles
            if rectangle.get("style") == {"background_color": 0xFFFFFFFF}
        ]
        negative_color = viewport._rgba_to_ui_color(viewport.INLIER_NEGATIVE_COLOR)
        positive_color = viewport._rgba_to_ui_color(viewport.INLIER_POSITIVE_COLOR)
        self.assertEqual(negative_color, 0xFFFF3800)
        self.assertEqual(positive_color, 0xFF0005FF)
        bar_colors = [
            rectangle.get("style", {}).get("background_color")
            for rectangle in rectangles
            if rectangle.get("style", {}).get("background_color") in {negative_color, positive_color}
        ]

        self.assertEqual(bar_colors, [negative_color, positive_color])
        self.assertEqual(view._histogram_fraction_offset(0.0, viewport.HOVER_DETECTION_HISTOGRAM_WIDTH), 0)
        self.assertEqual(
            view._histogram_fraction_offset(1.0, viewport.HOVER_DETECTION_HISTOGRAM_WIDTH),
            viewport.HOVER_DETECTION_HISTOGRAM_WIDTH - 1,
        )
        self.assertEqual([rectangle.get("width") for rectangle in marker_rectangles[-4:]], [2, 4, 6, 8])
        self.assertIn(
            {"width": viewport.HOVER_DETECTION_HISTOGRAM_WIDTH - 8},
            spacers,
        )
        self.assertIn(
            {"width": 0},
            spacers,
        )

    def test_hover_detection_overlay_draws_all_rows_before_histogram(self):
        view = self._make_view()
        labels = []
        zstacks = []

        class UiContext:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        original_hstack = getattr(viewport.ui, "HStack", None)
        original_vstack = getattr(viewport.ui, "VStack", None)
        original_zstack = getattr(viewport.ui, "ZStack", None)
        original_spacer = getattr(viewport.ui, "Spacer", None)
        original_rectangle = getattr(viewport.ui, "Rectangle", None)
        original_label = getattr(viewport.ui, "Label", None)
        try:
            viewport.ui.HStack = lambda **kwargs: UiContext()
            viewport.ui.VStack = lambda **kwargs: UiContext()
            viewport.ui.ZStack = lambda **kwargs: zstacks.append(dict(kwargs)) or UiContext()
            viewport.ui.Spacer = lambda **kwargs: None
            viewport.ui.Rectangle = lambda **kwargs: None
            viewport.ui.Label = lambda text, **kwargs: labels.append(str(text))

            view._build_hover_detection_overlay_body(
                {
                    "result_type": "Torus",
                    "rows": [
                        ("Seed Index", "1"),
                        ("Inliers", "2 pts"),
                        ("RMS", "1.2e-03"),
                        ("Pos", "(1, 0, 0)"),
                        ("Axis", "(0, 1, 0)"),
                        ("Size", "R=2 r=0.5"),
                    ],
                    "histogram": {
                        "max_bin_count": 1,
                        "bins": [{"count": 1, "color": viewport.INLIER_ZERO_COLOR}],
                    },
                }
            )
        finally:
            if original_hstack is None:
                delattr(viewport.ui, "HStack")
            else:
                viewport.ui.HStack = original_hstack
            if original_vstack is None:
                delattr(viewport.ui, "VStack")
            else:
                viewport.ui.VStack = original_vstack
            if original_zstack is None:
                delattr(viewport.ui, "ZStack")
            else:
                viewport.ui.ZStack = original_zstack
            if original_spacer is None:
                delattr(viewport.ui, "Spacer")
            else:
                viewport.ui.Spacer = original_spacer
            if original_rectangle is None:
                delattr(viewport.ui, "Rectangle")
            else:
                viewport.ui.Rectangle = original_rectangle
            if original_label is None:
                delattr(viewport.ui, "Label")
            else:
                viewport.ui.Label = original_label

        self.assertEqual(
            [label for label in labels if label in {"Seed Index", "Inliers", "RMS", "Pos", "Axis", "Size"}],
            ["Seed Index", "Inliers", "RMS", "Pos", "Axis", "Size"],
        )
        self.assertEqual(zstacks[0]["height"], viewport.HOVER_DETECTION_OVERLAY_MAX_HEIGHT)

    def test_hover_detection_overlay_grows_upward_by_one_row(self):
        view = self._make_view()
        five_rows = {"rows": [(str(index), str(index)) for index in range(5)]}
        six_rows = {"rows": [(str(index), str(index)) for index in range(6)]}

        self.assertEqual(view._hover_detection_overlay_height(five_rows), viewport.HOVER_DETECTION_OVERLAY_HEIGHT)
        self.assertEqual(view._hover_detection_overlay_height(six_rows), viewport.HOVER_DETECTION_OVERLAY_MAX_HEIGHT)

    def test_inlier_distance_histogram_is_unavailable_without_point_buffer(self):
        point_cloud = types.SimpleNamespace(
            points=[[0.9, 0.0, 0.0], [1.0, 0.0, 0.0], [1.1, 0.0, 0.0]],
            count=3,
        )
        result = types.SimpleNamespace(
            type="Sphere",
            inlier_indices=[-1, 0, 1, 2, 99],
            parameters={"center": [0.0, 0.0, 0.0], "radius": 1.0},
        )

        histogram = viewport.build_inlier_distance_histogram(point_cloud, result, bin_count=4)

        self.assertIsNone(histogram)

    def test_inlier_distance_histogram_is_unavailable_without_surface_distance(self):
        point_cloud = types.SimpleNamespace(points=[[0.0, 0.0, 0.0]], count=1)
        result = types.SimpleNamespace(type="Plane", inlier_indices=[0], parameters={})

        self.assertIsNone(viewport.build_inlier_distance_histogram(point_cloud, result))

    def test_surface_color_setter_rebuilds_preview_meshes_with_custom_color(self):
        view = self._make_view()
        result = types.SimpleNamespace(inlier_indices=[])
        view.surface_results = [result]
        calls = []
        original_builder = viewport.build_surface_preview_mesh
        viewport.build_surface_preview_mesh = lambda surface, solid_color=None: calls.append((surface, solid_color)) or None
        try:
            view.set_surface_color([0.3, 0.4, 0.5, 0.2])
        finally:
            viewport.build_surface_preview_mesh = original_builder

        self.assertEqual(calls, [(result, [0.3, 0.4, 0.5, 0.2])])

    def test_cone_distance_uses_axial_radial_surface_normal(self):
        result = types.SimpleNamespace(
            type="Cone",
            seed_position=[0.0, 0.0, 0.0],
            parameters={
                "bottom": [0.0, 0.0, 0.0],
                "top": [0.0, 0.0, 2.0],
                "bottom_radius": 1.0,
                "top_radius": 0.0,
            },
        )
        distance = viewport._surface_distance_function(result)

        self.assertAlmostEqual(distance([0.5, 0.0, 1.0]), 0.0)
        self.assertAlmostEqual(distance([0.0, 0.0, 1.0]), -0.5 / math.sqrt(1.25))
        self.assertAlmostEqual(distance([1.0, 0.0, 1.0]), 0.5 / math.sqrt(1.25))

    def test_torus_distance_uses_nearest_cross_section_circle(self):
        result = types.SimpleNamespace(
            type="Torus",
            seed_position=[0.0, 0.0, 0.0],
            parameters={
                "center": [0.0, 0.0, 0.0],
                "axis": [0.0, 0.0, 1.0],
                "major_radius": 2.0,
                "tube_radius": 0.5,
            },
        )
        distance = viewport._surface_distance_function(result)

        self.assertAlmostEqual(distance([2.5, 0.0, 0.0]), 0.0)
        self.assertAlmostEqual(distance([0.0, 0.0, 0.0]), 1.5)
        self.assertAlmostEqual(distance([2.0, 0.0, 0.0]), -0.5)


if __name__ == "__main__":
    unittest.main()
