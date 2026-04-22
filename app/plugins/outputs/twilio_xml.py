"""Twilio XML / Signalwire LAML output plugin.

Generates TwiML/LAML for phone system article navigation. The two formats
are functionally identical, so this single plugin covers both.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode
from xml.sax.saxutils import escape

from ..base import OutputPlugin


class TwilioXMLOutput(OutputPlugin):
    name = "twilio_xml"
    description = "Twilio TwiML / Signalwire LAML for phone system navigation"
    content_type = "application/xml"

    async def render(
        self,
        articles: list[dict],
        *,
        tts_base_url: str = "",
        voice: str | None = None,
        language: str | None = None,
        mode: str = "full",
    ) -> str:
        if not articles:
            return self._wrap_response(
                "  <Say>No articles are available at this time.</Say>"
            )

        lines: list[str] = []

        for article in articles:
            title = escape(article.get("title", "Untitled"))
            text = article.get("text", "")

            if mode in ("summary", "nextArticle"):
                # Header only — just announce the title
                prefix = "Next article" if mode == "nextArticle" else "Article"
                lines.append(f"  <Say>{prefix}: {title}</Say>")
                lines.append('  <Pause length="1"/>')
            elif tts_base_url and text:
                params = {"text": text}
                if voice:
                    params["voice"] = voice
                if language:
                    params["language"] = language
                audio_url = f"{tts_base_url}/speak?{urlencode(params, quote_via=quote)}"
                lines.append(f'  <Say>Article: {title}</Say>')
                lines.append(f'  <Play>{escape(audio_url)}</Play>')
                lines.append('  <Pause length="1"/>')
            else:
                lines.append(f"  <Say>{title}. {escape(text)}</Say>")
                lines.append('  <Pause length="1"/>')

        return self._wrap_response("\n".join(lines))

    def _wrap_response(self, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"{body}\n"
            "</Response>"
        )
