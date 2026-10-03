"""Bounded, recovering OpenCV capture for unattended operation."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import cv2

from .errors import HarmonizeError
from .observability import log_event


class CaptureReadError(HarmonizeError):
    """A bounded frame-read failure while the worker recovers."""


class CaptureSource:
    """Own one OpenCV handle in a worker and retain only the newest frame."""

    def __init__(
        self,
        *,
        device_index: int = 0,
        device_path: str | None = None,
        backend: str = "gstreamer",
        stream_source: str | None = None,
        startup_timeout_seconds: float = 10.0,
        read_timeout_seconds: float = 2.0,
        reconnect_initial_seconds: float = 0.5,
        reconnect_max_seconds: float = 5.0,
        shutdown_timeout_seconds: float = 5.0,
        cv2_module: Any = cv2,
        logger: logging.Logger | None = None,
    ):
        self.device_index = device_index
        self.device_path = device_path
        self.backend = backend
        self.stream_source = stream_source
        self.startup_timeout_seconds = startup_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._cv2 = cv2_module
        self._logger = logger or logging.getLogger("harmonize.capture")

        self._capture = None
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._reset_requested = threading.Event()
        self._ready = threading.Event()
        self._condition = threading.Condition()
        self._latest_frame = None
        self._generation = 0
        self._consumed_generation = 0
        self._last_error: Exception | None = None
        self.last_frame_monotonic: float | None = None

    @property
    def source_description(self) -> str:
        if self.stream_source is not None:
            return self.stream_source
        if self.device_path is not None:
            return self.device_path
        return f"/dev/video{self.device_index}"

    def _new_capture(self):
        if self.stream_source is not None:
            return self._cv2.VideoCapture(self.stream_source)
        backend_id = {
            "gstreamer": self._cv2.CAP_GSTREAMER,
            "v4l2": self._cv2.CAP_V4L2,
            "any": self._cv2.CAP_ANY,
        }[self.backend]
        source = self.device_path if self.device_path is not None else self.device_index
        return self._cv2.VideoCapture(source, backend_id)

    def _release_handle(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()

    def _open_handle(self) -> None:
        self._release_handle()
        capture = self._new_capture()
        if not capture.isOpened():
            capture.release()
            raise CaptureReadError(
                f"Unable to open capture source {self.source_description}"
            )
        capture.set(self._cv2.CAP_PROP_BUFFERSIZE, 0)
        self._capture = capture

    def open(self) -> None:
        if self._thread is not None:
            raise HarmonizeError("Capture source is already open")
        self._stop_requested.clear()
        self._reset_requested.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="harmonize-capture",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(self.startup_timeout_seconds):
            error = self._last_error
            self.close()
            detail = f": {error}" if error is not None else ""
            raise CaptureReadError(
                f"Capture source {self.source_description} did not produce a "
                f"frame within {self.startup_timeout_seconds:g} seconds{detail}"
            )

    def _capture_loop(self) -> None:
        backoff = self.reconnect_initial_seconds
        while not self._stop_requested.is_set():
            try:
                self._open_handle()
                log_event(
                    self._logger,
                    logging.INFO,
                    "capture_opened",
                    source=self.source_description,
                )
                backoff = self.reconnect_initial_seconds
                while not self._stop_requested.is_set():
                    if self._reset_requested.is_set():
                        self._reset_requested.clear()
                        raise CaptureReadError("capture reset requested")
                    assert self._capture is not None
                    ok, frame = self._capture.read()
                    if self._stop_requested.is_set():
                        break
                    if not ok or frame is None:
                        raise CaptureReadError(
                            f"Unable to read from {self.source_description}"
                        )
                    with self._condition:
                        self._latest_frame = frame
                        self._generation += 1
                        self.last_frame_monotonic = time.monotonic()
                        self._last_error = None
                        self._ready.set()
                        self._condition.notify_all()
            except Exception as exc:
                self._last_error = exc
                log_event(
                    self._logger,
                    logging.WARNING,
                    "capture_recovering",
                    source=self.source_description,
                    error=str(exc),
                    retry_seconds=backoff,
                )
            finally:
                self._release_handle()

            if self._stop_requested.wait(backoff):
                break
            backoff = min(backoff * 2, self.reconnect_max_seconds)

        with self._condition:
            self._condition.notify_all()

    def read(self):
        deadline = time.monotonic() + self.read_timeout_seconds
        with self._condition:
            while (
                self._generation <= self._consumed_generation
                and not self._stop_requested.is_set()
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    detail = (
                        f": {self._last_error}"
                        if self._last_error is not None
                        else ""
                    )
                    raise CaptureReadError(
                        f"No new frame from {self.source_description} within "
                        f"{self.read_timeout_seconds:g} seconds{detail}"
                    )
                self._condition.wait(remaining)
            if self._generation <= self._consumed_generation:
                raise CaptureReadError("Capture stopped before a new frame arrived")
            self._consumed_generation = self._generation
            frame = self._latest_frame
        return frame.copy()

    def request_reset(self) -> None:
        self._reset_requested.set()

    def close(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            self._release_handle()
            return
        self._stop_requested.set()
        self._reset_requested.set()
        # OpenCV backends generally unblock read when the handle is released.
        self._release_handle()
        with self._condition:
            self._condition.notify_all()
        thread.join(self.shutdown_timeout_seconds)
        if thread.is_alive():
            raise HarmonizeError(
                "Capture worker did not stop within "
                f"{self.shutdown_timeout_seconds:g} seconds"
            )
        log_event(
            self._logger,
            logging.INFO,
            "capture_closed",
            source=self.source_description,
        )
