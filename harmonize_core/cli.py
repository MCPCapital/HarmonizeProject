"""Persistent headless Harmonize command-line runtime."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import signal
import sys
import threading
import time

from harmonize_config import (
    ConfigError,
    ControlConfig,
    HarmonizeConfig,
    LightStateConfig,
    ReliabilityConfig,
    load_config,
    load_credentials,
)

from .capture import CaptureSource
from .controller import HarmonizeController
from .errors import HarmonizeError
from .hue import HueBridge, discover_bridge, resolve_area_name, resolve_group_id
from .local_control import LocalCommandProvider
from .light_state import HueLightStateManager, LightStateJournal
from .observability import HealthFile, configure_logging, log_event
from .state_machine import AmbilightSupervisor


@dataclass(frozen=True)
class RuntimeOptions:
    bridge_ip: str | None
    credentials_file: Path
    entertainment_area: str | None
    capture_device: int
    capture_device_path: str | None
    capture_backend: str
    stream_source: str | None
    brightness_adjustment: int
    color_processing_mode: str
    auto_restart_seconds: float
    single_light: bool
    sample_breadth: float
    update_interval_seconds: float
    logging_level: str
    exception_cleanup_behavior: str
    control: ControlConfig
    light_state: LightStateConfig
    reliability: ReliabilityConfig


class ShutdownCoordinator:
    """Map every process shutdown source to one idempotent request."""

    def __init__(self, target):
        self.target = target
        self.requested = threading.Event()
        self.reason: str | None = None

    def request(self, reason: str) -> None:
        if not self.requested.is_set():
            self.reason = reason
            self.requested.set()
            self.target.request_stop(reason)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-g", "--groupid")
    parser.add_argument("-b", "--bridgeid")
    parser.add_argument("-i", "--bridgeip")
    parser.add_argument("-s", "--single_light", action="store_true")
    parser.add_argument("-w", "--video_wait_time", type=float, default=None)
    parser.add_argument("-f", "--stream_filename")
    parser.add_argument("-l", "--light_brightness", type=int, default=None)
    parser.add_argument("-a", "--auto_restart", type=float, default=None)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="retained compatibility flag; runtime is always noninteractive",
    )
    parser.add_argument(
        "--check-area",
        action="store_true",
        help="resolve the selected Hue area read-only, then exit",
    )
    parser.add_argument(
        "--run-seconds",
        type=float,
        help="diagnostic daemon duration; omit to run until a signal",
    )
    parser.add_argument(
        "--health-file",
        type=Path,
        help="override the configured JSON health file",
    )
    parser.add_argument(
        "--inject-failure",
        choices=sorted(HarmonizeController.FAILURE_STAGES),
        help="lifecycle cleanup and recovery diagnostic",
    )
    return parser


def _load_optional_config(args: argparse.Namespace) -> HarmonizeConfig | None:
    path = args.config
    if path is None and Path("harmonize.toml").is_file():
        path = Path("harmonize.toml")
    if path is None:
        if args.unattended:
            raise ConfigError(
                "--unattended requires --config or an existing harmonize.toml"
            )
        return None
    return load_config(path, unattended=True)


def _runtime_options(
    args: argparse.Namespace, config: HarmonizeConfig | None
) -> RuntimeOptions:
    if config is None:
        return RuntimeOptions(
            bridge_ip=args.bridgeip,
            credentials_file=Path("client.json").resolve(),
            entertainment_area=None,
            capture_device=0,
            capture_device_path=None,
            capture_backend="gstreamer",
            stream_source=args.stream_filename,
            brightness_adjustment=(
                30 if args.light_brightness is None else args.light_brightness
            ),
            color_processing_mode="legacy_hsv",
            auto_restart_seconds=(
                0.0 if args.auto_restart is None else args.auto_restart
            ),
            single_light=args.single_light,
            sample_breadth=0.15,
            update_interval_seconds=0.0167,
            logging_level="DEBUG" if args.verbose else "INFO",
            exception_cleanup_behavior="restore",
            control=ControlConfig(
                socket_path=Path("run/harmonize.sock").resolve()
            ),
            light_state=LightStateConfig(
                journal_file=Path("run/harmonize-light-state.json").resolve()
            ),
            reliability=ReliabilityConfig(),
        )

    reliability = config.reliability
    if args.video_wait_time is not None:
        reliability = ReliabilityConfig(
            **{
                **reliability.__dict__,
                "startup_timeout_seconds": args.video_wait_time,
            }
        )
    return RuntimeOptions(
        bridge_ip=args.bridgeip or config.hue.bridge_ip,
        credentials_file=config.hue.credentials_file,
        entertainment_area=config.hue.entertainment_area,
        capture_device=config.capture.device_index,
        capture_device_path=(
            str(config.capture.device_path)
            if config.capture.device_path is not None
            else None
        ),
        capture_backend=config.capture.backend,
        stream_source=args.stream_filename or config.capture.stream_source,
        brightness_adjustment=(
            config.ambilight.brightness_adjustment
            if args.light_brightness is None
            else args.light_brightness
        ),
        color_processing_mode=config.ambilight.color_processing_mode,
        auto_restart_seconds=(
            config.ambilight.auto_restart_seconds
            if args.auto_restart is None
            else args.auto_restart
        ),
        single_light=args.single_light or config.ambilight.single_light,
        sample_breadth=config.ambilight.sample_breadth,
        update_interval_seconds=config.ambilight.update_interval_seconds,
        logging_level="DEBUG" if args.verbose else config.logging.level,
        exception_cleanup_behavior=config.ambilight.exception_cleanup_behavior,
        control=config.control,
        light_state=config.light_state,
        reliability=reliability,
    )


def _resolve_bridge(args: argparse.Namespace, options: RuntimeOptions) -> str:
    if args.bridgeid and not options.bridge_ip:
        raise HarmonizeError(
            "--bridgeid requires --bridgeip for deterministic headless startup"
        )
    return options.bridge_ip or discover_bridge()


def _write_health(
    reporter: HealthFile | None, supervisor: AmbilightSupervisor
) -> None:
    if reporter is not None:
        reporter.write(supervisor.snapshot())


def _status_snapshot(
    supervisor: AmbilightSupervisor, options: RuntimeOptions
) -> dict[str, object]:
    snapshot = supervisor.snapshot()
    snapshot["performance"] = {
        "color_processing_mode": options.color_processing_mode,
        "update_interval_seconds": options.update_interval_seconds,
        "brightness_adjustment": options.brightness_adjustment,
    }
    return snapshot


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hue = None
    supervisor = None
    reporter = None
    shutdown_timeout = 15.0
    old_handlers: dict[int, object] = {}
    try:
        if args.run_seconds is not None and args.run_seconds <= 0:
            raise ConfigError("--run-seconds must be greater than zero")
        config = _load_optional_config(args)
        options = _runtime_options(args, config)
        if (
            options.color_processing_mode == "direct_rgb"
            and options.brightness_adjustment != 0
        ):
            raise ConfigError("direct_rgb requires effective brightness_adjustment = 0")
        credentials = load_credentials(
            options.credentials_file, unattended=True
        )
        configure_logging(
            options.logging_level,
            secrets=(credentials.username, credentials.clientkey),
        )
        logger = logging.getLogger("harmonize")

        bridge_ip = _resolve_bridge(args, options)
        hue = HueBridge(bridge_ip, credentials.username)
        resources = hue.list_entertainment_resources()
        if options.entertainment_area is not None:
            area = resolve_area_name(resources, options.entertainment_area)
        elif args.groupid is not None:
            area = resolve_group_id(resources, args.groupid)
        else:
            raise HarmonizeError(
                "Headless startup requires hue.entertainment_area or --groupid"
            )

        log_event(
            logger,
            logging.INFO,
            "area_resolved",
            area=area.name,
            legacy_group_id=area.legacy_group_id,
            channels=len(area.channels),
            status=area.status,
        )
        if args.check_area:
            log_event(
                logger,
                logging.INFO,
                "area_check_complete",
                area=area.name,
                streaming_started=False,
            )
            return 0

        reliability = options.reliability
        shutdown_timeout = reliability.shutdown_timeout_seconds
        pending_journal = LightStateJournal(options.light_state.journal_file)
        if pending_journal.exists():
            try:
                pending_snapshot = pending_journal.load()
                log_event(
                    logger,
                    logging.WARNING,
                    "pending_light_state_journal",
                    area=pending_snapshot.area_name,
                    age_seconds=round(
                        max(0.0, time.time() - pending_snapshot.captured_at), 3
                    ),
                    action=(
                        "inspect and resolve with tools/harmonize_light_state.py "
                        "before Ambilight ON"
                    ),
                )
            except HarmonizeError as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "invalid_light_state_journal",
                    error=str(exc),
                    action="repair or remove the journal before Ambilight ON",
                )

        def light_state_factory(resolved_area):
            return HueLightStateManager(
                hue=hue,
                area=resolved_area,
                behavior=options.exception_cleanup_behavior,
                journal=LightStateJournal(options.light_state.journal_file),
                stale_after_seconds=options.light_state.stale_after_seconds,
                restore_attempts=options.light_state.restore_attempts,
                retry_seconds=options.light_state.retry_seconds,
            )

        def controller_factory() -> HarmonizeController:
            capture = CaptureSource(
                device_index=options.capture_device,
                device_path=options.capture_device_path,
                backend=options.capture_backend,
                stream_source=options.stream_source,
                startup_timeout_seconds=reliability.startup_timeout_seconds,
                read_timeout_seconds=reliability.capture_read_timeout_seconds,
                reconnect_initial_seconds=(
                    reliability.capture_reconnect_initial_seconds
                ),
                reconnect_max_seconds=reliability.capture_reconnect_max_seconds,
                shutdown_timeout_seconds=min(
                    reliability.shutdown_timeout_seconds / 3, 5.0
                ),
            )
            return HarmonizeController(
                hue=hue,
                area=area,
                capture=capture,
                client_key=credentials.clientkey,
                brightness_adjustment=options.brightness_adjustment,
                sample_breadth=options.sample_breadth,
                update_interval_seconds=options.update_interval_seconds,
                color_processing_mode=options.color_processing_mode,
                single_light=options.single_light,
                auto_restart_seconds=options.auto_restart_seconds,
                transport_reconnect_attempts=(
                    reliability.transport_reconnect_attempts
                ),
                transport_reconnect_initial_seconds=(
                    reliability.transport_reconnect_initial_seconds
                ),
                hue_status_interval_seconds=(
                    reliability.hue_status_interval_seconds
                ),
                failure_injection=args.inject_failure,
                light_state_factory=light_state_factory,
            )

        supervisor_box: dict[str, AmbilightSupervisor] = {}
        provider = LocalCommandProvider(
            options.control.socket_path,
            status=lambda: _status_snapshot(supervisor_box["supervisor"], options),
        )
        supervisor = AmbilightSupervisor(
            providers=[provider],
            controller_factory=controller_factory,
            startup_timeout_seconds=reliability.startup_timeout_seconds,
            shutdown_timeout_seconds=reliability.shutdown_timeout_seconds,
            recovery_attempts=options.control.recovery_attempts,
            recovery_initial_seconds=options.control.recovery_initial_seconds,
        )
        supervisor_box["supervisor"] = supervisor
        coordinator = ShutdownCoordinator(supervisor)

        def handle_signal(signum, frame) -> None:
            del frame
            coordinator.request(signal.Signals(signum).name)

        for signum in (signal.SIGTERM, signal.SIGINT):
            old_handlers[signum] = signal.signal(signum, handle_signal)

        health_path = args.health_file or reliability.health_file
        reporter = HealthFile(health_path) if health_path is not None else None
        supervisor.start_background()
        if not supervisor.ready.wait(reliability.startup_timeout_seconds):
            coordinator.request("startup_timeout")
            raise HarmonizeError(
                "Supervisor did not become ready within "
                f"{reliability.startup_timeout_seconds:g} seconds"
            )
        if supervisor.finished.is_set() and supervisor.error is not None:
            raise HarmonizeError(supervisor.error)
        _write_health(reporter, supervisor)

        started = time.monotonic()
        deadline = (
            started + args.run_seconds
            if args.run_seconds is not None
            else None
        )
        while not supervisor.finished.wait(reliability.health_interval_seconds):
            _write_health(reporter, supervisor)
            if deadline is not None and time.monotonic() >= deadline:
                coordinator.request("run_duration_elapsed")

        if not supervisor.join(reliability.shutdown_timeout_seconds + 1.0):
            coordinator.request("shutdown_timeout")
            raise HarmonizeError(
                "Supervisor did not stop within "
                f"{reliability.shutdown_timeout_seconds + 1:g} seconds"
            )
        _write_health(reporter, supervisor)
        if supervisor.error is not None:
            raise HarmonizeError(supervisor.error)
        log_event(
            logger,
            logging.INFO,
            "run_complete",
            elapsed_seconds=round(time.monotonic() - started, 3),
            shutdown_reason=coordinator.reason,
        )
        return 0
    except (ConfigError, HarmonizeError) as exc:
        if logging.getLogger().handlers:
            log_event(
                logging.getLogger("harmonize"),
                logging.ERROR,
                "startup_or_runtime_failed",
                error=str(exc),
            )
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if supervisor is not None and not supervisor.finished.is_set():
            supervisor.request_stop("cli_finalizer")
            supervisor.join(shutdown_timeout + 1.0)
        if reporter is not None and supervisor is not None:
            try:
                _write_health(reporter, supervisor)
            except Exception:
                pass
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        if hue is not None:
            hue.close()


def main() -> None:
    raise SystemExit(run())
