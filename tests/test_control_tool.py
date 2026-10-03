import unittest
from unittest.mock import patch

from harmonize_core.errors import HarmonizeError
from tools.harmonize_control import _wait_for_target, parser


class ControlToolTests(unittest.TestCase):
    def test_command_parser_normalizes_case(self):
        args = parser().parse_args(["on", "--socket", "/tmp/test.sock"])
        self.assertEqual(args.command, "ON")

    @patch("tools.harmonize_control.time.sleep")
    @patch("tools.harmonize_control.time.monotonic")
    @patch("tools.harmonize_control.send_local_command")
    def test_wait_reports_streaming_status(self, send, monotonic, sleep):
        monotonic.side_effect = [0, 0, 0.1]
        send.side_effect = [
            {"ok": True, "status": {"actual_state": "STARTING"}},
            {"ok": True, "status": {"actual_state": "STREAMING"}},
        ]
        response = _wait_for_target("/tmp/test.sock", "ON", 2)
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"]["actual_state"], "STREAMING")
        sleep.assert_called_once()

    @patch("tools.harmonize_control.time.sleep")
    @patch("tools.harmonize_control.time.monotonic")
    @patch("tools.harmonize_control.send_local_command")
    def test_wait_timeout_is_actionable(self, send, monotonic, sleep):
        monotonic.side_effect = [0, 0, 2]
        send.return_value = {
            "ok": True,
            "status": {"actual_state": "ERROR", "error": "capture failed"},
        }
        with self.assertRaisesRegex(HarmonizeError, "capture failed"):
            _wait_for_target("/tmp/test.sock", "ON", 1)


if __name__ == "__main__":
    unittest.main()
