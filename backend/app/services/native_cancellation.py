from sqlalchemy.orm import Session

from app.models import BackgroundJob
from app.services.background_jobs import request_cancellation


def request_native_cancellation(
    db: Session,
    job: BackgroundJob,
    message: str = "Cancellation requested.",
) -> BackgroundJob:
    """Cancel queued native work atomically; running work remains cooperative."""
    request_cancellation(db, job, message, commit=False)
    db.commit()
    db.refresh(job)
    return job
