from dataclasses import dataclass
from io import BytesIO

from lxml import etree


class SitemapParseError(ValueError):
    pass


@dataclass(frozen=True)
class SitemapUrl:
    loc: str
    lastmod: str | None = None
    changefreq: str | None = None
    priority: str | None = None


@dataclass(frozen=True)
class SitemapChild:
    loc: str
    lastmod: str | None = None


@dataclass(frozen=True)
class ParsedSitemap:
    document_type: str
    urls: list[SitemapUrl]
    children: list[SitemapChild]


def parse_sitemap_xml(content: bytes) -> ParsedSitemap:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=False,
    )
    try:
        root = etree.parse(BytesIO(content), parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise SitemapParseError(str(exc)) from exc
    tag = _local_name(root.tag)
    if tag == "urlset":
        return ParsedSitemap(
            document_type="urlset",
            urls=[url for url in (_parse_url(element) for element in root) if url is not None],
            children=[],
        )
    if tag == "sitemapindex":
        return ParsedSitemap(
            document_type="sitemapindex",
            urls=[],
            children=[
                child for child in (_parse_child(element) for element in root) if child is not None
            ],
        )
    raise SitemapParseError(f"Unsupported sitemap root element: {tag}")


def _parse_url(element: etree._Element) -> SitemapUrl | None:
    if _local_name(element.tag) != "url":
        return None
    loc = _child_text(element, "loc")
    if not loc:
        return None
    return SitemapUrl(
        loc=loc,
        lastmod=_child_text(element, "lastmod"),
        changefreq=_child_text(element, "changefreq"),
        priority=_child_text(element, "priority"),
    )


def _parse_child(element: etree._Element) -> SitemapChild | None:
    if _local_name(element.tag) != "sitemap":
        return None
    loc = _child_text(element, "loc")
    if not loc:
        return None
    return SitemapChild(loc=loc, lastmod=_child_text(element, "lastmod"))


def _child_text(element: etree._Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and child.text:
            value = child.text.strip()
            return value or None
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
