from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.database import SessionLocal
from app.services.scan_runner import ScanRunner
from app.storage.content_store import LocalContentStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    store = LocalContentStore(settings.html_storage_root)
    runner = ScanRunner(SessionLocal, store)
    runner.mark_interrupted()
    app.state.content_store = store
    app.state.scan_runner = runner
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Website Scanner", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
