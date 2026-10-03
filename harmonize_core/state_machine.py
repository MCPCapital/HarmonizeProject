"""Persistent desired-state arbitration and Ambilight lifecycle supervision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import threading
import time
from typing import Callable, Protocol

from .controller import LifecycleState
from .errors import HarmonizeError
from .observability import log_event


@dataclass(frozen=True)
class DesiredState:
    """A provider's normalized desired Ambilight state."""

    enabled: bool
    source: str
    timestamp: float


@dataclass(frozen=True)
class ProviderPolicy:
    """Arbitration and filtering rules for one desired-state provider."""

    priority: int
    automatic: bool
    stale_after_seconds: float | None = None
    enable_debounce_seconds: float = 0.0
    disable_grace_seconds: float = 0.0


class DesiredStateProvider(Protocol):
    name: str
    policy: ProviderPolicy

    def start(self, publish: Callable[[DesiredState, ProviderPolicy], None]) -> None: ...

    def close(self) -> None: ...


@dataclass
class _ProviderRecord:
    update: DesiredState
    policy: ProviderPolicy
    effective_enabled: bool
    changed_at: float


class DesiredStateArbiter:
    """Resolve provider updates by priority after automatic-source filtering."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._records: dict[str, _ProviderRecord] = {}
        self._lock = threading.Lock()
        self.generation = 0

    def update(self, desired: DesiredState, policy: ProviderPolicy) -> None:
        if not desired.source:
            raise ValueError("desired-state source must be non-empty")
        if policy.priority < 0:
            raise ValueError("provider priority must be non-negative")
        with self._lock:
            previous = self._records.get(desired.source)
            changed_at = desired.timestamp
            effective = desired.enabled
            if policy.automatic:
                if previous is None:
                    effective = False
                else:
                    effective = previous.effective_enabled
                    if previous.update.enabled == desired.enabled:
                        changed_at = previous.changed_at
            self._records[desired.source] = _ProviderRecord(
                update=desired,
                policy=policy,
                effective_enabled=effective,
                changed_at=changed_at,
            )
            self.generation += 1

    def resolve(self) -> DesiredState:
        now = self._clock()
        with self._lock:
            candidates: list[_ProviderRecord] = []
            stale_sources: list[str] = []
            for source, record in self._records.items():
                policy = record.policy
                age = max(0.0, now - record.update.timestamp)
                if (
                    policy.stale_after_seconds is not None
                    and age > policy.stale_after_seconds
                ):
                    stale_sources.append(source)
                    continue
                if policy.automatic and (
                    record.effective_enabled != record.update.enabled
                ):
                    delay = (
                        policy.enable_debounce_seconds
                        if record.update.enabled
                        else policy.disable_grace_seconds
                    )
                    if max(0.0, now - record.changed_at) >= delay:
                        record.effective_enabled = record.update.enabled
                candidates.append(record)
            for source in stale_sources:
                del self._records[source]
                self.generation += 1
            if not candidates:
                return DesiredState(False, "fail_safe", now)
            selected = max(
                candidates,
                key=lambda record: (
                    record.policy.priority,
                    record.update.timestamp,
                    record.update.source,
                ),
            )
            return DesiredState(
                selected.effective_enabled,
                selected.update.source,
                selected.update.timestamp,
            )


class SupervisorState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    STREAMING = "STREAMING"
    STOPPING = "STOPPING"
    RECOVERING = "RECOVERING"
    ERROR = "ERROR"


class AmbilightSupervisor:
    """Keep the daemon alive while reconciling desired and actual state."""

    def __init__(
        self,
        *,
        providers: list[DesiredStateProvider],
        controller_factory: Callable[[], object],
        startup_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        recovery_attempts: int = 3,
        recovery_initial_seconds: float = 1.0,
        poll_interval_seconds: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ):
        self.providers = providers
        self.controller_factory = controller_factory
        self.startup_timeout_seconds = startup_timeout_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self.recovery_attempts = recovery_attempts
        self.recovery_initial_seconds = recovery_initial_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.clock = clock
        self._logger = logger or logging.getLogger("harmonize.supervisor")

        self.arbiter = DesiredStateArbiter(clock=clock)
        self.state = SupervisorState.IDLE
        self.error: str | None = None
        self.desired = DesiredState(False, "fail_safe", clock())
        self.ready = threading.Event()
        self.finished = threading.Event()
        self._shutdown = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._controller = None
        self._controller_started_at: float | None = None
        self._transition_at = clock()
        self._transition_from = SupervisorState.IDLE
        self._transition_reason = "initial"
        self._recovery_count = 0
        self._retry_at: float | None = None
        self._failed_generation: int | None = None
        self._last_generation = -1
        self._lock = threading.Lock()

    def _transition(self, state: SupervisorState, reason: str) -> None:
        now = self.clock()
        previous = self.state
        elapsed = max(0.0, now - self._transition_at)
        with self._lock:
            self._transition_from = previous
            self.state = state
            self._transition_at = now
            self._transition_reason = reason
        log_event(
            self._logger,
            logging.INFO,
            "supervisor_transition",
            previous=previous.value,
            state=state.value,
            reason=reason,
            elapsed_seconds=round(elapsed, 3),
            desired_enabled=self.desired.enabled,
            provider_source=self.desired.source,
        )

    def publish(self, desired: DesiredState, policy: ProviderPolicy) -> None:
        self.arbiter.update(desired, policy)
        self._wake.set()

    def start_background(self) -> None:
        if self._thread is not None:
            raise HarmonizeError("Ambilight supervisor has already been started")
        self._thread = threading.Thread(
            target=self.run, name="harmonize-supervisor", daemon=True
        )
        self._thread.start()

    def request_stop(self, reason: str = "requested") -> None:
        if not self._shutdown.is_set():
            log_event(
                self._logger,
                logging.INFO,
                "supervisor_shutdown_requested",
                reason=reason,
                state=self.state.value,
            )
            self._shutdown.set()
            self._wake.set()

    def join(self, timeout: float | None = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def snapshot(self) -> dict[str, object]:
        now = self.clock()
        with self._lock:
            transition = {
                "from": self._transition_from.value,
                "to": self.state.value,
                "reason": self._transition_reason,
                "elapsed_seconds": round(max(0.0, now - self._transition_at), 3),
            }
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alive": self._thread is not None and self._thread.is_alive(),
                "ready": self.ready.is_set() and not self.finished.is_set(),
                "desired": {
                    "enabled": self.desired.enabled,
                    "source": self.desired.source,
                    "age_seconds": round(
                        max(0.0, now - self.desired.timestamp), 3
                    ),
                },
                "actual_state": self.state.value,
                "transition": transition,
                "error": self.error,
                "recovery_attempt": self._recovery_count,
            }

    def _start_controller(self, *, recovering: bool) -> None:
        if recovering:
            self._transition(
                SupervisorState.RECOVERING,
                f"retry {self._recovery_count} after controller failure",
            )
        self._controller = self.controller_factory()
        self._controller_started_at = self.clock()
        self._transition(
            SupervisorState.STARTING,
            f'{self.desired.source} requested ON',
        )
        self._controller.start_background()

    def _stop_controller(self, reason: str) -> bool:
        controller = self._controller
        if controller is None:
            return True
        self._transition(SupervisorState.STOPPING, reason)
        controller.request_stop(reason)
        if not controller.join(self.shutdown_timeout_seconds):
            self.error = (
                "Ambilight controller did not stop within "
                f"{self.shutdown_timeout_seconds:g} seconds"
            )
            self._transition(SupervisorState.ERROR, self.error)
            return False
        self._controller = None
        self._controller_started_at = None
        if controller.error is not None:
            self.error = str(controller.error)
            self._transition(SupervisorState.ERROR, self.error)
            return False
        self.error = None
        self._transition(SupervisorState.IDLE, "cleanup complete")
        return True

    def _controller_failed(self, error: object) -> None:
        if self._controller is not None:
            self._controller.join(self.shutdown_timeout_seconds)
            self._controller = None
            self._controller_started_at = None
        self.error = str(error or "Ambilight controller stopped unexpectedly")
        self._transition(SupervisorState.ERROR, self.error)
        if self._recovery_count < self.recovery_attempts:
            self._recovery_count += 1
            delay = self.recovery_initial_seconds * (2 ** (self._recovery_count - 1))
            self._retry_at = self.clock() + delay
        else:
            self._failed_generation = self.arbiter.generation
            self._retry_at = None

    def _reconcile(self) -> None:
        generation = self.arbiter.generation
        desired = self.arbiter.resolve()
        generation_changed = generation != self._last_generation
        if (
            desired.enabled != self.desired.enabled
            or desired.source != self.desired.source
            or generation != self._last_generation
        ):
            log_event(
                self._logger,
                logging.INFO,
                "desired_state_resolved",
                enabled=desired.enabled,
                source=desired.source,
                generation=generation,
            )
            if generation != self._last_generation:
                self._failed_generation = None
                self._recovery_count = 0
                self._retry_at = None
            self.desired = desired
            self._last_generation = generation

        controller = self._controller
        if not desired.enabled:
            self._retry_at = None
            self._failed_generation = None
            self._recovery_count = 0
            if controller is not None:
                self._stop_controller(f'{desired.source} requested OFF')
            elif self.state is SupervisorState.ERROR and not generation_changed:
                return
            elif self.state is not SupervisorState.IDLE:
                self.error = None
                self._transition(SupervisorState.IDLE, "disabled state acknowledged")
            return

        if controller is None:
            if self._failed_generation == generation:
                return
            if self._retry_at is not None and self.clock() < self._retry_at:
                return
            try:
                self._start_controller(recovering=self._recovery_count > 0)
            except Exception as exc:
                self._controller_failed(exc)
            return

        if controller.finished.is_set():
            if controller.error is not None:
                self._controller_failed(controller.error)
            else:
                self._controller = None
                self._controller_started_at = None
                self._controller_failed("Ambilight controller exited while ON")
            return

        child_state = controller.state
        if (
            child_state is LifecycleState.STARTING
            and self._controller_started_at is not None
            and self.clock() - self._controller_started_at
            > self.startup_timeout_seconds
        ):
            controller.request_stop(
                "startup timeout",
                light_state_behavior="restore",
            )
            controller.join(self.shutdown_timeout_seconds)
            self._controller_failed(
                "Ambilight controller did not reach STREAMING within "
                f"{self.startup_timeout_seconds:g} seconds"
            )
            return
        mapped = SupervisorState(child_state.value)
        if mapped is not self.state:
            if mapped is SupervisorState.STREAMING:
                self.error = None
            reason = (
                f'{desired.source} requested ON'
                if mapped is SupervisorState.STREAMING
                else f"controller entered {mapped.value}"
            )
            self._transition(mapped, reason)

    def run(self) -> None:
        started_providers: list[DesiredStateProvider] = []
        try:
            for provider in self.providers:
                provider.start(self.publish)
                started_providers.append(provider)
            self.ready.set()
            while not self._shutdown.is_set():
                self._reconcile()
                self._wake.wait(self.poll_interval_seconds)
                self._wake.clear()
        except Exception as exc:
            self.error = str(exc)
            self._transition(SupervisorState.ERROR, self.error)
            log_event(
                self._logger,
                logging.ERROR,
                "supervisor_failed",
                error=self.error,
            )
            self.ready.set()
        finally:
            if self._controller is not None:
                self._stop_controller("daemon shutdown")
            for provider in reversed(started_providers):
                try:
                    provider.close()
                except Exception as exc:
                    log_event(
                        self._logger,
                        logging.ERROR,
                        "provider_close_failed",
                        provider=provider.name,
                        error=str(exc),
                    )
                    if self.error is None:
                        self.error = str(exc)
            if self.state is not SupervisorState.ERROR:
                self._transition(SupervisorState.IDLE, "daemon stopped")
            self.finished.set()
            self.ready.set()
