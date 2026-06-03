# talkshow

[![test](https://github.com/cobdfamily/talkshow/actions/workflows/test.yml/badge.svg)](https://github.com/cobdfamily/talkshow/actions/workflows/test.yml)

FastAPI TTS microservice. Synthesises audio from raw SSML,
plain text, or content fetched via a source plugin. Caches
rendered audio on disk. See [`PROJECT.md`](PROJECT.md) for the
architecture and the full argument list.

| Endpoint                     | What it does                              |
|------------------------------|-------------------------------------------|
| `POST /v1/speak`             | Synthesise audio. Returns the WAV stream  |
|                              | or a JSON `path` if `peek=true`.          |
| `POST /v1/queue`             | Cache-warm: validate an offset / spawn    |
|                              | background synthesis without streaming    |
|                              | the body. Powers trunk's article flow.    |
| `GET  /v1/cache?path=...`    | Serve a cached audio file by its cache    |
|                              | path. Path-traversal-safe.                |
| `GET  /v1/plugins`           | List discovered TTS + source plugins.     |
| `GET  /`                     | Liveness; returns service / status /      |
|                              | version.                                  |

> Deploying talkshow in production? See
> **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full checklist (image
> distribution via the kibble registry, configure / run / verify,
> upgrades).

## Install and run

```sh
uv sync
uv run talkshow
```

Auto-generated docs at `/docs` and `/redocs`.

## Plugins

Two extension points under `src/talkshow/plugins/`:

- `tts/` — synthesis engines:
  - `azure` (**default**) — Microsoft Azure neural voices;
    needs `MSTTS_SUBSCRIPTION_KEY`.
  - `espeak` — offline, no-credentials fallback via the
    `espeak-ng` CLI (v1.1.0). Pick it with `?engine=espeak`;
    for air-gapped dev / CI or when no Azure key is set.
- `sources/` — content fetchers (default: `wordpress`; also `rss`)

Each plugin subclasses the ABC in `src/talkshow/plugins/base.py`
and is auto-discovered at startup by
`src/talkshow/plugins/loader.py`.

Every response carries `X-Request-Id` (echoed from the caller —
trunk forwards it — or freshly minted) plus `X-Service` /
`X-Service-Version`, so one call is greppable across the trunk →
talkshow hop (v1.0.6).

## Test

```sh
uv run pytest -q
uv run pytest --cov   # with branch coverage
```

## License

AGPL-3.0 — see `LICENSE`.
