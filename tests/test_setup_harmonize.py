import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock

from harmonize_config import load_config
from harmonize_core.hue import DiscoveredBridge
from setup_harmonize import run


ROOT = Path(__file__).parents[1]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeBridge:
    def __init__(self, address, username, resources):
        self.address = address
        self.username = username
        self.resources = resources
        self.closed = False

    def list_entertainment_resources(self):
        return self.resources

    def close(self):
        self.closed = True


class SetupHarmonizeTests(unittest.TestCase):
    def write_credentials(self, path: Path):
        path.write_text(
            json.dumps({"username": "user", "clientkey": "key"}),
            encoding="utf-8",
        )
        os.chmod(path, 0o600)

    def test_selects_multiple_bridge_and_area_and_saves_bridge_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "harmonize.toml"
            credential_path = root / "client.json"
            self.write_credentials(credential_path)
            bridges = (
                DiscoveredBridge("1111111111111111", "192.0.2.1", "BSB002", "One"),
                DiscoveredBridge("2222222222222222", "192.0.2.2", "BSB002", "Two"),
            )
            resources = [
                {"name": "Living Room", "channels": [{}, {}]},
                {"name": "TV area", "channels": [{}, {}, {}]},
            ]
            created = []

            def bridge_factory(address, username):
                bridge = FakeBridge(address, username, resources)
                created.append(bridge)
                return bridge

            answers = iter(("2", "2"))
            post = Mock(side_effect=AssertionError("pairing must be skipped"))
            get = Mock(side_effect=AssertionError("mDNS ID must be reused"))
            result = run(
                [
                    "--config",
                    str(config_path),
                    "--credentials",
                    str(credential_path),
                    "--example",
                    str(ROOT / "harmonize.example.toml"),
                ],
                input_fn=lambda prompt: next(answers),
                output_fn=lambda message: None,
                discovery_fn=lambda **kwargs: bridges,
                post_fn=post,
                get_fn=get,
                bridge_factory=bridge_factory,
            )

            self.assertEqual(result, 0)
            config = load_config(config_path, unattended=True)
            self.assertEqual(config.hue.bridge_id, "2222222222222222")
            self.assertEqual(config.hue.entertainment_area, "TV area")
            self.assertEqual(config.hue.credentials_file, credential_path)
            self.assertEqual(created[0].address, "192.0.2.2")
            self.assertTrue(created[0].closed)
            post.assert_not_called()
            get.assert_not_called()

    def test_first_time_setup_pairs_and_writes_private_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "harmonize.toml"
            credential_path = root / "client.json"
            discovered = (
                DiscoveredBridge(
                    "ecb5fafffeb0bd37", "192.0.2.10", "BSB002", "Hue Bridge"
                ),
            )
            post = Mock(
                return_value=FakeResponse(
                    [{"success": {"username": "user", "clientkey": "key"}}]
                )
            )
            result = run(
                [
                    "--config",
                    str(config_path),
                    "--credentials",
                    str(credential_path),
                    "--example",
                    str(ROOT / "harmonize.example.toml"),
                ],
                input_fn=lambda prompt: "",
                output_fn=lambda message: None,
                discovery_fn=lambda **kwargs: discovered,
                post_fn=post,
                get_fn=Mock(side_effect=AssertionError("ID is already known")),
                bridge_factory=lambda address, username: FakeBridge(
                    address,
                    username,
                    [{"name": "TV area", "channels": [{}]}],
                ),
            )

            self.assertEqual(result, 0)
            self.assertEqual(
                config_path.read_text(encoding="utf-8").count("bridge_id ="),
                1,
            )
            self.assertEqual(stat.S_IMODE(credential_path.stat().st_mode), 0o600)
            self.assertEqual(
                load_config(config_path, unattended=True).hue.bridge_id,
                "ecb5fafffeb0bd37",
            )
            post.assert_called_once()

    def test_declining_existing_config_stops_before_network_or_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "harmonize.toml"
            original = (
                '[hue]\n'
                'entertainment_area = "TV area"\n'
                'credentials_file = "client.json"\n'
            )
            config_path.write_text(original, encoding="utf-8")
            discovery = Mock()

            result = run(
                ["--config", str(config_path)],
                input_fn=lambda prompt: "n",
                output_fn=lambda message: None,
                discovery_fn=discovery,
            )

            self.assertEqual(result, 2)
            self.assertEqual(config_path.read_text(encoding="utf-8"), original)
            self.assertFalse((root / "client.json").exists())
            discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
