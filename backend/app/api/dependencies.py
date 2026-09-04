from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db

DbSession = Annotated[Session, Depends(get_db)]
ScanListLimit = Annotated[int, Query(ge=1, le=250)]
PageLimit = Annotated[int, Query(ge=1, le=250)]
PageOffset = Annotated[int, Query(ge=0)]
ResourceSortParam = Literal[
    "url",
    "kind",
    "mime_type",
    "http_status",
    "declared_size",
    "occurrence_count",
    "source_page_count",
    "observed",
    "in_scope_count",
    "first_discovered",
    "latest_discovered",
]
