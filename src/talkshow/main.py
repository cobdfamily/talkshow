"""Talkshow — TTS microservice with a plugin architecture."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Request

load_dotenv()

from talkshow.plugins import loader  # noqa: E402  -- after load_dotenv
from talkshow.routes import plugins, tts  # noqa: E402

_access_logger = logging.getLogger("talkshow.access")

__version__ = "1.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    loader.load_all()
    yield


app = FastAPI(
    title="Talkshow",
    description=(
        "A text-to-speech microservice. One endpoint, /v1/speak, "
        "synthesises audio from raw SSML, plain text, or content "
        "fetched via a source plugin (eg. WordPress). Plugin "
        "architecture for TTS engines and data sources."
    ),
    version=__version__,
    lifespan=lifespan,
    redoc_url="/redocs",
)


@app.middleware("http")
async def request_id_and_service_headers(request: Request, call_next):
    """End-to-end tracing (v1.0.6). Echo the caller's
    X-Request-Id (trunk forwards it on the trunk -> talkshow
    hop) or mint one, log it, and return it -- so a single
    inbound call correlates across trunk and talkshow logs.
    Also emit the fleet-standard X-Service / X-Service-Version
    headers (matches trunk, dispatch, brian)."""
    rid = request.headers.get("x-request-id") or secrets.token_hex(8)
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    response.headers["X-Service"] = "talkshow"
    response.headers["X-Service-Version"] = __version__
    _access_logger.info(
        "request",
        extra={
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
        },
    )
    return response


# Whole API lives under /v1/* for explicit versioning. Bumping to
# /v2 later is the sanctioned way to make breaking changes; clients
# pin the version they speak. Health endpoint stays unversioned at
# / so orchestration probes don't have to know the API version.
v1 = APIRouter(prefix="/v1")
v1.include_router(tts.router)
v1.include_router(plugins.router)
app.include_router(v1)


@app.get("/", tags=["Health"])
async def root():
    return {"service": "talkshow", "status": "ok", "version": app.version}


def run() -> None:
    """Console-script entrypoint (`uv run talkshow`)."""
    import os

    host = os.getenv("TALKSHOW_HOST", "0.0.0.0")
    port = int(os.getenv("TALKSHOW_PORT", "8000"))
    uvicorn.run("talkshow.main:app", host=host, port=port, reload=False)
