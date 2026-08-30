from __future__ import annotations

import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy-line-robot-rich-menu.py"
SPEC = importlib.util.spec_from_file_location("deploy_line_robot_rich_menu", SCRIPT)
rich_menu = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(rich_menu)


class LineRobotRichMenuTests(unittest.TestCase):
    def test_menu_has_owner_safe_physical_controls(self):
        payload = rich_menu.menu_payload()
        self.assertEqual({"width": 2500, "height": 1686}, payload["size"])
        self.assertEqual(17, len(payload["areas"]))
        pose_actions = [
            area["action"]["data"] for area in payload["areas"]
            if "action=robot_pose" in area["action"]["data"]
        ]
        self.assertEqual(13, len(pose_actions))
        self.assertTrue(all("preview=0" in value for value in pose_actions))
        self.assertTrue(all("confirmed=1" not in value for value in pose_actions))

    def test_dry_run_validates_generated_asset(self):
        result = rich_menu.deploy("", "", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(17, result["areas"])


if __name__ == "__main__":
    unittest.main()
