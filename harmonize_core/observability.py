"""Structured logs and atomic health snapshots for unattended operation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


def _redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...] = ()):
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.msg),
            "message": message,
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, Mapping):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(
            _redact(payload, self._secrets),
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging(level: str, *, secrets: tuple[str, ...] = ()) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(secrets))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def log_event(
    logger: logging.Logger, level: int, event: str, **fields: Any
) -> None:
    logger.log(
        level,
        event.replace("_", " "),
        extra={"event": event, "fields": fields},
    )


class HealthFile:
    """Write non-secret liveness state atomically for local diagnostics."""

    def __init__(self, path: Path):
        self.path = path

    def write(self, snapshot: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(dict(snapshot), handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, 0o644)
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
