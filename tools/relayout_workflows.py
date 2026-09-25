#!/usr/bin/env python3
"""Pull apart nodes that overlap in the shipped workflows.

A workflow's JSON carries pixel positions, and pixel positions age: a node
gains a parameter, renders 40 px taller, and quietly sits on the node below it.
The tutorials and chunks are laid out at import and fix themselves; a workflow
file does not, so this rewrites the ones that need it.

Only the numbers inside ``"pos": [x, y]`` change.  The rest of the file --
formatting, comments in note text, the order of the keys -- is left exactly as
it was, because these files are read and edited by hand.

``workflows/tutorials/`` is deliberately not touched: those files are written
by ``tools/export_workflows.py`` from the Python catalogue, which lays them out
on the way through.  Regenerate them instead of patching them, or the next
export puts the overlap straight back.

    python3 tools/relayout_workflows.py           # report what would move
    python3 tools/relayout_workflows.py --write   # move it

``--columns NAME.json`` lays one workflow out afresh in columns -- every
block one step right of what feeds it, one lane per line of work -- which
is for a graph whose links have grown long, not for one somebody arranged
by hand.  Combine with ``--write`` to keep it.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comfygmx.tutorial_graph import (  # noqa: E402
    _group_box, columns_layout, deoverlap, height_of, untangle_groups, width_of)


def collisions(nodes: list) -> list:
    """Every pair of nodes whose rectangles intersect."""
    found = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            ax, ay = a["pos"]
            bx, by = b["pos"]
            over_x = min(ax + width_of(a), bx + width_of(b)) - max(ax, bx)
            over_y = min(ay + height_of(a), by + height_of(b)) - max(ay, by)
            if over_x > 0 and over_y > 0:
                found.append((a["id"], b["id"], over_x, over_y))
    return found


def crossings(nodes: list, groups: list) -> list:
    """Every pair of coloured boxes that would be drawn across each other."""
    by_id = {n["id"]: n for n in nodes}
    boxes = []
    for group in groups or []:
        members = [by_id[i] for i in (group.get("nodes") or []) if i in by_id]
        if members:
            boxes.append((group.get("title", "?"), _group_box(members)))
    found = []
    for i, (title_a, a) in enumerate(boxes):
        for title_b, b in boxes[i + 1:]:
            over_x = min(a[2], b[2]) - max(a[0], b[0])
            over_y = min(a[3], b[3]) - max(a[1], b[1])
            if over_x > 4 and over_y > 4:
                found.append((title_a, title_b, over_x, over_y))
    return found


def rewrite(text: str, moves: dict) -> str:
    """Replace each node's ``"pos"`` in place, by finding it after its id."""
    for node_id, (x, y) in moves.items():
        marker = f'"id": "{node_id}"'
        at = text.find(marker)
        if at < 0:
            raise SystemExit(f"!! no node with id {node_id} in the file")
        start = text.find('"pos"', at)
        if start < 0:
            raise SystemExit(f"!! {node_id} has no pos")
        open_bracket = text.index("[", start)
        close = text.index("]", open_bracket)
        old = text[open_bracket:close + 1]
        if "\n" in old:
            # Keep the file's own shape: a pos written over four lines stays
            # over four lines, so the diff is the numbers and nothing else.
            indent = old.split("\n")[1][:len(old.split("\n")[1])
                                        - len(old.split("\n")[1].lstrip())]
            new = f"[\n{indent}{x},\n{indent}{y}\n{indent[:-2]}]"
        else:
            new = f"[{x}, {y}]"
        text = text[:open_bracket] + new + text[close + 1:]
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--gap", type=int, default=70)
    parser.add_argument("--columns", metavar="FILE", action="append", default=[],
                        help="lay this workflow out afresh in columns (repeatable)")
    args = parser.parse_args()

    columns = {Path(f).resolve() for f in args.columns}
    changed = 0
    for path in sorted((ROOT / "workflows").glob("*.json")):
        text = path.read_text()
        graph = json.loads(text)
        nodes = graph.get("nodes") or []
        if not nodes:
            continue
        groups = graph.get("groups") or []
        before = collisions(nodes)
        crossed = crossings(nodes, groups)
        if path.resolve() in columns:
            laid = columns_layout(copy.deepcopy(nodes), graph.get("links") or [], groups)
        else:
            laid = deoverlap(copy.deepcopy(nodes), gap_y=args.gap)
            # The coloured boxes are drawn round wherever the blocks are, so two
            # stages whose rows interleave get boxes lying across each other even
            # when no block touches another. Pull those apart as well.
            laid = untangle_groups(laid, groups, gap=args.gap)
        after = collisions(laid)
        still_crossed = crossings(laid, groups)
        moves = {}
        for original, moved in zip(nodes, laid):
            if original["pos"] != moved["pos"]:
                moves[original["id"]] = (moved["pos"][0], moved["pos"][1])
        if not moves:
            continue
        changed += 1
        print(f"{path.name}: {len(before)} overlap(s) -> {len(after)}, "
              f"{len(crossed)} crossing box(es) -> {len(still_crossed)}, "
              f"{len(moves)} node(s) moved")
        for node_id, pos in sorted(moves.items()):
            was = next(n["pos"] for n in nodes if n["id"] == node_id)
            print(f"    {node_id:<14} {was} -> [{pos[0]}, {pos[1]}]")
        if after:
            print(f"    !! still overlapping: {after}")
        if still_crossed:
            print(f"    !! boxes still crossing: {still_crossed}")
        if args.write:
            path.write_text(rewrite(text, moves))

    if not changed:
        print("nothing overlaps; no file needs to move")
    elif not args.write:
        print("\n(dry run -- pass --write to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
