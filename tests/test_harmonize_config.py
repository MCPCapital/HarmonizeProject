import os
from pathlib import Path
import tempfile
import unittest

from harmonize_config import ConfigError, load_config, load_credentials


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_config(self, text: str) -> Path:
        path = self.root / "harmonize.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_example_loads_in_unattended_mode(self):
        example = Path(__file__).parents[1] / "harmonize.example.toml"
        config = load_config(example, unattended=True)
        self.assertEqual(config.hue.entertainment_area, "TV area")
        self.assertEqual(config.capture.backend, "gstreamer")
        self.assertEqual(config.control.provider, "local")
        self.assertEqual(
            config.control.socket_path,
            (example.parent / "run/harmonize.sock").resolve(),
        )
        self.assertEqual(config.control.recovery_attempts, 3)
        self.assertEqual(
            config.ambilight.exception_cleanup_behavior, "restore"
        )
        self.assertEqual(
            config.light_state.journal_file,
            (example.parent / "run/harmonize-light-state.json").resolve(),
        )
        self.assertEqual(config.light_state.restore_attempts, 3)
        self.assertEqual(config.reliability.shutdown_timeout_seconds, 15.0)
        self.assertEqual(
            config.reliability.health_file,
            (example.parent / "run/harmonize-health.json").resolve(),
        )

    def test_unattended_requires_area(self):
        path = self.write_config('[hue]\ncredentials_file = "client.json"\n')
        with self.assertRaisesRegex(ConfigError, "entertainment_area is required"):
            load_config(path, unattended=True)

    def test_unattended_rejects_empty_area(self):
        path = self.write_config('[hue]\nentertainment_area = ""\n')
        with self.assertRaisesRegex(ConfigError, "non-empty"):
            load_config(path, unattended=True)

    def test_area_is_exact_and_rejects_padding(self):
        path = self.write_config('[hue]\nentertainment_area = " TV area"\n')
        with self.assertRaisesRegex(ConfigError, "whitespace"):
            load_config(path, unattended=True)

    def test_manual_mode_allows_interactive_area_fallback(self):
        path = self.write_config('[hue]\ncredentials_file = "client.json"\n')
        config = load_config(path, unattended=False)
        self.assertIsNone(config.hue.entertainment_area)

    def test_missing_file_has_actionable_error(self):
        with self.assertRaisesRegex(ConfigError, "Copy harmonize.example.toml"):
            load_config(self.root / "missing.toml", unattended=True)

    def test_unknown_setting_is_rejected(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\npassword = "no"\n'
        )
        with self.assertRaisesRegex(ConfigError, "hue.password"):
            load_config(path, unattended=True)

    def test_invalid_values_are_rejected(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[ambilight]\nsample_breadth = 2.0\n'
        )
        with self.assertRaisesRegex(ConfigError, "sample_breadth"):
            load_config(path, unattended=True)

    def test_obsolete_post_stream_behavior_is_rejected(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[ambilight]\npost_stream_behavior = "restore"\n'
        )
        with self.assertRaisesRegex(ConfigError, "post_stream_behavior"):
            load_config(path, unattended=True)

    def test_nonfinite_timing_is_rejected(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[ambilight]\nupdate_interval_seconds = nan\n'
        )
        with self.assertRaisesRegex(ConfigError, "must be finite"):
            load_config(path, unattended=True)

    def test_relative_credentials_follow_config_directory(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            'credentials_file = "secrets/client.json"\n'
        )
        config = load_config(path, unattended=True)
        self.assertEqual(
            config.hue.credentials_file,
            (self.root / "secrets/client.json").resolve(),
        )

    def test_stable_capture_device_path_is_resolved(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[capture]\ndevice_path = "/dev/v4l/by-id/capture-video-index0"\n'
            'backend = "v4l2"\n'
        )
        config = load_config(path, unattended=True)
        self.assertEqual(
            config.capture.device_path,
            Path("/dev/v4l/by-id/capture-video-index0"),
        )

    def test_device_path_and_stream_source_are_mutually_exclusive(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[capture]\ndevice_path = "/dev/video0"\n'
            'stream_source = "sample.mp4"\n'
        )
        with self.assertRaisesRegex(ConfigError, "mutually exclusive"):
            load_config(path, unattended=True)

    def test_reconnect_backoff_max_must_not_be_smaller_than_initial(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[reliability]\n'
            'capture_reconnect_initial_seconds = 2.0\n'
            'capture_reconnect_max_seconds = 1.0\n'
        )
        with self.assertRaisesRegex(ConfigError, "must be >="):
            load_config(path, unattended=True)

    def test_light_state_policy_values_are_validated(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[light_state]\nrestore_attempts = 0\n'
        )
        with self.assertRaisesRegex(ConfigError, "restore_attempts"):
            load_config(path, unattended=True)

    def test_control_policy_values_are_validated(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[control]\nrecovery_attempts = -1\n'
        )
        with self.assertRaisesRegex(ConfigError, "recovery_attempts"):
            load_config(path, unattended=True)

    def test_relative_socket_follows_config_directory(self):
        path = self.write_config(
            '[hue]\nentertainment_area = "TV area"\n'
            '[control]\nsocket_path = "state/control.sock"\n'
        )
        config = load_config(path, unattended=True)
        self.assertEqual(
            config.control.socket_path,
            (self.root / "state/control.sock").resolve(),
        )


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def write_credentials(self, text: str, mode: int = 0o600) -> Path:
        path = self.root / "client.json"
        path.write_text(text, encoding="utf-8")
        os.chmod(path, mode)
        return path

    def test_legacy_shape_loads_with_restrictive_permissions(self):
        path = self.write_credentials(
            '{"username": "example-user", "clientkey": "example-key"}'
        )
        credentials = load_credentials(path, unattended=True)
        self.assertEqual(credentials.username, "example-user")
        self.assertEqual(credentials.warnings, ())

    def test_unattended_rejects_open_permissions(self):
        path = self.write_credentials(
            '{"username": "example-user", "clientkey": "example-key"}', 0o664
        )
        with self.assertRaisesRegex(ConfigError, r"chmod 600"):
            load_credentials(path, unattended=True)

    def test_manual_mode_preserves_legacy_file_with_warning(self):
        path = self.write_credentials(
            '{"username": "example-user", "clientkey": "example-key"}', 0o664
        )
        credentials = load_credentials(path, unattended=False)
        self.assertEqual(len(credentials.warnings), 1)
        self.assertIn("chmod 600", credentials.warnings[0])

    def test_secret_values_are_not_in_shape_error(self):
        secret = "must-not-appear"
        path = self.write_credentials(
            '{"username": "' + secret + '", "clientkey": ""}'
        )
        with self.assertRaises(ConfigError) as raised:
            load_credentials(path, unattended=True)
        self.assertNotIn(secret, str(raised.exception))

    def test_symlink_is_rejected(self):
        target = self.write_credentials(
            '{"username": "example-user", "clientkey": "example-key"}'
        )
        link = self.root / "linked.json"
        link.symlink_to(target)
        with self.assertRaisesRegex(ConfigError, "non-symlink"):
            load_credentials(link, unattended=True)


if __name__ == "__main__":
    unittest.main()
