"""Parsers behind the built-in viewer.

Deliberately dependency-free: a .pdb/.gro reader that decimates large systems
before they reach the browser, and an .xvg reader that keeps the legends GROMACS
writes into the header.  What a file says about residues it does *not* contain
lives next door in :mod:`comfygmx.seqmap`.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .seqmap import (  # noqa: F401 -- re-exported for callers of this module
    _cif_pick, _cif_rows, _cif_value, _classify, _kind_of, _molecules,
    _residue_stream, _safe_int, one_letter, parse_sequence,
)

#: Backbone-ish atom names, kept preferentially when a system has to be thinned.
BACKBONE_NAMES = {"CA", "BB", "P", "C1'", "N", "C", "O"}

ELEMENT_COLORS = {
    "C": "#909090", "N": "#3050f8", "O": "#ff0d0d", "S": "#ffff30",
    "P": "#ff8000", "H": "#e8e8e8", "NA": "#ab5cf2", "CL": "#1ff01f",
    "MG": "#8aff00", "CA": "#3dff00", "ZN": "#7d80b0", "FE": "#e06633",
}

_GRO_LINE = re.compile(r"^\s*(\d+)(.{5})(.{5})\s*(\d+)")


def _element_from_name(name: str, hint: str = "") -> str:
    hint = hint.strip().upper()
    if hint:
        return hint
    name = name.strip().upper()
    if not name:
        return "C"
    if name[:2] in ("NA", "CL", "MG", "ZN", "FE", "CA") and len(name) == 2:
        return name[:2]
    return name[0]


def parse_structure(path: Path, max_atoms: int = 40000) -> Dict[str, Any]:
    """Read a .pdb/.gro into flat arrays the viewer can upload straight to WebGL."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".gro", ".g96"):
        atoms, box = _parse_gro(path)
    else:
        atoms, box = _parse_pdb(path)

    total = len(atoms)
    if total == 0:
        return {"error": f"no atoms found in {path.name}", "n_atoms": 0}

    kept = _decimate(atoms, max_atoms)
    chains: List[str] = []
    for atom in kept:
        if atom["chain"] not in chains:
            chains.append(atom["chain"])

    trace = _backbone_trace(kept)
    return {
        "name": path.name,
        "n_atoms": total,
        "n_shown": len(kept),
        "decimated": len(kept) < total,
        "box": box,
        "chains": chains,
        "x": [round(a["x"], 3) for a in kept],
        "y": [round(a["y"], 3) for a in kept],
        "z": [round(a["z"], 3) for a in kept],
        "element": [a["element"] for a in kept],
        "chain": [a["chain"] for a in kept],
        "resname": [a["resname"] for a in kept],
        "resid": [a["resid"] for a in kept],
        "name_": [a["name"] for a in kept],
        "bfactor": [round(a.get("bfactor", 0.0), 2) for a in kept],
        "trace": trace,
        "colors": ELEMENT_COLORS,
    }


def _pdb_atom(line: str) -> Optional[Dict[str, Any]]:
    """One ATOM/HETATM record, or None if the coordinates are not numbers."""
    try:
        x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
    except ValueError:
        return None
    name = line[12:16].strip()
    return {
        "x": x, "y": y, "z": z,
        "name": name,
        "resname": line[17:20].strip(),
        "chain": (line[21] or " ").strip() or "_",
        "resid": _safe_int(line[22:26]),
        "element": _element_from_name(name, line[76:78]),
        # The B-factor column: how much the atom moved in the crystal, or,
        # when a block has written its own numbers there, a per-residue
        # score such as conservation. The viewer can colour by it.
        "bfactor": _safe_float(line[60:66]),
    }


def _safe_float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_pdb(path: Path) -> Tuple[List[Dict[str, Any]], Optional[List[float]]]:
    atoms: List[Dict[str, Any]] = []
    box: Optional[List[float]] = None
    with path.open(errors="replace") as fh:
        for line in fh:
            if line.startswith("CRYST1"):
                try:
                    box = [float(line[6:15]), float(line[15:24]), float(line[24:33])]
                except ValueError:
                    box = None
                continue
            if line.startswith("ENDMDL"):
                break
            if not line.startswith(("ATOM", "HETATM")):
                continue
            atom = _pdb_atom(line)
            if atom is not None:
                atoms.append(atom)
    return atoms, box


