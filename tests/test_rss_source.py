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
        <p>The reporters were on the scene shortly after sunrise. The
        bridge had been under construction for the better part of a
        year, and its opening was meant to coincide with the start of
        the new fiscal quarter. Residents had mixed feelings: some
        welcomed the convenience, others worried about traffic noise.
        Council members declined to comment on the cost overruns,
        which by some estimates exceeded the original budget by
        nearly forty percent. The mayor, reached by phone, said the
        project was a victory for transit-oriented development.</p>
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
async def test_fetch_full_content_header(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, part="header",
    )
    assert article["title"] == "First Story"
    assert article["url"] == "https://news.example/first"
    assert article["offset"] == 0
    # Header line follows the strict format:
    # "<title>. By: <author>. Published on: <date>"
    assert article["header"].startswith("First Story. By: ")
    assert "Jane Reporter" in article["header"] or "jane@example.com" in article["header"]
    assert "Published on: April 27, 2026" in article["header"]
    # When part="header", text == header.
    assert article["text"] == article["header"]


@pytest.mark.asyncio
async def test_fetch_full_content_body_uses_content_encoded(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, part="body",
    )
    body = article["text"]
    assert "The full article body lives here." in body
    assert "More body text after the image." in body
    # Image replaced with alt-text gloss
    assert "Image description: A diagram of the new bridge" in body
    # Body must NOT include the header prefix.
    assert "By: " not in body
    assert "Published on:" not in body


# ---------------------------------------------------------------------------
# fetch — the path that falls through to the article URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_falls_through_to_article_url(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    patch_httpx["https://news.example/second"] = ARTICLE_PAGE_HTML
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=1, part="body",
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
async def test_short_content_encoded_falls_through_to_article_url(patch_httpx):
    """Some publishers (Glacier Media seen in the wild) put only the
    lead-image caption — a couple hundred characters — into
    content:encoded. The plugin must NOT trust that as the article
    body; it must fall through to the article-page fetch."""
    feed_xml = (
        '<?xml version="1.0"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        '<channel><item>'
        '<title>Caption-only feed item</title>'
        '<link>https://news.example/caption-only</link>'
        '<description>Short teaser.</description>'
        '<content:encoded><![CDATA['
        '<p>FILE - A photo caption from the wire service. AP Photo, File.</p>'
        ']]></content:encoded>'
        '</item></channel></rss>'
    )
    article_html = (
        '<!doctype html><html><body>'
        '<article>'
        '<p>Paragraph one of the real article body fetched from the page.</p>'
        '<p>Paragraph two with much more substance than the photo caption.</p>'
        '</article>'
        '</body></html>'
    )
    patch_httpx["https://feed.example/rss"] = feed_xml
    patch_httpx["https://news.example/caption-only"] = article_html

    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=0, part="body",
    )
    body = article["text"]
    assert "real article body fetched from the page" in body
    assert "much more substance" in body
    # The photo caption MUST NOT be the returned body.
    assert "FILE" not in body
    assert "AP Photo" not in body


@pytest.mark.asyncio
async def test_cloudflare_challenge_falls_back_to_description(patch_httpx):
    """When the article page returns Cloudflare's 'Just a moment...'
    interstitial, the plugin must NOT treat it as the article body."""
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    patch_httpx["https://news.example/second"] = (
        '<!doctype html><html><head><title>Just a moment...</title></head>'
        '<body><script src="https://challenges.cloudflare.com/cdn-cgi/'
        'challenge-platform/h/g/orchestrate/chl_page/v1?ray=abc"></script>'
        '</body></html>'
    )
    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=1, part="body",
    )
    body = article["text"]
    # We expect the feed item's description, not the Cloudflare page.
    assert "Another teaser." in body
    assert "Just a moment" not in body
    assert "challenges.cloudflare.com" not in body


@pytest.mark.asyncio
async def test_offset_out_of_range_raises_indexerror(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    with pytest.raises(IndexError):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=99,
        )


# ---------------------------------------------------------------------------
# Pagination — follow atom:link rel="next" until the offset is found
# ---------------------------------------------------------------------------


