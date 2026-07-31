import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models import Scan, WebsiteProperty
from app.schemas.scans import ScopeConfigPayload
from app.schemas.sites import WebsitePropertyCreate, WebsitePropertyUpdate
from app.services.scan_deletion import delete_scan
from app.services.site_management import (
    DuplicateSiteError,
    InactiveSiteError,
    SiteHasScansError,
    create_scan_from_site,
    create_site,
    delete_site,
    update_site,
)
from app.services.site_queries import get_site_detail, list_site_scans, list_sites
from app.storage.content_store import LocalContentStore


def test_create_site_normalizes_and_validates(db_session: Session) -> None:
    site = create_site(
        db_session,
        _site_payload(
            base_url="HTTPS://WWW.Example.COM:443/learn/?a=1",
            locale="en-us",
            group_key="customer_education",
            platform_key="wordpress_learn",
            ownership_key="customer_education",
        ),
    )

    assert site.base_url == "https://www.example.com/learn/?a=1"
    assert site.normalized_base_url == "https://www.example.com/learn/?a=1"
    assert site.locale == "en-US"
    assert site.is_active is True

    with pytest.raises(ValidationError):
        _site_payload(group_key="bad")
    with pytest.raises(ValidationError):
        _site_payload(locale="english")
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        create_site(db_session, _site_payload(base_url="ftp://example.com/"))


def test_duplicate_base_url_is_blocked_across_active_states(db_session: Session) -> None:
    create_site(db_session, _site_payload(base_url="https://example.com/"))

    with pytest.raises(DuplicateSiteError):
        create_site(db_session, _site_payload(base_url="https://EXAMPLE.com/"))

    existing = db_session.query(WebsiteProperty).one()
    existing.is_active = False
    db_session.commit()
    with pytest.raises(DuplicateSiteError):
        create_site(db_session, _site_payload(base_url="https://example.com/"))


def test_update_site_does_not_mutate_existing_scan_scope(db_session: Session) -> None:
    site = create_site(
        db_session,
        _site_payload(scope_config=ScopeConfigPayload(max_pages=10, included_path_prefixes=["/"])),
    )
    scan = create_scan_from_site(
        db_session, site.id, ScopeConfigPayload(max_pages=15, included_path_prefixes=["/"])
    )
    assert scan is not None

    updated = update_site(
        db_session,
        site.id,
        WebsitePropertyUpdate(
            name="Updated",
            scope_config=ScopeConfigPayload(max_pages=99, included_path_prefixes=["/docs/"]),
        ),
    )

    assert updated is not None
    assert updated.scope_config["max_pages"] == 99
    db_session.refresh(scan)
    assert scan.scope_config["max_pages"] == 15
    assert scan.scope_config["included_path_prefixes"] == ["/"]


def test_create_scan_from_site_requires_active_site_and_copies_scope(db_session: Session) -> None:
    site = create_site(db_session, _site_payload())
    override = ScopeConfigPayload(max_pages=7, max_depth=2, included_path_prefixes=["/custom/"])
    scan = create_scan_from_site(db_session, site.id, override)

    assert scan is not None
    assert scan.website_property_id == site.id
    assert scan.starting_url == site.base_url
    assert scan.scope_config["max_pages"] == 7
    assert site.scope_config["max_pages"] == 100

    site.is_active = False
    db_session.commit()
    with pytest.raises(InactiveSiteError):
        create_scan_from_site(db_session, site.id, override)


def test_site_list_filters_sorts_paginates_and_aggregates(db_session: Session) -> None:
    alpha = create_site(db_session, _site_payload(name="Alpha", base_url="https://alpha.example/"))
    beta = create_site(
        db_session,
        _site_payload(
            name="Beta",
            base_url="https://beta.example/",
            group_key="marketing",
            platform_key="wordpress_root",
            ownership_key="web_team",
        ),
    )
    _scan(db_session, alpha, status="completed", discovered=3, failed=0)
    latest = _scan(db_session, beta, status="failed", discovered=8, failed=2)
    db_session.commit()

    result = list_sites(
        db_session,
        search="beta",
        group_key="marketing",
        locale=None,
        platform_key=None,
        ownership_key=None,
        active_state="active",
        sort="latest_scan_at",
        direction="desc",
        limit=10,
        offset=0,
    )

    assert result.total == 1
    assert result.items[0].id == beta.id
    assert result.items[0].total_scan_count == 1
    assert result.items[0].latest_scan_id == latest.id
    assert result.items[0].latest_scan_failed_count == 2


def test_site_detail_and_site_scan_history(db_session: Session) -> None:
    site = create_site(db_session, _site_payload())
    _scan(db_session, site, status="completed")
    failed = _scan(db_session, site, status="failed")
    db_session.commit()

    detail = get_site_detail(db_session, site.id)
    assert detail is not None
    assert detail.total_scan_count == 2
    assert detail.latest_scan is not None
    assert detail.latest_scan.id == failed.id
    assert len(detail.recent_scans) == 2

    scans = list_site_scans(
        db_session,
        site.id,
        status="failed",
        sort="created_at",
        direction="desc",
        limit=1,
        offset=0,
    )
    assert scans is not None
    assert scans.total == 1
    assert scans.items[0].status == "failed"


def test_site_deletion_rules_and_scan_deletion_leaves_site(db_session: Session, tmp_path) -> None:
    empty = create_site(db_session, _site_payload(base_url="https://empty.example/"))
    assert delete_site(db_session, empty.id) == empty.id
    assert db_session.get(WebsiteProperty, empty.id) is None

    inactive = create_site(
        db_session, _site_payload(base_url="https://inactive.example/", is_active=False)
    )
    assert delete_site(db_session, inactive.id) == inactive.id

    site = create_site(db_session, _site_payload())
    scan = _scan(db_session, site)
    db_session.commit()
    with pytest.raises(SiteHasScansError):
        delete_site(db_session, site.id)

    result = delete_scan(db_session, scan.id, LocalContentStore(tmp_path))
    assert result is not None
    assert db_session.get(WebsiteProperty, site.id) is not None


def test_ad_hoc_scan_with_null_site_remains_valid(db_session: Session) -> None:
    scan = Scan(
        starting_url="https://adhoc.example/",
        status="completed",
        scope_config=ScopeConfigPayload().model_dump(),
    )
    db_session.add(scan)
    db_session.commit()

    assert scan.website_property_id is None
    assert scan.website_property_name is None


def _site_payload(**overrides) -> WebsitePropertyCreate:
    data = {
        "name": "Example Site",
        "base_url": "https://example.com/",
        "description": "A site",
        "group_key": "other",
        "locale": None,
        "platform_key": "other",
        "ownership_key": "unknown",
        "scope_config": ScopeConfigPayload(),
        "is_active": True,
    }
    data.update(overrides)
    return WebsitePropertyCreate(**data)


def _scan(
    db_session: Session,
    site: WebsiteProperty,
    status: str = "completed",
    discovered: int = 1,
    failed: int = 0,
) -> Scan:
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status=status,
        scope_config=site.scope_config.copy(),
        discovered_count=discovered,
        fetched_count=discovered,
        failed_count=failed,
        skipped_count=0,
        queued_count=0,
    )
    db_session.add(scan)
    db_session.flush()
    return scan
