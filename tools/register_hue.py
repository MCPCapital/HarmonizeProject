#!/usr/bin/env python3
"""Explicitly pair Harmonize with a locally discovered Hue bridge."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Callable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import discover_bridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pair with a Hue bridge and create a private client.json"
    )
    parser.add_argument(
        "-i", "--bridge-ip", help="use this bridge instead of local mDNS discovery"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("client.json"),
        help="credential file to create (default: client.json)",
    )
    return parser


def _credentials_from_response(response: requests.Response) -> dict[str, str]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HarmonizeError("Hue returned malformed registration data") from exc
    if (
        not isinstance(payload, list)
        or not payload
        or not isinstance(payload[0], dict)
    ):
        raise HarmonizeError("Hue returned malformed registration data")
    result = payload[0]
    success = result.get("success")
    if not isinstance(success, dict):
        error = result.get("error")
        description = error.get("description") if isinstance(error, dict) else None
        raise HarmonizeError(
            str(description)
            if description
            else "Hue bridge registration was not accepted"
        )
    username = success.get("username")
    clientkey = success.get("clientkey")
    if not isinstance(username, str) or not username:
        raise HarmonizeError("Hue registration response has no username")
    if not isinstance(clientkey, str) or not clientkey:
        raise HarmonizeError("Hue registration response has no client key")
    return {"username": username, "clientkey": clientkey}


def _write_credentials(path: Path, credentials: dict[str, str]) -> None:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            json.dump(credentials, output)
            output.write("\n")
        path.chmod(0o600)
    except FileExistsError as exc:
        raise HarmonizeError(
            f"Refusing to overwrite existing credential file: {path}"
        ) from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise HarmonizeError(f"Cannot create Hue credential file {path}: {exc}") from exc


def run(
    argv: list[str] | None = None,
    *,
    discover_fn: Callable[[], str] = discover_bridge,
    post_fn: Callable[..., requests.Response] = requests.post,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.output.exists():
            raise HarmonizeError(
                f"Refusing to overwrite existing credential file: {args.output}"
            )
        bridge_ip = args.bridge_ip or discover_fn()
        print(f"Using Hue bridge at {bridge_ip}.")
        print("Press the large link button on the bridge, then press Enter.")
        input()
        try:
            response = post_fn(
                f"http://{bridge_ip}/api",
                json={
                    "devicetype": "harmonize-modernized",
                    "generateclientkey": True,
                },
                timeout=5.0,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HarmonizeError(
                f"Hue bridge registration request failed: {exc}"
            ) from exc
        _write_credentials(args.output, _credentials_from_response(response))
    except (HarmonizeError, EOFError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Created private Hue credentials at {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
