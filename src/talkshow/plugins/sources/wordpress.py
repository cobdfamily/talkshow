"""WordPress REST API source plugin.

Fetches one article from a WordPress REST API (v2). The plugin
treats every URL as an index by default and uses `offset` to pick
which post to return.

The WP REST API at ``/wp-json/wp/v2/posts`` is the canonical index
endpoint; pass the site root or that path verbatim and the plugin
finds the rest. Pass ``summary=True`` to return the WP-rendered
excerpt; ``summary=False`` returns the full post body.
"""

from __future__ import annotations

import re

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


class WordPressSource(SourcePlugin):
    name = "wordpress"
    description = "Fetch articles from a WordPress REST API (v2)"

    async def fetch(
        self,
        url: str,
        *,
        offset: int = 0,
        summary: bool = False,
    ) -> dict:
        index_url = _posts_index(url)
        async with httpx.AsyncClient(timeout=30) as client:
            # `per_page` lets us index without paginating through
            # tens of pages for typical sites. WP caps it at 100.
            resp = await client.get(index_url, params={"per_page": 100})
            resp.raise_for_status()
            posts = resp.json()

        if offset < 0 or offset >= len(posts):
            raise IndexError(
                f"offset {offset} out of range (0..{len(posts) - 1})"
            )
        post = posts[offset]

        title = _strip_html(post.get("title", {}).get("rendered", ""))
        body = _strip_html(post.get("content", {}).get("rendered", ""))
        excerpt = _strip_html(post.get("excerpt", {}).get("rendered", ""))

        return {
            "title": title,
            # `text` is what dumb consumers read. When summary=True
            # we put the excerpt here so the rest of the pipeline
            # doesn't need to know about the distinction.
            "text": excerpt if summary else body,
            "url": post.get("link", ""),
            "summary": excerpt,
            "offset": offset,
        }
