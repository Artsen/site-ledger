from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree, html

STRUCTURED_CONTENT_EXTRACTOR_VERSION = "structured-content-v1"
STRUCTURED_CONTENT_CONFIG_VERSION = "default-v1"
MAX_STRUCTURED_SECTIONS = 10_000
MAX_STRUCTURED_CHARACTERS = 2_000_000

_HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}
_EXCLUDED_TAGS = {"head", "script", "style", "template", "svg", "noscript"}
_REGION_TAGS = {"main", "article", "nav", "header", "footer", "aside", "body"}
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "ul",
}
_CELL_TAGS = {"td", "th"}
_SPACE_RE = re.compile(r"[^\S\t\r\n]+", re.UNICODE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass
class ExtractedSection:
    position: int
    parent_position: int | None
    kind: str
    heading_level: int | None
    heading_text: str | None
    heading_dom_path: str | None
    region_key: str
    region_dom_path: str | None
    direct_text: str = ""
    direct_text_sha256: str = ""
    section_sha256: str = ""
    subtree_sha256: str = ""
    direct_word_count: int = 0
    direct_character_count: int = 0
    subtree_word_count: int = 0
    subtree_character_count: int = 0
    child_count: int = 0
    descendant_count: int = 0
    block_count: int = 0
    has_direct_content: bool = False
    _parts: list[str] = field(default_factory=list, repr=False)


@dataclass(frozen=True)
class ExtractedStructuredContent:
    extraction_state: str
    document_profile: str
    sections: tuple[ExtractedSection, ...]
    heading_count: int
    heading_counts: dict[str, int]
    document_word_count: int
    document_character_count: int
    document_text_sha256: str
    outline_sha256: str
    is_truncated: bool
    truncation_reasons: tuple[str, ...]


def extract_structured_content(
    content: bytes,
    *,
    max_sections: int = MAX_STRUCTURED_SECTIONS,
    max_characters: int = MAX_STRUCTURED_CHARACTERS,
) -> ExtractedStructuredContent:
    parser = html.HTMLParser(recover=True, remove_comments=True, huge_tree=False)
    try:
        document = html.document_fromstring(content, parser=parser)
    except (etree.ParserError, ValueError, TypeError):
        return _unavailable_result()

    body = document.find("body")
    root = body if body is not None else document
    sections: list[ExtractedSection] = []
    heading_stack: list[tuple[int, int]] = []
    current: ExtractedSection | None = None
    preamble_parts: list[str] = []
    preamble_node: etree._Element | None = None
    truncation_reasons: list[str] = []
    character_budget = max_characters

    def append_part(part: str, node: etree._Element) -> None:
        nonlocal character_budget, preamble_node
        if not part or character_budget <= 0:
            if part and "character_limit" not in truncation_reasons:
                truncation_reasons.append("character_limit")
            return
        bounded = part[:character_budget]
        character_budget -= len(bounded)
        if len(bounded) < len(part) and "character_limit" not in truncation_reasons:
            truncation_reasons.append("character_limit")
        target = current._parts if current is not None else preamble_parts
        target.append(bounded)
        if current is None and bounded.strip() and preamble_node is None:
            preamble_node = node

    def walk(element: etree._Element) -> bool:
        nonlocal character_budget, current
        tag = _tag_name(element)
        if tag in _EXCLUDED_TAGS:
            return True
        level = _HEADING_LEVELS.get(tag)
        if level is not None:
            preamble_section_count = 1 if preamble_node is not None else 0
            if len(sections) + preamble_section_count >= max_sections:
                if "section_limit" not in truncation_reasons:
                    truncation_reasons.append("section_limit")
                return False
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            parent_position = heading_stack[-1][1] if heading_stack else None
            region_key, region_path = _region(element)
            heading_text = _normalize_inline(_heading_text(element))
            if len(heading_text) > character_budget:
                heading_text = heading_text[:character_budget]
                if "character_limit" not in truncation_reasons:
                    truncation_reasons.append("character_limit")
            character_budget -= len(heading_text)
            current = ExtractedSection(
                position=len(sections),
                parent_position=parent_position,
                kind="heading",
                heading_level=level,
                heading_text=heading_text,
                heading_dom_path=_dom_path(element),
                region_key=region_key,
                region_dom_path=region_path,
            )
            sections.append(current)
            heading_stack.append((level, current.position))
            return True

        if element.text:
            append_part(element.text, element)
        for child in element:
            if not walk(child):
                return False
            if child.tail:
                append_part(child.tail, element)
            child_tag = _tag_name(child)
            if child_tag in _CELL_TAGS:
                append_part("\t", element)
            elif child_tag in _BLOCK_TAGS:
                append_part("\n", element)
        return True

    walk(root)
    preamble_text = _normalize_text("".join(preamble_parts))
    if preamble_text:
        region_key, region_path = _region(preamble_node if preamble_node is not None else root)
        sections.insert(
            0,
            ExtractedSection(
                position=0,
                parent_position=None,
                kind="preamble" if sections else "unheaded",
                heading_level=None,
                heading_text=None,
                heading_dom_path=None,
                region_key=region_key,
                region_dom_path=region_path,
                _parts=[preamble_text],
            ),
        )
        for section in sections[1:]:
            section.position += 1
            if section.parent_position is not None:
                section.parent_position += 1

    _finalize_sections(sections)
    heading_counts = {
        f"h{level}": sum(section.heading_level == level for section in sections)
        for level in range(1, 7)
    }
    heading_count = sum(heading_counts.values())
    document_text = _document_text(sections)
    outline = [
        {
            "kind": section.kind,
            "level": section.heading_level,
            "heading": section.heading_text,
            "parent": section.parent_position,
        }
        for section in sections
    ]
    profile = "headed" if heading_count else ("unheaded" if sections else "empty")
    return ExtractedStructuredContent(
        extraction_state="partial" if truncation_reasons else "ready",
        document_profile=profile,
        sections=tuple(sections),
        heading_count=heading_count,
        heading_counts=heading_counts,
        document_word_count=_word_count(document_text),
        document_character_count=len(document_text),
        document_text_sha256=_sha(document_text),
        outline_sha256=_canonical_sha(outline),
        is_truncated=bool(truncation_reasons),
        truncation_reasons=tuple(truncation_reasons),
    )


def validate_extracted_content(result: ExtractedStructuredContent) -> None:
    positions = [section.position for section in result.sections]
    if positions != list(range(len(result.sections))):
        raise ValueError("Structured section positions are not contiguous.")
    by_position = {section.position: section for section in result.sections}
    for section in result.sections:
        if section.parent_position is not None:
            parent = by_position.get(section.parent_position)
            if parent is None or parent.position >= section.position:
                raise ValueError("Structured section hierarchy is invalid.")
            if not parent.heading_level or not section.heading_level:
                raise ValueError("Only heading sections may participate in hierarchy.")
            if parent.heading_level >= section.heading_level:
                raise ValueError("Structured heading hierarchy is invalid.")
        if section.heading_level is not None and not 1 <= section.heading_level <= 6:
            raise ValueError("Structured heading level is outside h1-h6.")
        if section.direct_text_sha256 != _sha(section.direct_text):
            raise ValueError("Structured direct-text hash is invalid.")
        if section.direct_character_count != len(section.direct_text):
            raise ValueError("Structured direct character count is invalid.")
        if section.direct_word_count != _word_count(section.direct_text):
            raise ValueError("Structured direct word count is invalid.")
        expected_section_sha = _canonical_sha(
            [section.kind, section.heading_level, section.heading_text, section.direct_text]
        )
        if section.section_sha256 != expected_section_sha:
            raise ValueError("Structured section hash is invalid.")
    children: dict[int, list[ExtractedSection]] = {
        section.position: [] for section in result.sections
    }
    for section in result.sections:
        if section.parent_position is not None:
            children[section.parent_position].append(section)
    expected_subtrees: dict[int, tuple[str, int, int, int]] = {}
    for section in reversed(result.sections):
        child_values = [expected_subtrees[child.position] for child in children[section.position]]
        expected = (
            _canonical_sha([section.section_sha256, [value[0] for value in child_values]]),
            section.direct_word_count + sum(value[1] for value in child_values),
            section.direct_character_count + sum(value[2] for value in child_values),
            sum(1 + value[3] for value in child_values),
        )
        expected_subtrees[section.position] = expected
        if (
            section.subtree_sha256,
            section.subtree_word_count,
            section.subtree_character_count,
            section.descendant_count,
        ) != expected:
            raise ValueError("Structured subtree evidence is invalid.")
        if section.child_count != len(children[section.position]):
            raise ValueError("Structured child count is invalid.")
    document_text = _document_text(list(result.sections))
    if result.document_text_sha256 != _sha(document_text):
        raise ValueError("Structured document-text hash is invalid.")
    if result.document_character_count != len(document_text):
        raise ValueError("Structured document character count is invalid.")
    if result.document_word_count != _word_count(document_text):
        raise ValueError("Structured document word count is invalid.")
    heading_counts = {
        f"h{level}": sum(section.heading_level == level for section in result.sections)
        for level in range(1, 7)
    }
    if result.heading_counts != heading_counts or result.heading_count != sum(
        heading_counts.values()
    ):
        raise ValueError("Structured heading counts are invalid.")
    outline = [
        {
            "kind": section.kind,
            "level": section.heading_level,
            "heading": section.heading_text,
            "parent": section.parent_position,
        }
        for section in result.sections
    ]
    if result.outline_sha256 != _canonical_sha(outline):
        raise ValueError("Structured outline hash is invalid.")


def _finalize_sections(sections: list[ExtractedSection]) -> None:
    children: dict[int, list[int]] = {section.position: [] for section in sections}
    for section in sections:
        section.direct_text = _normalize_text("".join(section._parts))
        section.direct_character_count = len(section.direct_text)
        section.direct_word_count = _word_count(section.direct_text)
        section.has_direct_content = bool(section.direct_text)
        section.block_count = len([line for line in section.direct_text.splitlines() if line])
        section.direct_text_sha256 = _sha(section.direct_text)
        section.section_sha256 = _canonical_sha(
            [section.kind, section.heading_level, section.heading_text, section.direct_text]
        )
        if section.parent_position is not None:
            children[section.parent_position].append(section.position)

    by_position = {section.position: section for section in sections}
    for section in reversed(sections):
        child_sections = [by_position[position] for position in children[section.position]]
        section.child_count = len(child_sections)
        section.descendant_count = sum(1 + child.descendant_count for child in child_sections)
        section.subtree_word_count = section.direct_word_count + sum(
            child.subtree_word_count for child in child_sections
        )
        section.subtree_character_count = section.direct_character_count + sum(
            child.subtree_character_count for child in child_sections
        )
        section.subtree_sha256 = _canonical_sha(
            [section.section_sha256, [child.subtree_sha256 for child in child_sections]]
        )


def _document_text(sections: list[ExtractedSection] | tuple[ExtractedSection, ...]) -> str:
    parts: list[str] = []
    for section in sections:
        if section.kind == "heading":
            parts.append(section.heading_text or "")
        if section.direct_text:
            parts.append(section.direct_text)
    return "\n".join(parts)


def _heading_text(element: etree._Element) -> str:
    parts: list[str] = []

    def visit(node: etree._Element) -> None:
        if _tag_name(node) in _EXCLUDED_TAGS:
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(element)
    return " ".join(parts)


def _normalize_inline(value: str) -> str:
    return " ".join(value.split())


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE_RE.sub(" ", line).strip() for line in value.split("\n")]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def _word_count(value: str) -> int:
    return len(value.split())


