from dataclasses import replace
import threading
import time
import unittest

import numpy as np

from harmonize_core.controller import (
    HarmonizeController,
    LifecycleState,
    _HueStatusMonitor,
    _StreamMetrics,
)
from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import Channel, EntertainmentArea


AREA = EntertainmentArea(
    resource_id="12345678-1234-1234-1234-123456789abc",
    legacy_group_id="7",
    name="TV area",
    channels=(Channel(channel_id=0, x=0.0, y=0.0, z=0.0),),
)


class FakeHue:
    bridge_ip = "192.0.2.1"

    def __init__(self):
        self.actions = []
        self.fail_start = False
        self.fail_stop = False
        self.fail_resolve = False

    def application_id(self):
        return "test-app"

    def resolve_name(self, name):
        if self.fail_resolve:
            raise HarmonizeError(f'area "{name}" was not found')
        if name != AREA.name:
            raise HarmonizeError("unexpected area")
        status = (
            "active"
            if ("start", AREA.name) in self.actions
            else "inactive"
        )
        return replace(AREA, status=status)

    def start_streaming(self, area):
        self.actions.append(("start", area.name))
        if self.fail_start:
            raise HarmonizeError("injected lost start response")

    def stop_streaming(self, area):
        self.actions.append(("stop", area.name))
        if self.fail_stop:
            raise HarmonizeError("injected stop failure")


class FakeStatusHue:
    def __init__(self, status="active", *, error=None, blocking=False):
        self.status = status
        self.error = error
        self.blocking = blocking
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.closed = False

    def resolve_name(self, name):
        self.calls += 1
        self.started.set()
        if self.blocking:
            self.release.wait(1.0)
        if self.error is not None:
            raise self.error
        if name != AREA.name:
            raise HarmonizeError("unexpected area")
        return replace(AREA, status=self.status)

    def close(self):
        self.closed = True


class FakeCapture:
    def __init__(self, fail_open=False):
        self.fail_open = fail_open
        self.opened = False
        self.closed = False
        self.reset_requested = False
        self.reset_count = 0
        self.frame = np.full((4, 4, 3), (10, 20, 30), dtype=np.uint8)
        self.last_frame_monotonic = None

    def open(self):
        if self.fail_open:
            raise HarmonizeError("injected open failure")
        self.opened = True

    def read(self):
        self.last_frame_monotonic = 1.0
        return self.frame.copy()

    def request_reset(self):
        self.reset_requested = True

    def apply_requested_reset(self):
        self.reset_requested = False
        return False

    def reset(self):
        self.reset_count += 1

    def close(self):
        self.closed = True


class FakeLightStateManager:
    def __init__(self, fail_finish=False):
        self.snapshot = object()
        self.captured = 0
        self.finished = []
        self.fail_finish = fail_finish

    def capture(self):
        self.captured += 1
        return self.snapshot

    def finish(self, snapshot, *, behavior=None):
        self.finished.append((snapshot, behavior or "restore"))
        if self.fail_finish:
            raise HarmonizeError("injected restore failure")


class FakeTransport:
    instances = []
    fail_start = False
    fail_send = False
    fail_close = False
    fail_send_count = 0

    def __init__(self, **kwargs):
        self.started = False
        self.closed = False
        self.packets = []
        type(self).instances.append(self)

    def start(self):
        if self.fail_start:
            raise HarmonizeError("injected transport failure")
        self.started = True

    def send(self, packet):
        if type(self).fail_send_count:
            type(self).fail_send_count -= 1
            raise HarmonizeError("injected transient send failure")
        if self.fail_send:
            raise HarmonizeError("injected send failure")
        self.packets.append(packet)

    def close(self):
        self.closed = True
        if self.fail_close:
            raise HarmonizeError("injected close failure")


