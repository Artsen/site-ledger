from __future__ import annotations

import ssl
from collections.abc import AsyncIterable, AsyncIterator
from types import TracebackType
from typing import Any, cast

import httpcore
import httpx

from app.crawler.security import resolve_addresses

HTTPCORE_EXCEPTIONS: tuple[tuple[type[Exception], type[httpx.TransportError]], ...] = (
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve, validate, and connect to the same approved address set."""

    def __init__(self, allow_private_networks: bool = False):
        self.allow_private_networks = allow_private_networks
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await resolve_addresses(host, port, self.allow_private_networks)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    async def connect_unix_socket(self, *_args: Any, **_kwargs: Any) -> Any:
        raise httpcore.ConnectError("Unix sockets are disabled for crawler requests")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]):
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for part in self._stream:
            yield part

    async def aclose(self) -> None:
        await self._stream.aclose()  # type: ignore[attr-defined]


class PinnedAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """HTTPX transport with connect-time DNS validation and address pinning."""

    def __init__(
        self,
        *,
        allow_private_networks: bool = False,
        limits: httpx.Limits | None = None,
    ):
        configured_limits = limits or httpx.Limits()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=configured_limits.max_connections,
            max_keepalive_connections=configured_limits.max_keepalive_connections,
            keepalive_expiry=configured_limits.keepalive_expiry,
            network_backend=PinnedNetworkBackend(allow_private_networks),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        assert isinstance(request.stream, httpx.AsyncByteStream)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as exc:
            for source, target in HTTPCORE_EXCEPTIONS:
                if isinstance(exc, source):
                    raise target(str(exc), request=request) from exc
            raise httpx.TransportError(str(exc), request=request) from exc
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(cast(AsyncIterable[bytes], response.stream)),
            extensions=response.extensions,
        )

    async def __aenter__(self) -> PinnedAsyncHTTPTransport:
        await self._pool.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._pool.__aexit__(exc_type, exc_value, traceback)

    async def aclose(self) -> None:
        await self._pool.aclose()
