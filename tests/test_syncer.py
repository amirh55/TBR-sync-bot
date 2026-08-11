# -*- coding: utf-8 -*-
"""Behaviour of the main loop: a failing update must not stall the queue."""
import pytest

from tbr_sync.store import MappingStore
from tbr_sync.syncer import Syncer

CHAT = {"id": -100123, "username": "src", "type": "channel"}


def post(update_id, message_id, text):
    return {
        "update_id": update_id,
        "channel_post": {"message_id": message_id, "chat": CHAT, "text": text},
    }


class FakeBale:
    async def delete_webhook(self):
        pass

    async def get_me(self):
        return {"username": "fakebot"}

    async def get_chat(self, chat_id):
        return dict(CHAT)

    async def skip_pending_updates(self):
        return None


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_text(self, text, reply_to_message_id=None):
        self.sent.append(text)
        return [1000 + len(self.sent)]


async def drive(syncer, updates, telegram, poison=()):
    """Replicates the offset bookkeeping of Syncer.run over one batch."""
    bale = FakeBale()
    await syncer._resolve_source_chat(bale)
    offset = await syncer._initial_offset(bale)
    for update in updates:
        update_id = update.get("update_id")
        try:
            if update_id in poison:
                raise RuntimeError("oversized file / flood control / bad caption")
            await syncer.handle_update(bale, telegram, update)
        except Exception:
            pass
        finally:
            if isinstance(update_id, int):
                offset = update_id + 1
                syncer.store.set_offset(offset)
    return offset


@pytest.mark.asyncio
async def test_failing_update_does_not_stall_the_queue(config):
    cfg = config()
    syncer = Syncer(cfg)
    telegram = FakeTelegram()
    updates = [post(1, 11, "first"), post(2, 12, "boom"), post(3, 13, "third")]

    offset = await drive(syncer, updates, telegram, poison={2})

    assert offset == 4, "offset must move past the update that raised"
    assert telegram.sent == ["first", "third"], "later posts must still go through"
    assert syncer.store.get_offset() == 4
    syncer.store.close()


@pytest.mark.asyncio
async def test_restart_resumes_from_the_stored_offset(config):
    cfg = config()
    first = Syncer(cfg)
    await drive(first, [post(7, 70, "hello")], FakeTelegram())
    first.store.close()

    second = Syncer(cfg)
    assert await second._initial_offset(FakeBale()) == 8
    second.store.close()


@pytest.mark.asyncio
async def test_redelivered_message_is_not_posted_twice(config):
    cfg = config()
    syncer = Syncer(cfg)
    telegram = FakeTelegram()
    bale = FakeBale()
    await syncer._resolve_source_chat(bale)

    # Same Bale message_id arriving under two different update ids.
    await syncer.handle_update(bale, telegram, post(1, 55, "once"))
    await syncer.handle_update(bale, telegram, post(2, 55, "once"))

    assert telegram.sent == ["once"]
    syncer.store.close()


@pytest.mark.asyncio
async def test_source_channel_matches_by_id_when_username_is_missing(config):
    syncer = Syncer(config())
    await syncer._resolve_source_chat(FakeBale())
    assert syncer._is_source_channel({"chat": {"id": -100123, "type": "channel"}})
    syncer.store.close()


@pytest.mark.asyncio
async def test_source_channel_matches_by_username_case_insensitively(config):
    syncer = Syncer(config())
    await syncer._resolve_source_chat(FakeBale())
    assert syncer._is_source_channel({"chat": {"username": "SRC", "type": "channel"}})
    syncer.store.close()


@pytest.mark.asyncio
async def test_foreign_chat_is_rejected(config):
    syncer = Syncer(config())
    await syncer._resolve_source_chat(FakeBale())
    assert not syncer._is_source_channel({"chat": {"id": -999, "username": "somewhere_else"}})
    syncer.store.close()


def test_skip_notice_is_appended_when_files_were_dropped(config):
    syncer = Syncer(config())
    assert syncer._with_skip_notice("caption", 2) == "caption\n\nskipped 2"
    assert syncer._with_skip_notice("caption", 0) == "caption"
    syncer.store.close()


def test_store_round_trips(tmp_path):
    store = MappingStore(tmp_path / "s.db")
    store.save("chat", "msg", [1, 2, 3], "message")
    assert store.get("chat", "msg") == ([1, 2, 3], "message")
    assert store.get("chat", "missing") is None
    store.delete("chat", "msg")
    assert store.get("chat", "msg") is None
    store.close()


def test_offset_survives_reopen(tmp_path):
    store = MappingStore(tmp_path / "s.db")
    assert store.get_offset() is None
    store.set_offset(4242)
    store.close()
    assert MappingStore(tmp_path / "s.db").get_offset() == 4242
