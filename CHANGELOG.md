# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: SemVer; pre-1.0 minor bumps may break.

## [Unreleased]

## [1.0.0] - 2026-05-01

This is the first stable release. Below is what changed since
0.6.0; see the per-feature commits for full detail.

### Added

- **`/v1/queue`** — non-blocking cache-warm endpoint. Same
  arguments as `/v1/speak`. Returns
  `{"ready": false}` immediately and triggers synthesis in
  the background; subsequent polls return
  `{"ready": true, "path": "..."}` once the cache file is
  written. After three consecutive synthesis failures the
  endpoint stops auto-retrying and surfaces
  `{"ready": false, "attempts": 3, "error": "..."}` so the
  caller knows to give up. Designed for IVR flows that play
  hold audio while a long article is being prepared.
- **`/v1/cache?path=<abs>`** — streams a previously-cached WAV
  file by absolute path. Validates the path resolves inside
  `TALKSHOW_CACHE_DIR` and ends in `.wav`. Path-traversal,
  symlinks-out-of-cache, and partial `.wav.tmp` writes are
  rejected with 403. Typical flow: poll `/queue` until
  `ready: true`, take its `path`, hand it to `/cache`.
- **RSS pagination.** The `rss` source plugin now follows the
  standard Atom `<link rel="next">` chain when `offset` is
  past the end of the first page. Capped by the new
  `RSS_PAGE_LIMIT` env var (default 10 pages); pass
  `?page=N` in the URL to start deeper.
- **Per-publisher article-body extractors.** Selectors and
  in-body strip lists now live in
  `src/talkshow/plugins/sources/rss_extractors.yaml`. Hostname
  globs (`fnmatch`) pick the matching entry; `defaults`
  applies otherwise. Override path via
  `TALKSHOW_RSS_EXTRACTORS=/path/to/your.yaml`.
- **Source-plugin contract: `part="header"|"body"`.**
  `summary: bool` is gone. `part="header"` returns
  `"<title>. By: <author>. Published on: <date>"`;
  `part="body"` returns the article body only. The header
  string is also returned in the dict on every fetch so a
  caller can prepend it to the body if they want a
  title-card flow.
- **TTS plugin contract: `resolve_cache_path`.** New abstract
  method on `TTSPlugin` that returns the cache file path for
  a given request without invoking synthesis. `/queue` uses
  it to test "is this already on disk?" without spending
  Azure quota.

### Changed

- **Atomic cache writes.** `AzureTTS.synthesize` now writes
  audio to a `.wav.tmp` sibling and renames into place once
  the bytes are flushed. Readers (including a separate trunk
  process reading the cache volume) never see a half-written
  file.
- **SSML XML escaping.** Article text is now run through
  `xml.sax.saxutils.escape` before being placed in the SSML
  envelope. Fixes the "EntityName" parse errors that bare
  ampersands in titles caused.
- **Body selector reorder.** `[itemprop="articleBody"]`
  (schema.org) tried first; `<article>` / `<main>` moved to
  last-resort. Fixes Glacier Media articles getting nav and
  footer text scraped along with the body.
- **Header format separator** changed from ` - ` to `. `
  (period + space). Reads better through TTS — Azure pauses
  on the period.

### New env vars

- `RSS_PAGE_LIMIT` (default `10`) — pagination cap.
- `TALKSHOW_RSS_EXTRACTORS` — override path to extractor
  config.

### Migration from 0.6.0

Most changes are additive. Two breaking points:

1. Source-plugin `fetch` signature is now
   `fetch(url, *, offset=0, part="body")`. Callers using
   `summary=True` should now pass `part="header"`. The
   header format also changed:
     before: `"Title by Author on Date"`
     after:  `"Title. By: Author. Published on: Date"`
