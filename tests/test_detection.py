import importlib.util
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.findsurface.bootstrap"
APP_ROOT = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
)


def load_app_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_pkg = types.ModuleType("findsurface_omniverse")
app_pkg.__path__ = [str(APP_ROOT)]
sys.path.insert(0, str(EXTENSION_ROOT))
sys.modules.setdefault("findsurface_omniverse", app_pkg)

camera_module = load_app_module("findsurface_omniverse.camera", "camera.py")
surface_preview = load_app_module("findsurface_omniverse.surface_preview", "surface_preview.py")
from findsurface.bootstrap import native  # noqa: E402

app_state = load_app_module("findsurface_omniverse.app_state", "app_state.py")
picking = load_app_module("findsurface_omniverse.picking", "picking.py")
detection = types.SimpleNamespace(
    SurfaceResult=surface_preview.SurfaceResult,
    NativeFindSurfaceProvider=native.NativeFindSurfaceProvider,
    DetectionOptions=native.DetectionOptions,
    FindSurfaceSdkError=native.FindSurfaceSdkError,
    SMART_CONVERSION_PARAMETERS=native.SMART_CONVERSION_PARAMETERS,
    FsIntParameter=native.FsIntParameter,
    NAME_TO_FEATURE_TYPE=native.NAME_TO_FEATURE_TYPE,
)


