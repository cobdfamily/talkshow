"""RSS / Atom source plugin.

Fetches one item from any RSS or Atom feed. The URL passed in is
the feed URL itself; ``offset`` selects which item from the feed.

When ``offset`` is past the end of the first page, the plugin
walks the standard Atom ``<link rel="next">`` chain to deeper
pages until it finds the requested item. Capped at
``RSS_PAGE_LIMIT`` pages (default 10) to keep a bad caller from
dragging the plugin into hundreds of HTTP fetches; pass the URL
with ``?page=N`` already set if you need to start deeper.

Returns the standard SourcePlugin shape:

  title, text, url, header, offset

  header  "<title>. By: <author>. Published on: <date>"
  text    the header line when ``part="header"``,
          the article body (with ``<img>`` tags swapped for
          "Image description: <alt>") when ``part="body"``.

Body resolution order when ``part="body"``:

  1. ``content:encoded`` on the feed item (most modern WordPress
     feeds carry the full body here).
  2. The ``description`` / ``summary`` element when long enough
     to plausibly be the full article.
  3. Fetch the article URL and extract the main content. Some
     publishers (Glacier Media, etc.) gate articles behind
     Cloudflare; the fetch is best-effort and falls through to
     whatever short body the feed item already had if it fails.

Per-publisher article-body extractor rules live in
``rss_extractors.yaml`` next to this module. Defaults cover most
modern news CMSes via schema.org's ``itemprop="articleBody"`` and
WordPress class patterns; per-domain entries override on hostname
matches. Override the path with ``TALKSHOW_RSS_EXTRACTORS``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup

from ..base import SourcePlugin


_DEFAULT_PAGE_LIMIT = 10

# Path to the bundled extractor config. Co-located with the plugin
# so it's discoverable and ships with the wheel. Override at runtime
# via the ``TALKSHOW_RSS_EXTRACTORS`` env var.
_BUNDLED_EXTRACTORS_PATH = Path(__file__).parent / "rss_extractors.yaml"

# Used when both the env file and the bundled file fail to load.
# Keeps the plugin functional even with a misconfigured deployment.
_HARDCODED_FALLBACK_DEFAULTS = {
    "defaults": {
        "body_selectors": [
            '[itemprop="articleBody"]',
            '[class*="entry-content"]',
            '[class*="post-content"]',
            '[class*="article-body"]',
            '[class*="story-body"]',
            "article",
            "main",
        ],
        "strip": [],
    },
    "domains": [],
}


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1",
}

def _load_extractors() -> dict[str, Any]:
    """Read the active extractor config.

    Lookup order:
      1. ``TALKSHOW_RSS_EXTRACTORS`` env var, if set and readable.
      2. ``rss_extractors.yaml`` shipped alongside this module.
      3. ``_HARDCODED_FALLBACK_DEFAULTS`` so the plugin still works
         if both files are missing or malformed.

    Read on every fetch so an operator can edit the file and have
    changes pick up without restarting talkshow. PyYAML safe_load
    + a small amount of disk I/O is cheap relative to the HTTP
    fetch + TTS synthesis that follows.
    """
    candidates: list[Path] = []
    override = os.getenv("TALKSHOW_RSS_EXTRACTORS")
    if override:
        candidates.append(Path(override))
    candidates.append(_BUNDLED_EXTRACTORS_PATH)

    for path in candidates:
        try:
            with path.open("rb") as fh:
                loaded = yaml.safe_load(fh)
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(loaded, dict):
            return loaded
    return _HARDCODED_FALLBACK_DEFAULTS


def _match_extractor(url: str, config: dict[str, Any]) -> dict[str, Any]:
    """Pick the most specific extractor entry for ``url``.

    Hostname-only matching via ``fnmatch``; first match wins so
    ordering in the YAML file is significant. Falls back to
    ``config["defaults"]`` (always present) when nothing matches.
    """
    host = (urlparse(url).hostname or "").lower()
    for entry in config.get("domains", []) or []:
        for pattern in entry.get("match", []) or []:
            if fnmatch(host, pattern.lower()):
                return entry
    return config.get("defaults") or _HARDCODED_FALLBACK_DEFAULTS["defaults"]


def _format_date(raw: str) -> str:
    """Best-effort date formatting. Tries the common feed shapes
    (RFC 822, ISO 8601 with and without zone) and falls back to the
    raw string when nothing parses."""
    if not raw:
        return ""
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).strftime("%B %-d, %Y")
        except ValueError:
            continue
    return raw


def _replace_images(soup: BeautifulSoup) -> None:
    """In place: swap every ``<img>`` for ``"Image description: <alt>"``.

    Empty alt text becomes ``"(no description)"`` rather than dropping
    the image silently — TTS users want to know an image WAS there.
    """
    for img in soup.find_all("img"):
        alt = (img.get("alt") or "").strip() or "(no description)"
        img.replace_with(f"Image description: {alt}")


def _html_to_text(html: str) -> str:
    """Render an HTML fragment to plain text after image rewriting.
    Drops scripts and styles; collapses whitespace runs."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    _replace_images(soup)
    text = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _extract_main_content(html: str, url: str) -> str:
    """Pick the article body out of the page HTML using the
    extractor config. The selected node is then run through the
    extractor's ``strip`` list to remove in-body junk before
    being returned as a string."""
    soup = BeautifulSoup(html or "", "html.parser")
    extractor = _match_extractor(url, _load_extractors())

    selectors = extractor.get("body_selectors") or []
    matched = None
    for selector in selectors:
        matched = soup.select_one(selector)
        if matched:
            break
    if matched is None:
        matched = soup.body or soup

    for strip_selector in extractor.get("strip") or []:
        for victim in matched.select(strip_selector):
            victim.decompose()

    return str(matched)


