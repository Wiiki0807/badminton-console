import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from inject_deployment_settings import inject_settings


class InjectDeploymentSettingsTests(unittest.TestCase):
    def test_production_values_are_written_inside_api_artifact(self):
        env = {
            "INFERENCE_HUB_URL": "https://funnel.test",
            "INFERENCE_HUB_TOKEN": "secret-value",
            "INFERENCE_HUB_MODEL": "test-model",
            "INFERENCE_HUB_TIMEOUT_SECONDS": "7",
        }
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "deployment_settings.json"
            self.assertTrue(inject_settings(env, target))
            value = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(env, value)

    def test_preview_build_writes_empty_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "deployment_settings.json"
            self.assertFalse(inject_settings({}, target))
            self.assertEqual({}, json.loads(target.read_text(encoding="utf-8")))

    def test_partial_credentials_fail_the_build(self):
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "deployment_settings.json"
            with self.assertRaises(RuntimeError):
                inject_settings({"INFERENCE_HUB_URL": "https://funnel.test"}, target)


if __name__ == "__main__":
    unittest.main()