def _tag_name(element: etree._Element) -> str:
    return element.tag.lower() if isinstance(element.tag, str) else ""


def _region(element: etree._Element) -> tuple[str, str | None]:
    current: etree._Element | None = element
    while current is not None:
        tag = _tag_name(current)
        if tag in _REGION_TAGS:
            return tag, _dom_path(current)
        current = current.getparent()
    return "unknown", None


def _dom_path(element: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = element
    while current is not None and isinstance(current.tag, str):
        tag = current.tag.lower()
        parent = current.getparent()
        if parent is not None:
            siblings = [child for child in parent if _tag_name(child) == tag]
            if len(siblings) > 1:
                tag = f"{tag}:nth-of-type({siblings.index(current) + 1})"
        parts.append(tag)
        current = parent
    return " > ".join(reversed(parts))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _unavailable_result() -> ExtractedStructuredContent:
    empty_sha = _sha("")
    return ExtractedStructuredContent(
        extraction_state="unavailable",
        document_profile="unavailable",
        sections=(),
        heading_count=0,
        heading_counts={f"h{level}": 0 for level in range(1, 7)},
        document_word_count=0,
        document_character_count=0,
        document_text_sha256=empty_sha,
        outline_sha256=_canonical_sha([]),
        is_truncated=False,
        truncation_reasons=(),
    )
