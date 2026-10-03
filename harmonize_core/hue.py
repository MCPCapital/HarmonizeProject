"""Hue bridge queries and exact Entertainment-area resolution."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import threading
from typing import Any, Iterable

import requests
from urllib3.exceptions import InsecureRequestWarning
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

from .errors import HarmonizeError

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


@dataclass(frozen=True)
class Channel:
    channel_id: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class EntertainmentArea:
    resource_id: str
    legacy_group_id: str
    name: str
    channels: tuple[Channel, ...]
    status: str | None = None
    light_ids: tuple[str, ...] = ()


def _legacy_group_id(resource: dict[str, Any]) -> str:
    match = re.search(r"\d+", str(resource.get("id_v1", "")))
    if not match:
        raise HarmonizeError(
            f'Entertainment area "{resource.get("name", "<unnamed>")}" '
            "has no usable legacy group ID"
        )
    return match.group(0)


def _light_service_ids(resource: dict[str, Any]) -> tuple[str, ...]:
    references = resource.get("light_services", [])
    if not isinstance(references, list):
        raise HarmonizeError("Hue returned malformed Entertainment light services")
    result = []
    for reference in references:
        if not isinstance(reference, dict):
            raise HarmonizeError("Hue returned malformed Entertainment light service")
        if reference.get("rtype") == "light":
            resource_id = reference.get("rid")
            if not isinstance(resource_id, str) or not resource_id:
                raise HarmonizeError("Hue returned an invalid Entertainment light ID")
            result.append(resource_id)
    return tuple(result)


def area_from_resource(resource: dict[str, Any]) -> EntertainmentArea:
    try:
        channels = tuple(
            Channel(
                channel_id=int(channel["channel_id"]),
                x=float(channel["position"]["x"]),
                y=float(channel["position"]["y"]),
                z=float(channel["position"]["z"]),
            )
            for channel in resource["channels"]
        )
        return EntertainmentArea(
            resource_id=str(resource["id"]),
            legacy_group_id=_legacy_group_id(resource),
            name=str(resource["name"]),
            channels=channels,
            status=(
                str(resource["status"])
                if resource.get("status") is not None
                else None
            ),
            light_ids=_light_service_ids(resource),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HarmonizeError("Hue returned a malformed Entertainment area") from exc


def resolve_area_name(
    resources: Iterable[dict[str, Any]], configured_name: str
) -> EntertainmentArea:
    matches = [
        resource for resource in resources if resource.get("name") == configured_name
    ]
    if not matches:
        raise HarmonizeError(
            f'Hue Entertainment area "{configured_name}" was not found; '
            "check hue.entertainment_area and the Hue app"
        )
    if len(matches) > 1:
        raise HarmonizeError(
            f'Hue Entertainment area "{configured_name}" is ambiguous '
            f"({len(matches)} exact matches); rename duplicates in the Hue app"
        )
    return area_from_resource(matches[0])


def resolve_group_id(
    resources: Iterable[dict[str, Any]], group_id: str
) -> EntertainmentArea:
    matches = [
        resource
        for resource in resources
        if _legacy_group_id(resource) == str(group_id)
    ]
    if not matches:
        raise HarmonizeError(
            f"Hue Entertainment legacy group ID {group_id} was not found"
        )
    return area_from_resource(matches[0])


def select_area_interactively(
    resources: list[dict[str, Any]], input_fn=input, output_fn=print
) -> EntertainmentArea:
    if not resources:
        raise HarmonizeError(
            "No Hue Entertainment areas exist; create one in the Hue app"
        )
    if len(resources) == 1:
        return area_from_resource(resources[0])
    output_fn("Multiple Entertainment areas found:")
    for resource in resources:
        output_fn(f'[ {_legacy_group_id(resource)} ]: {resource.get("name", "")}')
    selected = input_fn("Select the legacy group ID: ").strip()
    return resolve_group_id(resources, selected)


class _HueListener(ServiceListener):
    def __init__(self) -> None:
        self.addresses: set[str] = set()
        self.found = threading.Event()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info is not None:
            self.addresses.update(
                address
                for address in info.parsed_addresses()
                if isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address)
            )
            self.found.set()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return None


def discover_bridge(timeout_seconds: float = 3.0) -> str:
    listener = _HueListener()
    zeroconf = Zeroconf()
    try:
        ServiceBrowser(zeroconf, "_hue._tcp.local.", listener)
        listener.found.wait(timeout_seconds)
    except (OSError, NotImplementedError) as exc:
        raise HarmonizeError(f"Hue mDNS discovery failed: {exc}") from exc
    finally:
        zeroconf.close()
    addresses = sorted(listener.addresses)
    if not addresses:
        raise HarmonizeError(
            "No IPv4 Hue bridge address found by mDNS; "
            "set hue.bridge_ip in harmonize.toml"
        )
    if len(addresses) > 1:
        raise HarmonizeError(
            "Multiple Hue bridges found by mDNS; set hue.bridge_ip explicitly"
        )
    return addresses[0]


class HueBridge:
    """Owns authenticated Hue HTTP operations for one explicit bridge."""

    def __init__(
        self,
        bridge_ip: str,
        username: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 5.0,
    ):
        self.bridge_ip = bridge_ip
        self.username = username
        self._session = session or requests.Session()
        self._timeout = timeout_seconds
        self._headers = {"hue-application-key": username}

    def new_session(self) -> HueBridge:
        """Return an equivalent bridge client with independent HTTP state."""
        return HueBridge(
            self.bridge_ip,
            self.username,
            timeout_seconds=self._timeout,
        )

    def close(self) -> None:
        self._session.close()

    def _request(
        self, method: str, path: str, *, json_body: dict[str, Any] | None = None
    ) -> requests.Response:
        try:
            response = self._session.request(
                method,
                f"https://{self.bridge_ip}{path}",
                headers=self._headers,
                json=json_body,
                verify=False,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise HarmonizeError(
                f"Hue bridge request failed for {method} {path}: {exc}"
            ) from exc
        return response

    def list_entertainment_resources(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET", "/clip/v2/resource/entertainment_configuration"
        )
        try:
            payload = response.json()
            resources = payload["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise HarmonizeError(
                "Hue returned malformed Entertainment-area data"
            ) from exc
        if not isinstance(resources, list):
            raise HarmonizeError("Hue Entertainment-area data is not a list")
        return resources

    def resolve_name(self, configured_name: str) -> EntertainmentArea:
        return resolve_area_name(
            self.list_entertainment_resources(), configured_name
        )

    def resolve_group(self, group_id: str) -> EntertainmentArea:
        return resolve_group_id(
            self.list_entertainment_resources(), group_id
        )

    def get_light(self, resource_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/clip/v2/resource/light/{resource_id}")
        try:
            payload = response.json()
            resources = payload["data"]
            errors = payload.get("errors", [])
        except (ValueError, KeyError, TypeError) as exc:
            raise HarmonizeError("Hue returned malformed light data") from exc
        if errors or not isinstance(resources, list) or len(resources) != 1:
            raise HarmonizeError(
                f"Hue light resource {resource_id} was not found or was ambiguous"
            )
        resource = resources[0]
        if not isinstance(resource, dict) or resource.get("id") != resource_id:
            raise HarmonizeError("Hue returned mismatched light data")
        return resource

    def update_light(self, resource_id: str, body: dict[str, Any]) -> None:
        response = self._request(
            "PUT", f"/clip/v2/resource/light/{resource_id}", json_body=body
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HarmonizeError("Hue returned malformed light-update data") from exc
        if payload.get("errors"):
            raise HarmonizeError(
                f"Hue rejected state update for light {resource_id}"
            )

    def application_id(self) -> str:
        response = self._request("GET", "/auth/v1")
        app_id = response.headers.get("hue-application-id")
        if not app_id:
            raise HarmonizeError("Hue response did not include hue-application-id")
        return app_id

    def start_streaming(self, area: EntertainmentArea) -> None:
        self._action(area, "start")

    def stop_streaming(self, area: EntertainmentArea) -> None:
        self._action(area, "stop")

    def _action(self, area: EntertainmentArea, action: str) -> None:
        response = self._request(
            "PUT",
            f"/clip/v2/resource/entertainment_configuration/{area.resource_id}",
            json_body={"action": action},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise HarmonizeError(
                f"Hue returned malformed response while requesting {action}"
            ) from exc
        if payload.get("errors"):
            raise HarmonizeError(
                f'Hue rejected Entertainment action "{action}" for area '
                f'"{area.name}"'
            )

    def close(self) -> None:
        self._session.close()
