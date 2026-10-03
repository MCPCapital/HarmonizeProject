#!/usr/bin/env python3
"""Expose the fixed Harmonize local-control commands over trusted-LAN HTTP."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harmonize_core.errors import HarmonizeError
from harmonize_core.local_control import send_local_command


DEFAULT_SOCKET = Path("/run/harmonize/harmonize.sock")
TARGETS = {
    "/?harmonize=on": "ON",
    "/?harmonize=off": "OFF",
    "/?harmonize=status": "STATUS",
}
CommandSender = Callable[[str | Path, str], dict[str, object]]


def dispatch(
    target: str,
    socket_path: str | Path,
    *,
    sender: CommandSender = send_local_command,
) -> tuple[int, dict[str, object]]:
    """Map one exact request target to one bounded local-control operation."""

    command = TARGETS.get(target)
    if command is None:
        return 400, {"error": "harmonize must be on, off, or status"}

    try:
        response = sender(socket_path, command)
    except HarmonizeError:
        return 503, {"error": "Harmonize is unavailable"}

    if response.get("ok") is not True:
        return 502, {"error": "Harmonize rejected the command"}

    if command == "STATUS":
        status = response.get("status")
        state = status.get("actual_state") if isinstance(status, dict) else None
        if not isinstance(state, str):
            return 502, {"error": "Harmonize returned an invalid status"}
        return 200, {"state": state}

    return 200, {"command": command, "state": "accepted"}


class HarmonizeHTTPServer(HTTPServer):
    def __init__(self, address: tuple[str, int], socket_path: Path):
        super().__init__(address, HarmonizeRequestHandler)
        self.socket_path = socket_path

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(3.0)
        return request, address


class HarmonizeRequestHandler(BaseHTTPRequestHandler):
    server: HarmonizeHTTPServer

    def _send_json(self, status: int, document: dict[str, object]) -> None:
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        status, document = dispatch(self.path, self.server.socket_path)
        self._send_json(status, document)

    def _method_not_allowed(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--bind", default="0.0.0.0")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--socket", type=Path, default=DEFAULT_SOCKET)
    return result


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("ERROR: --port must be between 1 and 65535", file=sys.stderr)
        return 2
    try:
        server = HarmonizeHTTPServer((args.bind, args.port), args.socket)
    except OSError as exc:
        print(f"ERROR: cannot listen on {args.bind}:{args.port}: {exc}", file=sys.stderr)
        return 2
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
