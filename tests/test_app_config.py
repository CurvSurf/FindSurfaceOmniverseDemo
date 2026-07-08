import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = (
    PROJECT_ROOT
    / "source"
    / "extensions"
    / "com.curvsurf.findsurface_omniverse"
    / "findsurface_omniverse"
)


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_config = load_module("findsurface_omniverse.app_config", "app_config.py")


class AppConfigTests(unittest.TestCase):
    def test_default_config_path_uses_app_extension_config_folder(self):
        path = Path(app_config.default_config_path())

        self.assertEqual(path.name, "app_defaults.json")
        self.assertEqual(path.parent.name, "config")
        self.assertEqual(path.parent.parent.name, "com.curvsurf.findsurface_omniverse")

    def test_missing_file_is_created_from_defaults(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_defaults.json"

            config, actual_path, created = app_config.load_app_config(str(path))

            self.assertTrue(created)
            self.assertEqual(Path(actual_path), path)
            self.assertTrue(path.exists())
            self.assertEqual(config["detection"]["range_parameters"]["seed_radius"]["value"], 0.15)

    def test_existing_file_is_merged_with_defaults(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "app_defaults.json"
            path.write_text(
                json.dumps(
                    {
                        "detection": {
                            "range_parameters": {"seed_radius": {"value": 0.25}},
                            "radial_expansion": 7,
                        }
                    }
                ),
                encoding="utf-8",
            )

            config, _actual_path, created = app_config.load_app_config(str(path))
            defaults = app_config.range_parameter_defaults(
                config,
                {
                    "seed_radius": ("Seed\nRadius", 0.15, 0.05, 0.50),
                },
            )

            self.assertFalse(created)
            self.assertEqual(defaults["seed_radius"], ("Seed\nRadius", 0.25, 0.05, 0.50))
            self.assertEqual(config["detection"]["radial_expansion"], 7)
            self.assertEqual(config["display"]["point_size"], 1.0)
            self.assertEqual(
                config["preset_file_directories"]["import_points"],
                "data/presets/pointclouds",
            )

    def test_slider_index_overrides_range_parameter_value(self):
        config = {
            "detection": {
                "range_parameters": {
                    "seed_radius": {
                        "value": 0.15,
                        "slider_index": 5,
                        "min": 0.05,
                        "max": 0.55,
                    }
                }
            }
        }

        defaults = app_config.range_parameter_defaults(
            config,
            {
                "seed_radius": ("Seed\nRadius", 0.15, 0.05, 0.50),
            },
        )

        self.assertEqual(defaults["seed_radius"], ("Seed\nRadius", 0.30, 0.05, 0.55))

    def test_null_slider_index_keeps_explicit_range_parameter_value(self):
        config = {
            "detection": {
                "range_parameters": {
                    "seed_radius": {
                        "value": 0.15,
                        "slider_index": None,
                        "min": 0.05,
                        "max": 0.55,
                    }
                }
            }
        }

        defaults = app_config.range_parameter_defaults(
            config,
            {
                "seed_radius": ("Seed\nRadius", 0.20, 0.05, 0.50),
            },
        )

        self.assertEqual(defaults["seed_radius"], ("Seed\nRadius", 0.15, 0.05, 0.55))


if __name__ == "__main__":
    unittest.main()
