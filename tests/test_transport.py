import io
import unittest

from harmonize_core.transport import OpenSslDtlsTransport


class FakeProcess:
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout):
        return 0


class TransportTests(unittest.TestCase):
    def test_send_writes_bytes_without_text_conversion(self):
        transport = OpenSslDtlsTransport(
            bridge_ip="192.0.2.1",
            application_id="app",
            client_key="hidden",
        )
        process = FakeProcess()
        transport._process = process
        packet = bytes((0, 127, 128, 255))
        transport.send(packet)
        self.assertEqual(process.stdin.getvalue(), packet)


if __name__ == "__main__":
    unittest.main()
