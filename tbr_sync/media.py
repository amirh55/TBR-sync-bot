# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass
class MediaItem:
    kind: str
    file_id: str
    unique_key: str
    file_name: str = ""
    mime_type: str = ""


def _listify(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _file_id(obj: dict | None) -> str | None:
    if not isinstance(obj, dict):
        return None
    return obj.get("file_id") or obj.get("fileId") or obj.get("id")


def _unique_key(obj: dict, fallback: str) -> str:
    return str(
        obj.get("file_unique_id")
        or obj.get("fileUniqueId")
        or obj.get("unique_id")
        or obj.get("uniqueId")
        or fallback
    )


def _mime(obj: dict) -> str:
    return str(obj.get("mime_type") or obj.get("mimeType") or "").lower().strip()


def _name(obj: dict) -> str:
    return str(obj.get("file_name") or obj.get("fileName") or "").lower().strip()


def _document_kind(obj: dict) -> str:
    mime = _mime(obj)
    name = _name(obj)
    if mime == "image/gif" or name.endswith(".gif"):
        return "animation"
    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        return "photo"
    if mime.startswith("video/") or name.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return "video"
    if mime.startswith("audio/") or name.endswith((".mp3", ".m4a", ".ogg", ".wav", ".opus")):
        return "audio"
    return "document"


def _looks_like_media_document(obj: dict) -> bool:
    return _document_kind(obj) in {"photo", "video", "animation", "audio"}


def _add(items: list[MediaItem], seen: set[str], kind: str, obj: dict | None) -> None:
    fid = _file_id(obj)
    if not fid:
        return
    key = f"{kind}:{_unique_key(obj or {}, fid)}"
    if key in seen:
        return
    seen.add(key)
    items.append(MediaItem(kind=kind, file_id=str(fid), unique_key=key, file_name=_name(obj or {}), mime_type=_mime(obj or {})))


def extract_media(message: dict, config: Config) -> list[MediaItem]:
    """Extract all supported media from a raw Bale message.

    Covers raw Bot API fields and a few python-bale-bot wrapper variants.
    """
    items: list[MediaItem] = []
    seen: set[str] = set()
    has_native_photo_or_video = False

    # Raw Bale/Telegram style: photo is an array of sizes for one photo.
    photo_value = message.get("photo") or message.get("photos")
    if photo_value:
        photos = _listify(photo_value)
        if photos:
            _add(items, seen, "photo", photos[-1])
            has_native_photo_or_video = True

    for video in _listify(message.get("video") or message.get("videos")):
        _add(items, seen, "video", video)
        has_native_photo_or_video = True

    for animation in _listify(message.get("animation")):
        _add(items, seen, "animation", animation)

    for audio in _listify(message.get("audio")):
        _add(items, seen, "audio", audio)

    for voice in _listify(message.get("voice")):
        _add(items, seen, "voice", voice)

    for sticker in _listify(message.get("sticker")):
        # Telegram accepts many stickers as sticker uploads. If it fails, sender falls back to document.
        _add(items, seen, "sticker", sticker)

    documents = []
    documents.extend(_listify(message.get("document")))
    documents.extend(_listify(message.get("documents")))
    for document in documents:
        if not isinstance(document, dict):
            continue
        kind = _document_kind(document)
        # If Bale sends the same photo/video twice (as photo + document), ignore the duplicate document.
        # If the post only has document, send image-like documents as photo/video so document_...file does not appear.
        if config.skip_duplicate_media_documents and has_native_photo_or_video and _looks_like_media_document(document):
            continue
        _add(items, seen, kind, document)

    return items


def detect_kind_from_file(path: Path, default: str) -> str:
    try:
        head = path.read_bytes()[:32]
    except Exception:
        return default
    if head.startswith(b"\xff\xd8\xff"):
        return "photo"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "photo"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "animation"
    if head.startswith(b"RIFF") and b"WEBP" in head[:16]:
        return "photo"
    if len(head) > 12 and b"ftyp" in head[4:12]:
        return "video"
    return default
