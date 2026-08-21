import re
from collections.abc import Iterable
from dataclasses import dataclass
from posixpath import normpath
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    unquote_plus,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

URL_NORMALIZATION_V1_VERSION = "url-normalization-v1"
URL_NORMALIZATION_V2_VERSION = "url-normalization-v2"
# Compatibility identifier for callers that explicitly characterize historical V1.
URL_NORMALIZATION_VERSION = URL_NORMALIZATION_V1_VERSION
SUPPORTED_URL_NORMALIZATION_VERSIONS = frozenset(
    {URL_NORMALIZATION_V1_VERSION, URL_NORMALIZATION_V2_VERSION}
)

UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
HEX = frozenset("0123456789abcdefABCDEF")
PATH_SAFE = "/:@!$&'()*+,;=-._~%"
QUERY_SAFE = "!$'()*+,-./:;=?@_~%[]"


@dataclass(frozen=True)
class NormalizedUrl:
    raw_url: str
    resolved_url: str
    normalized_url: str
    scheme: str
    host: str
    port: int | None
    path: str
    query: str


class UrlNormalizationError(ValueError):
    pass


def normalize_url(
    raw_url: str, base_url: str | None = None, drop_query_params: list[str] | None = None
) -> NormalizedUrl:
    """Compatibility wrapper for the frozen historical V1 contract."""
    return normalize_url_v1(raw_url, base_url, drop_query_params)


def normalize_url_for_version(
    raw_url: str,
    *,
    normalization_version: str,
    base_url: str | None = None,
    drop_query_params: Iterable[str] = (),
) -> NormalizedUrl:
    if normalization_version == URL_NORMALIZATION_V1_VERSION:
        return normalize_url_v1(raw_url, base_url, list(drop_query_params))
    if normalization_version == URL_NORMALIZATION_V2_VERSION:
        return normalize_url_v2(raw_url, base_url)
    raise UrlNormalizationError(f"Unsupported URL normalization version: {normalization_version}")


