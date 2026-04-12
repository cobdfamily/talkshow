"""WordPress REST API source plugin.

Fetches articles from a WordPress site's REST API (v2).
Works with any WordPress site that exposes /wp-json/wp/v2/posts.
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


class WordPressSource(SourcePlugin):
    name = "wordpress"
    description = "Fetch articles from a WordPress REST API (v2)"

    async def fetch(self, url: str, *, article_offset: int = 0) -> dict:
        articles = await self.list_articles(url)
        if article_offset < 0 or article_offset >= len(articles):
            raise IndexError(
                f"articleOffset {article_offset} out of range (0–{len(articles) - 1})"
            )
        article = articles[article_offset]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(article["api_url"])
            resp.raise_for_status()
            post = resp.json()

        return {
            "title": _strip_html(post.get("title", {}).get("rendered", "")),
            "text": _strip_html(post.get("content", {}).get("rendered", "")),
            "url": post.get("link", ""),
            "index": article_offset,
        }

    async def list_articles(self, url: str) -> list[dict]:
        api_url = url.rstrip("/") + "/wp-json/wp/v2/posts"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(api_url, params={"per_page": 100})
            resp.raise_for_status()
            posts = resp.json()

        return [
            {
                "title": _strip_html(p.get("title", {}).get("rendered", "")),
                "url": p.get("link", ""),
                "api_url": api_url + f"/{p['id']}",
                "index": i,
            }
            for i, p in enumerate(posts)
        ]
