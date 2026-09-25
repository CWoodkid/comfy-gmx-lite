#!/usr/bin/env python3
"""Regenerate workflows/ from the chunk fragments and the tutorial catalogue.

    python3 tools/export_workflows.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comfygmx.chunks import CHUNKS            # noqa: E402
from comfygmx.registry import REGISTRY        # noqa: E402
from comfygmx.tutorials import TUTORIALS      # noqa: E402
from comfygmx.tutorial_graph import relayout  # noqa: E402

OUT = ROOT / "workflows"
BY_ID = {chunk["id"]: chunk for chunk in CHUNKS}


def compose(*chunk_ids, extra_links=(), overrides=None, row_gap=260):
    """Stack chunks vertically, dropping duplicated nodes and joining the rest."""
    nodes, links, groups, seen, dy = [], [], [], set(), 0
    for chunk_id in chunk_ids:
        chunk = BY_ID[chunk_id]
        dropped = set()
        for node in chunk["graph"]["nodes"]:
            if node["id"] in seen:
                dropped.add(node["id"])
                continue
            seen.add(node["id"])
            nodes.append({
                "id": node["id"], "type": node["type"],
                "pos": [node["pos"][0], node["pos"][1] + dy],
                "params": dict(node["params"]),
            })
        for edge in chunk["graph"]["links"]:
            if edge["from_node"] in dropped or edge["to_node"] in dropped:
                continue
            links.append(dict(edge))
        # A group names its members and the editor measures them, so stacking
        # the chunks needs no arithmetic here -- only the members that survived
        # de-duplication.
        for group in chunk["graph"].get("groups") or []:
            members = [n for n in group["nodes"] if n not in dropped]
            if members:
                groups.append(dict(group, nodes=members))
        dy += max((n["pos"][1] for n in chunk["graph"]["nodes"]), default=0) + row_gap
    links.extend(dict(edge) for edge in extra_links)

    unique, keys = [], set()
    for edge in links:
        key = (edge["from_node"], edge["from_port"], edge["to_node"], edge["to_port"])
        if key not in keys:
            keys.add(key)
            unique.append(edge)
    for node_id, params in (overrides or {}).items():
        for node in nodes:
            if node["id"] == node_id:
                node["params"].update(params)
    # Stacking chunks leaves the rows wherever the arithmetic put them; this
    # spaces them by how tall the nodes really are.
    relayout(nodes)
    return {"version": 1, "nodes": nodes, "links": unique, "groups": groups}


def validate(name: str, graph: dict) -> None:
    types = {n["id"]: n["type"] for n in graph["nodes"]}
    for group in graph.get("groups") or []:
        assert group.get("title"), f"{name}: a group with no title"
        assert group.get("nodes") or group.get("bounds"), \
            f"{name}: group '{group['title']}' names neither members nor bounds"
        for member in group.get("nodes") or []:
            assert member in types, \
                f"{name}: group '{group['title']}' names unknown node '{member}'"
    for node in graph["nodes"]:
        assert REGISTRY.has(node["type"]), f"{name}: unknown type {node['type']}"
        known = {p.name for p in REGISTRY.get(node["type"]).all_params()}
        for key in node.get("params", {}):
            assert key in known, f"{name}: {node['id']} has unknown parameter '{key}'"
    for edge in graph["links"]:
        src = REGISTRY.get(types[edge["from_node"]])
        dst = REGISTRY.get(types[edge["to_node"]])
        assert edge["from_port"] in {p.name for p in src.outputs}, f"{name}: {edge}"
        assert edge["to_port"] in {p.name for p in dst.inputs}, f"{name}: {edge}"


def write(path: Path, graph: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, indent=2) + "\n")
    print(f"{path.relative_to(ROOT)}: {len(graph['nodes'])} nodes, "
          f"{len(graph['links'])} links, {len(graph.get('groups') or [])} groups")


def main() -> int:
    # The membrane chunk has no trajectory block of its own: stacked under
    # the basic one, its density blocks read the trajectory that one tidies.
    from_pbc = [{"from_node": "pbc", "from_port": port, "to_node": block, "to_port": port}
                for block in ("dens", "pi") for port in ("traj", "tpr")]
    examples = {
        "analysis-standard": compose("analysis_basic", "analysis_membrane",
                                     extra_links=from_pbc),
    }
    for name, graph in examples.items():
        validate(name, graph)
        write(OUT / f"{name}.json", graph)

    for tutorial in TUTORIALS:
        graph = tutorial.get("graph")
        if not graph:
            continue
        payload = {"version": 1, "nodes": graph["nodes"], "links": graph["links"],
                   "groups": graph.get("groups") or []}
        validate(tutorial["id"], payload)
        # Letters, digits and dashes only. Taking out just spaces and colons
        # left punctuation in the file name -- one title with a comma in it
        # produced "...-a-run-that-stopped,-and-...json", which is a nuisance
        # to type and worse to quote in a shell.
        slug = re.sub(r"-{2,}", "-",
                      re.sub(r"[^a-z0-9]+", "-", tutorial["name"].lower())).strip("-")
        # The collections number independently, so the collection has to be
        # part of the name or gmx 1 and martini 1 would overwrite each other.
        collection = tutorial.get("collection", "gmx")
        write(OUT / "tutorials" / f"{collection}-{tutorial['number']:02d}-{slug}.json",
              payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
