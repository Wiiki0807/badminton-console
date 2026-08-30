from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "openclaw" / "x1_gesture_control.py"
SPEC = importlib.util.spec_from_file_location("x1_gesture_control", SCRIPT)
x1 = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(x1)


class X1GestureControlTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.epoch_patch = mock.patch.object(x1, "EPOCH_FILE", Path(self.tempdir.name) / "epoch")
        self.epoch_patch.start()
        self.addCleanup(self.epoch_patch.stop)

    @mock.patch.object(x1, "_gesture_path", return_value=Path("/safe/away.json"))
    @mock.patch.object(x1, "_request", return_value={"ok": True})
    def test_preview_is_default_and_real_is_explicit(self, request, _path):
        x1.play("away", real=False)
        self.assertTrue(request.call_args.args[0]["isaac_only"])

        x1.play("away", real=True)
        self.assertFalse(request.call_args.args[0]["isaac_only"])

    def test_unlisted_gesture_is_rejected(self):
        with self.assertRaises(ValueError):
            x1._gesture_path("../../danger")

    @mock.patch.object(x1, "_gesture_path", return_value=Path("/safe/away.json"))
    @mock.patch.object(x1, "_request", return_value={"ok": True, "duration_s": 0})
    def test_sequence_is_bounded(self, _request, _path):
        result = x1.sequence(["away", "thanks"], real=False, pause=0)
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(result["completed"]))
        with self.assertRaises(ValueError):
            x1.sequence(["away"] * 6, real=False, pause=0)


if __name__ == "__main__":
    unittest.main()
