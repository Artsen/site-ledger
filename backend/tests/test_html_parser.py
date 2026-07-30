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
    parsed = parse_html(b"<html><head><title>Bad<body><a href='/x'>x", "https://example.com/")
    assert parsed.title
    assert parsed.anchors[0].resolved_url == "https://example.com/x"
