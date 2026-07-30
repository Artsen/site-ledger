import re
from dataclasses import dataclass
from posixpath import normpath
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit


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

    path = _normalize_path(parts.path or "/")
    query = _normalize_query(parts.query, drop_query_params or [])
    netloc = host if port is None else f"{host}:{port}"
    normalized = urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    resolved_without_fragment = urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", parts.query, "")
    )
    return NormalizedUrl(
        raw_url=raw_url,
        resolved_url=resolved_without_fragment,
        normalized_url=normalized,
        scheme=parts.scheme.lower(),
        host=host,
        port=port,
        path=path,
        query=query,
    )


def _normalize_path(path: str) -> str:
    had_trailing = path.endswith("/")
    decoded = unquote(path)
    normalized = normpath(decoded)
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if had_trailing and not normalized.endswith("/"):
        normalized = f"{normalized}/"
    return quote(normalized, safe="/:@!$&'()*+,;=")


def _normalize_query(query: str, drop_patterns: list[str]) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if _should_drop_query_param(key, drop_patterns):
            continue
        kept.append((key, value))
    kept.sort(key=lambda item: (item[0], item[1]))
    return urlencode(kept, doseq=True)


def _should_drop_query_param(key: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("*") and key.startswith(pattern[:-1]):
            return True
        if key == pattern:
            return True
    return False
