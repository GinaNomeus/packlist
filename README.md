# packlist

Packing lists that learn, for families travelling with children of any age.

- **Master lists in packing order.** Items stay in the order they are packed in the house, grouped by where they live or which bag they go into.
- **A checklist for every trip**, built from the master lists. Items that depend on the trip are marked *decide*. Suggested new items are marked *new*. What was left out for this trip stays visible, so nothing is dropped silently.
- **A phone app to tick things off.** Tap = packed, ⋯ = not needed this time, "All packed" for a whole bag. It works offline and catches up later.
- **A command line** (`pack`) for the same data, so an assistant such as Claude can do the bookkeeping when you just say "the wash bag is done".
- **Children's ages are recorded on every trip**, so a list for another child can start from what was needed at the same age before.

## Public code, private lists

This repository holds only code and a made-up example (`examples/`). The real lists live in a separate **private** GitHub repository:

```
current.json           {"trip": "<trip id>"}
trips/<trip id>.json   the trip's checklist with a status for every item
```

The phone app is a static page (GitHub Pages, `docs/`). It reads and writes that private repository through the GitHub API, with a fine-grained GitHub key that can only access that one repository. The key is stored only on the phone. Nothing about the lists passes through this repository or GitHub Pages.

`scripts/check_no_private_data.py`, installed as a pre-commit hook, refuses any commit to this repository that contains an item from the private lists.

## Setup

1. Create a private repository for the data and clone it to `~/packlist-data` (or set `PACK_DATA`).
2. Install the CLI: `uv sync`. Then run `uv run pack --help`.
3. Write a trip in Markdown (see `examples/campsite-weekend.md`) and load it:
   `pack import-trip 2026-05-camp examples/campsite-weekend.md --start 2026-05-20 --child Juno=2024-03`
4. On the phone, open the GitHub Pages address, add it to the Home Screen, and connect it:
   - **Data repository**: `owner/name`
   - **GitHub key**: a fine-grained token with *Contents: read and write* on that repository only.

## Command line

```
pack status                 progress per person
pack left [--person Juno]   what is still to pack, in packing order
pack done tent bag          mark a whole section (or matching items) packed
pack skip wellies           not needed on this trip
pack undo head torch        back on the list
```

Words match item and section names. `-n` shows what would change, and `--only-todo` leaves skipped items alone. Every change is pushed to the data repository at once, and the phone picks it up within seconds.

## Markdown format

`## Person`, `### Section`, and `- [ ] item` lines (indent for sub-items). Markers:
- ❓ = decide for this trip
- ➕ = suggested new item
- `*(note)*` = a note shown under the item

## Tests

`uv run pytest`
