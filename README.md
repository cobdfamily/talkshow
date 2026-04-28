# talkshow

[![test](https://github.com/cobdfamily/talkshow/actions/workflows/test.yml/badge.svg)](https://github.com/cobdfamily/talkshow/actions/workflows/test.yml)

FastAPI TTS microservice. One endpoint — `/speak` — synthesises
audio from raw SSML, plain text, or content fetched via a source
plugin. Caches rendered audio on disk. See
[`PROJECT.md`](PROJECT.md) for the architecture and the full
argument list.

> Deploying talkshow in production? See
> **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full checklist (image
> distribution via the kibble registry, configure / run / verify,
> upgrades).

## Install and run

```sh
uv sync
uv run talkshow
```

Auto-generated docs at `/docs` and `/redoc`.

## Plugins

Two extension points under `src/talkshow/plugins/`:

- `tts/` — synthesis engines (default: `azure`)
- `sources/` — content fetchers (default: `wordpress`)

Each plugin subclasses the ABC in `src/talkshow/plugins/base.py`
and is auto-discovered at startup by
`src/talkshow/plugins/loader.py`.

## Test

```sh
uv run pytest -q
uv run pytest --cov   # with branch coverage
```

## License

AGPL-3.0 — see `LICENSE`.
