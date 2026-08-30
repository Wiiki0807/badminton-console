from __future__ import annotations

import json
import pathlib
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import function_app  # noqa: E402


def postback_request(data: str):
    body = json.dumps({"events": [{
        "type": "postback",
        "replyToken": "reply-token",
        "webhookEventId": "robot-event-1",
        "source": {"type": "user", "userId": "U-owner"},
        "postback": {"data": data},
    }]}).encode()
    return function_app.func.HttpRequest(
        method="POST",
        url="https://example.test/api/line-webhook",
        headers={"x-line-signature": "valid"},
        body=body,
    )


class LineRobotTests(unittest.TestCase):
    @mock.patch("function_app.line_bot.reply_messages")
    @mock.patch("function_app.line_openclaw.robot_command", return_value={"ok": True})
    @mock.patch("function_app.inference_hub.is_line_owner", return_value=True)
    @mock.patch("function_app.store.claim_line_webhook_event", return_value=True)
    @mock.patch("function_app.line_bot.verify_signature", return_value=True)
    @mock.patch.dict(
        "os.environ",
        {"LINE_CHANNEL_SECRET": "secret", "LINE_CHANNEL_ACCESS_TOKEN": "line-token"},
        clear=True,
    )
    def test_pose_postback_is_owner_scoped_and_carries_robot(
        self, _verify, _claim, _owner, robot_command, reply_messages
    ):
        response = function_app.line_webhook(postback_request(
            "action=robot_pose&robot=x1&pose=hello"
        ))

        self.assertEqual(200, response.status_code)
        robot_command.assert_called_once_with(
            "U-owner", "play", "hello", robot="x1", preview=False
        )
        sent = reply_messages.call_args.args[1][0]
        self.assertEqual(13, len(sent["quickReply"]["items"]))
        self.assertIn("hello", sent["text"])

    @mock.patch("function_app.line_bot.reply_messages")
    @mock.patch("function_app.line_openclaw.robot_command")
    @mock.patch("function_app.inference_hub.is_line_owner", return_value=False)
    @mock.patch("function_app.store.claim_line_webhook_event", return_value=True)
    @mock.patch("function_app.line_bot.verify_signature", return_value=True)
    @mock.patch.dict(
        "os.environ",
        {"LINE_CHANNEL_SECRET": "secret", "LINE_CHANNEL_ACCESS_TOKEN": "line-token"},
        clear=True,
    )
    def test_non_owner_postback_never_reaches_robot(
        self, _verify, _claim, _owner, robot_command, reply_messages
    ):
        response = function_app.line_webhook(postback_request(
            "action=robot_pose&robot=x1&pose=away"
        ))

        self.assertEqual(200, response.status_code)
        robot_command.assert_not_called()
        self.assertIn("主人", reply_messages.call_args.args[1][0]["text"])


if __name__ == "__main__":
    unittest.main()
