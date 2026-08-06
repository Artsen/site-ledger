from app.parsers.ai_documents import PARSER_VERSION, classify_ai_document, parse_ai_index


def test_parse_ai_index_preserves_structure_optional_and_duplicate_links() -> None:
    content = (
        b"\xef\xbb\xbf# Example docs\r\n\r\n> Stable summary\r\n\r\nIntro copy.\r\n\r\n"
        b"## Docs\r\n- [Guide](./guide.md): Start here\r\n"
        b"- [Guide again](./guide.md?mode=full#top)\r\n\r\n## Optional\r\n"
        b"- **[API](//example.com/openapi.json)**: Machine contract\r\n"
    )

    parsed = parse_ai_index(content, "https://example.com/llms.txt")

    assert PARSER_VERSION == "ai-document-parser-v1"
    assert parsed.title == "Example docs"
    assert parsed.summary == "Stable summary"
    assert parsed.introduction == "Intro copy."
    assert [item.position for item in parsed.references] == [0, 1, 2]
    assert parsed.references[0].resolved_url == "https://example.com/guide.md"
    assert parsed.references[0].description == "Start here"
    assert parsed.references[1].resolved_url.endswith("guide.md?mode=full#top")
    assert parsed.references[2].optional is True
    assert parsed.references[2].resolved_url == "https://example.com/openapi.json"


def test_parse_ai_index_reports_missing_h1_without_executing_html() -> None:
    parsed = parse_ai_index(
        b"<script>alert(1)</script>\n\n## Links\n- [Doc](/doc.md)",
        "https://example.com/llms.txt",
    )

    assert parsed.title is None
    assert parsed.references[0].resolved_url == "https://example.com/doc.md"
    assert {warning["code"] for warning in parsed.warnings} == {"missing_h1"}


def test_classification_uses_strong_evidence_before_extensions() -> None:
    assert (
        classify_ai_document("https://example.com/anything.bin", "text/html")[0]
        == "html_page_reference"
    )
    assert classify_ai_document("https://example.com/index.txt", "text/plain")[0] == "text_document"
    assert classify_ai_document("https://example.com/docs/llms.txt", None)[0] == "llms_index"
    assert classify_ai_document("https://example.com/llms-full.txt", None)[0] == "llms_full"
    assert classify_ai_document("https://example.com/file.txt", None)[0] == "unknown"
    assert (
        classify_ai_document(
            "https://example.com/openapi.json", "application/json", b'{"openapi":"3.1.0"}'
        )[0]
        == "openapi_specification"
    )
    assert (
        classify_ai_document(
            "https://example.com/events.yaml", "application/yaml", b"asyncapi: 3.0.0"
        )[0]
        == "asyncapi_specification"
    )
    assert (
        classify_ai_document("https://example.com/image.png", "image/png")[0]
        == "unsupported_binary"
    )


def test_parser_bounds_stored_fields() -> None:
    parsed = parse_ai_index(
        (
            "# "
            + "T" * 800
            + "\n\n## "
            + "S" * 800
            + "\n- ["
            + "L" * 1200
            + "](/doc.md): "
            + "D" * 2500
        ).encode(),
        "https://example.com/llms.txt",
    )

    assert len(parsed.title or "") == 500
    assert len(parsed.references[0].section_title or "") == 500
    assert len(parsed.references[0].label or "") == 1000
    assert len(parsed.references[0].description or "") == 2000
