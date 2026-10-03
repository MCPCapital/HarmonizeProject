"""Legacy-compatible frame sampling without shared mutable state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import cv2
import numpy as np

from .hue import Channel

Rgb = tuple[int, int, int]
Bounds = tuple[int, int, int, int]


def adjust_brightness(frame: np.ndarray, value: int) -> np.ndarray:
    """Preserve the v2.4.2 HSV-value adjustment exactly."""

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue, saturation, brightness = cv2.split(hsv)
    limit = 255 - value
    brightness[brightness > limit] = 255
    brightness[brightness <= limit] += value
    return cv2.cvtColor(
        cv2.merge((hue, saturation, brightness)), cv2.COLOR_HSV2BGR
    )


def sample_bounds(
    channels: tuple[Channel, ...], width: int, height: int, breadth: float
) -> dict[int, Bounds]:
    """Map Hue x/z positions to the same edge samples used by v2.4.2."""

    distance = int(breadth * (width / 2 + height / 2))
    result: dict[int, Bounds] = {}
    for channel in channels:
        pixel_x = int((channel.x + 1) * width // 2)
        pixel_y = int((-channel.z + 1) * height // 2)
        result[channel.channel_id] = (
            max(0, pixel_y - distance),
            min(height, pixel_y + distance),
            max(0, pixel_x - distance),
            min(width, pixel_x + distance),
        )
    return result


@dataclass
class FrameAnalyzer:
    channels: tuple[Channel, ...]
    width: int
    height: int
    brightness_adjustment: int
    breadth: float
    single_light: bool
    color_processing_mode: str = "legacy_hsv"

    def __post_init__(self) -> None:
        self._bounds = sample_bounds(
            self.channels, self.width, self.height, self.breadth
        )

    def colors(self, bgr_frame: np.ndarray) -> dict[int, Rgb]:
        if self.single_light and len(self.channels) == 1:
            # v2.4.2 intentionally bypassed brightness adjustment in this mode.
            blue, green, red, _ = cv2.mean(bgr_frame)
            return {1: (int(red), int(green), int(blue))}

        if self.color_processing_mode == "direct_rgb":
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        else:
            adjusted = adjust_brightness(bgr_frame, self.brightness_adjustment)
            rgb_frame = cv2.cvtColor(adjusted, cv2.COLOR_BGR2RGB)
        colors: dict[int, Rgb] = {}
        for channel_id, (top, bottom, left, right) in self._bounds.items():
            area = rgb_frame[top:bottom, left:right, :]
            if area.size == 0:
                colors[channel_id] = (0, 0, 0)
                continue
            red, green, blue, _ = cv2.mean(area)
            colors[channel_id] = (int(red), int(green), int(blue))
        return colors


def legacy_rgb_bytes(colors: Mapping[int, Rgb]) -> dict[int, bytes]:
    """Encode the legacy 8-bit values as repeated-byte 16-bit RGB."""

    result: dict[int, bytes] = {}
    for channel_id, (red, green, blue) in colors.items():
        result[channel_id] = bytes(
            (
                red // 2,
                red // 2,
                green // 2,
                green // 2,
                blue // 2,
                blue // 2,
            )
        )
    return result
