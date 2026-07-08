import importlib.util
import argparse
import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_PATH = PROJECT_ROOT / "tools" / "repoman" / "launch.py"
MAIN_APP_NAME = "com.curvsurf.findsurface_omniverse_demo.kit"


_MISSING = object()


def install_launch_stubs():
    omni = types.ModuleType("omni")
    repo = types.ModuleType("omni.repo")
    man = types.ModuleType("omni.repo.man")
    kit_template = types.ModuleType("omni.repo.kit_template")
    backend = types.ModuleType("omni.repo.kit_template.backend")
    frontend = types.ModuleType("omni.repo.kit_template.frontend")
    exceptions = types.ModuleType("omni.repo.man.exceptions")
    fileutils = types.ModuleType("omni.repo.man.fileutils")
    guidelines = types.ModuleType("omni.repo.man.guidelines")
    utils = types.ModuleType("omni.repo.man.utils")
    rich = types.ModuleType("rich")
    rich_console = types.ModuleType("rich.console")
    rich_theme = types.ModuleType("rich.theme")

    man.resolve_tokens = lambda value: str(value).replace("${root}", str(PROJECT_ROOT)).replace("${shell_ext}", ".bat")
    backend.read_toml = lambda path: {}
    frontend.Separator = lambda value: ("separator", value)

    class CLIInputColorPalette:
        def select(self, *args, **kwargs):
            raise AssertionError("select UI should not be called when default_app is available")

    frontend.CLIInputColorPalette = CLIInputColorPalette
    exceptions.QuietExpectedError = RuntimeError
    fileutils.rmtree = lambda path: None
    guidelines.get_host_platform = lambda: "windows-x86_64"
    utils.find_and_extract_package = lambda path: (path, path)
    utils.process_args_to_cmd = lambda args: " ".join(map(str, args))
    utils.run_process = lambda *args, **kwargs: 0
    utils.run_process_return_output = lambda *args, **kwargs: ""
    rich_console.Console = lambda *args, **kwargs: types.SimpleNamespace(print=lambda *a, **k: None)
    rich_theme.Theme = lambda *args, **kwargs: object()

    omni.repo = repo
    repo.man = man
    repo.kit_template = kit_template
    kit_template.backend = backend
    kit_template.frontend = frontend
    man.exceptions = exceptions
    man.fileutils = fileutils
    man.guidelines = guidelines
    man.utils = utils
    rich.console = rich_console
    rich.theme = rich_theme

    modules = {
        "omni": omni,
        "omni.repo": repo,
        "omni.repo.man": man,
        "omni.repo.kit_template": kit_template,
        "omni.repo.kit_template.backend": backend,
        "omni.repo.kit_template.frontend": frontend,
        "omni.repo.man.exceptions": exceptions,
        "omni.repo.man.fileutils": fileutils,
        "omni.repo.man.guidelines": guidelines,
        "omni.repo.man.utils": utils,
        "rich": rich,
        "rich.console": rich_console,
        "rich.theme": rich_theme,
    }
    previous = {name: sys.modules.get(name, _MISSING) for name in modules}
    for name, module in modules.items():
        sys.modules[name] = module
    return previous


def restore_modules(previous):
    for name, module in previous.items():
        if module is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def load_launch_module():
    previous = install_launch_stubs()
    spec = importlib.util.spec_from_file_location("findsurface_repo_launch_test", LAUNCH_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        restore_modules(previous)
    return module


repo_launch = load_launch_module()


class RepoLaunchTests(unittest.TestCase):
    def test_setup_repo_tool_launches_configured_default_app_without_prompting(self):
        parser = argparse.ArgumentParser()
        run_repo_tool = repo_launch.setup_repo_tool(
            parser,
            {"repo_launch": {"default_app": MAIN_APP_NAME}},
        )
        options = parser.parse_args([])
        options.extra_args = []
        launched = []
        repo_launch.launch_kit = lambda app_name, *args, **kwargs: launched.append(app_name)

        run_repo_tool(
            options,
            {
                "repo": {"folders": {"build": "_build"}},
                "repo_launch": {"default_app": MAIN_APP_NAME},
            },
        )

        self.assertEqual(launched, [MAIN_APP_NAME])

    def test_select_kit_uses_configured_default_app_without_prompting(self):
        repo_launch.discover_typed_kit_files = lambda target_directory: {
            "ApplicationTemplate": [
                MAIN_APP_NAME,
                "findsurface.debug-validation.kit",
                "findsurface_no_viewport.debug_validation.kit",
                "uiapp.debug-validation.kit",
            ]
        }

        selected = repo_launch.select_kit(
            PROJECT_ROOT / "source" / "apps",
            {"repo_launch": {"default_app": MAIN_APP_NAME}},
        )

        self.assertEqual(selected, MAIN_APP_NAME)


if __name__ == "__main__":
    unittest.main()
