"""Offline configuration and credential validation for Harmonize.

This module deliberately performs no network discovery and never contacts Hue.
Milestone 3 will integrate it with the application runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import stat
import tomllib
from typing import Any


class ConfigError(ValueError):
    """A configuration error safe to display without exposing credentials."""


@dataclass(frozen=True)
class HueConfig:
    entertainment_area: str | None
    credentials_file: Path
    bridge_ip: str | None = None


@dataclass(frozen=True)
class CaptureConfig:
    device_index: int = 0
    device_path: Path | None = None
    backend: str = "gstreamer"
    stream_source: str | None = None


@dataclass(frozen=True)
class ControlConfig:
    provider: str = "local"
    socket_path: Path = Path("run/harmonize.sock")
    automatic_stale_seconds: float = 30.0
    automatic_enable_debounce_seconds: float = 1.0
    automatic_disable_grace_seconds: float = 5.0
    recovery_attempts: int = 3
    recovery_initial_seconds: float = 1.0


@dataclass(frozen=True)
class AmbilightConfig:
    video_wait_seconds: float = 2.0
    brightness_adjustment: int = 0
    color_processing_mode: str = "legacy_hsv"
    auto_restart_seconds: float = 0.0
    single_light: bool = False
    sample_breadth: float = 0.15
    update_interval_seconds: float = 0.05
    exception_cleanup_behavior: str = "restore"


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class LightStateConfig:
    journal_file: Path = Path("run/harmonize-light-state.json")
    stale_after_seconds: float = 300.0
    restore_attempts: int = 3
    retry_seconds: float = 0.5


@dataclass(frozen=True)
class ReliabilityConfig:
    startup_timeout_seconds: float = 10.0
    shutdown_timeout_seconds: float = 15.0
    capture_read_timeout_seconds: float = 2.0
    capture_reconnect_initial_seconds: float = 0.5
    capture_reconnect_max_seconds: float = 5.0
    transport_reconnect_attempts: int = 3
    transport_reconnect_initial_seconds: float = 0.5
    hue_status_interval_seconds: float = 10.0
    health_interval_seconds: float = 1.0
    health_file: Path | None = None


@dataclass(frozen=True)
class HarmonizeConfig:
    hue: HueConfig
    capture: CaptureConfig
    control: ControlConfig
    ambilight: AmbilightConfig
    logging: LoggingConfig
    light_state: LightStateConfig
    reliability: ReliabilityConfig
    source_file: Path


@dataclass(frozen=True)
class HueCredentials:
    username: str
    clientkey: str
    warnings: tuple[str, ...] = ()


_SECTIONS = {
    "hue",
    "capture",
    "control",
    "ambilight",
    "logging",
    "light_state",
    "reliability",
}
_KEYS = {
    "hue": {"entertainment_area", "credentials_file", "bridge_ip"},
    "capture": {"device_index", "device_path", "backend", "stream_source"},
    "control": {
        "provider",
        "socket_path",
        "automatic_stale_seconds",
        "automatic_enable_debounce_seconds",
        "automatic_disable_grace_seconds",
        "recovery_attempts",
        "recovery_initial_seconds",
    },
    "ambilight": {
        "video_wait_seconds",
        "brightness_adjustment",
        "color_processing_mode",
        "auto_restart_seconds",
        "single_light",
        "sample_breadth",
        "update_interval_seconds",
        "exception_cleanup_behavior",
    },
    "logging": {"level"},
    "light_state": {
        "journal_file",
        "stale_after_seconds",
        "restore_attempts",
        "retry_seconds",
    },
    "reliability": {
        "startup_timeout_seconds",
        "shutdown_timeout_seconds",
        "capture_read_timeout_seconds",
        "capture_reconnect_initial_seconds",
        "capture_reconnect_max_seconds",
        "transport_reconnect_attempts",
        "transport_reconnect_initial_seconds",
        "hue_status_interval_seconds",
        "health_interval_seconds",
        "health_file",
    },
}


def _table(document: dict[str, Any], name: str) -> dict[str, Any]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return value


def _reject_unknown(document: dict[str, Any]) -> None:
    unknown_sections = sorted(set(document) - _SECTIONS)
    if unknown_sections:
        raise ConfigError(
            "Unknown configuration section(s): " + ", ".join(unknown_sections)
        )
    for section in _SECTIONS:
        values = _table(document, section)
        unknown_keys = sorted(set(values) - _KEYS[section])
        if unknown_keys:
            names = ", ".join(f"{section}.{key}" for key in unknown_keys)
            raise ConfigError(f"Unknown configuration setting(s): {names}")


def _string(
    table: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    optional: bool = False,
) -> str | None:
    value = table.get(key, default)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    if value != value.strip():
        raise ConfigError(f"{key} must not begin or end with whitespace")
    return value


def _number(
    table: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigError(f"{key} must be finite")
    if result < minimum or (maximum is not None and result > maximum):
        limit = (
            f" between {minimum} and {maximum}"
            if maximum is not None
            else f" >= {minimum}"
        )
        raise ConfigError(f"{key} must be{limit}")
    return result


def _integer(
    table: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int
) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _boolean(table: dict[str, Any], key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def load_config(path: str | Path, *, unattended: bool) -> HarmonizeConfig:
    """Load and validate TOML without performing network or device access."""

    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Configuration file not found: {source}. "
            "Copy harmonize.example.toml to harmonize.toml and edit it."
        ) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read configuration file {source}: {exc}") from exc

    _reject_unknown(document)
    hue_values = _table(document, "hue")
    capture_values = _table(document, "capture")
    control_values = _table(document, "control")
    ambilight_values = _table(document, "ambilight")
    logging_values = _table(document, "logging")
    light_state_values = _table(document, "light_state")
    reliability_values = _table(document, "reliability")

    area = _string(hue_values, "entertainment_area", optional=True)
    if unattended and area is None:
        raise ConfigError(
            "hue.entertainment_area is required in unattended mode; "
            'set it to the exact Hue Entertainment area name, for example "TV area"'
        )

    credentials_name = _string(
        hue_values, "credentials_file", default="client.json"
    )
    assert credentials_name is not None
    credentials_path = Path(credentials_name).expanduser()
    if not credentials_path.is_absolute():
        credentials_path = source.parent / credentials_path

    backend = _string(capture_values, "backend", default="gstreamer")
    if backend not in {"gstreamer", "v4l2", "any"}:
        raise ConfigError("capture.backend must be one of: gstreamer, v4l2, any")
    device_path_name = _string(capture_values, "device_path", optional=True)
    device_path = None
    if device_path_name is not None:
        device_path = Path(device_path_name).expanduser()
        if not device_path.is_absolute():
            device_path = source.parent / device_path
        # Keep stable /dev/v4l/by-id symlinks intact instead of canonicalizing
        # them back to enumeration-dependent /dev/videoN names.
        device_path = device_path.absolute()
    stream_source = _string(capture_values, "stream_source", optional=True)
    if device_path is not None and stream_source is not None:
        raise ConfigError(
            "capture.device_path and capture.stream_source are mutually exclusive"
        )

    provider = _string(control_values, "provider", default="local")
    if provider != "local":
        raise ConfigError(
            "control.provider must be local; automatic providers are optional "
            "and require a future configured adapter"
        )
    socket_name = _string(
        control_values, "socket_path", default="run/harmonize.sock"
    )
    assert socket_name is not None
    socket_path = Path(socket_name).expanduser()
    if not socket_path.is_absolute():
        socket_path = source.parent / socket_path
    socket_path = socket_path.resolve()

    exception_behavior = _string(
        ambilight_values, "exception_cleanup_behavior", default="restore"
    )
    if exception_behavior not in {"restore", "off"}:
        raise ConfigError(
            "ambilight.exception_cleanup_behavior must be one of: restore, off"
        )

    brightness_adjustment = _integer(
        ambilight_values,
        "brightness_adjustment",
        0,
        minimum=-255,
        maximum=255,
    )
    color_processing_mode = _string(
        ambilight_values, "color_processing_mode", default="legacy_hsv"
    )
    if color_processing_mode not in {"legacy_hsv", "direct_rgb"}:
        raise ConfigError(
            "ambilight.color_processing_mode must be one of: "
            "legacy_hsv, direct_rgb"
        )
    if color_processing_mode == "direct_rgb" and brightness_adjustment != 0:
        raise ConfigError(
            "ambilight.color_processing_mode direct_rgb requires "
            "brightness_adjustment = 0"
        )

    log_level = _string(logging_values, "level", default="INFO")
    assert log_level is not None
    log_level = log_level.upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(
            "logging.level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
        )

    journal_name = _string(
        light_state_values,
        "journal_file",
        default="run/harmonize-light-state.json",
    )
    assert journal_name is not None
    journal_file = Path(journal_name).expanduser()
    if not journal_file.is_absolute():
        journal_file = source.parent / journal_file
    journal_file = journal_file.resolve()

    health_file_name = _string(
        reliability_values, "health_file", optional=True
    )
    health_file = None
    if health_file_name is not None:
        health_file = Path(health_file_name).expanduser()
        if not health_file.is_absolute():
            health_file = source.parent / health_file
        health_file = health_file.resolve()

    capture_reconnect_initial = _number(
        reliability_values,
        "capture_reconnect_initial_seconds",
        0.5,
        minimum=0.01,
    )
    capture_reconnect_max = _number(
        reliability_values,
        "capture_reconnect_max_seconds",
        5.0,
        minimum=0.01,
    )
    if capture_reconnect_max < capture_reconnect_initial:
        raise ConfigError(
            "capture_reconnect_max_seconds must be >= "
            "capture_reconnect_initial_seconds"
        )

    return HarmonizeConfig(
        hue=HueConfig(
            entertainment_area=area,
            credentials_file=credentials_path.resolve(),
            bridge_ip=_string(hue_values, "bridge_ip", optional=True),
        ),
        capture=CaptureConfig(
            device_index=_integer(
                capture_values, "device_index", 0, minimum=0, maximum=255
            ),
            device_path=device_path,
            backend=backend,
            stream_source=stream_source,
        ),
        control=ControlConfig(
            provider=provider,
            socket_path=socket_path,
            automatic_stale_seconds=_number(
                control_values,
                "automatic_stale_seconds",
                30.0,
                minimum=0.1,
            ),
            automatic_enable_debounce_seconds=_number(
                control_values,
                "automatic_enable_debounce_seconds",
                1.0,
                minimum=0.0,
            ),
            automatic_disable_grace_seconds=_number(
                control_values,
                "automatic_disable_grace_seconds",
                5.0,
                minimum=0.0,
            ),
            recovery_attempts=_integer(
                control_values,
                "recovery_attempts",
                3,
                minimum=0,
                maximum=100,
            ),
            recovery_initial_seconds=_number(
                control_values,
                "recovery_initial_seconds",
                1.0,
                minimum=0.01,
            ),
        ),
        ambilight=AmbilightConfig(
            video_wait_seconds=_number(
                ambilight_values, "video_wait_seconds", 2.0, minimum=0.0
            ),
            brightness_adjustment=brightness_adjustment,
            color_processing_mode=color_processing_mode,
            auto_restart_seconds=_number(
                ambilight_values, "auto_restart_seconds", 0.0, minimum=0.0
            ),
            single_light=_boolean(ambilight_values, "single_light", False),
            sample_breadth=_number(
                ambilight_values,
                "sample_breadth",
                0.15,
                minimum=0.001,
                maximum=1.0,
            ),
            update_interval_seconds=_number(
                ambilight_values, "update_interval_seconds", 0.05, minimum=0.001
            ),
            exception_cleanup_behavior=exception_behavior,
        ),
        logging=LoggingConfig(level=log_level),
        light_state=LightStateConfig(
            journal_file=journal_file,
            stale_after_seconds=_number(
                light_state_values,
                "stale_after_seconds",
                300.0,
                minimum=1.0,
            ),
            restore_attempts=_integer(
                light_state_values,
                "restore_attempts",
                3,
                minimum=1,
                maximum=20,
            ),
            retry_seconds=_number(
                light_state_values,
                "retry_seconds",
                0.5,
                minimum=0.01,
            ),
        ),
        reliability=ReliabilityConfig(
            startup_timeout_seconds=_number(
                reliability_values,
                "startup_timeout_seconds",
                10.0,
                minimum=0.1,
            ),
            shutdown_timeout_seconds=_number(
                reliability_values,
                "shutdown_timeout_seconds",
                15.0,
                minimum=0.1,
            ),
            capture_read_timeout_seconds=_number(
                reliability_values,
                "capture_read_timeout_seconds",
                2.0,
                minimum=0.1,
            ),
            capture_reconnect_initial_seconds=capture_reconnect_initial,
            capture_reconnect_max_seconds=capture_reconnect_max,
            transport_reconnect_attempts=_integer(
                reliability_values,
                "transport_reconnect_attempts",
                3,
                minimum=0,
                maximum=100,
            ),
            transport_reconnect_initial_seconds=_number(
                reliability_values,
                "transport_reconnect_initial_seconds",
                0.5,
                minimum=0.01,
            ),
            hue_status_interval_seconds=_number(
                reliability_values,
                "hue_status_interval_seconds",
                10.0,
                minimum=0.5,
            ),
            health_interval_seconds=_number(
                reliability_values,
                "health_interval_seconds",
                1.0,
                minimum=0.1,
            ),
            health_file=health_file,
        ),
        source_file=source,
    )


def load_credentials(path: str | Path, *, unattended: bool) -> HueCredentials:
    """Load legacy client.json safely and enforce service-mode permissions."""

    credential_path = Path(path).expanduser()
    try:
        metadata = credential_path.lstat()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Hue credentials file not found: {credential_path}. "
            "Register with the bridge in manual mode first."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Cannot inspect Hue credentials file: {exc}") from exc

    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigError("Hue credentials path must name a regular, non-symlink file")

    mode = stat.S_IMODE(metadata.st_mode)
    warning = None
    if mode & 0o077:
        message = (
            f"Hue credentials permissions are {mode:04o}; "
            f"run: chmod 600 {credential_path}"
        )
        if unattended:
            raise ConfigError(message)
        warning = message

    try:
        with credential_path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read Hue credentials JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise ConfigError("Hue credentials JSON must contain an object")
    username = document.get("username")
    clientkey = document.get("clientkey")
    if not isinstance(username, str) or not username:
        raise ConfigError("Hue credentials JSON requires a non-empty username")
    if not isinstance(clientkey, str) or not clientkey:
        raise ConfigError("Hue credentials JSON requires a non-empty clientkey")

    warnings = (warning,) if warning else ()
    return HueCredentials(username=username, clientkey=clientkey, warnings=warnings)
