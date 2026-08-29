import unittest

import line_openclaw_bridge as bridge


class NewsBridgeTests(unittest.TestCase):
    def test_news_request_gets_structured_contract(self):
        result = bridge._news_task_message("整理機器人近期新聞")
        self.assertIn("verified_news_digest", result)

    def test_non_news_task_is_unchanged(self):
        self.assertEqual("查詢機器人狀態", bridge._news_task_message("查詢機器人狀態"))

    def test_parses_raw_or_fenced_digest(self):
        raw = '{"type":"verified_news_digest","items":[{"title":"A"}]}'
        self.assertIsNotNone(bridge._parse_news_digest(raw))
        self.assertIsNotNone(bridge._parse_news_digest(f"```json\n{raw}\n```"))
        self.assertIsNone(bridge._parse_news_digest("普通文字"))


if __name__ == "__main__":
    unittest.main()
