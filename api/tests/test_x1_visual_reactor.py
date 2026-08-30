from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


OPENCLAW = Path(__file__).resolve().parents[2] / "openclaw"
sys.path.insert(0, str(OPENCLAW))
SCRIPT = OPENCLAW / "x1_visual_reactor_control.py"
SPEC = importlib.util.spec_from_file_location("x1_visual_reactor_control", SCRIPT)
control = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(control)


class X1VisualReactorControlTests(unittest.TestCase):
    def test_start_writes_bounded_persistent_rule(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            control, "STATE_DIR", Path(directory)
        ), mock.patch.object(control, "CONFIG_FILE", Path(directory) / "config.json"):
            result = control.start("light", ["nod", "shake-head"], "head", 1.5, 20)
            stored = control._read(Path(directory) / "config.json")

        self.assertTrue(result["ok"])
        self.assertTrue(stored["enabled"])
        self.assertEqual(["nod", "shake-head"], stored["actions"])
        self.assertEqual(1.5, stored["confirmSeconds"])
        self.assertEqual(20, stored["repeatSeconds"])

    def test_start_rejects_unsafe_timing_and_gesture(self):
        with self.assertRaises(ValueError):
            control.start("light", ["not-a-pose"], "head", 1.5, 20)
        with self.assertRaises(ValueError):
            control.start("light", ["nod"], "head", 0.2, 20)
        with self.assertRaises(ValueError):
            control.start("light", ["nod"], "head", 1.5, 1)

    @mock.patch.object(control.subprocess, "run", return_value=mock.Mock(returncode=0))
    def test_stop_disables_rule_and_stops_motion(self, run):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            control, "STATE_DIR", Path(directory)
        ), mock.patch.object(control, "CONFIG_FILE", Path(directory) / "config.json"):
            control._write({"enabled": True, "revision": 1})
            result = control.stop()
            stored = control._read(Path(directory) / "config.json")

        self.assertFalse(stored["enabled"])
        self.assertTrue(result["motionStopped"])
        self.assertEqual("stop", run.call_args.args[0][-1])


if __name__ == "__main__":
    unittest.main()
