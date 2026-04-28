# Talkshow

FastAPI (Python) TTS microservice. One endpoint, two plugin types, file-based audio caching.

## Architecture

- **One endpoint:** `/speak`. Returns audio/wav.
- **Two plugin types:** `tts/` (synthesis engines) and `sources/` (content fetchers). Each extends an ABC in `app/plugins/base.py` and is auto-discovered by `app/plugins/loader.py`.
- **Caching lives in plugins,** not core. Path: `cache/<plugin>/<language>/<voice>/<sha512-128>-<rate>-<pitch>.wav`. Serve from cache when the file exists.

## /speak

Three mutually substitutable input forms; precedence is `ssml > text > url`:

| Arg | Purpose |
|---|---|
| `ssml` | Raw SSML, sent verbatim to the TTS engine. Carries its own voice/rate/pitch. |
| `text` | Plain text, wrapped in an SSML envelope by the engine. |
| `url`  | Source URL fetched via the configured source plugin. |
| `offset` | When `url` is an index, the 0-based article offset. |
| `summary` | `true` returns a summary; `false` returns the full body. |
| `voice` | Voice name (engine-specific). |
| `language` | Language code (e.g. `en-US`). |
| `rate` | Speech rate (e.g. `+10%`). |
| `pitch` | Speech pitch (e.g. `-5%`). |
| `engine` | TTS plugin name. Default `azure`. |
| `plugin` | Source plugin name. Default `wordpress`. |

POST takes the same args via JSON body OR query string; query wins on conflict.

## Source plugin contract

```python
class SourcePlugin(ABC):
    name: str
    description: str

    async def fetch(
        self, url: str, *, offset: int = 0, summary: bool = False,
    ) -> dict:
        ...
```

Returned dict carries `title`, `text`, `url`, `summary`, `offset`. `text` is the renderable string — when `summary=True`, it's the excerpt; when `False`, it's the full body.

## TTS plugin contract

```python
class TTSPlugin(ABC):
    name: str
    description: str

    async def synthesize(
        self, text: str, *,
        ssml: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        rate: str | None = None,
        pitch: str | None = None,
    ) -> AsyncIterator[bytes]:
        ...
```

When `ssml` is supplied it's sent verbatim; the prosody args are ignored (the SSML carries them itself).

## Environment

Env vars prefixed `MSTTS_`: `SUBSCRIPTION_KEY`, `REGION`, `DEFAULT_VOICE`, `DEFAULT_LANGUAGE`. Loaded from `.env` at startup.
