#!/usr/bin/env python3
"""Read-only bridge plus local capture/packet preflight for Milestone 3."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harmonize_config import ConfigError, load_config, load_credentials
from harmonize_core.analysis import FrameAnalyzer
from harmonize_core.capture import CaptureSource
from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import HueBridge, discover_bridge, resolve_area_name
from harmonize_core.protocol import HueStreamPacketBuilder


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve Hue read-only, capture one local frame, and build one "
            "unsent HueStream packet"
        )
    )
    parser.add_argument(
        "--config", type=Path, default=Path("harmonize.toml")
    )
    parser.add_argument("--bridge-ip")
    args = parser.parse_args()

    bridge = None
    capture = None
    try:
        config = load_config(args.config, unattended=True)
        credentials = load_credentials(
            config.hue.credentials_file, unattended=True
        )
        bridge_ip = args.bridge_ip or config.hue.bridge_ip or discover_bridge()
        bridge = HueBridge(bridge_ip, credentials.username)
        resources = bridge.list_entertainment_resources()
        area_name = config.hue.entertainment_area
        assert area_name is not None
        area = resolve_area_name(resources, area_name)

        capture = CaptureSource(
            device_index=config.capture.device_index,
            backend=config.capture.backend,
            stream_source=config.capture.stream_source,
        )
        capture.open()
        frame = capture.read()
        height, width = frame.shape[:2]
        analyzer = FrameAnalyzer(
            channels=area.channels,
            width=width,
            height=height,
            brightness_adjustment=config.ambilight.brightness_adjustment,
            breadth=config.ambilight.sample_breadth,
            single_light=(
                config.ambilight.single_light and len(area.channels) == 1
            ),
        )
        packet = HueStreamPacketBuilder(area.resource_id).build(
            analyzer.colors(frame)
        )
    except (ConfigError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if capture is not None:
            capture.close()
        if bridge is not None:
            bridge.close()

    print("Milestone 3 preflight succeeded.")
    print(f'Configured area: "{area.name}" ({len(area.channels)} channels)')
    print(f"Captured frame: {width}x{height}")
    print(f"Built unsent binary HueStream packet: {len(packet)} bytes")
    print("No Entertainment action or DTLS connection was attempted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
