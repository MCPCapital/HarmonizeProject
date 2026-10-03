"""Authenticated-by-filesystem local ON/OFF/STATUS command provider."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import threading
import time
from typing import Callable

from .errors import HarmonizeError
from .state_machine import DesiredState, ProviderPolicy


class LocalCommandProvider:
    name = "local"

    def __init__(
        self,
        socket_path: str | Path,
        *,
        status: Callable[[], dict[str, object]],
        clock: Callable[[], float] = time.monotonic,
    ):
        self.socket_path = Path(socket_path)
        self.status = status
        self.clock = clock
        self.policy = ProviderPolicy(priority=100, automatic=False)
        self._publish = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _prepare_path(self) -> None:
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.socket_path.exists() and not self.socket_path.is_symlink():
            return
        metadata = self.socket_path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise HarmonizeError(
                f"Control socket path exists and is not a socket: {self.socket_path}"
            )
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(self.socket_path))
        except (ConnectionRefusedError, FileNotFoundError):
            self.socket_path.unlink(missing_ok=True)
        except OSError as exc:
            raise HarmonizeError(
                f"Cannot validate existing control socket {self.socket_path}: {exc}"
            ) from exc
        else:
            raise HarmonizeError(
                f"Another Harmonize daemon is using {self.socket_path}"
            )
        finally:
            probe.close()

    def start(self, publish) -> None:
        self._prepare_path()
        self._publish = publish
        self._stop.clear()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(4)
            server.settimeout(0.2)
        except Exception:
            server.close()
            self.socket_path.unlink(missing_ok=True)
            raise
        self._server = server
        self._thread = threading.Thread(
            target=self._serve, name="harmonize-local-control", daemon=True
        )
        self._thread.start()

    def _response(self, command: str) -> dict[str, object]:
        normalized = command.strip().upper()
        if normalized in {"ON", "OFF"}:
            assert self._publish is not None
            self._publish(
                DesiredState(normalized == "ON", self.name, self.clock()),
                self.policy,
            )
            return {"ok": True, "command": normalized}
        if normalized == "STATUS":
            return {"ok": True, "status": self.status()}
        return {
            "ok": False,
            "error": "command must be ON, OFF, or STATUS",
        }

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(1.0)
                try:
                    request = connection.recv(1024)
                    if len(request) >= 1024:
                        response = {"ok": False, "error": "command is too long"}
                    else:
                        response = self._response(
                            request.decode("ascii", errors="strict")
                        )
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                try:
                    connection.sendall(
                        json.dumps(response, separators=(",", ":")).encode("utf-8")
                        + b"\n"
                    )
                except OSError:
                    pass

    def close(self) -> None:
        self._stop.set()
        server, self._server = self._server, None
        if server is not None:
            server.close()
        if self._thread is not None:
            self._thread.join(1.0)
            self._thread = None
        self.socket_path.unlink(missing_ok=True)


def send_local_command(
    socket_path: str | Path,
    command: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object]:
    """Send one bounded local command and decode its JSON response."""

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout_seconds)
        client.connect(str(socket_path))
        client.sendall(command.upper().encode("ascii") + b"\n")
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 65536:
                raise HarmonizeError("Control response exceeded 65536 bytes")
    except (OSError, UnicodeError) as exc:
        raise HarmonizeError(
            f"Cannot send {command.upper()} to {socket_path}: {exc}"
        ) from exc
    finally:
        client.close()
    try:
        document = json.loads(bytes(response).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HarmonizeError("Control socket returned invalid JSON") from exc
    if not isinstance(document, dict):
        raise HarmonizeError("Control socket returned a non-object response")
    return document
