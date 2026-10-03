#!/usr/bin/env python3
"""Resolve a configured Hue Entertainment area without changing bridge state."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harmonize_config import ConfigError, load_config, load_credentials
from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import HueBridge, discover_bridge, resolve_area_name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Hue Entertainment-area validation"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("harmonize.toml")
    )
    parser.add_argument("--bridge-ip")
    args = parser.parse_args()

    try:
        config = load_config(args.config, unattended=True)
        credentials = load_credentials(
            config.hue.credentials_file, unattended=True
        )
        bridge_ip = args.bridge_ip or config.hue.bridge_ip or discover_bridge()
        bridge = HueBridge(bridge_ip, credentials.username)
        try:
            resources = bridge.list_entertainment_resources()
            area_name = config.hue.entertainment_area
            assert area_name is not None
            area = resolve_area_name(resources, area_name)
            unknown_name = "__Harmonize_M3_missing_area_probe__"
            try:
                resolve_area_name(resources, unknown_name)
            except HarmonizeError as expected:
                unknown_result = str(expected)
            else:
                raise HarmonizeError(
                    f'Unexpectedly found reserved test area "{unknown_name}"'
                )
        finally:
            bridge.close()
    except (ConfigError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Read-only Hue validation succeeded.")
    print(f'Configured area: "{area.name}"')
    print(f"Channel count: {len(area.channels)}")
    print(f'Entertainment status: {area.status or "<not reported>"}')
    print(f"Unknown-name behavior: {unknown_result}")
    print("No Entertainment action request was sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
