from urllib.parse import urlsplit, urlunsplit


def normalize_site_base_url(value: str) -> str:
    raw = value.strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("Site base URL must use HTTP or HTTPS.")
    if not parts.hostname:
        raise ValueError("Site base URL must include a hostname.")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    netloc = host
    if parts.port and not (
        (parts.scheme == "http" and parts.port == 80)
        or (parts.scheme == "https" and parts.port == 443)
    ):
        netloc = f"{host}:{parts.port}"
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))
