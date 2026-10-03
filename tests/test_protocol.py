import unittest

from harmonize_core.errors import HarmonizeError
from harmonize_core.protocol import HueStreamPacketBuilder


class PacketTests(unittest.TestCase):
    UUID = "12345678-1234-1234-1234-123456789abc"

    def test_packet_layout_is_deterministic_and_binary_safe(self):
        packet = HueStreamPacketBuilder(self.UUID).build(
            {0: (255, 128, 2), 2: (4, 6, 8)}
        )
        expected = (
            b"HueStream"
            + bytes((2, 0, 0, 0, 0, 0, 0))
            + self.UUID.encode("ascii")
            + bytes((0, 127, 127, 64, 64, 1, 1))
            + bytes((2, 2, 2, 3, 3, 4, 4))
        )
        self.assertEqual(packet, expected)
        self.assertEqual(len(packet), 66)

    def test_invalid_configuration_id_is_rejected(self):
        with self.assertRaisesRegex(HarmonizeError, "36-character UUID"):
            HueStreamPacketBuilder("too-short")

    def test_channel_id_must_fit_one_byte(self):
        builder = HueStreamPacketBuilder(self.UUID)
        with self.assertRaisesRegex(HarmonizeError, "outside the byte range"):
            builder.build({256: (1, 2, 3)})


if __name__ == "__main__":
    unittest.main()
