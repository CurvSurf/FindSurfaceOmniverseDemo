import importlib.util
import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SURFACE_PREVIEW_PATH = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
    / "surface_preview.py"
)

spec = importlib.util.spec_from_file_location("findsurface_omniverse_surface_preview_test", SURFACE_PREVIEW_PATH)
surface_preview = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = surface_preview
spec.loader.exec_module(surface_preview)


class SurfacePreviewTests(unittest.TestCase):
    def test_demo_surfaces_build_solid_and_wire_meshes(self):
        for result in surface_preview.demo_surface_results():
            with self.subTest(result=result.type):
                mesh = surface_preview.build_surface_preview_mesh(result)
                self.assertIsNotNone(mesh)
                self.assertGreater(len(mesh.points), 0)
                self.assertGreater(len(mesh.vertex_counts), 0)
                self.assertGreater(len(mesh.vertex_indices), 0)
                self.assertGreater(len(mesh.wire_lines), 0)
                self.assertEqual(len(mesh.colors), len(mesh.vertex_indices))
                self.assertTrue(all(len(color) == 4 for color in mesh.colors))

    def test_surface_fill_is_subtle_and_transparent(self):
        result = surface_preview.demo_surface_results()[0]

        mesh = surface_preview.build_surface_preview_mesh(result)

        self.assertIsNotNone(mesh)
        self.assertTrue(all(color[3] <= 0.06 for color in mesh.colors))

    def test_torus_uses_ten_degree_sweep_steps_plus_remainder(self):
        torus = next(result for result in surface_preview.demo_surface_results() if result.type == "Torus")
        torus.parameters["sweep_angle"] = math.radians(95.0)

        mesh = surface_preview.build_surface_preview_mesh(torus)

        self.assertIsNotNone(mesh)
        self.assertEqual(len(mesh.points), 11 * 18)

    def test_plane_uses_native_origin_frame_for_position(self):
        plane = next(result for result in surface_preview.demo_surface_results() if result.type == "Plane")
        plane.parameters = {
            "origin": (10.0, 20.0, 30.0),
            "x_axis": (0.0, 1.0, 0.0),
            "y_axis": (0.0, 0.0, 1.0),
            "z_axis": (1.0, 0.0, 0.0),
            "width": 4.0,
            "height": 2.0,
        }

        mesh = surface_preview.build_surface_preview_mesh(plane)

        self.assertIsNotNone(mesh)
        xs = {round(point[0], 6) for point in mesh.points}
        ys = sorted({round(point[1], 6) for point in mesh.points})
        zs = sorted({round(point[2], 6) for point in mesh.points})
        self.assertEqual(xs, {10.0})
        self.assertEqual(ys[0], 18.0)
        self.assertEqual(ys[-1], 22.0)
        self.assertEqual(zs[0], 29.0)
        self.assertEqual(zs[-1], 31.0)

    def test_plane_uses_native_corner_names_for_position(self):
        plane = next(result for result in surface_preview.demo_surface_results() if result.type == "Plane")
        plane.parameters = {
            "lower_left": (8.0, 19.0, 30.0),
            "lower_right": (12.0, 19.0, 30.0),
            "upper_right": (12.0, 21.0, 30.0),
            "upper_left": (8.0, 21.0, 30.0),
        }

        mesh = surface_preview.build_surface_preview_mesh(plane)

        self.assertIsNotNone(mesh)
        xs = sorted({round(point[0], 6) for point in mesh.points})
        ys = sorted({round(point[1], 6) for point in mesh.points})
        zs = {round(point[2], 6) for point in mesh.points}
        self.assertEqual(xs[0], 8.0)
        self.assertEqual(xs[-1], 12.0)
        self.assertEqual(ys[0], 19.0)
        self.assertEqual(ys[-1], 21.0)
        self.assertEqual(zs, {30.0})


if __name__ == "__main__":
    unittest.main()
