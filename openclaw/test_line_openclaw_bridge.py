import unittest

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
        self.assertNotIn('"type":"verified_news_digest"', result)

    def test_parses_raw_or_fenced_digest(self):
        raw = '{"type":"verified_news_digest","items":[{"title":"A"}]}'
        self.assertIsNotNone(bridge._parse_news_digest(raw))
        self.assertIsNotNone(bridge._parse_news_digest(f"```json\n{raw}\n```"))
        self.assertIsNone(bridge._parse_news_digest("普通文字"))

    def test_parses_market_snapshot_only_with_quotes(self):
        raw = '{"type":"market_snapshot","quotes":[{"symbol":"NVDA"}]}'
        self.assertIsNotNone(bridge._parse_market_snapshot(raw))
        self.assertIsNone(bridge._parse_market_snapshot('{"type":"market_snapshot","quotes":[]}'))


if __name__ == "__main__":
    unittest.main()
