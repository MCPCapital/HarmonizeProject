import unittest
from pathlib import Path
from unittest.mock import patch

from harmonize_core.errors import HarmonizeError
from tools.wait_for_control import wait_for_control


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class WaitForControlTests(unittest.TestCase):
    def test_retries_until_status_succeeds(self):
        clock = FakeClock()
        responses = [
            HarmonizeError("socket absent"),
            {"ok": True, "status": {"actual_state": "IDLE"}},
        ]

        def send(*args):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with patch("tools.wait_for_control.send_local_command", side_effect=send):
            result = wait_for_control(
                Path("/run/harmonize/harmonize.sock"),
                1.0,
                clock=clock,
                sleeper=clock.sleep,
            )
        self.assertTrue(result["ok"])

    def test_timeout_is_actionable(self):
        clock = FakeClock()
        with patch(
            "tools.wait_for_control.send_local_command",
            side_effect=HarmonizeError("socket absent"),
        ):
            with self.assertRaisesRegex(HarmonizeError, "not ready"):
                wait_for_control(
                    Path("/run/harmonize/harmonize.sock"),
                    0.2,
                    clock=clock,
                    sleeper=clock.sleep,
                )


if __name__ == "__main__":
    unittest.main()
