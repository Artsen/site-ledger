"""Run a deterministic local Resource Inventory benchmark."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from lxml import html
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.crawler.html_parser import parse_html
from app.database import Base
from app.models import (
    ResourceOccurrence,
    ResourceReferenceOccurrence,
    ResourceSnapshot,
    Scan,
    WebResource,
    WebsiteProperty,
)
from app.services.resource_queries import list_scan_resources, list_site_resources

PAGE_COUNT = 2_000


def _fixture(index: int) -> bytes:
    return f"""<html><body>
    <img src='/images/shared.webp' srcset='/images/shared.webp 1x, /images/shared@2x.webp 2x'>
    <img src='/images/unique-{index}.webp'><img src='/images/shared.webp'>
    <script src='/assets/app.js'></script><link rel='stylesheet' href='/assets/app.css'>
    <link rel='preload' as='font' href='/assets/site.woff2'>
    <a href='/documents/guide-{index % 10}.pdf'>Guide</a>
    </body></html>""".encode()


def _resource(url: str) -> WebResource:
    parts = urlsplit(url)
    return WebResource(
        normalized_url=url,
        resource_type="page",
        scheme=parts.scheme,
        host=parts.hostname or "fixture.test",
        port=parts.port,
        path=parts.path,
        query=parts.query,
    )


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="site-ledger-resource-benchmark-") as directory:
        database_path = Path(directory) / "resources.db"
        engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(engine)
        empty_size = database_path.stat().st_size

        started = time.perf_counter()
        for index in range(PAGE_COUNT):
            document = html.fromstring(_fixture(index))
            document.xpath("//a[@href]")
        anchor_only_ms = (time.perf_counter() - started) * 1_000

        started = time.perf_counter()
        parsed_pages = [
            parse_html(_fixture(index), f"https://fixture.test/pages/{index}")
            for index in range(PAGE_COUNT)
        ]
        resource_parse_ms = (time.perf_counter() - started) * 1_000

        with Session(engine, expire_on_commit=False) as db:
            site = WebsiteProperty(
                name="Resource benchmark",
                base_url="https://fixture.test/",
                normalized_base_url="https://fixture.test/",
                group_key="Benchmark",
                platform_key="Generated",
                ownership_key="Local",
                scope_config={},
                is_active=True,
            )
            scan = Scan(
                website_property=site,
                starting_url="https://fixture.test/",
                status="completed",
                scope_config={},
                discovered_count=PAGE_COUNT,
                fetched_count=PAGE_COUNT,
                html_page_observed_count=PAGE_COUNT,
            )
            db.add(scan)
            db.flush()
            page_resources = [
                _resource(f"https://fixture.test/pages/{index}") for index in range(PAGE_COUNT)
            ]
            target_urls = sorted(
                {
                    reference.resolved_url
                    for parsed in parsed_pages
                    for reference in parsed.resource_references
                }
                | {
                    anchor.resolved_url
                    for parsed in parsed_pages
                    for anchor in parsed.anchors
                    if anchor.resolved_url
                }
            )
            target_resources = [_resource(url) for url in target_urls]
            db.add_all(page_resources + target_resources)
            db.flush()
            targets = {item.normalized_url: item.id for item in target_resources}
            snapshots = [
                ResourceSnapshot(
                    scan_id=scan.id,
                    resource_id=resource.id,
                    requested_url=resource.normalized_url,
                    final_url=resource.normalized_url,
                    http_status=200,
                    content_type="text/html",
                    crawl_depth=1,
                    fetch_state="fetched",
                    representation_kind="html_page",
                    representation_rule="mime_text_html",
                    normalized_mime_type="text/html",
                    response_body_state="full_html",
                    inspected_prefix_byte_count=0,
                )
                for resource in page_resources
            ]
            db.add_all(snapshots)
            db.flush()

            started = time.perf_counter()
            occurrences = []
            anchor_occurrences = []
            for snapshot, parsed in zip(snapshots, parsed_pages, strict=True):
                for reference in parsed.resource_references:
                    occurrences.append(
                        ResourceReferenceOccurrence(
                            source_snapshot_id=snapshot.id,
                            target_resource_id=targets[reference.resolved_url],
                            relation_type=reference.relation_type,
                            element_tag=reference.element_tag,
                            attribute_name=reference.attribute_name,
                            raw_url=reference.raw_url,
                            resolved_url=reference.resolved_url,
                            normalized_target_url=reference.resolved_url,
                            inferred_kind=reference.inferred_kind,
                            classification_rule=reference.classification_rule,
                            dom_path=reference.dom_path,
                            rel=reference.rel,
                            media=reference.media,
                            type_hint=reference.type_hint,
                            as_hint=reference.as_hint,
                            srcset_descriptor=reference.srcset_descriptor,
                            alt_text=reference.alt_text,
                            title=reference.title,
                            width_attribute=reference.width_attribute,
                            height_attribute=reference.height_attribute,
                            in_scope=True,
                            scope_decision="crawlable",
                        )
                    )
                for anchor in parsed.anchors:
                    if anchor.resolved_url is None:
                        continue
                    anchor_occurrences.append(
                        ResourceOccurrence(
                            source_snapshot_id=snapshot.id,
                            relation_type="page_link",
                            raw_href=anchor.raw_href,
                            resolved_url=anchor.resolved_url,
                            normalized_target_url=anchor.resolved_url,
                            target_resource_id=targets[anchor.resolved_url],
                            anchor_text=anchor.anchor_text,
                            title=anchor.title,
                            aria_label=anchor.aria_label,
                            rel=anchor.rel,
                            target=anchor.target,
                            dom_path=anchor.dom_path,
                            in_scope=True,
                            scope_decision="crawlable",
                            link_role=anchor.link_role,
                            link_role_rule=anchor.link_role_rule,
                            link_context_json=anchor.link_context_json,
                        )
                    )
            db.add_all(occurrences)
            db.add_all(anchor_occurrences)
            db.commit()
            persistence_ms = (time.perf_counter() - started) * 1_000

            query_count = 0

            def count_query(*_args: object) -> None:
                nonlocal query_count
                query_count += 1

            event.listen(engine, "before_cursor_execute", count_query)
            started = time.perf_counter()
            scan_inventory = list_scan_resources(db, scan.id, limit=50)
            scan_query_ms = (time.perf_counter() - started) * 1_000
            scan_query_count = query_count
            started = time.perf_counter()
            site_inventory = list_site_resources(db, site.id, limit=50)
            site_query_ms = (time.perf_counter() - started) * 1_000
            site_query_count = query_count - scan_query_count
            event.remove(engine, "before_cursor_execute", count_query)

        result: dict[str, object] = {
            "pages": PAGE_COUNT,
            "unique_resources": scan_inventory.total if scan_inventory else 0,
            "total_occurrences": len(occurrences) + len(anchor_occurrences),
            "anchor_only_parse_ms": round(anchor_only_ms, 2),
            "resource_reference_parse_ms": round(resource_parse_ms, 2),
            "occurrence_persistence_ms": round(persistence_ms, 2),
            "scan_inventory_query_ms": round(scan_query_ms, 2),
            "scan_inventory_query_count": scan_query_count,
            "site_inventory_query_ms": round(site_query_ms, 2),
            "site_inventory_query_count": site_query_count,
            "site_unique_resources": site_inventory.total if site_inventory else 0,
            "database_size_increase_bytes": database_path.stat().st_size - empty_size,
        }
        engine.dispose()
        return result


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
