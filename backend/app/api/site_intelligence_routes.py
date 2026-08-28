from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.site_intelligence import SiteIntelligenceRead
from app.services.site_intelligence import get_site_intelligence

router = APIRouter(prefix="/api", tags=["site-intelligence"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/sites/{site_id}/intelligence", response_model=SiteIntelligenceRead)
def site_intelligence(site_id: int, db: DbSession) -> SiteIntelligenceRead:
    result = get_site_intelligence(db, site_id)
    if result is None:
        raise HTTPException(404, "Site not found")
    return result
