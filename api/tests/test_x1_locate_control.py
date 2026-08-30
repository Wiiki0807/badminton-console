from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "openclaw" / "x1_locate_control.py"
SPEC = importlib.util.spec_from_file_location("x1_locate_control", SCRIPT)
locate = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(locate)


class X1LocateControlTests(unittest.TestCase):
    def test_query_is_bounded(self):
        self.assertEqual("bottle,cup", locate._validate_query(" bottle， cup "))
        with self.assertRaises(RuntimeError):
            locate._validate_query("a,b,c,d,e,f,g,h,i")
        with self.assertRaises(RuntimeError):
            locate._validate_query("bottle; curl bad")

    @mock.patch.object(locate, "_fresh_detection")
    @mock.patch.object(locate, "_select_camera")
    def test_detect_returns_count_centers_and_bounding_boxes(self, select, fresh):
        select.return_value = {"ok": True, "camera": "USB Camera #3", "width": 1280, "height": 720}
        fresh.return_value = {
            "count": 1, "infer_ms": 456,
            "boxes": [{"label": "bottle", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.6}],
        }

        result = locate.detect("bottle", "head", include_image=False)

        self.assertEqual(1, result["count"])
        self.assertEqual([100, 200, 300, 600], result["boxes"][0]["bbox_1000"])
        self.assertEqual([200, 400], result["boxes"][0]["center_1000"])
        self.assertEqual([128, 144, 384, 432], result["boxes"][0]["bbox_pixels"])


if __name__ == "__main__":
    unittest.main()
