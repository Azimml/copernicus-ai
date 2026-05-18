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
    import os
    from app.core.db import init as db_init
    from app.core.config import settings, DATA_DIR
    logger.info("Initializing database…")
    db_init()
    logger.info("Pre-loading retrieval index...")
    try:
        chat_service.reload_index()
        logger.info("Retrieval index loaded.")
    except Exception as exc:
        logger.warning("Index not loaded yet: %s. Run `make index` to build it.", exc)

    # Pre-warm the answer cache so common demo questions feel instant.
    # Multi-worker mode: only one worker should run warmup — otherwise we'd
    # burn 4× the OpenAI cost for the same answers. An O_EXCL file create
    # acts as a cheap cross-process lock; the loser of the race no-ops.
    warmup_lock = DATA_DIR / "warmup.lock"
    warmup_owner = False
    if os.environ.get("CHAT_WARMUP_ENABLED", "1") == "1" and settings.openai_api_key:
        from app.services.warmup import start_warmup
        # Drop any stale lock from a previous run that didn't clean up
        # (e.g. SIGKILL). Warmup takes ~60s so anything older is dead.
        try:
            if warmup_lock.exists() and warmup_lock.stat().st_mtime < (
                __import__("time").time() - 300
            ):
                warmup_lock.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            fd = os.open(warmup_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            warmup_owner = True
            start_warmup(chat_service)
        except FileExistsError:
            logger.info("Skipping warmup — another worker is handling it")
    yield
    if warmup_owner:
        try:
            warmup_lock.unlink(missing_ok=True)
        except Exception:
            pass


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
