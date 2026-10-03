import unittest
from pathlib import Path

from harmonize_config import load_config


ROOT = Path(__file__).parents[1]
UNIT = ROOT / "deploy/harmonize.service"
CONFIG = ROOT / "deploy/harmonize.toml"


class DeploymentTests(unittest.TestCase):
    def test_appliance_config_uses_exact_area_and_stable_capture_path(self):
        config = load_config(CONFIG, unattended=True)
        self.assertEqual(config.hue.entertainment_area, "TV area")
        self.assertEqual(
            config.capture.device_path,
            Path(
                "/dev/v4l/by-id/"
                "usb-MACROSILICON_WARRKY_USB_3.0_62196249-video-index0"
            ),
        )
        self.assertEqual(config.capture.backend, "v4l2")
        self.assertEqual(
            config.control.socket_path,
            Path("/run/harmonize/harmonize.sock"),
        )
        self.assertEqual(
            config.light_state.journal_file,
            Path("/var/lib/harmonize/light-state.json"),
        )

    def test_unit_uses_dedicated_identity_and_bounded_restart(self):
        text = UNIT.read_text()
        required = (
            "User=harmonize",
            "Group=harmonize",
            "SupplementaryGroups=video",
            "ExecStartPost=/opt/harmonize/venv/bin/python /opt/harmonize/app/tools/wait_for_control.py",
            "Restart=on-failure",
            "RestartSec=5s",
            "StartLimitBurst=3",
            "TimeoutStopSec=25s",
            "KillSignal=SIGTERM",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "DevicePolicy=closed",
            "RuntimeDirectory=harmonize",
            "StateDirectory=harmonize",
        )
        for setting in required:
            with self.subTest(setting=setting):
                self.assertIn(setting, text)

    def test_install_is_non_overwriting_and_rollback_is_scoped(self):
        install = (ROOT / "deploy/install-systemd.sh").read_text()
        uninstall = (ROOT / "deploy/uninstall-systemd.sh").read_text()
        self.assertIn("Refusing to replace existing path", install)
        self.assertIn("Refusing to reuse existing harmonize account", install)
        self.assertIn("Refusing to remove an unrecognized Harmonize unit", uninstall)
        self.assertNotIn("client.json", " ".join(
            line for line in install.splitlines() if line.startswith("echo ")
        ))


if __name__ == "__main__":
    unittest.main()
