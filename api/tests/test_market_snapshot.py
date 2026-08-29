import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import function_app
from shared import line_bot, market_snapshot


TASK_ID = "12345678-1234-1234-1234-123456789012"
SNAPSHOT = {
    "type": "market_snapshot", "title": "美股收盤", "market": "US",
    "asOf": "2026-08-28 16:00 ET", "session": "美東收盤",
    "quotes": [{
        "name": "NVIDIA", "symbol": "NVDA", "price": 217.55,
        "change": -10.43, "changePercent": -4.57, "currency": "USD",
        "open": 225.0, "high": 226.0, "low": 216.0, "volume": 12345678,
        "sourceUrl": "https://example.com/quote/nvda",
    }],
}


def postback_request(action: str) -> function_app.func.HttpRequest:
    body = json.dumps({"events": [{
        "type": "postback", "replyToken": "reply-token", "webhookEventId": "event-1",
        "source": {"type": "user", "userId": "U-owner"},
        "postback": {"data": f"action={action}&task={TASK_ID}"},
    }]}).encode()
    return function_app.func.HttpRequest(
        method="POST", url="https://example.test/api/line-webhook",
        headers={"x-line-signature": "valid"}, body=body,
    )


class MarketSnapshotTests(unittest.TestCase):
    def test_validates_and_builds_compact_flex_bubble(self):
        snapshot = market_snapshot.validate(SNAPSHOT)
        message = line_bot.market_snapshot_flex(TASK_ID, snapshot)
        self.assertEqual("flex", message["type"])
        self.assertEqual("bubble", message["contents"]["type"])
        footer = message["contents"]["footer"]["contents"]
        self.assertIn("action=market_refresh", footer[0]["action"]["data"])
        self.assertIn("action=market_details", footer[1]["action"]["data"])
        row = message["contents"]["body"]["contents"][3]
        self.assertEqual("NVDA", row["contents"][0]["text"])
        self.assertEqual("▼ 4.57%", row["contents"][2]["text"])

    def test_rejects_unsafe_or_non_finite_quotes(self):
        unsafe = json.loads(json.dumps(SNAPSHOT))
        unsafe["quotes"][0]["sourceUrl"] = "http://example.com/quote"
        self.assertIsNone(market_snapshot.validate(unsafe))
        unsafe["quotes"][0]["sourceUrl"] = "https://example.com/quote"
        unsafe["quotes"][0]["price"] = "NaN"
        self.assertIsNone(market_snapshot.validate(unsafe))

    @mock.patch("function_app.store.finish_line_openclaw_task")
    @mock.patch("function_app.line_bot.push_market_snapshot")
    @mock.patch("function_app.store.save_line_openclaw_market_snapshot")
    @mock.patch("function_app.store.get_line_openclaw_task", return_value={"targetId": "U-owner"})
    @mock.patch("function_app.inference_hub.openclaw_callback_token_matches", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_callback_saves_and_pushes_market_flex(
        self, _auth, _get_task, save_snapshot, push_snapshot, finish
    ):
        req = function_app.func.HttpRequest(
            method="POST", url="https://example.test/api/line-openclaw-callback",
            headers={"x-line-openclaw-token": "secret"},
            body=json.dumps({"taskId": TASK_ID, "status": "completed", "text": "fallback",
                             "marketSnapshot": SNAPSHOT}).encode(),
        )
        response = function_app.line_openclaw_callback(req)
        self.assertEqual(200, response.status_code)
        saved = save_snapshot.call_args.args[1]
        push_snapshot.assert_called_once_with("U-owner", TASK_ID, saved, "line-token")
        finish.assert_called_once_with(TASK_ID, "completed")

    @mock.patch("function_app.store.get_line_openclaw_market_snapshot", return_value=SNAPSHOT)
    @mock.patch("function_app.store.claim_line_webhook_event", return_value=True)
    @mock.patch("function_app.line_bot.reply")
    @mock.patch("function_app.line_bot.verify_signature", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_SECRET": "secret", "LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_details_postback_returns_owner_scoped_snapshot(
        self, _verify, reply, _claim, get_snapshot
    ):
        response = function_app.line_webhook(postback_request("market_details"))
        self.assertEqual(200, response.status_code)
        get_snapshot.assert_called_once_with(TASK_ID, "U-owner")
        self.assertIn("NVIDIA（NVDA）", reply.call_args.args[1])

    @mock.patch("function_app.line_openclaw.submit_task")
    @mock.patch("function_app.store.create_line_openclaw_task")
    @mock.patch("function_app.store.get_line_openclaw_task", return_value={"prompt": "查詢 NVDA 股價"})
    @mock.patch("function_app.store.get_line_openclaw_market_snapshot", return_value=SNAPSHOT)
    @mock.patch("function_app.store.claim_line_webhook_event", return_value=True)
    @mock.patch("function_app.line_bot.reply")
    @mock.patch("function_app.line_bot.verify_signature", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_SECRET": "secret", "LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_refresh_postback_creates_a_new_owner_task(
        self, _verify, reply, _claim, _get_snapshot, _get_task, create_task, submit_task
    ):
        response = function_app.line_webhook(postback_request("market_refresh"))
        self.assertEqual(200, response.status_code)
        new_task_id = create_task.call_args.args[0]
        create_task.assert_called_once_with(new_task_id, "U-owner", "查詢 NVDA 股價")
        submit_task.assert_called_once_with("U-owner", "查詢 NVDA 股價", task_id=new_task_id)
        self.assertIn("已開始更新報價", reply.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
