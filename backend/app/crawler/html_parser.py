import hashlib
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urljoin

from lxml import html
from lxml.etree import ParserError

from app.crawler.link_roles import classify_link_role
from app.crawler.resource_classification import classify_reference

LINK_RESOURCE_RELATION_PRECEDENCE = (
    "stylesheet",
    "manifest",
    "apple-touch-icon",
    "mask-icon",
    "icon",
    "modulepreload",
    "preload",
    "alternate",
)


def rel_tokens(value: str | None) -> frozenset[str]:
    return frozenset(token.casefold() for token in value.split()) if value else frozenset()


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
class ResourceReferenceData:
    position: int
    relation_type: str
    element_tag: str
    attribute_name: str
    raw_url: str
    resolved_url: str
    inferred_kind: str
    classification_rule: str
    dom_path: str
    rel: str | None
    media: str | None
    type_hint: str | None
    as_hint: str | None
    srcset_descriptor: str | None
    alt_text: str | None
    title: str | None
    width_attribute: str | None
    height_attribute: str | None
    crossorigin: str | None
    loading: str | None
    context_json: dict[str, Any]


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
    resource_references: list[ResourceReferenceData]


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
                if "canonical" in rel_tokens(item.get("rel")) and item.get("href"):
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

    resource_references = _extract_resource_references(document, base_url)

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
        resource_references=resource_references,
    )


def _extract_resource_references(document: Any, base_url: str) -> list[ResourceReferenceData]:
    references: list[ResourceReferenceData] = []
    for element in cast(
        list[Any],
        document.xpath(
            "//img[@src or @srcset] | //picture/source[@src or @srcset] | "
            "//input[translate(@type,'IMAGE','image')='image'][@src] | //script[@src] | "
            "//link[@href] | //video[@src or @poster] | //audio[@src] | "
            "//video/source[@src or @srcset] | //audio/source[@src or @srcset] | "
            "//track[@src] | //object[@data] | //embed[@src]"
        ),
    ):
        tag = str(element.tag).casefold()
        rel = _as_str(element.get("rel"))
        attributes = _resource_attributes(tag, element, rel)
        for attribute_name, relation_type in attributes:
            raw_value = _as_str(element.get(attribute_name))
            candidates = (
                _parse_srcset(raw_value) if attribute_name == "srcset" else [(raw_value, None)]
            )
            for raw_url, descriptor in candidates:
                if raw_url is None or not _is_resource_url(raw_url):
                    continue
                resolved = urljoin(base_url, raw_url)
                classification = classify_reference(
                    url=resolved,
                    element_tag=tag,
                    attribute_name=attribute_name,
                    rel=rel,
                    as_hint=_as_str(element.get("as")),
                )
                owner = _reference_owner(element)
                references.append(
                    ResourceReferenceData(
                        position=len(references),
                        relation_type=relation_type,
                        element_tag=tag,
                        attribute_name=attribute_name,
                        raw_url=raw_url,
                        resolved_url=resolved,
                        inferred_kind=classification.kind,
                        classification_rule=classification.rule,
                        dom_path=_dom_path(element),
                        rel=rel,
                        media=_as_str(element.get("media")),
                        type_hint=_as_str(element.get("type")),
                        as_hint=_as_str(element.get("as")),
                        srcset_descriptor=descriptor,
                        alt_text=_as_str(owner.get("alt")) if owner is not None else None,
                        title=_as_str(element.get("title")),
                        width_attribute=_as_str(owner.get("width")) if owner is not None else None,
                        height_attribute=_as_str(owner.get("height"))
                        if owner is not None
                        else None,
                        crossorigin=_as_str(element.get("crossorigin")),
                        loading=_as_str(owner.get("loading")) if owner is not None else None,
                        context_json={
                            "owner_tag": str(owner.tag).casefold() if owner is not None else tag
                        },
                    )
                )
    return references


def _resource_attributes(tag: str, element: Any, rel: str | None) -> list[tuple[str, str]]:
    if tag == "link":
        tokens = rel_tokens(rel)
        for relation in LINK_RESOURCE_RELATION_PRECEDENCE:
            if relation in tokens:
                return [("href", relation)]
        return []
    if tag == "object":
        return [("data", "embedded_object")]
    if tag == "video":
        result = []
        if element.get("src") is not None:
            result.append(("src", "video"))
        if element.get("poster") is not None:
            result.append(("poster", "poster"))
        return result
    result = []
    if element.get("src") is not None:
        result.append(("src", _relation_type(tag, element)))
    if element.get("srcset") is not None:
        result.append(("srcset", "responsive_image"))
    return result


def _relation_type(tag: str, element: Any) -> str:
    if tag in {"img", "input"}:
        return "image"
    if tag == "script":
        return "script"
    if tag == "audio":
        return "audio"
    if tag in {"video", "track"}:
        return "video"
    if tag == "source":
        parent = element.getparent()
        return str(parent.tag).casefold() if parent is not None else "media_source"
    if tag == "embed":
        return "embedded_object"
    return "embedded_resource"


def _reference_owner(element: Any) -> Any:
    if str(element.tag).casefold() == "source":
        parent = element.getparent()
        if parent is not None and str(parent.tag).casefold() == "picture":
            images = parent.xpath("./img[1]")
            if images:
                return images[0]
    return element


def _parse_srcset(value: str | None) -> list[tuple[str, str | None]]:
    if not value:
        return []
    candidates: list[tuple[str, str | None]] = []
    for raw_candidate in value.split(","):
        parts = raw_candidate.strip().split()
        if not parts:
            continue
        descriptor = parts[1] if len(parts) == 2 and re_srcset_descriptor(parts[1]) else None
        if len(parts) > 2:
            continue
        candidates.append((parts[0], descriptor))
    return candidates


def re_srcset_descriptor(value: str) -> bool:
    if value.endswith("w"):
        return value[:-1].isdigit() and int(value[:-1]) > 0
    if value.endswith("x"):
        try:
            return float(value[:-1]) > 0
        except ValueError:
            return False
    return False


def _is_resource_url(value: str | None) -> bool:
    if not value:
        return False
    candidate = value.strip()
    return (
        bool(candidate)
        and not candidate.startswith("#")
        and not candidate.casefold().startswith(("data:", "javascript:", "mailto:", "tel:"))
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
