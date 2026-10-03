import unittest
from pathlib import Path

from harmonize_core.errors import HarmonizeError
from tools.harmonize_http import dispatch


class HTTPToolTests(unittest.TestCase):
    socket_path = Path("/run/harmonize/harmonize.sock")

    def test_exact_targets_map_to_fixed_commands(self):
        sent = []

        def sender(socket_path, command):
            sent.append((socket_path, command))
            if command == "STATUS":
                return {"ok": True, "status": {"actual_state": "IDLE"}}
            return {"ok": True, "command": command}

        expectations = (
            ("/?harmonize=on", "ON", {"command": "ON", "state": "accepted"}),
            ("/?harmonize=off", "OFF", {"command": "OFF", "state": "accepted"}),
            ("/?harmonize=status", "STATUS", {"state": "IDLE"}),
        )
        for target, command, expected in expectations:
            with self.subTest(target=target):
                status, response = dispatch(
                    target, self.socket_path, sender=sender
                )
                self.assertEqual(status, 200)
                self.assertEqual(response, expected)
                self.assertEqual(sent[-1], (self.socket_path, command))

    def test_missing_unsupported_and_extra_input_is_rejected(self):
        def unexpected_sender(socket_path, command):
            self.fail("invalid requests must not reach the control socket")

        invalid_targets = (
            "/",
            "/?harmonize=restart",
            "/?harmonize=ON",
            "/?harmonize=on&extra=true",
            "/?extra=true&harmonize=on",
            "/?harmonize=on&harmonize=off",
            "/other?harmonize=on",
        )
        for target in invalid_targets:
            with self.subTest(target=target):
                status, response = dispatch(
                    target, self.socket_path, sender=unexpected_sender
                )
                self.assertEqual(status, 400)
                self.assertIn("error", response)

    def test_unavailable_socket_is_service_unavailable(self):
        def sender(socket_path, command):
            raise HarmonizeError("private detail")

        status, response = dispatch(
            "/?harmonize=status", self.socket_path, sender=sender
        )
        self.assertEqual(status, 503)
        self.assertEqual(response, {"error": "Harmonize is unavailable"})

    def test_rejected_command_and_invalid_status_are_bad_gateway(self):
        status, _ = dispatch(
            "/?harmonize=on",
            self.socket_path,
            sender=lambda socket_path, command: {"ok": False},
        )
        self.assertEqual(status, 502)

        status, _ = dispatch(
            "/?harmonize=status",
            self.socket_path,
            sender=lambda socket_path, command: {"ok": True, "status": {}},
        )
        self.assertEqual(status, 502)


if __name__ == "__main__":
    unittest.main()
