"""`pack`: the command line behind the phone app.

Usually driven by an assistant on the traveller's behalf ("the wash bag is done"),
so every command prints what it changed in plain words. Every change is pushed
to the private data repository at once, where the phone app picks it up.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import store
from .mdimport import parse_checklist, parse_master
from .model import PACKED, SKIPPED, TODO, slug

MARK = {TODO: "[ ]", PACKED: "[x]", SKIPPED: "[–]"}


def age_months(born: str, on: str) -> int:
    b = dt.date.fromisoformat(born if len(born) > 7 else born + "-01")
    d = dt.date.fromisoformat(on)
    return (d.year - b.year) * 12 + d.month - b.month - (1 if d.day < b.day else 0)


def cmd_import_list(a):
    store.sync_down()
    data = parse_master(Path(a.file).read_text(encoding="utf-8"), a.person)
    path = store.data_dir() / "lists" / f"{slug(a.person)}.json"
    store.write_json(path, data)
    if not store.sync_up(f"Import {a.person}'s master list"):
        sys.exit("Could not push to GitHub; try again.")
    n = sum(len(s["items"]) for s in data["sections"])
    print(f"Imported {n} items in {len(data['sections'])} sections.")


def cmd_import_trip(a):
    parsed = parse_checklist(Path(a.file).read_text(encoding="utf-8"))
    trip = {
        "id": a.id,
        "title": a.title or parsed["title"],
        "start": a.start,
        "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
        "children": {},
        "people": parsed["people"],
        "left_out": parsed["left_out"],
        "rev": 0,
    }
    for spec in a.child or []:
        name, born = spec.split("=")
        trip["children"][name] = {"born": born, "age_months": age_months(born, a.start)}
    store.sync_down()
    if store.trip_path(a.id).exists() and not a.force:
        sys.exit(f"Trip {a.id} exists already (use --force to replace it).")
    store.save_trip(trip)
    store.set_current_trip(a.id)
    if not store.sync_up(f"New trip: {trip['title']}"):
        sys.exit("Could not push to GitHub; try again.")
    print(f"Trip '{trip['title']}' created with {store.progress(trip)['total']} items; it is now the current trip.")


def _print_items(rows):
    last = None
    for p, s, it in rows:
        head = f"{p['name']} · {s['name']}"
        if head != last:
            print(f"\n{head}")
            last = head
        flags = (" (decide)" if it.get("ask") and it.get("status", TODO) == TODO else "") + (" (new)" if it.get("new") else "")
        print(f"  {MARK[it.get('status', TODO)]} {it['name']}{flags}")


def _load(a):
    store.sync_down()
    return store.load_trip(a.trip)


def cmd_status(a):
    trip = _load(a)
    for p in trip["people"]:
        c = store.progress(trip, p)
        print(f"{p['name']}: {c[PACKED]} packed, {c[SKIPPED]} not needed, {c[TODO]} left of {c['total']}")


def cmd_left(a):
    trip = _load(a)
    rows = [r for r in store.iter_items(trip) if r[2].get("status", TODO) == TODO
            and (not a.person or r[0]["name"].lower().startswith(a.person.lower()))]
    _print_items(rows)
    print(f"\n{len(rows)} left.")


def cmd_show(a):
    trip = _load(a)
    _print_items([r for r in store.iter_items(trip)
                  if not a.person or r[0]["name"].lower().startswith(a.person.lower())])


def _select(trip, a):
    rows = []
    for words in a.words:
        found = store.match(trip, words, a.person, a.section)
        if a.only_todo:
            found = [r for r in found if r[2].get("status", TODO) == TODO]
        if not found:
            print(f"Nothing matches '{words}'.")
        rows += found
    return rows


def _change(a, status):
    if a.dry_run:
        rows = _select(_load(a), a)
        _print_items(rows)
        print(f"\n(dry run: {len(rows)} items would change)")
        return

    def change(trip):
        rows = _select(trip, a)
        for _, _, it in rows:
            store.set_status(it, status)
        return rows

    rows = store.update(change, f"{status}: {', '.join(a.words)}", a.trip)
    _print_items(rows)
    print(f"\n{len(rows)} item(s) marked {status}.")


def cmd_split(a):
    """Replace one item with several, in the same place, so each can be ticked off."""

    def change(trip):
        rows = store.match(trip, a.item, a.person)
        if len(rows) != 1:
            names = ", ".join(r[2]["name"] for r in rows) or "nothing"
            raise SystemExit(f"'{a.item}' must match exactly one item (it matches: {names}).")
        _, section, old = rows[0]
        taken = {it["id"] for _, _, it in store.iter_items(trip)}
        new_items = []
        for name in a.into:
            item = {"name": name, "status": TODO}
            for key in ("ask", "new", "note"):
                if key in old:
                    item[key] = old[key]
            item["id"] = old["id"].rsplit(".", 1)[0] + "." + slug(name)
            while item["id"] in taken:
                item["id"] += "-2"
            taken.add(item["id"])
            new_items.append(item)
        i = section["items"].index(old)
        section["items"][i:i + 1] = new_items
        return old, new_items

    old, new_items = store.update(change, f"split: {a.item}", a.trip)
    print(f"'{old['name']}' is now: " + ", ".join(it["name"] for it in new_items))


def cmd_move(a):
    """Move one item to another section (another bag), keeping its status."""

    def change(trip):
        rows = store.match(trip, a.item, a.person)
        if len(rows) != 1:
            names = ", ".join(r[2]["name"] for r in rows) or "nothing"
            raise SystemExit(f"'{a.item}' must match exactly one item (it matches: {names}).")
        person, old_section, item = rows[0]
        targets = [s for s in person["sections"] if a.to.lower() in s["name"].lower()]
        if len(targets) != 1:
            names = ", ".join(s["name"] for s in targets) or "nothing"
            raise SystemExit(f"'{a.to}' must match exactly one section of {person['name']} (it matches: {names}).")
        target = targets[0]
        old_section["items"].remove(item)
        pos = len(target["items"])
        if a.before:
            hits = [i for i, it in enumerate(target["items"]) if a.before.lower() in it["name"].lower()]
            if hits:
                pos = hits[0]
        target["items"].insert(pos, item)
        return item, old_section, target

    item, old, new = store.update(change, f"move: {a.item} -> {a.to}", a.trip)
    print(f"Moved '{item['name']}' from '{old['name']}' to '{new['name']}'.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pack", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-list", help="import a person's master list from Markdown")
    p.add_argument("person"); p.add_argument("file"); p.set_defaults(fn=cmd_import_list)

    p = sub.add_parser("import-trip", help="create a trip from a Markdown checklist")
    p.add_argument("id"); p.add_argument("file")
    p.add_argument("--title"); p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--tags", help="comma-separated, e.g. beach,summer")
    p.add_argument("--child", action="append", help="name=YYYY-MM birth month, e.g. Juno=2024-03")
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_import_trip)

    for name, fn, help_ in (("status", cmd_status, "progress per person"),
                            ("left", cmd_left, "what is still to pack"),
                            ("show", cmd_show, "the whole checklist")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--trip"); p.add_argument("--person"); p.set_defaults(fn=fn)

    for name, status, help_ in (("done", PACKED, "mark items or whole sections packed"),
                                ("skip", SKIPPED, "mark items not needed this time"),
                                ("undo", TODO, "put items back on the to-pack list")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("words", nargs="+", help="part of an item or section name, or an item id")
        p.add_argument("--trip"); p.add_argument("--person")
        p.add_argument("--section", action="store_true", help="match section names only")
        p.add_argument("--only-todo", action="store_true", help="leave items already decided alone")
        p.add_argument("-n", "--dry-run", action="store_true")
        p.set_defaults(fn=lambda a, s=status: _change(a, s))

    p = sub.add_parser("split", help="turn one item into several, in the same place")
    p.add_argument("item", help="words matching exactly one item")
    p.add_argument("--into", nargs="+", required=True, help='the new item names, e.g. --into "Tent" "Pegs"')
    p.add_argument("--trip"); p.add_argument("--person"); p.set_defaults(fn=cmd_split)

    p = sub.add_parser("move", help="move one item to another section (bag)")
    p.add_argument("item", help="words matching exactly one item")
    p.add_argument("--to", required=True, help="words matching the target section")
    p.add_argument("--before", help="place it before the first item matching these words")
    p.add_argument("--trip"); p.add_argument("--person"); p.set_defaults(fn=cmd_move)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
