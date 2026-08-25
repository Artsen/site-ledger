import gzip

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BackgroundJob,
    ScanSeed,
    SiteInventorySuppression,
    SourceRefresh,
    UrlSourceEntry,
    WebResource,
)
from app.parsers.compression import (
    DecompressedResponseTooLargeError,
    InvalidGzipError,
    maybe_decompress_gzip,
)
from app.parsers.robots import parse_sitemap_directives
from app.parsers.sitemap import SitemapParseError, parse_sitemap_xml
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate
from app.schemas.sources import UrlSourceCreate
from app.services.inventory_lifecycle import (
    ManagedSourceEntryError,
    bulk_create_inventory_suppressions,
    bulk_delete_inventory_entries,
    bulk_restore_inventory_suppressions,
    create_inventory_suppression,
    delete_inventory_suppression,
    remove_manual_source_entry,
)
from app.services.scan_deletion import delete_scan
from app.services.site_management import create_scan_from_site, create_site, delete_site
from app.services.source_management import (
    DuplicateSourceError,
    add_manual_urls,
    create_source,
    upsert_source_entry,
)
from app.services.source_queries import list_inventory, list_scan_seeds, list_sources
from app.services.source_refresh import (
    discover_from_robots,
    enqueue_bulk_source_refreshes,
    refresh_source,
)
from app.storage.content_store import LocalContentStore


def test_sitemap_parser_handles_urlsets_indexes_and_unsafe_xml() -> None:
    parsed = parse_sitemap_xml(
        b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/a</loc><lastmod>2026-01-01</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>
          <url><lastmod>missing loc</lastmod></url>
        </urlset>"""
    )
    assert parsed.document_type == "urlset"
    assert parsed.urls[0].loc == "https://example.com/a"
    assert parsed.urls[0].priority == "0.8"

    index = parse_sitemap_xml(
        b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/child.xml</loc><lastmod>2026-01-02</lastmod></sitemap>
        </sitemapindex>"""
    )
    assert index.children[0].loc.endswith("child.xml")

    with pytest.raises(SitemapParseError):
        parse_sitemap_xml(
            b"<!DOCTYPE foo [ <!ENTITY xxe SYSTEM 'file:///etc/passwd'> ]><foo>&xxe;</foo>"
        )


def test_gzip_detection_and_limits() -> None:
    body = gzip.compress(b"<urlset />")
    content, decompressed = maybe_decompress_gzip(
        body,
        url="https://example.com/sitemap.xml.gz",
        content_type=None,
        max_decompressed_bytes=100,
    )
    assert decompressed is True
    assert content == b"<urlset />"

    with pytest.raises(InvalidGzipError):
        maybe_decompress_gzip(
            b"not gzip",
            url="https://example.com/sitemap.xml.gz",
            content_type=None,
            max_decompressed_bytes=100,
        )
    with pytest.raises(DecompressedResponseTooLargeError):
        maybe_decompress_gzip(
            gzip.compress(b"x" * 200),
            url="https://example.com/sitemap.xml.gz",
            content_type=None,
            max_decompressed_bytes=100,
        )


def test_robots_parser_extracts_multiple_directives() -> None:
    directives = parse_sitemap_directives(
        b"Sitemap: /sitemap.xml\nsitemap: https://cdn.example.com/other.xml\n",
        "https://example.com/robots.txt",
    )

    assert [item.resolved_url for item in directives] == [
        "https://example.com/sitemap.xml",
        "https://cdn.example.com/other.xml",
    ]


