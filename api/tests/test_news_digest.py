import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import function_app
from shared import line_bot, news_digest


DIGEST = {
    "type": "verified_news_digest",
    "title": "機器人近期新聞",
    "cutoff": "2026-08-29 18:00 台北時間",
    "overallTrend": "人形機器人開始進入試產。",
    "watchNext": "量產良率。",
    "items": [{
        "title": "官方推出新平台",
        "date": "2026-08-29",
        "shortSummary": "新平台支援機器人開發。",
        "summary": "官方發布新平台，整合模擬、訓練與部署工具。",
        "importance": "縮短開發流程。",
        "confidence": "官方確認",
        "sources": ["https://example.com/news/robot"],
    }],
}


class NewsDigestTests(unittest.TestCase):
    def test_validates_and_builds_flex_carousel_actions(self):
        digest = news_digest.validate(DIGEST)
        message = line_bot.news_digest_flex("12345678-1234-1234-1234-123456789012", digest)

        self.assertEqual("flex", message["type"])
        bubble = message["contents"]["contents"][0]
        detail, original = bubble["footer"]["contents"]
        self.assertEqual("postback", detail["action"]["type"])
        self.assertIn("action=news_detail", detail["action"]["data"])
        self.assertEqual("uri", original["action"]["type"])
        self.assertEqual("https://example.com/news/robot", original["action"]["uri"])

    def test_rejects_digest_with_only_unsafe_sources(self):
        value = json.loads(json.dumps(DIGEST))
        value["items"][0]["sources"] = ["javascript:alert(1)", "http://example.com"]
        self.assertIsNone(news_digest.validate(value))

    @mock.patch("function_app.store.finish_line_openclaw_task")
    @mock.patch("function_app.line_bot.push_news_digest")
    @mock.patch("function_app.store.save_line_openclaw_news_digest")
    @mock.patch("function_app.store.get_line_openclaw_task")
    @mock.patch("function_app.inference_hub.openclaw_callback_token_matches", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_callback_saves_and_pushes_flex(
        self, _auth, get_task, save_digest, push_digest, finish
    ):
        task_id = "12345678-1234-1234-1234-123456789012"
        get_task.return_value = {"targetId": "U-owner"}
        body = json.dumps({
            "taskId": task_id, "status": "completed", "text": "fallback",
            "newsDigest": DIGEST,
        }).encode()
        req = function_app.func.HttpRequest(
            method="POST", url="https://example.test/api/line-openclaw-callback",
            headers={"x-line-openclaw-token": "secret"}, body=body,
        )

        response = function_app.line_openclaw_callback(req)

        self.assertEqual(200, response.status_code)
        saved = save_digest.call_args.args[1]
        self.assertEqual("機器人近期新聞", saved["title"])
        push_digest.assert_called_once_with("U-owner", task_id, saved, "line-token")
        finish.assert_called_once_with(task_id, "completed")

    @mock.patch("function_app.store.get_line_openclaw_news_item")
    @mock.patch("function_app.store.claim_line_webhook_event", return_value=True)
    @mock.patch("function_app.line_bot.reply")
    @mock.patch("function_app.line_bot.verify_signature", return_value=True)
    @mock.patch.dict(
        "os.environ",
        {"LINE_CHANNEL_SECRET": "secret", "LINE_CHANNEL_ACCESS_TOKEN": "line-token"},
        clear=True,
    )
    def test_postback_returns_owner_scoped_detail(
        self, _verify, reply, _claim, get_item
    ):
        task_id = "12345678-1234-1234-1234-123456789012"
        get_item.return_value = news_digest.validate(DIGEST)["items"][0]
        body = json.dumps({"events": [{
            "type": "postback", "replyToken": "reply-token", "webhookEventId": "event-1",
            "source": {"type": "user", "userId": "U-owner"},
            "postback": {"data": f"action=news_detail&task={task_id}&item=0"},
        }]}).encode()
        req = function_app.func.HttpRequest(
            method="POST", url="https://example.test/api/line-webhook",
            headers={"x-line-signature": "valid"}, body=body,
        )

        response = function_app.line_webhook(req)

        self.assertEqual(200, response.status_code)
        get_item.assert_called_once_with(task_id, "U-owner", 0)
        self.assertIn("官方推出新平台", reply.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
