from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import chat_service, router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.db import init as db_init
    logger.info("Initializing database…")
    db_init()
    logger.info("Pre-loading retrieval index...")
    try:
        chat_service.reload_index()
        logger.info("Retrieval index loaded.")
    except Exception as exc:
        logger.warning("Index not loaded yet: %s. Run `make index` to build it.", exc)
    yield


app = FastAPI(title="Copernicus Berlin AI Assistant", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


def _widget_asset(path: str) -> FileResponse:
    return FileResponse(path, headers=_NO_CACHE)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_index() -> FileResponse:
    return FileResponse("app/static/admin/index.html", headers=_NO_CACHE)


@app.get("/widget", include_in_schema=False)
@app.get("/widget/", include_in_schema=False)
async def widget_index() -> FileResponse:
    return _widget_asset("app/static/widget/index.html")


@app.get("/widget/embed.js", include_in_schema=False)
async def widget_embed() -> FileResponse:
    return _widget_asset("app/static/widget/embed.js")


@app.get("/widget/widget.js", include_in_schema=False)
async def widget_js() -> FileResponse:
    return _widget_asset("app/static/widget/widget.js")


@app.get("/widget/widget.css", include_in_schema=False)
async def widget_css() -> FileResponse:
    return _widget_asset("app/static/widget/widget.css")


app.mount("/widget", StaticFiles(directory="app/static/widget", html=True), name="widget")
app.mount("/admin", StaticFiles(directory="app/static/admin", html=True), name="admin")
