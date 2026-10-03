"""Session-scoped Hue light-state capture, restore/off, and safe journaling."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

from .errors import HarmonizeError
from .hue import EntertainmentArea, HueBridge
from .observability import log_event


@dataclass(frozen=True)
class LightState:
    resource_id: str
    name: str
    on: bool
    brightness: float | None
    color_xy: tuple[float, float] | None
    mirek: int | None

    @classmethod
    def from_resource(cls, resource: dict[str, Any]) -> "LightState":
        try:
            resource_id = str(resource["id"])
            name = str(resource.get("metadata", {}).get("name", resource_id))
            on = resource["on"]["on"]
            if not isinstance(on, bool):
                raise TypeError("on is not boolean")
            mode = resource.get("mode", "normal")
            if mode != "normal":
                raise HarmonizeError(
                    f'Hue light "{name}" is in unsupported mode {mode!r}'
                )
            cls._require_static(resource, name)
            brightness = None
            if "dimming" in resource:
                brightness = float(resource["dimming"]["brightness"])
                if not math.isfinite(brightness) or not 0 <= brightness <= 100:
                    raise ValueError("brightness outside 0..100")
            color_xy = None
            mirek = None
            color_temperature = resource.get("color_temperature")
            if (
                isinstance(color_temperature, dict)
                and color_temperature.get("mirek_valid") is True
                and color_temperature.get("mirek") is not None
            ):
                mirek = int(color_temperature["mirek"])
            elif isinstance(resource.get("color"), dict):
                xy = resource["color"].get("xy")
                if isinstance(xy, dict):
                    x, y = float(xy["x"]), float(xy["y"])
                    if not all(math.isfinite(value) for value in (x, y)):
                        raise ValueError("color coordinates are not finite")
                    color_xy = (x, y)
            return cls(
                resource_id=resource_id,
                name=name,
                on=on,
                brightness=brightness,
                color_xy=color_xy,
                mirek=mirek,
            )
        except HarmonizeError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise HarmonizeError("Hue returned malformed static light state") from exc

    @staticmethod
    def _require_static(resource: dict[str, Any], name: str) -> None:
        dynamic_status = resource.get("dynamics", {}).get("status", "none")
        effect_status = resource.get("effects_v2", {}).get("status", {}).get(
            "effect",
            resource.get("effects", {}).get("status", "no_effect"),
        )
        timed_status = resource.get("timed_effects", {}).get(
            "status", "no_effect"
        )
        unsupported = []
        if dynamic_status != "none":
            unsupported.append(f"dynamic state {dynamic_status!r}")
        if effect_status != "no_effect":
            unsupported.append(f"effect {effect_status!r}")
        if timed_status != "no_effect":
            unsupported.append(f"timed effect {timed_status!r}")
        if unsupported:
            raise HarmonizeError(
                f'Cannot safely snapshot Hue light "{name}" with '
                + ", ".join(unsupported)
                + "; stop the scene/effect before Ambilight ON"
            )

    def restore_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "on": {"on": self.on},
            "dynamics": {"duration": 0},
        }
        if self.brightness is not None:
            body["dimming"] = {"brightness": self.brightness}
        if self.mirek is not None:
            body["color_temperature"] = {"mirek": self.mirek}
        elif self.color_xy is not None:
            body["color"] = {
                "xy": {"x": self.color_xy[0], "y": self.color_xy[1]}
            }
        return body

    def matches(self, resource: dict[str, Any], *, behavior: str) -> bool:
        try:
            if behavior == "off":
                return resource["on"]["on"] is False
            if resource["on"]["on"] is not self.on:
                return False
            if self.brightness is not None and abs(
                float(resource["dimming"]["brightness"]) - self.brightness
            ) > 0.2:
                return False
            if self.mirek is not None:
                if abs(int(resource["color_temperature"]["mirek"]) - self.mirek) > 1:
                    return False
            elif self.color_xy is not None:
                xy = resource["color"]["xy"]
                if (
                    abs(float(xy["x"]) - self.color_xy[0]) > 0.001
                    or abs(float(xy["y"]) - self.color_xy[1]) > 0.001
                ):
                    return False
            return True
        except (KeyError, TypeError, ValueError):
            return False


@dataclass(frozen=True)
class LightStateSnapshot:
    session_id: str
    area_id: str
    area_name: str
    captured_at: float
    lights: tuple[LightState, ...]


class LightStateJournal:
    """Atomic owner-only journal; stale entries are never auto-applied."""

    def __init__(self, path: Path):
        self.path = path

    def exists(self) -> bool:
        return self.path.exists() or self.path.is_symlink()

    def write(
        self,
        snapshot: LightStateSnapshot,
        *,
        status: str = "pending",
        error: str | None = None,
    ) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "status": status,
            "error": error,
            "session_id": snapshot.session_id,
            "area_id": snapshot.area_id,
            "area_name": snapshot.area_name,
            "captured_at": snapshot.captured_at,
            "lights": [asdict(light) for light in snapshot.lights],
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def load(self) -> LightStateSnapshot:
        try:
            metadata = self.path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise HarmonizeError(
                    "Light-state journal must be a regular, non-symlink file"
                )
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise HarmonizeError(
                    f"Light-state journal permissions must be 0600: {self.path}"
                )
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != 1:
                raise HarmonizeError("Unsupported light-state journal version")
            lights = tuple(
                LightState(
                    resource_id=str(item["resource_id"]),
                    name=str(item["name"]),
                    on=item["on"],
                    brightness=(
                        float(item["brightness"])
                        if item.get("brightness") is not None
                        else None
                    ),
                    color_xy=(
                        tuple(float(value) for value in item["color_xy"])
                        if item.get("color_xy") is not None
                        else None
                    ),
                    mirek=(
                        int(item["mirek"])
                        if item.get("mirek") is not None
                        else None
                    ),
                )
                for item in payload["lights"]
            )
            snapshot = LightStateSnapshot(
                session_id=str(payload["session_id"]),
                area_id=str(payload["area_id"]),
                area_name=str(payload["area_name"]),
                captured_at=float(payload["captured_at"]),
                lights=lights,
            )
        except HarmonizeError:
            raise
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HarmonizeError(
                f"Cannot load light-state journal {self.path}: {exc}"
            ) from exc
        if not snapshot.lights or any(not light.resource_id for light in snapshot.lights):
            raise HarmonizeError("Light-state journal contains no usable lights")
        if any(not isinstance(light.on, bool) for light in snapshot.lights):
            raise HarmonizeError("Light-state journal contains invalid on/off state")
        return snapshot

    def remove(self, session_id: str) -> None:
        current = self.load()
        if current.session_id != session_id:
            raise HarmonizeError(
                "Light-state journal belongs to a different session; refusing removal"
            )
        self.path.unlink()


class HueLightStateManager:
    """Capture and finalize static state for exactly one Entertainment area."""

    def __init__(
        self,
        *,
        hue: HueBridge,
        area: EntertainmentArea,
        behavior: str,
        journal: LightStateJournal,
        stale_after_seconds: float,
        restore_attempts: int,
        retry_seconds: float,
        wall_clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ):
        if behavior not in {"restore", "off"}:
            raise ValueError("light-state behavior must be restore or off")
        self.hue = hue
        self.area = area
        self.behavior = behavior
        self.journal = journal
        self.stale_after_seconds = stale_after_seconds
        self.restore_attempts = restore_attempts
        self.retry_seconds = retry_seconds
        self.wall_clock = wall_clock
        self.sleeper = sleeper
        self._logger = logger or logging.getLogger("harmonize.light_state")

    def capture(self) -> LightStateSnapshot:
        if self.journal.exists():
            pending = self.journal.load()
            age = max(0.0, self.wall_clock() - pending.captured_at)
            stale = age > self.stale_after_seconds
            raise HarmonizeError(
                f'Pending light-state journal for area "{pending.area_name}" '
                f"is {age:.1f}s old ({'stale' if stale else 'unresolved'}); "
                "inspect and resolve it with tools/harmonize_light_state.py "
                "before Ambilight ON"
            )
        if not self.area.light_ids:
            raise HarmonizeError(
                f'Hue Entertainment area "{self.area.name}" exposes no light services'
            )
        if len(set(self.area.light_ids)) != len(self.area.light_ids):
            raise HarmonizeError(
                f'Hue Entertainment area "{self.area.name}" repeats a light service'
            )
        lights = tuple(
            LightState.from_resource(self.hue.get_light(resource_id))
            for resource_id in self.area.light_ids
        )
        snapshot = LightStateSnapshot(
            session_id=str(uuid4()),
            area_id=self.area.resource_id,
            area_name=self.area.name,
            captured_at=self.wall_clock(),
            lights=lights,
        )
        self.journal.write(snapshot)
        log_event(
            self._logger,
            logging.INFO,
            "light_state_captured",
            area=self.area.name,
            session_id=snapshot.session_id,
            light_count=len(lights),
            behavior=self.behavior,
        )
        return snapshot

    def _apply_one(self, light: LightState, behavior: str) -> None:
        body = (
            light.restore_body()
            if behavior == "restore"
            else {"on": {"on": False}, "dynamics": {"duration": 0}}
        )
        last_error: Exception | None = None
        for attempt in range(1, self.restore_attempts + 1):
            try:
                self.hue.update_light(light.resource_id, body)
                current = self.hue.get_light(light.resource_id)
                if not light.matches(current, behavior=behavior):
                    raise HarmonizeError(
                        f'Hue light "{light.name}" did not verify after {behavior}'
                    )
                return
            except Exception as exc:
                last_error = exc
                log_event(
                    self._logger,
                    logging.WARNING,
                    "light_state_apply_retry",
                    light=light.name,
                    behavior=behavior,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self.restore_attempts:
                    self.sleeper(self.retry_seconds)
        raise HarmonizeError(
            f'Failed to {behavior} Hue light "{light.name}" after '
            f"{self.restore_attempts} attempts: {last_error}"
        )

    def apply(self, snapshot: LightStateSnapshot, *, behavior: str | None = None) -> None:
        selected = behavior or self.behavior
        failures = []
        for light in snapshot.lights:
            try:
                self._apply_one(light, selected)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            error = "; ".join(failures)
            self.journal.write(snapshot, status="recovery_required", error=error)
            raise HarmonizeError(error)
        self.journal.remove(snapshot.session_id)
        log_event(
            self._logger,
            logging.INFO,
            "light_state_applied",
            area=snapshot.area_name,
            session_id=snapshot.session_id,
            light_count=len(snapshot.lights),
            behavior=selected,
        )

    def finish(
        self,
        snapshot: LightStateSnapshot,
        *,
        behavior: str | None = None,
    ) -> None:
        current = self.journal.load()
        if current.session_id != snapshot.session_id:
            raise HarmonizeError(
                "Light-state journal session changed; refusing automatic apply"
            )
        self.apply(snapshot, behavior=behavior)
