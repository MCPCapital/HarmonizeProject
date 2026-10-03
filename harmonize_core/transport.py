"""Binary OpenSSL DTLS transport with observable readiness."""

from __future__ import annotations

import os
import selectors
import subprocess
import time

from .errors import HarmonizeError


class OpenSslDtlsTransport:
    def __init__(
        self,
        *,
        bridge_ip: str,
        application_id: str,
        client_key: str,
        connect_timeout_seconds: float = 5.0,
        popen_factory=subprocess.Popen,
    ):
        self.bridge_ip = bridge_ip
        self.application_id = application_id
        self._client_key = client_key
        self.connect_timeout_seconds = connect_timeout_seconds
        self._popen = popen_factory
        self._process = None

    def start(self) -> None:
        if self._process is not None:
            raise HarmonizeError("DTLS transport is already started")
        command = [
            "openssl",
            "s_client",
            "-dtls1_2",
            "-brief",
            "-cipher",
            "PSK-AES128-GCM-SHA256",
            "-psk_identity",
            self.application_id,
            "-psk",
            self._client_key,
            "-connect",
            f"{self.bridge_ip}:2100",
        ]
        try:
            process = self._popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
            )
        except OSError as exc:
            raise HarmonizeError(f"Unable to start OpenSSL DTLS: {exc}") from exc
        self._process = process
        try:
            self._wait_until_ready()
        except Exception:
            self.close()
            raise

    def _wait_until_ready(self) -> None:
        assert self._process is not None
        assert self._process.stderr is not None
        deadline = time.monotonic() + self.connect_timeout_seconds
        selector = selectors.DefaultSelector()
        selector.register(self._process.stderr, selectors.EVENT_READ)
        diagnostic = bytearray()
        try:
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    raise HarmonizeError(
                        "OpenSSL DTLS exited before the connection became ready"
                    )
                remaining = max(0.0, deadline - time.monotonic())
                events = selector.select(remaining)
                if not events:
                    continue
                chunk = os.read(self._process.stderr.fileno(), 4096)
                if not chunk:
                    continue
                diagnostic.extend(chunk)
                if (
                    b"CONNECTION ESTABLISHED" in diagnostic
                    or b"Protocol version:" in diagnostic
                ):
                    return
        finally:
            selector.close()
        raise HarmonizeError(
            "Timed out waiting for the OpenSSL DTLS connection to become ready"
        )

    def send(self, packet: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise HarmonizeError("DTLS transport is not ready")
        if self._process.poll() is not None:
            raise HarmonizeError("OpenSSL DTLS exited while streaming")
        try:
            self._process.stdin.write(packet)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise HarmonizeError("OpenSSL DTLS write failed") from exc

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if process.stderr is not None:
            process.stderr.close()
