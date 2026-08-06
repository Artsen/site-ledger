from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

PARSER_VERSION = "ai-document-parser-v1"


@dataclass(frozen=True)
class ParsedAiReference:
    position: int
    section_title: str | None
    label: str | None
    description: str | None
    raw_url: str
    resolved_url: str
    optional: bool


@dataclass(frozen=True)
class ParsedAiIndex:
    title: str | None
    summary: str | None
    introduction: str | None
    references: list[ParsedAiReference]
    warnings: list[dict[str, str]]


def parse_ai_index(content: bytes, base_url: str, encoding: str = "utf-8") -> ParsedAiIndex:
    warnings: list[dict[str, str]] = []
    try:
        text = content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        text = content.decode("utf-8", errors="replace")
        warnings.append(
            {
                "code": "unsupported_encoding",
                "message": "Decoded with UTF-8 replacement characters.",
            }
        )
    if text.startswith("\ufeff"):
        text = text[1:]
    tokens = MarkdownIt("commonmark", {"html": False, "linkify": False}).parse(text)
    title: str | None = None
    summary: str | None = None
    current_section: str | None = None
    intro_parts: list[str] = []
    references: list[ParsedAiReference] = []
    seen_section = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open" and index + 1 < len(tokens):
            inline = tokens[index + 1]
            value = _inline_text(inline)[:500] or None
            if token.tag == "h1" and title is None:
                title = value
            elif token.tag == "h2":
                current_section = value
                seen_section = True
            index += 2
            continue
        if token.type == "blockquote_open" and summary is None and index + 1 < len(tokens):
            candidate = next((item for item in tokens[index + 1 :] if item.type == "inline"), None)
            summary = _inline_text(candidate)[:2000] if candidate else None
        if token.type == "inline":
            if (
                not seen_section
                and title
                and token.content.strip()
                and token.content.strip() != summary
            ):
                intro_parts.append(token.content.strip())
            for raw_url, label, description in _links(token):
                references.append(
                    ParsedAiReference(
                        position=len(references),
                        section_title=(current_section or "")[:500] or None,
                        label=label[:1000] or None,
                        description=description[:2000] or None,
                        raw_url=raw_url[:4000],
                        resolved_url=urljoin(base_url, raw_url)[:4000],
                        optional=(current_section or "").strip().casefold() == "optional",
                    )
                )
        index += 1
    if title is None:
        warnings.append(
            {"code": "missing_h1", "message": "The index does not declare a required H1 title."}
        )
    return ParsedAiIndex(
        title=title,
        summary=summary,
        introduction="\n\n".join(intro_parts)[:10000] or None,
        references=references,
        warnings=warnings,
    )


def classify_ai_document(
    url: str,
    mime_type: str | None,
    content: bytes | None = None,
    *,
    explicit_relation: str | None = None,
    parent_kind: str | None = None,
) -> tuple[str, str]:
    path_name = PurePosixPath(unquote(urlsplit(url).path)).name.casefold()
    mime = (mime_type or "").split(";", 1)[0].strip().casefold()
    if explicit_relation in {"llms-txt", "llms_txt"}:
        return "llms_index", "explicit_llms_relation"
    if explicit_relation in {"llms-full-txt", "llms_full_txt"}:
        return "llms_full", "explicit_llms_full_relation"
    if path_name == "llms.txt":
        return "llms_index", "filename_llms_txt"
    if path_name == "llms-full.txt":
        return "llms_full", "filename_llms_full_txt"
    if mime in {"text/html", "application/xhtml+xml"}:
        return "html_page_reference", "mime_html"
    if mime in {"text/markdown", "text/x-markdown"}:
        return "markdown_document", "mime_markdown"
    if mime == "text/plain":
        return "text_document", "mime_text"
    if mime in {"application/json", "application/openapi+json"}:
        signature = (content or b"")[:65536].lower()
        if b'"openapi"' in signature or b'"swagger"' in signature:
            return "openapi_specification", "json_signature_openapi"
        if b'"asyncapi"' in signature:
            return "asyncapi_specification", "json_signature_asyncapi"
        return "json_document", "mime_json"
    if mime in {"application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml"}:
        signature = (content or b"")[:65536].lower()
        if b"openapi:" in signature or b"swagger:" in signature:
            return "openapi_specification", "yaml_signature_openapi"
        if b"asyncapi:" in signature:
            return "asyncapi_specification", "yaml_signature_asyncapi"
        return "yaml_document", "mime_yaml"
    extension = path_name.rsplit(".", 1)[-1] if "." in path_name else ""
    if extension in {"md", "markdown"}:
        return "markdown_document", "extension_markdown"
    if extension == "json":
        return "json_document", "extension_json"
    if extension in {"yaml", "yml"}:
        return "yaml_document", "extension_yaml"
    if extension == "txt" and parent_kind == "llms_index":
        return "text_document", "parent_index_text_reference"
    if mime and not (mime.startswith("text/") or "json" in mime or "yaml" in mime):
        return "unsupported_binary", "mime_unsupported_binary"
    return "unknown", "insufficient_evidence"


def _inline_text(token: Token | None) -> str:
    if token is None:
        return ""
    if not token.children:
        return token.content.strip()
    return "".join(
        child.content for child in token.children if child.type in {"text", "code_inline"}
    ).strip()


def _links(token: Token) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    children = token.children or []
    for index, child in enumerate(children):
        if child.type != "link_open":
            continue
        href = str(child.attrGet("href") or "")
        close = next(
            (
                position
                for position in range(index + 1, len(children))
                if children[position].type == "link_close"
            ),
            len(children),
        )
        label = "".join(
            item.content
            for item in children[index + 1 : close]
            if item.type in {"text", "code_inline"}
        ).strip()
        description = (
            "".join(item.content for item in children[close + 1 :] if item.type == "text")
            .strip()
            .lstrip(":-– ")
        )
        if href:
            result.append((href, label, description))
    return result
