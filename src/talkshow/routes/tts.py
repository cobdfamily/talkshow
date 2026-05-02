"""TTS endpoints: ``/speak`` (synthesise + return audio),
``/queue`` (warm the cache without waiting), and ``/cache`` (stream
a previously cached file by path).

``/speak`` and ``/queue`` accept content in three mutually-
substitutable forms:

  ssml -> sent verbatim to the TTS engine
  text -> wrapped in an SSML envelope built from voice/lang/rate/pitch
  url  -> fetched via a source plugin (using offset + part), then
          synthesised as text

When more than one form is supplied, precedence is:

  ssml > text > url

so an explicit override always wins.

``/speak`` returns ``audio/wav`` and blocks on synthesis when the
cache is cold. ``/queue`` returns ``{"ready": bool, "path": str?}``:
``ready=true`` when the cached file is already on disk (the
absolute path is included so the caller can stream it via
``/cache`` or read it directly), ``ready=false`` after starting
synthesis in the background.

``/cache?path=...`` streams a previously cached audio file. Path
must resolve inside the cache directory; traversal attempts and
arbitrary filesystem reads are rejected.

When synthesis fails, ``/queue`` reports ``attempts`` and ``error``
on the next poll. After ``MAX_QUEUE_ATTEMPTS`` consecutive
failures it stops retrying — callers should give up at that
point.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..plugins import loader
from ..plugins.base import TTSPlugin

router = APIRouter(tags=["TTS"])

_log = logging.getLogger(__name__)

# Module-level set of cache paths currently being synthesised by a
# background task started via /queue. Keeps duplicate /queue polls
# from kicking off N parallel syntheses for the same input. Same
# input always resolves to the same path (the cache key is a hash
# of the request), so set membership is exact.
_INFLIGHT: set[Path] = set()

# Per-path failure tracking. Each entry is ``{"attempts": int,
# "error": str}``. Reset on successful synthesis or cache hit.
# At ``MAX_QUEUE_ATTEMPTS`` we stop auto-retrying; the caller sees
# ``attempts`` >= cap and gives up.
_FAILED: dict[Path, dict] = {}

_INFLIGHT_LOCK = asyncio.Lock()

MAX_QUEUE_ATTEMPTS = 3


def _cache_root() -> Path:
    """Absolute path of the cache base. /speak's ``path`` argument
    must resolve to a location inside this directory; anywhere else
    is rejected as a path-traversal attempt."""
    return Path(os.getenv("TALKSHOW_CACHE_DIR", "cache")).resolve()


def _is_safe_cache_path(candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(_cache_root())
        return True
    except (OSError, ValueError):
        return False


class SpeakBody(BaseModel):
    ssml: str | None = Field(None, description="Raw SSML; sent verbatim")
    text: str | None = Field(None, description="Plain text to synthesise")
    url: str | None = Field(None, description="Source URL to fetch from")
    offset: int | None = Field(None, description="When url is an index, the article offset")
    part: str | None = Field(
        None,
        description="Which part of the source to speak: 'header' or 'body' (default body)",
    )
    voice: str | None = Field(None, description="Voice name (e.g. en-US-EmmaMultilingualNeural)")
    language: str | None = Field(None, description="Language code (e.g. en-US)")
    rate: str | None = Field(None, description="Speech rate (e.g. +10%)")
    pitch: str | None = Field(None, description="Speech pitch (e.g. -5%)")
    engine: str | None = Field(None, description="TTS engine plugin name")
    source: str | None = Field(None, description="Source plugin name (default: wordpress)")


async def _resolve_text(
    *,
    ssml: str | None,
    text: str | None,
    url: str | None,
    offset: int,
    part: str,
    source_name: str,
) -> tuple[str, str | None]:
    """Pick the synthesis input.

    Returns (text_for_tts, ssml_or_None). When SSML is set, the
    text return is empty -- the engine will use the SSML directly.
    """
    if ssml:
        return "", ssml
    if text:
        return text, None
    if url:
        plugin = loader.get_source(source_name)
        if not plugin:
            available = list(loader.list_sources().keys())
            raise HTTPException(
                status_code=404,
                detail=f"Source '{source_name}' not found. Available: {available}",
            )
        try:
            article = await plugin.fetch(url, offset=offset, part=part)
        except IndexError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Source fetch failed: {e}")
        return article.get("text", ""), None
    raise HTTPException(
        status_code=400,
        detail="provide one of: ssml, text, url",
    )


def _serve_cached_path(path_str: str) -> Response:
    """Stream a previously cached file directly. Validates the path
    is inside the cache directory and points at a ``.wav`` file
    before serving. The suffix check is defence-in-depth: cache
    contents are produced only by talkshow today, but rejecting
    non-WAV reads keeps a misplaced file in the cache dir from
    being served as audio (and rejects half-written ``.wav.tmp``
    files from the atomic-write window)."""
    candidate = Path(path_str)
    if not _is_safe_cache_path(candidate):
        raise HTTPException(
            status_code=403,
            detail="path must be inside the talkshow cache directory",
        )
    resolved = candidate.resolve()
    if resolved.suffix.lower() != ".wav":
        raise HTTPException(
            status_code=403,
            detail="only .wav files may be served from the cache",
        )
    if not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail="cached file not found",
        )
    return FileResponse(
        str(resolved),
        media_type="audio/wav",
        filename=resolved.name,
    )


async def _do_synthesize(
    *,
    ssml: str | None,
    text: str | None,
    url: str | None,
    offset: int,
    part: str,
    voice: str | None,
    language: str | None,
    rate: str | None,
    pitch: str | None,
    engine_name: str,
    source_name: str,
) -> Response:
    final_text, final_ssml = await _resolve_text(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        source_name=source_name,
    )

    if not final_text and not final_ssml:
        raise HTTPException(
            status_code=400, detail="resolved input was empty",
        )

    plugin = loader.get_tts(engine_name)
    if not plugin:
        available = list(loader.list_tts().keys())
        raise HTTPException(
            status_code=404,
            detail=f"TTS engine '{engine_name}' not found. Available: {available}",
        )

    stream = plugin.synthesize(
        final_text,
        ssml=final_ssml,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
    )

    chunks: list[bytes] = []
    try:
        async for chunk in stream:
            chunks.append(chunk)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS synthesis failed: {e}")

    if not chunks:
        raise HTTPException(status_code=500, detail="TTS engine returned no audio")

    audio_data = b"".join(chunks)
    return Response(
        content=audio_data,
        media_type="audio/wav",
        headers={"Content-Length": str(len(audio_data))},
    )


_common = dict(
    summary="Synthesise speech audio",
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio"},
        400: {"description": "Missing required input"},
        404: {"description": "Engine or source plugin not found"},
        502: {"description": "Source fetch or TTS synthesis failed"},
    },
)


@router.get(
    "/speak",
    description=(
        "Synthesise speech audio. Provide one of: `ssml` (verbatim), "
        "`text` (plain), or `url` (fetched via the configured source "
        "plugin). When `url` is used, `offset` selects which article "
        "from an index page and `part` picks 'header' (just the "
        "title/byline/date line) or 'body' (the article itself). "
        "Returns audio/wav. To play a previously cached file by its "
        "absolute path (eg. one reported by /queue), call /cache "
        "instead."
    ),
    **_common,
)
async def synthesize_get(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text to synthesise"),
    url: str | None = Query(None, description="Source URL"),
    offset: int = Query(0, description="Article offset (when url is an index)"),
    part: str = Query("body", description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
):
    return await _do_synthesize(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
        engine_name=engine or "azure",
        source_name=source or "wordpress",
    )


@router.post(
    "/speak",
    description=(
        "Synthesise speech audio. Same args as GET; query takes "
        "precedence over body when both supply a value."
    ),
    **_common,
)
async def synthesize_post(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text"),
    url: str | None = Query(None, description="Source URL"),
    offset: int | None = Query(None, description="Article offset"),
    part: str | None = Query(None, description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
    body: SpeakBody | None = None,
):
    final_ssml = ssml or (body.ssml if body else None)
    final_text = text or (body.text if body else None)
    final_url = url or (body.url if body else None)
    final_offset = offset if offset is not None else (body.offset if body else None)
    final_part = part or (body.part if body else None) or "body"
    final_voice = voice or (body.voice if body else None)
    final_language = language or (body.language if body else None)
    final_rate = rate or (body.rate if body else None)
    final_pitch = pitch or (body.pitch if body else None)
    engine_name = engine or (body.engine if body else None) or "azure"
    source_name = source or (body.source if body else None) or "wordpress"

    return await _do_synthesize(
        ssml=final_ssml,
        text=final_text,
        url=final_url,
        offset=final_offset or 0,
        part=final_part,
        voice=final_voice,
        language=final_language,
        rate=final_rate,
        pitch=final_pitch,
        engine_name=engine_name,
        source_name=source_name,
    )


# ----------------------------------------------------------------------
# /cache — serve a previously cached file by path
# ----------------------------------------------------------------------


@router.get(
    "/cache",
    summary="Stream a previously cached audio file",
    description=(
        "Returns the WAV file at `path`, validated to be inside the "
        "talkshow cache directory. Typical use: poll `/queue` until "
        "`ready: true`, take its `path`, hand it to `/cache`. "
        "Path-traversal attempts and reads outside the cache return 403."
    ),
    responses={
        200: {"content": {"audio/wav": {}}, "description": "WAV audio"},
        403: {"description": "Path is outside the cache directory"},
        404: {"description": "File not found at the given path"},
    },
    tags=["Cache"],
)
async def cache_get(
    path: str = Query(
        ...,
        description="Absolute path to a cached file inside the cache directory",
    ),
):
    return _serve_cached_path(path)


# ----------------------------------------------------------------------
# /queue — cache-warm endpoint
# ----------------------------------------------------------------------


async def _kickoff_synthesis(
    plugin: TTSPlugin,
    *,
    text: str,
    ssml: str | None,
    voice: str | None,
    language: str | None,
    rate: str | None,
    pitch: str | None,
    cache_path: Path,
) -> None:
    """Drain the synthesize() generator so the plugin writes the
    cache file. Tracks the path in ``_INFLIGHT`` so duplicate /queue
    calls for the same input don't trigger parallel syntheses, and
    records failures in ``_FAILED`` so the next /queue poll can
    surface the error and stop retrying after MAX_QUEUE_ATTEMPTS."""
    async with _INFLIGHT_LOCK:
        if cache_path in _INFLIGHT:
            return
        _INFLIGHT.add(cache_path)
    try:
        async for _ in plugin.synthesize(
            text,
            ssml=ssml,
            voice=voice,
            language=language,
            rate=rate,
            pitch=pitch,
        ):
            pass
        # Success — clear any prior failure so a re-queue starts fresh.
        async with _INFLIGHT_LOCK:
            _FAILED.pop(cache_path, None)
    except Exception as e:
        async with _INFLIGHT_LOCK:
            existing = _FAILED.get(cache_path, {"attempts": 0})
            _FAILED[cache_path] = {
                "attempts": existing["attempts"] + 1,
                "error": str(e),
            }
        _log.warning(
            "background synthesis failed for %s (attempt %d): %s",
            cache_path,
            _FAILED[cache_path]["attempts"],
            e,
        )
    finally:
        async with _INFLIGHT_LOCK:
            _INFLIGHT.discard(cache_path)


async def _do_queue(
    *,
    ssml: str | None,
    text: str | None,
    url: str | None,
    offset: int,
    part: str,
    voice: str | None,
    language: str | None,
    rate: str | None,
    pitch: str | None,
    engine_name: str,
    source_name: str,
    peek: bool = False,
) -> dict:
    """Resolve a request and tell the caller whether the audio is
    cached. With ``peek=True`` no synthesis is started — the call
    only reports cache status. Without it the standard
    fire-and-forget background synthesis runs on a cold cache.

    The 400 / 404 paths still apply when the source plugin can't
    resolve the offset (out of range, feed unreachable). That makes
    ``peek=True`` useful as an "offset exists?" probe — the caller
    sees a 400 IndexError when the offset is past the end of the
    feed and ``ready: false`` otherwise.
    """
    final_text, final_ssml = await _resolve_text(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        source_name=source_name,
    )

    if not final_text and not final_ssml:
        raise HTTPException(
            status_code=400, detail="resolved input was empty",
        )

    plugin = loader.get_tts(engine_name)
    if not plugin:
        available = list(loader.list_tts().keys())
        raise HTTPException(
            status_code=404,
            detail=f"TTS engine '{engine_name}' not found. Available: {available}",
        )

    cache_path = plugin.resolve_cache_path(
        final_text or "",
        ssml=final_ssml,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
    )

    if cache_path.exists():
        # On a cache hit, drop any stale failure record so the next
        # cold call has a fresh attempt counter.
        async with _INFLIGHT_LOCK:
            _FAILED.pop(cache_path, None)
        return {"ready": True, "path": str(cache_path.resolve())}

    # Peek mode: caller wants the cache verdict but does NOT want a
    # synthesis task spawned. Used by trunk for "is offset N+1 a
    # valid story?" probes where firing synthesis would burn quota
    # the listener may never use.
    if peek:
        return {"ready": False}

    # Cold cache. Surface any prior failures and decide whether to
    # retry. Past MAX_QUEUE_ATTEMPTS we stop spawning new tasks; the
    # caller sees ``attempts >= MAX_QUEUE_ATTEMPTS`` and gives up.
    failure = _FAILED.get(cache_path)
    response: dict = {"ready": False}
    if failure:
        response["attempts"] = failure["attempts"]
        response["error"] = failure["error"]
        if failure["attempts"] >= MAX_QUEUE_ATTEMPTS:
            return response

    # Fire-and-forget. The cache file is the source of truth, so a
    # subsequent /queue poll will either see ``ready: true`` once
    # the task has written it, or see incremented attempts/error if
    # synthesis raised.
    asyncio.create_task(
        _kickoff_synthesis(
            plugin,
            text=final_text or "",
            ssml=final_ssml,
            voice=voice,
            language=language,
            rate=rate,
            pitch=pitch,
            cache_path=cache_path,
        )
    )
    return response


_queue_common = dict(
    summary="Check if synthesised audio is cached; warm the cache otherwise",
    responses={
        200: {
            "description": (
                "JSON `{ready, path?, attempts?, error?}`. "
                "`ready: true` with `path` set = file is on disk; "
                "stream it directly or pass `path` to /speak. "
                "`ready: false` (no error) = synthesis is in flight; "
                "poll again. `ready: false` with `attempts` and "
                "`error` set = the last attempt failed; the synth "
                "is being retried unless `attempts` >= the engine's "
                "max-attempt cap, at which point retries stop."
            )
        },
        400: {"description": "Missing required input"},
        404: {"description": "Engine or source plugin not found"},
        502: {"description": "Source fetch failed"},
    },
)


@router.get(
    "/queue",
    description=(
        "Same arguments as `/speak`. Returns `{ready: true}` if the "
        "audio is already cached, otherwise kicks off synthesis in "
        "the background and returns `{ready: false}` immediately. "
        "Poll until ready, then call `/speak` to stream the file."
    ),
    **_queue_common,
)
async def queue_get(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text to synthesise"),
    url: str | None = Query(None, description="Source URL"),
    offset: int = Query(0, description="Article offset (when url is an index)"),
    part: str = Query("body", description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
    peek: bool = Query(
        False,
        description=(
            "Inspector mode. Returns `ready` based on cache state but "
            "does NOT spawn synthesis on a cold cache. The 400 path "
            "for out-of-range offsets stays the same, so this is the "
            "right way to probe whether a feed offset exists without "
            "burning quota."
        ),
    ),
):
    return await _do_queue(
        ssml=ssml,
        text=text,
        url=url,
        offset=offset,
        part=part,
        voice=voice,
        language=language,
        rate=rate,
        pitch=pitch,
        engine_name=engine or "azure",
        source_name=source or "wordpress",
        peek=peek,
    )


@router.post(
    "/queue",
    description=(
        "Same arguments as `/speak` POST; same precedence rules. "
        "Returns `{ready: bool}`."
    ),
    **_queue_common,
)
async def queue_post(
    ssml: str | None = Query(None, description="Raw SSML"),
    text: str | None = Query(None, description="Plain text"),
    url: str | None = Query(None, description="Source URL"),
    offset: int | None = Query(None, description="Article offset"),
    part: str | None = Query(None, description="Which part to speak: 'header' or 'body'"),
    voice: str | None = Query(None, description="Voice name"),
    language: str | None = Query(None, description="Language code"),
    rate: str | None = Query(None, description="Speech rate"),
    pitch: str | None = Query(None, description="Speech pitch"),
    engine: str | None = Query(None, description="TTS engine plugin name"),
    source: str | None = Query(None, description="Source plugin name"),
    peek: bool = Query(
        False,
        description="Inspector mode: report cache state without spawning synthesis.",
    ),
    body: SpeakBody | None = None,
):
    final_ssml = ssml or (body.ssml if body else None)
    final_text = text or (body.text if body else None)
    final_url = url or (body.url if body else None)
    final_offset = offset if offset is not None else (body.offset if body else None)
    final_part = part or (body.part if body else None) or "body"
    final_voice = voice or (body.voice if body else None)
    final_language = language or (body.language if body else None)
    final_rate = rate or (body.rate if body else None)
    final_pitch = pitch or (body.pitch if body else None)
    engine_name = engine or (body.engine if body else None) or "azure"
    source_name = source or (body.source if body else None) or "wordpress"

    return await _do_queue(
        ssml=final_ssml,
        text=final_text,
        url=final_url,
        offset=final_offset or 0,
        part=final_part,
        voice=final_voice,
        language=final_language,
        rate=final_rate,
        pitch=final_pitch,
        engine_name=engine_name,
        source_name=source_name,
        peek=peek,
    )
