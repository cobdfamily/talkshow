"""WordPress REST API source plugin.

Fetches one article from a WordPress REST API (v2). The plugin
treats every URL as an index by default and uses `offset` to pick
which post to return.

The WP REST API at ``/wp-json/wp/v2/posts`` is the canonical index
endpoint; pass the site root or that path verbatim and the plugin
finds the rest. ``part="header"`` returns the formatted intro line;
``part="body"`` returns the full post body.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx

from ..base import SourcePlugin


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#039;", "'").replace("&nbsp;", " ")
    return text.strip()


def _posts_index(url: str) -> str:
    """Return the WP REST posts index URL given a site root or
    ``/wp-json/...`` path. Idempotent."""
    if "/wp-json/" in url:
        return url.rstrip("/")
    return url.rstrip("/") + "/wp-json/wp/v2/posts"


def _format_wp_date(raw: str) -> str:
    """WP returns ISO 8601 without a zone; render it as
    "April 27, 2026" for the header line."""
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw).strftime("%B %-d, %Y")
    except ValueError:
        return raw


def _build_header(title: str, author: str, published: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(title)
    if author:
        parts.append(f"By: {author}")
    if published:
        parts.append(f"Published on: {published}")
    return ". ".join(parts)


class WordPressSource(SourcePlugin):
    name = "wordpress"
    description = "Fetch articles from a WordPress REST API (v2)"

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

        index_url = _posts_index(url)
        async with httpx.AsyncClient(timeout=30) as client:
            # `per_page` lets us index without paginating through
            # tens of pages for typical sites. WP caps it at 100.
            # `_embed` pulls the author record in one call so we
            # don't need a second round-trip for the byline.
            resp = await client.get(
                index_url, params={"per_page": 100, "_embed": "author"},
            )
            resp.raise_for_status()
            posts = resp.json()

        if offset < 0 or offset >= len(posts):
            raise IndexError(
                f"offset {offset} out of range (0..{len(posts) - 1})"
            )
        post = posts[offset]

        title = _strip_html(post.get("title", {}).get("rendered", ""))
        body = _strip_html(post.get("content", {}).get("rendered", ""))
        published = _format_wp_date(post.get("date") or "")
        embedded = post.get("_embedded", {}) or {}
        authors = embedded.get("author") or []
        author = (authors[0].get("name") if authors else "") or ""

        header = _build_header(title, author, published)
        text = header if part == "header" else body

        return {
            "title": title,
            "text": text,
            "url": post.get("link", ""),
            "header": header,
            "offset": offset,
        }
