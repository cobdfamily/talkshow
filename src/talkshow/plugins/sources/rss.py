"""RSS / Atom source plugin.

Inspired by ``Other/undercurrent`` but trimmed to a single
:meth:`fetch`. The URL passed in is the feed URL itself; ``offset``
selects which item from the feed.

Returns the standard SourcePlugin shape:

  title, text, url, summary, offset

  summary  "[title] by [author] on [date]"
  text     summary form when ``summary=True``;
           full body (with ``<img>`` tags swapped for
           "Image description: [alt text]") when ``False``.

Body resolution order:

  1. ``content:encoded`` on the feed item (most modern WordPress
     feeds carry the full body here).
  2. The ``description`` / ``summary`` element when long enough
     to plausibly be the full article.
  3. Fetch the article URL itself and extract the main content.

If all three fail, the plugin returns whatever short body was on
the feed item rather than empty text.
"""

from __future__ import annotations

import re
from datetime import datetime

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..base import SourcePlugin


_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Heuristic body selectors, tried in order. WordPress and
# WordPress-shaped CMSes cover most of what cobd cares about; the
# generic <article> / <main> tags catch the rest. If nothing
# matches we fall back to the whole <body>.
_BODY_SELECTORS = (
    "article",
    "main",
    '[class*="entry-content"]',
    '[class*="post-content"]',
    '[class*="article-body"]',
    '[class*="story-body"]',
)


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


def _extract_main_content(html: str) -> str:
    """Return the HTML of whichever main-content selector matches first."""
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in _BODY_SELECTORS:
        node = soup.select_one(selector)
        if node:
            return str(node)
    return str(soup.body or soup)


class RSSSource(SourcePlugin):
    name = "rss"
    description = "Fetch articles from any RSS or Atom feed"

    async def fetch(
        self,
        url: str,
        *,
        offset: int = 0,
        summary: bool = False,
    ) -> dict:
        feed_xml = await self._fetch_text(url)
        feed = feedparser.parse(feed_xml)
        entries = feed.entries
        if not entries:
            raise IndexError("feed has no items")
        if offset < 0 or offset >= len(entries):
            raise IndexError(
                f"offset {offset} out of range (0..{len(entries) - 1})"
            )
        entry = entries[offset]

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

        summary_str = self._build_summary(title, author, published)

        if summary:
            body_text = summary_str
        else:
            body_text = await self._resolve_body(entry, link)

        return {
            "title": title,
            "text": body_text,
            "url": link,
            "summary": summary_str,
            "offset": offset,
        }

    @staticmethod
    def _build_summary(title: str, author: str, published: str) -> str:
        parts = [title] if title else []
        if author:
            parts.append(f"by {author}")
        if published:
            parts.append(f"on {published}")
        return " ".join(parts)

    async def _resolve_body(self, entry, link: str) -> str:
        """Find the best body source and render to plain text."""
        # 1. content:encoded — the full article when the feed is generous.
        contents = entry.get("content") or []
        if contents and isinstance(contents, list):
            first_html = contents[0].get("value") or ""
            if first_html:
                return _html_to_text(first_html)

        # 2. description / summary — sometimes also a full body.
        desc = entry.get("description") or entry.get("summary") or ""
        if desc and len(desc) > 500:
            return _html_to_text(desc)

        # 3. Fetch the article URL.
        if link:
            try:
                html = await self._fetch_text(link)
                return _html_to_text(_extract_main_content(html))
            except Exception:
                # Network died — return whatever short body we had
                # rather than emit nothing.
                pass

        return _html_to_text(desc)

    @staticmethod
    async def _fetch_text(url: str) -> str:
        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            return resp.text
