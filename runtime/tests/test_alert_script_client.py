from __future__ import annotations

import sys
import unittest
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from sentinelflow.alerts.client import SOCAlertApiClient
from sentinelflow.config.runtime import SentinelFlowRuntimeConfig


def _build_runtime_config(script_code: str) -> SentinelFlowRuntimeConfig:
    return SentinelFlowRuntimeConfig(
        demo_mode=False,
        demo_fallback=False,
        verify_ssl=True,
        agent_enabled=True,
        llm_api_base_url="https://api.openai.com/v1",
        llm_api_key="",
        llm_model="",
        llm_temperature=0,
        llm_timeout=60,
        alert_source_enabled=True,
        alert_source_type="script",
        alert_source_url="",
        alert_source_method="GET",
        alert_source_headers="",
        alert_source_query="",
        alert_source_body="",
        alert_source_timeout=15,
        alert_source_sample_payload="",
        alert_parser_rule={},
        alert_script_code=script_code,
        alert_script_timeout=5,
        poll_interval_seconds=60,
    )


class AlertScriptClientTest(unittest.TestCase):
    def test_fetch_script_alerts_normalizes_standard_output(self) -> None:
        config = _build_runtime_config(
            """
import json

print(json.dumps([
    {
        "eventIds": "E-1",
        "alert_name": "demo-alert",
        "sip": "10.0.0.1",
        "dip": "10.0.0.2",
        "payload": "hello",
        "response_body": "world",
        "alert_time": "2026-04-08 12:00:00",
        "alert_source": "custom-source",
        "current_judgment": "待确认",
        "history_judgment": "历史处置",
        "raw_data": {"source": "script"}
    }
], ensure_ascii=False))
""".strip()
        )
        client = SOCAlertApiClient()

        result = client.fetch_script_alerts(config)

        self.assertNotIn("error", result)
        self.assertEqual(result["count"], 1)
        first = result["alerts"][0]
        self.assertEqual(first["eventIds"], "E-1")
        self.assertEqual(first["alert_name"], "demo-alert")
        self.assertEqual(first["response_body"], "world")
        self.assertEqual(first["alert_source"], "custom-source")
        self.assertEqual(first["raw_data"], {"source": "script"})

    def test_fetch_script_alerts_rejects_invalid_json(self) -> None:
        config = _build_runtime_config("print('not-json')")
        client = SOCAlertApiClient()

        result = client.fetch_script_alerts(config)

        self.assertIn("error", result)
        self.assertIn("stdout 不是合法 JSON", str(result["error"]))


if __name__ == "__main__":
    unittest.main()
