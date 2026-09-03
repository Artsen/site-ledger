from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import is_transient_database_lock
from app.models import WebsiteProperty


class FindingSerializationBusyError(RuntimeError):
    pass


def lock_site_for_finding_change(db: Session, site_id: int) -> WebsiteProperty | None:
    """Serialize Finding creation/deletion before inspecting Site-scoped state."""
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        driver_connection = connection.connection.driver_connection
        if driver_connection is None:
            raise RuntimeError("SQLite driver connection is unavailable.")
        if not driver_connection.in_transaction:
            try:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            except OperationalError as exc:
                if is_transient_database_lock(exc):
                    raise FindingSerializationBusyError(
                        "Finding state is being updated by another request. Try again."
                    ) from exc
                raise

    return db.scalar(select(WebsiteProperty).where(WebsiteProperty.id == site_id).with_for_update())
