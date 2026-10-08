"""Run Windows dependency ownership checks without downloading any runtime."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class InstallationSafetyTests(unittest.TestCase):
    def test_powershell_ownership_and_removal(self):
        shell = shutil.which("powershell.exe")
        if shell is None:
            self.skipTest("Windows PowerShell is required")
        script = Path(__file__).with_name("installation_safety.ps1")
        with tempfile.TemporaryDirectory(prefix="fsod-installation-test-") as sandbox:
            result = subprocess.run(
                [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Sandbox", sandbox],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("INSTALLATION_SAFETY_OK", result.stdout)