2. Custom TTS plugins must implement `resolve_cache_path` —
   the abstract method has no default. The bundled
   `AzureTTS` is updated; out-of-tree plugins need a small
   addition (forward to `self.cache_path(...)` with the
   plugin's own defaults).

## [0.6.0] - 2026-04-28

### Changed (breaking)
- The whole HTTP API moves under a `/v1/*` prefix.
  Concretely:
    - `/speak`         -> `/v1/speak`
    - `/plugins`       -> `/v1/plugins`
    - `/plugins/{type}` -> `/v1/plugins/{type}`
  The unversioned `/` health endpoint stays put so
  orchestration probes don't have to know the API
  version. Bumping to `/v2` later is the sanctioned
  way to make breaking changes; clients pin the
  version they speak.

### Migration

Every caller needs to update the path. There's no
back-compat shim; `/speak` now 404s. The query and
body shape is unchanged.

  before: GET /speak?text=hi
  after:  GET /v1/speak?text=hi

  before: GET /plugins
  after:  GET /v1/plugins

## [0.5.0] - 2026-04-27

### Added
- `rss` source plugin (`src/talkshow/plugins/sources/rss.py`)
  for any RSS or Atom feed. Inspired by `Other/undercurrent`
  but reduced to the single `fetch(url, offset, summary)`
  contract.
  - `summary=True` returns
    `"[title] by [author] on [date]"` as the renderable text.
  - `summary=False` returns the full body, with `<img>` tags
    rewritten as `"Image description: [alt text]"`. Empty alt
    becomes `"(no description)"` so a TTS user always hears
    that an image WAS there.
  - Body resolution: `content:encoded` first, then a long
    `description`/`summary`, then a fallback fetch of the
    article URL with main-content extraction
    (`<article>` / `<main>` / `entry-content` /
    `post-content` / `article-body` / `story-body`).
  - Robust date formatting across RFC 822 and ISO 8601
    shapes; falls back to the raw string on a miss.
  - `User-Agent` header set to a real browser string so
    feeds that block default `python-httpx` UAs still
    respond.
- Two new dependencies: `feedparser>=6.0` (RSS / Atom
  variants) and `beautifulsoup4>=4.12` (HTML parsing +
  alt-text rewriting). Both standard for this kind of
  scraping.

### Tests
- `tests/test_rss_source.py` — six cases covering the
  full-content path, summary string assembly, the URL
  fallback path, image alt-text replacement (with and
  without alt), out-of-range offset, and an end-to-end
  flow through `/speak?source=rss&url=...`.

## [0.4.1] - 2026-04-27

### Changed (breaking)
- `/speak` source-plugin selector renamed back from
  `plugin` to `source`. The 0.4.0 rename was a mistake.
  Switch `/speak?plugin=wordpress` calls to
  `/speak?source=wordpress`. Default value unchanged.

## [0.4.0] - 2026-04-27

### Note
- This release temporarily renamed the source-plugin
  selector to `plugin`. 0.4.1 reverts that to `source`.
  Skip 0.4.0 for the layout work below; the rename was
  not the right call.

### Changed — Layout
- Project converted to a `src/talkshow/` layout managed by uv.
  `app/` and the top-level `main.py` are gone; everything now
  lives at `src/talkshow/{main,config,routes,plugins}.py`.
- `requirements.txt` removed in favour of `pyproject.toml` +
  `uv.lock`. Dev deps live in `[dependency-groups] dev`. Running
  the suite is `uv run pytest`; running the app locally is
  `uv run talkshow`.
- Two-stage `Dockerfile` (uv build → `python:3.12-slim`
  runtime) replaces the old single-stage pip image. Non-root
  user, uvicorn as PID 1, cache dir owned by uid 1000.

### Added — Tooling
- `[tool.coverage.*]` config in `pyproject.toml` — branch
  coverage with a 70% `fail_under` floor.
- `[tool.ruff]` config; CI's `lint` job gates `pytest`.
- `pytest-cov` in dev deps; CI uploads `coverage.xml` as an
  artifact.
- `CHANGELOG.md` (this file) — Keep-a-Changelog format.
- `DEPLOYMENT.md` — production deploy checklist.
- README test-workflow status badge.

## [0.3.0] - 2026-04-27

### Changed (breaking)
- Collapsed to a single `/speak` endpoint. Removed
  `/source`, `/source/list`, `/output/{format}`, the
  `OutputPlugin` ABC, and the `twilio_xml` plugin.
- `/speak` accepts content as `ssml` (verbatim), `text`
  (plain), or `url` (fetched via the configured source
  plugin). Precedence: `ssml > text > url`. Always
  returns `audio/wav`.
- `TTSPlugin.synthesize` gained an `ssml` keyword. When
  set the SSML is sent verbatim and prosody args are
  ignored.

## [0.2.0] - 2026-04-27

### Changed (breaking)
- `SourcePlugin` collapsed to a single
  `fetch(url, *, offset=0, summary=False) -> dict`.
  Removed `list_articles`. The plugin decides whether
  the URL is an index or a single article.
- `OutputPlugin.render` now takes a single article dict
  (was a list); `mode` kwarg removed.
- `/source` endpoint replaces `articleOffset` with
  `offset` and gains `summary`. `/source/list` removed.
- `/output/{format}` drops the `mode` parameter and
  gains `summary`.

## [0.1.1] - 2026-04-27

### Added
- First containerised release. `Dockerfile`,
  `.dockerignore`, `.github/workflows/test.yml`,
  `.github/workflows/release.yml` (publishes to
  `kibble.apps.blindhub.ca/cobdfamily/talkshow:<version>`
  on every `git tag v*`).

### Fixed
- Stale test fixture: `FakeOutput.render` was missing
  the `mode=` keyword the OutputPlugin base added in a
  later commit, causing four `/output/*` tests to 500.

## [0.1.0] - earlier

Initial FastAPI TTS microservice with three-plugin
architecture (TTS engines, sources, output formatters),
file-based audio caching, Microsoft Azure TTS, WordPress
source, and Twilio TwiML / SignalWire LAML output.

[Unreleased]: https://github.com/cobdfamily/talkshow/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/cobdfamily/talkshow/compare/v0.6.0...v1.0.0
[0.6.0]: https://github.com/cobdfamily/talkshow/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/cobdfamily/talkshow/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/cobdfamily/talkshow/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/cobdfamily/talkshow/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/cobdfamily/talkshow/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/cobdfamily/talkshow/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/cobdfamily/talkshow/releases/tag/v0.1.1
[0.1.0]: https://github.com/cobdfamily/talkshow/commits/v0.1.0
