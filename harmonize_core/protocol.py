"""Binary-safe Hue Entertainment packet construction."""

from __future__ import annotations

from collections.abc import Mapping

from .analysis import Rgb, legacy_rgb_bytes
from .errors import HarmonizeError


class HueStreamPacketBuilder:
    HEADER = b"HueStream" + bytes((2, 0, 0, 0, 0, 0, 0))

    def __init__(self, entertainment_id: str):
        encoded_id = entertainment_id.encode("ascii")
        if len(encoded_id) != 36:
            raise HarmonizeError(
                "Hue Entertainment configuration ID must be a 36-character UUID"
            )
        self._prefix = self.HEADER + encoded_id

    def build(self, colors: Mapping[int, Rgb]) -> bytes:
        message = bytearray(self._prefix)
        for channel_id, encoded_rgb in legacy_rgb_bytes(colors).items():
            if not 0 <= channel_id <= 255:
                raise HarmonizeError(
                    f"Hue channel ID {channel_id} is outside the byte range"
                )
            message.append(channel_id)
            message.extend(encoded_rgb)
        return bytes(message)
