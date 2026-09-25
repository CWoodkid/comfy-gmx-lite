"""Preconfigured node chunks -- small subgraphs you drop in and adjust.

Each chunk is a graph fragment with local ids.  The editor renames the ids,
offsets the positions to wherever you dropped it, and leaves the free ports for
you to wire up.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import REGISTRY
from .tutorial_graph import relayout

X, Y = 300, 150

#: Group colours, by what the block of nodes is *for* rather than by where it
#: sits.  Used by the chunks below, by the shipped workflows and by the
#: packaged tutorials, so the same colour means the same thing everywhere:
#: you learn it once and every graph reads the same way afterwards.
COLOR = {
    "input":       "#4a7a4a",   # green  -- getting a structure in and cleaned
    "build":       "#b58b2a",   # olive  -- box, solvent, ions, membrane
    "coarse":      "#6a6aa8",   # indigo -- martinize and everything CG-specific
    "minimise":    "#3f6d7d",   # teal   -- energy minimisation
    "equilibrate": "#3f789e",   # blue   -- NVT, NPT, the ladder
    "production":  "#a1309b",   # purple -- the run you actually keep
    "analysis":    "#b06634",   # brown  -- measuring what came out
    "restart":     "#8a4a4a",   # red    -- surgery on a finished system
    "params":      "#4a4a4a",   # grey   -- settings shared by everything else
}


def _g(title: str, color: str, *node_ids: str) -> Dict[str, Any]:
    """A coloured box around named nodes.

    The box has no bounds here on purpose.  How tall a node renders depends on
    its widgets, which only the browser knows, so the group names its members
    and the editor measures them once they are on the canvas.
    """
    return {"title": title, "color": color, "nodes": list(node_ids)}


def _n(local_id: str, node_type: str, col: int, row: int, **params: Any) -> Dict[str, Any]:
    from .tutorial_graph import as_current
    return as_current({"id": local_id, "type": node_type, "pos": [col * X, row * Y],
                       "params": params})


def _l(a: str, ap: str, b: str, bp: str) -> Dict[str, str]:
    return {"from_node": a, "from_port": ap, "to_node": b, "to_port": bp}


def _minimisation(prefix: str, col: int, row: int, preset: str, deffnm: str,
                  title: str = "", color: str = "") -> Dict[str, Any]:
    groups = [_g(title, color, f"{prefix}mdp", f"{prefix}grompp", f"{prefix}mdrun")] \
        if title else []
    return {
        "groups": groups,
        "nodes": [
            _n(f"{prefix}mdp", "util.mdp", col, row, preset=preset, filename=f"{deffnm}.mdp"),
            _n(f"{prefix}grompp", "gmx.grompp", col + 1, row, output=f"{deffnm}.tpr"),
            _n(f"{prefix}mdrun", "gmx.mdrun", col + 2, row, deffnm=deffnm),
        ],
        "links": [
            _l(f"{prefix}mdp", "mdp", f"{prefix}grompp", "mdp"),
            _l(f"{prefix}grompp", "tpr", f"{prefix}mdrun", "tpr"),
        ],
    }


def _merge(*fragments: Dict[str, Any]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    links: List[Dict[str, str]] = []
    groups: List[Dict[str, Any]] = []
    for fragment in fragments:
        nodes.extend(fragment.get("nodes", []))
        links.extend(fragment.get("links", []))
        groups.extend(fragment.get("groups", []))
    return {"nodes": nodes, "links": links, "groups": groups}


def _stage(prefix: str, col: int, row: int, preset: str, deffnm: str,
           title: str = "", color: str = "") -> Dict[str, Any]:
    """One mdp -> grompp -> mdrun stage, optionally in a coloured box."""
    return _minimisation(prefix, col, row, preset, deffnm, title, color)


CHUNKS: List[Dict[str, Any]] = [
    {
        "id": "solvate_ionise",
        "name": "Topology, PBC box, solvate & ionise",
        "category": "Build",
        "description": "pdb2gmx -> editconf -> solvate -> genion: from a cleaned "
                       "structure to a box of water and ions with a topology to match. "
                       "Pick the force field and water model on the first block; the "
                       "genion block runs its own throwaway grompp, so nothing else has "
                       "to be wired.",
        "graph": {
            "groups": [_g("Topology, box, solvent & ions", COLOR["build"],
                          "top", "box", "solv", "ions")],
            "nodes": [
                _n("top", "gmx.pdb2gmx", 0, 0, forcefield="charmm36-jul2022", water="tip3p",
                   ignh=True),
                _n("box", "gmx.editconf", 1, 0, box_type="dodecahedron", distance=1.2),
                _n("solv", "gmx.solvate", 2, 0, solvent="spc216.gro"),
                _n("ions", "gmx.genion", 3, 0, concentration=0.15, solvent_group="SOL"),
            ],
            "links": [
                _l("top", "structure", "box", "structure"),
                _l("top", "topology", "solv", "topology"),
                _l("box", "structure", "solv", "structure"),
                _l("solv", "structure", "ions", "structure"),
                _l("solv", "topology", "ions", "topology"),
            ],
        },
    },
    {
        "id": "em",
        "name": "Energy minimisation",
        "category": "Run",
        "description": "Steepest descent to clear the clashes that packing leaves behind.",
        "graph": _stage("em_", 0, 0, "em_atomistic", "em",
                          "Energy minimisation", COLOR["minimise"]),
    },
    {
        "id": "nvt",
        "name": "NVT equilibration",
        "category": "Run",
        "description": "Restrained NVT with velocity generation -- brings the thermostat "
                       "to temperature before the box is allowed to move.",
        "graph": _stage("nvt_", 0, 0, "nvt_atomistic", "nvt",
                          "NVT equilibration", COLOR["equilibrate"]),
    },
    {
        "id": "npt",
        "name": "NPT equilibration",
        "category": "Run",
        "description": "Restrained NPT so the density settles before production.",
        "graph": _stage("npt_", 0, 0, "npt_atomistic", "npt",
                          "NPT equilibration", COLOR["equilibrate"]),
    },
    {
        "id": "production",
        "name": "Production MD",
        "category": "Run",
        "description": "The unrestrained production run. It ends at mdrun, which "
                       "hands out the trajectory and the run file that made it, so "
                       "the Standard analysis chunk joins on with two wires.",
        # This used to end with a trjconv putting the molecules back together
        # across the box edge. The Standard analysis chunk begins with the very
        # same block, set the very same way, so anybody doing the obvious thing
        # -- run, then analyse -- read and wrote the whole trajectory twice for
        # no gain. On a 46 GB trajectory off a share that reads at 21 MB/s that
        # is most of an hour.
        #
        # The box fix stayed with the analysis rather than the run, because of
        # how the two go wrong when somebody uses one on its own. A run with no
        # box fix gives a trajectory whose molecules are visibly torn the
        # moment you look at it, and you add one block. An analysis with no box
        # fix gives numbers: a molecule split across the box has an enormous
        # apparent movement, and nothing says so. A fault you can see beats a
        # fault you cannot.
        "graph": _stage("md_", 0, 0, "md_atomistic", "md",
                        "Production MD", COLOR["production"]),
    },
    {
        "id": "em_nvt_npt",
        "name": "Equilibration ladder (EM → NVT → NPT)",
        "category": "Run",
        "description": "The three stages chained, each starting from the previous "
                       "structure and sharing one topology.",
        "graph": _merge(
            _stage("em_", 0, 0, "em_atomistic", "em",
                   "Energy minimisation", COLOR["minimise"]),
            _stage("nvt_", 0, 1, "nvt_atomistic", "nvt",
                   "NVT equilibration", COLOR["equilibrate"]),
            _stage("npt_", 0, 2, "npt_atomistic", "npt",
                   "NPT equilibration", COLOR["equilibrate"]),
            {"nodes": [], "links": [
                _l("em_mdrun", "structure", "nvt_grompp", "structure"),
                _l("nvt_mdrun", "structure", "npt_grompp", "structure"),
                _l("nvt_mdrun", "checkpoint", "npt_grompp", "checkpoint"),
            ]},
        ),
    },
    {
        "id": "martini_run",
        "name": "Martini equilibration & production",
        "category": "Martini",
        "description": "Martini 3 minimisation, restrained equilibration at 5 fs and "
                       "production at 20 fs, semiisotropic throughout.",
        "graph": _merge(
            _stage("cgem_", 0, 0, "em_martini", "em",
                   "CG minimisation", COLOR["minimise"]),
            _stage("cgeq_", 0, 1, "eq_martini", "eq",
                   "CG equilibration", COLOR["equilibrate"]),
            _stage("cgmd_", 0, 2, "md_martini", "md",
                   "CG production", COLOR["production"]),
            {"nodes": [], "links": [
                _l("cgem_mdrun", "structure", "cgeq_grompp", "structure"),
                _l("cgeq_mdrun", "structure", "cgmd_grompp", "structure"),
                _l("cgeq_mdrun", "checkpoint", "cgmd_grompp", "checkpoint"),
            ]},
        ),
    },
    {
        "id": "analysis_basic",
        "name": "Standard analysis",
        "category": "Analysis",
        "description": "Put the molecules back together across the box edge, take "
                       "out the overall tumbling, then RMSD, RMSF and radius of "
                       "gyration off that copy, each one drawn in the graph rather "
                       "than left as a file to go and find. Two wires join it to a "
                       "run: the trajectory and the run file, both from mdrun.",
        "graph": {
            "groups": [_g("Standard analysis", COLOR["analysis"],
                          "pbc", "fit", "rms", "rmsf", "rg",
                          "plot_rms", "plot_rmsf", "plot_rg")],
            "nodes": [
                _n("pbc", "gmx.trjconv", 0, 0, pbc="mol", ur="compact", center=True,
                   groups="Protein\nSystem\n"),
                _n("fit", "gmx.trjconv", 1, 0, pbc="none", fit="rot+trans", center=False,
                   output="traj_fit.xtc", groups="Backbone\nSystem\n"),
                _n("rms", "gmx.rms", 2, 0, groups="Backbone\nBackbone\n"),
                _n("plot_rms", "view.plot", 3, 0),
                _n("rmsf", "gmx.rmsf", 2, 1, groups="Backbone\n", res=True),
                _n("plot_rmsf", "view.plot", 3, 1),
                _n("rg", "gmx.gyrate", 2, 2, sel="Protein", tu="ns"),
                _n("plot_rg", "view.plot", 3, 2),
            ],
            "links": [
                _l("pbc", "traj", "fit", "traj"),
                _l("fit", "traj", "rms", "traj"),
                _l("fit", "traj", "rmsf", "traj"),
                _l("fit", "traj", "rg", "traj"),
                # The run file rides along with the trajectory. Every
                # measurement needs one to know what the particles are, and
                # without this each of them wanted its own wire running back
                # past everything to wherever the run file was built.
                _l("pbc", "tpr", "fit", "tpr"),
                _l("fit", "tpr", "rms", "tpr"),
                _l("fit", "tpr", "rmsf", "tpr"),
                _l("fit", "tpr", "rg", "tpr"),
                _l("rms", "xvg", "plot_rms", "xvg"),
                _l("rmsf", "xvg", "plot_rmsf", "xvg"),
                _l("rg", "xvg", "plot_rg", "xvg"),
            ],
        },
    },
    {
        "id": "analysis_membrane",
        "name": "Membrane checks",
        "category": "Analysis",
        "description": "Density profile along z and a periodic-image check -- the two "
                       "things worth looking at before trusting a bilayer run.",
        "graph": {
            "groups": [_g("Membrane checks", COLOR["analysis"], "dens", "pi", "energy",
                          "plot_dens", "plot_pi", "plot_energy")],
            "nodes": [
                _n("dens", "gmx.density", 0, 0, d="Z", sl=100, groups="System\n"),
                _n("plot_dens", "view.plot", 1, 0),
                _n("pi", "gmx.mindist", 0, 1, pi=True, groups="Protein\n"),
                _n("plot_pi", "view.plot", 1, 1),
                _n("energy", "gmx.energy", 0, 2,
                   terms="Potential\nTemperature\nPressure\nBox-Z\n"),
                _n("plot_energy", "view.plot", 1, 2),
            ],
            "links": [
                _l("dens", "xvg", "plot_dens", "xvg"),
                _l("pi", "xvg", "plot_pi", "xvg"),
                _l("energy", "xvg", "plot_energy", "xvg"),
            ],
        },
    },
]


# Rows are written as indices above; this turns them into pixels that account
# for how tall each node actually renders. Without it a chunk with an mdp node
# in it overlaps its own next row.
for _chunk in CHUNKS:
    relayout(_chunk["graph"]["nodes"])


#: The heading the user's own chunks appear under in the palette.
CUSTOM_SECTION = "Custom chunks"

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG.sub("-", (text or "").strip().lower()).strip("-") or "chunk"


def custom_chunks(settings: Any) -> List[Dict[str, Any]]:
    """Every chunk the user has saved, newest first.

    One file per chunk rather than one index: a chunk is then something you can
    copy to another machine, or delete with rm, and two browser tabs saving at
    once cannot lose each other's work.
    """
    out: List[Dict[str, Any]] = []
    directory = getattr(settings, "chunks_dir", None)
    if directory is None or not Path(directory).is_dir():
        return out
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        graph = data.get("graph") or {}
        if not isinstance(graph.get("nodes"), list):
            continue
        # Saved by the full Comfy-gmx, perhaps, with blocks this one lacks: a
        # chunk with a missing block would land on the canvas with a hole in it.
        if not all(REGISTRY.has(str(node.get("type") or ""))
                   for node in graph["nodes"]):
            continue
        out.append({
            "id": data.get("id") or path.stem,
            "name": data.get("name") or path.stem,
            # The sub-heading inside "Custom chunks". Blank is fine: those land
            # directly under the section.
            "category": data.get("category") or "",
            "description": data.get("description") or "",
            "graph": graph,
            "custom": True,
            "path": str(path),
            "saved": data.get("saved") or path.stat().st_mtime,
        })
    out.sort(key=lambda c: (c["category"].lower(), c["name"].lower()))
    return out


def save_chunk(settings: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Write one user chunk. Saving over the same name replaces it."""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("a chunk needs a name")
    graph = payload.get("graph") or {}
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("a chunk needs at least one node")

    category = str(payload.get("category") or "").strip()
    chunk_id = str(payload.get("id") or "").strip()
    if not chunk_id:
        # The category is part of the id so the same name can exist under two
        # headings without one silently overwriting the other.
        chunk_id = f"custom_{_slug(category)}_{_slug(name)}" if category \
            else f"custom_{_slug(name)}"
    if not chunk_id.startswith("custom_"):
        raise ValueError("only chunks named custom_* can be written here")

    directory = Path(settings.chunks_dir)
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "id": chunk_id,
        "name": name,
        "category": category,
        "description": str(payload.get("description") or "").strip(),
        "graph": {
            "nodes": nodes,
            "links": graph.get("links") or [],
            "groups": graph.get("groups") or [],
        },
        "saved": time.time(),
    }
    (directory / f"{chunk_id}.json").write_text(json.dumps(record, indent=2))
    record["custom"] = True
    record["path"] = str(directory / f"{chunk_id}.json")
    return record


def delete_chunk(settings: Any, chunk_id: str) -> Optional[str]:
    """Remove one user chunk. The built-in ones are not ours to delete."""
    if not chunk_id.startswith("custom_"):
        raise ValueError(f"'{chunk_id}' ships with Comfy-gmx and cannot be deleted")
    path = Path(settings.chunks_dir) / f"{chunk_id}.json"
    if not path.is_file():
        return None
    path.unlink()
    return str(path)


def chunk_list(settings: Any = None) -> List[Dict[str, Any]]:
    """The built-in chunks, then whatever the user has saved."""
    if settings is None:
        return CHUNKS
    return CHUNKS + custom_chunks(settings)
