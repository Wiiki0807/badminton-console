import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from shared import line_bot


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


if __name__ == "__main__":
    unittest.main()
