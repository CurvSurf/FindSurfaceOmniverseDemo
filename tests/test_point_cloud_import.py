import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_EXTENSION_ROOT = PROJECT_ROOT / "source" / "extensions" / "com.curvsurf.findsurface_omniverse"
POINT_CLOUD_PATH = (
    APP_EXTENSION_ROOT
    / "findsurface_omniverse"
    / "point_cloud.py"
)
OVERSIZED_USD_PATH = PROJECT_ROOT / "tests" / "fixtures" / "oversized_200001_points.usd"
PRESET_POINTCLOUD_DIR = APP_EXTENSION_ROOT / "data" / "presets" / "pointclouds"

spec = importlib.util.spec_from_file_location("findsurface_omniverse_point_cloud_import_test", POINT_CLOUD_PATH)
point_cloud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = point_cloud
spec.loader.exec_module(point_cloud)


class PointCloudImportTests(unittest.TestCase):
    def _write_usda(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".usda", delete=False, encoding="utf-8") as stream:
            stream.write(text)
            return stream.name

    def test_plain_xyz_import_records_metadata_without_sampling(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            stream.write("# comment\n")
            stream.write("1 2 3\n")
            stream.write("4,5,6\n")

        cloud = point_cloud.load_point_cloud(path)

        self.assertEqual(cloud.points, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        self.assertEqual(cloud.metadata["source_point_count"], 2)
        self.assertEqual(cloud.metadata["imported_point_count"], 2)
        self.assertEqual(cloud.metadata["sampling_policy"], "none")
        self.assertEqual(cloud.metadata["source_format"], "xyz")

    def test_preset_xyz_imports_as_point_cloud(self):
        preset_path = PRESET_POINTCLOUD_DIR / "tango.xyz"
        if not preset_path.is_file():
            preset_path = sorted(PRESET_POINTCLOUD_DIR.glob("*.xyz"))[0]

        cloud = point_cloud.load_point_cloud(str(preset_path))

        self.assertGreater(cloud.count, 0)
        self.assertEqual(cloud.metadata["source_format"], "xyz")

    def test_sampling_applies_only_when_max_points_is_exceeded(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(10):
                stream.write(f"{index} 0 0\n")

        options = point_cloud.ImportOptions(
            max_points=5,
            target_points=3,
            overflow_policy="sample",
            sample_seed=7,
        )
        first = point_cloud.load_point_cloud(path, options)
        second = point_cloud.load_point_cloud(path, options)

        self.assertEqual(first.count, 3)
        self.assertEqual(first.points, second.points)
        self.assertEqual(first.metadata["source_point_count"], 10)
        self.assertEqual(first.metadata["imported_point_count"], 3)
        self.assertEqual(first.metadata["sampling_policy"], "reservoir")
        self.assertEqual(first.metadata["sample_seed"], 7)
        self.assertIsNone(first.metadata["sampled_source_indices"])
        self.assertFalse(first.metadata["sampled_source_indices_retained"])
        self.assertEqual(first.metadata["sampled_source_indices_omitted_reason"], "disabled")

    def test_sampling_can_retain_source_index_mapping_when_requested(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(10):
                stream.write(f"{index} 0 0\n")

        options = point_cloud.ImportOptions(
            max_points=5,
            target_points=3,
            overflow_policy="sample",
            sample_seed=7,
            retain_sampled_source_indices=True,
        )
        cloud = point_cloud.load_point_cloud(path, options)

        self.assertEqual(len(cloud.metadata["sampled_source_indices"]), 3)
        self.assertEqual(
            cloud.metadata["sampled_source_indices"],
            sorted(cloud.metadata["sampled_source_indices"]),
        )
        self.assertTrue(cloud.metadata["sampled_source_indices_retained"])
        self.assertIsNone(cloud.metadata["sampled_source_indices_omitted_reason"])

    def test_sampling_omits_source_index_mapping_above_memory_limit(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(10):
                stream.write(f"{index} 0 0\n")

        options = point_cloud.ImportOptions(
            max_points=5,
            target_points=3,
            overflow_policy="sample",
            retain_sampled_source_indices=True,
            max_source_index_mapping_points=2,
        )
        cloud = point_cloud.load_point_cloud(path, options)

        self.assertIsNone(cloud.metadata["sampled_source_indices"])
        self.assertFalse(cloud.metadata["sampled_source_indices_retained"])
        self.assertEqual(cloud.metadata["sampled_source_indices_omitted_reason"], "memory_limit")

    def test_import_progress_reports_counting_and_parsing_phases(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(3):
                stream.write(f"{index} 0 0\n")

        phases = []
        cloud = point_cloud.load_point_cloud(path, progress_callback=lambda progress: phases.append(progress.phase))

        self.assertEqual(cloud.count, 3)
        self.assertIn("counting", phases)
        self.assertIn("parsing", phases)
        self.assertIn("finalizing", phases)

    def test_import_cancel_token_stops_before_partial_cloud_is_returned(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(point_cloud.PROGRESS_INTERVAL_POINTS + 1):
                stream.write(f"{index} 0 0\n")

        token = point_cloud.ImportCancelToken()

        def on_progress(progress):
            if progress.phase == "parsing" and progress.current:
                token.cancel()

        with self.assertRaises(point_cloud.ImportCanceledError):
            point_cloud.load_point_cloud(
                path,
                point_cloud.ImportOptions(overflow_policy="sample"),
                progress_callback=on_progress,
                cancel_token=token,
            )

    def test_reject_policy_fails_when_max_points_is_exceeded(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(4):
                stream.write(f"{index} 0 0\n")

        options = point_cloud.ImportOptions(max_points=3, overflow_policy="reject")

        with self.assertRaises(point_cloud.PointCloudSizeError):
            point_cloud.load_point_cloud(path, options)

    def test_default_ask_policy_reports_exact_count_before_sampling(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xyz", delete=False) as stream:
            path = stream.name
            for index in range(6):
                stream.write(f"{index} 0 0\n")

        options = point_cloud.ImportOptions(max_points=5, target_points=3)

        with self.assertRaises(point_cloud.PointCloudSizeError) as raised:
            point_cloud.load_point_cloud(path, options)

        self.assertEqual(raised.exception.source_point_count, 6)
        self.assertEqual(raised.exception.max_points, 5)
        self.assertEqual(raised.exception.target_points, 3)

    def test_oversized_usd_fixture_reports_exact_count_before_sampling(self):
        with self.assertRaises(point_cloud.PointCloudSizeError) as raised:
            point_cloud.load_point_cloud(str(OVERSIZED_USD_PATH))

        self.assertEqual(raised.exception.source_point_count, 200_001)
        self.assertEqual(raised.exception.max_points, 200_000)

    def test_usda_import_reads_multiple_points_prims(self):
        path = self._write_usda(
            """#usda 1.0

def Xform "Root"
{
    def Points "SamplesA"
    {
        point3f[] points = [(1, 2, 3), (4, 5, 6)]
    }

    def Xform "Nested"
    {
        def Points "SamplesB"
        {
            point3f[] points = [
                (7, 8, 9)
            ]
        }
    }
}
"""
        )

        cloud = point_cloud.load_point_cloud(path)

        self.assertEqual(cloud.points, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
        self.assertEqual(cloud.metadata["source_point_count"], 3)
        self.assertEqual(cloud.metadata["source_format"], "usda")

    def test_usda_import_ignores_mesh_vertices_by_default(self):
        path = self._write_usda(
            """#usda 1.0

def Mesh "VisualizationMesh"
{
    point3f[] points = [(100, 100, 100), (200, 200, 200), (300, 300, 300)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0, 1, 2]
}

def Points "Samples"
{
    point3f[] points = [(1, 1, 1)]
}
"""
        )

        cloud = point_cloud.load_point_cloud(path)

        self.assertEqual(cloud.points, [[1.0, 1.0, 1.0]])
        self.assertEqual(cloud.metadata["source_point_count"], 1)

    def test_usda_import_can_include_mesh_vertices_with_explicit_option(self):
        path = self._write_usda(
            """#usda 1.0

def Mesh "VisualizationMesh"
{
    point3f[] points = [(100, 100, 100), (200, 200, 200), (300, 300, 300)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0, 1, 2]
}

def Points "Samples"
{
    point3f[] points = [(1, 1, 1)]
}
"""
        )

        cloud = point_cloud.load_point_cloud(path, point_cloud.ImportOptions(include_mesh_vertices=True))

        self.assertEqual(
            cloud.points,
            [[100.0, 100.0, 100.0], [200.0, 200.0, 200.0], [300.0, 300.0, 300.0], [1.0, 1.0, 1.0]],
        )
        self.assertEqual(cloud.metadata["source_point_count"], 4)

    def test_import_reads_points_from_findsurface_geometry_export_usda(self):
        path = self._write_usda(
            """#usda 1.0
# FIND_SURFACE_DATA_BEGIN
# {
#   "app_id": "com.curvsurf.findsurface_omniverse",
#   "kind": "geometry_export",
#   "schema_version": 1
# }
# FIND_SURFACE_DATA_END

def Xform "FindSurfaceExport" (
    kind = "geometry_export"
)
{
    def Xform "Plane_1"
    {
        def Mesh "VisualizationMesh"
        {
            point3f[] points = [(100, 100, 100), (200, 200, 200), (300, 300, 300)]
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
        }

        def Points "Inliers"
        {
            int64[] ids = [1, 2]
            point3f[] points = [(1, 0, 0), (2, 0, 0)]
        }
    }
}
"""
        )

        cloud = point_cloud.load_point_cloud(path)

        self.assertEqual(cloud.points, [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
        self.assertEqual(cloud.metadata["source_point_count"], 2)


if __name__ == "__main__":
    unittest.main()
