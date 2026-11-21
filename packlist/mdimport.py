"""Import packing lists written in Markdown (as kept in a notes app or document).

Two shapes are understood:

* A **master list** for one person: `## Section`, optional `### Sub-section`,
  `- item`, and indented `  - sub-item` lines.
* A **trip checklist** covering several people: `## Person`, `### Section`,
  `- [ ] item` lines, plus an optional `## Left out ...` section.

Markers inside item text: ❓ = decide for this trip, ➕ = suggested new item,
`*(note)*` = a note shown next to the item.
"""

from __future__ import annotations

import re

from .model import ASK_MARK, NEW_MARK, IdMaker, clean_item

SKIP_SECTIONS = ("what changed", "to confirm")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_ITEM = re.compile(r"^(\s*)[-*]\s+(.*)$")


def _strip_heading(text: str) -> str:
    return re.sub(r"\s*\*\(([^)]*)\)\*\s*", " ", text).replace("**", "").strip()


def _add_item(items: list, indent: int, text: str) -> None:
    item = clean_item(text)
    if not item["name"]:
        return
    if indent >= 2 and items:
        items[-1].setdefault("sub", []).append(item)
    else:
        items.append(item)


def parse_master(md: str, person: str) -> dict:
    """Parse one person's master list into {person, title, sections:[{name, items}]}."""
    title = person
    sections: list[dict] = []
    top = sub = None
    skipping = False
    current: dict | None = None
    for line in md.splitlines():
        h = _HEADING.match(line)
        if h:
            level, text = len(h.group(1)), _strip_heading(h.group(2))
            if level == 1:
                title = text
                current = None
                continue
            if level == 2:
                top, sub = text, None
                skipping = text.lower().startswith(SKIP_SECTIONS)
            else:
                sub = text
            if skipping:
                current = None
                continue
            name = f"{top} – {sub}" if sub else top
            current = {"name": name, "items": []}
            sections.append(current)
            continue
        m = _ITEM.match(line)
        if m and current is not None and not skipping:
            _add_item(current["items"], len(m.group(1)), m.group(2))
    sections = [s for s in sections if s["items"]]
    ids = IdMaker()
    for s in sections:
        for it in s["items"]:
            it["id"] = ids.make(person, s["name"], it["name"])
            it.pop("status", None)
            for child in it.get("sub", []):
                child.pop("status", None)
    return {"person": person, "title": title, "sections": sections}


def parse_checklist(md: str) -> dict:
    """Parse a trip checklist into {title, people:[{name, sections}], left_out:[...]}."""
    title = "Trip"
    people: list[dict] = []
    left_out: list[str] = []
    person: dict | None = None
    current: dict | None = None
    in_left_out = False
    for line in md.splitlines():
        h = _HEADING.match(line)
        if h:
            level, text = len(h.group(1)), _strip_heading(h.group(2))
            if level == 1:
                title = text
            elif level == 2:
                in_left_out = text.lower().startswith("left out")
                current = None
                if not in_left_out:
                    person = {"name": text, "sections": []}
                    people.append(person)
            elif person is not None and not in_left_out:
                # ❓ on a section heading: every item in it is a decide-for-this-trip item
                current = {"name": text.replace(ASK_MARK, "").replace(NEW_MARK, "").strip(), "items": []}
                if ASK_MARK in text:
                    current["ask"] = True
                person["sections"].append(current)
            continue
        if in_left_out:
            if line.strip():
                left_out.append(line.strip().lstrip("-* ").replace("**", ""))
            continue
        m = _ITEM.match(line)
        if m and current is not None:
            _add_item(current["items"], len(m.group(1)), m.group(2))
    ids = IdMaker()
    for p in people:
        p["sections"] = [s for s in p["sections"] if s["items"]]
        pname = p["name"].split("(")[0].strip()
        for s in p["sections"]:
            section_asks = s.pop("ask", False)
            for it in s["items"]:
                it["id"] = ids.make(pname, s["name"], it["name"])
                if section_asks:
                    it["ask"] = True
    return {"title": title, "people": people, "left_out": left_out}
