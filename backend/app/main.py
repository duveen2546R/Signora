from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.v1 import captures, rigs, signs, translate
from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.services.ingest_service import sync_upload_directory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as session:
        try:
            jobs = sync_upload_directory(session)
            if jobs:
                logger.info("registered %d capture(s) from the uploads directory", len(jobs))
        except LookupError as exc:
            # A fresh installation may have CSVs before its first avatar rig profile. Keep the API
            # available so the profile can be uploaded, then the next restart will discover them.
            logger.warning("capture directory sync deferred: %s", exc)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# Composed sentences are long runs of smooth numeric series and compress to a fraction of their
# size; without this a three-sign sentence is over a megabyte of JSON.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (rigs.router, captures.router, signs.router, translate.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "app": settings.app_name}
