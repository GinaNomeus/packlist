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
