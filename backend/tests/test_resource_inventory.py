from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, text

from app.crawler.resource_classification import classify_reference, classify_response
from app.crawler.safe_fetch import FetchLimits, SafeHttpFetcher
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler
from app.models import (
    ContentBlob,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.resource_queries import (
    get_scan_resource,
    list_resource_occurrences,
    list_scan_resources,
    list_site_resource_history,
    list_site_resources,
    scan_resource_summary,
)
from app.services.scan_deletion import delete_scan, preview_scan_deletion
from app.storage.content_store import LocalContentStore


@pytest.mark.parametrize(
    ("content_type", "url", "kind", "rule"),
    [
        (
            "text/html; charset=utf-8",
            "https://example.test/file.pdf",
            "html_page",
            "mime_text_html",
        ),
        ("application/xhtml+xml", "https://example.test/", "html_page", "mime_text_html"),
        ("image/jpeg", "https://example.test/image", "image", "mime_image"),
        ("image/webp", "https://example.test/image", "image", "mime_image"),
        ("image/svg+xml", "https://example.test/image", "image", "mime_image"),
        ("application/pdf", "https://example.test/file.php", "document", "mime_pdf"),
        ("application/msword", "https://example.test/file", "document", "mime_document"),
        ("text/css", "https://example.test/file", "stylesheet", "mime_stylesheet"),
        ("text/javascript", "https://example.test/file", "script", "mime_javascript"),
        ("font/woff2", "https://example.test/file", "font", "mime_font"),
        ("video/mp4", "https://example.test/file", "video", "mime_video"),
        ("audio/mpeg", "https://example.test/file", "audio", "mime_audio"),
        ("application/zip", "https://example.test/file", "archive", "mime_archive"),
        ("application/rss+xml", "https://example.test/file", "feed", "mime_feed"),
        ("application/manifest+json", "https://example.test/file", "manifest", "mime_manifest"),
        (
            "application/json",
            "https://example.test/file",
            "structured_data",
            "mime_structured_data",
        ),
    ],
)
def test_response_classification(content_type: str, url: str, kind: str, rule: str) -> None:
    result = classify_response(url=url, content_type=content_type)
    assert (result.kind, result.rule) == (kind, rule)


def test_signature_and_element_classification() -> None:
    assert (
        classify_response(
            url="https://example.test/download", content_type=None, prefix=b"%PDF-1.7"
        ).kind
        == "document"
    )
    reference = classify_reference(
        url="https://example.test/dynamic.php",
        element_tag="img",
        attribute_name="src",
    )
    assert (reference.kind, reference.rule) == ("image", "element_img")


@pytest.mark.asyncio
async def test_ambiguous_non_html_inspection_is_bounded() -> None:
    body = b"%PDF-1.7" + b"x" * 100_000
    fetcher = SafeHttpFetcher(
        FetchLimits(
            timeout_seconds=10,
            max_response_bytes=200_000,
            max_redirects=2,
            user_agent="SiteLedgerTest/1",
            allow_private_networks=True,
            metadata_only_non_html=True,
        ),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body)),
    )

    result = await fetcher.get("https://fixture.test/download")

    assert result.response_body_state == "prefix_inspected"
    assert result.inspected_prefix_byte_count == 4096
    assert result.network_bytes_transferred == 4096
    assert len(result.content) == 4096


