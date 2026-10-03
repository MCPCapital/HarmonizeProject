import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
UNIT = ROOT / "deploy/harmonize-http.service"
INSTALL = ROOT / "deploy/install-http.sh"
UNINSTALL = ROOT / "deploy/uninstall-http.sh"


class HTTPDeploymentTests(unittest.TestCase):
    def assert_destination_safety(self, source, destination, expected_safe):
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; destination_is_safe "$2" "$3"',
                "bash",
                str(INSTALL),
                str(source),
                str(destination),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode == 0, expected_safe, result.stderr)

    def test_install_guard_accepts_absent_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_bytes(b"release content\n")
            self.assert_destination_safety(source, root / "destination", True)

    def test_install_guard_accepts_identical_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.write_bytes(b"release content\n")
            destination.write_bytes(source.read_bytes())
            self.assert_destination_safety(source, destination, True)

    def test_install_guard_rejects_different_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.write_bytes(b"release content\n")
            destination.write_bytes(b"locally modified content\n")
            self.assert_destination_safety(source, destination, False)

    def test_install_guard_rejects_identical_symlink_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            destination = root / "destination"
            source.write_bytes(b"release content\n")
            target.write_bytes(source.read_bytes())
            destination.symlink_to(target)
            self.assert_destination_safety(source, destination, False)

    def test_unit_uses_fixed_port_identity_and_socket(self):
        text = UNIT.read_text()
        required = (
            "Wants=harmonize.service",
            "After=harmonize.service",
            "User=harmonize",
            "Group=harmonize",
            "--bind=0.0.0.0 --port=8765",
            "--socket=/run/harmonize/harmonize.sock",
            "Restart=on-failure",
        )
        for setting in required:
            with self.subTest(setting=setting):
                self.assertIn(setting, text)

    def test_unit_hides_credentials_and_state(self):
        text = UNIT.read_text()
        required = (
            "NoNewPrivileges=yes",
            "CapabilityBoundingSet=",
            "PrivateDevices=yes",
            "ProtectSystem=strict",
            "ProtectHome=yes",
            "RestrictAddressFamilies=AF_UNIX AF_INET",
            "InaccessiblePaths=/etc/harmonize /var/lib/harmonize",
        )
        for setting in required:
            with self.subTest(setting=setting):
                self.assertIn(setting, text)

    def test_install_and_rollback_are_non_overwriting_and_scoped(self):
        install = INSTALL.read_text()
        uninstall = UNINSTALL.read_text()
        self.assertIn("Refusing to replace existing path", install)
        self.assertIn("Refusing to use an unrecognized harmonize account", install)
        self.assertIn("Refusing to remove an unrecognized Harmonize HTTP unit", uninstall)
        self.assertIn("Refusing to remove an unrecognized Harmonize HTTP tool", uninstall)
        self.assertNotIn("harmonize.service", " ".join(
            line for line in uninstall.splitlines()
            if line.startswith("systemctl disable")
        ))


if __name__ == "__main__":
    unittest.main()
