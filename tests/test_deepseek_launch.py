"""Regression checks at the canonical launcher CLI boundary."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DeepSeekLaunchTests(unittest.TestCase):
    def test_known_broken_image_cannot_allocate(self):
        launcher = Path(__file__).resolve().parents[1] / "deploy/deepseek-v41/launch.py"
        with tempfile.TemporaryDirectory() as directory:
            model, cache = Path(directory) / "model", Path(directory) / "cache"
            model.mkdir()
            cache.mkdir()
            result = subprocess.run(
                [sys.executable, str(launcher), "--model-path", str(model),
                 "--cache-path", str(cache), "--execute"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("known failed compiler preflight", result.stderr)