def _parse_gro(path: Path) -> Tuple[List[Dict[str, Any]], Optional[List[float]]]:
    atoms: List[Dict[str, Any]] = []
    box: Optional[List[float]] = None
    with path.open(errors="replace") as fh:
        lines = fh.readlines()
    if len(lines) < 3:
        return atoms, box
    try:
        count = int(lines[1].strip())
    except ValueError:
        return atoms, box
    body = lines[2:2 + count]
    for line in body:
        if len(line) < 44:
            continue
        try:
            # nm in the file, angstrom everywhere else in the viewer
            x = float(line[20:28]) * 10.0
            y = float(line[28:36]) * 10.0
            z = float(line[36:44]) * 10.0
        except ValueError:
            continue
        name = line[10:15].strip()
        atoms.append({
            "x": x, "y": y, "z": z,
            "name": name,
            "resname": line[5:10].strip(),
            "chain": "_",
            "resid": _safe_int(line[0:5]),
            "element": _element_from_name(name),
        })
    tail = lines[2 + count: 3 + count]
    if tail:
        parts = tail[0].split()
        if len(parts) >= 3:
            try:
                box = [float(parts[0]) * 10, float(parts[1]) * 10, float(parts[2]) * 10]
            except ValueError:
                box = None
    return atoms, box


