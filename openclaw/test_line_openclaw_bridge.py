import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import line_openclaw_bridge as bridge


class NewsBridgeTests(unittest.TestCase):
    @mock.patch("line_openclaw_bridge.subprocess.run")
    def test_openclaw_failure_reports_sanitized_stderr(self, run):
        run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="session is busy token=do-not-leak",
        )

        with self.assertRaisesRegex(RuntimeError, "session is busy") as raised:
            bridge._openclaw("agent", "--json")

        self.assertNotIn("do-not-leak", str(raised.exception))

    @mock.patch("line_openclaw_bridge._callback")
    @mock.patch("line_openclaw_bridge._openclaw")
    def test_line_tasks_use_isolated_openclaw_sessions(self, openclaw, callback):
        openclaw.return_value = {"result": {"text": "完成"}}

        bridge._run_agent(
            "12345678-abcd-4321-abcd-1234567890ab",
            "整理一項工作",
            "https://example.test/callback",
        )

        arguments = openclaw.call_args.args
        session_index = arguments.index("--session-key") + 1
        self.assertEqual(
            "agent:main:line-task-12345678abcd4321", arguments[session_index]
        )
        callback.assert_called_once()

    @mock.patch("line_openclaw_bridge.subprocess.run")
    def test_x1_direct_play_uses_allowlisted_controller_and_real_mode(self, run):
        run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps({"ok": True}), stderr=""
        )

        result = bridge._x1_robot_command({
            "robot": "x1", "action": "play", "gesture": "thanks"
        })

        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertEqual("/usr/bin/python3", command[0])
        self.assertEqual(["play", "thanks", "--real"], command[-3:])

    def test_x1_direct_play_rejects_unknown_gesture(self):
        with self.assertRaisesRegex(ValueError, "allow-listed"):
            bridge._x1_robot_command({
                "robot": "x1", "action": "play", "gesture": "dance"
            })

    @mock.patch("line_openclaw_bridge.subprocess.run")
    def test_x1_head_only_gesture_is_allowlisted(self, run):
        run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps({"ok": True}), stderr=""
        )
        bridge._x1_robot_command({
            "robot": "x1", "action": "play", "gesture": "nod"
        })
        self.assertEqual(["play", "nod", "--real"], run.call_args.args[0][-3:])

    def test_x1_direct_command_requires_robot_name(self):
        with self.assertRaisesRegex(ValueError, "unsupported robot"):
            bridge._x1_robot_command({"action": "status"})

    @mock.patch("line_openclaw_bridge.subprocess.run")
    def test_x1_preview_omits_real_flag(self, run):
        run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps({"ok": True}), stderr=""
        )

        bridge._x1_robot_command({
            "robot": "x1", "action": "play", "gesture": "bad", "preview": True
        })

        self.assertEqual(["play", "bad"], run.call_args.args[0][-2:])

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

    @mock.patch("line_openclaw_bridge._extract_artifact")
    @mock.patch("line_openclaw_bridge.subprocess.run")
    def test_x1_head_snapshot_uses_bounded_camera_wrapper(self, run, extract):
        run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                "ok": True, "media": "/safe/x1-head.jpg",
                "camera": "USB Camera #3", "width": 640, "height": 480,
            }),
            stderr="",
        )
        extract.return_value = ({"name": "x1-head.jpg"}, "")

        artifact, caption = bridge._capture_x1_snapshot("head")

        self.assertEqual("x1-head.jpg", artifact["name"])
        self.assertIn("640×480", caption)
        self.assertEqual(["snapshot", "--view", "head"], run.call_args.args[0][-3:])

    def test_x1_camera_photo_request_is_detected(self):
        self.assertIsNotNone(
            bridge.X1_CAMERA_SNAPSHOT_RE.search("請將 X1 機器人頭部視角的照片拍給我")
        )
        self.assertEqual("left-hand", bridge._requested_x1_camera_view("拍 X1 左手相機照片"))
        self.assertEqual("right-hand", bridge._requested_x1_camera_view("拍 X1 右臂 camera snapshot"))

    def test_rejects_sensitive_workspace_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            generated = workspace / "api_token.txt"
            generated.write_text("secret", encoding="utf-8")
            with mock.patch.object(bridge, "WORKSPACE_DIR", workspace):
                artifact, cleaned = bridge._extract_artifact(f"MEDIA:{generated}")

        self.assertIsNone(artifact)
        self.assertIn("無法安全附加", cleaned)

    def test_extracts_remote_media_images_and_removes_bare_links(self):
        text = (
            "找到官方圖片：\n"
            "MEDIA:https://www.unitree.com/images/g1-one.jpg\n\n"
            "MEDIA:https://www.unitree.com/images/g1-two.png\n"
            "來源：https://www.unitree.com/g1"
        )

        urls, cleaned = bridge._extract_remote_images(text)

        self.assertEqual(2, len(urls))
        self.assertEqual("https://www.unitree.com/images/g1-one.jpg", urls[0])
        self.assertNotIn("MEDIA:", cleaned)
        self.assertIn("來源：https://www.unitree.com/g1", cleaned)


if __name__ == "__main__":
    unittest.main()
