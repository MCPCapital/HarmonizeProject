#!/usr/bin/env python3
"""Send an ON, OFF, or STATUS command to the local Harmonize daemon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harmonize_config import ConfigError, load_config
from harmonize_core.errors import HarmonizeError
from harmonize_core.local_control import send_local_command


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("command", choices=("ON", "OFF", "STATUS"), type=str.upper)
    result.add_argument("--config", type=Path, default=Path("harmonize.toml"))
    result.add_argument("--socket", type=Path)
    result.add_argument(
        "--wait-seconds",
        type=float,
        default=30.0,
        help="wait for ON=STREAMING or OFF=IDLE (default: 30)",
    )
    result.add_argument(
        "--no-wait",
        action="store_true",
        help="return after the daemon accepts ON or OFF",
    )
    return result


def _wait_for_target(
    socket_path: Path,
    command: str,
    timeout_seconds: float,
) -> dict[str, object]:
    target = "STREAMING" if command == "ON" else "IDLE"
    deadline = time.monotonic() + timeout_seconds
    latest = None
    while time.monotonic() < deadline:
        response = send_local_command(socket_path, "STATUS")
        latest = response.get("status")
        if isinstance(latest, dict) and latest.get("actual_state") == target:
            return {"ok": True, "command": command, "status": latest}
        time.sleep(0.1)
    actual = latest.get("actual_state") if isinstance(latest, dict) else "unknown"
    error = latest.get("error") if isinstance(latest, dict) else None
    detail = f"; error: {error}" if error else ""
    raise HarmonizeError(
        f"{command} did not reach {target} within {timeout_seconds:g} seconds "
        f"(actual: {actual}){detail}"
    )


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.wait_seconds <= 0:
            raise ConfigError("--wait-seconds must be greater than zero")
        socket_path = args.socket
        if socket_path is None:
            socket_path = load_config(
                args.config, unattended=True
            ).control.socket_path
        response = send_local_command(socket_path, args.command)
        if response.get("ok") is not True:
            print(json.dumps(response, indent=2, sort_keys=True))
            return 2
        if args.command != "STATUS" and not args.no_wait:
            response = _wait_for_target(
                socket_path, args.command, args.wait_seconds
            )
        print(json.dumps(response, indent=2, sort_keys=True))
        return 0
    except (ConfigError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
