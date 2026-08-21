from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.scope import ScopeConfig, ScopeEngine
from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
    UrlNormalizationError,
    normalize_url_v1,
    normalize_url_v2,
)
from app.models import UrlIdentityState, WebResource, WebResourceAlias
from app.services.repositories import get_or_create_resource
from app.services.url_identity import active_url_normalization_version, resolve_resource

ROOT = Path(__file__).resolve().parents[2]


def _reference_module():
    path = ROOT / "tools" / "url_identity_audit.py"
    spec = importlib.util.spec_from_file_location("url_identity_v2_reference", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REFERENCE = _reference_module()


@pytest.mark.parametrize(
    "raw",
    [
        "HTTP://EXAMPLE.COM:80/a/../b#fragment",
        "https://example.com/a%2fb",
        "https://example.com/a%3fb",
        "https://example.com/%2e/",
        "https://example.com/a//b",
        "https://example.com/%41",
        "https://bücher.example/",
        "https://[2001:DB8::1]/",
        "https://example.com/?b=2&a=1",
        "https://example.com/?id=2&id=1",
        "https://example.com/?a",
        "https://example.com/?a=",
        "https://example.com/?q=+",
        "https://example.com/?q=%20",
        "https://example.com/?a=1&&b=2",
    ],
)
def test_production_v2_matches_reviewed_candidate_reference(raw: str) -> None:
    assert (
        normalize_url_v2(raw).normalized_url
        == REFERENCE.candidate_normalize_url(raw).normalized_url
    )


def test_v1_is_frozen_and_v2_preserves_identity_distinctions() -> None:
    assert normalize_url_v1("https://example.com/a%2Fb").normalized_url == (
        "https://example.com/a/b"
    )
    assert normalize_url_v2("https://example.com/a%2Fb").normalized_url == (
        "https://example.com/a%2Fb"
    )
    assert (
        normalize_url_v2("https://example.com/?a").normalized_url
        != normalize_url_v2("https://example.com/?a=").normalized_url
    )
    with pytest.raises(UrlNormalizationError):
        normalize_url_v2("https://user:password@example.com/")


def test_v2_site_query_policy_dedupes_without_changing_global_identity() -> None:
    dropping = ScopeEngine(
        ScopeConfig(drop_query_parameters=["utm_*"]),
        "https://example.com/",
        URL_NORMALIZATION_V2_VERSION,
    )
    retaining = ScopeEngine(ScopeConfig(), "https://example.com/", URL_NORMALIZATION_V2_VERSION)
    first = dropping.evaluate("https://example.com/page?utm_source=a")
    second = dropping.evaluate("https://example.com/page?utm_source=b")
    other_site = retaining.evaluate("https://example.com/page?utm_source=b")

    assert first.normalized is not None and second.normalized is not None
    assert first.normalized.normalized_url.endswith("?utm_source=a")
    assert second.normalized.normalized_url.endswith("?utm_source=b")
    assert first.site_policy_key == second.site_policy_key == "https://example.com/page"
    assert other_site.site_policy_key == "https://example.com/page?utm_source=b"


def test_fresh_runtime_uses_v2_and_does_not_reuse_grandfathered_v1(db_session: Session) -> None:
    assert active_url_normalization_version(db_session) == URL_NORMALIZATION_V2_VERSION
    normalized = normalize_url_v2("https://example.com/same")
    legacy = WebResource(
        resource_type="page",
        normalization_version=URL_NORMALIZATION_V1_VERSION,
        normalized_url=normalized.normalized_url,
        scheme=normalized.scheme,
        host=normalized.host,
        port=normalized.port,
        path=normalized.path,
        query=normalized.query,
    )
    db_session.add(legacy)
    db_session.flush()

    active = get_or_create_resource(db_session, normalized)

    assert active.id != legacy.id
    assert active.normalization_version == URL_NORMALIZATION_V2_VERSION
    assert db_session.scalar(select(UrlIdentityState)).reconciliation_required is False


def test_versioned_uniqueness_allows_coexistence_but_rejects_v2_duplicate(
    db_session: Session,
) -> None:
    normalized = normalize_url_v2("https://example.com/coexist")
    for version in (URL_NORMALIZATION_V1_VERSION, URL_NORMALIZATION_V2_VERSION):
        db_session.add(
            WebResource(
                resource_type="page",
                normalization_version=version,
                normalized_url=normalized.normalized_url,
                scheme=normalized.scheme,
                host=normalized.host,
                path=normalized.path,
                query=normalized.query,
            )
        )
    db_session.commit()
    db_session.add(
        WebResource(
            resource_type="asset",
            normalization_version=URL_NORMALIZATION_V2_VERSION,
            normalized_url=normalized.normalized_url,
            scheme=normalized.scheme,
            host=normalized.host,
            path=normalized.path,
            query=normalized.query,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_resource_alias_resolution_is_direct_first(db_session: Session) -> None:
    normalized = normalize_url_v2("https://example.com/target")
    target = get_or_create_resource(db_session, normalized)
    db_session.add(
        WebResourceAlias(
            legacy_resource_id=999,
            target_resource_id=target.id,
            migration_id=999,
            alias_reason="synthetic-test",
        )
    )
    db_session.flush()

    assert resolve_resource(db_session, target.id) is target
    assert resolve_resource(db_session, 999) is target
