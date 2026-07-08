import ctypes
import importlib.util
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NATIVE_PICKING = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
    / "native_picking.py"
)


def load_native_picking():
    spec = importlib.util.spec_from_file_location("findsurface_omniverse_native_picking_under_test", NATIVE_PICKING)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native_picking = load_native_picking()


class NativePickingTests(unittest.TestCase):
    def test_default_build_command_targets_current_platform_library(self):
        command = native_picking.default_build_command("c++")
        output = str(native_picking.default_library_path())

        self.assertEqual(command[0], "c++")
        self.assertIn("-shared", command)
        self.assertIn("-o", command)
        self.assertIn(output, command)
        self.assertIn(str(native_picking.default_source_path()), command)
        if output.endswith(".so"):
            self.assertIn("-fPIC", command)
        if output.endswith(".dll"):
            self.assertIn("-static-libgcc", command)
            self.assertIn("-static-libstdc++", command)

    def test_native_point_picker_builds_missing_default_library_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            library_path = Path(tmp) / Path(native_picking.default_library_path()).name
            fake_lib = types.SimpleNamespace(
                fs_pick_point_orthographic=types.SimpleNamespace(),
                fs_pick_point_perspective=types.SimpleNamespace(),
            )

            def build_library():
                library_path.write_bytes(b"placeholder")
                return library_path

            with mock.patch.object(native_picking, "default_library_path", return_value=library_path), mock.patch.object(
                native_picking, "build_default_library", side_effect=build_library
            ) as build, mock.patch.object(native_picking.ctypes, "CDLL", return_value=fake_lib):
                native_picking.NativePointPicker()

            build.assert_called_once_with()

    def test_orthographic_pick_falls_back_to_nearest_native_point(self):
        if not native_picking.default_library_path().exists():
            self.skipTest("Native picking library is not built")
        picker = native_picking.NativePointPicker()
        points = (ctypes.c_float * 6)(
            0.0,
            0.0,
            0.0,
            10.0,
            0.0,
            0.0,
        )
        active_mask = (ctypes.c_uint8 * 2)(1, 1)
        camera = types.SimpleNamespace(
            position=(0.0, 0.0, 10.0),
            center=(0.0, 0.0, 0.0),
            right=(1.0, 0.0, 0.0),
            up=(0.0, 1.0, 0.0),
            forward=(0.0, 0.0, -1.0),
            zoom=1.0,
            diameter=10.0,
        )

        without_fallback = picker.pick_orthographic(
            points,
            active_mask,
            2,
            camera,
            (100.0, 100.0),
            (75.0, 50.0),
            1.0,
            fallback_to_nearest=False,
        )
        with_fallback = picker.pick_orthographic(
            points,
            active_mask,
            2,
            camera,
            (100.0, 100.0),
            (75.0, 50.0),
            1.0,
            fallback_to_nearest=True,
        )

        self.assertIsNone(without_fallback)
        self.assertEqual(with_fallback, 0)


if __name__ == "__main__":
    unittest.main()
