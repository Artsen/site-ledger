import hashlib
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urljoin

from lxml import html
from lxml.etree import ParserError

from app.crawler.link_roles import classify_link_role


@dataclass(frozen=True)
class AnchorData:
    raw_href: str | None
    resolved_url: str | None
    anchor_text: str | None
    title: str | None
    aria_label: str | None
    rel: str | None
    target: str | None
    dom_path: str
    link_role: str
    link_role_rule: str
    link_context_json: dict[str, Any]


@dataclass(frozen=True)
class ParsedHtml:
    html_language: str | None
    title: str | None
    meta_description: str | None
    meta_robots: str | None
    canonical_url: str | None
    encoding: str | None
    viewport: str | None
    head_json: dict[str, Any]
    head_sha256: str
    anchors: list[AnchorData]


def parse_html(content: bytes, base_url: str) -> ParsedHtml:
    parser = html.HTMLParser(encoding=None, recover=True)
    try:
        document: Any = html.fromstring(content, parser=parser, base_url=base_url)
    except ParserError:
        document = html.fromstring(
            b"<html><head></head><body></body></html>", parser=parser, base_url=base_url
        )
    head: Any | None = document.find("head")
    html_element = document if document.tag.lower() == "html" else document.find("html")
    language = _as_str(html_element.get("lang")) if html_element is not None else None
    title = _first_text(cast(list[Any], head.xpath(".//title")) if head is not None else [])
    metas: list[dict[str, str | None]] = []
    links: list[dict[str, str | None]] = []
    ordered: list[dict[str, Any]] = []
    og: dict[str, str] = {}
    twitter: dict[str, str] = {}
    json_ld: list[str] = []
    meta_description = None
    meta_robots = None
    viewport = None
    canonical = None

    if head is not None:
        for child in head.iterchildren():
            tag = child.tag.lower() if isinstance(child.tag, str) else ""
            if tag == "meta":
                item = _attributes(child)
                metas.append(item)
                ordered.append({"tag": "meta", "attributes": item})
                name = (item.get("name") or item.get("property") or "").lower()
                content_value = item.get("content")
                if name == "description":
                    meta_description = content_value
                elif name == "robots":
                    meta_robots = content_value
                elif name == "viewport":
                    viewport = content_value
                elif name.startswith("og:") and content_value is not None:
                    og[name] = content_value
                elif name.startswith("twitter:") and content_value is not None:
                    twitter[name] = content_value
            elif tag == "link":
                item = _attributes(child)
                links.append(item)
                ordered.append({"tag": "link", "attributes": item})
                if (item.get("rel") or "").lower() == "canonical" and item.get("href"):
                    canonical = urljoin(base_url, item["href"])
            elif tag == "script" and (child.get("type") or "").lower() == "application/ld+json":
                text = child.text_content()
                json_ld.append(text)
                ordered.append({"tag": "script", "type": "application/ld+json", "text": text})
            elif tag == "title":
                ordered.append({"tag": "title", "text": child.text_content()})

    anchors: list[AnchorData] = []
    for anchor in cast(list[Any], document.xpath("//a")):
        raw_href = _as_str(anchor.get("href"))
        resolved = urljoin(base_url, raw_href) if raw_href else None
        link_role = classify_link_role(anchor, resolved)
        anchors.append(
            AnchorData(
                raw_href=raw_href,
                resolved_url=resolved,
                anchor_text=" ".join(anchor.text_content().split()) or None,
                title=_as_str(anchor.get("title")),
                aria_label=_as_str(anchor.get("aria-label")),
                rel=_as_str(anchor.get("rel")),
                target=_as_str(anchor.get("target")),
                dom_path=_dom_path(anchor),
                link_role=link_role.role,
                link_role_rule=link_role.rule,
                link_context_json=link_role.context,
            )
        )

    doc_encoding = _as_str(document.getroottree().docinfo.encoding)
    head_json = {
        "encoding": doc_encoding,
        "viewport": viewport,
        "meta": metas,
        "links": links,
        "open_graph": og,
        "twitter": twitter,
        "json_ld": json_ld,
        "ordered": ordered,
    }
    head_bytes = html.tostring(head, encoding="utf-8") if head is not None else b""
    return ParsedHtml(
        html_language=language,
        title=title,
        meta_description=meta_description,
        meta_robots=meta_robots,
        canonical_url=canonical,
        encoding=doc_encoding,
        viewport=viewport,
        head_json=head_json,
        head_sha256=hashlib.sha256(head_bytes).hexdigest(),
        anchors=anchors,
    )


def _first_text(nodes: list[Any]) -> str | None:
    if not nodes:
        return None
    text = " ".join(nodes[0].text_content().split())
    return text or None


def _attributes(element: Any) -> dict[str, str | None]:
    return {_as_required_str(key).lower(): _as_str(value) for key, value in element.attrib.items()}


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _as_required_str(value: object) -> str:
    return _as_str(value) or ""


def _dom_path(element: Any) -> str:
    parts: list[str] = []
    current = element
    while current is not None and isinstance(current.tag, str):
        tag = current.tag.lower()
        parent = current.getparent()
        if parent is not None:
            siblings = [
                node for node in parent if isinstance(node.tag, str) and node.tag.lower() == tag
            ]
            if len(siblings) > 1:
                tag = f"{tag}:nth-of-type({siblings.index(current) + 1})"
        parts.append(tag)
        current = parent
    return " > ".join(reversed(parts))
