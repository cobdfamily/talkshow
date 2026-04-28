# Talkshow

FastAPI (Python) TTS microservice. Plugin architecture for TTS engines, data sources, and output formatters. Audio caching. Auto-generated docs at `/docs` and `/redoc`.

## Architecture

- **Three plugin types:** `sources/`, `tts/`, `outputs/` — each extends an ABC in `app/plugins/base.py`, auto-discovered by `app/plugins/loader.py`.
- **Caching lives in plugins**, not core. Path: `cache/<plugin>/<language>/<voice>/<sha512-128>-<rate>-<pitch>.wav`. Serve from cache when file exists.
- **Query-takes-precedence-over-body** on all POST endpoints that accept both.

## Endpoints

| Endpoint | Params | Notes |
|---|---|---|
| `/speak` (GET/POST) | `text`, `voice`, `language`, `rate`, `pitch`, `engine` | POST combines query+body text (space-joined, query first). Default engine: `azure`. |
| `/source` (GET/POST) | `name`, `url`, `offset`, `summary` | Fetches one article from a source plugin. |
| `/output/{format_name}` (GET/POST) | `source_name`, `source_url`, `voice`, `language`, `offset`, `summary` | Fetches one article via the source plugin and renders it via the output plugin. |

## Source plugin contract

Every source plugin implements one method:

```python
async def fetch(self, url: str, *, offset: int = 0, summary: bool = False) -> dict
```

- `url` — the URL to fetch from. May be a single article or an index page that lists multiple. The plugin decides.
- `offset` — when `url` is an index, the 0-based position of the article to return.
- `summary` — `True` returns the article's summary; `False` returns the full body. The summary lives in the article's `summary` field; the renderable text lives in `text` (which is the summary when `summary=True`, the body when `False`).

Returned dict shape:

```python
{"title": str, "text": str, "url": str, "summary": str, "offset": int}
```

## Environment

All env vars prefixed `MSTTS_`: `SUBSCRIPTION_KEY`, `REGION`, `DEFAULT_VOICE`, `DEFAULT_LANGUAGE`. Stored in `.env`.
