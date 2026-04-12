"""Talkshow — TTS microservice with a plugin architecture."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app.plugins import loader
from app.routes import outputs, plugins, sources, tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    loader.load_all()
    yield


app = FastAPI(
    title="Talkshow",
    description=(
        "A text-to-speech microservice with a plugin architecture for TTS engines, "
        "data sources, and output formatters. Supports Microsoft Azure TTS, "
        "WordPress data sources, and Twilio XML / Signalwire LAML output."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(tts.router)
app.include_router(sources.router)
app.include_router(outputs.router)
app.include_router(plugins.router)


@app.get("/", tags=["Health"])
async def root():
    return {"service": "talkshow", "status": "ok", "docs": "/docs"}
