import os
from pathlib import Path
import tempfile
import unittest

from harmonize_core.errors import HarmonizeError
from harmonize_core.local_control import LocalCommandProvider, send_local_command


class LocalControlTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temporary.name) / "harmonize.sock"
        self.updates = []
        self.provider = LocalCommandProvider(
            self.socket_path,
            status=lambda: {"actual_state": "IDLE", "desired": {"enabled": False}},
        )
        self.provider.start(lambda desired, policy: self.updates.append((desired, policy)))

    def tearDown(self):
        self.provider.close()
        self.temporary.cleanup()

    def test_on_off_and_status_protocol(self):
        response = send_local_command(self.socket_path, "on")
        self.assertEqual(response, {"ok": True, "command": "ON"})
        self.assertTrue(self.updates[-1][0].enabled)
        self.assertEqual(self.updates[-1][0].source, "local")
        response = send_local_command(self.socket_path, "STATUS")
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"]["actual_state"], "IDLE")
        response = send_local_command(self.socket_path, "OFF")
        self.assertFalse(self.updates[-1][0].enabled)

    def test_socket_is_owner_only_and_removed_on_close(self):
        self.assertEqual(os.stat(self.socket_path).st_mode & 0o777, 0o600)
        self.provider.close()
        self.assertFalse(self.socket_path.exists())

    def test_invalid_command_is_rejected(self):
        response = send_local_command(self.socket_path, "maybe")
        self.assertFalse(response["ok"])
        self.assertIn("ON, OFF, or STATUS", response["error"])

    def test_refuses_to_replace_regular_file(self):
        self.provider.close()
        self.socket_path.write_text("do not replace", encoding="utf-8")
        replacement = LocalCommandProvider(self.socket_path, status=dict)
        with self.assertRaisesRegex(HarmonizeError, "not a socket"):
            replacement.start(lambda desired, policy: None)


if __name__ == "__main__":
    unittest.main()