def _paginated_page(items: list[tuple[str, str]], next_url: str | None) -> str:
    """Render a small RSS page with optional rel='next' atom link."""
    next_link = (
        f'<atom:link rel="next" href="{next_url}" />' if next_url else ""
    )
    item_xml = "".join(
        f'<item><title>{title}</title><link>{link}</link>'
        f'<description>{title}</description></item>'
        for title, link in items
    )
    return (
        '<?xml version="1.0"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">'
        '<channel><title>P</title>'
        f'{next_link}{item_xml}'
        '</channel></rss>'
    )


@pytest.mark.asyncio
async def test_pagination_follows_rel_next(patch_httpx):
    """offset=3 against a feed with 2 items per page must follow
    rel='next' and return the 4th item overall (index 1 of page 2)."""
    patch_httpx["https://feed.example/rss"] = _paginated_page(
        [("p1-a", "https://x/1a"), ("p1-b", "https://x/1b")],
        next_url="https://feed.example/rss?page=2",
    )
    patch_httpx["https://feed.example/rss?page=2"] = _paginated_page(
        [("p2-a", "https://x/2a"), ("p2-b", "https://x/2b")],
        next_url="https://feed.example/rss?page=3",
    )

    article = await RSSSource().fetch(
        "https://feed.example/rss", offset=3, part="header",
    )
    assert article["title"] == "p2-b"
    assert article["url"] == "https://x/2b"
    # offset is reported back as the input offset (not the within-page index).
    assert article["offset"] == 3


@pytest.mark.asyncio
async def test_pagination_stops_at_chain_end(patch_httpx):
    """When rel='next' runs out and the offset still isn't found,
    raise IndexError rather than looping."""
    patch_httpx["https://feed.example/rss"] = _paginated_page(
        [("only-1", "https://x/1"), ("only-2", "https://x/2")],
        next_url=None,  # no more pages
    )
    with pytest.raises(IndexError, match="no more pages"):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=10,
        )


@pytest.mark.asyncio
async def test_pagination_respects_env_page_limit(patch_httpx, monkeypatch):
    """RSS_PAGE_LIMIT caps how many pages we'll fetch even if more
    are advertised. A bad caller can't drag the plugin into hundreds
    of HTTP fetches."""
    monkeypatch.setenv("RSS_PAGE_LIMIT", "2")
    patch_httpx["https://feed.example/rss"] = _paginated_page(
        [("p1", "https://x/1")], next_url="https://feed.example/rss?page=2",
    )
    patch_httpx["https://feed.example/rss?page=2"] = _paginated_page(
        [("p2", "https://x/2")], next_url="https://feed.example/rss?page=3",
    )
    # offset=2 needs page 3, but the cap is 2 — must raise.
    with pytest.raises(IndexError, match="page limit"):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=2,
        )


@pytest.mark.asyncio
async def test_negative_offset_rejected(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    with pytest.raises(IndexError, match=">= 0"):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=-1,
        )


def test_page_limit_env_parsing(monkeypatch):
    """Default, override, garbage, and negative values."""
    from talkshow.plugins.sources.rss import RSSSource, _DEFAULT_PAGE_LIMIT

    monkeypatch.delenv("RSS_PAGE_LIMIT", raising=False)
    assert RSSSource._page_limit() == _DEFAULT_PAGE_LIMIT

    monkeypatch.setenv("RSS_PAGE_LIMIT", "25")
    assert RSSSource._page_limit() == 25

    monkeypatch.setenv("RSS_PAGE_LIMIT", "garbage")
    assert RSSSource._page_limit() == _DEFAULT_PAGE_LIMIT

    monkeypatch.setenv("RSS_PAGE_LIMIT", "-3")
    assert RSSSource._page_limit() == _DEFAULT_PAGE_LIMIT


# ---------------------------------------------------------------------------
# Article-body extractor configuration
# ---------------------------------------------------------------------------


def test_match_extractor_picks_domain_specific_entry():
    from talkshow.plugins.sources.rss import _match_extractor

    config = {
        "defaults": {"body_selectors": [".default"], "strip": []},
        "domains": [
            {
                "match": ["bowenislandundercurrent.com", "*.glaciermedia.ca"],
                "body_selectors": ['[itemprop="articleBody"]'],
                "strip": [".inline-share"],
            },
            {
                "match": ["custom.example"],
                "body_selectors": [".custom-body"],
            },
        ],
    }

    e = _match_extractor("https://bowenislandundercurrent.com/the-mix/x", config)
    assert e["body_selectors"] == ['[itemprop="articleBody"]']
    assert e["strip"] == [".inline-share"]

    e = _match_extractor("https://north.glaciermedia.ca/news/x", config)
    assert e["body_selectors"] == ['[itemprop="articleBody"]']

    e = _match_extractor("https://custom.example/post", config)
    assert e["body_selectors"] == [".custom-body"]


