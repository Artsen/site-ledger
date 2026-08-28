from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from lxml import etree, html

STRUCTURED_CONTENT_EXTRACTOR_VERSION = "structured-content-v2"
STRUCTURED_CONTENT_CONFIG_VERSION = "canonical-document-v1"
STRUCTURED_MARKDOWN_RENDERER_VERSION = "structured-markdown-v1"

MAX_STRUCTURAL_NODES = 50_000
MAX_STRUCTURED_CHARACTERS = 2_000_000
MAX_INLINE_RUNS = 100_000
MAX_DOCUMENT_DEPTH = 128
MAX_ATTRIBUTES_PER_NODE = 32
MAX_ATTRIBUTE_CHARACTERS = 8_192

STRUCTURAL_NODE_KINDS = {
    "document",
    "section",
    "heading",
    "paragraph",
    "list",
    "list_item",
    "figure",
    "caption",
    "blockquote",
    "code_block",
    "table",
    "table_row",
    "table_cell",
    "definition_list",
    "definition_term",
    "definition_description",
    "thematic_break",
    "generic_block",
}

_EXCLUDED = {"head", "script", "style", "template", "noscript", "svg"}
_REGIONS = {"main", "article", "nav", "header", "footer", "aside", "body"}
_CONTAINERS = {
    "html",
    "body",
    "main",
    "article",
    "nav",
    "header",
    "footer",
    "aside",
    "section",
    "div",
}
_INLINE_CONTAINERS = {"span", "small", "mark", "abbr", "cite", "q", "time", "label", "bdi", "bdo"}
_ATTRIBUTES = {
    "href",
    "src",
    "alt",
    "title",
    "rel",
    "target",
    "width",
    "height",
    "start",
    "type",
    "scope",
    "colspan",
    "rowspan",
    "id",
    "class",
}
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"\S+")
_BACKTICKS = re.compile(r"`+")


@dataclass
class CanonicalNode:
    kind: str
    source_tag: str | None = None
    source_dom_path: str | None = None
    region_key: str = "unknown"
    region_dom_path: str | None = None
    text: str | None = None
    inline: list[dict[str, Any]] = field(default_factory=list)
    source_attributes: dict[str, str] = field(default_factory=dict)
    semantic: dict[str, Any] = field(default_factory=dict)
    children: list[CanonicalNode] = field(default_factory=list)
    position: int = -1
    parent_position: int | None = None
    depth: int = 0
    semantic_sha256: str = ""
    subtree_sha256: str = ""
    child_count: int = 0
    descendant_count: int = 0


@dataclass(frozen=True)
class CanonicalDocument:
    extraction_state: str
    document_profile: str
    nodes: tuple[CanonicalNode, ...]
    heading_count: int
    heading_counts: dict[str, int]
    document_word_count: int
    document_character_count: int
    document_text_sha256: str
    outline_sha256: str
    canonical_document_sha256: str
    markdown: str
    markdown_sha256: str
    is_truncated: bool
    truncation_reasons: tuple[str, ...]


