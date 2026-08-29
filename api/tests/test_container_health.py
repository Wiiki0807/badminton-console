import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import function_app


class ContainerHealthTests(unittest.TestCase):
    def test_health_is_dependency_free(self):
        request = function_app.func.HttpRequest(
            method="GET", url="https://example.test/api/health", body=b""
        )

        response = function_app.health(request)

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"ok": True, "service": "badminton-api"},
            json.loads(response.get_body()),
        )


if __name__ == "__main__":
    unittest.main()