def _looks_like_cf_challenge(html: str) -> bool:
    """Cloudflare's interstitial returns a small HTML page titled
    'Just a moment...' with a script-tag challenge. Detect it so we
    don't try to parse it as the article."""
    if not html:
        return False
    return (
        "Just a moment..." in html
        and "challenges.cloudflare.com" in html
    )


class RSSSource(SourcePlugin):
    name = "rss"
    description = "Fetch articles from any RSS or Atom feed"

    async def fetch(
        self,
        url: str,
        *,
        offset: int = 0,
        part: str = "body",
    ) -> dict:
        if part not in ("header", "body"):
            raise ValueError(
                f"part must be 'header' or 'body', got {part!r}"
            )
        if offset < 0:
            raise IndexError(f"offset must be >= 0, got {offset}")

        page_limit = self._page_limit()
        entry = await self._locate_entry(url, offset, page_limit)

        title = (entry.get("title") or "").strip()
        author = (
            entry.get("author")
            or entry.get("dc_creator")
            or ""
        ).strip()
        published = _format_date(
            entry.get("published") or entry.get("updated") or ""
        )
        link = entry.get("link") or ""

        header = self._build_header(title, author, published)

        if part == "header":
            text = header
        else:
            text = await self._resolve_body(entry, link)

        return {
            "title": title,
            "text": text,
            "url": link,
            "header": header,
            "offset": offset,
        }

    @staticmethod
    def _page_limit() -> int:
        """Per-fetch read of ``RSS_PAGE_LIMIT`` so tests can flip
        it via monkeypatch.setenv without restarting the plugin.
        Falls back to ``_DEFAULT_PAGE_LIMIT`` on missing or
        non-integer values."""
        raw = os.getenv("RSS_PAGE_LIMIT")
        if not raw:
            return _DEFAULT_PAGE_LIMIT
        try:
            value = int(raw)
        except ValueError:
            return _DEFAULT_PAGE_LIMIT
        return value if value > 0 else _DEFAULT_PAGE_LIMIT

    async def _locate_entry(
        self, url: str, offset: int, page_limit: int,
    ) -> dict:
        """Walk the ``rel="next"`` chain until the requested
        offset is found or the page limit / chain end is reached.

        Caching note: the synthesised audio is keyed on the
        article body, so two callers that reach the same article
        through different starting URLs (eg. ``?page=2`` + offset 0
        vs root URL + offset 20) still hit the same WAV file.
        """
        remaining = offset
        current_url = url
        pages_fetched = 0

        while True:
            feed_xml = await self._fetch_text(current_url)
            pages_fetched += 1
            feed = feedparser.parse(feed_xml)
            entries = feed.entries

            if not entries:
                if pages_fetched == 1:
                    raise IndexError("feed has no items")
                # A "next" link led to an empty page — treat as end.
                raise IndexError(
                    f"offset {offset} out of range; pagination ended at "
                    f"page {pages_fetched}"
                )

            if remaining < len(entries):
                return entries[remaining]

            remaining -= len(entries)

            if pages_fetched >= page_limit:
                raise IndexError(
                    f"offset {offset} out of range within page limit "
                    f"({page_limit}); pass ?page=N in the URL to start "
                    f"deeper, or raise RSS_PAGE_LIMIT"
                )

            next_link = self._find_next_link(feed)
            if not next_link:
                raise IndexError(
                    f"offset {offset} out of range; feed has no more "
                    f"pages after page {pages_fetched}"
                )
            current_url = next_link

    @staticmethod
    def _find_next_link(feed) -> str | None:
        """Return the channel-level ``<atom:link rel="next">`` href
        if the feed exposes one, else None.

        feedparser stores Atom links on ``feed.feed.links`` (the
        channel-level metadata, not the per-entry list). RSS 2.0
        feeds with embedded Atom pagination namespace work too —
        feedparser normalises them onto the same attribute."""
        feed_meta = getattr(feed, "feed", None) or {}
        for link in feed_meta.get("links", []) or []:
            if link.get("rel") == "next":
                href = link.get("href")
                if href:
                    return href
        return None

    @staticmethod
    def _build_header(title: str, author: str, published: str) -> str:
        """Compose `"<title>. By: <author>. Published on: <date>"`,
        skipping any segment that's empty so a feed without an author
        doesn't leave a dangling `By: .`. The period-and-space joiner
        gives TTS engines a natural sentence break."""
        parts: list[str] = []
        if title:
            parts.append(title)
        if author:
            parts.append(f"By: {author}")
        if published:
            parts.append(f"Published on: {published}")
        return ". ".join(parts)

    async def _resolve_body(self, entry, link: str) -> str:
        """Find the best body source and render to plain text."""
        contents = entry.get("content") or []
        content_html = ""
        if contents and isinstance(contents, list):
            content_html = contents[0].get("value") or ""

        desc = entry.get("description") or entry.get("summary") or ""

        # 1. content:encoded if it's plausibly the full article body.
        #    Glacier Media (and other publishers we've hit) sometimes
        #    drop only the lead-image caption into content:encoded —
        #    a couple hundred characters of figure markup and an
        #    AP photo credit. The length gate catches that and forces
        #    a fall-through to the article-page fetch, which returns
        #    the real body.
        if len(content_html) > 500:
            return _html_to_text(content_html)

        # 2. description / summary if long enough to be the full body.
        if len(desc) > 500:
            return _html_to_text(desc)

        # 3. Fetch the article URL.
        if link:
            try:
                html = await self._fetch_text(link)
                if not _looks_like_cf_challenge(html):
                    return _html_to_text(_extract_main_content(html, link))
            except Exception:
                # Network died — fall through to whichever short
                # feed body we have.
                pass

        # 4. Last resort: whichever short body is longer.
        fallback = content_html if len(content_html) > len(desc) else desc
        return _html_to_text(fallback)

    @staticmethod
    async def _fetch_text(url: str) -> str:
        async with httpx.AsyncClient(
            timeout=30,
            headers=_BROWSER_HEADERS,
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