@pytest.mark.asyncio
async def test_non_html_is_successful_metadata_and_resource_inventory_is_aggregated(
    db_session, tmp_path
) -> None:
    site = WebsiteProperty(
        name="Fixture",
        base_url="https://fixture.test/",
        normalized_base_url="https://fixture.test/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    db_session.add(site)
    db_session.flush()
    scan = Scan(
        website_property_id=site.id,
        starting_url="https://fixture.test/",
        status="queued",
        scope_config=ScopeConfig(
            allowed_host_patterns=["fixture.test"],
            allow_private_networks=True,
            max_pages=5,
            max_depth=2,
        ).to_dict(),
    )
    db_session.add(scan)
    db_session.commit()
    transferred_pdf_body = b"%PDF-1.7" + b"x" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"""
                <html><head>
                  <link rel="stylesheet" href="/site.css">
                  <link rel="preload" as="font" href="/shared.woff2">
                </head><body>
                  <img src="/hero.webp" srcset="/hero.webp 1x, /hero@2x.webp 2x"
                       alt="Hero" width="800" height="400">
                  <img src="/hero.webp" alt="Repeated">
                  <script src="/app.js"></script>
                  <a href="/guide.pdf">Guide</a>
                </body></html>
                """,
            )
        if request.url.path == "/guide.pdf":
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/pdf",
                    "content-length": str(len(transferred_pdf_body)),
                    "content-disposition": 'attachment; filename="guide.pdf"',
                },
                content=transferred_pdf_body,
            )
        raise AssertionError(f"Embedded Resource was fetched: {request.url}")

    await StaticPageCrawler(
        db_session,
        LocalContentStore(tmp_path),
        transport=httpx.MockTransport(handler),
    ).run(scan)

    snapshots = db_session.query(ResourceSnapshot).order_by(ResourceSnapshot.id).all()
    assert len(snapshots) == 2
    pdf = next(item for item in snapshots if item.representation_kind == "document")
    assert pdf.fetch_state == "fetched"
    assert pdf.error_type is None
    assert pdf.parse_method == "not_applicable"
    assert pdf.html_blob_id is None
    assert pdf.response_body_state == "metadata_only"
    assert pdf.network_bytes_transferred == 0
    assert pdf.declared_content_length == len(transferred_pdf_body)
    assert db_session.query(ContentBlob).count() == 1
    assert scan.failed_count == 0
    assert scan.status == "completed"
    assert scan.html_page_observed_count == 1
    assert scan.resource_observed_count == 1

    inventory = list_scan_resources(db_session, scan.id)
    assert inventory is not None
    assert inventory.total == 6
    by_url = {item.normalized_url: item for item in inventory.items}
    assert by_url["https://fixture.test/guide.pdf"].observed
    assert by_url["https://fixture.test/hero.webp"].occurrence_count == 3
    assert by_url["https://fixture.test/hero.webp"].source_page_count == 1
    assert by_url["https://fixture.test/app.js"].discovered_only
    assert len({item.resource_id for item in inventory.items}) == inventory.total
    summary = scan_resource_summary(db_session, scan.id)
    assert summary is not None
    assert summary.observed_resources == 1
    assert summary.discovered_only_resources == 5
    assert summary.kind_counts["image"] == 2

    occurrences = list_resource_occurrences(
        db_session, by_url["https://fixture.test/hero.webp"].resource_id, scan_id=scan.id
    )
    assert occurrences.total == 3
    assert [item.alt_text for item in occurrences.items] == ["Hero", "Hero", "Repeated"]
    assert {item.srcset_descriptor for item in occurrences.items} == {None, "1x"}
    assert db_session.query(ResourceReferenceOccurrence).count() == 7

    site_inventory = list_site_resources(db_session, site.id)
    assert site_inventory is not None and site_inventory.total == inventory.total
    history = list_site_resource_history(
        db_session, site.id, by_url["https://fixture.test/guide.pdf"].resource_id
    )
    assert history is not None and history.total == 1
    assert history.items[0].observed
    detail = get_scan_resource(
        db_session, scan.id, by_url["https://fixture.test/guide.pdf"].resource_id
    )
    assert detail is not None and detail.resource.effective_kind == "document"
    assert (
        db_session.query(WebResource)
        .filter_by(normalized_url="https://fixture.test/guide.pdf")
        .count()
        == 1
    )

    statements: list[str] = []

    def before_cursor_execute(*args) -> None:
        statements.append(str(args[2]))

    event.listen(db_session.bind, "before_cursor_execute", before_cursor_execute)
    try:
        assert list_scan_resources(db_session, scan.id, limit=2, offset=2).total == 6
    finally:
        event.remove(db_session.bind, "before_cursor_execute", before_cursor_execute)
    assert len(statements) <= 3
    assert not any(
        "SELECT" in sql and "resource_reference_occurrences.id =" in sql for sql in statements
    )

    plan = db_session.execute(
        text(
            "EXPLAIN QUERY PLAN SELECT target_resource_id FROM resource_reference_occurrences "
            "WHERE source_snapshot_id=:snapshot_id AND inferred_kind=:kind"
        ),
        {"snapshot_id": snapshots[0].id, "kind": "image"},
    ).all()
    assert any("ix_resource_reference_source_kind" in str(row) for row in plan)

    preview = preview_scan_deletion(db_session, scan.id)
    assert preview is not None
    assert preview.resource_reference_occurrences == 7
    assert preview.resources_observed == 1
    assert preview.resources_discovered == 5
    result = delete_scan(db_session, scan.id, LocalContentStore(tmp_path))
    assert result is not None
    assert result.resource_reference_occurrences_deleted == 7
    assert db_session.query(ResourceReferenceOccurrence).count() == 0
    assert (
        db_session.query(WebResource)
        .filter(WebResource.normalized_url.endswith("hero.webp"))
        .count()
        == 0
    )


