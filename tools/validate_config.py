#!/usr/bin/env python3
"""Validate Harmonize configuration without contacting devices or the network."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harmonize_config import ConfigError, load_config, load_credentials


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Harmonize TOML offline; this command never contacts Hue."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("harmonize.toml"),
        help="configuration file (default: harmonize.toml)",
    )
    parser.add_argument(
        "--mode",
        choices=("unattended", "manual"),
        default="unattended",
        help="validation mode (default: unattended)",
    )
    parser.add_argument(
        "--check-credentials",
        action="store_true",
        help="validate credential shape and permissions without printing secrets",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    unattended = args.mode == "unattended"
    try:
        config = load_config(args.config, unattended=unattended)
        warnings: tuple[str, ...] = ()
        if args.check_credentials:
            credentials = load_credentials(
                config.hue.credentials_file, unattended=unattended
            )
            warnings = credentials.warnings
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    area = config.hue.entertainment_area or "<interactive selection>"
    print(f"configuration valid ({args.mode} mode)")
    print(f"Hue Entertainment area: {area}")
    capture_target = config.capture.device_path or config.capture.device_index
    print(
        "capture backend/device: "
        f"{config.capture.backend}/{capture_target}"
    )
    print(f"control provider: {config.control.provider}")
    if args.check_credentials:
        print("Hue credentials: valid shape; values hidden")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
