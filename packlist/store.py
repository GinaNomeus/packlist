"""Reading and writing the private data repository.

The data lives in its own **private** git repository (cloned at $PACK_DATA,
default ~/packlist-data), never in this public code repository:

    current.json            {"trip": "<trip id>"}: the trip the phone app shows
    trips/<trip-id>.json    one file per trip, with a status for every item

The phone app reads and writes the same files through the GitHub API, so every
change here is committed and pushed straight away, and every read starts with
the latest version from GitHub.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from .model import PACKED, SKIPPED, STATUSES, TODO


def data_dir() -> Path:
    return Path(os.environ.get("PACK_DATA", Path.home() / "packlist-data")).expanduser()


def is_git_repo() -> bool:
    return (data_dir() / ".git").exists()


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(data_dir()), *args], check=check,
                          capture_output=True, text=True)


def sync_down() -> None:
    """Take the latest data from GitHub, keeping any local commits on top.

    Uncommitted edits are refused rather than overwritten."""
    if not is_git_repo():
        return
    if git("status", "--porcelain").stdout.strip():
        raise SystemExit(f"{data_dir()} has uncommitted changes; commit or discard them first.")
    git("fetch", "--quiet", "origin")
    if git("rebase", "--quiet", "@{upstream}", check=False).returncode != 0:
        git("rebase", "--abort", check=False)
        raise SystemExit("Local commits conflict with the newest data on GitHub; nothing was changed.")


def sync_up(message: str) -> bool:
    """Commit and push. False when GitHub has a newer version (retry)."""
    if not is_git_repo():
        return True
    git("add", "-A")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return True
    git("commit", "--quiet", "-m", message)
    return git("push", "--quiet", "origin", "HEAD", check=False).returncode == 0


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # One key per line keeps git diffs readable; the phone app writes the same shape.
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---- trips -----------------------------------------------------------------

def trip_path(trip_id: str) -> Path:
    return data_dir() / "trips" / f"{trip_id}.json"


def current_trip_id() -> str | None:
    p = data_dir() / "current.json"
    return read_json(p).get("trip") if p.exists() else None


def set_current_trip(trip_id: str) -> None:
    write_json(data_dir() / "current.json", {"trip": trip_id})


def load_trip(trip_id: str | None = None) -> dict:
    trip_id = trip_id or current_trip_id()
    if not trip_id:
        raise SystemExit("No current trip. Create one first.")
    return read_json(trip_path(trip_id))


def save_trip(trip: dict) -> None:
    trip["rev"] = int(trip.get("rev", 0)) + 1
    trip["updated_at"] = now()
    write_json(trip_path(trip["id"]), trip)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def update(change, message: str, trip_id: str | None = None, attempts: int = 4):
    """Run `change(trip) -> result` on the latest trip and push it, retrying
    when the phone saved something in between."""
    for _ in range(attempts):
        sync_down()
        trip = load_trip(trip_id)
        result = change(trip)
        save_trip(trip)
        if sync_up(message):
            return result
    raise SystemExit("Could not save to GitHub (it kept changing, or there is no connection). Nothing was changed.")


def iter_items(trip: dict):
    """Yield (person, section, item) in packing order."""
    for person in trip["people"]:
        for section in person["sections"]:
            for item in section["items"]:
                yield person, section, item


def find_item(trip: dict, item_id: str) -> dict | None:
    for _, _, item in iter_items(trip):
        if item["id"] == item_id:
            return item
    return None


def set_status(item: dict, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    item["status"] = status
    if status == TODO:
        item.pop("at", None)
    else:
        item["at"] = now()


def match(trip: dict, words: str, person: str | None = None, section_only: bool = False):
    """Items whose section or name contains `words` (case-insensitive).

    A query that names a section matches every item in it.
    """
    q = words.lower().strip()
    out = []
    for p, s, item in iter_items(trip):
        if person and not p["name"].lower().startswith(person.lower()):
            continue
        in_section = q in s["name"].lower()
        in_name = q in item["name"].lower() or q == item["id"]
        if in_section or (in_name and not section_only):
            out.append((p, s, item))
    return out


def progress(trip: dict, person: dict | None = None) -> dict:
    people = [person] if person else trip["people"]
    counts = {TODO: 0, PACKED: 0, SKIPPED: 0}
    for p in people:
        for s in p["sections"]:
            for it in s["items"]:
                counts[it.get("status", TODO)] += 1
    counts["total"] = sum(counts[k] for k in STATUSES)
    return counts
