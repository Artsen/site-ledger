from __future__ import annotations

import hashlib
import html as html_stdlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

from lxml import html

VOLATILE_SENTINEL = "__SITE_LEDGER_VOLATILE__"
INCAPSULA_RULE_ID = "incapsula_script_src_cb_v1"
DOCUMENT_CONTENT_EXTRACTOR_VERSION = "document-content-v2"

_DEFAULT_DOCUMENT_PROFILE = "default_web_document"
_WEB_CONTENT_NOT_FOUND_PROFILE = "web_content_not_found_v1"
_OPERATIONAL_DIAGNOSTIC_SENTINEL = "__SITE_LEDGER_OPERATIONAL_DIAGNOSTIC__"

_SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE | re.DOTALL)
_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE | re.DOTALL)
_RESOURCE_TAG = re.compile(r"<(?:script|link)\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTRIBUTE = re.compile(
    r"(?P<name>[A-Za-z_:][\w:.-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_CB_PARAMETER = re.compile(r"(?P<prefix>[?&](?:amp;)?cb=)(?P<value>[^&#]*)", re.IGNORECASE)
_VER_PARAMETER = re.compile(r"(?P<prefix>[?&](?:amp;)?ver=)(?P<value>[^&#]*)", re.IGNORECASE)
_WORDPRESS_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:[-+][\w.-]+)?$")
_GENERATOR_VERSION = re.compile(r"^(?P<prefix>\s*WordPress\s+)\S+(?P<suffix>\s*)$", re.I)
_SCRIPT_TAG_BYTES = re.compile(rb"<script\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTRIBUTE_BYTES = re.compile(
    rb"(?P<name>[A-Za-z_:][\w:.-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_CB_PARAMETER_BYTES = re.compile(rb"(?P<prefix>[?&](?:amp;)?cb=)(?P<value>[^&#]*)", re.IGNORECASE)


@dataclass(frozen=True)
class SourceAnalysis:
    exact_hash: str
    normalized_source_hash: str
    document_content_hash: str | None
    text: str
    normalized_text: str
    incapsula_cb_values: tuple[str, ...]


def analyze_source(content: bytes, encoding: str | None) -> SourceAnalysis | None:
    try:
        text = content.decode(encoding or "utf-8", errors="strict")
    except (LookupError, UnicodeDecodeError):
        return None
    normalized, _ = normalize_volatile_source(text)
    normalized_bytes, values = _normalize_volatile_source_bytes(content)
    return SourceAnalysis(
        exact_hash=hashlib.sha256(content).hexdigest(),
        normalized_source_hash=hashlib.sha256(normalized_bytes).hexdigest(),
        document_content_hash=_document_content_hash(text),
        text=text,
        normalized_text=normalized,
        incapsula_cb_values=tuple(values),
    )


def normalize_volatile_source(source: str) -> tuple[str, list[str]]:
    values: list[str] = []

    def normalize_script(match: re.Match[str]) -> str:
        tag = match.group(0)
        source_attribute = _attribute_value(tag, "src")
        if source_attribute is None:
            return tag
        decoded_url = html_stdlib.unescape(source_attribute)
        if urlsplit(decoded_url).path != "/_Incapsula_Resource":
            return tag

        def replace_parameter(parameter: re.Match[str]) -> str:
            values.append(html_stdlib.unescape(parameter.group("value")))
            return f"{parameter.group('prefix')}{VOLATILE_SENTINEL}"

        normalized_value, count = _CB_PARAMETER.subn(replace_parameter, source_attribute)
        if not count:
            return tag
        return _replace_attribute_value(tag, "src", normalized_value)

    return _SCRIPT_TAG.sub(normalize_script, source), values


def _normalize_volatile_source_bytes(source: bytes) -> tuple[bytes, list[str]]:
    values: list[str] = []

    def normalize_script(match: re.Match[bytes]) -> bytes:
        tag = match.group(0)
        source_match = next(
            (
                attribute
                for attribute in _ATTRIBUTE_BYTES.finditer(tag)
                if attribute.group("name").lower() == b"src"
            ),
            None,
        )
        if source_match is None:
            return tag
        source_value = source_match.group("value")
        try:
            decoded_url = html_stdlib.unescape(source_value.decode("ascii"))
        except UnicodeDecodeError:
            return tag
        if urlsplit(decoded_url).path != "/_Incapsula_Resource":
            return tag

        def replace_parameter(parameter: re.Match[bytes]) -> bytes:
            values.append(html_stdlib.unescape(parameter.group("value").decode("ascii")))
            return parameter.group("prefix") + VOLATILE_SENTINEL.encode("ascii")

        normalized_value, count = _CB_PARAMETER_BYTES.subn(replace_parameter, source_value)
        if not count:
            return tag
        start, end = source_match.span("value")
        return tag[:start] + normalized_value + tag[end:]

    return _SCRIPT_TAG_BYTES.sub(normalize_script, source), values


def source_difference_categories(
    baseline: SourceAnalysis,
    target: SourceAnalysis,
    *,
    document_changed: bool,
    metadata_changed: bool,
) -> tuple[list[str], list[dict[str, object]]]:
    categories: set[str] = set()
    details: list[dict[str, object]] = []
    volatile_changed = baseline.incapsula_cb_values != target.incapsula_cb_values and bool(
        baseline.incapsula_cb_values or target.incapsula_cb_values
    )
    if volatile_changed:
        categories.update({"runtime", "volatile"})
        details.append(
            {
                "rule_id": INCAPSULA_RULE_ID,
                "category": "volatile",
                "baseline_values": list(baseline.incapsula_cb_values),
                "target_values": list(target.incapsula_cb_values),
            }
        )
    if document_changed:
        categories.add("document_content")
    if metadata_changed:
        categories.add("metadata")

    baseline_dependency, baseline_signals = _normalize_wordpress_dependencies(
        baseline.normalized_text
    )
    target_dependency, target_signals = _normalize_wordpress_dependencies(target.normalized_text)
    dependency_changed = baseline_signals != target_signals and bool(
        baseline_signals or target_signals
    )
    if dependency_changed:
        categories.add("dependency")
        details.append(
            {
                "rule_id": "wordpress_dependency_version_v1",
                "category": "dependency",
                "baseline_signals": baseline_signals,
                "target_signals": target_signals,
            }
        )

    if baseline.normalized_source_hash != target.normalized_source_hash:
        residual_changed = baseline_dependency != target_dependency
        if residual_changed and not document_changed and not metadata_changed:
            categories.add("unclassified")
    return sorted(categories), details


def _normalize_wordpress_dependencies(source: str) -> tuple[str, list[str]]:
    signals: list[str] = []

    def normalize_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        if (_attribute_value(tag, "name") or "").casefold() != "generator":
            return tag
        content = _attribute_value(tag, "content")
        version = _GENERATOR_VERSION.match(content or "")
        if version is None:
            return tag
        signals.append(f"generator:{(content or '').strip()}")
        return _replace_attribute_value(
            tag,
            "content",
            f"{version.group('prefix')}__SITE_LEDGER_DEPENDENCY_VERSION__{version.group('suffix')}",
        )

    normalized = _META_TAG.sub(normalize_meta, source)

    def normalize_resource(match: re.Match[str]) -> str:
        tag = match.group(0)
        attribute_name = "src" if tag[1:7].casefold().startswith("script") else "href"
        value = _attribute_value(tag, attribute_name)
        if value is None:
            return tag
        decoded = html_stdlib.unescape(value)
        if "/wp-" not in urlsplit(decoded).path.casefold():
            return tag

        def replace_version(parameter: re.Match[str]) -> str:
            version = html_stdlib.unescape(parameter.group("value"))
            if not _WORDPRESS_VERSION.match(version):
                return parameter.group(0)
            signals.append(f"asset:{urlsplit(decoded).path}?ver={version}")
            return f"{parameter.group('prefix')}__SITE_LEDGER_DEPENDENCY_VERSION__"

        replaced = _VER_PARAMETER.sub(replace_version, value)
        return _replace_attribute_value(tag, attribute_name, replaced)

    return _RESOURCE_TAG.sub(normalize_resource, normalized), sorted(signals)


def _document_content_hash(source: str) -> str | None:
    try:
        document = html.fromstring(source)
    except (ValueError, TypeError):
        return None
    elements = cast(
        list[html.HtmlElement], document.xpath("//script|//style|//noscript|//template|//svg")
    )
    for element in elements:
        element.drop_tree()
    profile = _identify_document_profile(document)
    if profile == _WEB_CONTENT_NOT_FOUND_PROFILE:
        _replace_web_content_not_found_diagnostics(document)
    body = document.find("body")
    root = body if body is not None else document
    text = " ".join(" ".join(cast(Iterable[str], root.itertext())).split())
    return _text_hash(html_stdlib.unescape(text))


def _identify_document_profile(document: html.HtmlElement) -> str:
    root_children = _element_children(document)
    titles = document.xpath("/html/head/title")
    bodies = document.xpath("/html/body")
    if (
        document.tag.casefold() != "html"
        or document.attrib
        or [child.tag.casefold() for child in root_children] != ["head", "body"]
        or len(titles) != 1
        or len(bodies) != 1
    ):
        return _DEFAULT_DOCUMENT_PROFILE
    head = root_children[0]
    title = cast(html.HtmlElement, titles[0])
    if (
        head.attrib
        or [child.tag.casefold() for child in _element_children(head)] != ["title"]
        or title.attrib
        or len(title)
        or _element_text(title) != "WebContentNotFound"
    ):
        return _DEFAULT_DOCUMENT_PROFILE

    body = cast(html.HtmlElement, bodies[0])
    children = _element_children(body)
    if (
        body.attrib
        or [child.tag.casefold() for child in children] != ["h1", "p", "ul"]
        or not _inter_element_text_is_whitespace(body)
    ):
        return _DEFAULT_DOCUMENT_PROFILE
    heading, paragraph, error_list = children
    if (
        heading.attrib
        or len(heading)
        or _element_text(heading) != ("The requested content does not exist.")
    ):
        return _DEFAULT_DOCUMENT_PROFILE
    if paragraph.attrib or _element_text(paragraph) or len(paragraph) or error_list.attrib:
        return _DEFAULT_DOCUMENT_PROFILE

    fields = _element_children(error_list)
    if (
        len(fields) != 4
        or not _inter_element_text_is_whitespace(error_list)
        or any(child.tag.casefold() != "li" or child.attrib or len(child) for child in fields)
    ):
        return _DEFAULT_DOCUMENT_PROFILE
    values = [_element_text(field) for field in fields]
    if values[:2] != ["HttpStatusCode: 404", "ErrorCode: WebContentNotFound"]:
        return _DEFAULT_DOCUMENT_PROFILE
    if not _diagnostic_value(values[2], "RequestId") or not _diagnostic_value(
        values[3], "TimeStamp"
    ):
        return _DEFAULT_DOCUMENT_PROFILE
    return _WEB_CONTENT_NOT_FOUND_PROFILE


def _replace_web_content_not_found_diagnostics(document: html.HtmlElement) -> None:
    fields = cast(list[html.HtmlElement], document.xpath("/html/body/ul/li"))
    for field, label in zip(fields[2:], ("RequestId", "TimeStamp"), strict=True):
        field.text = f"{label} : {_OPERATIONAL_DIAGNOSTIC_SENTINEL}"


def _element_text(element: html.HtmlElement) -> str:
    return " ".join(" ".join(cast(Iterable[str], element.itertext())).split())


def _element_children(element: html.HtmlElement) -> list[html.HtmlElement]:
    return [child for child in element if isinstance(child.tag, str)]


def _inter_element_text_is_whitespace(element: html.HtmlElement) -> bool:
    return not (element.text or "").strip() and all(
        not (child.tail or "").strip() for child in element
    )


def _diagnostic_value(text: str, label: str) -> str | None:
    match = re.fullmatch(rf"{re.escape(label)}\s*:\s*(\S.*)", text)
    return match.group(1) if match else None


def _attribute_value(tag: str, name: str) -> str | None:
    for match in _ATTRIBUTE.finditer(tag):
        if match.group("name").casefold() == name.casefold():
            return match.group("value")
    return None


def _replace_attribute_value(tag: str, name: str, value: str) -> str:
    for match in _ATTRIBUTE.finditer(tag):
        if match.group("name").casefold() == name.casefold():
            start, end = match.span("value")
            return f"{tag[:start]}{value}{tag[end:]}"
    return tag


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
