"""Twilio XML / SignalWire LAML output plugin.

Renders a single article into TwiML/LAML for phone-system playback.
The two formats are functionally identical; this one plugin covers
both. The article's ``text`` field is what's read to the caller —
the source plugin decides whether that's the full body or just a
summary by setting ``summary=True/False`` on its fetch.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode
from xml.sax.saxutils import escape

from ..base import OutputPlugin


class TwilioXMLOutput(OutputPlugin):
    name = "twilio_xml"
    description = "Twilio TwiML / SignalWire LAML for phone-system navigation"
    content_type = "application/xml"

    async def render(
        self,
        article: dict,
        *,
        tts_base_url: str = "",
        voice: str | None = None,
        language: str | None = None,
    ) -> str:
        if not article:
            return self._wrap_response(
                "  <Say>No article is available at this time.</Say>"
            )

        title = escape(article.get("title", "Untitled"))
        text = article.get("text", "")

        lines: list[str] = []
        if tts_base_url and text:
            # Hand the body off to /speak so the IVR plays real
            # synthesised speech rather than Twilio's default
            # voice reading the entire body inline.
            params = {"text": text}
            if voice:
                params["voice"] = voice
            if language:
                params["language"] = language
            audio_url = f"{tts_base_url}/speak?{urlencode(params, quote_via=quote)}"
            lines.append(f"  <Say>Article: {title}</Say>")
            lines.append(f"  <Play>{escape(audio_url)}</Play>")
        else:
            # Fallback: no TTS configured, or empty body.
            # Read the title (and text, if any) inline.
            inline = f"{title}. {escape(text)}" if text else title
            lines.append(f"  <Say>{inline}</Say>")
        lines.append('  <Pause length="1"/>')

        return self._wrap_response("\n".join(lines))

    def _wrap_response(self, body: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<Response>\n"
            f"{body}\n"
            "</Response>"
        )
