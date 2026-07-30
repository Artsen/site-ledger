import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeDestinationError(ValueError):
    pass


async def validate_public_destination(url: str, allow_private_networks: bool = False) -> None:
    if allow_private_networks:
        return
    host = urlsplit(url).hostname
    if not host:
        raise UnsafeDestinationError("URL host is missing")
    infos = socket.getaddrinfo(host, None)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeDestinationError(f"Destination IP is not public: {ip}")
