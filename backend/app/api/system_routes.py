from fastapi import APIRouter

from app.api.dependencies import DbSession
from app.services.url_identity import (
    inspect_url_identity_state,
)

router = APIRouter(prefix="/api")


@router.get("/health")
def health(db: DbSession) -> dict[str, object]:
    identity = inspect_url_identity_state(db)
    return {
        "status": "maintenance_required" if identity.maintenance_required else "ok",
        "url_identity": {
            "active_version": identity.active_normalization_version,
            "maintenance_required": identity.maintenance_required,
            "migration_id": identity.active_migration_id,
            "migration_status": identity.migration_status,
        },
    }
