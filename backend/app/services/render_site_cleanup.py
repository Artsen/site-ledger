from sqlalchemy import delete, distinct, select
from sqlalchemy.orm import Session

from app.models import ArtifactBlob, RenderedArtifact, RenderedObservation, RenderRun
from app.storage.artifact_store import LocalArtifactStore


def prepare_render_site_cleanup(db: Session, site_id: int) -> list[ArtifactBlob]:
    site_observation_ids = select(RenderedObservation.id).where(
        RenderedObservation.render_run_id.in_(
            select(RenderRun.id).where(RenderRun.website_property_id == site_id)
        )
    )
    candidate_ids = list(
        db.scalars(
            select(distinct(RenderedArtifact.artifact_blob_id)).where(
                RenderedArtifact.rendered_observation_id.in_(site_observation_ids)
            )
        )
    )
    if not candidate_ids:
        return []
    shared_ids = set(
        db.scalars(
            select(distinct(RenderedArtifact.artifact_blob_id)).where(
                RenderedArtifact.artifact_blob_id.in_(candidate_ids),
                RenderedArtifact.rendered_observation_id.not_in(site_observation_ids),
            )
        )
    )
    return list(
        db.scalars(
            select(ArtifactBlob).where(
                ArtifactBlob.id.in_(candidate_ids), ArtifactBlob.id.not_in(shared_ids)
            )
        )
    )


def remove_render_site_blobs(db: Session, blobs: list[ArtifactBlob]) -> None:
    if blobs:
        db.execute(delete(ArtifactBlob).where(ArtifactBlob.id.in_([blob.id for blob in blobs])))


def cleanup_render_artifact_files(
    store: LocalArtifactStore, blobs: list[ArtifactBlob]
) -> list[str]:
    warnings: list[str] = []
    for blob in blobs:
        try:
            if not store.delete(blob):
                warnings.append(f"Rendered artifact file was already missing: {blob.storage_key}")
        except OSError as exc:
            warnings.append(f"Could not delete rendered artifact file {blob.storage_key}: {exc}")
    return warnings
