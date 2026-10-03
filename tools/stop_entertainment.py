#!/usr/bin/env python3
"""Emergency cleanup: stop only the exactly configured Entertainment area."""

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
        description="Stop only the exactly configured Hue Entertainment area"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("harmonize.toml")
    )
    parser.add_argument("--bridge-ip")
    args = parser.parse_args()

    bridge = None
    try:
        config = load_config(args.config, unattended=True)
        credentials = load_credentials(
            config.hue.credentials_file, unattended=True
        )
        bridge_ip = args.bridge_ip or config.hue.bridge_ip or discover_bridge()
        bridge = HueBridge(bridge_ip, credentials.username)
        area_name = config.hue.entertainment_area
        assert area_name is not None
        area = resolve_area_name(
            bridge.list_entertainment_resources(), area_name
        )
        if area.status == "active":
            bridge.stop_streaming(area)
            area = resolve_area_name(
                bridge.list_entertainment_resources(), area_name
            )
        if area.status != "inactive":
            raise HarmonizeError(
                f'Entertainment area "{area.name}" did not report inactive '
                f"after cleanup; current status is {area.status!r}"
            )
    except (ConfigError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if bridge is not None:
            bridge.close()

    print(f'Entertainment area "{area.name}" is inactive.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
