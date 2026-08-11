# -*- coding: utf-8 -*-
from pathlib import Path

import pytest
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from tbr_sync.telegram_api import MAX_ALBUM_ITEMS, MAX_CAPTION, MAX_TEXT, TelegramSender, _album_batches


@pytest.fixture
def sender(config):
    instance = TelegramSender.__new__(TelegramSender)
    instance.config = config()
    instance.bot = None
    return instance


def _photos(count):
    return [("photo", Path(f"{i}.jpg")) for i in range(count)]


# --------------------------------------------------------------- album sizing


@pytest.mark.parametrize("count", range(2, 60))
def test_every_batch_is_a_legal_album_size(count):
    """Telegram accepts 2..10 items per sendMediaGroup call."""
    batches = _album_batches(_photos(count))
    sizes = [len(batch) for batch in batches]
    assert sum(sizes) == count
    assert all(2 <= size <= MAX_ALBUM_ITEMS for size in sizes)


def test_eleven_items_are_not_split_into_ten_plus_one():
    assert [len(b) for b in _album_batches(_photos(11))] == [9, 2]


def test_ten_items_stay_in_one_batch():
    assert [len(b) for b in _album_batches(_photos(10))] == [10]


# ------------------------------------------------------------ text rendering


def test_escape_heavy_text_still_fits_telegram_limit(sender):
    chunks = sender.render_chunks("&" * 6000)
    assert chunks
    assert all(len(chunk) <= MAX_TEXT for chunk in chunks)


def test_no_chunk_ends_inside_an_html_entity(sender):
    for chunk in sender.render_chunks("&" * 6000):
        assert not chunk.rstrip().endswith("&")


def test_bold_tags_are_balanced_in_every_chunk(sender):
    chunks = sender.render_chunks(("*" + "ب" * 300 + "*\n") * 40)
    assert chunks
    for chunk in chunks:
        assert chunk.count("<b>") == chunk.count("</b>")


def test_blank_text_renders_nothing(sender):
    assert sender.render_chunks("   \n  ") == []


def test_short_text_is_used_as_a_caption(sender):
    assert sender._caption_and_rest("hello") == ("hello", [])


def test_long_text_is_sent_as_follow_up_instead_of_caption(sender):
    caption, rest = sender._caption_and_rest("x" * (MAX_CAPTION + 100))
    assert caption is None
    assert rest


# -------------------------------------------------------------------- retry


def test_bad_request_is_a_network_error_subclass():
    """python-telegram-bot quirk the retry logic depends on: BadRequest must fail fast."""
    assert issubclass(BadRequest, NetworkError)


async def _always(exc):
    raise exc


@pytest.mark.asyncio
async def test_timeout_is_retried_then_succeeds(sender):
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimedOut()
        return "done"

    assert await sender._retry("test", flaky) == "done"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_bad_request_is_not_retried(sender):
    calls = {"n": 0}

    async def bad():
        calls["n"] += 1
        raise BadRequest("chat not found")

    with pytest.raises(BadRequest):
        await sender._retry("test", bad)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_flood_control_is_waited_out(sender):
    calls = {"n": 0}

    async def flood():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RetryAfter(0)
        return "ok"

    assert await sender._retry("test", flood) == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_retry_gives_up_after_the_configured_attempts(config):
    instance = TelegramSender.__new__(TelegramSender)
    instance.config = config(telegram_max_retries=3)
    instance.bot = None
    calls = {"n": 0}

    async def dead():
        calls["n"] += 1
        raise NetworkError("down")

    with pytest.raises(NetworkError):
        await instance._retry("test", dead)
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retried_upload_reads_the_file_from_the_start(sender, tmp_path):
    """A retry must re-open the file; a spent handle would upload zero bytes."""
    probe = tmp_path / "payload.bin"
    probe.write_bytes(b"HELLO-PAYLOAD")
    reads = []
    attempts = {"n": 0}

    async def upload():
        attempts["n"] += 1
        with probe.open("rb") as handle:
            reads.append(handle.read())
        if attempts["n"] < 2:
            raise TimedOut()
        return "sent"

    await sender._retry("upload", upload)
    assert reads == [b"HELLO-PAYLOAD", b"HELLO-PAYLOAD"]
