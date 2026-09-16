import threading
import time
import unittest

import numpy as np

from harmonize_core.capture import CaptureSource


class FakeCapture:
    def __init__(self, read_ok=True):
        self.read_ok = read_ok
        self.released = False

    def isOpened(self):
        return True

    def set(self, key, value):
        return True

    def get(self, key):
        return {
            3: 3,
            4: 2,
            5: 60,
            6: 1196444237,
            38: 1,
        }.get(key, 0)

    def getBackendName(self):
        return "FAKE"

    def read(self):
        time.sleep(0.001)
        if self.released or not self.read_ok:
            return False, None
        return True, np.zeros((2, 3, 3), dtype=np.uint8)

    def release(self):
        self.released = True


class FakeCv2:
    CAP_GSTREAMER = 1800
    CAP_V4L2 = 200
    CAP_ANY = 0
    CAP_PROP_BUFFERSIZE = 38
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    CAP_PROP_FOURCC = 6

    def __init__(self, read_results=None):
        self.calls = []
        self.captures = []
        self.read_results = list(read_results or [])

    def VideoCapture(self, *args):
        self.calls.append(args)
        read_ok = self.read_results.pop(0) if self.read_results else True
        capture = FakeCapture(read_ok=read_ok)
        self.captures.append(capture)
        return capture


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class CaptureTests(unittest.TestCase):
    def make_source(self, fake_cv2, **kwargs):
        return CaptureSource(
            cv2_module=fake_cv2,
            startup_timeout_seconds=1.0,
            read_timeout_seconds=0.1,
            reconnect_initial_seconds=0.01,
            reconnect_max_seconds=0.02,
            shutdown_timeout_seconds=0.5,
            **kwargs,
        )

    def test_file_reset_preserves_original_source(self):
        fake_cv2 = FakeCv2()
        source = self.make_source(fake_cv2, stream_source="sample.mp4")
        source.open()
        source.request_reset()
        self.assertTrue(wait_for(lambda: len(fake_cv2.calls) >= 2))
        source.close()
        self.assertTrue(all(call == ("sample.mp4",) for call in fake_cv2.calls))
        self.assertTrue(fake_cv2.captures[0].released)

    def test_device_path_reset_preserves_stable_path_and_backend(self):
        fake_cv2 = FakeCv2()
        source = self.make_source(
            fake_cv2,
            device_path="/dev/v4l/by-id/capture-video-index0",
            backend="v4l2",
        )
        source.open()
        source.request_reset()
        self.assertTrue(wait_for(lambda: len(fake_cv2.calls) >= 2))
        source.close()
        self.assertTrue(
            all(
                call == ("/dev/v4l/by-id/capture-video-index0", 200)
                for call in fake_cv2.calls
            )
        )

    def test_device_reset_preserves_index_and_backend(self):
        fake_cv2 = FakeCv2()
        source = self.make_source(
            fake_cv2, device_index=4, backend="v4l2"
        )
        source.open()
        source.request_reset()
        self.assertTrue(wait_for(lambda: len(fake_cv2.calls) >= 2))
        source.close()
        self.assertTrue(all(call == (4, 200) for call in fake_cv2.calls))

    def test_failed_read_reopens_with_backoff_and_recovers(self):
        fake_cv2 = FakeCv2(read_results=[False, True])
        source = self.make_source(fake_cv2, device_index=0)
        source.open()
        frame = source.read()
        self.assertEqual(frame.shape, (2, 3, 3))
        self.assertGreaterEqual(len(fake_cv2.calls), 2)
        source.close()

    def test_sample_reports_age_generation_and_replaced_frames(self):
        fake_cv2 = FakeCv2()
        source = self.make_source(fake_cv2, device_index=0)
        source.open()
        first = source.read_sample()
        self.assertEqual(first.frame.shape, (2, 3, 3))
        self.assertGreater(first.captured_monotonic, 0)
        self.assertGreaterEqual(first.generation, 1)
        self.assertGreaterEqual(first.replaced_frames, 0)
        self.assertTrue(wait_for(lambda: source._generation >= first.generation + 2))
        second = source.read_sample()
        self.assertGreaterEqual(second.replaced_frames, 1)
        timing = source.timing_snapshot()
        self.assertIsNotNone(timing)
        self.assertGreater(timing["samples"], 0)
        self.assertGreater(timing["mean_ms"], 0)
        source.close()

    def test_close_unblocks_worker_and_is_bounded(self):
        fake_cv2 = FakeCv2()
        source = self.make_source(fake_cv2, device_index=0)
        source.open()
        started = time.monotonic()
        source.close()
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
