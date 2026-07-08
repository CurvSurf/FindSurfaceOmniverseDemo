import unittest
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGE_ROOT = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
)
APP_TEST_AND_TOOL_ROOTS = (PROJECT_ROOT / "tests", PROJECT_ROOT / "tools")
MAIN_APP_NAME = "com.curvsurf.findsurface_omniverse_demo.kit"
VENDORED_TOOL_ROOTS = (
    PROJECT_ROOT / "tools" / "ci",
    PROJECT_ROOT / "tools" / "packman",
    PROJECT_ROOT / "tools" / "repoman",
)


class RepositoryOwnershipTests(unittest.TestCase):
    def test_repo_launch_defaults_to_main_demo_app(self):
        with open(PROJECT_ROOT / "repo.toml", "rb") as stream:
            repo_config = tomllib.load(stream)

        default_app = repo_config["repo_launch"]["default_app"]

        self.assertEqual(default_app, MAIN_APP_NAME)
        self.assertTrue((PROJECT_ROOT / "source" / "apps" / default_app).is_file())

    def test_repo_wrappers_route_bare_launch_to_main_demo_app(self):
        for relative_path in ("repo.bat", "repo.sh"):
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(MAIN_APP_NAME, source)

    def test_preset_sample_assets_live_in_app_extension_data(self):
        preset_root = PROJECT_ROOT / "source" / "extensions" / "com.curvsurf.findsurface_omniverse" / "data" / "presets"

        self.assertTrue(any((preset_root / "pointclouds").glob("*.xyz")))
        self.assertTrue(any((preset_root / "workspaces").glob("*.usda")))


    def test_app_source_does_not_import_app_owned_modules_from_extension(self):
        forbidden_imports = (
            "findsurface.bootstrap.app_state",
            "findsurface.bootstrap.app_point_cloud",
            "findsurface.bootstrap.camera",
            "findsurface.bootstrap.detection",
            "findsurface.bootstrap.native_picking",
            "findsurface.bootstrap.picking",
            "findsurface.bootstrap.point_cloud",
            "findsurface.bootstrap.surface_preview",
            "findsurface.bootstrap.viewport",
            "findsurface.bootstrap.workspace",
        )
        violations = []
        for path in APP_PACKAGE_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for forbidden_import in forbidden_imports:
                if forbidden_import in source:
                    violations.append((path.relative_to(PROJECT_ROOT), forbidden_import))

        self.assertEqual(violations, [])

    def test_tests_and_tools_do_not_load_extension_private_modules_by_path(self):
        forbidden_patterns = (
            "BOOTSTRAP_ROOT",
            "spec_from_file_location(\"findsurface.bootstrap",
            "spec_from_file_location('findsurface.bootstrap",
            "load_module(\"findsurface.bootstrap",
            "load_module('findsurface.bootstrap",
            "findsurface_sdk/",
            "findsurface_sdk\\",
        )
        violations = []
        for root in APP_TEST_AND_TOOL_ROOTS:
            for path in root.rglob("*"):
                if path == Path(__file__):
                    continue
                if any(path.is_relative_to(vendor_root) for vendor_root in VENDORED_TOOL_ROOTS):
                    continue
                if path.suffix not in {".py", ".ps1", ".sh"}:
                    continue
                source = path.read_text(encoding="utf-8")
                for forbidden_pattern in forbidden_patterns:
                    if forbidden_pattern in source:
                        violations.append((path.relative_to(PROJECT_ROOT), forbidden_pattern))

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
