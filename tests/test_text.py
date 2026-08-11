# -*- coding: utf-8 -*-
import pytest

from tbr_sync.text import bale_markdown_to_telegram_html, split_plain_text
from tbr_sync.telegram_api import MAX_TEXT


def test_short_text_is_one_chunk():
    assert split_plain_text("hello", MAX_TEXT) == ["hello"]


def test_empty_text_gives_no_chunks():
    assert split_plain_text("", MAX_TEXT) == []


def test_chunks_never_exceed_the_limit():
    text = "\n".join(f"line {i} " + "x" * 60 for i in range(500))
    assert all(len(chunk) <= MAX_TEXT for chunk in split_plain_text(text, MAX_TEXT))


def test_text_without_boundaries_is_split_losslessly():
    text = "a" * 10_000
    chunks = split_plain_text(text, MAX_TEXT)
    assert "".join(chunks) == text
    assert all(len(chunk) <= MAX_TEXT for chunk in chunks)


def test_split_prefers_line_breaks():
    text = "\n".join("x" * 100 for _ in range(200))
    assert all(not chunk.startswith("\n") for chunk in split_plain_text(text, 1000))


def test_tiny_limit_still_terminates():
    assert all(len(chunk) <= 2 for chunk in split_plain_text("ab" * 500, 2))


def test_limit_below_two_is_rejected():
    with pytest.raises(ValueError):
        split_plain_text("abc", 1)


def test_bold_markup_becomes_html(config):
    assert bale_markdown_to_telegram_html("*bold*", config()) == "<b>bold</b>"


def test_double_star_is_also_bold(config):
    assert bale_markdown_to_telegram_html("**bold**", config()) == "<b>bold</b>"


def test_unclosed_bold_is_still_balanced(config):
    rendered = bale_markdown_to_telegram_html("*never closed", config())
    assert rendered.count("<b>") == rendered.count("</b>") == 1


def test_html_characters_are_escaped(config):
    assert bale_markdown_to_telegram_html("a < b & c", config()) == "a &lt; b &amp; c"


def test_username_replacement(config):
    cfg = config(bale_username_to_replace="@old", telegram_username_replacement="@new")
    assert bale_markdown_to_telegram_html("join @old now", cfg) == "join @new now"