def controller(hue, capture):
    return HarmonizeController(
        hue=hue,
        area=AREA,
        capture=capture,
        client_key="hidden",
        brightness_adjustment=0,
        sample_breadth=0.15,
        update_interval_seconds=0.001,
        single_light=False,
        auto_restart_seconds=0,
        transport_reconnect_attempts=0,
        transport_reconnect_initial_seconds=0.001,
        hue_status_interval_seconds=60,
        transport_factory=FakeTransport,
    )


class HueStatusMonitorTests(unittest.TestCase):
    def test_slow_query_is_single_flight_and_nonblocking(self):
        bridge = FakeStatusHue(blocking=True)
        monitor = _HueStatusMonitor(lambda: bridge, AREA.name)
        monitor.start()
        started_at = time.monotonic()
        self.assertTrue(monitor.request(4))
        self.assertLess(time.monotonic() - started_at, 0.05)
        self.assertTrue(bridge.started.wait(1.0))
        self.assertFalse(monitor.request(4))
        self.assertIsNone(monitor.poll(4))
        bridge.release.set()

        deadline = time.monotonic() + 1.0
        result = None
        while result is None and time.monotonic() < deadline:
            result = monitor.poll(4)
            time.sleep(0.001)
        self.assertIsNotNone(result)
        self.assertIsNone(result.error)
        self.assertEqual(result.area.status, "active")
        self.assertEqual(bridge.calls, 1)
        self.assertTrue(monitor.stop(1.0))
        self.assertTrue(bridge.closed)

    def test_stop_is_bounded_during_inflight_query(self):
        bridge = FakeStatusHue(blocking=True)
        monitor = _HueStatusMonitor(lambda: bridge, AREA.name)
        monitor.start()
        self.assertTrue(monitor.request(1))
        self.assertTrue(bridge.started.wait(1.0))
        started_at = time.monotonic()
        self.assertFalse(monitor.stop(0.01))
        self.assertLess(time.monotonic() - started_at, 0.1)
        bridge.release.set()
        self.assertTrue(monitor.stop(1.0))
        self.assertTrue(bridge.closed)

    def test_discards_result_from_stale_generation(self):
        bridge = FakeStatusHue()
        monitor = _HueStatusMonitor(lambda: bridge, AREA.name)
        monitor.start()
        self.assertTrue(monitor.request(1))
        self.assertTrue(bridge.started.wait(1.0))
        deadline = time.monotonic() + 1.0
        while monitor._result is None and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertIsNone(monitor.poll(2))
        self.assertTrue(monitor.stop(1.0))

    def test_converts_unexpected_worker_error(self):
        bridge = FakeStatusHue(error=RuntimeError("broken"))
        monitor = _HueStatusMonitor(lambda: bridge, AREA.name)
        monitor.start()
        self.assertTrue(monitor.request(1))
        self.assertTrue(bridge.started.wait(1.0))
        deadline = time.monotonic() + 1.0
        result = None
        while result is None and time.monotonic() < deadline:
            result = monitor.poll(1)
            time.sleep(0.001)
        self.assertIsInstance(result.error, HarmonizeError)
        self.assertIn("broken", str(result.error))
        self.assertTrue(monitor.stop(1.0))


