import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.curvsurf.findsurface_omniverse"
EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.findsurface.bootstrap"
APP_ROOT = (
    APP_EXTENSION_ROOT
    / "findsurface_omniverse"
)
PRESET_WORKSPACE_DIR = APP_EXTENSION_ROOT / "data" / "presets" / "workspaces"


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

app_state = load_app_module("findsurface_omniverse.app_state", "app_state.py")
point_cloud = load_app_module("findsurface_omniverse.point_cloud", "point_cloud.py")
surface_preview = load_app_module("findsurface_omniverse.surface_preview", "surface_preview.py")
from findsurface.bootstrap import usd_schema  # noqa: E402

workspace = load_app_module("findsurface_omniverse.workspace", "workspace.py")


class WorkspaceTests(unittest.TestCase):
    def _cloud(self):
        return point_cloud.PointCloudData(
            "fixture.xyz",
            [
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (2.0, 0.0, 0.0),
                (3.0, 0.0, 0.0),
            ],
        )

    def _surface_result(self):
        return surface_preview.SurfaceResult(
            id="Plane_1",
            type="Plane",
            seed_position=(1.0, 0.0, 0.0),
            seed_index=1,
            inlier_indices=[1, 2],
            active_generation=0,
            measurement_accuracy=0.01,
            rms_error=0.001,
            parameters={"origin": (1.5, 0.0, 0.0)},
        )

    def test_workspace_preserves_cancel_transaction_history(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())
        state.remove_result("Plane_1", restore_inliers=True)

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "workspace.usda")
            workspace.write_workspace(path, state)
            loaded = workspace.read_workspace(path).state

        self.assertEqual(loaded.results, [])
        self.assertEqual(loaded.active_count, loaded.point_count)
        self.assertEqual(len(loaded.transaction_log), 2)

        undone_cancel = loaded.undo_last()

        self.assertEqual(undone_cancel.id, "Plane_1")
        self.assertEqual([result.id for result in loaded.results], ["Plane_1"])
        self.assertFalse(loaded.active_mask[1])
        self.assertFalse(loaded.active_mask[2])
        self.assertEqual(loaded.generation, 1)

        undone_apply = loaded.undo_last()

        self.assertEqual(undone_apply.id, "Plane_1")
        self.assertEqual(loaded.results, [])
        self.assertEqual(loaded.active_count, loaded.point_count)
        self.assertEqual(loaded.generation, 0)

    def test_preset_workspace_loads_as_workspace_document(self):
        preset_path = PRESET_WORKSPACE_DIR / "tango.usda"
        if not preset_path.is_file():
            preset_path = sorted(PRESET_WORKSPACE_DIR.glob("*.usda"))[0]

        document = workspace.read_workspace(str(preset_path))

        self.assertEqual(document.detection_type, "Auto")
        self.assertGreater(document.point_cloud.count, 0)
        self.assertGreaterEqual(document.state.active_count, 0)

    def test_workspace_preserves_transaction_index_for_redo(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())
        state.undo_last()

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "workspace.usda")
            workspace.write_workspace(path, state)
            loaded = workspace.read_workspace(path).state

        self.assertEqual(loaded.transaction_index, 0)
        self.assertTrue(loaded.can_redo)
        self.assertEqual(loaded.results, [])

        loaded.redo_last()

        self.assertEqual([result.id for result in loaded.results], ["Plane_1"])

    def test_workspace_preserves_state_change_transaction_payload(self):
        state = app_state.PointCloudState(self._cloud())
        state.record_state_change(
            app_state.TRANSACTION_GLOBAL_VISIBILITY,
            {"outlier_points_visible": True},
            {"outlier_points_visible": False},
        )

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "workspace.usda")
            workspace.write_workspace(path, state)
            loaded = workspace.read_workspace(path).state

        self.assertEqual(len(loaded.transaction_log), 1)
        transaction = loaded.transaction_log[0]
        self.assertEqual(transaction.event_type, app_state.TRANSACTION_GLOBAL_VISIBILITY)
        self.assertEqual(transaction.state_before, {"outlier_points_visible": True})
        self.assertEqual(transaction.state_after, {"outlier_points_visible": False})
        self.assertEqual(transaction.generation_before, 0)
        self.assertEqual(transaction.generation_after, 0)

    def test_geometry_export_writes_usd_prims_with_payload(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "geometry_export.usda")
            workspace.write_geometry_export(path, state, include_visualization_meshes=True)
            payload = workspace._read_payload(path)
            text = Path(path).read_text(encoding="utf-8")

        self.assertEqual(payload["kind"], workspace.USD_KIND_GEOMETRY_EXPORT)
        self.assertIn('def Xform "FindSurfaceExport"', text)
        self.assertIn('prepend apiSchemas = ["FindSurfaceGeometryExportAPI"]', text)
        self.assertIn('kind = "geometry_export"', text)
        self.assertIn('def Xform "Plane_1"', text)
        self.assertIn('prepend apiSchemas = ["FindSurfaceDetectionResultAPI"]', text)
        self.assertIn('custom string findsurface:geometry_type = "Plane"', text)
        self.assertIn('custom double findsurface:rms_error = 0.001', text)
        self.assertIn('custom double findsurface:measurement_accuracy = 0.01', text)
        self.assertIn('custom int findsurface:seed_index = 1', text)
        self.assertIn('custom double3 findsurface:seed_position = (1, 0, 0)', text)
        self.assertIn("custom int[] findsurface:inlier_indices = [1, 2]", text)
        self.assertIn('custom double3 findsurface:param:origin = (1.5, 0, 0)', text)
        self.assertIn('def Points "Inliers"', text)
        self.assertIn('prepend apiSchemas = ["FindSurfaceInlierPointsAPI"]', text)
        self.assertIn("int64[] ids = [1, 2]", text)
        self.assertIn("point3f[] points = [(1, 0, 0), (2, 0, 0)]", text)
        self.assertIn('def Scope "Looks"', text)
        self.assertIn('def Material "TransparentSolid"', text)
        self.assertIn('def Material "Wire"', text)
        self.assertIn('uniform token info:id = "UsdPreviewSurface"', text)
        self.assertIn('def Mesh "VisualizationMesh"', text)
        self.assertIn('prepend apiSchemas = ["FindSurfaceVisualizationAPI"]', text)
        self.assertIn('rel material:binding = </FindSurfaceExport/Looks/TransparentSolid>', text)
        self.assertIn("uniform bool doubleSided = true", text)
        self.assertIn("float[] primvars:displayOpacity = [0.18]", text)
        self.assertIn('def BasisCurves "VisualizationWire"', text)
        self.assertIn('rel material:binding = </FindSurfaceExport/Looks/Wire>', text)
        self.assertIn("float[] widths = [0.00625]", text)
        self.assertIn('color3f[] primvars:displayColor = [(0.15, 1, 0.65)]', text)
        self.assertGreaterEqual(text.count('prepend apiSchemas = ["FindSurfaceVisualizationAPI"]'), 2)

    def test_workspace_load_rejects_geometry_export_prims(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "geometry_export.usda")
            workspace.write_geometry_export(path, state)

            with self.assertRaises(workspace.WorkspaceError):
                workspace.read_workspace(path)

    def test_geometry_export_schema_writer_can_append_schema_lines_without_replacing_fallback(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())

        def writer(payload):
            self.assertEqual(payload["kind"], workspace.USD_KIND_GEOMETRY_EXPORT)
            return [
                'def Scope "FindSurfaceSchema"',
                "{",
                '    custom string note = "schema hook"',
                "}",
            ]

        previous = workspace.set_geometry_export_schema_writer(writer)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "geometry_export.usda")
                workspace.write_geometry_export(path, state)
                text = Path(path).read_text(encoding="utf-8")
        finally:
            workspace.set_geometry_export_schema_writer(previous)

        self.assertIn('def Xform "FindSurfaceExport"', text)
        self.assertIn('def Points "Inliers"', text)
        self.assertIn('def Scope "FindSurfaceSchema"', text)
        self.assertIn('custom string note = "schema hook"', text)

    def test_geometry_export_schema_writer_rejects_non_string_lines(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())
        previous = workspace.set_geometry_export_schema_writer(lambda payload: [object()])
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "geometry_export.usda")
                with self.assertRaises(workspace.WorkspaceError):
                    workspace.write_geometry_export(path, state)
        finally:
            workspace.set_geometry_export_schema_writer(previous)

    def test_geometry_export_discovers_schema_writer_from_environment(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())
        module = types.ModuleType("fake_findsurface_schema")
        module.write_lines = lambda payload: ['def Scope "AutoDiscoveredSchema"', "{", "}"]
        sys.modules[module.__name__] = module
        previous_writer = workspace.set_geometry_export_schema_writer(None)
        previous_env = os.environ.get(workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV)
        os.environ[workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV] = f"{module.__name__}:write_lines"
        workspace.reset_geometry_export_schema_writer_discovery()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "geometry_export.usda")
                workspace.write_geometry_export(path, state)
                text = Path(path).read_text(encoding="utf-8")
        finally:
            if previous_env is None:
                os.environ.pop(workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV, None)
            else:
                os.environ[workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV] = previous_env
            workspace.set_geometry_export_schema_writer(previous_writer)
            workspace.reset_geometry_export_schema_writer_discovery()
            sys.modules.pop(module.__name__, None)

        self.assertIn('def Scope "AutoDiscoveredSchema"', text)
        self.assertIn('def Points "Inliers"', text)

    def test_geometry_export_reports_configured_schema_writer_without_callable(self):
        state = app_state.PointCloudState(self._cloud())
        state.apply_result(self._surface_result())
        module = types.ModuleType("fake_empty_findsurface_schema")
        sys.modules[module.__name__] = module
        previous_writer = workspace.set_geometry_export_schema_writer(None)
        previous_env = os.environ.get(workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV)
        os.environ[workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV] = module.__name__
        workspace.reset_geometry_export_schema_writer_discovery()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / "geometry_export.usda")
                with self.assertRaises(workspace.WorkspaceError):
                    workspace.write_geometry_export(path, state)
        finally:
            if previous_env is None:
                os.environ.pop(workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV, None)
            else:
                os.environ[workspace.GEOMETRY_EXPORT_SCHEMA_WRITER_ENV] = previous_env
            workspace.set_geometry_export_schema_writer(previous_writer)
            workspace.reset_geometry_export_schema_writer_discovery()
            sys.modules.pop(module.__name__, None)


if __name__ == "__main__":
    unittest.main()
