from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai_document_routes import router as ai_document_router
from app.api.routes import router
from app.config import get_settings
from app.product import API_TITLE, API_VERSION, PRODUCT_DESCRIPTION
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = LocalContentStore(settings.html_storage_root)
    app.state.content_store = store
    app.state.artifact_store = LocalArtifactStore(settings.rendered_artifact_storage_root)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        description=PRODUCT_DESCRIPTION,
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(ai_document_router)
    return app


app = create_app()
