import sqlite3
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from alembic import command
from app.config import get_settings
from app.models import ContentBlob, HtmlStructuredContentArtifact
from app.services.structured_content import get_or_create_structured_artifact


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
            connection.execute(
                "INSERT INTO html_structured_content_sections "
                "(id, artifact_id, position, kind, heading_level, heading_text, region_key, "
                "direct_text, direct_text_sha256, section_sha256, subtree_sha256, "
                "direct_word_count, direct_character_count, subtree_word_count, "
                "subtree_character_count, child_count, descendant_count, block_count, "
                "has_direct_content) VALUES "
                "(1, 1, 0, 'heading', 1, 'Historical', 'body', 'V1 body', ?, ?, ?, "
                "2, 7, 2, 7, 0, 0, 1, 1)",
                ("d" * 64, "e" * 64, "f" * 64),
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

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO html_structured_content_artifacts "
                "(id, content_blob_id, extractor_version, extractor_config_version, "
                "extraction_state, document_profile, section_count, heading_count, "
                "heading_counts_json, document_word_count, document_character_count, "
                "document_text_sha256, outline_sha256, is_truncated, truncation_reasons_json, "
                "node_count, canonical_document_sha256, markdown_renderer_version, "
                "markdown_sha256, markdown_character_count) VALUES "
                "(2, 1, 'structured-content-v2', 'canonical-document-v1', 'ready', 'headed', "
                "1, 1, '{\"h1\": 1}', 1, 5, ?, ?, 0, '[]', 1, ?, "
                "'structured-markdown-v1', ?, 7)",
                ("1" * 64, "2" * 64, "3" * 64, "4" * 64),
            )
            connection.execute(
                "INSERT INTO html_structured_content_nodes "
                "(id, artifact_id, position, kind, depth, region_key, inline_json, "
                "source_attributes_json, semantic_json, semantic_sha256, subtree_sha256, "
                "child_count, descendant_count) VALUES "
                "(1, 2, 0, 'document', 0, 'body', '[]', '{}', '{}', ?, ?, 0, 0)",
                ("5" * 64, "6" * 64),
            )
            connection.commit()

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
            historical_section = connection.execute(
                "SELECT heading_text, direct_text, subtree_sha256 "
                "FROM html_structured_content_sections WHERE id = 1"
            ).fetchone()
            v2_shells = connection.execute(
                "SELECT COUNT(*) FROM html_structured_content_artifacts "
                "WHERE extractor_version = 'structured-content-v2' "
                "AND extractor_config_version = 'canonical-document-v1'"
            ).fetchone()[0]
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(html_structured_content_artifacts)"
                )
            }
        assert "html_structured_content_nodes" not in tables
        assert historical == ("structured-content-v1", "default-v1")
        assert historical_section == ("Historical", "V1 body", "f" * 64)
        assert v2_shells == 0
        assert (
            not {
                "node_count",
                "canonical_document_sha256",
                "markdown_renderer_version",
                "markdown_sha256",
                "markdown_character_count",
            }
            & columns
        )

        command.upgrade(config, "202608270027")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with Session(engine) as session:
            v1 = session.get(HtmlStructuredContentArtifact, 1)
            assert v1 is not None
            assert (v1.extractor_version, v1.extractor_config_version) == (
                "structured-content-v1",
                "default-v1",
            )
            assert v1.sections[0].heading_text == "Historical"
            assert (
                session.scalar(
                    select(HtmlStructuredContentArtifact).where(
                        HtmlStructuredContentArtifact.extractor_version == "structured-content-v2",
                        HtmlStructuredContentArtifact.extractor_config_version
                        == "canonical-document-v1",
                    )
                )
                is None
            )
            blob = session.get(ContentBlob, 1)
            assert blob is not None
            prepared, reused = get_or_create_structured_artifact(
                session, blob, content=b"<h1>Prepared again</h1><p>Body</p>"
            )
            session.commit()
            assert reused is False
            assert prepared.node_count == len(prepared.nodes) > 0
            assert prepared.canonical_document_sha256
        engine.dispose()
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
