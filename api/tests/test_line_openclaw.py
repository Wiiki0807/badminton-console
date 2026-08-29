from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import line_openclaw  # noqa: E402


class LineOpenClawTests(unittest.TestCase):
    def test_only_explicit_prefix_routes_a_long_task(self):
        self.assertEqual(
            {"action": "task", "text": "整理這個 repo 並回報"},
            line_openclaw.parse_command("OpenClaw 整理這個 repo 並回報"),
        )
        self.assertIsNone(line_openclaw.parse_command("幫我整理這個 repo"))

    def test_pairing_code_is_parsed_separately(self):
        self.assertEqual(
            {"action": "pair", "code": "abc12345"},
            line_openclaw.parse_command("小羽 配對 abc12345"),
        )

    @mock.patch("shared.line_openclaw.request.urlopen")
    @mock.patch("shared.line_openclaw.inference_hub._setting")
    def test_task_request_uses_narrow_gateway_path_and_callback(self, setting, urlopen):
        values = {
            "INFERENCE_HUB_URL": "https://cam.example",
            "INFERENCE_HUB_TOKEN": "secret",
            "LINE_OPENCLAW_CALLBACK_URL": "https://azure.example/callback",
        }
        setting.side_effect = lambda name, default="": values.get(name, default)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "ok": True, "taskId": "task-1"
        }).encode()
        urlopen.return_value = response

        result = line_openclaw.submit_task("U12345678", "do work", task_id="task-1")

        self.assertEqual("task-1", result)
        sent = urlopen.call_args.args[0]
        self.assertEqual("https://cam.example/openclaw/v1/tasks", sent.full_url)
        self.assertEqual("Bearer secret", sent.headers["Authorization"])
        self.assertEqual("U12345678", json.loads(sent.data)["userId"])


if __name__ == "__main__":
    unittest.main()
