import unittest

from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import (
    HueBridge,
    resolve_area_name,
    resolve_group_id,
    select_area_interactively,
)


def resource(name="TV area", resource_id="12345678-1234-1234-1234-123456789abc"):
    return {
        "id": resource_id,
        "id_v1": "/groups/7",
        "name": name,
        "status": "inactive",
        "channels": [
            {
                "channel_id": 0,
                "position": {"x": -0.5, "y": 0.0, "z": 0.5},
            }
        ],
        "light_services": [
            {"rid": "light-one", "rtype": "light"},
            {"rid": "ignored", "rtype": "room"},
        ],
    }


class HueResolutionTests(unittest.TestCase):
    def test_exact_name_resolves(self):
        area = resolve_area_name([resource()], "TV area")
        self.assertEqual(area.name, "TV area")
        self.assertEqual(area.legacy_group_id, "7")
        self.assertEqual(area.channels[0].channel_id, 0)
        self.assertEqual(area.status, "inactive")
        self.assertEqual(area.light_ids, ("light-one",))

    def test_name_matching_is_case_sensitive(self):
        with self.assertRaisesRegex(HarmonizeError, '"tv area" was not found'):
            resolve_area_name([resource()], "tv area")

    def test_missing_name_is_actionable(self):
        with self.assertRaisesRegex(HarmonizeError, "hue.entertainment_area"):
            resolve_area_name([resource()], "Missing area")

    def test_duplicate_exact_names_are_rejected(self):
        other = resource(
            resource_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        )
        with self.assertRaisesRegex(HarmonizeError, "2 exact matches"):
            resolve_area_name([resource(), other], "TV area")

    def test_legacy_group_id_resolves(self):
        self.assertEqual(resolve_group_id([resource()], "7").name, "TV area")

    def test_manual_selection_prompts_only_when_multiple(self):
        second = resource(
            name="Desk",
            resource_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        )
        second["id_v1"] = "/groups/9"
        prompts = []
        area = select_area_interactively(
            [resource(), second],
            input_fn=lambda prompt: prompts.append(prompt) or "9",
            output_fn=lambda message: None,
        )
        self.assertEqual(area.name, "Desk")
        self.assertEqual(len(prompts), 1)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class HueBridgeSessionTests(unittest.TestCase):
    def test_close_closes_owned_session(self):
        session = FakeSession([])
        bridge = HueBridge("192.0.2.1", "user", session=session)
        bridge.close()
        self.assertTrue(session.closed)

    def test_new_session_preserves_connection_settings(self):
        session = FakeSession([])
        bridge = HueBridge(
            "192.0.2.1",
            "user",
            session=session,
            timeout_seconds=2.5,
        )
        child = bridge.new_session()
        try:
            self.assertIsNot(child, bridge)
            self.assertEqual(child.bridge_ip, bridge.bridge_ip)
            self.assertEqual(child.username, bridge.username)
            self.assertEqual(child._timeout, 2.5)
            self.assertIsNot(child._session, session)
        finally:
            child.close()


class HueLightTests(unittest.TestCase):
    def test_get_light_requires_one_matching_resource(self):
        session = FakeSession(
            [FakeResponse({"data": [{"id": "light-one", "on": {"on": True}}]})]
        )
        bridge = HueBridge("192.0.2.1", "user", session=session)
        resource = bridge.get_light("light-one")
        self.assertEqual(resource["id"], "light-one")
        self.assertIn("/clip/v2/resource/light/light-one", session.requests[0][1])

    def test_update_light_rejects_bridge_errors(self):
        session = FakeSession([FakeResponse({"errors": [{"description": "bad"}]})])
        bridge = HueBridge("192.0.2.1", "user", session=session)
        with self.assertRaisesRegex(HarmonizeError, "rejected state update"):
            bridge.update_light("light-one", {"on": {"on": False}})


if __name__ == "__main__":
    unittest.main()
