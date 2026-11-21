#!/usr/bin/env python3
"""Refuse a commit that contains anything from the private packing data.

Install as a git pre-commit hook:  ln -s ../../scripts/check_no_private_data.py .git/hooks/pre-commit

It reads the private data folder ($PACK_DATA, default ~/packlist-data) on this
machine and fails when a file being committed (or the commit author) contains:

* any item name, section name, person or child name, or trip title, as a whole word;
* any capitalised word from item names, notes and "left out" lines (names, places);
* any note or source line;
* any birth date.

It fails closed: without the data folder there is nothing to check against, so
the commit is refused (set PACK_DATA, or ALLOW_NO_PRIVATE_DATA=1 on a machine
that has no private data at all).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MARKERS = re.compile(r"❓|➕|\*\(|\)\*|\[[ xX]\]")
WORD = re.compile(r"[A-ZÄÖÜ][\wäöüß'’-]{3,}")


def _clean(text: str) -> str:
    return MARKERS.sub(" ", text).strip(" -*#\t").strip().lower()


def private_terms(data: Path) -> tuple[set[str], set[str]]:
    """(whole-word terms, substring phrases) from the private data."""
    words: set[str] = set()
    phrases: set[str] = set()

    def add_name(name: str, min_len: int = 4) -> None:
        name = _clean(name)
        if len(name) >= min_len:
            words.add(name)

    def add_free_text(text: str) -> None:
        if len(_clean(text)) >= 12:
            phrases.add(_clean(text))
        # Capitalised words that do not start a phrase are names and places.
        text = MARKERS.sub(" ", text).strip(" -*#\t")
        for part in re.split(r"[:,;()–]|\s-\s|->", text):
            for w in WORD.findall(part.strip())[1:] if part.strip()[:1].isupper() else WORD.findall(part):
                words.add(w.lower())
        for part in re.split(r"[:,;()]", text):
            add_name(part, 6)

    files = list(data.glob("trips/*.json")) + list(data.glob("lists/*.json"))
    for f in files:
        obj = json.loads(f.read_text(encoding="utf-8"))
        add_name(obj.get("title", ""))
        for child, info in (obj.get("children") or {}).items():
            add_name(child, 3)
            if info.get("born"):
                phrases.add(str(info["born"]).lower())
        for line in obj.get("left_out", []):
            add_free_text(line)
        for person in obj.get("people", [obj]):
            add_name(person.get("name", "").split("(")[0], 3)
            add_name(person.get("person", ""), 3)
            for section in person.get("sections", []):
                add_name(section["name"], 5)
                for item in section.get("items", []):
                    for it in [item, *item.get("sub", [])]:
                        add_name(it["name"])
                        add_free_text(it["name"])
                        if it.get("note"):
                            add_free_text(it["note"])
    for f in data.glob("source/*.md"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.lstrip().startswith("#"):
                add_free_text(line)
    # Everyday words that the private list happens to use too, kept in the private folder.
    allow = data / ".check-allow"
    if allow.exists():
        words -= {w.strip().lower() for w in allow.read_text(encoding="utf-8").splitlines() if w.strip()}
    return words, phrases


def staged_files() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def find_problems(texts: dict[str, str], words: set[str], phrases: set[str]) -> list[tuple[str, str]]:
    problems = []
    for where, text in texts.items():
        low = text.lower()
        tokens = set(re.findall(r"[\wäöüß'’-]+", low))
        for w in words:
            if re.fullmatch(r"[\wäöüß'’-]+", w):
                hit = w in tokens
            else:
                hit = re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low)
            if hit:
                problems.append((where, w))
        for ph in phrases:
            if ph in low:
                problems.append((where, ph))
    return problems


def main() -> int:
    data = Path(os.environ.get("PACK_DATA", Path.home() / "packlist-data")).expanduser()
    if not data.exists():
        if os.environ.get("ALLOW_NO_PRIVATE_DATA") == "1":
            return 0
        print(f"Commit refused: private data folder {data} not found, so nothing can be checked.", file=sys.stderr)
        return 1
    words, phrases = private_terms(data)
    texts = {}
    for f in staged_files():
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True, check=True).stdout
        texts[f] = blob.decode("utf-8", "ignore")
    ident = subprocess.run(["git", "var", "GIT_AUTHOR_IDENT"], capture_output=True, text=True).stdout
    texts["(commit author)"] = re.sub(r"\s\d+ [+-]\d{4}$", "", ident.strip())
    problems = sorted(set(problems_ for problems_ in find_problems(texts, words, phrases)))
    verbose = os.environ.get("PACK_CHECK_VERBOSE") == "1"  # show the matched text (local terminal only)
    for where, term in problems:
        shown = f"'{term}'" if verbose else f"{len(term)} characters"
        print(f"PRIVATE DATA in {where}: text from the private packing data appears here ({shown}).", file=sys.stderr)
    if problems:
        print("Commit refused: real packing data must stay in the private data repository.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
