"""Headless, recovering Harmonize lifecycle with bounded resource ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import statistics
import threading
import time
from typing import Callable

from .analysis import FrameAnalyzer
from .capture import CapturedFrame, CaptureReadError, CaptureSource
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


def _milliseconds_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "mean": round(statistics.fmean(values) * 1000, 3),
        "median": round(statistics.median(values) * 1000, 3),
        "p95": round(ordered[round((len(ordered) - 1) * 0.95)] * 1000, 3),
        "max": round(max(values) * 1000, 3),
    }


class _StreamMetrics:
    """Small in-memory window; emits one aggregate log instead of frame logs."""

    def __init__(self, update_interval_seconds: float, started_at: float):
        self.update_interval_seconds = update_interval_seconds
        self.started_at = started_at
        self.last_packet_at: float | None = None
        self.packet_count = 0
        self.replaced_frames = 0
        self.frame_ages: list[float] = []
        self.analysis_durations: list[float] = []
        self.packet_intervals: list[float] = []

    def record(
        self,
        *,
        captured_at: float,
        analysis_started_at: float,
        analysis_duration: float,
        packet_at: float,
        replaced_frames: int,
    ) -> None:
        self.packet_count += 1
        self.replaced_frames += replaced_frames
        self.frame_ages.append(max(0.0, analysis_started_at - captured_at))
        self.analysis_durations.append(analysis_duration)
        if self.last_packet_at is not None:
            self.packet_intervals.append(packet_at - self.last_packet_at)
        self.last_packet_at = packet_at

    def snapshot(
        self,
        now: float,
        capture_timing: dict[str, float | int] | None,
    ) -> dict[str, object]:
        elapsed = max(0.000001, now - self.started_at)
        gap_threshold = max(
            self.update_interval_seconds * 1.5,
            self.update_interval_seconds + 0.01,
        )
        return {
            "window_seconds": round(elapsed, 3),
            "configured_interval_ms": round(
                self.update_interval_seconds * 1000, 3
            ),
            "packets": self.packet_count,
            "effective_update_rate_hz": round(self.packet_count / elapsed, 3),
            "frame_age_ms": _milliseconds_summary(self.frame_ages),
            "analysis_ms": _milliseconds_summary(self.analysis_durations),
            "packet_interval_ms": _milliseconds_summary(self.packet_intervals),
            "long_packet_gaps": sum(
                interval > gap_threshold for interval in self.packet_intervals
            ),
            "long_gap_threshold_ms": round(gap_threshold * 1000, 3),
            "replaced_application_frames": self.replaced_frames,
            "capture_interarrival_ms": capture_timing,
        }


@dataclass(frozen=True)
class _HueStatusResult:
    generation: int
    area: EntertainmentArea | None
    error: HarmonizeError | None


class _HueStatusMonitor:
    """Run single-flight Hue status queries away from the packet loop."""

    def __init__(
        self,
        bridge_factory: Callable[[], HueBridge],
        area_name: str,
    ):
        self._bridge_factory = bridge_factory
        self._area_name = area_name
        self._lock = threading.Lock()
        self._request_event = threading.Event()
        self._stop_requested = threading.Event()
        self._requested_generation: int | None = None
        self._pending = False
        self._result: _HueStatusResult | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="harmonize-hue-status",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def request(self, generation: int) -> bool:
        with self._lock:
            if (
                self._stop_requested.is_set()
                or self._pending
                or self._result is not None
            ):
                return False
            self._pending = True
            self._requested_generation = generation
        self._request_event.set()
        return True

    def poll(self, generation: int) -> _HueStatusResult | None:
        with self._lock:
            result = self._result
            if result is None:
                return None
            self._result = None
        if result.generation != generation:
            return None
        return result

    def stop(self, timeout_seconds: float) -> bool:
        self._stop_requested.set()
        self._request_event.set()
        self._thread.join(timeout_seconds)
        return not self._thread.is_alive()

    def _run(self) -> None:
        bridge: HueBridge | None = None
        try:
            while True:
                self._request_event.wait()
                self._request_event.clear()
                if self._stop_requested.is_set():
                    return
                with self._lock:
                    generation = self._requested_generation
                if generation is None:
                    continue
                try:
                    if bridge is None:
                        bridge = self._bridge_factory()
                    area = bridge.resolve_name(self._area_name)
                    result = _HueStatusResult(generation, area, None)
                except Exception as exc:
                    error = (
                        exc
                        if isinstance(exc, HarmonizeError)
                        else HarmonizeError(f"Hue status monitor failed: {exc}")
                    )
                    result = _HueStatusResult(generation, None, error)
                with self._lock:
                    self._result = result
                    self._pending = False
                    self._requested_generation = None
        finally:
            if bridge is not None:
                bridge.close()


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
        color_processing_mode: str = "legacy_hsv",
        transport_reconnect_attempts: int = 3,
        transport_reconnect_initial_seconds: float = 0.5,
        hue_status_interval_seconds: float = 10.0,
        hue_status_shutdown_timeout_seconds: float = 5.5,
        hue_status_bridge_factory: Callable[[], HueBridge] | None = None,
        metrics_interval_seconds: float = 10.0,
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
        self.color_processing_mode = color_processing_mode
        self.transport_reconnect_attempts = transport_reconnect_attempts
        self.transport_reconnect_initial_seconds = (
            transport_reconnect_initial_seconds
        )
        self.hue_status_interval_seconds = hue_status_interval_seconds
        self.hue_status_shutdown_timeout_seconds = (
            hue_status_shutdown_timeout_seconds
        )
        self.hue_status_bridge_factory = (
            hue_status_bridge_factory or (lambda: self.hue.new_session())
        )
        self.metrics_interval_seconds = metrics_interval_seconds
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
            color_processing_mode=self.color_processing_mode,
        )

    def _transport(self) -> OpenSslDtlsTransport:
        return self.transport_factory(
            bridge_ip=self.hue.bridge_ip,
            application_id=self.hue.application_id(),
            client_key=self.client_key,
        )

    def _read_sample(self) -> CapturedFrame:
        read_sample = getattr(self.capture, "read_sample", None)
        if read_sample is not None:
            return read_sample()
        frame = self.capture.read()
        captured_at = self.capture.last_frame_monotonic or time.monotonic()
        return CapturedFrame(frame, captured_at, 0, 0)

    def _capture_timing_snapshot(self):
        snapshot = getattr(self.capture, "timing_snapshot", None)
        return snapshot() if snapshot is not None else None

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
        status_monitor: _HueStatusMonitor | None = None
        status_generation = 0
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
            frame = self._read_sample().frame
            analyzer = self._analyzer(frame)
            log_event(
                self._logger,
                logging.INFO,
                "analysis_configured",
                color_processing_mode=self.color_processing_mode,
                brightness_adjustment=self.brightness_adjustment,
                update_interval_seconds=self.update_interval_seconds,
                width=frame.shape[1],
                height=frame.shape[0],
            )
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

            status_monitor = _HueStatusMonitor(
                self.hue_status_bridge_factory,
                self.area.name,
            )
            status_monitor.start()
            self._transition(LifecycleState.STREAMING)
            self.ready.set()
            last_hue_check = time.monotonic()
            last_metrics_log = last_hue_check
            metrics = _StreamMetrics(
                self.update_interval_seconds, last_metrics_log
            )
            while not self._stop_requested.is_set():
                try:
                    sample = self._read_sample()
                    frame = sample.frame
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
                    analysis_started = time.monotonic()
                    colors = analyzer.colors(frame)
                    analysis_duration = time.monotonic() - analysis_started
                    transport.send(builder.build(colors))
                    packet_at = time.monotonic()
                    metrics.record(
                        captured_at=sample.captured_monotonic,
                        analysis_started_at=analysis_started,
                        analysis_duration=analysis_duration,
                        packet_at=packet_at,
                        replaced_frames=sample.replaced_frames,
                    )
                    with self._health_lock:
                        self._last_packet_monotonic = packet_at

                    status_result = status_monitor.poll(status_generation)
                    if status_result is not None:
                        last_hue_check = time.monotonic()
                        if status_result.error is not None:
                            raise status_result.error
                        current = status_result.area
                        if current is None or current.status != "active":
                            name = (
                                self.area.name if current is None else current.name
                            )
                            status = None if current is None else current.status
                            raise HarmonizeError(
                                f'Hue Entertainment area "{name}" '
                                f"reported status {status!r}"
                            )

                    now = time.monotonic()
                    if (
                        now - last_hue_check
                        >= self.hue_status_interval_seconds
                    ):
                        status_monitor.request(status_generation)

                    if now - last_metrics_log >= self.metrics_interval_seconds:
                        log_event(
                            self._logger,
                            logging.INFO,
                            "stream_metrics",
                            **metrics.snapshot(
                                now, self._capture_timing_snapshot()
                            ),
                        )
                        last_metrics_log = now
                        metrics = _StreamMetrics(
                            self.update_interval_seconds, now
                        )
                        metrics.last_packet_at = packet_at
                except HarmonizeError as exc:
                    log_event(
                        self._logger,
                        logging.WARNING,
                        "stream_recovery_started",
                        error=str(exc),
                    )
                    status_generation += 1
                    if not status_monitor.stop(
                        self.hue_status_shutdown_timeout_seconds
                    ):
                        log_event(
                            self._logger,
                            logging.WARNING,
                            "hue_status_monitor_stop_timed_out",
                            context="recovery",
                        )
                    status_monitor = None
                    transport, builder, analyzer = self._recover_transport(
                        transport, frame
                    )
                    status_monitor = _HueStatusMonitor(
                        self.hue_status_bridge_factory,
                        self.area.name,
                    )
                    status_monitor.start()
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
            if status_monitor is not None and not status_monitor.stop(
                self.hue_status_shutdown_timeout_seconds
            ):
                remember_cleanup_error(
                    HarmonizeError("Hue status monitor did not stop in time")
                )
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
