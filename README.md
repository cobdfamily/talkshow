# talkshow

FastAPI TTS microservice with a plugin architecture for TTS engines,
data sources, and output formatters. Caches rendered audio on disk.
See `PROJECT.md` for the full architecture.

## Install and run

```
pip install -r requirements.txt
python main.py
```

Docs are auto-generated at `/docs` and `/redoc`.

## Plugins

Three extension points under `app/plugins/`:

- `sources/` — article sources
- `tts/` — TTS engines (default: azure)
- `outputs/` — output formatters (e.g., Twilio XML)

Each plugin subclasses the ABC in `app/plugins/base.py` and is
auto-discovered by `app/plugins/loader.py`.

## Test

```
pytest tests/
```

## License

AGPL-3.0 — see `LICENSE`.
