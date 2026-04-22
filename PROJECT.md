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
| `/source` (GET/POST) | `name`, `url`, `articleOffset` | Fetches a single article from a source plugin. |
| `/source/list` (GET/POST) | `name`, `url` | Lists available articles (header metadata only). |
| `/output/{format_name}` (GET/POST) | `source_name`, `source_url`, `voice`, `language`, `articleOffset`, `mode` | Fetches articles from a source and renders via an output plugin. |

## Mode parameter

Accepted on `/output/{format_name}` only. Controls what the output plugin fetches and how it renders.

| Mode | Fetch behavior | Render behavior |
|---|---|---|
| `full` (default) | Single article at `articleOffset` via `fetch()` | Full article: title + body (TTS audio if available) |
| `summary` | All articles via `list_articles()` | Header only: title per article, no body |
| `nextArticle` | Single article at `articleOffset + 1` via `fetch()` | Header only: announces next article title |

## Environment

All env vars prefixed `MSTTS_`: `SUBSCRIPTION_KEY`, `REGION`, `DEFAULT_VOICE`, `DEFAULT_LANGUAGE`. Stored in `.env`.
