"""Talkshow — TTS microservice with a plugin architecture."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app.plugins import loader
from app.routes import plugins, tts


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
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(tts.router)
app.include_router(plugins.router)


@app.get("/", tags=["Health"])
async def root():
    return {"service": "talkshow", "status": "ok", "docs": "/docs"}