def _decimate(atoms: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Thin a system down, keeping backbone atoms in preference to the rest."""
    if len(atoms) <= limit:
        return atoms
    backbone = [a for a in atoms if a["name"] in BACKBONE_NAMES]
    if len(backbone) >= limit:
        stride = math.ceil(len(backbone) / limit)
        return backbone[::stride]
    remaining = limit - len(backbone)
    others = [a for a in atoms if a["name"] not in BACKBONE_NAMES]
    stride = max(1, math.ceil(len(others) / remaining)) if remaining else len(others) + 1
    return backbone + others[::stride]


def _backbone_trace(atoms: List[Dict[str, Any]]) -> List[List[int]]:
    """Index runs through consecutive CA/BB atoms, one list per chain."""
    runs: List[List[int]] = []
    current: List[int] = []
    last_chain = None
    last_resid = None
    for index, atom in enumerate(atoms):
        if atom["name"] not in ("CA", "BB"):
            continue
        if atom["chain"] != last_chain or (last_resid is not None
                                           and atom["resid"] - last_resid > 5):
            if len(current) > 1:
                runs.append(current)
            current = []
        current.append(index)
        last_chain, last_resid = atom["chain"], atom["resid"]
    if len(current) > 1:
        runs.append(current)
    return runs


# --------------------------------------------------------------------------
# What is in a structure, without running anything

def _grouped(chains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Distinct molecules, each with the chains that carry it, in chain order."""
    groups: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    for chain in chains:
        description = chain.get("molecule") or ""
        if not description:
            continue
        if description not in index:
            index[description] = len(groups)
            groups.append({"description": description, "chains": [],
                           "residues": 0})
        entry = groups[index[description]]
        entry["chains"].append(chain["id"])
        entry["residues"] += chain.get("residues", 0)
    return groups


def parse_composition(path: Path) -> Dict[str, Any]:
    """Chains, residue ranges and molecule species -- the things you have to
    know before you can fill in "keep chains" on a cleaning node.

    Reading it here rather than leaving the user to open the file elsewhere is
    the whole point: the answer is three lines of parsing and it decides what
    every downstream node is configured with.
    """
    path = Path(path)
    if not path.is_file():
        return {"error": f"not a file: {path}"}

    title = ""
    models = 0
    atoms = 0
    suffix = path.suffix.lower()
    if suffix in (".cif", ".mmcif"):
        title = _cif_value(path, "_struct.title")
        seen_models = set()
        picks = None
        for columns, values in _cif_rows(path, "_atom_site"):
            if picks is None:
                picks = _cif_pick(columns, "pdbx_PDB_model_num")
            atoms += 1
            if picks >= 0:
                seen_models.add(values[picks])
        models = max(1, len(seen_models))
    elif suffix in (".gro", ".g96"):
        with path.open(errors="replace") as handle:
            title = handle.readline().strip()
            try:
                atoms = int(handle.readline().strip())
            except ValueError:
                atoms = 0
        models = 1
    else:
        with path.open(errors="replace") as handle:
            for line in handle:
                if line.startswith(("ATOM", "HETATM")):
                    atoms += 1
                elif line.startswith("MODEL"):
                    models += 1
                elif not title and line.startswith(("TITLE", "HEADER", "COMPND")):
                    title = line[10:].strip()
        models = max(models, 1)

    chains: Dict[str, Dict[str, Any]] = {}
    species: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for chain, resid, resname in _residue_stream(path):
        kind = _kind_of(resname)
        entry = chains.get(chain)
        if entry is None:
            entry = chains[chain] = {"id": chain, "residues": 0, "first": resid,
                                     "last": resid, "resnames": set(), "kinds": {}}
            order.append(chain)
        entry["residues"] += 1
        entry["last"] = resid
        entry["first"] = min(entry["first"], resid) if entry["residues"] > 1 else resid
        entry["resnames"].add(resname)
        entry["kinds"][kind] = entry["kinds"].get(kind, 0) + 1
        found = species.get(resname)
        if found is None:
            species[resname] = {"name": resname, "residues": 1, "kind": kind}
        else:
            found["residues"] += 1

    named = _molecules(path)
    out_chains = []
    for chain in order:
        entry = chains[chain]
        sample = sorted(entry["resnames"])
        out_chains.append({
            "id": entry["id"],
            # What the depositor said this chain is. Blank for a file that
            # never carried the records -- a .gro has nowhere to put them.
            "molecule": named.get(entry["id"], ""),
            "residues": entry["residues"],
            "first": entry["first"],
            "last": entry["last"],
            "kind": _classify(entry["kinds"]),
            # What is in it, without listing 19,032 identical names.
            "resnames": sample[:6],
            "distinct": len(sample),
            "breakdown": dict(sorted(entry["kinds"].items(), key=lambda i: -i[1])),
        })

    ranked = sorted(species.values(), key=lambda s: -s["residues"])
    return {
        "name": path.name,
        "path": str(path),
        "title": title[:200],
        "n_atoms": atoms,
        "models": models,
        "chains": out_chains,
        # The same thing the other way round: one entry per distinct molecule
        # with the chains that are it. Twelve chains in a receptor complex are
        # six molecules, and "which letters do I keep" is answered by the
        # shorter list, not by reading a description twelve times.
        "molecules": _grouped(out_chains),
        "species": ranked[:60],
        "n_species": len(ranked),
        "waters": sum(s["residues"] for s in ranked if s["kind"] == "water"),
        "ions": sum(s["residues"] for s in ranked if s["kind"] == "ion"),
        "hetero": [s for s in ranked if s["kind"] == "other"][:40],
    }


# --------------------------------------------------------------------------
# xvg
# --------------------------------------------------------------------------

def parse_xvg(path: Path, max_points: int = 4000) -> Dict[str, Any]:
    """Read an .xvg (or a plain numeric table) with its grace legends."""
    path = Path(path)
    title, xlabel, ylabel = "", "", ""
    legends: List[str] = []
    rows: List[List[float]] = []

    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if line.startswith("@"):
                lowered = line.lower()
                if " title " in lowered:
                    title = _quoted(line)
                elif "xaxis" in lowered and "label" in lowered:
                    xlabel = _quoted(line)
                elif "yaxis" in lowered and "label" in lowered:
                    ylabel = _quoted(line)
                elif re.search(r"@\s*s\d+\s+legend", line):
                    legends.append(_quoted(line))
                continue
            parts = line.split()
            try:
                rows.append([float(p) for p in parts])
            except ValueError:
                continue

    if not rows:
        return {"error": f"no numeric rows in {path.name}", "series": []}

    width = min(len(r) for r in rows)
    stride = max(1, math.ceil(len(rows) / max_points))
    sampled = rows[::stride]
    x = [r[0] for r in sampled]
    series = []
    for column in range(1, width):
        label = legends[column - 1] if column - 1 < len(legends) else f"column {column}"
        series.append({"label": label, "y": [r[column] for r in sampled]})

    return {
        "name": path.name,
        "title": title, "xlabel": xlabel, "ylabel": ylabel,
        "n_rows": len(rows), "n_shown": len(sampled), "stride": stride,
        "x": x, "series": series,
        "stats": [
            {
                "label": s["label"],
                "mean": _mean(s["y"]),
                "sd": _sd(s["y"]),
                "min": min(s["y"]) if s["y"] else 0.0,
                "max": max(s["y"]) if s["y"] else 0.0,
            }
            for s in series
        ],
    }


def _quoted(line: str) -> str:
    match = re.search(r'"(.*)"', line)
    return match.group(1) if match else line.split(None, 2)[-1]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sd(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# --------------------------------------------------------------------------
# mdrun log
# --------------------------------------------------------------------------

def parse_md_log(path: Path, tail_lines: int = 400) -> Dict[str, Any]:
    """Performance numbers and the tail of an mdrun .log."""
    path = Path(path)
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    performance = {}
    for line in lines:
        if line.strip().startswith("Performance:"):
            parts = line.split()
            if len(parts) >= 3:
                performance = {"ns_per_day": parts[1], "hours_per_ns": parts[2]}
    warnings = [ln.strip() for ln in lines if "WARNING" in ln or "Warning" in ln]
    return {
        "name": path.name,
        "performance": performance,
        "warnings": warnings[:50],
        "tail": lines[-tail_lines:],
    }


# --------------------------------------------------------------------------
# gmx dssp
# --------------------------------------------------------------------------

#: What each letter in a dssp assignment file means.  The order is the order
#: they are stacked in the summary plot: helices together, sheets together,
#: everything loose at the end.
DSSP_CODES = (
    ("H", "alpha helix"),
    ("G", "3-10 helix"),
    ("I", "pi helix"),
    ("P", "PP helix"),
    ("E", "beta strand"),
    ("B", "beta bridge"),
    ("T", "turn"),
    ("S", "bend"),
    ("~", "loop"),
)
DSSP_MEANING = dict(DSSP_CODES)
#: Everything that is not an assignment at all.
DSSP_BLANK = {" ", "-", "=", ".", "~", "C", "L"}


def parse_dssp(path: Path, max_frames: int = 600,
               max_residues: int = 900) -> Dict[str, Any]:
    """Read what ``gmx dssp -o`` writes: one line a frame, one letter a residue.

    The file is a picture rather than a table -- which residue was in which
    kind of structure, frame by frame -- and there is nothing in the app that
    can read a picture out of a column of numbers.  So it comes back as the
    matrix itself, thinned to something a canvas can draw, plus the per-frame
    fractions, which is the summary you would otherwise have to run
    ``gmx dssp -num`` a second time to get.
    """
    path = Path(path)
    rows: List[str] = []
    with path.open(errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n").rstrip("\r")
            if not line or line.startswith(("#", "@")):
                continue
            rows.append(line)
    if not rows:
        return {"error": f"no assignments in {path.name}", "frames": []}

    residues = max(len(row) for row in rows)
    if residues < 2:
        return {"error": f"{path.name} does not look like a dssp assignment file",
                "frames": []}

    frame_stride = max(1, math.ceil(len(rows) / max_frames))
    residue_stride = max(1, math.ceil(residues / max_residues))
    # Fractions are counted over every frame and every residue, not over the
    # thinned picture: the summary should not change because the node is small.
    counts: Dict[str, List[int]] = {code: [] for code, _ in DSSP_CODES}
    for row in rows:
        tally: Dict[str, int] = {}
        for letter in row:
            key = "~" if letter in DSSP_BLANK else letter.upper()
            tally[key] = tally.get(key, 0) + 1
        for code, _ in DSSP_CODES:
            counts[code].append(tally.get(code, 0))

    shown = []
    for row in rows[::frame_stride]:
        padded = row.ljust(residues, "~")
        shown.append("".join("~" if c in DSSP_BLANK else c.upper()
                             for c in padded[::residue_stride]))

    present = [code for code, _ in DSSP_CODES if any(counts[code])]
    seen = set("".join(shown))
    for letter in sorted(seen):
        if letter not in DSSP_MEANING and letter != "~":
            present.append(letter)

    total = float(residues) or 1.0
    series = [
        {"code": code, "label": DSSP_MEANING[code],
         "y": [n / total for n in counts[code][::frame_stride]]}
        for code in present if code in DSSP_MEANING
    ]
    return {
        "name": path.name,
        "n_frames": len(rows), "n_residues": residues,
        "frame_stride": frame_stride, "residue_stride": residue_stride,
        "frames": shown,
        "codes": present,
        "legend": [{"code": c, "label": DSSP_MEANING.get(c, c)} for c in present],
        "series": series,
        "summary": [
            {"code": code, "label": DSSP_MEANING[code],
             "mean": _mean([n / total for n in counts[code]])}
            for code in present if code in DSSP_MEANING
        ],
    }


# --------------------------------------------------------------------------
# A trajectory, as a handful of frames
# --------------------------------------------------------------------------

def parse_trajectory(path: Path, max_frames: int = 40,
                     max_atoms: int = 4000) -> Dict[str, Any]:
    """Read a multi-model PDB into one structure and a stack of coordinates.

    The point is to *look* at a run, not to analyse it, so this is deliberately
    cheap: the first model decides the atoms, their names and the backbone
    trace, and every model after it contributes nothing but three numbers per
    atom.  A file whose models disagree about how many atoms they have is a
    file this cannot animate, and it says so rather than drawing nonsense.
    """
    path = Path(path)
    models: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    box: Optional[List[float]] = None
    started = False
    with path.open(errors="replace") as handle:
        for line in handle:
            if line.startswith("CRYST1") and box is None:
                try:
                    box = [float(line[6:15]), float(line[15:24]), float(line[24:33])]
                except ValueError:
                    box = None
            elif line.startswith("MODEL"):
                if started and current:
                    models.append(current)
                current, started = [], True
            elif line.startswith("ENDMDL"):
                if current:
                    models.append(current)
                current, started = [], False
            elif line.startswith(("ATOM", "HETATM")):
                atom = _pdb_atom(line)
                if atom is not None:
                    current.append(atom)
    if current:
        models.append(current)
    if not models:
        return {"error": f"no atoms found in {path.name}", "n_frames": 0}

    widths = {len(m) for m in models}
    if len(widths) > 1:
        return {"error": f"{path.name} has models of different sizes "
                         f"({min(widths)}-{max(widths)} atoms), so it cannot be "
                         "played as one trajectory", "n_frames": len(models)}

    stride = max(1, math.ceil(len(models) / max_frames))
    shown = models[::stride]

    # Whatever survives decimation in the first frame is what every frame
    # contributes, so the atoms line up across the stack.
    first = shown[0]
    for index, atom in enumerate(first):
        atom["_i"] = index
    kept = _decimate(first, max_atoms)
    indices = [atom["_i"] for atom in kept]
    for atom in first:
        atom.pop("_i", None)

    chains: List[str] = []
    for atom in kept:
        if atom["chain"] not in chains:
            chains.append(atom["chain"])

    frames = []
    for model in shown:
        frames.append({
            "x": [round(model[i]["x"], 2) for i in indices],
            "y": [round(model[i]["y"], 2) for i in indices],
            "z": [round(model[i]["z"], 2) for i in indices],
        })

    return {
        "name": path.name,
        "n_frames": len(models), "n_shown": len(shown), "frame_stride": stride,
        "n_atoms": len(first), "n_atoms_shown": len(kept),
        "decimated": len(kept) < len(first),
        "box": box, "chains": chains,
        "x": frames[0]["x"], "y": frames[0]["y"], "z": frames[0]["z"],
        "element": [a["element"] for a in kept],
        "chain": [a["chain"] for a in kept],
        "resname": [a["resname"] for a in kept],
        "resid": [a["resid"] for a in kept],
        "name_": [a["name"] for a in kept],
        "trace": _backbone_trace(kept),
        "colors": ELEMENT_COLORS,
        "frames": frames,
    }


# --------------------------------------------------------------------------
# Picking a smaller box by eye
# --------------------------------------------------------------------------

#: Residue names that are water or a plain ion. These are the only things a box
#: can be cut through without consequence: throwing a water molecule away costs
#: nothing, and the gap fills itself in within a few picoseconds.
SOLVENT_RESNAMES = {
    "W", "WF", "SOL", "HOH", "TIP3", "TIP3P", "TIP4P", "SPC", "SPCE", "WAT",
    "ION", "NA", "CL", "NA+", "CL-", "K", "K+", "MG", "CA", "ZN", "CLA", "SOD",
    "POT", "PW", "CAL", "MG2", "IB+",
}

#: Lipid names, for telling "this cuts through the membrane" from "this cuts
#: through the protein". The two need different answers: a membrane can be
#: built again at the smaller size with the same mixture, and a protein cannot
#: be made smaller at all.
#:
#: Names first, then a shape rule for the ones not on the list. Martini and
#: CHARMM lipid names are four or five characters ending in a two-letter head
#: group code, which catches the great majority of the ones nobody has thought
#: to list here.
LIPID_RESNAMES = {
    "CHOL", "CHL1", "ERGO", "DPSM", "PSM", "PPCS", "DBSM", "BNSM",
    "POP1", "POP2", "POP3", "PIP1", "PIP2", "PIP3", "SAPI", "PAPI", "PUPI",
    "DPG1", "DPG3", "DPGS", "DPCE", "PNCE", "XNCE", "DXCE",
    "CARD", "CDL0", "CDL1", "CDL2", "TOCL", "LIPA", "REMP", "LPS",
    "DOTAP", "DDAB", "SDPE", "PADG", "PVDG", "TOG", "TRIO",
}

#: The head-group codes at the end of a lipid name.
LIPID_TAILS = ("PC", "PE", "PS", "PG", "PA", "PI", "SM", "CL", "DG", "TG",
               "PP", "PN", "CE")

AXES = ("x", "y", "z")


def _is_lipid(resname: str) -> bool:
    name = resname.upper()
    if name in LIPID_RESNAMES:
        return True
    if len(name) in (4, 5) and name[-2:] in LIPID_TAILS:
        # ...but not the ions and waters that happen to end the same way.
        return name not in SOLVENT_RESNAMES
    return False


def _box_class(resname: str, droppable) -> str:
    """Which of the three kinds this residue is, for the box picture."""
    name = resname.upper()
    if name in droppable:
        return "solvent"
    if _is_lipid(name):
        return "membrane"
    return "structure"


# --------------------------------------------------------------------------
# Choosing a box to put a molecule in
# --------------------------------------------------------------------------

#: How many waters `gmx solvate` actually puts into a cubic nanometre of empty
#: box.  Liquid water is 33.4 molecules per nm3; solvate leaves a little room
#: at every wall and around the solute, and comes out at 32.3.  Measured, not
#: looked up -- see the note on SOLUTE_NM3_PER_ATOM.
WATERS_PER_NM3 = 32.3

#: How much room one atom of the solute takes away from the water, in nm3.
#:
#: These two numbers were fitted to four real runs on lysozyme -- a cube at
#: -d 1.0 and 1.2, a dodecahedron and an octahedron -- where solvate put in
#: 10,644, 12,596, 7,339 and 8,097 waters.  The estimate below is within half a
#: percent of every one of them.  It is still an estimate and is labelled as
#: one; what it is for is showing that one box shape costs a third more water
#: than another, which is a difference nobody should have to run twice to see.
SOLUTE_NM3_PER_ATOM = 0.0080

#: The volume of each box shape, as a fraction of the cube that has the same
#: minimum image distance.  Measured from what `gmx editconf` actually writes,
#: not looked up: for a solute 5.0101 nm across at -d 1.0 it builds a 7.01008
#: nm cube, a dodecahedron of 7.01008 x 7.01008 x 4.95687, and an octahedron of
#: 7.01008 x 6.60917 x 5.72371.
BOX_SHAPES: Dict[str, Dict[str, Any]] = {
    "cubic": {"volume": 1.0, "label": "cube"},
    "triclinic": {"volume": 1.0, "label": "triclinic (a cube, unless you set one yourself)"},
    "dodecahedron": {"volume": 0.7071, "label": "rhombic dodecahedron"},
    "octahedron": {"volume": 0.7698, "label": "truncated octahedron"},
}


def _hull_candidates(points: List[Tuple[float, float, float]],
                     bins: int = 24) -> List[Tuple[float, float, float]]:
    """The atoms most likely to be the outermost ones, cheaply.

    The two atoms furthest apart in a molecule are both on its outside.  Every
    pair is far too many to try -- ten thousand atoms is fifty million pairs --
    so the sky around the middle of the molecule is divided into a grid of
    directions and only the atom furthest out in each direction is kept.  That
    leaves a few hundred, which can then be compared with every other one.

    This is a very good approximation and not a proof: an atom that is furthest
    out in no direction cannot be one of the two, so nothing that matters is
    thrown away unless two directions land in the same square.  With 24 by 24
    squares that does not happen for anything protein-shaped.
    """
    if len(points) <= 400:
        return list(points)
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    cz = sum(p[2] for p in points) / n
    best: Dict[Tuple[int, int], Tuple[float, Tuple[float, float, float]]] = {}
    for point in points:
        dx, dy, dz = point[0] - cx, point[1] - cy, point[2] - cz
        far = dx * dx + dy * dy + dz * dz
        if far <= 0.0:
            continue
        length = math.sqrt(far)
        # Which way it lies, as a square on the sky: how far up, and around.
        row = int((dz / length + 1.0) * 0.5 * (bins - 1))
        col = int((math.atan2(dy, dx) + math.pi) / (2 * math.pi) * (bins - 1))
        key = (row, col)
        found = best.get(key)
        if found is None or far > found[0]:
            best[key] = (far, point)
    return [entry[1] for entry in best.values()]


def solute_span(points: List[Tuple[float, float, float]]) -> Dict[str, Any]:
    """How far apart the two furthest atoms are, and which they are.

    This one number decides the box.  `gmx editconf -d` builds a box whose
    smallest measurement is this distance plus twice the gap you asked for --
    so a long thin molecule needs a big box however thin it is, which is the
    thing that surprises people about their first membrane protein.
    """
    candidates = _hull_candidates(points)
    best = 0.0
    ends: Tuple[Tuple[float, float, float], Tuple[float, float, float]] = ((0, 0, 0), (0, 0, 0))
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            dx = first[0] - second[0]
            dy = first[1] - second[1]
            dz = first[2] - second[2]
            far = dx * dx + dy * dy + dz * dz
            if far > best:
                best = far
                ends = (first, second)
    return {"diameter": round(math.sqrt(best), 4),
            "from": [round(v, 3) for v in ends[0]],
            "to": [round(v, 3) for v in ends[1]],
            "considered": len(candidates)}


def box_shapes(diameter: float, distance: float, n_solute: int = 0) -> List[Dict[str, Any]]:
    """What each box shape would cost, for one molecule and one gap.

    Every shape is built on the same edge length -- how far apart the two
    furthest atoms are, plus the gap at each end -- and then differs only in
    how much of the corner is cut off.  Cutting the corners off is free: the
    molecule cannot reach into them anyway, and every nanometre of them would
    otherwise have to be filled with water and simulated.
    """
    edge = diameter + 2.0 * max(0.0, distance)
    cube = edge ** 3
    taken = n_solute * SOLUTE_NM3_PER_ATOM
    out = []
    for name, shape in BOX_SHAPES.items():
        volume = cube * shape["volume"]
        out.append({
            "type": name,
            "label": shape["label"],
            "edge": round(edge, 4),
            "volume": round(volume, 1),
            "waters": max(0, int(round((volume - taken) * WATERS_PER_NM3))),
            "share": shape["volume"],
        })
    return out


def _jacobi3(a: List[List[float]]) -> Tuple[List[float], List[List[float]]]:
    """The three special directions of a 3x3 symmetric table of numbers.

    Any cloud of points has three directions at right angles to each other
    that describe how it is spread out: the one it reaches furthest along, the
    one it reaches least far along, and the one in between.  Finding them is a
    standard piece of arithmetic (Jacobi's method): repeatedly pick the largest
    off-diagonal entry and rotate it away, until only the diagonal is left.

    Written out here rather than borrowed from numpy so this panel works on any
    machine, with no extra package to install.  Three by three converges in a
    handful of turns.

    Gives back the three numbers on the diagonal and the three directions, one
    per column.
    """
    m = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(60):
        # largest entry that is not on the diagonal
        p_, q_ = 0, 1
        biggest = abs(m[0][1])
        for i, j in ((0, 2), (1, 2)):
            if abs(m[i][j]) > biggest:
                biggest, p_, q_ = abs(m[i][j]), i, j
        if biggest < 1e-12:
            break
        theta = (m[q_][q_] - m[p_][p_]) / (2.0 * m[p_][q_])
        sign = 1.0 if theta >= 0 else -1.0
        t = sign / (abs(theta) + math.sqrt(theta * theta + 1.0))
        c = 1.0 / math.sqrt(t * t + 1.0)
        s = t * c
        for k in range(3):
            mkp, mkq = m[k][p_], m[k][q_]
            m[k][p_] = c * mkp - s * mkq
            m[k][q_] = s * mkp + c * mkq
        for k in range(3):
            mpk, mqk = m[p_][k], m[q_][k]
            m[p_][k] = c * mpk - s * mqk
            m[q_][k] = s * mpk + c * mqk
        for k in range(3):
            vkp, vkq = v[k][p_], v[k][q_]
            v[k][p_] = c * vkp - s * vkq
            v[k][q_] = s * vkp + c * vkq
    return [m[i][i] for i in range(3)], v


def principal_extents(points: List[Tuple[float, float, float]]) -> Dict[str, Any]:
    """How far the molecule reaches along its own three directions, in nm.

    A long molecule lying across the corner of the file looks enormous when you
    measure it along x, y and z, because you are measuring its diagonal three
    times.  Turn it so its long direction lies along one axis and the other two
    measurements collapse -- for a 40 x 10 x 3 nm slab lying askew, from
    40 x 17 x 19 down to the 40 x 10 x 3 it really is.

    ``gmx editconf -princ`` does exactly this turn, and puts the longest
    direction on x, the middle one on y and the shortest on z.  That was
    checked against editconf on a slab of known size, not assumed.

    Every atom counts the same here, where editconf weighs them by mass.  For
    the directions of a protein the difference is small, and this is a preview:
    the numbers editconf writes are the ones that count.
    """
    n = len(points)
    if n < 3:
        return {}
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    cz = sum(p[2] for p in points) / n
    cov = [[0.0] * 3 for _ in range(3)]
    for px, py, pz in points:
        d = (px - cx, py - cy, pz - cz)
        for i in range(3):
            for j in range(3):
                cov[i][j] += d[i] * d[j]
    for i in range(3):
        for j in range(3):
            cov[i][j] /= n
    _, vectors = _jacobi3(cov)
    axes = [[vectors[0][k], vectors[1][k], vectors[2][k]] for k in range(3)]
    spread = []
    for axis in axes:
        values = [p[0] * axis[0] + p[1] * axis[1] + p[2] * axis[2] for p in points]
        spread.append((max(values) - min(values), axis))
    # Longest first, which is the order editconf leaves them in: x, y, z.
    spread.sort(key=lambda item: -item[0])
    return {
        "lengths": [round(item[0], 3) for item in spread],
        "axes": [[round(v, 4) for v in item[1]] for item in spread],
    }


def box_around(path: Path, max_points: int = 4000) -> Dict[str, Any]:
    """Everything needed to choose a box round one molecule, by eye.

    Reads the structure, works out how far across it is and where it sits, and
    thins the atoms down to a scatter small enough to draw.  Water and ions are
    left out of the measurement: a box is chosen to fit the thing being
    studied, and there is no point measuring water that is about to be thrown
    away and poured back in.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".gro", ".g96"):
        atoms, box = _parse_gro(path)
    else:
        atoms, box = _parse_pdb(path)
    if not atoms:
        return {"error": f"no atoms found in {path.name}", "n_atoms": 0}

    solute = [a for a in atoms if _box_class(a["resname"], SOLVENT_RESNAMES) != "solvent"]
    dropped = len(atoms) - len(solute)
    if not solute:
        return {"error": "everything in that file is water or ions, so there is "
                         "nothing to put a box around",
                "n_atoms": len(atoms)}

    # Ångström in the file, nanometres everywhere here: GROMACS works in nm and
    # every number on this panel has to be the number you would type.
    points = [(a["x"] / 10.0, a["y"] / 10.0, a["z"] / 10.0) for a in solute]
    span = solute_span(points)
    # Whether the hydrogens are here yet. A deposited X-ray structure has none,
    # pdb2gmx adds them, and they stick out further than anything else -- so a
    # box chosen from the bare file comes out a few percent small. Worth saying
    # rather than silently being 3% out.
    hydrogens = sum(1 for a in solute if (a.get("element") or "").upper() == "H")

    extent = {}
    for index, name in enumerate(AXES):
        values = [p[index] for p in points]
        extent[name] = [round(min(values), 3), round(max(values), 3)]

    step = max(1, len(points) // max_points)
    thin = points[::step]
    return {
        "name": path.name,
        "n_atoms": len(atoms),
        "n_solute": len(solute),
        "n_solvent": dropped,
        "span": span,
        "extent": extent,
        "centre": {name: round((extent[name][0] + extent[name][1]) / 2, 3)
                   for name in AXES},
        # Both parsers hand the box back in angstrom; everything on this panel
        # is in nanometres, because that is what GROMACS takes and what the
        # user will type.
        "box": [round(v / 10.0, 4) for v in box] if box else None,
        # How big it is once it has been turned to lie along the axes, which
        # is what makes a hand-set box worth having for a long molecule.
        "aligned": principal_extents(points),
        "solute_nm3": round(len(solute) * SOLUTE_NM3_PER_ATOM, 1),
        "hydrogens": hydrogens,
        "points": {
            "xy": [[round(p[0], 2), round(p[1], 2)] for p in thin],
            "xz": [[round(p[0], 2), round(p[2], 2)] for p in thin],
        },
        "waters_per_nm3": WATERS_PER_NM3,
    }
