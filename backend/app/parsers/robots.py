from dataclasses import dataclass
from urllib.parse import urljoin


@dataclass(frozen=True)
class SitemapDirective:
    raw_value: str
    resolved_url: str


def parse_sitemap_directives(content: bytes, robots_url: str) -> list[SitemapDirective]:
    text = content.decode("utf-8", errors="replace")
    directives: list[SitemapDirective] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        if key.strip().lower() != "sitemap":
            continue
        raw_value = value.strip()
        if not raw_value:
            continue
        resolved = urljoin(robots_url, raw_value)
        if resolved in seen:
            continue
        seen.add(resolved)
        directives.append(SitemapDirective(raw_value=raw_value, resolved_url=resolved))
    return directives
