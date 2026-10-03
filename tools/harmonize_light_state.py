#!/usr/bin/env python3
"""Inspect or explicitly resolve a pending Harmonize light-state journal."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harmonize_config import ConfigError, load_config, load_credentials
from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import HueBridge, discover_bridge
from harmonize_core.light_state import HueLightStateManager, LightStateJournal


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("action", choices=("inspect", "restore", "off", "discard"))
    result.add_argument("--config", type=Path, default=Path("harmonize.toml"))
    result.add_argument(
        "--confirm-area",
        help="exact configured area name required for restore, off, or discard",
    )
    result.add_argument(
        "--allow-stale",
        action="store_true",
        help="allow explicit restore/off beyond light_state.stale_after_seconds",
    )
    return result


def _summary(snapshot, now):
    return {
        "area": snapshot.area_name,
        "area_id": snapshot.area_id,
        "captured_at": datetime.fromtimestamp(
            snapshot.captured_at, timezone.utc
        ).isoformat(),
        "age_seconds": round(max(0.0, now - snapshot.captured_at), 3),
        "session_id": snapshot.session_id,
        "lights": [
            {
                "id": light.resource_id,
                "name": light.name,
                "on": light.on,
                "brightness": light.brightness,
                "color_xy": light.color_xy,
                "mirek": light.mirek,
            }
            for light in snapshot.lights
        ],
    }


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    bridge = None
    try:
        config = load_config(args.config, unattended=True)
        journal = LightStateJournal(config.light_state.journal_file)
        snapshot = journal.load()
        now = time.time()
        if args.action == "inspect":
            print(json.dumps(_summary(snapshot, now), indent=2, sort_keys=True))
            return 0
        configured_area = config.hue.entertainment_area
        if args.confirm_area != configured_area or snapshot.area_name != configured_area:
            raise HarmonizeError(
                f'--confirm-area must exactly match configured area "{configured_area}"'
            )
        age = max(0.0, now - snapshot.captured_at)
        if (
            args.action in {"restore", "off"}
            and age > config.light_state.stale_after_seconds
            and not args.allow_stale
        ):
            raise HarmonizeError(
                f"Journal is stale ({age:.1f}s); inspect it and pass --allow-stale "
                "only if applying it is still safe"
            )
        if args.action == "discard":
            journal.remove(snapshot.session_id)
            print(json.dumps({"ok": True, "action": "discard", "area": configured_area}))
            return 0

        credentials = load_credentials(config.hue.credentials_file, unattended=True)
        bridge = HueBridge(
            config.hue.bridge_ip or discover_bridge(), credentials.username
        )
        area = bridge.resolve_name(configured_area)
        if area.resource_id != snapshot.area_id:
            raise HarmonizeError(
                "Configured Entertainment area resource changed; refusing recovery"
            )
        if set(area.light_ids) != {light.resource_id for light in snapshot.lights}:
            raise HarmonizeError(
                "Configured Entertainment area light membership changed; refusing recovery"
            )
        manager = HueLightStateManager(
            hue=bridge,
            area=area,
            behavior=args.action,
            journal=journal,
            stale_after_seconds=config.light_state.stale_after_seconds,
            restore_attempts=config.light_state.restore_attempts,
            retry_seconds=config.light_state.retry_seconds,
        )
        manager.apply(snapshot, behavior=args.action)
        print(json.dumps({"ok": True, "action": args.action, "area": configured_area}))
        return 0
    except (ConfigError, HarmonizeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if bridge is not None:
            bridge.close()


if __name__ == "__main__":
    raise SystemExit(run())
