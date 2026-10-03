import unittest
from pathlib import Path
from types import SimpleNamespace
import tempfile

from harmonize_core.cli import ShutdownCoordinator, _status_snapshot, build_parser, run


class FakeController:
    def __init__(self):
        self.reasons = []

    def request_stop(self, reason):
        self.reasons.append(reason)


class CliTests(unittest.TestCase):
    def test_legacy_short_options_remain_available(self):
        args = build_parser().parse_args(
            [
                "-v",
                "-g",
                "7",
                "-b",
                "bridge-id",
                "-i",
                "192.0.2.1",
                "-s",
                "-w",
                "3",
                "-f",
                "sample.mp4",
                "-l",
                "30",
                "-a",
                "8",
            ]
        )
        self.assertTrue(args.verbose)
        self.assertEqual(args.groupid, "7")
        self.assertEqual(args.bridgeid, "bridge-id")
        self.assertEqual(args.bridgeip, "192.0.2.1")
        self.assertTrue(args.single_light)
        self.assertEqual(args.video_wait_time, 3.0)
        self.assertEqual(args.stream_filename, "sample.mp4")
        self.assertEqual(args.light_brightness, 30)
        self.assertEqual(args.auto_restart, 8.0)

    def test_unattended_and_read_only_flags_parse(self):
        args = build_parser().parse_args(
            ["--config", "harmonize.example.toml", "--unattended", "--check-area"]
        )
        self.assertTrue(args.unattended)
        self.assertTrue(args.check_area)

    def test_default_config_startup_wait_is_positive(self):
        args = build_parser().parse_args(["--config", "harmonize.example.toml"])
        self.assertIsNone(args.video_wait_time)

    def test_shutdown_coordinator_is_idempotent(self):
        controller = FakeController()
        coordinator = ShutdownCoordinator(controller)
        coordinator.request("SIGTERM")
        coordinator.request("SIGINT")
        self.assertEqual(controller.reasons, ["SIGTERM"])
        self.assertEqual(coordinator.reason, "SIGTERM")

    def test_status_snapshot_reports_only_safe_performance_fields(self):
        class FakeSupervisor:
            def snapshot(self):
                return {"actual_state": "STREAMING"}

        options = SimpleNamespace(
            color_processing_mode="direct_rgb",
            update_interval_seconds=0.033,
            brightness_adjustment=0,
        )
        self.assertEqual(
            _status_snapshot(FakeSupervisor(), options),
            {
                "actual_state": "STREAMING",
                "performance": {
                    "color_processing_mode": "direct_rgb",
                    "update_interval_seconds": 0.033,
                    "brightness_adjustment": 0,
                },
            },
        )

    def test_cli_brightness_override_cannot_bypass_direct_rgb_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "harmonize.toml"
            config.write_text(
                '[hue]\nentertainment_area = "TV area"\n'
                '[ambilight]\nbrightness_adjustment = 0\n'
                'color_processing_mode = "direct_rgb"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                run(["--config", str(config), "--light_brightness", "1"]),
                2,
            )

    def test_failure_injection_choices_are_explicit(self):
        args = build_parser().parse_args(
            ["--inject-failure", "after_hue_start"]
        )
        self.assertEqual(args.inject_failure, "after_hue_start")


if __name__ == "__main__":
    unittest.main()
