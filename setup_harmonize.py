#!/usr/bin/env python3
"""Guided, explicit first-time and reconfiguration setup for Harmonize."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time
import tomllib
from typing import Callable

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harmonize_config import (
    ConfigError,
    HarmonizeConfig,
    load_config,
    load_credentials,
)
from harmonize_core.errors import HarmonizeError
from harmonize_core.hue import DiscoveredBridge, HueBridge, discover_bridges


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover, pair, and configure Harmonize interactively"
    )
    parser.add_argument("-i", "--bridge-ip", help="manual bridge-IP override")
    parser.add_argument("-b", "--bridge-id", help="stable 16-digit Hue bridge ID")
    parser.add_argument("--area", help="exact Entertainment-area name")
    parser.add_argument("--config", type=Path, default=Path("harmonize.toml"))
    parser.add_argument("--credentials", type=Path)
    parser.add_argument(
        "--example",
        type=Path,
        default=PROJECT_ROOT / "harmonize.example.toml",
        help="template used when creating a new configuration",
    )
    parser.add_argument("--discovery-timeout", type=float, default=3.0)
    parser.add_argument("--pairing-timeout", type=float, default=60.0)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="update an existing configuration without confirmation",
    )
    return parser


def _choose_number(
    prompt: str,
    count: int,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> int:
    while True:
        try:
            selected = input_fn(prompt).strip()
        except EOFError as exc:
            raise HarmonizeError(
                "Setup input ended before a selection was made"
            ) from exc
        try:
            index = int(selected)
        except ValueError:
            output_fn(f"Enter a number from 1 to {count}.")
            continue
        if 1 <= index <= count:
            return index - 1
        output_fn(f"Enter a number from 1 to {count}.")


def _select_bridge(
    bridges: tuple[DiscoveredBridge, ...],
    *,
    bridge_ip: str | None,
    bridge_id: str | None,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> DiscoveredBridge:
    normalized_id = bridge_id.lower() if bridge_id is not None else None
    if bridge_ip is not None:
        matches = [bridge for bridge in bridges if bridge.address == bridge_ip]
        if matches:
            selected = matches[0]
            if normalized_id is not None and selected.bridge_id != normalized_id:
                raise HarmonizeError(
                    "--bridge-ip and --bridge-id identify different bridges"
                )
            return selected
        return DiscoveredBridge(normalized_id or "", bridge_ip, None, "Manual bridge")
    if normalized_id is not None:
        matches = [bridge for bridge in bridges if bridge.bridge_id == normalized_id]
        if not matches:
            raise HarmonizeError(
                f"Hue bridge {bridge_id} was not found by local mDNS; "
                "use -i as fallback"
            )
        return matches[0]
    if not bridges:
        raise HarmonizeError(
            "No Hue bridges found by local mDNS; retry with -i BRIDGE_IP"
        )
    if len(bridges) == 1:
        return bridges[0]

    output_fn("Found multiple Hue Bridges:")
    for index, bridge in enumerate(bridges, start=1):
        model = f", model {bridge.model_id}" if bridge.model_id else ""
        output_fn(
            f"  [{index}] {bridge.service_name} — {bridge.address} "
            f"(ID {bridge.bridge_id}{model})"
        )
    return bridges[
        _choose_number(
            "Select a bridge: ",
            len(bridges),
            input_fn=input_fn,
            output_fn=output_fn,
        )
    ]


def _registration_result(response: requests.Response) -> dict[str, str] | None:
    try:
        payload = response.json()
    except ValueError as exc:
        raise HarmonizeError("Hue returned malformed registration data") from exc
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise HarmonizeError("Hue returned malformed registration data")
    result = payload[0]
    success = result.get("success")
    if isinstance(success, dict):
        username = success.get("username")
        clientkey = success.get("clientkey")
        if (
            isinstance(username, str)
            and username
            and isinstance(clientkey, str)
            and clientkey
        ):
            return {"username": username, "clientkey": clientkey}
        raise HarmonizeError("Hue registration response omitted required credentials")
    error = result.get("error")
    if isinstance(error, dict) and error.get("type") == 101:
        return None
    description = error.get("description") if isinstance(error, dict) else None
    raise HarmonizeError(str(description or "Hue bridge registration was not accepted"))


def _write_credentials(path: Path, credentials: dict[str, str]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
            f"Refusing to overwrite existing credentials: {path}"
        ) from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise HarmonizeError(f"Cannot create credentials at {path}: {exc}") from exc


def _pair_bridge(
    bridge_ip: str,
    credential_path: Path,
    timeout_seconds: float,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    post_fn: Callable[..., requests.Response],
    clock: Callable[[], float],
    sleep_fn: Callable[[float], None],
) -> dict[str, str]:
    output_fn("Press the large link button on the selected Hue Bridge.")
    try:
        input_fn("Press Enter after pressing the link button: ")
    except EOFError as exc:
        raise HarmonizeError("Setup input ended before pairing") from exc
    deadline = clock() + timeout_seconds
    while True:
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
        credentials = _registration_result(response)
        if credentials is not None:
            _write_credentials(credential_path, credentials)
            return credentials
        if clock() >= deadline:
            raise HarmonizeError(
                "Hue link button was not detected before pairing timed out"
            )
        sleep_fn(min(2.0, max(0.0, deadline - clock())))


def _fetch_bridge_id(
    bridge_ip: str,
    username: str,
    *,
    get_fn: Callable[..., requests.Response],
) -> str:
    try:
        response = get_fn(
            f"http://{bridge_ip}/api/{username}/config",
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HarmonizeError(
            f"Cannot read the selected Hue bridge identity: {exc}"
        ) from exc
    bridge_id = payload.get("bridgeid") if isinstance(payload, dict) else None
    if not isinstance(bridge_id, str) or re.fullmatch(
        r"[0-9A-Fa-f]{16}", bridge_id
    ) is None:
        raise HarmonizeError("Hue bridge did not report a valid stable bridge ID")
    return bridge_id.lower()


def _select_area(
    resources: list[dict[str, object]],
    *,
    area_name: str | None,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> str:
    candidates = [
        resource
        for resource in resources
        if isinstance(resource, dict) and isinstance(resource.get("name"), str)
    ]
    if not candidates:
        raise HarmonizeError(
            "No Hue Entertainment areas exist; create one in the Hue app"
        )
    if area_name is not None:
        matches = [resource for resource in candidates if resource["name"] == area_name]
        if len(matches) != 1:
            raise HarmonizeError(
                f'Entertainment area "{area_name}" was not found exactly once'
            )
        return area_name
    if len(candidates) == 1:
        return str(candidates[0]["name"])

    output_fn("Found multiple Hue Entertainment areas:")
    for index, resource in enumerate(candidates, start=1):
        channels = resource.get("channels")
        channel_count = len(channels) if isinstance(channels, list) else "unknown"
        output_fn(f'  [{index}] {resource["name"]} — {channel_count} channels')
    selected = _choose_number(
        "Select an Entertainment area: ",
        len(candidates),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return str(candidates[selected]["name"])


def _config_credentials_name(config_path: Path, credential_path: Path) -> str:
    try:
        return str(credential_path.relative_to(config_path.parent))
    except ValueError:
        return str(credential_path)


def _update_hue_table(
    text: str, *, area_name: str, credential_name: str, bridge_id: str
) -> str:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "[hue]"),
        None,
    )
    if start is None:
        raise ConfigError("Configuration template has no [hue] table")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("[")
        ),
        len(lines),
    )
    values = {
        "entertainment_area": json.dumps(area_name),
        "credentials_file": json.dumps(credential_name),
        "bridge_id": json.dumps(bridge_id),
    }
    found: set[str] = set()
    key_pattern = re.compile(
        r"^\s*#?\s*(entertainment_area|credentials_file|bridge_id)\s*="
    )
    for index in range(start + 1, end):
        match = key_pattern.match(lines[index])
        if match:
            key = match.group(1)
            if key in found:
                lines[index] = ""
                continue
            lines[index] = f"{key} = {values[key]}\n"
            found.add(key)
    missing = [key for key in values if key not in found]
    lines[start + 1:start + 1] = [f"{key} = {values[key]}\n" for key in missing]
    return "".join(lines)


def _write_config(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    previous_mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, previous_mode)
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
        raise HarmonizeError(f"Cannot write configuration {path}: {exc}") from exc


def run(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    discovery_fn: Callable[..., tuple[DiscoveredBridge, ...]] = discover_bridges,
    post_fn: Callable[..., requests.Response] = requests.post,
    get_fn: Callable[..., requests.Response] = requests.get,
    bridge_factory: Callable[[str, str], HueBridge] = HueBridge,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> int:
    args = build_parser().parse_args(argv)
    bridge = None
    try:
        if args.discovery_timeout <= 0 or args.pairing_timeout <= 0:
            raise ConfigError(
                "Discovery and pairing timeouts must be greater than zero"
            )
        if args.bridge_id is not None and re.fullmatch(
            r"[0-9A-Fa-f]{16}", args.bridge_id
        ) is None:
            raise ConfigError(
                "--bridge-id must contain exactly 16 hexadecimal characters"
            )
        config_path = args.config.expanduser().resolve()
        existing_config: HarmonizeConfig | None = None
        if config_path.exists():
            existing_config = load_config(config_path, unattended=False)
            if not args.yes:
                answer = input_fn(
                    f"Update existing configuration {config_path}? [y/N] "
                )
                if answer.strip().lower() not in {"y", "yes"}:
                    raise HarmonizeError(
                        "Configuration update cancelled; no changes were made"
                    )
        credential_path = (
            args.credentials.expanduser().resolve()
            if args.credentials is not None
            else existing_config.hue.credentials_file
            if existing_config is not None
            else (config_path.parent / "client.json").resolve()
        )

        output_fn("Discovering Hue Bridges locally by mDNS...")
        discovered = discovery_fn(timeout_seconds=args.discovery_timeout)
        selected_bridge = _select_bridge(
            discovered,
            bridge_ip=args.bridge_ip or (
                existing_config.hue.bridge_ip if existing_config is not None else None
            ),
            bridge_id=args.bridge_id or (
                existing_config.hue.bridge_id if existing_config is not None else None
            ),
            input_fn=input_fn,
            output_fn=output_fn,
        )
        output_fn(
            f"Selected {selected_bridge.service_name} at {selected_bridge.address}."
        )

        if (
            existing_config is not None
            and existing_config.hue.bridge_id is not None
            and selected_bridge.bridge_id
            and selected_bridge.bridge_id != existing_config.hue.bridge_id
            and credential_path == existing_config.hue.credentials_file
            and credential_path.exists()
        ):
            raise HarmonizeError(
                "The selected bridge differs from the credential's configured bridge; "
                "use --credentials with a new unused path to pair safely"
            )

        if credential_path.exists():
            credentials = load_credentials(credential_path, unattended=True)
            output_fn(f"Reusing existing credentials at {credential_path}.")
        else:
            credential_values = _pair_bridge(
                selected_bridge.address,
                credential_path,
                args.pairing_timeout,
                input_fn=input_fn,
                output_fn=output_fn,
                post_fn=post_fn,
                clock=clock,
                sleep_fn=sleep_fn,
            )
            credentials = load_credentials(credential_path, unattended=True)
            assert credentials.username == credential_values["username"]
            output_fn(f"Created private credentials at {credential_path}.")

        bridge_id = selected_bridge.bridge_id or _fetch_bridge_id(
            selected_bridge.address, credentials.username, get_fn=get_fn
        )
        bridge = bridge_factory(selected_bridge.address, credentials.username)
        area_name = _select_area(
            bridge.list_entertainment_resources(),
            area_name=args.area,
            input_fn=input_fn,
            output_fn=output_fn,
        )

        source = (
            config_path.read_text(encoding="utf-8")
            if config_path.exists()
            else args.example.read_text(encoding="utf-8")
        )
        updated = _update_hue_table(
            source,
            area_name=area_name,
            credential_name=_config_credentials_name(config_path, credential_path),
            bridge_id=bridge_id,
        )
        try:
            tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(
                f"Generated configuration is invalid TOML: {exc}"
            ) from exc
        _write_config(config_path, updated)
        load_config(config_path, unattended=True)
    except (ConfigError, HarmonizeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if bridge is not None:
            bridge.close()

    output_fn(f"Saved bridge ID {bridge_id} and area \"{area_name}\" in {config_path}.")
    output_fn(
        "Setup complete. Validate with: ./harmonize.py --config "
        f"{shlex.quote(str(config_path))} --check-area"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
