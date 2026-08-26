import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_NAMES = {
    "token",
    "access_token",
    "auth",
    "authorization",
    "api_key",
    "apikey",
    "key",
    "signature",
    "sig",
    "secret",
    "password",
    "passwd",
    "session",
    "sessionid",
    "code",
    "credential",
}
REQUEST_HEADERS = {
    "accept",
    "content-type",
    "origin",
    "referer",
    "user-agent",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
}
RESPONSE_HEADERS = {
    "content-type",
    "content-length",
    "content-encoding",
    "cache-control",
    "etag",
    "last-modified",
    "location",
    "retry-after",
    "server",
    "timing-allow-origin",
}
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


def redact_url(url: str) -> tuple[str, str]:
    digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        query = urlencode(
            [
                (name, "[REDACTED]" if name.lower() in SENSITIVE_NAMES else value)
                for name, value in parse_qsl(parts.query, keep_blank_values=True)
            ],
            doseq=True,
        )
        return urlunsplit((parts.scheme, host, parts.path, query, ""))[:4096], digest
    except ValueError:
        return "[invalid URL]", digest


def sanitize_headers(headers: dict[str, str], *, response: bool = False) -> dict[str, str]:
    allowed = RESPONSE_HEADERS if response else REQUEST_HEADERS
    result: dict[str, str] = {}
    for name, value in headers.items():
        key = name.lower()
        if key not in allowed or len(result) >= 32:
            continue
        if key in {"referer", "origin", "location"}:
            value = redact_url(value)[0]
        result[key] = value[:2048]
        if sum(len(k) + len(v) for k, v in result.items()) > 16_384:
            result.pop(key, None)
            break
    return result


def redact_text(value: str, limit: int) -> str:
    return URL_PATTERN.sub(lambda match: redact_url(match.group(0))[0], value)[:limit]
