import json
import os
import subprocess
import sys
import textwrap

import pytest

from app.crawler.html_parser import parse_html


def test_extracts_head_metadata_json_ld_and_anchors() -> None:
    parsed = parse_html(
        b"""
        <html lang="en"><head>
          <title>Example</title>
          <meta name="description" content="Desc">
          <meta name="robots" content="noindex">
          <meta property="og:title" content="OG">
          <meta name="twitter:title" content="TW">
          <link rel="canonical" href="/canonical">
          <script type="application/ld+json">{"name":"Example"}</script>
        </head><body>
          <a href="/next" title="Next" aria-label="Next page"
             rel="nofollow" target="_blank"> Next page </a>
          <a href="/next">Duplicate</a>
          <a>Empty</a>
        </body></html>
        """,
        "https://example.com/start",
    )
    assert parsed.html_language == "en"
    assert parsed.title == "Example"
    assert parsed.meta_description == "Desc"
    assert parsed.meta_robots == "noindex"
    assert parsed.canonical_url == "https://example.com/canonical"
    assert parsed.head_json["open_graph"]["og:title"] == "OG"
    assert parsed.head_json["twitter"]["twitter:title"] == "TW"
    assert parsed.head_json["json_ld"] == ['{"name":"Example"}']
    assert len(parsed.anchors) == 3
    assert parsed.anchors[0].resolved_url == "https://example.com/next"
    assert parsed.anchors[0].rel == "nofollow"


def test_malformed_html_is_best_effort() -> None:
    parsed = parse_html(
        b"<html><head><title>Bad</title></head><body><a href='/x'>x",
        "https://example.com/",
    )
    assert parsed.title == "Bad"
    assert parsed.anchors[0].resolved_url == "https://example.com/x"


def test_canonical_rel_uses_case_insensitive_token_membership() -> None:
    parsed = parse_html(
        b'<html><head><link rel="alternate canonical" href="/canonical"></head></html>',
        "https://example.com/start",
    )

    assert parsed.canonical_url == "https://example.com/canonical"


def test_link_resource_relation_precedence_is_hash_seed_independent() -> None:
    script = textwrap.dedent(
        """
        import json
        from app.crawler.html_parser import parse_html

        parsed = parse_html(
            b'''<html><head>
              <link rel="stylesheet preload" href="/style.css">
              <link rel="manifest alternate" href="/manifest.webmanifest">
              <link rel="icon preload" href="/icon.png">
            </head></html>''',
            "https://example.com/",
        )
        print(json.dumps([
            [item.relation_type, item.resolved_url]
            for item in parsed.resource_references
        ]))
        """
    )
    outputs = []
    for seed in ("1", "2", "17", "999"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        outputs.append(json.loads(result.stdout))

    expected = [
        ["stylesheet", "https://example.com/style.css"],
        ["manifest", "https://example.com/manifest.webmanifest"],
        ["icon", "https://example.com/icon.png"],
    ]
    assert outputs == [expected] * 4


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("canonical", "https://example.com/canonical"),
        ("CANONICAL", "https://example.com/canonical"),
        ("canonical alternate", "https://example.com/canonical"),
        ("alternate canonical", "https://example.com/canonical"),
        (" alternate   canonical ", "https://example.com/canonical"),
        ("alternate\t\ncanonical", "https://example.com/canonical"),
        ("canonical canonical", "https://example.com/canonical"),
        ("future-token canonical", "https://example.com/canonical"),
        ("alternate", None),
    ],
)
def test_canonical_rel_token_fixtures(rel: str, expected: str | None) -> None:
    content = f'<html><head><link rel="{rel}" href="/canonical"></head></html>'.encode()

    assert parse_html(content, "https://example.com/start").canonical_url == expected


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (None, None),
        ("relative", "https://example.com/root/relative"),
        ("https://canonical.example/path", "https://canonical.example/path"),
    ],
)
def test_canonical_href_preserves_existing_resolution_behavior(
    href: str | None, expected: str | None
) -> None:
    href_attribute = f' href="{href}"' if href is not None else ""
    content = f'<html><head><link rel="canonical"{href_attribute}></head></html>'.encode()

    assert parse_html(content, "https://example.com/root/page").canonical_url == expected


def test_later_qualifying_canonical_remains_the_winner() -> None:
    parsed = parse_html(
        b"""<html><head>
          <link rel="canonical alternate" href="/first">
          <link rel="alternate CANONICAL" href="/second">
        </head></html>""",
        "https://example.com/",
    )

    assert parsed.canonical_url == "https://example.com/second"


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("stylesheet", "stylesheet"),
        ("preload", "preload"),
        ("modulepreload", "modulepreload"),
        ("manifest", "manifest"),
        ("icon", "icon"),
        ("apple-touch-icon", "apple-touch-icon"),
        ("mask-icon", "mask-icon"),
        ("alternate", "alternate"),
        ("future-token", None),
        ("future-token stylesheet", "stylesheet"),
        ("stylesheet preload", "stylesheet"),
        ("preload stylesheet", "stylesheet"),
        ("manifest alternate", "manifest"),
        ("alternate manifest", "manifest"),
        ("icon preload", "icon"),
        ("apple-touch-icon icon", "apple-touch-icon"),
        ("mask-icon icon", "mask-icon"),
        ("modulepreload preload", "modulepreload"),
        ("stylesheet stylesheet", "stylesheet"),
        ("StyleSheet PreLoad", "stylesheet"),
        ("  preload   stylesheet  ", "stylesheet"),
    ],
)
def test_link_resource_relation_uses_fixed_precedence(rel: str, expected: str | None) -> None:
    content = f'<html><head><link rel="{rel}" href="/asset"></head></html>'.encode()
    references = parse_html(content, "https://example.com/").resource_references

    assert [item.relation_type for item in references] == ([expected] if expected else [])


def test_canonical_only_and_mixed_resource_relations_keep_separate_semantics() -> None:
    canonical_only = parse_html(
        b'<html><head><link rel="canonical" href="/page"></head></html>',
        "https://example.com/",
    )
    mixed = parse_html(
        b'<html><head><link rel="canonical stylesheet" href="/asset.css"></head></html>',
        "https://example.com/",
    )

    assert canonical_only.canonical_url == "https://example.com/page"
    assert canonical_only.resource_references == []
    assert mixed.canonical_url == "https://example.com/asset.css"
    assert [item.relation_type for item in mixed.resource_references] == ["stylesheet"]


def test_raw_rel_head_evidence_and_reference_order_are_preserved() -> None:
    raw_rel = "PreLoad   StyleSheet custom-token"
    first_content = (
        f'<html><head><link rel="{raw_rel}" href="/a.css">'
        '<link rel="manifest alternate" href="/manifest"></head></html>'
    ).encode()
    second_content = first_content.replace(
        b"PreLoad   StyleSheet custom-token", b"StyleSheet PreLoad custom-token"
    )
    first = parse_html(first_content, "https://example.com/")
    second = parse_html(second_content, "https://example.com/")

    assert first.head_json["links"][0]["rel"] == raw_rel
    assert first.head_json["ordered"][0]["attributes"]["rel"] == raw_rel
    assert first.resource_references[0].rel == raw_rel
    assert [item.position for item in first.resource_references] == [0, 1]
    assert [item.relation_type for item in first.resource_references] == ["stylesheet", "manifest"]
    assert [item.relation_type for item in second.resource_references] == ["stylesheet", "manifest"]
    assert first.head_sha256 != second.head_sha256
