#!/usr/bin/env python3
# Wait until the local Harmonize control socket answers STATUS.

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harmonize_core.errors import HarmonizeError
from harmonize_core.local_control import send_local_command


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--socket", type=Path, required=True)
    result.add_argument("--timeout-seconds", type=float, default=20.0)
    return result


def wait_for_control(
    socket_path: Path,
    timeout_seconds: float,
    *,
    clock=time.monotonic,
    sleeper=time.sleep,
) -> dict[str, object]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    deadline = clock() + timeout_seconds
    last_error: Exception | None = None
    while clock() < deadline:
        try:
            response = send_local_command(socket_path, "STATUS")
            if response.get("ok") is True:
                return response
            last_error = HarmonizeError("STATUS returned a non-success response")
        except (OSError, HarmonizeError) as exc:
            last_error = exc
        sleeper(0.1)
    raise HarmonizeError(
        f"Harmonize control socket was not ready within {timeout_seconds:g} "
        f"seconds: {last_error}"
    )


def main() -> int:
    args = parser().parse_args()
    try:
        wait_for_control(args.socket, args.timeout_seconds)
    except (ValueError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
