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
        self.assertEqual(5, len(payload["areas"]))
        actions = [area["action"]["data"] for area in payload["areas"]]
        self.assertIn("action=robot_control&robot=x1&command=robots", actions)
        self.assertIn("action=robot_control&robot=x1&command=list", actions)
        self.assertFalse(any("action=robot_pose" in value for value in actions))

    def test_dry_run_validates_generated_asset(self):
        result = rich_menu.deploy("", "", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(5, result["areas"])

    def test_pose_catalog_uses_large_swipeable_cards(self):
        from shared import line_bot, line_openclaw

        message = line_bot.robot_pose_catalog("x1", line_openclaw.X1_POSES)
        bubbles = message["contents"]["contents"]
        self.assertEqual("flex", message["type"])
        self.assertEqual(3, len(bubbles))
        cells = [
            cell for bubble in bubbles for row in bubble["body"]["contents"]
            for cell in row["contents"] if cell.get("action")
        ]
        self.assertEqual(13, len(cells))
        self.assertTrue(all("preview=0" in item["action"]["data"] for item in cells))
        self.assertTrue(all("confirmed=1" not in item["action"]["data"] for item in cells))


if __name__ == "__main__":
    unittest.main()
