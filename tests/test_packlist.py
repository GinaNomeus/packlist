import json
from pathlib import Path

import pytest

from packlist import store
from packlist.cli import age_months, main
from packlist.mdimport import parse_checklist, parse_master

EXAMPLE = Path(__file__).parent.parent / "examples" / "campsite-weekend.md"


def test_checklist_keeps_order_markers_and_notes():
    t = parse_checklist(EXAMPLE.read_text())
    assert [p["name"] for p in t["people"]] == ["Sam", "Juno"]
    sam = t["people"][0]
    assert [s["name"] for s in sam["sections"]] == ["Front door", "Tent bag", "Wash kit", "Cool box"]
    tent = {i["name"]: i for i in sam["sections"][1]["items"]}
    assert tent["Sleeping bag"]["note"].startswith("the warm one")
    assert tent["Camping chairs (only if we drive)"]["ask"] is True
    cool = sam["sections"][3]["items"]
    assert cool[0]["new"] is True
    assert [s["name"] for s in cool[1]["sub"]] == ["Oat sachets", "Ground coffee"]
    assert t["left_out"] == ["Sam – city break only: theatre tickets", "Juno – swimming: armbands"]


def test_ids_are_unique_and_readable():
    t = parse_checklist(EXAMPLE.read_text())
    ids = [i["id"] for p in t["people"] for s in p["sections"] for i in s["items"]]
    assert len(ids) == len(set(ids))
    assert "sam.front-door.keys" in ids


def test_master_list_with_subsections():
    md = "# Kit\n\n## What changed\n- ignore me\n\n## Kitchen\n\n### Crate A\n- Lantern\n\n### Crate B\n- Kettle\n"
    m = parse_master(md, "Sam")
    assert [s["name"] for s in m["sections"]] == ["Kitchen – Crate A", "Kitchen – Crate B"]


def test_age_in_months():
    assert age_months("2024-03", "2026-05-20") == 26
    assert age_months("2024-03-25", "2026-05-20") == 25


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PACK_DATA", str(tmp_path))  # not a git repo: no syncing
    main(["import-trip", "camp", str(EXAMPLE), "--start", "2026-05-20", "--child", "Juno=2024-03"])
    return tmp_path


def test_cli_done_skip_and_section(data, capsys):
    main(["done", "tent bag", "--only-todo"])
    main(["skip", "wellies"])
    trip = json.loads((data / "trips" / "camp.json").read_text())
    assert trip["children"]["Juno"]["age_months"] == 26
    c = store.progress(trip)
    assert (c["packed"], c["skipped"]) == (4, 1)
    main(["undo", "head torch"])
    assert store.progress(store.load_trip())["packed"] == 3


def test_split_keeps_place_and_flags(data):
    main(["split", "camping chairs", "--into", "Chairs", "Table"])
    names = [i["name"] for i in store.load_trip()["people"][0]["sections"][1]["items"]]
    assert names == ["Tent + pegs", "Sleeping bag", "Head torch", "Chairs", "Table"]
    assert all(i.get("ask") for i in store.load_trip()["people"][0]["sections"][1]["items"][3:])


def test_move_to_other_section_keeps_status(data):
    main(["done", "dental kit"])
    main(["move", "dental kit", "--to", "tent bag", "--before", "head torch"])
    sam = store.load_trip()["people"][0]
    assert [i["name"] for i in sam["sections"][1]["items"]][2] == "Dental kit"
    assert sam["sections"][1]["items"][2]["status"] == "packed"
    assert "Dental kit" not in [i["name"] for i in sam["sections"][2]["items"]]


def test_change_survives_a_phone_save_in_between(tmp_path, monkeypatch):
    """The phone pushes while the CLI is saving: the CLI must redo its change on top."""
    import subprocess

    def run(*args, cwd):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True)

    remote, data, phone = tmp_path / "remote.git", tmp_path / "data", tmp_path / "phone"
    run("git", "init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    run("git", "clone", "-q", str(remote), str(data), cwd=tmp_path)
    for d in (data,):
        run("git", "config", "user.email", "t@example.com", cwd=d); run("git", "config", "user.name", "t", cwd=d)
    monkeypatch.setenv("PACK_DATA", str(data))
    parsed = __import__("packlist.mdimport", fromlist=["x"]).parse_checklist(EXAMPLE.read_text())
    store.write_json(data / "trips" / "camp.json", {"id": "camp", "title": "x", "people": parsed["people"], "rev": 0})
    store.set_current_trip("camp")
    run("git", "add", "-A", cwd=data); run("git", "commit", "-q", "-m", "start", cwd=data)
    run("git", "push", "-q", "-u", "origin", "main", cwd=data)

    real_sync_up, calls = store.sync_up, []

    def phone_pushes_first(message):
        if not calls:  # the phone saves just before our first push
            calls.append(1)
            run("git", "clone", "-q", str(remote), str(phone), cwd=tmp_path)
            run("git", "config", "user.email", "p@example.com", cwd=phone); run("git", "config", "user.name", "p", cwd=phone)
            t = json.loads((phone / "trips" / "camp.json").read_text())
            t["people"][1]["sections"][0]["items"][0]["status"] = "packed"   # Favourite rabbit
            (phone / "trips" / "camp.json").write_text(json.dumps(t, indent=1))
            run("git", "commit", "-q", "-am", "phone", cwd=phone); run("git", "push", "-q", cwd=phone)
        return real_sync_up(message)

    monkeypatch.setattr(store, "sync_up", phone_pushes_first)
    main(["done", "keys"])
    store.sync_down()
    t = store.load_trip()
    assert t["people"][0]["sections"][0]["items"][0]["status"] == "packed"   # ours: Keys
    assert t["people"][1]["sections"][0]["items"][0]["status"] == "packed"   # the phone's


def test_add_item_before_another(data):
    main(["add", "Storybook", "--person", "juno", "--to", "night", "--before", "night light", "--note", "bedtime"])
    night = store.load_trip()["people"][1]["sections"][1]["items"]
    assert [i["name"] for i in night] == ["Travel cot", "Storybook", "Night light"]
    assert night[1]["status"] == "todo" and night[1]["note"] == "bedtime"


def test_notes_and_lessons(data):
    main(["note", "Book the campsite with shade"])
    main(["note", "--lesson", "Bring a second tarp"])
    t = store.load_trip()
    assert t["notes"][0]["text"] == "Book the campsite with shade" and t["notes"][0]["at"]
    assert t["lessons"] == ["Bring a second tarp"]
