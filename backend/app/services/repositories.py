from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.url_normalizer import NormalizedUrl
from app.database import materialize_outer_transaction
from app.models import WebResource
from app.services.url_identity import require_url_identity_runtime_write


def get_or_create_resource(
    db: Session,
    normalized: NormalizedUrl,
    *,
    normalization_version: str | None = None,
) -> WebResource:
    runtime = require_url_identity_runtime_write(db)
    version = normalization_version or runtime.active_normalization_version
    resource = db.scalar(
        select(WebResource).where(
            WebResource.normalization_version == version,
            WebResource.normalized_url == normalized.normalized_url,
        )
    )
    if resource:
        resource.last_seen_at = datetime.now(UTC)
        db.flush()
        return resource
    resource = WebResource(
        resource_type="page",
        normalization_version=version,
        normalized_url=normalized.normalized_url,
        scheme=normalized.scheme,
        host=normalized.host,
        port=normalized.port,
        path=normalized.path,
        query=normalized.query,
    )
    materialize_outer_transaction(db)
    try:
        with db.begin_nested():
            db.add(resource)
            db.flush()
        return resource
    except IntegrityError:
        winner = db.scalar(
            select(WebResource).where(
                WebResource.normalization_version == version,
                WebResource.normalized_url == normalized.normalized_url,
            )
        )
        if winner is None:
            raise
        winner.last_seen_at = datetime.now(UTC)
        db.flush()
        return winner
