import http.client
from pathlib import Path
import tempfile
import threading
import unittest

from harmonize_core.local_control import LocalCommandProvider
from tools.harmonize_http import HarmonizeHTTPServer


class HTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temporary.name) / "harmonize.sock"
        self.updates = []
        self.provider = LocalCommandProvider(
            self.socket_path,
            status=lambda: {
                "actual_state": "IDLE",
                "performance": {
                    "color_processing_mode": "direct_rgb",
                    "update_interval_seconds": 0.033,
                    "brightness_adjustment": 0,
                },
            },
        )
        self.provider.start(
            lambda desired, policy: self.updates.append((desired, policy))
        )
        self.server = HarmonizeHTTPServer(("127.0.0.1", 0), self.socket_path)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        self.provider.close()
        self.temporary.cleanup()

    def request(self, method, target):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=2
        )
        connection.request(method, target)
        response = connection.getresponse()
        result = response.status, response.getheaders(), response.read()
        connection.close()
        return result

    def test_status_returns_concise_state_and_performance_config(self):
        status, headers, body = self.request("GET", "/?harmonize=status")
        self.assertEqual(status, 200)
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertEqual(
            body,
            b'{"state":"IDLE","performance":{'
            b'"color_processing_mode":"direct_rgb",'
            b'"update_interval_seconds":0.033,'
            b'"brightness_adjustment":0}}\n',
        )

    def test_on_and_off_reach_local_provider(self):
        status, _, body = self.request("GET", "/?harmonize=on")
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"command":"ON","state":"accepted"}\n')
        self.assertTrue(self.updates[-1][0].enabled)

        status, _, body = self.request("GET", "/?harmonize=off")
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"command":"OFF","state":"accepted"}\n')
        self.assertFalse(self.updates[-1][0].enabled)

    def test_invalid_get_is_400_and_does_not_publish(self):
        status, _, _ = self.request("GET", "/?harmonize=on&extra=true")
        self.assertEqual(status, 400)
        self.assertEqual(self.updates, [])

    def test_non_get_is_405(self):
        status, headers, _ = self.request("POST", "/?harmonize=on")
        self.assertEqual(status, 405)
        self.assertIn(("Allow", "GET"), headers)
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
