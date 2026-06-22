# -*- coding: utf-8 -*-
from __future__ import annotations

import html

from .config import Config

RTL_MARK = "\u200f"


def _apply_replacements(text: str, config: Config) -> str:
    if config.bale_username_to_replace and config.telegram_username_replacement:
        text = text.replace(config.bale_username_to_replace, config.telegram_username_replacement)
    return text


def _add_rtl_marks(text: str) -> str:
    lines = text.split("\n")
    return "\n".join((RTL_MARK + line) if line.strip() and not line.startswith(RTL_MARK) else line for line in lines)


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
