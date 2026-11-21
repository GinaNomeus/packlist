"""Data model helpers: ids, item cleanup, statuses."""

from __future__ import annotations

import re
import unicodedata

TODO = "todo"
PACKED = "packed"
SKIPPED = "skipped"  # "not needed this time"
STATUSES = (TODO, PACKED, SKIPPED)

ASK_MARK = "❓"
NEW_MARK = "➕"


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "item"


class IdMaker:
    """Stable, readable, unique ids like `sam.front-door.keys`."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def make(self, *parts: str) -> str:
        base = ".".join(slug(p) for p in parts)
        candidate, n = base, 2
        while candidate in self.seen:
            candidate, n = f"{base}-{n}", n + 1
        self.seen.add(candidate)
        return candidate


_ITALIC_NOTE = re.compile(r"\s*\*\(([^)]*)\)\*\s*")


def clean_item(raw: str) -> dict:
    """Turn a markdown list line's text into an item dict (without id)."""
    text = raw.strip()
    status = TODO
    m = re.match(r"^\[( |x|X)\]\s*", text)
    if m:
        status = PACKED if m.group(1).lower() == "x" else TODO
        text = text[m.end():]
    item: dict = {}
    if ASK_MARK in text:
        item["ask"] = True
        text = text.replace(ASK_MARK, "")
    if NEW_MARK in text:
        item["new"] = True
        text = text.replace(NEW_MARK, "")
    notes = _ITALIC_NOTE.findall(text)
    text = _ITALIC_NOTE.sub(" ", text)
    text = text.replace("**", "").strip()
    item = {"name": text, **item}
    if notes:
        item["note"] = "; ".join(notes)
    item["status"] = status
    return item
