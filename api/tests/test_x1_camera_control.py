from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "openclaw" / "x1_camera_control.py"
SPEC = importlib.util.spec_from_file_location("x1_camera_control", SCRIPT)
camera = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(camera)


class _Response:
    headers = {"Content-Length": "12"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return b"\xff\xd8headcam\xff\xd9"


class X1CameraControlTests(unittest.TestCase):
    @mock.patch.object(camera, "status")
    @mock.patch.object(camera.request, "urlopen", return_value=_Response())
    def test_snapshot_is_bounded_to_workspace_and_valid_jpeg(self, _open, status):
        status.return_value = {
            "ok": True, "is_head_camera": True, "is_live": True,
            "camera": "USB Camera #3", "width": 640, "height": 480,
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            camera, "WORKSPACE", Path(directory)
        ):
            result = camera.snapshot()
            target = Path(result["media"])
            self.assertTrue(target.is_relative_to(Path(directory)))
            self.assertEqual(b"\xff\xd8headcam\xff\xd9", target.read_bytes())

    @mock.patch.object(camera, "_json_get")
    def test_status_fails_closed_for_the_wrong_usb_camera(self, get_json):
        get_json.side_effect = [
            {"camera_label": "USB Camera #2", "is_live": True, "has_frame": True},
            {"devices": [{"active": True, "unique_id": "vid_0bda&pid_5846"}]},
        ]
        self.assertFalse(camera.status()["ok"])


if __name__ == "__main__":
    unittest.main()
