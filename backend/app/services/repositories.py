from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.url_normalizer import NormalizedUrl
from app.models import WebResource


def get_or_create_resource(db: Session, normalized: NormalizedUrl) -> WebResource:
    resource = db.scalar(
        select(WebResource).where(
            WebResource.resource_type == "page",
            WebResource.normalized_url == normalized.normalized_url,
        )
    )
    if resource:
        resource.last_seen_at = datetime.now(UTC)
        db.flush()
        return resource
    resource = WebResource(
        resource_type="page",
        normalized_url=normalized.normalized_url,
        scheme=normalized.scheme,
        host=normalized.host,
        port=normalized.port,
        path=normalized.path,
        query=normalized.query,
    )
    db.add(resource)
    db.flush()
    return resource
