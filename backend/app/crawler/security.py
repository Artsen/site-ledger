from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit


class UnsafeDestinationError(ValueError):
    pass


class DestinationResolutionError(UnsafeDestinationError):
    pass


@dataclass(frozen=True)
class ResolvedDestination:
    original_url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]
    allow_private_networks: bool


NAT64_WELL_KNOWN_NETWORK = ipaddress.ip_network("64:ff9b::/96")


async def resolve_addresses(
    host: str, port: int, allow_private_networks: bool = False
) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationResolutionError(f"Destination could not be resolved: {host}") from exc

    addresses = tuple(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise DestinationResolutionError(f"Destination could not be resolved: {host}")

    public = tuple(address for address in addresses if _is_public_address(address))
    private = tuple(address for address in addresses if address not in public)
    if public and private and not allow_private_networks:
        raise UnsafeDestinationError(
            "Destination resolves to mixed public and non-public addresses"
        )
    if private and not allow_private_networks:
        raise UnsafeDestinationError(f"Destination IP is not globally routable: {private[0]}")
    return addresses


def _is_public_address(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    embedded: ipaddress.IPv4Address | None = None
    if isinstance(parsed, ipaddress.IPv6Address):
        embedded = parsed.ipv4_mapped
        if embedded is None and parsed in NAT64_WELL_KNOWN_NETWORK:
            embedded = ipaddress.IPv4Address(int(parsed) & 0xFFFFFFFF)
    candidate = embedded or parsed
    return candidate.is_global and not candidate.is_multicast


async def validate_public_destination(
    url: str, allow_private_networks: bool = False
) -> ResolvedDestination:
    parsed, port = validate_destination_url(url)
    host = parsed.hostname or ""
    return ResolvedDestination(
        original_url=url,
        scheme=parsed.scheme.lower(),
        host=host,
        port=port,
        addresses=await resolve_addresses(host, port, allow_private_networks),
        allow_private_networks=allow_private_networks,
    )


def validate_destination_url(url: str) -> tuple[SplitResult, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeDestinationError("URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeDestinationError("URL scheme must be HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeDestinationError("URL user information is not allowed")
    if not parsed.hostname:
        raise UnsafeDestinationError("URL host is missing")
    return parsed, port or (443 if parsed.scheme.lower() == "https" else 80)
