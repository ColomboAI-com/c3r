"""Regression checks at the canonical launcher CLI boundary."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DeepSeekLaunchTests(unittest.TestCase):
    def test_known_broken_image_cannot_allocate(self):
        launcher = Path(__file__).resolve().parents[1] / "deploy/deepseek-v41/launch.py"
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "launch.py"
            shutil.copy2(launcher, fixture)
            config = launcher.with_name("h100-production.env").read_text()
            lines = [
                "VLLM_IMAGE_ID=sha256:10b3c8fe9c38f6e87dfef21c8d0e457f76ab89b32892bb37a056375b25ddbf85"
                if line.startswith("VLLM_IMAGE_ID=") else line
                for line in config.splitlines()
            ]
            fixture.with_name("h100-production.env").write_text("\n".join(lines))
            model, cache = Path(directory) / "model", Path(directory) / "cache"
            model.mkdir()
            cache.mkdir()
            result = subprocess.run(
                [sys.executable, str(fixture), "--model-path", str(model),
                 "--cache-path", str(cache), "--execute"],
                capture_output=True, text=True, timeout=10, check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("known failed compiler preflight", result.stderr)
