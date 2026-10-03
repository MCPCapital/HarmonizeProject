import threading
import time
import unittest

from harmonize_core.controller import LifecycleState
from harmonize_core.errors import HarmonizeError
from harmonize_core.state_machine import (
    AmbilightSupervisor,
    DesiredState,
    DesiredStateArbiter,
    ProviderPolicy,
    SupervisorState,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeProvider:
    def __init__(self, name, policy, clock):
        self.name = name
        self.policy = policy
        self.clock = clock
        self.publish = None
        self.closed = False

    def start(self, publish):
        self.publish = publish

    def emit(self, enabled):
        self.publish(DesiredState(enabled, self.name, self.clock()), self.policy)

    def close(self):
        self.closed = True


class FakeHueController:
    def __init__(self, *, fail=False):
        self.state = LifecycleState.IDLE
        self.error = None
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.events = []
        self.fail = fail

    def start_background(self):
        self.events.append("start")
        if self.fail:
            self.state = LifecycleState.ERROR
            self.error = HarmonizeError("fake Hue startup failed")
            self.finished.set()
            self.ready.set()
        else:
            self.state = LifecycleState.STREAMING
            self.ready.set()

    def request_stop(self, reason, *, light_state_behavior="off"):
        self.events.append(("stop", reason, light_state_behavior))
        self.state = LifecycleState.IDLE
        self.finished.set()

    def join(self, timeout):
        self.events.append(("join", timeout))
        return True


class ArbiterTests(unittest.TestCase):
    def test_explicit_provider_is_immediate_and_has_precedence(self):
        clock = FakeClock()
        arbiter = DesiredStateArbiter(clock=clock)
        automatic = ProviderPolicy(
            priority=50,
            automatic=True,
            stale_after_seconds=10,
            enable_debounce_seconds=2,
            disable_grace_seconds=3,
        )
        explicit = ProviderPolicy(priority=100, automatic=False)
        arbiter.update(DesiredState(True, "automatic", clock()), automatic)
        self.assertFalse(arbiter.resolve().enabled)
        clock.advance(2)
        self.assertTrue(arbiter.resolve().enabled)
        arbiter.update(DesiredState(False, "local", clock()), explicit)
        resolved = arbiter.resolve()
        self.assertFalse(resolved.enabled)
        self.assertEqual(resolved.source, "local")

    def test_automatic_debounce_grace_and_stale_fail_safe(self):
        clock = FakeClock()
        arbiter = DesiredStateArbiter(clock=clock)
        policy = ProviderPolicy(
            priority=50,
            automatic=True,
            stale_after_seconds=10,
            enable_debounce_seconds=2,
            disable_grace_seconds=3,
        )
        arbiter.update(DesiredState(True, "future-cec", clock()), policy)
        self.assertFalse(arbiter.resolve().enabled)
        clock.advance(1.9)
        self.assertFalse(arbiter.resolve().enabled)
        clock.advance(0.1)
        self.assertTrue(arbiter.resolve().enabled)
        arbiter.update(DesiredState(False, "future-cec", clock()), policy)
        clock.advance(2.9)
        self.assertTrue(arbiter.resolve().enabled)
        clock.advance(0.1)
        self.assertFalse(arbiter.resolve().enabled)
        arbiter.update(DesiredState(True, "future-cec", clock()), policy)
        clock.advance(11)
        resolved = arbiter.resolve()
        self.assertFalse(resolved.enabled)
        self.assertEqual(resolved.source, "fail_safe")


class SupervisorTests(unittest.TestCase):
    def subject(self, clock, factory, providers=None, retries=1):
        return AmbilightSupervisor(
            providers=providers or [],
            controller_factory=factory,
            startup_timeout_seconds=2,
            shutdown_timeout_seconds=3,
            recovery_attempts=retries,
            recovery_initial_seconds=1,
            poll_interval_seconds=0.001,
            clock=clock,
        )

    def reconcile_twice(self, subject):
        subject._reconcile()
        subject._reconcile()

    def test_repeated_explicit_on_off_cycles_keep_supervisor_alive(self):
        clock = FakeClock()
        controllers = []

        def factory():
            result = FakeHueController()
            controllers.append(result)
            return result

        subject = self.subject(clock, factory)
        policy = ProviderPolicy(priority=100, automatic=False)
        for cycle in range(2):
            subject.publish(DesiredState(True, "local", clock()), policy)
            self.reconcile_twice(subject)
            self.assertEqual(subject.state, SupervisorState.STREAMING)
            snapshot = subject.snapshot()
            self.assertTrue(snapshot["desired"]["enabled"])
            self.assertEqual(snapshot["actual_state"], "STREAMING")
            clock.advance(1)
            subject.publish(DesiredState(False, "local", clock()), policy)
            subject._reconcile()
            self.assertEqual(subject.state, SupervisorState.IDLE)
            self.assertIsNone(subject.error)
        self.assertEqual(len(controllers), 2)
        self.assertTrue(all(controller.finished.is_set() for controller in controllers))

    def test_failed_start_cleans_up_then_recovers(self):
        clock = FakeClock()
        controllers = [FakeHueController(fail=True), FakeHueController()]
        subject = self.subject(clock, lambda: controllers.pop(0), retries=1)
        policy = ProviderPolicy(priority=100, automatic=False)
        subject.publish(DesiredState(True, "local", clock()), policy)
        subject._reconcile()
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.ERROR)
        self.assertIn("fake Hue startup failed", subject.error)
        clock.advance(1)
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.STARTING)
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.STREAMING)
        self.assertIsNone(subject.error)

    def test_exhausted_failure_latches_until_new_command(self):
        clock = FakeClock()
        made = []

        def factory():
            made.append(FakeHueController(fail=True))
            return made[-1]

        subject = self.subject(clock, factory, retries=0)
        policy = ProviderPolicy(priority=100, automatic=False)
        subject.publish(DesiredState(True, "local", clock()), policy)
        self.reconcile_twice(subject)
        self.assertEqual(subject.state, SupervisorState.ERROR)
        subject._reconcile()
        self.assertEqual(len(made), 1)
        clock.advance(1)
        subject.publish(DesiredState(True, "local", clock()), policy)
        subject._reconcile()
        self.assertEqual(len(made), 2)

    def test_interchangeable_provider_sources_drive_same_lifecycle(self):
        for source, priority in (("fake-cec", 50), ("fake-home", 60)):
            with self.subTest(source=source):
                clock = FakeClock()
                policy = ProviderPolicy(priority=priority, automatic=False)
                provider = FakeProvider(source, policy, clock)
                controller = FakeHueController()
                subject = self.subject(clock, lambda: controller, [provider])
                provider.start(subject.publish)
                provider.emit(True)
                self.reconcile_twice(subject)
                self.assertEqual(subject.state, SupervisorState.STREAMING)
                provider.emit(False)
                subject._reconcile()
                self.assertEqual(subject.state, SupervisorState.IDLE)
                self.assertIn(
                    ("stop", f"{source} requested OFF", "off"),
                    controller.events,
                )

    def test_cleanup_error_remains_visible_until_new_off_command(self):
        clock = FakeClock()
        controller = FakeHueController()

        def failed_stop(reason):
            controller.events.append(("stop", reason))
            controller.error = HarmonizeError("restore failed")
            controller.state = LifecycleState.ERROR
            controller.finished.set()

        controller.request_stop = failed_stop
        subject = self.subject(clock, lambda: controller, retries=0)
        policy = ProviderPolicy(priority=100, automatic=False)
        subject.publish(DesiredState(True, "local", clock()), policy)
        self.reconcile_twice(subject)
        clock.advance(1)
        subject.publish(DesiredState(False, "local", clock()), policy)
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.ERROR)
        self.assertEqual(subject.error, "restore failed")
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.ERROR)
        clock.advance(1)
        subject.publish(DesiredState(False, "local", clock()), policy)
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.IDLE)
        self.assertIsNone(subject.error)

    def test_controller_factory_failure_uses_bounded_recovery_policy(self):
        clock = FakeClock()
        calls = []

        def factory():
            calls.append("called")
            raise HarmonizeError("factory failed")

        subject = self.subject(clock, factory, retries=0)
        subject.publish(
            DesiredState(True, "local", clock()),
            ProviderPolicy(priority=100, automatic=False),
        )
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.ERROR)
        self.assertEqual(subject.error, "factory failed")
        subject._reconcile()
        self.assertEqual(calls, ["called"])

    def test_threaded_supervisor_stays_alive_in_idle(self):
        provider = FakeProvider(
            "fake-local",
            ProviderPolicy(priority=100, automatic=False),
            time.monotonic,
        )
        controllers = []

        def factory():
            result = FakeHueController()
            controllers.append(result)
            return result

        subject = AmbilightSupervisor(
            providers=[provider],
            controller_factory=factory,
            startup_timeout_seconds=1,
            shutdown_timeout_seconds=1,
            recovery_attempts=0,
            poll_interval_seconds=0.001,
        )
        subject.start_background()
        self.assertTrue(subject.ready.wait(1))
        self.assertEqual(subject.state, SupervisorState.IDLE)
        self.assertTrue(subject.snapshot()["alive"])
        provider.emit(True)
        deadline = time.monotonic() + 1
        while subject.state is not SupervisorState.STREAMING:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.001)
        provider.emit(False)
        deadline = time.monotonic() + 1
        while subject.state is not SupervisorState.IDLE:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.001)
        self.assertTrue(subject.snapshot()["alive"])
        provider.emit(True)
        deadline = time.monotonic() + 1
        while subject.state is not SupervisorState.STREAMING:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.001)
        subject.request_stop("test complete")
        self.assertTrue(subject.join(1))
        self.assertIn(
            ("stop", "daemon shutdown", "off"),
            controllers[-1].events,
        )
        self.assertTrue(provider.closed)

    def test_starting_timeout_enters_error_after_cleanup(self):
        clock = FakeClock()
        controller = FakeHueController()

        def stuck_start():
            controller.events.append("start")
            controller.state = LifecycleState.STARTING

        controller.start_background = stuck_start
        subject = self.subject(clock, lambda: controller, retries=0)
        policy = ProviderPolicy(priority=100, automatic=False)
        subject.publish(DesiredState(True, "local", clock()), policy)
        subject._reconcile()
        clock.advance(2.1)
        subject._reconcile()
        self.assertEqual(subject.state, SupervisorState.ERROR)
        self.assertIn("did not reach STREAMING", subject.error)
        self.assertIn(("stop", "startup timeout", "restore"), controller.events)
        self.assertTrue(controller.finished.is_set())


if __name__ == "__main__":
    unittest.main()
