import base64
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import line_openclaw_bridge as bridge


class NewsBridgeTests(unittest.TestCase):
    def test_news_request_gets_structured_contract(self):
        result = bridge._news_task_message("整理機器人近期新聞")
        self.assertIn("verified_news_digest", result)

    def test_non_news_task_is_unchanged(self):
        self.assertEqual("查詢機器人狀態", bridge._news_task_message("查詢機器人狀態"))

    def test_market_request_gets_market_contract(self):
        result = bridge._news_task_message("查詢 MSFT NVDA 最新股價")
        self.assertIn('"type":"market_snapshot"', result)
        self.assertIn('"date":"YYYY-MM-DD"', result)
        self.assertIn("chartRequested 必須是 false", result)
        self.assertNotIn('"type":"verified_news_digest"', result)

    def test_market_chart_request_requires_structured_chart_data(self):
        result = bridge._news_task_message("查詢 NVDA 最近五個交易日股價並產出曲線圖")
        self.assertIn("chartRequested 必須是 true", result)
        self.assertIn("最近 N 個已完成交易日", result)

    def test_parses_raw_or_fenced_digest(self):
        raw = '{"type":"verified_news_digest","items":[{"title":"A"}]}'
        self.assertIsNotNone(bridge._parse_news_digest(raw))
        self.assertIsNotNone(bridge._parse_news_digest(f"```json\n{raw}\n```"))
        self.assertIsNone(bridge._parse_news_digest("普通文字"))

    def test_parses_market_snapshot_only_with_quotes(self):
        raw = '{"type":"market_snapshot","quotes":[{"symbol":"NVDA"}]}'
        self.assertIsNotNone(bridge._parse_market_snapshot(raw))
        self.assertIsNone(bridge._parse_market_snapshot('{"type":"market_snapshot","quotes":[]}'))

    def test_extracts_workspace_media_as_downloadable_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            generated = workspace / "rgb_cam_stream_server.py"
            generated.write_text("print('camera')\n", encoding="utf-8")
            expected = generated.read_bytes()
            with mock.patch.object(bridge, "WORKSPACE_DIR", workspace):
                artifact, cleaned = bridge._extract_artifact(
                    f"程式已完成。\n\n(MEDIA:{generated})"
                )

        self.assertEqual("rgb_cam_stream_server.py", artifact["name"])
        self.assertEqual(expected, base64.b64decode(artifact["base64"]))
        self.assertNotIn("MEDIA:", cleaned)

    def test_rejects_sensitive_workspace_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            generated = workspace / "api_token.txt"
            generated.write_text("secret", encoding="utf-8")
            with mock.patch.object(bridge, "WORKSPACE_DIR", workspace):
                artifact, cleaned = bridge._extract_artifact(f"MEDIA:{generated}")

        self.assertIsNone(artifact)
        self.assertIn("無法安全附加", cleaned)


if __name__ == "__main__":
    unittest.main()
