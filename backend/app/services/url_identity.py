from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crawler.url_normalizer import (
    URL_NORMALIZATION_V1_VERSION,
    URL_NORMALIZATION_V2_VERSION,
)
from app.models import UrlIdentityMigration, UrlIdentityState, WebResource, WebResourceAlias


@dataclass(frozen=True)
class UrlIdentityRuntimeStatus:
    active_normalization_version: str
    reconciliation_required: bool
    active_migration_id: int | None
    migration_status: str | None
    maintenance_required: bool
    maintenance_reason: str | None


class UrlIdentityMaintenanceRequired(RuntimeError):
    def __init__(self, status: UrlIdentityRuntimeStatus) -> None:
        self.migration_id = status.active_migration_id
        self.migration_status = status.migration_status
        self.reason = status.maintenance_reason
        migration = self.migration_id if self.migration_id is not None else "unknown"
        migration_status = self.migration_status or "missing"
        super().__init__(
            f"URL identity migration {migration} is in {migration_status!r} state; "
            "normal writes are disabled until recovery completes."
        )


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


def inspect_url_identity_state(db: Session) -> UrlIdentityRuntimeStatus:
    state = ensure_url_identity_state(db)
    migration_status: str | None = None
    maintenance_reason: str | None = None

    if state.active_migration_id is None:
        healthy = (
            state.active_normalization_version == URL_NORMALIZATION_V1_VERSION
            and state.reconciliation_required
        ) or (
            state.active_normalization_version == URL_NORMALIZATION_V2_VERSION
            and not state.reconciliation_required
        )
        if not healthy:
            maintenance_reason = "inconsistent_identity_state"
    else:
        migration = db.get(UrlIdentityMigration, state.active_migration_id)
        if migration is None:
            migration_status = "missing"
            maintenance_reason = "active_migration_missing"
        else:
            migration_status = migration.status
            healthy = (
                migration.status == "completed"
                and migration.source_normalization_version == URL_NORMALIZATION_V1_VERSION
                and migration.target_normalization_version == URL_NORMALIZATION_V2_VERSION
                and state.active_normalization_version == URL_NORMALIZATION_V2_VERSION
                and not state.reconciliation_required
            )
            if not healthy:
                maintenance_reason = (
                    "active_migration_not_completed"
                    if migration.status != "completed"
                    else "inconsistent_identity_state"
                )

    return UrlIdentityRuntimeStatus(
        active_normalization_version=state.active_normalization_version,
        reconciliation_required=state.reconciliation_required,
        active_migration_id=state.active_migration_id,
        migration_status=migration_status,
        maintenance_required=maintenance_reason is not None,
        maintenance_reason=maintenance_reason,
    )


def require_url_identity_runtime_write(db: Session) -> UrlIdentityRuntimeStatus:
    status = inspect_url_identity_state(db)
    if status.maintenance_required:
        raise UrlIdentityMaintenanceRequired(status)
    return status


def active_url_normalization_version(db: Session) -> str:
    return require_url_identity_runtime_write(db).active_normalization_version


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
