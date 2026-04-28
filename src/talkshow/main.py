"""Talkshow — TTS microservice with a plugin architecture."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from talkshow.plugins import loader  # noqa: E402  -- after load_dotenv
from talkshow.routes import plugins, tts  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    loader.load_all()
    yield


app = FastAPI(
    title="Talkshow",
    description=(
        "A text-to-speech microservice. One endpoint, /speak, "
        "synthesises audio from raw SSML, plain text, or content "
        "fetched via a source plugin (eg. WordPress). Plugin "
        "architecture for TTS engines and data sources."
    ),
    version="0.5.0",
    lifespan=lifespan,
)

app.include_router(tts.router)
app.include_router(plugins.router)


@app.get("/", tags=["Health"])
async def root():
    return {"service": "talkshow", "status": "ok", "docs": "/docs"}


def run() -> None:
    """Console-script entrypoint (`uv run talkshow`)."""
    import os
    host = os.getenv("TALKSHOW_HOST", "0.0.0.0")
    port = int(os.getenv("TALKSHOW_PORT", "8000"))
    uvicorn.run("talkshow.main:app", host=host, port=port, reload=False)
