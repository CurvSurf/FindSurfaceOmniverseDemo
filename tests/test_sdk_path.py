"""App-owned explicit SDK path must not change bootstrap's global defaults."""
import os
import unittest
from unittest import mock

from test_capture_flow import extension, make_extension


class SdkPathTests(unittest.TestCase):
    def test_explicit_process_path_is_passed_to_native_provider(self):
        ext = make_extension()
        with mock.patch.dict(os.environ, {"FINDSURFACE_APP_SDK_PATH": "private/FindSurface.dll"}), \
                mock.patch("findsurface.bootstrap.findsurface_sdk.wrapper.FindSurfaceSdk") as sdk, \
                mock.patch("findsurface.bootstrap.native.NativeFindSurfaceProvider") as native, \
                mock.patch.object(extension, "FindSurfaceDetector") as detector:
            self.assertIs(ext._create_provider(), detector.return_value)
            sdk.assert_called_once_with(library_path="private/FindSurface.dll")
            native.assert_called_once_with(sdk=sdk.return_value)
            detector.assert_called_once_with(provider=native.return_value)

    def test_legacy_startup_keeps_default_provider(self):
        ext = make_extension()
        with mock.patch.dict(os.environ), mock.patch.object(extension, "FindSurfaceDetector") as detector:
            os.environ.pop("FINDSURFACE_APP_SDK_PATH", None)
            self.assertIs(ext._create_provider(), detector.return_value)
            detector.assert_called_once_with()