def normalize_url_v1(
    raw_url: str, base_url: str | None = None, drop_query_params: list[str] | None = None
) -> NormalizedUrl:
    if raw_url is None:
        raise UrlNormalizationError("URL is missing")
    candidate = raw_url.strip()
    if not candidate:
        raise UrlNormalizationError("URL is empty")
    resolved = urljoin(base_url, candidate) if base_url else candidate
    parts = urlsplit(resolved)
    if not parts.scheme or not parts.netloc:
        raise UrlNormalizationError("URL must be absolute after resolution")
    if parts.scheme.lower() not in {"http", "https"}:
        raise UrlNormalizationError("unsupported scheme")

    try:
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        port = parts.port
    except (UnicodeError, ValueError) as exc:
        raise UrlNormalizationError(str(exc)) from exc
    if not host:
        raise UrlNormalizationError("URL host is missing")
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise UrlNormalizationError("URL host contains invalid characters")
    if (parts.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None

    path = _normalize_v1_path(parts.path or "/")
    query = _normalize_v1_query(parts.query, drop_query_params or [])
    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    return _result(raw_url, resolved, normalized, parts.scheme.lower(), host, port, path, query)


def normalize_url_v2(raw_url: str, base_url: str | None = None) -> NormalizedUrl:
    """Production form of the audited PR #27/#29 candidate, without Site policy drops."""
    if raw_url is None:
        raise UrlNormalizationError("URL is missing")
    candidate = raw_url.strip()
    if not candidate:
        raise UrlNormalizationError("URL is empty")
    resolved = urljoin(base_url, candidate) if base_url else candidate
    try:
        parts = urlsplit(resolved)
        port = parts.port
    except ValueError as exc:
        raise UrlNormalizationError(str(exc)) from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise UrlNormalizationError("absolute HTTP(S) URL required")
    if parts.username is not None or parts.password is not None:
        raise UrlNormalizationError("credential-bearing URLs are not identities")
    try:
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UrlNormalizationError(str(exc)) from exc
    if not host:
        raise UrlNormalizationError("URL host is missing")
    if (scheme, port) in {("http", 80), ("https", 443)}:
        port = None
    path = _normalize_v2_path(parts.path or "/")
    query = _normalize_v2_query(parts.query, ())
    authority_host = f"[{host}]" if ":" in host else host
    authority = authority_host if port is None else f"{authority_host}:{port}"
    normalized = urlunsplit((scheme, authority, path, query, ""))
    return _result(raw_url, resolved, normalized, scheme, host, port, path, query)


def site_url_policy_key(normalized: NormalizedUrl, drop_query_params: Iterable[str]) -> str:
    """Return a Site-local candidate dedupe key without changing global V2 identity."""
    patterns = tuple(drop_query_params)
    if not patterns:
        return normalized.normalized_url
    if normalized.query:
        query = _normalize_v2_query(normalized.query, patterns)
        authority_host = f"[{normalized.host}]" if ":" in normalized.host else normalized.host
        authority = (
            authority_host if normalized.port is None else f"{authority_host}:{normalized.port}"
        )
        return urlunsplit((normalized.scheme, authority, normalized.path, query, ""))
    return normalized.normalized_url


def _result(
    raw_url: str,
    resolved: str,
    normalized: str,
    scheme: str,
    host: str,
    port: int | None,
    path: str,
    query: str,
) -> NormalizedUrl:
    resolved_parts = urlsplit(resolved)
    resolved_without_fragment = urlunsplit(
        (
            resolved_parts.scheme,
            resolved_parts.netloc,
            resolved_parts.path or "/",
            resolved_parts.query,
            "",
        )
    )
    return NormalizedUrl(
        raw_url=raw_url,
        resolved_url=resolved_without_fragment,
        normalized_url=normalized,
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        query=query,
    )


def _normalize_v1_path(path: str) -> str:
    had_trailing = path.endswith("/")
    decoded = unquote(path)
    normalized = normpath(decoded)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if had_trailing and not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return quote(normalized, safe="/:@!$&'()*+,;=")


def _normalize_v1_query(query: str, drop_patterns: list[str]) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if _should_drop_query_param(key, drop_patterns):
            continue
        kept.append((key, value))
    kept.sort(key=lambda item: (item[0], item[1]))
    return urlencode(kept, doseq=True)


def _normalize_v2_path(path: str) -> str:
    escaped = _normalize_percent_encoding(path, decode_dot=False)
    without_dots = _remove_literal_dot_segments(escaped)
    return quote(without_dots, safe=PATH_SAFE)


def _normalize_v2_query(query: str, drop_patterns: tuple[str, ...]) -> str:
    if not query:
        return ""
    kept: list[str] = []
    for component in query.split("&"):
        raw_key = component.split("=", 1)[0]
        try:
            key = unquote_plus(raw_key)
        except UnicodeDecodeError:
            key = raw_key
        if _should_drop_query_param(key, drop_patterns):
            continue
        kept.append(quote(_normalize_percent_encoding(component), safe=QUERY_SAFE))
    return "&".join(kept)


def _normalize_percent_encoding(value: str, *, decode_dot: bool = True) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%":
            if index + 2 < len(value) and value[index + 1] in HEX and value[index + 2] in HEX:
                octet = int(value[index + 1 : index + 3], 16)
                decoded = chr(octet)
                if decoded in UNRESERVED and (decode_dot or decoded != "."):
                    output.append(decoded)
                else:
                    output.append(f"%{octet:02X}")
                index += 3
                continue
            output.append("%25")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _remove_literal_dot_segments(path: str) -> str:
    input_buffer = path
    output = ""
    while input_buffer:
        if input_buffer.startswith("../"):
            input_buffer = input_buffer[3:]
        elif input_buffer.startswith("./"):
            input_buffer = input_buffer[2:]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            output = output.rsplit("/", 1)[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output = output.rsplit("/", 1)[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            match = re.match(r"^(/?[^/]*)", input_buffer)
            assert match is not None
            segment = match.group(1)
            output += segment
            input_buffer = input_buffer[len(segment) :]
    return output or "/"


def _should_drop_query_param(key: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("*") and key.startswith(pattern[:-1]):
            return True
        if key == pattern:
            return True
    return False
