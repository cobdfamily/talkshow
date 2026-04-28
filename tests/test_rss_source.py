"""Tests for the RSS / Atom source plugin.

Mocks the HTTP fetch so the suite stays offline. The fixture
defines a small RSS document and a stub article HTML page that
the plugin's URL-fallback path retrieves.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from talkshow.plugins.sources import rss as rss_module
from talkshow.plugins.sources.rss import RSSSource


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


RSS_WITH_FULL_CONTENT = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>First Story</title>
      <author>jane@example.com (Jane Reporter)</author>
      <pubDate>Mon, 27 Apr 2026 09:00:00 +0000</pubDate>
      <link>https://news.example/first</link>
      <description>Short teaser only.</description>
      <content:encoded><![CDATA[
        <p>The full article body lives here.</p>
        <img src="https://x/y.jpg" alt="A diagram of the new bridge" />
        <p>More body text after the image.</p>
      ]]></content:encoded>
    </item>
    <item>
      <title>Second Story</title>
      <author>bob@example.com (Bob Bylined)</author>
      <pubDate>Sun, 26 Apr 2026 16:30:00 +0000</pubDate>
      <link>https://news.example/second</link>
      <description>Another teaser.</description>
    </item>
  </channel>
</rss>
"""


# Description-only feed: forces the URL-fetch fallback path.
ARTICLE_PAGE_HTML = """\
<!doctype html>
<html>
<head><title>Second Story</title></head>
<body>
  <header>nav and stuff we don't want</header>
  <article>
    <h1>Second Story</h1>
    <p>Real article body fetched from the page.</p>
    <img src="https://x/z.jpg" alt="The bylined writer at their desk" />
    <p>More article text.</p>
  </article>
  <footer>copyright</footer>
</body>
</html>
"""


def _make_async_response(text: str):
    """Build a minimal stand-in for an httpx.Response."""
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


@pytest.fixture
def patch_httpx(monkeypatch):
    """Patch httpx.AsyncClient with one whose .get() returns a
    pre-canned response per URL. Returns a dict the test fills in."""
    response_map: dict[str, str] = {}

    class FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, follow_redirects=False):  # noqa: ARG002
            if url not in response_map:
                raise AssertionError(f"unmocked URL: {url}")
            return _make_async_response(response_map[url])

    monkeypatch.setattr(rss_module.httpx, "AsyncClient", FakeAsyncClient)
    return response_map


# ---------------------------------------------------------------------------
# fetch — the path with content:encoded carrying the full body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_full_content_summary(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, summary=True,
    )
    assert article["title"] == "First Story"
    assert article["url"] == "https://news.example/first"
    assert article["offset"] == 0
    # summary string follows the spec
    assert article["summary"].startswith("First Story by")
    assert "Jane Reporter" in article["summary"] or "jane@example.com" in article["summary"]
    assert "April 27, 2026" in article["summary"]
    # When summary=True, text == summary
    assert article["text"] == article["summary"]


@pytest.mark.asyncio
async def test_fetch_full_content_body_uses_content_encoded(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, summary=False,
    )
    body = article["text"]
    assert "The full article body lives here." in body
    assert "More body text after the image." in body
    # Image replaced with alt-text gloss
    assert "Image description: A diagram of the new bridge" in body


# ---------------------------------------------------------------------------
# fetch — the path that falls through to the article URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_falls_through_to_article_url(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    patch_httpx["https://news.example/second"] = ARTICLE_PAGE_HTML
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=1, summary=False,
    )
    body = article["text"]
    # Content came from the article HTML's <article> tag.
    assert "Real article body fetched from the page." in body
    # Image alt-text from the article page is present.
    assert "Image description: The bylined writer at their desk" in body
    # Header / footer stuff was OUTSIDE <article>, so it should not
    # appear.
    assert "nav and stuff" not in body
    assert "copyright" not in body


@pytest.mark.asyncio
async def test_offset_out_of_range_raises_indexerror(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    with pytest.raises(IndexError, match="out of range"):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=99,
        )


@pytest.mark.asyncio
async def test_image_with_no_alt_renders_no_description_marker(patch_httpx):
    patch_httpx["https://feed.example/rss"] = (
        '<?xml version="1.0"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        '<channel><item>'
        '<title>X</title><link>https://x/x</link>'
        '<content:encoded><![CDATA[<p>before</p><img src="https://x/y.jpg"/><p>after</p>]]></content:encoded>'
        '</item></channel></rss>'
    )
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, summary=False,
    )
    assert "Image description: (no description)" in article["text"]


# ---------------------------------------------------------------------------
# Through the /speak endpoint -- end-to-end
# ---------------------------------------------------------------------------


def test_rss_plugin_drives_speak_endpoint(monkeypatch):
    """Smoke: register the real RSS plugin alongside a stub TTS,
    drive /speak with url= and source=rss, assert the TTS engine
    was handed the body text from the feed."""
    from fastapi.testclient import TestClient

    from talkshow.plugins import loader
    from talkshow.plugins.base import TTSPlugin

    captured = {}

    class StubTTS(TTSPlugin):
        name = "stub"
        description = "stub for /speak"

        async def synthesize(
            self, text, *,
            ssml=None, voice=None, language=None, rate=None, pitch=None,
        ):
            captured["text"] = text
            captured["ssml"] = ssml
            yield b"RIFF" + b"\x00" * 100

    # Register a fresh set of plugins.
    loader._tts_plugins.clear()
    loader._source_plugins.clear()
    loader.register_tts(StubTTS())
    loader.register_source(RSSSource())

    # Stub httpx for the RSS fetch.
    class FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, follow_redirects=False):  # noqa: ARG002
            return _make_async_response(RSS_WITH_FULL_CONTENT)

    monkeypatch.setattr(rss_module.httpx, "AsyncClient", FakeAsyncClient)

    from talkshow.main import app
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get(
        "/v1/speak",
        params={
            "url": "https://feed.example/rss",
            "source": "rss",
            "offset": 0,
            "engine": "stub",
        },
    )
    assert r.status_code == 200, r.text
    assert "The full article body lives here." in captured["text"]
    assert "Image description: A diagram of the new bridge" in captured["text"]
