import base64
from io import BytesIO
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import function_app
from PIL import Image

from shared import line_bot, remote_image, store


class OpenClawArtifactTests(unittest.TestCase):
    @mock.patch("shared.line_bot._send_messages")
    def test_push_images_uses_native_line_image_messages(self, send):
        line_bot.push_images(
            "U-owner", "task-id",
            [("https://blob.example/one.jpg", "https://blob.example/one-preview.jpg")],
            "找到官方圖片。", "line-token",
        )

        payload = send.call_args.args[1]
        self.assertEqual("text", payload["messages"][0]["type"])
        self.assertEqual("image", payload["messages"][1]["type"])
        self.assertEqual(
            "https://blob.example/one.jpg",
            payload["messages"][1]["originalContentUrl"],
        )

    def test_artifact_flex_has_https_download_button(self):
        message = line_bot.artifact_flex(
            "rgb_cam_stream_server.py", "https://blob.example/file?sas=1", 2048,
            "已產生 Python 串流伺服器。",
        )

        self.assertEqual("flex", message["type"])
        button = message["contents"]["footer"]["contents"][0]
        self.assertEqual("uri", button["action"]["type"])
        self.assertEqual("下載檔案", button["action"]["label"])
        self.assertEqual("https://blob.example/file?sas=1", button["action"]["uri"])

    def test_rejects_artifact_with_mismatched_size(self):
        value = {
            "name": "server.py", "contentType": "text/x-python", "size": 999,
            "base64": base64.b64encode(b"print('ok')").decode(),
        }
        self.assertIsNone(function_app._openclaw_artifact(value))

    @mock.patch("function_app.store.finish_line_openclaw_task")
    @mock.patch("function_app.line_bot.push_artifact")
    @mock.patch("function_app.store.upload_line_artifact", return_value="https://blob.example/file?sas=1")
    @mock.patch("function_app.store.get_line_openclaw_task", return_value={"targetId": "U-owner"})
    @mock.patch("function_app.inference_hub.openclaw_callback_token_matches", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_callback_uploads_and_pushes_artifact_card(
        self, _auth, _get_task, upload, push, finish
    ):
        task_id = "12345678-1234-1234-1234-123456789012"
        raw = b"print('camera')\n"
        body = json.dumps({
            "taskId": task_id,
            "status": "completed",
            "text": "已產生 Python 串流伺服器。",
            "artifact": {
                "name": "rgb_cam_stream_server.py",
                "contentType": "text/x-python",
                "size": len(raw),
                "base64": base64.b64encode(raw).decode(),
            },
        }).encode()
        req = function_app.func.HttpRequest(
            method="POST", url="https://example.test/api/line-openclaw-callback",
            headers={"x-line-openclaw-token": "secret"}, body=body,
        )

        response = function_app.line_openclaw_callback(req)

        self.assertEqual(200, response.status_code)
        upload.assert_called_once_with(raw, "rgb_cam_stream_server.py", "text/x-python")
        push.assert_called_once_with(
            "U-owner", task_id, "rgb_cam_stream_server.py",
            "https://blob.example/file?sas=1", len(raw),
            "已產生 Python 串流伺服器。", "line-token",
        )
        finish.assert_called_once_with(task_id, "completed")

    @mock.patch("function_app.store.finish_line_openclaw_task")
    @mock.patch("function_app.line_bot.push_images")
    @mock.patch(
        "function_app.store.upload_line_generated_image",
        return_value=("https://blob.example/image.jpg", "https://blob.example/preview.jpg"),
    )
    @mock.patch("function_app.remote_image.fetch_public_image", return_value=(b"jpeg", "image/jpeg"))
    @mock.patch("function_app.store.get_line_openclaw_task", return_value={"targetId": "U-owner"})
    @mock.patch("function_app.inference_hub.openclaw_callback_token_matches", return_value=True)
    @mock.patch.dict("os.environ", {"LINE_CHANNEL_ACCESS_TOKEN": "line-token"}, clear=True)
    def test_callback_converts_remote_media_to_line_images(
        self, _auth, _get_task, fetch, upload, push, finish
    ):
        task_id = "12345678-1234-1234-1234-123456789012"
        body = json.dumps({
            "taskId": task_id, "status": "completed", "text": "找到 Unitree 官方圖片。",
            "imageUrls": ["https://www.unitree.com/images/g1.jpg"],
        }).encode()
        req = function_app.func.HttpRequest(
            method="POST", url="https://example.test/api/line-openclaw-callback",
            headers={"x-line-openclaw-token": "secret"}, body=body,
        )

        response = function_app.line_openclaw_callback(req)

        self.assertEqual(200, response.status_code)
        fetch.assert_called_once_with("https://www.unitree.com/images/g1.jpg")
        upload.assert_called_once_with(b"jpeg", "image/jpeg")
        self.assertEqual("U-owner", push.call_args.args[0])
        self.assertEqual(
            [("https://blob.example/image.jpg", "https://blob.example/preview.jpg")],
            push.call_args.args[2],
        )
        finish.assert_called_once_with(task_id, "completed")

    @mock.patch("shared.store.generate_blob_sas", return_value="signature")
    @mock.patch("shared.store.BlobServiceClient")
    @mock.patch.dict(
        "os.environ",
        {"STORAGE_CONNECTION_STRING": "AccountName=test;AccountKey=key"},
        clear=True,
    )
    def test_blob_is_uploaded_as_attachment(self, service_factory, _sas):
        blob = mock.MagicMock()
        blob.url = "https://blob.example/live/file.py"
        service_factory.from_connection_string.return_value.get_blob_client.return_value = blob

        url = store.upload_line_artifact(b"print(1)", "server.py", "text/x-python")

        settings = blob.upload_blob.call_args.kwargs["content_settings"]
        self.assertEqual("text/x-python", settings.content_type)
        self.assertEqual('attachment; filename="server.py"', settings.content_disposition)
        self.assertEqual("https://blob.example/live/file.py?signature", url)

    @mock.patch("shared.remote_image.socket.getaddrinfo")
    def test_remote_image_rejects_private_dns_result(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(ValueError):
            remote_image.validate_public_https_url("https://images.example/test.jpg")

    @mock.patch("shared.remote_image.request.build_opener")
    @mock.patch("shared.remote_image.socket.getaddrinfo")
    def test_remote_image_normalizes_public_png_to_jpeg(self, getaddrinfo, build_opener):
        getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        source = BytesIO()
        Image.new("RGB", (40, 20), "green").save(source, format="PNG")

        class Response:
            headers = {"Content-Length": str(len(source.getvalue()))}
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def geturl(self): return "https://images.example/test.png"
            def read(self, _size): return source.getvalue()

        build_opener.return_value.open.return_value = Response()

        raw, content_type = remote_image.fetch_public_image("https://images.example/test.png")

        self.assertEqual("image/jpeg", content_type)
        self.assertTrue(raw.startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
