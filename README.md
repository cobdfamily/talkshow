# talkshow

FastAPI TTS microservice. One endpoint — `/speak` — synthesises
audio from raw SSML, plain text, or content fetched via a source
plugin. Caches rendered audio on disk. See `PROJECT.md` for the
architecture and the full argument list.

## Install and run

```
pip install -r requirements.txt
python main.py
```

Auto-generated docs at `/docs` and `/redoc`.

## Plugins

Two extension points under `app/plugins/`:

- `tts/` — synthesis engines (default: `azure`)
- `sources/` — content fetchers (default: `wordpress`)

Each plugin subclasses the ABC in `app/plugins/base.py` and is
auto-discovered at startup by `app/plugins/loader.py`.

## Test

```
pytest tests/
```

## License

AGPL-3.0 — see `LICENSE`.
