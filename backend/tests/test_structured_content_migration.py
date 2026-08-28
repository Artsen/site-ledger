import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings


def test_structured_content_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "structured-content-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608070019")
        command.upgrade(config, "202608070020")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            artifact_indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(html_structured_content_artifacts)"
                )
            }
        assert "html_structured_content_artifacts" in tables
        assert "html_structured_content_sections" in tables
        assert "ix_html_structured_content_artifacts_blob_state" in artifact_indexes

        command.downgrade(config, "202608070019")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert "html_structured_content_artifacts" not in tables
        assert "html_structured_content_sections" not in tables

        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()


def test_structured_content_v2_migration_preserves_v1_and_round_trips(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "structured-content-v2-migration.db"
    monkeypatch.setenv("SCANNER_DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "202608260026")
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO content_blobs "
                "(id, sha256, storage_key, compression_type, raw_byte_size, stored_byte_size) "
                "VALUES (1, ?, 'v1.gz', 'gzip', 1, 1)",
                ("a" * 64,),
            )
            connection.execute(
                "INSERT INTO html_structured_content_artifacts "
                "(id, content_blob_id, extractor_version, extractor_config_version, "
                "extraction_state, document_profile, section_count, heading_count, "
                "heading_counts_json, document_word_count, document_character_count, "
                "document_text_sha256, outline_sha256, is_truncated, truncation_reasons_json) "
                "VALUES (1, 1, 'structured-content-v1', 'default-v1', 'ready', 'headed', "
                "0, 0, '{}', 0, 0, ?, ?, 0, '[]')",
                ("b" * 64, "c" * 64),
            )
            connection.commit()

        command.upgrade(config, "202608270027")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(html_structured_content_artifacts)"
                )
            }
            historical = connection.execute(
                "SELECT extractor_version, extractor_config_version, node_count "
                "FROM html_structured_content_artifacts WHERE id = 1"
            ).fetchone()
        assert "html_structured_content_nodes" in tables
        assert {
            "node_count",
            "canonical_document_sha256",
            "markdown_renderer_version",
            "markdown_sha256",
            "markdown_character_count",
        } <= columns
        assert historical == ("structured-content-v1", "default-v1", 0)

        command.downgrade(config, "202608260026")
        with sqlite3.connect(database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            historical = connection.execute(
                "SELECT extractor_version, extractor_config_version "
                "FROM html_structured_content_artifacts WHERE id = 1"
            ).fetchone()
        assert "html_structured_content_nodes" not in tables
        assert historical == ("structured-content-v1", "default-v1")
    finally:
        get_settings.cache_clear()
