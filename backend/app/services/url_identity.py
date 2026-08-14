from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
)
from app.models import UrlIdentityState, WebResource, WebResourceAlias


def ensure_url_identity_state(db: Session) -> UrlIdentityState:
    state = db.get(UrlIdentityState, 1)
    if state is not None:
        return state
    resource_count = db.scalar(select(func.count(WebResource.id))) or 0
    state = UrlIdentityState(
        id=1,
        active_normalization_version=(
            URL_NORMALIZATION_V1_VERSION if resource_count else URL_NORMALIZATION_V2_VERSION
        ),
        reconciliation_required=bool(resource_count),
        activated_at=datetime.now(UTC),
    )
    try:
        with db.begin_nested():
            db.add(state)
            db.flush()
    except IntegrityError:
        state = db.get(UrlIdentityState, 1)
        if state is None:
            raise
    return state


def active_url_normalization_version(db: Session) -> str:
    return ensure_url_identity_state(db).active_normalization_version


def resolve_resource(db: Session, requested_resource_id: int) -> WebResource | None:
    direct = db.get(WebResource, requested_resource_id)
    if direct is not None:
        return direct
    target_id = db.scalar(
        select(WebResourceAlias.target_resource_id).where(
            WebResourceAlias.legacy_resource_id == requested_resource_id
        )
    )
    return db.get(WebResource, target_id) if target_id is not None else None


def resolve_resource_id(db: Session, requested_resource_id: int) -> int | None:
    resource = resolve_resource(db, requested_resource_id)
    return resource.id if resource is not None else None
