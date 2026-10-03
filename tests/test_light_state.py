import json
import os
from pathlib import Path
import tempfile
import unittest

from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import EntertainmentArea
from harmonize_core.light_state import (
    HueLightStateManager,
    LightState,
    LightStateJournal,
    LightStateSnapshot,
)


AREA = EntertainmentArea(
    resource_id="area-id",
    legacy_group_id="200",
    name="TV area",
    channels=(),
    light_ids=("right-id", "left-id"),
)


def light_resource(
    resource_id,
    name,
    *,
    on=True,
    brightness=42.5,
    xy=(0.3, 0.4),
    mirek=None,
    dynamics="none",
    effect="no_effect",
):
    result = {
        "id": resource_id,
        "metadata": {"name": name},
        "mode": "normal",
        "on": {"on": on},
        "dimming": {"brightness": brightness},
        "dynamics": {"status": dynamics},
        "effects_v2": {"status": {"effect": effect}},
        "timed_effects": {"status": "no_effect"},
    }
    if mirek is not None:
        result["color_temperature"] = {"mirek": mirek, "mirek_valid": True}
        result["color"] = {"xy": {"x": xy[0], "y": xy[1]}}
    else:
        result["color_temperature"] = {"mirek": None, "mirek_valid": False}
        result["color"] = {"xy": {"x": xy[0], "y": xy[1]}}
    return result


class FakeHue:
    def __init__(self):
        self.resources = {
            "right-id": light_resource("right-id", "TV Right", on=True),
            "left-id": light_resource(
                "left-id", "TV Left", on=False, brightness=18.0, mirek=300
            ),
        }
        self.updates = []
        self.failures = {}

    def get_light(self, resource_id):
        return json.loads(json.dumps(self.resources[resource_id]))

    def update_light(self, resource_id, body):
        self.updates.append((resource_id, body))
        remaining = self.failures.get(resource_id, 0)
        if remaining:
            self.failures[resource_id] = remaining - 1
            raise HarmonizeError("injected update failure")
        resource = self.resources[resource_id]
        if "on" in body:
            resource["on"].update(body["on"])
        if "dimming" in body:
            resource["dimming"].update(body["dimming"])
        if "color" in body:
            resource["color"].update(body["color"])
            resource["color_temperature"] = {"mirek": None, "mirek_valid": False}
        if "color_temperature" in body:
            resource["color_temperature"] = {
                "mirek": body["color_temperature"]["mirek"],
                "mirek_valid": True,
            }


class LightStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "state.json"
        self.hue = FakeHue()

    def tearDown(self):
        self.temporary.cleanup()

    def manager(self, behavior="restore", **kwargs):
        return HueLightStateManager(
            hue=self.hue,
            area=AREA,
            behavior=behavior,
            journal=LightStateJournal(self.path),
            stale_after_seconds=kwargs.get("stale_after_seconds", 300),
            restore_attempts=kwargs.get("restore_attempts", 3),
            retry_seconds=0.001,
            wall_clock=kwargs.get("wall_clock", lambda: 1000.0),
            sleeper=lambda seconds: None,
        )

    def test_static_xy_and_temperature_states_are_captured(self):
        xy = LightState.from_resource(self.hue.resources["right-id"])
        temperature = LightState.from_resource(self.hue.resources["left-id"])
        self.assertEqual(xy.color_xy, (0.3, 0.4))
        self.assertIsNone(xy.mirek)
        self.assertEqual(temperature.mirek, 300)
        self.assertIsNone(temperature.color_xy)
        self.assertFalse(temperature.on)

    def test_dynamic_or_effect_state_is_rejected(self):
        dynamic = light_resource("one", "Dynamic", dynamics="dynamic_palette")
        with self.assertRaisesRegex(HarmonizeError, "dynamic state"):
            LightState.from_resource(dynamic)
        effect = light_resource("two", "Effect", effect="candle")
        with self.assertRaisesRegex(HarmonizeError, "effect"):
            LightState.from_resource(effect)

    def test_restore_round_trip_and_journal_cleanup(self):
        manager = self.manager()
        snapshot = manager.capture()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.hue.resources["right-id"]["on"]["on"] = False
        self.hue.resources["right-id"]["dimming"]["brightness"] = 90.0
        self.hue.resources["right-id"]["color"]["xy"] = {"x": 0.1, "y": 0.2}
        self.hue.resources["left-id"]["on"]["on"] = True
        self.hue.resources["left-id"]["color_temperature"] = {
            "mirek": 450,
            "mirek_valid": True,
        }
        manager.finish(snapshot)
        self.assertFalse(self.path.exists())
        self.assertTrue(self.hue.resources["right-id"]["on"]["on"])
        self.assertEqual(
            self.hue.resources["right-id"]["color"]["xy"],
            {"x": 0.3, "y": 0.4},
        )
        self.assertFalse(self.hue.resources["left-id"]["on"]["on"])
        self.assertEqual(
            self.hue.resources["left-id"]["color_temperature"]["mirek"], 300
        )

    def test_off_mode_turns_every_area_light_off(self):
        manager = self.manager("off")
        snapshot = manager.capture()
        manager.finish(snapshot)
        self.assertTrue(
            all(not resource["on"]["on"] for resource in self.hue.resources.values())
        )
        self.assertFalse(self.path.exists())

    def test_partial_failure_retries_and_keeps_recovery_journal(self):
        manager = self.manager(restore_attempts=2)
        snapshot = manager.capture()
        self.hue.failures["left-id"] = 2
        with self.assertRaisesRegex(HarmonizeError, "TV Left"):
            manager.finish(snapshot)
        self.assertTrue(self.path.exists())
        payload = json.loads(self.path.read_text())
        self.assertEqual(payload["status"], "recovery_required")
        self.assertEqual(
            [item[0] for item in self.hue.updates].count("left-id"), 2
        )

    def test_existing_journal_blocks_new_capture_even_when_stale(self):
        manager = self.manager(wall_clock=lambda: 1000.0)
        snapshot = manager.capture()
        stale_manager = self.manager(
            stale_after_seconds=10, wall_clock=lambda: snapshot.captured_at + 20
        )
        with self.assertRaisesRegex(HarmonizeError, "stale"):
            stale_manager.capture()

    def test_session_mismatch_prevents_automatic_restore(self):
        manager = self.manager()
        snapshot = manager.capture()
        other = LightStateSnapshot(
            session_id="other",
            area_id=snapshot.area_id,
            area_name=snapshot.area_name,
            captured_at=snapshot.captured_at,
            lights=snapshot.lights,
        )
        with self.assertRaisesRegex(HarmonizeError, "session changed"):
            manager.finish(other)
        self.assertTrue(self.path.exists())

    def test_journal_rejects_open_permissions_and_symlinks(self):
        manager = self.manager()
        manager.capture()
        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(HarmonizeError, "0600"):
            LightStateJournal(self.path).load()
        self.path.unlink()
        target = Path(self.temporary.name) / "target"
        target.write_text("{}")
        self.path.symlink_to(target)
        with self.assertRaisesRegex(HarmonizeError, "non-symlink"):
            LightStateJournal(self.path).load()


if __name__ == "__main__":
    unittest.main()
