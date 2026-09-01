import asyncio
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpcore
import httpx
import pytest

from app.crawler.safe_fetch import FetchLimits, SafeHttpFetcher, TotalRequestTimeoutError
from app.crawler.secure_transport import PinnedNetworkBackend
from app.crawler.security import (
    UnsafeDestinationError,
    resolve_addresses,
    validate_public_destination,
)
from app.crawler.static_crawler import TRANSIENT_FETCH_ERRORS


def _dns_answer(*addresses: str) -> list[tuple[Any, ...]]:
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
        for address in addresses
    ]


@pytest.mark.asyncio
async def test_resolution_is_async_and_accepts_only_global_addresses(monkeypatch) -> None:
    def blocking_answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        time.sleep(0.05)
        return _dns_answer("8.8.8.8")

    monkeypatch.setattr(socket, "getaddrinfo", blocking_answer)
    ticked = False

    async def ticker() -> None:
        nonlocal ticked
        await asyncio.sleep(0.005)
        ticked = True

    addresses, _ = await asyncio.gather(resolve_addresses("example.test", 443), ticker())
    assert ticked
    assert addresses == ("8.8.8.8",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.1.1",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
    ],
)
async def test_non_global_destinations_are_rejected(monkeypatch, address: str) -> None:
    loop = asyncio.get_running_loop()

    async def answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return _dns_answer(address)

    monkeypatch.setattr(loop, "getaddrinfo", answer)
    with pytest.raises(UnsafeDestinationError, match="not globally routable"):
        await resolve_addresses("example.test", 443)


@pytest.mark.asyncio
async def test_mixed_answers_require_private_network_opt_in(monkeypatch) -> None:
    loop = asyncio.get_running_loop()

    async def answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return _dns_answer("8.8.8.8", "127.0.0.1")

    monkeypatch.setattr(loop, "getaddrinfo", answer)
    with pytest.raises(UnsafeDestinationError, match="mixed public"):
        await resolve_addresses("example.test", 443)
    assert await resolve_addresses("example.test", 443, True) == ("8.8.8.8", "127.0.0.1")


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
async def test_clearly_global_addresses_are_accepted(monkeypatch, address: str) -> None:
    loop = asyncio.get_running_loop()

    async def answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return _dns_answer(address)

    monkeypatch.setattr(loop, "getaddrinfo", answer)
    assert await resolve_addresses("example.test", 443) == (address,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["::ffff:127.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1"],
)
async def test_embedded_non_global_ipv4_is_rejected(monkeypatch, address: str) -> None:
    loop = asyncio.get_running_loop()

    async def answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return _dns_answer(address)

    monkeypatch.setattr(loop, "getaddrinfo", answer)
    with pytest.raises(UnsafeDestinationError, match="not globally routable"):
        await resolve_addresses("example.test", 443)
    assert await resolve_addresses("example.test", 443, True) == (address,)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["::ffff:8.8.8.8", "64:ff9b::808:808"])