class DetectionTests(unittest.TestCase):
    def _state_with_points(self, count=5):
        points = [(float(index), 0.0, 0.0) for index in range(count)]
        return app_state.PointCloudState(types.SimpleNamespace(count=count, points=points))

    def _surface_result(self, result_id, inlier_indices):
        return detection.SurfaceResult(
            id=result_id,
            type="Plane",
            seed_position=(0.0, 0.0, 0.0),
            seed_index=inlier_indices[0],
            inlier_indices=list(inlier_indices),
            active_generation=0,
            measurement_accuracy=0.01,
            rms_error=0.001,
            parameters={"origin": (0.0, 0.0, 0.0)},
        )

    def test_delete_geometry_is_undoable_without_restoring_inliers(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1, 2]))

        deleted = state.remove_result("Plane_1", restore_inliers=False)

        self.assertEqual(deleted.id, "Plane_1")
        self.assertEqual(state.results, [])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])

        undone = state.undo_last()

        self.assertEqual(undone.id, "Plane_1")
        self.assertEqual([result.id for result in state.results], ["Plane_1"])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])
        self.assertEqual(state.generation, 1)

    def test_cancel_geometry_is_undoable_and_re_removes_inliers(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1, 2]))
        state.apply_result(self._surface_result("Plane_2", [3]))

        canceled = state.remove_result("Plane_1", restore_inliers=True)

        self.assertEqual(canceled.id, "Plane_1")
        self.assertEqual([result.id for result in state.results], ["Plane_2"])
        self.assertTrue(state.active_mask[1])
        self.assertTrue(state.active_mask[2])

        undone = state.undo_last()

        self.assertEqual(undone.id, "Plane_1")
        self.assertEqual([result.id for result in state.results], ["Plane_1", "Plane_2"])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])
        self.assertFalse(state.active_mask[3])
        self.assertEqual(state.generation, 2)

    def test_reset_detection_is_undoable(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1, 2]))

        state.reset()

        self.assertEqual(state.results, [])
        self.assertEqual(state.active_count, state.point_count)

        undone = state.undo_last()

        self.assertEqual(undone.id, "Plane_1")
        self.assertEqual([result.id for result in state.results], ["Plane_1"])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])
        self.assertEqual(state.generation, 1)

    def test_redo_restores_undone_transaction(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1, 2]))

        state.undo_last()
        redone = state.redo_last()

        self.assertEqual(redone.id, "Plane_1")
        self.assertEqual([result.id for result in state.results], ["Plane_1"])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])
        self.assertFalse(state.can_redo)

    def test_new_transaction_after_undo_discards_redo_tail(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1]))
        state.apply_result(self._surface_result("Plane_2", [2]))

        state.undo_last()
        state.apply_result(self._surface_result("Plane_3", [3]))

        self.assertEqual([result.id for result in state.results], ["Plane_1", "Plane_3"])
        self.assertEqual([transaction.result_id for transaction in state.transaction_log], ["Plane_1", "Plane_3"])
        self.assertFalse(state.can_redo)

    def test_can_jump_to_transaction_index(self):
        state = self._state_with_points()
        state.apply_result(self._surface_result("Plane_1", [1]))
        state.apply_result(self._surface_result("Plane_2", [2]))

        self.assertTrue(state.go_to_transaction_index(0))
        self.assertEqual(state.results, [])
        self.assertEqual(state.active_count, state.point_count)

        self.assertTrue(state.go_to_transaction_index(2))
        self.assertEqual([result.id for result in state.results], ["Plane_1", "Plane_2"])
        self.assertFalse(state.active_mask[1])
        self.assertFalse(state.active_mask[2])

    def test_provider_reuses_prepared_pointcloud_for_same_generation(self):
        class Sdk:
            def __init__(self):
                self.build_calls = 0
                self.set_buffer_calls = 0
                self.seed_indices = []

            def create_context(self):
                return object()

            def release_context(self, context):
                pass

            def set_float(self, *args):
                pass

            def set_int(self, context, parameter, value):
                if parameter == detection.FsIntParameter.SEED_INDEX:
                    self.seed_indices.append(value)

            def set_boolean(self, *args):
                pass

            def build_pointcloud_buffer(self, points):
                self.build_calls += 1
                return object(), len(points)

            def set_pointcloud_buffer(self, context, point_array, point_count):
                self.set_buffer_calls += 1
                return point_array

            def find(self, context, feature_type):
                plane = types.SimpleNamespace(
                    lower_left=(-1.0, -1.0, 0.0),
                    lower_right=(1.0, -1.0, 0.0),
                    upper_right=(1.0, 1.0, 0.0),
                    upper_left=(-1.0, 1.0, 0.0),
                )
                return types.SimpleNamespace(
                    result_type=int(detection.NAME_TO_FEATURE_TYPE["Plane"]),
                    rms_error=0.01,
                    plane_result=plane,
                )

            def get_outlier_flags(self, context, point_count):
                return [0] * point_count

        sdk = Sdk()
        provider = detection.NativeFindSurfaceProvider(sdk)
        points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
        active_mask = [True, False, True]
        options = detection.DetectionOptions(detection_type="Plane")

        provider.detect(points, active_mask, 0, options, active_generation=0)
        provider.detect(points, active_mask, 2, options, active_generation=0)

        self.assertEqual(sdk.build_calls, 1)
        self.assertEqual(sdk.set_buffer_calls, 2)
        self.assertEqual(sdk.seed_indices, [0, 1])

    def test_provider_rebuilds_prepared_pointcloud_when_generation_changes(self):
        class Sdk:
            def __init__(self):
                self.build_calls = 0
                self.seed_indices = []

            def create_context(self):
                return object()

            def release_context(self, context):
                pass

            def set_float(self, *args):
                pass

            def set_int(self, context, parameter, value):
                if parameter == detection.FsIntParameter.SEED_INDEX:
                    self.seed_indices.append(value)

            def set_boolean(self, *args):
                pass

            def build_pointcloud_buffer(self, points):
                self.build_calls += 1
                return object(), len(points)

            def set_pointcloud_buffer(self, context, point_array, point_count):
                return point_array

            def find(self, context, feature_type):
                plane = types.SimpleNamespace(
                    lower_left=(-1.0, -1.0, 0.0),
                    lower_right=(1.0, -1.0, 0.0),
                    upper_right=(1.0, 1.0, 0.0),
                    upper_left=(-1.0, 1.0, 0.0),
                )
                return types.SimpleNamespace(
                    result_type=int(detection.NAME_TO_FEATURE_TYPE["Plane"]),
                    rms_error=0.01,
                    plane_result=plane,
                )

            def get_outlier_flags(self, context, point_count):
                return [0] * point_count

        sdk = Sdk()
        provider = detection.NativeFindSurfaceProvider(sdk)
        points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
        active_mask = [True, False, True]
        options = detection.DetectionOptions(detection_type="Plane")

        provider.detect(points, active_mask, 2, options, active_generation=0)
        active_mask[0] = False
        provider.detect(points, active_mask, 2, options, active_generation=1)

        self.assertEqual(sdk.build_calls, 2)
        self.assertEqual(sdk.seed_indices, [1, 0])

    def test_provider_does_not_request_outlier_flags_for_invalid_result(self):
        class Sdk:
            def __init__(self):
                self.calls = []

            def create_context(self):
                self.calls.append("create")
                return object()

            def release_context(self, context):
                self.calls.append("release")

            def set_float(self, *args):
                pass

            def set_int(self, *args):
                pass

            def set_boolean(self, *args):
                pass

            def set_pointcloud(self, context, points):
                self.calls.append("set_pointcloud")
                return object()

            def find(self, context, feature_type):
                self.calls.append("find")
                return types.SimpleNamespace(result_type=0, rms_error=0.0)

            def get_outlier_flags(self, context, point_count):
                self.calls.append("flags")
                return [0] * point_count

        sdk = Sdk()
        provider = detection.NativeFindSurfaceProvider(sdk)
        options = detection.DetectionOptions(detection_type="Plane")

        with self.assertRaises(detection.FindSurfaceSdkError):
            provider.detect([[0.0, 0.0, 0.0]], [True], 0, options)

        self.assertNotIn("flags", sdk.calls)
        self.assertIn("release", sdk.calls)

    def test_provider_enables_all_smart_conversion_options(self):
        class Sdk:
            def __init__(self):
                self.boolean_calls = []

            def set_float(self, *args):
                pass

            def set_int(self, *args):
                pass

            def set_boolean(self, context, parameter, value):
                self.boolean_calls.append((parameter, value))

        sdk = Sdk()
        provider = detection.NativeFindSurfaceProvider(sdk)

        provider._apply_options(object(), detection.DetectionOptions(), 0)

        self.assertEqual(
            sdk.boolean_calls,
            [(parameter, True) for parameter in detection.SMART_CONVERSION_PARAMETERS],
        )

    def test_orthographic_pick_prefers_nearest_screen_point(self):
        camera = camera_module.OrbitCamera()
        camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        points = [[0.0, 0.0, 0.0], [0.7, 0.7, 0.0]]

        picked = picking.pick_point_orthographic(
            points,
            [True, True],
            camera,
            (1000.0, 1000.0),
            (500.0, 500.0),
            20.0,
        )

        self.assertEqual(picked, 0)

    def test_orthographic_pick_ignores_inactive_points(self):
        camera = camera_module.OrbitCamera()
        camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])

        picked = picking.pick_point_orthographic(
            [[0.0, 0.0, 0.0], [0.02, 0.0, 0.0]],
            [False, True],
            camera,
            (1000.0, 1000.0),
            (500.0, 500.0),
            20.0,
        )

        self.assertEqual(picked, 1)

    def test_orthographic_pick_prefers_frontmost_point_in_probe_cylinder(self):
        camera = camera_module.OrbitCamera()
        camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        camera.set_direction_up([0.0, 0.0, -1.0], [0.0, 1.0, 0.0])

        picked = picking.pick_point_orthographic(
            [[0.0, 0.0, -0.8], [0.0, 0.0, 0.8]],
            [True, True],
            camera,
            (1000.0, 1000.0),
            (500.0, 500.0),
            20.0,
        )

        self.assertEqual(picked, 1)

    def test_orthographic_pick_ignores_points_behind_camera_ray(self):
        camera = camera_module.OrbitCamera()
        camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        camera.set_direction_up([0.0, 0.0, -1.0], [0.0, 1.0, 0.0])
        camera.center = [0.0, 0.0, 10.0]

        picked = picking.pick_point_orthographic(
            [[0.0, 0.0, 20.0], [0.0, 0.0, 9.0]],
            [True, True],
            camera,
            (1000.0, 1000.0),
            (500.0, 500.0),
            20.0,
        )

        self.assertEqual(picked, 1)

    def test_perspective_pick_uses_screen_space_probe(self):
        camera = camera_module.OrbitCamera()
        camera.fit([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0])
        camera.set_projection_mode(camera_module.PROJECTION_PERSPECTIVE)
        points = [[0.0, 0.0, 0.0], [0.9, 0.9, 0.0]]

        picked = picking.pick_point_perspective(
            points,
            [True, True],
            camera,
            (1000.0, 1000.0),
            (500.0, 500.0),
            20.0,
        )

        self.assertEqual(picked, 0)


if __name__ == "__main__":
    unittest.main()