@pytest.mark.asyncio
async def test_sitemap_refresh_persists_entries_and_current_membership(db_session: Session) -> None:
    site = create_site(
        db_session,
        _site_payload(
            scope_config=ScopeConfigPayload(
                allowed_host_patterns=["example.com"], drop_query_parameters=["utm_*"]
            )
        ),
    )
    source = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Main sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert source is not None

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://example.com/a?utm_source=x</loc><lastmod>2026-01-01</lastmod></url>
              <url><loc>https://outside.example/b</loc></url>
              <url><loc>ftp://example.com/file</loc></url>
            </urlset>""",
        )
    )
    refresh = await refresh_source(db_session, site.id, source.id, transport)

    assert refresh is not None
    assert refresh.status == "completed_with_errors"
    entries = db_session.query(UrlSourceEntry).order_by(UrlSourceEntry.id).all()
    assert len(entries) == 3
    assert entries[0].normalized_url == "https://example.com/a?utm_source=x"
    assert entries[0].validation_state == "valid"
    assert entries[1].scope_decision == "external"
    assert entries[2].validation_state == "invalid"


def test_bulk_source_refresh_is_deduplicated_atomic_and_queued(db_session: Session) -> None:
    site = create_site(db_session, _site_payload())
    first = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="First", source_url="https://example.com/first.xml"),
    )
    second = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Second", source_url="https://example.com/second.xml"),
    )
    other_site = create_site(
        db_session,
        WebsitePropertyCreate(
            name="Other",
            base_url="https://other.example/",
            scope_config=ScopeConfigPayload(),
        ),
    )
    other = create_source(
        db_session,
        other_site.id,
        UrlSourceCreate(name="Other", source_url="https://other.example/sitemap.xml"),
    )
    assert first is not None and second is not None and other is not None

    refreshes = enqueue_bulk_source_refreshes(db_session, site.id, [second.id, first.id, second.id])
    assert refreshes is not None
    assert [refresh.url_source_id for refresh in refreshes] == [second.id, first.id]
    assert all(refresh.status == "queued" for refresh in refreshes)
    assert db_session.scalar(select(func.count(BackgroundJob.id))) == 2

    with pytest.raises(ValueError, match="do not belong"):
        enqueue_bulk_source_refreshes(db_session, site.id, [first.id, other.id])
    assert db_session.scalar(select(func.count(SourceRefresh.id))) == 2

    with pytest.raises(ValueError, match="active refresh"):
        enqueue_bulk_source_refreshes(db_session, site.id, [first.id])
    assert db_session.scalar(select(func.count(SourceRefresh.id))) == 2


@pytest.mark.asyncio
async def test_sitemap_refresh_does_not_clear_inventory_suppression(
    db_session: Session,
) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    source = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Main sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert source is not None
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"<urlset><url><loc>https://example.com/foo</loc></url></urlset>",
        )
    )
    await refresh_source(db_session, site.id, source.id, transport)
    entry = db_session.query(UrlSourceEntry).one()
    suppression = create_inventory_suppression(db_session, site.id, entry.id)
    assert suppression is not None

    await refresh_source(db_session, site.id, source.id, transport)
    db_session.refresh(entry)
    assert entry.is_current is True
    assert db_session.get(SiteInventorySuppression, suppression.id) is not None
    active = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        limit=10,
        offset=0,
    )
    assert active is not None and active.total == 0


@pytest.mark.asyncio
async def test_inventory_delete_allows_sitemap_refresh_to_recreate_without_duplicates(
    db_session: Session,
) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    source = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Main sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert source is not None
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=b"<urlset><url><loc>https://example.com/foo</loc></url></urlset>",
        )
    )
    first_refresh = await refresh_source(db_session, site.id, source.id, transport)
    original = db_session.query(UrlSourceEntry).one()
    original_resource_id = original.resource_id
    suppression = create_inventory_suppression(db_session, site.id, original.id)
    assert suppression is not None

    deleted = bulk_delete_inventory_entries(db_session, site.id, [original.id, original.id])
    assert deleted is not None
    assert (deleted.selected, deleted.changed, deleted.unchanged) == (1, 1, 0)
    assert db_session.query(UrlSourceEntry).count() == 0
    assert db_session.get(SiteInventorySuppression, suppression.id) is None
    assert db_session.get(WebResource, original_resource_id) is not None

    recreated = await refresh_source(db_session, site.id, source.id, transport)
    recreated_entry = db_session.query(UrlSourceEntry).one()
    assert first_refresh is not None and first_refresh.entries_added == 1
    assert recreated is not None and recreated.entries_added == 1
    assert recreated_entry.resource_id == original_resource_id

    repeated = await refresh_source(db_session, site.id, source.id, transport)
    assert repeated is not None
    assert (repeated.entries_added, repeated.entries_updated) == (0, 1)
    assert db_session.query(UrlSourceEntry).count() == 1


def test_bulk_inventory_delete_is_atomic_across_sites(db_session: Session) -> None:
    site = create_site(db_session, _site_payload())
    _source, entries, *_ = add_manual_urls(
        db_session, site.id, "https://example.com/first\nhttps://example.com/second"
    )
    other = create_site(
        db_session,
        WebsitePropertyCreate(name="Other", base_url="https://other.example/"),
    )
    _other_source, other_entries, *_ = add_manual_urls(
        db_session, other.id, "https://other.example/first"
    )

    with pytest.raises(ValueError, match="do not belong"):
        bulk_delete_inventory_entries(db_session, site.id, [entries[0].id, other_entries[0].id])

    assert db_session.get(UrlSourceEntry, entries[0].id) is not None
    assert db_session.get(UrlSourceEntry, entries[1].id) is not None
    assert db_session.get(UrlSourceEntry, other_entries[0].id) is not None


@pytest.mark.asyncio
async def test_robots_discovery_creates_sitemap_sources(db_session: Session) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"Sitemap: /sitemap.xml\n")
    )

    refresh = await discover_from_robots(db_session, site.id, transport)
    sources = list_sources(
        db_session, site.id, source_type=None, active_state="all", limit=10, offset=0
    )

    assert refresh is not None
    assert refresh.status == "completed"
    assert sources is not None
    assert {source.source_type for source in sources.items} == {"robots", "sitemap"}


def test_manual_urls_inventory_and_scan_seeds(db_session: Session) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )

    source, entries, accepted, rejected, duplicates = add_manual_urls(
        db_session, site.id, "/a\nhttps://example.com/a\njavascript:alert(1)"
    )
    assert source is not None
    assert accepted == 1
    assert rejected == 1
    assert duplicates == 1

    inventory = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        limit=10,
        offset=0,
    )
    assert inventory is not None
    assert inventory.total == 2

    scan = create_scan_from_site(
        db_session,
        site.id,
        ScopeConfigPayload(allowed_host_patterns=["example.com"]),
        include_inventory=True,
    )
    assert scan is not None
    seeds = list_scan_seeds(db_session, scan.id, limit=10, offset=0)
    assert seeds is not None
    assert any(seed.origins[0].origin_type == "manual" for seed in seeds.items)


def test_inventory_suppression_preserves_multi_source_truth_and_skips_seeding(
    db_session: Session,
) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    manual, manual_entries, *_ = add_manual_urls(db_session, site.id, "https://example.com/pricing")
    assert manual is not None
    suppression = create_inventory_suppression(db_session, site.id, manual_entries[0].id)
    assert suppression is not None
    sitemap = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Main sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert sitemap is not None
    sitemap_entry, _ = upsert_source_entry(
        db_session,
        sitemap,
        "https://example.com/pricing",
        site=site,
        source_type="sitemap",
    )
    db_session.commit()

    repeated = create_inventory_suppression(db_session, site.id, sitemap_entry.id)
    assert repeated is not None and repeated.id == suppression.id

    active = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="active",
        limit=10,
        offset=0,
    )
    removed = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="suppressed",
        limit=10,
        offset=0,
    )
    assert active is not None and active.total == 0
    assert removed is not None and removed.total == 1
    assert removed.items[0].source_count == 2
    assert removed.items[0].suppression_id == suppression.id
    assert all(entry.is_current for entry in (manual_entries[0], sitemap_entry))
    sources = list_sources(
        db_session, site.id, source_type=None, active_state="all", limit=10, offset=0
    )
    assert sources is not None
    assert sorted(source.current_entry_count for source in sources.items) == [1, 1]

    scan = create_scan_from_site(
        db_session,
        site.id,
        ScopeConfigPayload(allowed_host_patterns=["example.com"]),
        include_inventory=True,
    )
    assert scan is not None
    assert (
        not db_session.query(ScanSeed)
        .filter_by(scan_id=scan.id, normalized_url="https://example.com/pricing")
        .count()
    )
    assert delete_inventory_suppression(db_session, site.id, suppression.id) == suppression.id
    restored = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        limit=10,
        offset=0,
    )
    assert restored is not None and restored.items[0].source_count == 2


def test_manual_entry_removal_is_nondestructive_and_readd_reactivates(db_session: Session) -> None:
    site = create_site(db_session, _site_payload())
    source, entries, *_ = add_manual_urls(db_session, site.id, "https://example.com/manual")
    assert source is not None
    entry = entries[0]
    first_seen = entry.first_seen_at
    resource_id = entry.resource_id

    removed = remove_manual_source_entry(db_session, site.id, source.id, entry.id)
    assert removed is not None and removed.is_current is False
    assert db_session.get(UrlSourceEntry, entry.id) is not None
    assert db_session.get(WebResource, resource_id) is not None

    _source, readded, *_ = add_manual_urls(db_session, site.id, "https://example.com/manual")
    assert readded[0].id == entry.id
    assert readded[0].is_current is True
    assert readded[0].first_seen_at == first_seen
    assert db_session.query(UrlSourceEntry).count() == 1


def test_managed_entry_removal_is_rejected_and_raw_suppression_is_exact(
    db_session: Session,
) -> None:
    site = create_site(db_session, _site_payload())
    sitemap = create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Sitemap", source_url="https://example.com/sitemap.xml"),
    )
    assert sitemap is not None
    managed, _ = upsert_source_entry(
        db_session, sitemap, "https://example.com/a", site=site, source_type="sitemap"
    )
    _manual, invalid, *_ = add_manual_urls(db_session, site.id, "javascript:alert(1)")
    db_session.commit()

    with pytest.raises(ManagedSourceEntryError, match="managed by its Source"):
        remove_manual_source_entry(db_session, site.id, sitemap.id, managed.id)
    suppression = create_inventory_suppression(db_session, site.id, invalid[0].id)
    assert suppression is not None
    assert (suppression.target_kind, suppression.target_value) == (
        "raw_url",
        "javascript:alert(1)",
    )
    assert db_session.query(SiteInventorySuppression).count() == 1
    other = create_site(
        db_session,
        WebsitePropertyCreate(name="Other", base_url="https://other.example/"),
    )
    _source, other_invalid, *_ = add_manual_urls(db_session, other.id, "javascript:alert(1)")
    assert create_inventory_suppression(db_session, site.id, other_invalid[0].id) is None
    other_inventory = list_inventory(
        db_session,
        other.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        limit=10,
        offset=0,
    )
    assert other_inventory is not None and other_inventory.total == 1
    assert delete_inventory_suppression(db_session, other.id, suppression.id) is None


def test_inventory_suppression_remains_compatible_across_url_identity_versions(
    db_session: Session,
) -> None:
    site = create_site(db_session, _site_payload())
    _source, entries, *_ = add_manual_urls(db_session, site.id, "https://example.com/a%2Fb")
    legacy = SiteInventorySuppression(
        website_property_id=site.id,
        target_kind="normalized_url",
        target_value="https://example.com/a/b",
        normalization_version="url-normalization-v1",
    )
    db_session.add(legacy)
    db_session.commit()

    active = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="active",
        limit=10,
        offset=0,
    )
    removed = list_inventory(
        db_session,
        site.id,
        search=None,
        source_type=None,
        source_id=None,
        scope_decision=None,
        validation_state=None,
        visibility="suppressed",
        limit=10,
        offset=0,
    )
    repeated = create_inventory_suppression(db_session, site.id, entries[0].id)

    assert active is not None and active.total == 0
    assert removed is not None and removed.total == 1
    assert repeated is not None and repeated.id == legacy.id
    assert db_session.query(SiteInventorySuppression).count() == 1


def test_bulk_inventory_suppression_is_atomic_deduplicated_and_restorable(
    db_session: Session,
) -> None:
    site = create_site(db_session, _site_payload())
    _source, entries, *_ = add_manual_urls(
        db_session,
        site.id,
        "https://example.com/first\nhttps://example.com/second\nhttps://example.com/third",
    )
    other = create_site(
        db_session,
        WebsitePropertyCreate(name="Other", base_url="https://other.example/"),
    )
    _other_source, other_entries, *_ = add_manual_urls(
        db_session, other.id, "https://other.example/first"
    )

    created = bulk_create_inventory_suppressions(
        db_session, site.id, [entries[0].id, entries[0].id, entries[1].id]
    )
    assert created is not None
    assert (created.selected, created.changed, created.unchanged) == (2, 2, 0)
    repeated = bulk_create_inventory_suppressions(
        db_session, site.id, [entries[0].id, entries[1].id]
    )
    assert repeated is not None
    assert (repeated.selected, repeated.changed, repeated.unchanged) == (2, 0, 2)
    assert db_session.query(SiteInventorySuppression).count() == 2

    with pytest.raises(ValueError, match="do not belong"):
        bulk_create_inventory_suppressions(
            db_session, site.id, [entries[2].id, other_entries[0].id]
        )
    assert db_session.query(SiteInventorySuppression).count() == 2

    suppressions = (
        db_session.query(SiteInventorySuppression).order_by(SiteInventorySuppression.id).all()
    )
    restored = bulk_restore_inventory_suppressions(
        db_session, site.id, [suppressions[0].id, suppressions[0].id]
    )
    assert restored is not None
    assert (restored.selected, restored.changed, restored.unchanged) == (1, 1, 0)
    assert db_session.query(SiteInventorySuppression).count() == 1

    other_suppression = create_inventory_suppression(db_session, other.id, other_entries[0].id)
    assert other_suppression is not None
    with pytest.raises(ValueError, match="do not belong"):
        bulk_restore_inventory_suppressions(
            db_session,
            site.id,
            [suppressions[1].id, other_suppression.id],
        )
    assert db_session.get(SiteInventorySuppression, suppressions[1].id) is not None


def test_source_duplicate_and_deletion_resource_cleanup(db_session: Session, tmp_path) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    create_source(
        db_session,
        site.id,
        UrlSourceCreate(name="Main sitemap", source_url="https://example.com/sitemap.xml"),
    )
    with pytest.raises(DuplicateSourceError):
        create_source(
            db_session,
            site.id,
            UrlSourceCreate(name="Duplicate", source_url="https://EXAMPLE.com/sitemap.xml"),
        )
    add_manual_urls(db_session, site.id, "https://example.com/a")
    source = db_session.query(UrlSourceEntry).one()
    suppression = create_inventory_suppression(db_session, site.id, source.id)
    assert suppression is not None
    resource_count = db_session.query(WebResource).count()
    assert resource_count == 1

    assert delete_site(db_session, site.id) == site.id
    assert db_session.query(WebResource).count() == 0
    assert db_session.get(SiteInventorySuppression, suppression.id) is None

    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(allowed_host_patterns=["example.com"])),
    )
    add_manual_urls(db_session, site.id, "https://example.com/a")
    scan = create_scan_from_site(
        db_session,
        site.id,
        ScopeConfigPayload(allowed_host_patterns=["example.com"]),
        include_inventory=True,
    )
    assert scan is not None
    scan.status = "completed"
    db_session.commit()
    delete_scan(db_session, scan.id, LocalContentStore(tmp_path))
    assert db_session.query(WebResource).count() == 1


def _site_payload(**overrides) -> WebsitePropertyCreate:
    data = {
        "name": "Example Site",
        "base_url": "https://example.com/",
        "description": None,
        "group_key": "Other",
        "locale": None,
        "platform_key": "Other",
        "ownership_key": "Unknown",
        "scope_config": ScopeConfigPayload(),
        "is_active": True,
    }
    data.update(overrides)
    return WebsitePropertyCreate(**data)
