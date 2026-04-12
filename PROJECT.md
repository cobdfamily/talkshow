# Project Details

A TTS microservice built with **FastAPI** (Python). It features a plugin architecture for
TTS engines, data sources, and output formatters, with built-in audio caching and
auto-generated API documentation (Swagger UI at `/docs`, ReDoc at `/redoc`).

## Requirements

1. **Plugin system** — Folder-based plugin architecture for three plugin types: **sources**,
   **TTS engines**, and **outputs**. External plugins can implement the project's abstract
   interfaces and be dropped into the plugin directories.

2. **Microsoft TTS plugin** — Uses the Azure Cognitive Services Speech SDK
   (`azure-cognitiveservices-speech-sdk`) with configurable voice, language, and text.

3. **Text input** — Text can be passed via the `text` query parameter and/or `text` body
   parameter (JSON). If both are provided, they are combined with a space, query first.

4. **Datasource config** — The following query/body params configure a datasource plugin:
   `name`, `url`, `articleOffset`.

5. **`.gitignore`** — Configured for Python and macOS (`.DS_Store`, `__pycache__`, `.env`, etc.).

6. **Environment variables** — MS TTS subscription keys and defaults are stored in `.env`,
   all prefixed with `MSTTS_` (e.g. `MSTTS_SUBSCRIPTION_KEY`, `MSTTS_REGION`,
   `MSTTS_DEFAULT_VOICE`, `MSTTS_DEFAULT_LANGUAGE`).

7. **Speech streaming and caching:**
   - 7.1. Generated speech is cached to disk. Folder structure: `cache/<plugin>/<language>/<voice>/`.
   - 7.2. Filename: 128-char SHA-256 hash of text + `-<rate>-<pitch>.wav`.
   - 7.3. If a cached file exists, it is streamed directly instead of regenerating.
   - 7.4. All caching and streaming logic lives inside the plugins, not core, so plugins are
     reusable across projects.

8. **Source plugins** — Fetch data from URLs (e.g. articles from a WordPress tag or Hugo tag).

9. **Output plugins** — Format non-audio output, such as Twilio XML or Signalwire LAML for
   phone system article navigation.

10. **API documentation** — Automatic via FastAPI's built-in OpenAPI support.
