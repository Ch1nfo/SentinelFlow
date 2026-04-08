from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.config import runtime as runtime_config


class RuntimeConfigTest(unittest.TestCase):
    def test_save_and_reset_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_dir = tmp_path / ".sentinelflow"
            config_path = config_dir / "runtime.json"

            with patch.object(runtime_config, "CONFIG_DIR", config_dir), patch.object(runtime_config, "CONFIG_PATH", config_path):
                saved = runtime_config.save_runtime_config(
                    {
                        "demo_mode": False,
                        "poll_interval_seconds": 15,
                    }
                )

                self.assertFalse(saved.demo_mode)
                self.assertEqual(saved.poll_interval_seconds, 15)
                self.assertTrue(config_path.exists())

                persisted = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertNotIn("api_base_url", persisted)
                self.assertEqual(persisted["poll_interval_seconds"], 15)

                reset = runtime_config.reset_runtime_config()
                self.assertFalse(reset.demo_mode)
                self.assertFalse(config_path.exists())