class _Builder:
    def __init__(self, max_nodes: int, max_characters: int, max_inline_runs: int, max_depth: int):
        self.max_nodes = max_nodes
        self.characters_left = max_characters
        self.inline_runs_left = max_inline_runs
        self.max_depth = max_depth
        self.node_count = 1
        self.reasons: list[str] = []
        self.root = CanonicalNode(kind="document", source_tag="body", region_key="body")
        self.section_stack: list[tuple[int, CanonicalNode]] = []
        self.current_section: CanonicalNode | None = None

    def reason(self, value: str) -> None:
        if value not in self.reasons:
            self.reasons.append(value)

    def add(self, parent: CanonicalNode, node: CanonicalNode, depth: int) -> CanonicalNode | None:
        if self.node_count >= self.max_nodes:
            self.reason("node_limit")
            return None
        if depth > self.max_depth:
            self.reason("depth_limit")
            return None
        parent.children.append(node)
        self.node_count += 1
        return node

    def bounded_text(self, value: str, *, prose: bool = True) -> str:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        if prose:
            value = _SPACE.sub(" ", value).strip()
        if not value:
            return ""
        bounded = value[: self.characters_left]
        self.characters_left -= len(bounded)
        if len(bounded) < len(value):
            self.reason("character_limit")
        return bounded

    def bounded_inline(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bounded: list[dict[str, Any]] = []
        for run in runs:
            if self.inline_runs_left <= 0:
                self.reason("inline_run_limit")
                break
            self.inline_runs_left -= 1
            retained = dict(run)
            nested = retained.get("runs")
            if isinstance(nested, list):
                retained["runs"] = self.bounded_inline(nested)
            bounded.append(retained)
        return bounded


def extract_canonical_document(
    content: bytes,
    *,
    max_nodes: int = MAX_STRUCTURAL_NODES,
    max_characters: int = MAX_STRUCTURED_CHARACTERS,
    max_inline_runs: int = MAX_INLINE_RUNS,
    max_depth: int = MAX_DOCUMENT_DEPTH,
) -> CanonicalDocument:
    parser = html.HTMLParser(recover=True, remove_comments=True, huge_tree=False)
    try:
        parsed = html.document_fromstring(content, parser=parser)
    except (etree.ParserError, ValueError, TypeError):
        return _empty_document("unavailable")
    body = parsed.find("body")
    root_element = body if body is not None else parsed
    builder = _Builder(max_nodes, max_characters, max_inline_runs, max_depth)
    builder.root.source_dom_path = _dom_path(root_element)
    builder.root.region_dom_path = builder.root.source_dom_path
    _walk_container(builder, root_element, builder.root, "body", builder.root.region_dom_path, 1)
    _flatten_and_hash(builder.root)
    nodes = tuple(_preorder(builder.root))
    headings = [node for node in nodes if node.kind == "heading"]
    heading_counts = {
        f"h{level}": sum(node.semantic.get("level") == level for node in headings)
        for level in range(1, 7)
    }
    document_text = _document_text(nodes)
    outline = [
        {
            "level": node.semantic.get("level"),
            "text": node.text or "",
            "section_parent": node.parent_position,
        }
        for node in headings
    ]
    markdown = render_markdown(nodes)
    profile = "headed" if headings else ("unheaded" if len(nodes) > 1 else "empty")
    return CanonicalDocument(
        extraction_state="partial" if builder.reasons else "ready",
        document_profile=profile,
        nodes=nodes,
        heading_count=len(headings),
        heading_counts=heading_counts,
        document_word_count=len(_WORD.findall(document_text)),
        document_character_count=len(document_text),
        document_text_sha256=_sha(document_text),
        outline_sha256=_canonical_sha(outline),
        canonical_document_sha256=builder.root.subtree_sha256,
        markdown=markdown,
        markdown_sha256=_sha(markdown),
        is_truncated=bool(builder.reasons),
        truncation_reasons=tuple(builder.reasons),
    )


def validate_canonical_document(document: CanonicalDocument) -> None:
    if [node.position for node in document.nodes] != list(range(len(document.nodes))):
        raise ValueError("Canonical node positions are not contiguous.")
    by_position = {node.position: node for node in document.nodes}
    for node in document.nodes:
        if node.kind not in STRUCTURAL_NODE_KINDS:
            raise ValueError(f"Unknown canonical node kind: {node.kind}")
        if node.parent_position is not None:
            parent = by_position.get(node.parent_position)
            if parent is None or parent.position >= node.position:
                raise ValueError("Canonical node hierarchy is invalid.")
        if node.semantic_sha256 != canonical_semantic_sha256(node):
            raise ValueError("Canonical node semantic hash is invalid.")
        child_hashes = [
            child.subtree_sha256
            for child in document.nodes
            if child.parent_position == node.position
        ]
        if node.subtree_sha256 != canonical_subtree_sha256(node.semantic_sha256, child_hashes):
            raise ValueError("Canonical subtree hash is invalid.")
    if not document.nodes or document.canonical_document_sha256 != document.nodes[0].subtree_sha256:
        raise ValueError("Canonical document hash is invalid.")
    markdown = render_markdown(document.nodes)
    if document.markdown != markdown or document.markdown_sha256 != _sha(markdown):
        raise ValueError("Structured Markdown evidence is invalid.")


def _walk_container(
    builder: _Builder,
    element: etree._Element,
    parent: CanonicalNode,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    if element.text and element.text.strip():
        _add_text_paragraph(builder, parent, element.text, element, region, region_path, depth)
    for child in element:
        _walk_element(builder, child, parent, region, region_path, depth)
        if child.tail and child.tail.strip():
            target = (
                builder.current_section
                if parent.kind == "document" and builder.current_section
                else parent
            )
            _add_text_paragraph(builder, target, child.tail, element, region, region_path, depth)


def _walk_element(
    builder: _Builder,
    element: etree._Element,
    parent: CanonicalNode,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    tag = _tag(element)
    if not tag or tag in _EXCLUDED:
        return
    if tag in _REGIONS:
        target = (
            builder.current_section
            if parent.kind == "document" and builder.current_section
            else parent
        )
        _walk_container(builder, element, target, tag, _dom_path(element), depth + 1)
        return
    if tag in {f"h{level}" for level in range(1, 7)}:
        _add_heading(builder, element, int(tag[1]), region, region_path, depth)
        return
    target = (
        builder.current_section or _ensure_preamble(builder, region, region_path, depth)
        if parent.kind == "document"
        else parent
    )
    if tag in {"html", "body", "section", "div"}:
        _walk_container(builder, element, target, region, region_path, depth + 1)
    elif tag == "p":
        _add_inline_block(builder, target, "paragraph", element, region, region_path, depth)
    elif tag in {"ul", "ol"}:
        _add_list(builder, target, element, region, region_path, depth)
    elif tag == "figure":
        _add_figure(builder, target, element, region, region_path, depth)
    elif tag == "figcaption":
        _add_inline_block(builder, target, "caption", element, region, region_path, depth)
    elif tag == "blockquote":
        _add_container_block(builder, target, "blockquote", element, region, region_path, depth)
    elif tag == "pre":
        text = builder.bounded_text(_element_text(element), prose=False)
        _add_simple(
            builder,
            target,
            "code_block",
            element,
            region,
            region_path,
            depth,
            text=text,
            semantic={"language": _code_language(element)},
        )
    elif tag == "table":
        _add_table(builder, target, element, region, region_path, depth)
    elif tag == "dl":
        _add_definition_list(builder, target, element, region, region_path, depth)
    elif tag == "hr":
        _add_simple(builder, target, "thematic_break", element, region, region_path, depth)
    elif tag == "br":
        _add_inline_node_paragraph(
            builder, target, [{"kind": "line_break"}], element, region, region_path, depth
        )
    elif tag in _INLINE_CONTAINERS or tag in {"a", "img", "code", "strong", "b", "em", "i"}:
        _add_inline_node_paragraph(
            builder,
            target,
            _inline_runs(builder, element, wrap_root=True),
            element,
            region,
            region_path,
            depth,
        )
    else:
        _add_container_block(
            builder,
            target,
            "generic_block",
            element,
            region,
            region_path,
            depth,
            semantic={"source_tag": tag},
        )


def _ensure_preamble(
    builder: _Builder, region: str, region_path: str | None, depth: int
) -> CanonicalNode:
    if builder.current_section is None:
        section = CanonicalNode(
            kind="section",
            region_key=region,
            region_dom_path=region_path,
            semantic={"section_kind": "preamble"},
        )
        builder.current_section = builder.add(builder.root, section, depth)
    return builder.current_section or builder.root


def _add_heading(
    builder: _Builder,
    element: etree._Element,
    level: int,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    while builder.section_stack and builder.section_stack[-1][0] >= level:
        builder.section_stack.pop()
    parent = builder.section_stack[-1][1] if builder.section_stack else builder.root
    section = CanonicalNode(
        kind="section",
        region_key=region,
        region_dom_path=region_path,
        semantic={"section_kind": "heading", "level": level},
    )
    added = builder.add(parent, section, depth)
    if added is None:
        return
    heading = CanonicalNode(
        kind="heading",
        source_tag=_tag(element),
        source_dom_path=_dom_path(element),
        region_key=region,
        region_dom_path=region_path,
        inline=builder.bounded_inline(_inline_runs(builder, element)),
        source_attributes=_attributes(builder, element),
        semantic={"level": level},
    )
    heading.text = _inline_text(heading.inline)
    builder.add(added, heading, depth + 1)
    builder.section_stack.append((level, added))
    builder.current_section = added


def _add_inline_block(
    builder: _Builder,
    parent: CanonicalNode,
    kind: str,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> CanonicalNode | None:
    runs = builder.bounded_inline(_inline_runs(builder, element))
    return _add_simple(
        builder,
        parent,
        kind,
        element,
        region,
        region_path,
        depth,
        text=_inline_text(runs),
        inline=runs,
    )


def _add_inline_node_paragraph(
    builder: _Builder,
    parent: CanonicalNode,
    runs: list[dict[str, Any]],
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    runs = builder.bounded_inline(runs)
    _add_simple(
        builder,
        parent,
        "paragraph",
        element,
        region,
        region_path,
        depth,
        text=_inline_text(runs),
        inline=runs,
    )


def _add_text_paragraph(
    builder: _Builder,
    parent: CanonicalNode,
    value: str,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    text = builder.bounded_text(value)
    if text:
        target = (
            builder.current_section or _ensure_preamble(builder, region, region_path, depth)
            if parent.kind == "document"
            else parent
        )
        _add_simple(
            builder,
            target,
            "paragraph",
            element,
            region,
            region_path,
            depth,
            text=text,
            inline=[{"kind": "text", "text": text}],
        )


def _add_simple(
    builder: _Builder,
    parent: CanonicalNode,
    kind: str,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
    *,
    text: str | None = None,
    inline: list[dict[str, Any]] | None = None,
    semantic: dict[str, Any] | None = None,
) -> CanonicalNode | None:
    node = CanonicalNode(
        kind=kind,
        source_tag=_tag(element),
        source_dom_path=_dom_path(element),
        region_key=region,
        region_dom_path=region_path,
        text=text,
        inline=inline or [],
        source_attributes=_attributes(builder, element),
        semantic=semantic or {},
    )
    return builder.add(parent, node, depth)


def _add_container_block(
    builder: _Builder,
    parent: CanonicalNode,
    kind: str,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
    semantic: dict[str, Any] | None = None,
) -> None:
    node = _add_simple(
        builder, parent, kind, element, region, region_path, depth, semantic=semantic
    )
    if node is not None:
        _walk_container(builder, element, node, region, region_path, depth + 1)


def _add_list(
    builder: _Builder,
    parent: CanonicalNode,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    ordered = _tag(element) == "ol"
    start = _integer(element.get("start"), 1)
    node = _add_simple(
        builder,
        parent,
        "list",
        element,
        region,
        region_path,
        depth,
        semantic={"ordered": ordered, "start": start},
    )
    if node is None:
        return
    for child in element:
        if _tag(child) != "li":
            continue
        item = _add_simple(builder, node, "list_item", child, region, region_path, depth + 1)
        if item is None:
            continue
        runs = _inline_runs(builder, child, skip_tags={"ul", "ol"})
        if runs:
            _add_inline_node_paragraph(builder, item, runs, child, region, region_path, depth + 2)
        for nested in child:
            if _tag(nested) in {"ul", "ol"}:
                _add_list(builder, item, nested, region, region_path, depth + 2)


def _add_figure(
    builder: _Builder,
    parent: CanonicalNode,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    figure = _add_simple(builder, parent, "figure", element, region, region_path, depth)
    if figure is None:
        return
    for child in element:
        tag = _tag(child)
        if tag == "figcaption":
            _add_inline_block(builder, figure, "caption", child, region, region_path, depth + 1)
        elif tag == "img":
            _add_inline_node_paragraph(
                builder, figure, _inline_runs(builder, child), child, region, region_path, depth + 1
            )
        else:
            _walk_element(builder, child, figure, region, region_path, depth + 1)


def _add_table(
    builder: _Builder,
    parent: CanonicalNode,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    table = _add_simple(builder, parent, "table", element, region, region_path, depth)
    if table is None:
        return
    rows = cast(list[etree._Element], element.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr"))
    for row_element in rows:
        row = _add_simple(builder, table, "table_row", row_element, region, region_path, depth + 1)
        if row is None:
            continue
        for cell_element in row_element:
            if _tag(cell_element) not in {"th", "td"}:
                continue
            semantic = {
                "header": _tag(cell_element) == "th",
                "scope": cell_element.get("scope"),
                "colspan": _integer(cell_element.get("colspan"), 1),
                "rowspan": _integer(cell_element.get("rowspan"), 1),
            }
            runs = builder.bounded_inline(_inline_runs(builder, cell_element))
            _add_simple(
                builder,
                row,
                "table_cell",
                cell_element,
                region,
                region_path,
                depth + 2,
                text=_inline_text(runs),
                inline=runs,
                semantic=semantic,
            )


def _add_definition_list(
    builder: _Builder,
    parent: CanonicalNode,
    element: etree._Element,
    region: str,
    region_path: str | None,
    depth: int,
) -> None:
    definition = _add_simple(
        builder, parent, "definition_list", element, region, region_path, depth
    )
    if definition is None:
        return
    for child in element:
        kind = (
            "definition_term"
            if _tag(child) == "dt"
            else "definition_description"
            if _tag(child) == "dd"
            else None
        )
        if kind:
            _add_inline_block(builder, definition, kind, child, region, region_path, depth + 1)


def _inline_runs(
    builder: _Builder,
    element: etree._Element,
    *,
    skip_tags: set[str] | None = None,
    wrap_root: bool = False,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    skip_tags = skip_tags or set()

    def text_run(value: str | None, prose: bool = True) -> None:
        raw = (value or "").replace("\r\n", "\n").replace("\r", "\n")
        normalized = _SPACE.sub(" ", raw) if prose else raw
        text = builder.bounded_text(normalized, prose=False)
        if not text:
            return
        if runs and runs[-1].get("kind") == "text":
            runs[-1]["text"] = f"{runs[-1]['text']}{text}"
        else:
            runs.append({"kind": "text", "text": text})

    def visit(node: etree._Element) -> None:
        tag = _tag(node)
        if tag in _EXCLUDED or tag in skip_tags:
            return
        if tag == "img":
            runs.append(
                {
                    "kind": "image",
                    "src": node.get("src") or "",
                    "alt": node.get("alt") or "",
                    "title": node.get("title"),
                }
            )
            return
        if tag == "br":
            runs.append({"kind": "line_break"})
            return
        if tag == "a":
            nested = _inline_runs(builder, node)
            runs.append(
                {
                    "kind": "link",
                    "href": node.get("href") or "",
                    "title": node.get("title"),
                    "rel": _tokens(node.get("rel")),
                    "target": node.get("target"),
                    "runs": nested,
                }
            )
            return
        if tag == "code" and _tag(node.getparent()) != "pre":
            runs.append(
                {
                    "kind": "inline_code",
                    "text": builder.bounded_text(_element_text(node), prose=False),
                }
            )
            return
        if tag in {"strong", "b", "em", "i"}:
            runs.append(
                {
                    "kind": "strong" if tag in {"strong", "b"} else "emphasis",
                    "runs": _inline_runs(builder, node),
                }
            )
            return
        text_run(node.text)
        for child in node:
            visit(child)
            text_run(child.tail)

    root_tag = _tag(element)
    if root_tag == "img":
        return [
            {
                "kind": "image",
                "src": element.get("src") or "",
                "alt": element.get("alt") or "",
                "title": element.get("title"),
            }
        ]
    if root_tag == "br":
        return [{"kind": "line_break"}]
    if wrap_root and root_tag == "a":
        return [
            {
                "kind": "link",
                "href": element.get("href") or "",
                "title": element.get("title"),
                "rel": _tokens(element.get("rel")),
                "target": element.get("target"),
                "runs": _inline_runs(builder, element),
            }
        ]
    if root_tag == "code" and _tag(element.getparent()) != "pre":
        return [
            {
                "kind": "inline_code",
                "text": builder.bounded_text(_element_text(element), prose=False),
            }
        ]
    if wrap_root and root_tag in {"strong", "b", "em", "i"}:
        return [
            {
                "kind": "strong" if root_tag in {"strong", "b"} else "emphasis",
                "runs": _inline_runs(builder, element),
            }
        ]
    text_run(element.text)
    for child in element:
        visit(child)
        text_run(child.tail)
    return runs


def _attributes(builder: _Builder, element: etree._Element) -> dict[str, str]:
    result: dict[str, str] = {}
    characters = 0
    for key in sorted(element.attrib):
        normalized = key.lower()
        if normalized not in _ATTRIBUTES:
            continue
        value = str(element.attrib[key]).replace("\r\n", "\n").replace("\r", "\n")
        if (
            len(result) >= MAX_ATTRIBUTES_PER_NODE
            or characters + len(normalized) + len(value) > MAX_ATTRIBUTE_CHARACTERS
        ):
            builder.reason("source_attribute_limit")
            break
        result[normalized] = value
        characters += len(normalized) + len(value)
    return result


def _flatten_and_hash(root: CanonicalNode) -> None:
    position = 0

    def assign(node: CanonicalNode, parent: int | None, depth: int) -> None:
        nonlocal position
        node.position = position
        node.parent_position = parent
        node.depth = depth
        position += 1
        for child in node.children:
            assign(child, node.position, depth + 1)

    def finish(node: CanonicalNode) -> tuple[str, int]:
        descendant_count = 0
        child_hashes: list[str] = []
        for child in node.children:
            child_hash, descendants = finish(child)
            child_hashes.append(child_hash)
            descendant_count += 1 + descendants
        node.child_count = len(node.children)
        node.descendant_count = descendant_count
        node.semantic_sha256 = _canonical_sha(_semantic_payload(node))
        node.subtree_sha256 = _canonical_sha([node.semantic_sha256, child_hashes])
        return node.subtree_sha256, descendant_count

    assign(root, None, 0)
    finish(root)


def _semantic_payload(node: Any) -> dict[str, Any]:
    return {
        "kind": node.kind,
        "text": node.text,
        "inline": list(node.inline_json if hasattr(node, "inline_json") else node.inline),
        "semantic": dict(node.semantic_json if hasattr(node, "semantic_json") else node.semantic),
    }


def canonical_semantic_sha256(node: Any) -> str:
    return _canonical_sha(_semantic_payload(node))


def canonical_subtree_sha256(semantic_sha256: str, child_hashes: Sequence[str]) -> str:
    return _canonical_sha([semantic_sha256, list(child_hashes)])


def render_markdown(nodes: Sequence[Any]) -> str:
    if not nodes:
        return ""
    by_parent: dict[int | None, list[Any]] = {}
    for node in nodes:
        by_parent.setdefault(
            node.parent_node_id if hasattr(node, "parent_node_id") else node.parent_position, []
        ).append(node)
    for values in by_parent.values():
        values.sort(key=lambda item: item.position)
    root = min(nodes, key=lambda item: item.position)

    def children(node: Any) -> list[Any]:
        key = node.id if hasattr(node, "id") else node.position
        return by_parent.get(key, [])

    def inline(runs: Iterable[Mapping[str, Any]]) -> str:
        output = ""
        for run in runs:
            kind = run.get("kind")
            if kind == "text":
                output += _escape(str(run.get("text", "")))
            elif kind == "link":
                label = inline(run.get("runs", []))
                destination = _escape_destination(str(run.get("href", "")))
                output += f"[{label}]({destination})"
            elif kind == "image":
                alt = _escape(str(run.get("alt", "")))
                destination = _escape_destination(str(run.get("src", "")))
                output += f"![{alt}]({destination})"
            elif kind == "inline_code":
                output += _inline_code(str(run.get("text", "")))
            elif kind == "strong":
                output += f"**{inline(run.get('runs', []))}**"
            elif kind == "emphasis":
                output += f"*{inline(run.get('runs', []))}*"
            elif kind == "line_break":
                output += "\\\n"
        return output

    def render(node: Any, list_depth: int = 0) -> str:
        kind = node.kind
        node_inline = node.inline_json if hasattr(node, "inline_json") else node.inline
        semantic = node.semantic_json if hasattr(node, "semantic_json") else node.semantic
        text = node.text or ""
        if kind in {"document", "section"}:
            return "\n\n".join(
                part for child in children(node) if (part := render(child, list_depth)).strip()
            )
        if kind == "heading":
            return f"{'#' * int(semantic.get('level', 1))} {inline(node_inline)}".rstrip()
        if kind == "paragraph":
            return inline(node_inline)
        if kind == "caption":
            return f"*{inline(node_inline)}*"
        if kind == "figure":
            rendered = [render(child, list_depth) for child in children(node)]
            return "\n\n".join(value for value in rendered if value)
        if kind == "blockquote":
            body = "\n\n".join(render(child, list_depth) for child in children(node))
            return "\n".join(f"> {line}" if line else ">" for line in body.splitlines())
        if kind == "code_block":
            fence = "`" * max(3, _max_backticks(text) + 1)
            language = str(semantic.get("language") or "")
            return f"{fence}{language}\n{text}\n{fence}"
        if kind == "list":
            return "\n".join(render(child, list_depth + 1) for child in children(node))
        if kind == "list_item":
            parent = next(
                (
                    candidate
                    for candidate in nodes
                    if (candidate.id if hasattr(candidate, "id") else candidate.position)
                    == (
                        node.parent_node_id
                        if hasattr(node, "parent_node_id")
                        else node.parent_position
                    )
                ),
                None,
            )
            parent_semantic = (
                (parent.semantic_json if hasattr(parent, "semantic_json") else parent.semantic)
                if parent
                else {}
            )
            siblings = children(parent) if parent else [node]
            marker = (
                f"{int(parent_semantic.get('start', 1)) + siblings.index(node)}."
                if parent_semantic.get("ordered")
                else "-"
            )
            rendered = [render(child, list_depth) for child in children(node)]
            first = rendered[0] if rendered else ""
            rest = rendered[1:]
            indent = "  " * max(0, list_depth - 1)
            result = f"{indent}{marker} {first}"
            for value in rest:
                result += "\n" + "\n".join(f"{indent}  {line}" for line in value.splitlines())
            return result.rstrip()
        if kind == "table":
            return _render_table(node, children, inline)
        if kind in {"table_row", "table_cell"}:
            return inline(node_inline) or _escape(text)
        if kind == "definition_list":
            return "\n".join(render(child, list_depth) for child in children(node))
        if kind == "definition_term":
            return inline(node_inline)
        if kind == "definition_description":
            return f": {inline(node_inline)}"
        if kind == "thematic_break":
            return "---"
        if kind == "generic_block":
            nested = "\n\n".join(render(child, list_depth) for child in children(node))
            return nested or inline(node_inline) or _escape(text)
        return ""

    return render(root).strip() + ("\n" if len(nodes) > 1 else "")


def _render_table(table: Any, children: Any, inline: Any) -> str:
    rows = children(table)
    values: list[list[str]] = []
    headers: list[bool] = []
    for row in rows:
        cells = children(row)
        rendered: list[str] = []
        for cell in cells:
            semantic = cell.semantic_json if hasattr(cell, "semantic_json") else cell.semantic
            value = inline(
                cell.inline_json if hasattr(cell, "inline_json") else cell.inline
            ).replace("|", "\\|")
            spans = []
            if int(semantic.get("colspan", 1)) != 1:
                spans.append(f"colspan={semantic['colspan']}")
            if int(semantic.get("rowspan", 1)) != 1:
                spans.append(f"rowspan={semantic['rowspan']}")
            rendered.append(f"{value} ({', '.join(spans)})" if spans else value)
        values.append(rendered)
        headers.append(
            bool(cells)
            and all(
                (cell.semantic_json if hasattr(cell, "semantic_json") else cell.semantic).get(
                    "header"
                )
                for cell in cells
            )
        )
    if not values:
        return ""
    width = max(len(row) for row in values)
    values = [row + [""] * (width - len(row)) for row in values]
    separator = "| " + " | ".join("---" for _ in range(width)) + " |"
    source_rows = ["| " + " | ".join(row) + " |" for row in values]
    if headers[0]:
        lines = [source_rows[0], separator, *source_rows[1:]]
    else:
        neutral_header = "| " + " | ".join("" for _ in range(width)) + " |"
        lines = [neutral_header, separator, *source_rows]
    return "\n".join(lines)


def _preorder(root: CanonicalNode) -> Iterable[CanonicalNode]:
    yield root
    for child in root.children:
        yield from _preorder(child)


def _document_text(nodes: Sequence[CanonicalNode]) -> str:
    values: list[str] = []
    for node in nodes:
        if (
            node.kind
            in {
                "heading",
                "paragraph",
                "caption",
                "code_block",
                "table_cell",
                "definition_term",
                "definition_description",
            }
            and node.text
        ):
            values.append(node.text)
    return "\n".join(values)


def _inline_text(runs: Iterable[Mapping[str, Any]]) -> str:
    values: list[str] = []
    for run in runs:
        kind = run.get("kind")
        if kind in {"text", "inline_code"}:
            values.append(str(run.get("text", "")))
        elif kind in {"link", "strong", "emphasis"}:
            values.append(_inline_text(run.get("runs", [])))
        elif kind == "line_break":
            values.append("\n")
    return _SPACE.sub(" ", "".join(values)).strip()


def _empty_document(state: str) -> CanonicalDocument:
    root = CanonicalNode(
        kind="document",
        position=0,
        semantic_sha256=_canonical_sha(
            {"kind": "document", "text": None, "inline": [], "semantic": {}}
        ),
    )
    root.subtree_sha256 = _canonical_sha([root.semantic_sha256, []])
    return CanonicalDocument(
        state,
        "unavailable",
        (root,),
        0,
        {f"h{i}": 0 for i in range(1, 7)},
        0,
        0,
        _sha(""),
        _canonical_sha([]),
        root.subtree_sha256,
        "",
        _sha(""),
        False,
        (),
    )


def _tag(element: etree._Element | None) -> str:
    return element.tag.lower() if element is not None and isinstance(element.tag, str) else ""


def _element_text(element: etree._Element) -> str:
    return "".join(str(value) for value in element.itertext())


def _dom_path(element: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = element
    while current is not None and isinstance(current.tag, str):
        tag = current.tag.lower()
        parent = current.getparent()
        if parent is not None:
            siblings = [child for child in parent if _tag(child) == tag]
            if len(siblings) > 1:
                tag += f":nth-of-type({siblings.index(current) + 1})"
        parts.append(tag)
        current = parent
    return " > ".join(reversed(parts))


def _tokens(value: str | None) -> list[str]:
    return sorted(set((value or "").lower().split()))


def _integer(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _code_language(element: etree._Element) -> str | None:
    code = element.find("code")
    classes = (code.get("class") if code is not None else element.get("class")) or ""
    return next(
        (
            item.removeprefix("language-")
            for item in classes.split()
            if item.startswith("language-")
        ),
        None,
    )


def _escape(value: str) -> str:
    return re.sub(r"([\\`*_[\]<>#|])", r"\\\1", value)


def _escape_destination(value: str) -> str:
    if any(character.isspace() or character in "()\\<>" for character in value):
        escaped = value.replace("\\", "\\\\").replace("<", "\\<").replace(">", "\\>")
        return f"<{escaped}>"
    return value


def _max_backticks(value: str) -> int:
    return max((len(match.group()) for match in _BACKTICKS.finditer(value)), default=0)


def _inline_code(value: str) -> str:
    fence = "`" * (_max_backticks(value) + 1)
    if not fence:
        fence = "`"
    padding = " " if value.startswith("`") or value.endswith("`") else ""
    return f"{fence}{padding}{value}{padding}{fence}"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
