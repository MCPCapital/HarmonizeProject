import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools.register_hue import run


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class RegisterHueTests(unittest.TestCase):
    def test_local_discovery_is_the_default_and_credentials_are_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "client.json"
            discover = Mock(return_value="192.0.2.10")
            post = Mock(
                return_value=FakeResponse(
                    [{"success": {"username": "user", "clientkey": "key"}}]
                )
            )
            with patch("builtins.input", return_value=""):
                result = run(
                    ["--output", str(output)],
                    discover_fn=discover,
                    post_fn=post,
                )

            self.assertEqual(result, 0)
            discover.assert_called_once_with()
            self.assertEqual(post.call_args.args[0], "http://192.0.2.10/api")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{"username": "user", "clientkey": "key"}\n',
            )

    def test_bridge_ip_override_skips_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "client.json"
            discover = Mock(side_effect=AssertionError("discovery must be skipped"))
            post = Mock(
                return_value=FakeResponse(
                    [{"success": {"username": "user", "clientkey": "key"}}]
                )
            )
            with patch("builtins.input", return_value=""):
                result = run(
                    ["-i", "192.0.2.20", "--output", str(output)],
                    discover_fn=discover,
                    post_fn=post,
                )

            self.assertEqual(result, 0)
            discover.assert_not_called()
            self.assertEqual(post.call_args.args[0], "http://192.0.2.20/api")

    def test_existing_credentials_are_refused_before_bridge_contact(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "client.json"
            output.write_text("existing", encoding="utf-8")
            discover = Mock()
            post = Mock()

            result = run(
                ["--output", str(output)], discover_fn=discover, post_fn=post
            )

            self.assertEqual(result, 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing")
            discover.assert_not_called()
            post.assert_not_called()

    def test_bridge_registration_error_does_not_create_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "client.json"
            post = Mock(
                return_value=FakeResponse(
                    [{"error": {"description": "link button not pressed"}}]
                )
            )
            with patch("builtins.input", return_value=""):
                result = run(
                    ["-i", "192.0.2.20", "--output", str(output)], post_fn=post
                )

            self.assertEqual(result, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