async def test_embedded_global_ipv4_is_accepted(monkeypatch, address: str) -> None:
    loop = asyncio.get_running_loop()

    async def answer(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        return _dns_answer(address)

    monkeypatch.setattr(loop, "getaddrinfo", answer)
    assert await resolve_addresses("example.test", 443) == (address,)


@pytest.mark.asyncio
async def test_userinfo_is_rejected_even_with_private_network_opt_in() -> None:
    with pytest.raises(UnsafeDestinationError, match="user information") as caught:
        await validate_public_destination("http://user:secret@127.0.0.1/", True)
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_network_backend_connects_to_the_validated_address(monkeypatch) -> None:
    connected: list[str] = []
    sentinel = object()

    async def resolved(*_args: Any, **_kwargs: Any) -> tuple[str, ...]:
        return ("8.8.8.8",)

    class Backend:
        async def connect_tcp(self, host: str, *_args: Any, **_kwargs: Any) -> Any:
            connected.append(host)
            return sentinel

        async def sleep(self, _seconds: float) -> None:
            return None

    monkeypatch.setattr("app.crawler.secure_transport.resolve_addresses", resolved)
    backend = PinnedNetworkBackend()
    backend._backend = Backend()  # type: ignore[assignment]
    stream = await backend.connect_tcp("example.test", 443)
    assert stream is sentinel
    assert connected == ["8.8.8.8"]


@pytest.mark.asyncio
async def test_network_backend_rejects_rebinding_before_connect(monkeypatch) -> None:
    connected = False

    async def rebound(*_args: Any, **_kwargs: Any) -> tuple[str, ...]:
        raise UnsafeDestinationError("Destination IP is not globally routable: 127.0.0.1")

    class Backend:
        async def connect_tcp(self, *_args: Any, **_kwargs: Any) -> Any:
            nonlocal connected
            connected = True

    monkeypatch.setattr("app.crawler.secure_transport.resolve_addresses", rebound)
    backend = PinnedNetworkBackend()
    backend._backend = Backend()  # type: ignore[assignment]
    with pytest.raises(UnsafeDestinationError, match="not globally routable"):
        await backend.connect_tcp("example.test", 443)
    assert not connected


def test_unix_socket_connections_are_disabled() -> None:
    backend = PinnedNetworkBackend()
    with pytest.raises(httpcore.ConnectError, match="disabled"):
        asyncio.run(backend.connect_unix_socket("ignored"))


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html>ok</html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_safe_fetch_ignores_ambient_proxy_environment(monkeypatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    fetcher = SafeHttpFetcher(
        FetchLimits(
            timeout_seconds=2,
            max_response_bytes=10_000,
            max_redirects=2,
            user_agent="SiteLedgerSecurityTest/1",
            allow_private_networks=True,
        )
    )
    try:
        result = await fetcher.get(f"http://127.0.0.1:{server.server_port}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.http_status == 200
    assert result.content == b"<html>ok</html>"


class _SlowDripStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for chunk in (b"<html>", b"slow", b"</html>"):
            await asyncio.sleep(0.04)
            yield chunk


@pytest.mark.asyncio
async def test_safe_fetch_enforces_total_wall_clock_deadline_for_slow_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            stream=_SlowDripStream(),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SafeHttpFetcher(
            FetchLimits(
                timeout_seconds=0.07,
                max_response_bytes=10_000,
                max_redirects=2,
                user_agent="SiteLedgerSecurityTest/1",
            ),
            client=client,
            connection_pinning=False,
            destination_validator=lambda *_args: asyncio.sleep(0),
        )
        with pytest.raises(TotalRequestTimeoutError, match="Total request deadline") as caught:
            await fetcher.get("https://example.test/")

    assert 50 <= caught.value.elapsed_ms < 250


@pytest.mark.asyncio
async def test_safe_fetch_deadline_is_shared_across_redirect_hops() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.04)
        if request.url.path == "/first":
            return httpx.Response(302, headers={"location": "/second"}, request=request)
        return httpx.Response(200, content=b"<html>late</html>", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SafeHttpFetcher(
            FetchLimits(
                timeout_seconds=0.07,
                max_response_bytes=10_000,
                max_redirects=2,
                user_agent="SiteLedgerSecurityTest/1",
            ),
            client=client,
            connection_pinning=False,
            destination_validator=lambda *_args: asyncio.sleep(0),
        )
        with pytest.raises(TotalRequestTimeoutError):
            await fetcher.get("https://example.test/first")


def test_total_request_timeout_is_an_explicit_retryable_crawler_outcome() -> None:
    assert "request_timeout" in TRANSIENT_FETCH_ERRORS


@pytest.mark.asyncio
async def test_successful_fetch_cancels_deadline_and_leaves_caller_usable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>ok</html>", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SafeHttpFetcher(
            FetchLimits(
                timeout_seconds=0.02,
                max_response_bytes=10_000,
                max_redirects=2,
                user_agent="SiteLedgerSecurityTest/1",
            ),
            client=client,
            connection_pinning=False,
            destination_validator=lambda *_args: asyncio.sleep(0),
        )
        first = await fetcher.get("https://example.test/first")
        await asyncio.sleep(0.03)
        second = await fetcher.get("https://example.test/second")

    assert first.http_status == second.http_status == 200
