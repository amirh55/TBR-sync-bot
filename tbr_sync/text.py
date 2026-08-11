# -*- coding: utf-8 -*-
from __future__ import annotations

import html

from .config import Config

RTL_MARK = "‏"


def _apply_replacements(text: str, config: Config) -> str:
    if config.bale_username_to_replace and config.telegram_username_replacement:
        text = text.replace(config.bale_username_to_replace, config.telegram_username_replacement)
    return text


def _add_rtl_marks(text: str) -> str:
    lines = text.split("\n")
    return "\n".join((RTL_MARK + line) if line.strip() and not line.startswith(RTL_MARK) else line for line in lines)


def split_plain_text(text: str, limit: int) -> list[str]:
    """Split raw text into chunks of at most `limit` characters.

    Splitting must happen on the plain text, never on the rendered HTML: cutting
    rendered HTML can land inside a <b> tag or an &amp; entity, which makes
    Telegram reject the whole message with "can't parse entities".
    """
    if limit < 2:
        raise ValueError("limit must be at least 2")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        # Prefer a line break, then a space, and only hard-cut as a last resort.
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk.strip()]


def bale_markdown_to_telegram_html(text: str | None, config: Config) -> str:
    """Convert Bale single-star bold markup to Telegram-safe HTML.

    Bale channel captions can arrive as: emoji*multi line text\n@channel\n*
    A small character parser is safer than a regular expression for this case.
    """
    if not text:
        return ""

    text = _apply_replacements(text, config)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    out: list[str] = []
    bold_open = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "*":
            # Support both *bold* and **bold**.
            if i + 1 < len(text) and text[i + 1] == "*":
                i += 2
            else:
                i += 1
            out.append("</b>" if bold_open else "<b>")
            bold_open = not bold_open
            continue
        out.append(html.escape(ch, quote=False))
        i += 1

    if bold_open:
        out.append("</b>")

    result = "".join(out)
    if config.force_rtl:
        result = _add_rtl_marks(result)
    return result
