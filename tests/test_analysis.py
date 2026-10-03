import unittest

import cv2
import numpy as np

from harmonize_core.analysis import (
    FrameAnalyzer,
    adjust_brightness,
    legacy_rgb_bytes,
    sample_bounds,
)
from harmonize_core.hue import Channel


class AnalysisTests(unittest.TestCase):
    def test_position_mapping_uses_hue_x_and_z_axes(self):
        channels = (
            Channel(channel_id=0, x=-1.0, y=0.4, z=1.0),
            Channel(channel_id=1, x=1.0, y=-0.7, z=-1.0),
        )
        self.assertEqual(
            sample_bounds(channels, 100, 50, 0.10),
            {
                0: (0, 7, 0, 7),
                1: (43, 50, 93, 100),
            },
        )

    def test_brightness_matches_legacy_hsv_value_adjustment(self):
        frame = np.array([[[10, 20, 30], [250, 250, 250]]], dtype=np.uint8)
        adjusted = adjust_brightness(frame, 30)
        hsv = cv2.cvtColor(adjusted, cv2.COLOR_BGR2HSV)
        self.assertEqual(int(hsv[0, 0, 2]), 60)
        self.assertEqual(int(hsv[0, 1, 2]), 255)

    def test_frame_sampling_returns_rgb(self):
        channel = Channel(channel_id=3, x=0.0, y=0.0, z=0.0)
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        frame[:, :] = (20, 40, 80)
        analyzer = FrameAnalyzer(
            channels=(channel,),
            width=4,
            height=4,
            brightness_adjustment=0,
            breadth=1.0,
            single_light=False,
        )
        self.assertEqual(analyzer.colors(frame), {3: (80, 40, 20)})

    def test_single_light_preserves_legacy_brightness_bypass_and_channel_one(self):
        channel = Channel(channel_id=9, x=0.0, y=0.0, z=0.0)
        frame = np.full((2, 2, 3), (10, 20, 30), dtype=np.uint8)
        analyzer = FrameAnalyzer(
            channels=(channel,),
            width=2,
            height=2,
            brightness_adjustment=100,
            breadth=0.15,
            single_light=True,
        )
        self.assertEqual(analyzer.colors(frame), {1: (30, 20, 10)})

    def test_legacy_rgb_encoding_repeats_halved_bytes(self):
        self.assertEqual(
            legacy_rgb_bytes({7: (255, 128, 1)})[7],
            bytes((127, 127, 64, 64, 0, 0)),
        )


if __name__ == "__main__":
    unittest.main()
