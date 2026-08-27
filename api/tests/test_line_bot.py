import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shared import line_bot
from shared import inference_hub


STATE = {
    "players": [
        {"name": "阿力", "rating": 728, "games": 2, "targetGames": 5, "wins": 1, "losses": 1},
        {"name": "楷翔", "rating": 646, "games": 1, "targetGames": 5, "wins": 0, "losses": 1},
    ],
    "stats": [
        {"name": "阿力", "wins": 1, "pointsFor": 38, "pointsAgainst": 36, "diff": 2},
    ],
    "recent": [
        {"court": 1, "a": ["阿力", "Grace"], "b": ["楷翔", "Kevin"], "score": "21–17", "deltaA": 14, "deltaB": -14},
        {"court": 2, "a": ["小宇", "阿力"], "b": ["Grace", "Kevin"], "score": "17–21", "deltaA": -6, "deltaB": 6},
    ],
    "nextUp": {"a": ["阿力", "楷翔"], "b": ["Grace", "Kevin"], "matchType": "自由雙打", "diff": 35},
}


class LineBotAnswerTests(unittest.TestCase):
    def test_named_daily_performance_includes_scores(self):
        text = line_bot.answer("查詢阿力的本日戰績和對戰分數", STATE)
        self.assertIn("阿力 本日戰績", text)
        self.assertIn("已打 2 場", text)
        self.assertIn("21–17", text)
        self.assertIn("17–21", text)

    def test_self_query_uses_line_display_name(self):
        text = line_bot.answer("查詢自己的本日戰績和對戰分數", STATE, "阿力")
        self.assertIn("阿力 本日戰績", text)

    def test_rating_and_games_queries(self):
        self.assertIn("728", line_bot.answer("積分 阿力", STATE))
        self.assertIn("今日積分變化：+8", line_bot.answer("查詢阿力累積積分", STATE))
        self.assertIn("已打 2 場／目標 5 場", line_bot.answer("查詢阿力已打場數", STATE))

    def test_next_match_prediction(self):
        text = line_bot.answer("查詢猜測下一組對戰組合", STATE)
        self.assertIn("阿力／楷翔", text)
        self.assertIn("Grace／Kevin", text)
        self.assertIn("實力差 35 分", text)

    def test_self_query_reports_unmatched_profile(self):
        text = line_bot.answer("我的積分", STATE, "不同的LINE名稱")
        self.assertIn("尚未對應", text)

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_unknown_query_keeps_help_fallback_when_llm_is_disabled(self):
        text = line_bot.answer("今天適合練什麼？", STATE)
        self.assertIn("我目前還不懂", text)

    @mock.patch("shared.inference_hub.request.urlopen")
    @mock.patch.dict(
        "os.environ",
        {"INFERENCE_HUB_URL": "http://hub.test:8790", "INFERENCE_HUB_TOKEN": "test-token"},
        clear=True,
    )
    def test_unknown_query_uses_inference_hub(self, urlopen):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "建議先練高遠球。"}}]}
        ).encode("utf-8")
        urlopen.return_value = response

        text = line_bot.answer("今天適合練什麼？", STATE, "阿力")

        self.assertEqual("建議先練高遠球。", text)
        sent = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertFalse(sent["stream"])
        self.assertIn("阿力", sent["messages"][1]["content"])
        self.assertEqual("Bearer test-token", urlopen.call_args.args[0].headers["Authorization"])

    @mock.patch("shared.inference_hub.request.urlopen", side_effect=error.URLError("offline"))
    @mock.patch.dict(
        "os.environ",
        {"INFERENCE_HUB_URL": "http://hub.test:8790", "INFERENCE_HUB_TOKEN": "test-token"},
        clear=True,
    )
    def test_hub_failure_falls_back_to_help(self, _urlopen):
        with self.assertLogs(level="ERROR"):
            text = line_bot.answer("今天適合練什麼？", STATE)
        self.assertIn("我目前還不懂", text)

    @mock.patch("shared.inference_hub.request.urlopen")
    @mock.patch.dict("os.environ", {}, clear=True)
    def test_deployment_settings_file_supplies_production_config(self, urlopen):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "artifact config works"}}]}
        ).encode("utf-8")
        urlopen.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            settings = pathlib.Path(directory) / "deployment_settings.json"
            settings.write_text(json.dumps({
                "INFERENCE_HUB_URL": "https://funnel.test",
                "INFERENCE_HUB_TOKEN": "artifact-token",
            }), encoding="utf-8")
            with mock.patch.object(inference_hub, "SETTINGS_FILE", settings):
                inference_hub._deployment_settings.cache_clear()
                try:
                    text = line_bot.answer("自然語句", STATE)
                finally:
                    inference_hub._deployment_settings.cache_clear()
        self.assertEqual("artifact config works", text)
        req = urlopen.call_args.args[0]
        self.assertEqual("https://funnel.test/chat/completions", req.full_url)
        self.assertEqual("Bearer artifact-token", req.headers["Authorization"])


if __name__ == "__main__":
    unittest.main()