def test_match_extractor_falls_back_to_defaults():
    from talkshow.plugins.sources.rss import _match_extractor

    config = {
        "defaults": {"body_selectors": [".default"], "strip": []},
        "domains": [{"match": ["other.com"], "body_selectors": [".other"]}],
    }
    e = _match_extractor("https://nomatch.example/x", config)
    assert e["body_selectors"] == [".default"]


def test_match_extractor_is_case_insensitive_on_hostname():
    from talkshow.plugins.sources.rss import _match_extractor

    config = {
        "defaults": {"body_selectors": [".default"], "strip": []},
        "domains": [
            {"match": ["bowenislandundercurrent.com"], "body_selectors": [".x"]},
        ],
    }
    e = _match_extractor("https://BowenIslandUndercurrent.COM/x", config)
    assert e["body_selectors"] == [".x"]


def test_extractor_strip_removes_inline_junk(monkeypatch, tmp_path):
    """Selectors in the matched extractor's `strip` list must be
    cut from the body before text extraction."""
    from talkshow.plugins.sources.rss import _extract_main_content

    config_file = tmp_path / "extractors.yaml"
    config_file.write_text(
        "defaults:\n"
        "  body_selectors: ['article']\n"
        "  strip: ['.share-bar', '.related']\n"
        "domains: []\n"
    )
    monkeypatch.setenv("TALKSHOW_RSS_EXTRACTORS", str(config_file))

    html = (
        "<html><body><article>"
        "<p>Real body text.</p>"
        "<div class='share-bar'>SHARE BUTTONS</div>"
        "<div class='related'>RELATED ARTICLES</div>"
        "<p>More real body.</p>"
        "</article></body></html>"
    )
    out = _extract_main_content(html, "https://nomatch.example/x")
    assert "Real body text." in out
    assert "More real body." in out
    assert "SHARE BUTTONS" not in out
    assert "RELATED ARTICLES" not in out


def test_extractor_env_override_loads_custom_file(monkeypatch, tmp_path):
    """A user-supplied YAML at TALKSHOW_RSS_EXTRACTORS overrides
    the bundled defaults."""
    from talkshow.plugins.sources.rss import _load_extractors

    config_file = tmp_path / "extractors.yaml"
    config_file.write_text(
        "defaults:\n"
        "  body_selectors: ['.user-supplied']\n"
        "  strip: []\n"
        "domains: []\n"
    )
    monkeypatch.setenv("TALKSHOW_RSS_EXTRACTORS", str(config_file))

    cfg = _load_extractors()
    assert cfg["defaults"]["body_selectors"] == [".user-supplied"]


def test_extractor_load_falls_back_when_override_unreadable(monkeypatch):
    """If the env-pointed file doesn't exist or is malformed, the
    loader silently falls back to the bundled config rather than
    crashing the plugin."""
    from talkshow.plugins.sources.rss import _load_extractors

    monkeypatch.setenv("TALKSHOW_RSS_EXTRACTORS", "/no/such/file.yaml")
    cfg = _load_extractors()
    # Bundled defaults should still produce something usable.
    assert "defaults" in cfg
    assert cfg["defaults"].get("body_selectors")


@pytest.mark.asyncio
async def test_invalid_part_raises_valueerror(patch_httpx):
    patch_httpx["https://feed.example/rss"] = RSS_WITH_FULL_CONTENT
    with pytest.raises(ValueError, match="part must be"):
        await RSSSource().fetch(
            "https://feed.example/rss", offset=0, part="something_else",
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
        "https://feed.example/rss", offset=0, part="body",
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

        def resolve_cache_path(
            self, text, *, ssml=None, voice=None, language=None, rate=None, pitch=None,
        ):
            return self.cache_path(
                ssml or text, language or "en-US", voice or "V",
                rate or "0%", pitch or "0%",
            )

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
