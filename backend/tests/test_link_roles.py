import pytest

from app.crawler.html_parser import parse_html
from app.services.parse_artifacts import HTML_PARSER_VERSION, get_or_create_artifact
from app.storage.content_store import LocalContentStore


@pytest.mark.parametrize(
    ("markup", "role", "rule"),
    [
        ("<a href='mailto:a@example.com'>Email</a>", "email", "href_mailto"),
        ("<a href='tel:+15555555'>Call</a>", "telephone", "href_tel"),
        ("<a href='/report' download>Report</a>", "download", "download_attribute"),
        ("<a href='/report.pdf'>Report</a>", "download", "download_extension"),
        (
            "<nav aria-label='Breadcrumb'><a href='/a'>A</a></nav>",
            "breadcrumb",
            "landmark_breadcrumb",
        ),
        ("<footer><a href='/a'>A</a></footer>", "footer", "ancestor_footer"),
        ("<aside><a href='/a'>A</a></aside>", "sidebar", "ancestor_aside"),
        ("<main><a href='/a'>A</a></main>", "main_content", "ancestor_main"),
        ("<nav><a href='/a'><img src='x'></a></nav>", "navigation", "ancestor_nav"),
        ("<header><a href='/a'>A</a></header>", "header_utility", "ancestor_header"),
        ("<a href='/a'><img src='x'></a>", "image", "image_only"),
        ("<a href='/a'>A</a>", "unknown", "fallback_unknown"),
    ],
)
def test_link_role_rules(markup: str, role: str, rule: str) -> None:
    anchor = parse_html(
        f"<html><body>{markup}</body></html>".encode(), "https://example.com/"
    ).anchors[0]
    assert (anchor.link_role, anchor.link_role_rule) == (role, rule)


def test_link_role_precedence_download_before_footer() -> None:
    anchor = parse_html(
        b"<html><body><footer><a href='/report.pdf'>Report</a></footer></body></html>",
        "https://example.com/",
    ).anchors[0]
    assert anchor.link_role == "download"


def test_current_parser_artifact_persists_roles(db_session, tmp_path) -> None:
    content = b"<html><body><main><a href='/a'>A</a></main></body></html>"
    store = LocalContentStore(tmp_path)
    blob = store.put_html(db_session, content, "text/html", "utf-8")
    artifact = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/",
    )
    reused = get_or_create_artifact(
        db_session,
        blob=blob,
        content=content,
        resolution_base_url="https://example.com/",
    )
    assert artifact.artifact.parser_version == HTML_PARSER_VERSION
    assert reused.parsed is False
    assert reused.anchors[0].link_role == "main_content"
