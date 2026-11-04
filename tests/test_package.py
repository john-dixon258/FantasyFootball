"""Basic checks for the project package."""

import subprocess
import sys
import tempfile
import unittest

import fantasy_football_ai_analyst


class PackageTests(unittest.TestCase):
    def test_package_can_be_imported(self) -> None:
        self.assertIsNotNone(fantasy_football_ai_analyst)

    def test_module_entry_point_finds_demo_outside_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "fantasy_football_ai_analyst", "demo"],
                cwd=directory, capture_output=True, text=True, check=False, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fictional", result.stdout)
        self.assertIn("Alex Example", result.stdout)


if __name__ == "__main__":
    unittest.main()