def test_site_inventory_uses_latest_observation_without_cross_site_leak(db_session) -> None:
    first_site = WebsiteProperty(
        name="First",
        base_url="https://shared.test/",
        normalized_base_url="https://shared.test/",
        group_key="Group",
        platform_key="Platform",
        ownership_key="Owner",
        scope_config={},
        is_active=True,
    )
    second_site = WebsiteProperty(
        name="Second",
        base_url="https://shared.test/",
        normalized_base_url="https://shared.test/second",
        group_key="Group",
        platform_key="Platform",
        ownership_key="Owner",
        scope_config={},
        is_active=True,
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://shared.test/file",
        scheme="https",
        host="shared.test",
        path="/file",
        query="",
    )
    db_session.add_all([first_site, second_site, resource])
    db_session.flush()
    scans = [
        Scan(
            website_property_id=first_site.id,
            starting_url=first_site.base_url,
            status="completed",
            scope_config={},
        ),
        Scan(
            website_property_id=first_site.id,
            starting_url=first_site.base_url,
            status="completed",
            scope_config={},
        ),
        Scan(
            website_property_id=second_site.id,
            starting_url=second_site.base_url,
            status="completed",
            scope_config={},
        ),
    ]
    db_session.add_all(scans)
    db_session.flush()
    now = datetime.now(UTC)
    snapshots = [
        (scans[0], now, "document", "mime_pdf", "application/pdf", 200, 100),
        (scans[1], now + timedelta(minutes=1), "image", "mime_image", "image/png", 206, 200),
        (
            scans[2],
            now + timedelta(minutes=2),
            "stylesheet",
            "mime_stylesheet",
            "text/css",
            418,
            300,
        ),
    ]
    db_session.add_all(
        [
            ResourceSnapshot(
                scan_id=scan.id,
                resource_id=resource.id,
                requested_url=resource.normalized_url,
                final_url=resource.normalized_url,
                http_status=status,
                content_type=mime,
                crawl_depth=0,
                fetched_at=fetched_at,
                fetch_state="fetched",
                representation_kind=kind,
                representation_rule=rule,
                normalized_mime_type=mime,
                declared_content_length=size,
                response_body_state="metadata_only",
            )
            for scan, fetched_at, kind, rule, mime, status, size in snapshots
        ]
    )
    db_session.commit()

    inventory = list_site_resources(db_session, first_site.id)

    assert inventory is not None and inventory.total == 1
    latest = inventory.items[0]
    assert (latest.effective_kind, latest.normalized_mime_type, latest.http_status) == (
        "image",
        "image/png",
        206,
    )
    assert latest.declared_content_length == 200
    assert latest.observation_count == 2
    assert latest.scan_count == 2
