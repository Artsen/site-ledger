import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC instants and restore tzinfo stripped by SQLite."""

    impl = DateTime
    cache_ok = True

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: datetime | None, _dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, _dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


settings = get_settings()
if settings.database_url.startswith("sqlite:///"):
    db_path = Path(settings.database_url.removeprefix("sqlite:///"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: object) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
        if not _is_memory_sqlite(settings.database_url):
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _is_memory_sqlite(database_url: str) -> bool:
    return database_url in {"sqlite://", "sqlite:///:memory:"} or database_url.endswith(":memory:")


def is_transient_database_lock(error: OperationalError) -> bool:
    if not isinstance(error.orig, sqlite3.OperationalError):
        return False
    message = str(error.orig).lower()
    return "database is locked" in message or "database table is locked" in message


def materialize_outer_transaction(db: Session) -> None:
    """Prevent a first SQLite SAVEPOINT from becoming an independently committed transaction."""
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = connection.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("SQLite driver connection is unavailable.")
    if not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