class ControllerTests(unittest.TestCase):
    def setUp(self):
        FakeTransport.instances = []
        FakeTransport.fail_start = False
        FakeTransport.fail_send = False
        FakeTransport.fail_close = False
        FakeTransport.fail_send_count = 0

    def test_streaming_session_reaches_ready_and_cleans_up(self):
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        self.assertEqual(subject.state, LifecycleState.STREAMING)
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(subject.state, LifecycleState.IDLE)
        self.assertIsNone(subject.error)
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])
        self.assertTrue(capture.closed)
        self.assertTrue(FakeTransport.instances[0].closed)
        self.assertTrue(FakeTransport.instances[0].packets)
        snapshot = subject.health_snapshot()
        self.assertEqual(snapshot["state"], "IDLE")
        self.assertFalse(snapshot["alive"])
        self.assertFalse(snapshot["ready"])

    def test_slow_status_query_does_not_pause_packet_sends(self):
        hue = FakeHue()
        capture = FakeCapture()
        status_hue = FakeStatusHue(blocking=True)
        subject = controller(hue, capture)
        subject.hue_status_interval_seconds = 0.001
        subject.hue_status_bridge_factory = lambda: status_hue
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        self.assertTrue(status_hue.started.wait(1.0))
        packet_count = len(FakeTransport.instances[0].packets)
        time.sleep(0.03)
        self.assertGreater(
            len(FakeTransport.instances[0].packets),
            packet_count + 2,
        )
        status_hue.release.set()
        subject.request_stop()
        self.assertTrue(subject.join(1.0))
        self.assertEqual(subject.state, LifecycleState.IDLE)
        self.assertTrue(status_hue.closed)

    def test_inactive_async_status_preserves_recovery(self):
        hue = FakeHue()
        capture = FakeCapture()
        status_bridges = [FakeStatusHue("inactive"), FakeStatusHue("active")]
        subject = controller(hue, capture)
        subject.hue_status_interval_seconds = 0.001
        subject.hue_status_bridge_factory = lambda: status_bridges.pop(0)
        subject.transport_reconnect_attempts = 1
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        deadline = time.monotonic() + 1.0
        while len(FakeTransport.instances) < 2:
            if time.monotonic() >= deadline:
                self.fail("inactive status did not trigger transport recovery")
            time.sleep(0.001)
        subject.request_stop()
        self.assertTrue(subject.join(1.0))
        self.assertEqual(subject.state, LifecycleState.IDLE)
        self.assertIsNone(subject.error)
        self.assertEqual(
            hue.actions,
            [
                ("start", "TV area"),
                ("stop", "TV area"),
                ("start", "TV area"),
                ("stop", "TV area"),
            ],
        )

    def test_stream_metrics_summarize_without_changing_stream_values(self):
        metrics = _StreamMetrics(0.05, 10.0)
        metrics.record(
            captured_at=10.010,
            analysis_started_at=10.012,
            analysis_duration=0.003,
            packet_at=10.016,
            replaced_frames=2,
        )
        metrics.record(
            captured_at=10.060,
            analysis_started_at=10.064,
            analysis_duration=0.005,
            packet_at=10.076,
            replaced_frames=1,
        )
        snapshot = metrics.snapshot(
            10.1, {"samples": 4, "mean_ms": 18.0}
        )
        self.assertEqual(snapshot["packets"], 2)
        self.assertEqual(snapshot["effective_update_rate_hz"], 20.0)
        self.assertEqual(snapshot["replaced_application_frames"], 3)
        self.assertEqual(snapshot["frame_age_ms"]["mean"], 3.0)
        self.assertEqual(snapshot["analysis_ms"]["mean"], 4.0)
        self.assertEqual(snapshot["packet_interval_ms"]["mean"], 60.0)
        self.assertEqual(snapshot["capture_interarrival_ms"]["samples"], 4)

    def test_capture_failure_does_not_start_hue(self):
        hue = FakeHue()
        capture = FakeCapture(fail_open=True)
        subject = controller(hue, capture)
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(hue.actions, [])
        self.assertTrue(capture.closed)

    def test_startup_revalidation_failure_acquires_no_resources(self):
        hue = FakeHue()
        hue.fail_resolve = True
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertFalse(capture.opened)
        self.assertTrue(capture.closed)
        self.assertEqual(hue.actions, [])

    def test_transport_start_failure_stops_hue(self):
        FakeTransport.fail_start = True
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])
        self.assertTrue(FakeTransport.instances[0].closed)
        self.assertTrue(capture.closed)

    def test_uncertain_hue_start_result_still_requests_stop(self):
        hue = FakeHue()
        hue.fail_start = True
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])
        self.assertTrue(capture.closed)

    def test_transport_failure_is_not_treated_as_capture_restart(self):
        FakeTransport.fail_send = True
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.auto_restart_seconds = 1
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(capture.reset_count, 0)
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])

    def test_cleanup_continues_when_transport_close_fails(self):
        FakeTransport.fail_close = True
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertTrue(capture.closed)
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])

    def test_stop_request_is_idempotent(self):
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        subject.request_stop("SIGTERM")
        subject.request_stop("SIGINT")
        subject.join(1.0)
        self.assertEqual(hue.actions.count(("stop", "TV area")), 1)

    def test_transient_transport_failure_recovers(self):
        FakeTransport.fail_send_count = 1
        hue = FakeHue()
        capture = FakeCapture()
        subject = controller(hue, capture)
        subject.transport_reconnect_attempts = 2
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        deadline = time.monotonic() + 1.0
        while len(FakeTransport.instances) < 2:
            if time.monotonic() >= deadline:
                self.fail("transport recovery did not create a replacement")
            time.sleep(0.001)
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(subject.state, LifecycleState.IDLE)
        self.assertIsNone(subject.error)
        self.assertEqual(
            hue.actions,
            [
                ("start", "TV area"),
                ("stop", "TV area"),
                ("start", "TV area"),
                ("stop", "TV area"),
            ],
        )
        self.assertTrue(FakeTransport.instances[0].closed)

    def test_explicit_stop_turns_off_captured_area_lights(self):
        hue = FakeHue()
        capture = FakeCapture()
        manager = FakeLightStateManager()
        subject = controller(hue, capture)
        subject.light_state_factory = lambda area: manager
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(manager.captured, 1)
        self.assertEqual(manager.finished, [(manager.snapshot, "off")])
        self.assertEqual(hue.actions, [("start", "TV area"), ("stop", "TV area")])

    def test_exceptional_startup_failure_restores_captured_state(self):
        hue = FakeHue()
        capture = FakeCapture()
        manager = FakeLightStateManager()
        subject = controller(hue, capture)
        subject.failure_injection = "after_dtls_ready"
        subject.light_state_factory = lambda area: manager
        subject.run()
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(manager.captured, 1)
        self.assertEqual(manager.finished, [(manager.snapshot, "restore")])

    def test_uncertain_hue_stop_preserves_state_journal_without_apply(self):
        hue = FakeHue()
        hue.fail_stop = True
        capture = FakeCapture()
        manager = FakeLightStateManager()
        subject = controller(hue, capture)
        subject.light_state_factory = lambda area: manager
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertEqual(manager.captured, 1)
        self.assertEqual(manager.finished, [])

    def test_restore_failure_is_reported_after_other_cleanup(self):
        hue = FakeHue()
        capture = FakeCapture()
        manager = FakeLightStateManager(fail_finish=True)
        subject = controller(hue, capture)
        subject.light_state_factory = lambda area: manager
        subject.start_background()
        self.assertTrue(subject.ready.wait(1.0))
        subject.request_stop()
        subject.join(1.0)
        self.assertEqual(subject.state, LifecycleState.ERROR)
        self.assertIn("restore failure", str(subject.error))
        self.assertTrue(capture.closed)
        self.assertTrue(FakeTransport.instances[0].closed)
        self.assertEqual(hue.actions[-1], ("stop", "TV area"))

    def test_failure_before_hue_start_creates_no_state_journal(self):
        hue = FakeHue()
        capture = FakeCapture()
        manager = FakeLightStateManager()
        subject = controller(hue, capture)
        subject.failure_injection = "after_capture_ready"
        subject.light_state_factory = lambda area: manager
        subject.run()
        self.assertEqual(manager.captured, 0)
        self.assertEqual(manager.finished, [])
        self.assertEqual(hue.actions, [])


if __name__ == "__main__":
    unittest.main()
