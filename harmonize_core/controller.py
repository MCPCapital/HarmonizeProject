"""Headless, recovering Harmonize lifecycle with bounded resource ownership."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import threading
import time
from typing import Callable

from .analysis import FrameAnalyzer
from .capture import CaptureReadError, CaptureSource
from .errors import HarmonizeError
from .hue import EntertainmentArea, HueBridge
from .light_state import HueLightStateManager, LightStateSnapshot
from .observability import log_event
from .protocol import HueStreamPacketBuilder
from .transport import OpenSslDtlsTransport


class LifecycleState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    STREAMING = "STREAMING"
    RECOVERING = "RECOVERING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class HarmonizeController:
    """Own capture, Hue session, analysis, transport, recovery, and cleanup."""

    FAILURE_STAGES = {
        "after_capture_ready",
        "after_hue_start",
        "after_dtls_ready",
    }

    def __init__(
        self,
        *,
        hue: HueBridge,
        area: EntertainmentArea,
        capture: CaptureSource,
        client_key: str,
        brightness_adjustment: int,
        sample_breadth: float,
        update_interval_seconds: float,
        single_light: bool,
        auto_restart_seconds: float,
        transport_reconnect_attempts: int = 3,
        transport_reconnect_initial_seconds: float = 0.5,
        hue_status_interval_seconds: float = 10.0,
        failure_injection: str | None = None,
        light_state_factory: Callable[[EntertainmentArea], HueLightStateManager] | None = None,
        transport_factory: Callable[..., OpenSslDtlsTransport] = OpenSslDtlsTransport,
        logger: logging.Logger | None = None,
    ):
        if (
            failure_injection is not None
            and failure_injection not in self.FAILURE_STAGES
        ):
            raise ValueError(f"Unknown failure injection stage: {failure_injection}")
        self.hue = hue
        self.area = area
        self.capture = capture
        self.client_key = client_key
        self.brightness_adjustment = brightness_adjustment
        self.sample_breadth = sample_breadth
        self.update_interval_seconds = update_interval_seconds
        self.single_light = single_light
        self.auto_restart_seconds = auto_restart_seconds
        self.transport_reconnect_attempts = transport_reconnect_attempts
        self.transport_reconnect_initial_seconds = (
            transport_reconnect_initial_seconds
        )
        self.hue_status_interval_seconds = hue_status_interval_seconds
        self.failure_injection = failure_injection
        self.light_state_factory = light_state_factory
        self.transport_factory = transport_factory
        self._logger = logger or logging.getLogger("harmonize.controller")

        self.state = LifecycleState.IDLE
        self.error: Exception | None = None
        self.ready = threading.Event()
        self.finished = threading.Event()
        self._stop_requested = threading.Event()
        self._stop_light_behavior: str | None = None
        self._thread: threading.Thread | None = None
        self._health_lock = threading.Lock()
        self._last_packet_monotonic: float | None = None
        self._transition_monotonic = time.monotonic()

    def _transition(self, state: LifecycleState, **fields) -> None:
        previous = self.state
        self.state = state
        self._transition_monotonic = time.monotonic()
        log_event(
            self._logger,
            logging.INFO,
            "lifecycle_transition",
            previous=previous.value,
            state=state.value,
            area=self.area.name,
            **fields,
        )

    def start_background(self) -> None:
        if self._thread is not None:
            raise HarmonizeError("Controller has already been started")
        self._thread = threading.Thread(
            target=self.run, name="harmonize-controller", daemon=True
        )
        self._thread.start()

    def request_stop(
        self,
        reason: str = "requested",
        *,
        light_state_behavior: str = "off",
    ) -> None:
        if light_state_behavior not in {"restore", "off"}:
            raise ValueError("light_state_behavior must be restore or off")
        if not self._stop_requested.is_set():
            log_event(
                self._logger,
                logging.INFO,
                "shutdown_requested",
                reason=reason,
                state=self.state.value,
                light_state_behavior=light_state_behavior,
            )
            self._stop_light_behavior = light_state_behavior
            self._stop_requested.set()

    def join(self, timeout: float | None = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def health_snapshot(self) -> dict[str, object]:
        now = time.monotonic()

        def age(value: float | None) -> float | None:
            return None if value is None else round(max(0.0, now - value), 3)

        with self._health_lock:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": self.state.value,
                "ready": (
                    self.state is LifecycleState.STREAMING
                    and self.error is None
                ),
                "alive": self._thread is not None and self._thread.is_alive(),
                "area": self.area.name,
                "last_frame_age_seconds": age(
                    self.capture.last_frame_monotonic
                ),
                "last_packet_age_seconds": age(self._last_packet_monotonic),
                "state_age_seconds": age(self._transition_monotonic),
                "error": str(self.error) if self.error is not None else None,
            }

    def _validate_area(self, area: EntertainmentArea) -> None:
        if not area.channels:
            raise HarmonizeError(
                f'Hue Entertainment area "{area.name}" has no channels'
            )
        if len(area.channels) > 20:
            raise HarmonizeError(
                f'Hue Entertainment area "{area.name}" has '
                f"{len(area.channels)} channels; maximum is 20"
            )

    def _analyzer(self, frame) -> FrameAnalyzer:
        height, width = frame.shape[:2]
        return FrameAnalyzer(
            channels=self.area.channels,
            width=width,
            height=height,
            brightness_adjustment=self.brightness_adjustment,
            breadth=self.sample_breadth,
            single_light=self.single_light and len(self.area.channels) == 1,
        )

    def _transport(self) -> OpenSslDtlsTransport:
        return self.transport_factory(
            bridge_ip=self.hue.bridge_ip,
            application_id=self.hue.application_id(),
            client_key=self.client_key,
        )

    def _inject(self, stage: str) -> None:
        if self.failure_injection == stage:
            raise HarmonizeError(f"Injected Milestone 4 failure at {stage}")

    def _recover_transport(self, transport, frame):
        try:
            transport.close()
        except Exception as exc:
            log_event(
                self._logger,
                logging.WARNING,
                "transport_close_failed",
                error=str(exc),
            )

        delay = self.transport_reconnect_initial_seconds
        last_error: Exception | None = None
        for attempt in range(1, self.transport_reconnect_attempts + 1):
            if self._stop_requested.wait(delay):
                raise HarmonizeError("Shutdown requested during transport recovery")
            self._transition(
                LifecycleState.RECOVERING,
                component="transport",
                attempt=attempt,
            )
            recovered = None
            try:
                self.area = self.hue.resolve_name(self.area.name)
                self._validate_area(self.area)
                if self.area.status == "active":
                    # Clear a bridge-side DTLS session that may outlive a dead
                    # client process before opening the replacement transport.
                    self.hue.stop_streaming(self.area)
                self.hue.start_streaming(self.area)
                log_event(
                    self._logger,
                    logging.INFO,
                    "hue_session_restarted",
                    area=self.area.name,
                    attempt=attempt,
                )
                recovered = self._transport()
                recovered.start()
                builder = HueStreamPacketBuilder(self.area.resource_id)
                analyzer = self._analyzer(frame)
                self._transition(
                    LifecycleState.STREAMING,
                    recovered_component="transport",
                    attempt=attempt,
                )
                return recovered, builder, analyzer
            except Exception as exc:
                if recovered is not None:
                    try:
                        recovered.close()
                    except Exception:
                        pass
                last_error = exc
                log_event(
                    self._logger,
                    logging.WARNING,
                    "transport_recovery_failed",
                    attempt=attempt,
                    error=str(exc),
                )
                delay = min(delay * 2, 8.0)
        raise HarmonizeError(
            "DTLS/Hue recovery exhausted "
            f"{self.transport_reconnect_attempts} attempts: {last_error}"
        )

    def run(self) -> None:
        stream_stop_required = False
        transport = None
        light_state_manager = None
        light_snapshot: LightStateSnapshot | None = None
        self._transition(LifecycleState.STARTING)

        def remember_cleanup_error(cleanup_error: Exception) -> None:
            if self.error is None:
                self.error = cleanup_error
                self.state = LifecycleState.ERROR
            log_event(
                self._logger,
                logging.ERROR,
                "cleanup_failed",
                error=str(cleanup_error),
            )

        try:
            # Revalidate the exact configured name immediately before acquiring
            # capture or requesting an Entertainment session.
            self.area = self.hue.resolve_name(self.area.name)
            self._validate_area(self.area)
            if self.light_state_factory is not None:
                light_state_manager = self.light_state_factory(self.area)

            self.capture.open()
            frame = self.capture.read()
            analyzer = self._analyzer(frame)
            builder = HueStreamPacketBuilder(self.area.resource_id)
            self._inject("after_capture_ready")

            if light_state_manager is not None:
                light_snapshot = light_state_manager.capture()
            stream_stop_required = True
            self.hue.start_streaming(self.area)
            self._inject("after_hue_start")

            transport = self._transport()
            transport.start()
            self._inject("after_dtls_ready")

            self._transition(LifecycleState.STREAMING)
            self.ready.set()
            last_hue_check = time.monotonic()
            while not self._stop_requested.is_set():
                try:
                    frame = self.capture.read()
                except CaptureReadError as exc:
                    self._transition(
                        LifecycleState.RECOVERING,
                        component="capture",
                        error=str(exc),
                    )
                    continue
                if self.state is LifecycleState.RECOVERING:
                    analyzer = self._analyzer(frame)
                    self._transition(
                        LifecycleState.STREAMING,
                        recovered_component="capture",
                    )

                try:
                    colors = analyzer.colors(frame)
                    transport.send(builder.build(colors))
                    with self._health_lock:
                        self._last_packet_monotonic = time.monotonic()

                    if (
                        time.monotonic() - last_hue_check
                        >= self.hue_status_interval_seconds
                    ):
                        current = self.hue.resolve_name(self.area.name)
                        last_hue_check = time.monotonic()
                        if current.status != "active":
                            raise HarmonizeError(
                                f'Hue Entertainment area "{current.name}" '
                                f"reported status {current.status!r}"
                            )
                except HarmonizeError as exc:
                    log_event(
                        self._logger,
                        logging.WARNING,
                        "stream_recovery_started",
                        error=str(exc),
                    )
                    transport, builder, analyzer = self._recover_transport(
                        transport, frame
                    )
                    last_hue_check = time.monotonic()

                self._stop_requested.wait(self.update_interval_seconds)
        except Exception as exc:
            self.error = exc
            self.state = LifecycleState.ERROR
            log_event(
                self._logger,
                logging.ERROR,
                "controller_failed",
                error=str(exc),
            )
            self.ready.set()
        finally:
            if self.state is not LifecycleState.ERROR:
                self._transition(LifecycleState.STOPPING)
            if transport is not None:
                try:
                    transport.close()
                except Exception as cleanup_error:
                    remember_cleanup_error(cleanup_error)
            try:
                self.capture.close()
            except Exception as cleanup_error:
                remember_cleanup_error(cleanup_error)
            if stream_stop_required:
                entertainment_stopped = False
                try:
                    self.hue.stop_streaming(self.area)
                    entertainment_stopped = True
                except Exception as cleanup_error:
                    remember_cleanup_error(cleanup_error)
                if (
                    entertainment_stopped
                    and light_state_manager is not None
                    and light_snapshot is not None
                ):
                    try:
                        light_state_manager.finish(
                            light_snapshot,
                            behavior=self._stop_light_behavior,
                        )
                    except Exception as cleanup_error:
                        remember_cleanup_error(cleanup_error)
            if self.state is not LifecycleState.ERROR:
                self._transition(LifecycleState.IDLE)
            self.ready.set()
            self.finished.set()
