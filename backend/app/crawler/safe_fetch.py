from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpx

from app.crawler.security import validate_public_destination

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ALLOWED_CALLER_HEADERS = {
    "accept",
    "accept-language",
    "if-none-match",
    "if-modified-since",
}
FORBIDDEN_CALLER_HEADERS = {"authorization", "cookie", "proxy-authorization"}

RedirectValidator = Callable[[str], Awaitable[tuple[bool, str | None, str | None, str | None]]]
DestinationValidator = Callable[[str, bool], Awaitable[None]]


@dataclass(frozen=True)
class FetchLimits:
    timeout_seconds: float
    max_response_bytes: int
    max_redirects: int
    user_agent: str
    allow_private_networks: bool = False


@dataclass(frozen=True)
class SafeFetchResult:
    requested_url: str
    final_url: str
    http_status: int
    headers: dict[str, str]
    content: bytes
    encoding: str | None
    redirect_chain: list[dict[str, Any]]
    response_time_ms: int

    @property
    def content_type(self) -> str | None:
        return self.headers.get("content-type")


class SafeHttpFetcher:
    def __init__(
        self,
        limits: FetchLimits,
        transport: httpx.AsyncBaseTransport | None = None,
        redirect_validator: RedirectValidator | None = None,
        destination_validator: DestinationValidator = validate_public_destination,
    ):
        self.limits = limits
        self.transport = transport
        self.redirect_validator = redirect_validator
        self.destination_validator = destination_validator

    async def get(self, url: str, headers: dict[str, str] | None = None) -> SafeFetchResult:
        started = monotonic()
        request_headers = {"User-Agent": self.limits.user_agent}
        request_headers.update(_validated_request_headers(headers or {}))
        async with httpx.AsyncClient(
            follow_redirects=False,
            max_redirects=self.limits.max_redirects,
            timeout=self.limits.timeout_seconds,
            headers=request_headers,
            transport=self.transport,
        ) as client:
            response, content, chain = await self._get_with_validated_redirects(client, url)
        return SafeFetchResult(
            requested_url=url,
            final_url=str(response.url),
            http_status=response.status_code,
            headers=dict(response.headers),
            content=content,
            encoding=response.encoding,
            redirect_chain=chain,
            response_time_ms=int((monotonic() - started) * 1000),
        )

    async def _get_with_validated_redirects(
        self, client: httpx.AsyncClient, start_url: str
    ) -> tuple[httpx.Response, bytes, list[dict[str, Any]]]:
        current_url = start_url
        seen_redirects = {start_url}
        redirect_chain: list[dict[str, Any]] = []

        for _hop in range(self.limits.max_redirects + 1):
            await self.destination_validator(current_url, self.limits.allow_private_networks)
            async with client.stream("GET", current_url) as response:
                if response.status_code not in REDIRECT_STATUSES:
                    content = await self._read_limited_response(response, redirect_chain)
                    return response, content, redirect_chain

                location = response.headers.get("location")
                try:
                    resolved_url = urljoin(str(response.url), location) if location else None
                except ValueError as exc:
                    redirect_chain.append(_redirect_record(current_url, response, location, None))
                    raise RedirectFailureError(
                        "invalid_url",
                        str(exc),
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    ) from exc
                redirect_chain.append(
                    _redirect_record(current_url, response, location, resolved_url)
                )
                if not location or not resolved_url:
                    raise RedirectFailureError(
                        "invalid_url",
                        "Redirect response did not include a valid Location header",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                try:
                    httpx.URL(resolved_url)
                except httpx.InvalidURL as exc:
                    raise RedirectFailureError(
                        "invalid_url",
                        str(exc),
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    ) from exc
                if self.redirect_validator is not None:
                    ok, error_type, message, normalized_url = await self.redirect_validator(
                        resolved_url
                    )
                    if not ok:
                        raise RedirectFailureError(
                            error_type or "scope_excluded",
                            message or "Redirect was rejected",
                            str(response.url),
                            response.status_code,
                            dict(response.headers),
                            redirect_chain,
                        )
                    if normalized_url:
                        resolved_url = normalized_url
                if resolved_url in seen_redirects:
                    raise RedirectFailureError(
                        "redirect_loop",
                        "Redirect loop detected",
                        str(response.url),
                        response.status_code,
                        dict(response.headers),
                        redirect_chain,
                    )
                await self.destination_validator(resolved_url, self.limits.allow_private_networks)
                seen_redirects.add(resolved_url)
                current_url = resolved_url

        raise RedirectFailureError(
            "too_many_redirects", "Redirect limit exceeded", current_url, None, None, redirect_chain
        )

    async def _read_limited_response(
        self, response: httpx.Response, redirect_chain: list[dict[str, Any]]
    ) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.limits.max_response_bytes:
                    raise ResponseTooLargeError(
                        "Content-Length exceeded configured response limit", redirect_chain
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.limits.max_response_bytes:
                raise ResponseTooLargeError(
                    "Streamed response exceeded configured response limit", redirect_chain
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _redirect_record(
    requested_url: str, response: httpx.Response, location: str | None, resolved_url: str | None
) -> dict[str, Any]:
    return {
        "requested_url": requested_url,
        "status_code": response.status_code,
        "location": location,
        "resolved_url": resolved_url,
    }


def connect_error_type(exc: httpx.ConnectError) -> str:
    text = str(exc).lower()
    if "name" in text or "dns" in text:
        return "dns_error"
    if "ssl" in text or "tls" in text:
        return "tls_error"
    return "connection_error"


class RedirectFailureError(Exception):
    def __init__(
        self,
        error_type: str,
        message: str,
        final_url: str | None,
        http_status: int | None,
        response_headers: dict[str, Any] | None,
        redirect_chain: list[dict[str, Any]],
    ):
        super().__init__(message)
        self.error_type = error_type
        self.final_url = final_url
        self.http_status = http_status
        self.response_headers = response_headers
        self.redirect_chain = redirect_chain


class ResponseTooLargeError(Exception):
    def __init__(self, message: str, redirect_chain: list[dict[str, Any]]):
        super().__init__(message)
        self.redirect_chain = redirect_chain


def _validated_request_headers(headers: dict[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.strip().lower()
        if normalized in FORBIDDEN_CALLER_HEADERS:
            raise ValueError(f"Header is not allowed for crawler requests: {key}")
        if normalized not in ALLOWED_CALLER_HEADERS:
            raise ValueError(f"Header is not supported for crawler requests: {key}")
        validated[key] = value
    return validated
