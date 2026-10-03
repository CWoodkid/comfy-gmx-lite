"""Nodes that show you something instead of computing something.

A preview node earns its place by being cheap.  It stages the structure it is
given, prints two lines about it, and hands the same file straight on -- so
dropping one into the middle of a chain costs a hard link and changes nothing
downstream.  The drawing happens in the browser, from the same parser the
Viewer tab uses.

Everything about *how* it is drawn -- points or trace, colour, size -- is node
display state, not a parameter.  Parameters go into the node's cache signature,
and switching from points to a backbone trace must not re-run the graph.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import List, Tuple

from .base import (
    Node, NodeError, Param, Plan, PlanContext, Port, local_path,
)

CATEGORY = "View"


def _ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th. "every 3th frame" is a typo nobody typed."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"

#: What the browser-side parser can actually draw.  Anything else still runs;
#: the node just says so in its caption instead of drawing.
_DRAWABLE = (".pdb", ".gro", ".g96", ".ent")
#: The plot reader takes anything that is a column of numbers, whatever it is
#: called; these are the names it actually meets.
_PLOTTABLE = (".xvg", ".dat", ".csv", ".txt", ".agr")


class PreviewStructureNode(Node):
    type = "view.structure"
    title = "Preview structure"
    category = CATEGORY
    color = "#3f6d7d"
    tool = "shell"
    preview_kind = "structure"
    preview_port = "structure"
    description = (
        "Draws whatever structure is wired into it, inside the node. Useful for "
        "checking at a glance that a step did what you expected. It passes the "
        "structure through unchanged, so it can sit between two steps without "
        "affecting either. Drag the picture to turn it, scroll to zoom, drag the "
        "node's corner to make it bigger."
    )
    inputs = (Port("structure", "structure", "structure", optional=True),)
    outputs = (Port("structure", "structure", "structure"),)
    params = (
        Param("path", "file", "Or a file", "",
              placeholder="only used when nothing is wired in",
              help="Lets the node stand on its own as a way of looking at a file "
                   "on disk. A connected input always wins."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        name = ctx.inp("structure")
        if name:
            if ctx.pstr("path"):
                plan.notes.append("the wired-in structure is used, not the file below")
            # No copy: staging already put the file in this work directory, and
            # a preview that duplicates an 800k-bead .gro to look at it is not a
            # preview. The step below is the whole cost of the node.
            plan.sh(
                f"ls -l {shlex.quote(name)} && head -n 2 {shlex.quote(name)}",
                label=f"preview {name}",
            )
        else:
            raw = ctx.pstr("path")
            if not raw:
                raise NodeError("nothing to preview: wire a structure in, or set a file")
            source = Path(local_path(raw))
            if not source.is_absolute() and ctx.settings is not None:
                candidate = ctx.settings.uploads_dir / raw
                if candidate.exists():
                    source = candidate
            if not ctx.dry and not source.exists():
                raise NodeError(f"file does not exist: {source}")
            name = source.name
            plan.bring(source, name)

        if not name.lower().endswith(_DRAWABLE):
            plan.notes.append(
                f"'{Path(name).suffix or name}' is not one of {', '.join(_DRAWABLE)}; "
                "it runs, but the node cannot draw it"
            )
        plan.outputs["structure"] = name
        return plan


class PreviewPlotNode(Node):
    type = "view.plot"
    title = "Preview plot"
    category = CATEGORY
    color = "#3f6d7d"
    tool = "shell"
    preview_kind = "plot"
    preview_port = "xvg"
    description = (
        "Draws the curve of whatever analysis is wired into it, inside the node. "
        "Every analysis node hands out an .xvg and until now nothing in the graph "
        "read one -- you could open it in the Files tab, but the graph itself "
        "ended in a row of loose ends.\n\n"
        "It passes the data straight through, so it can sit between two steps "
        "without affecting either, and it reads anything that is a column of "
        "numbers with GROMACS legends on top. Hover for values, drag the node's "
        "corner to make it bigger."
    )
    inputs = (Port("xvg", "xvg", "data", optional=True),)
    outputs = (Port("xvg", "xvg", "data"),)
    params = (
        Param("path", "file", "Or a file", "",
              placeholder="only used when nothing is wired in",
              help="Lets the node stand on its own as a way of looking at a file "
                   "on disk. A connected input always wins."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        name = ctx.inp("xvg")
        if name:
            if ctx.pstr("path"):
                plan.notes.append("the wired-in data is used, not the file below")
            plan.sh(f"wc -l {shlex.quote(name)}", label=f"preview {name}")
        else:
            raw = ctx.pstr("path")
            if not raw:
                raise NodeError("nothing to plot: wire an analysis in, or set a file")
            source = Path(local_path(raw))
            if not source.is_absolute() and ctx.settings is not None:
                candidate = ctx.settings.uploads_dir / raw
                if candidate.exists():
                    source = candidate
            if not ctx.dry and not source.exists():
                raise NodeError(f"file does not exist: {source}")
            name = source.name
            plan.bring(source, name)

        if not name.lower().endswith(_PLOTTABLE):
            plan.notes.append(
                f"'{Path(name).suffix or name}' is an unusual name for a data file; "
                "it is read as columns of numbers anyway"
            )
        plan.outputs["xvg"] = name
        return plan


class PreviewTrajectoryNode(Node):
    type = "view.trajectory"
    title = "Preview trajectory"
    category = CATEGORY
    color = "#3f6d7d"
    tool = "gmx"
    extra_command = "gmx trjconv"
    preview_kind = "trajectory"
    preview_port = "frames"
    description = (
        "A rough look at a run: wire a trajectory and its tpr in and it plays "
        "the motion inside the node.\n\n"
        "It is deliberately cheap, and cheap is the point -- it pulls a few "
        "dozen evenly spaced frames of one selection out with trjconv rather "
        "than trying to be a trajectory viewer. Enough to see whether the "
        "protein stayed folded, whether it left the box, whether the membrane "
        "held together. For anything you would measure, use the analysis nodes.\n\n"
        "The frames it takes are written out as a multi-model PDB, so the same "
        "file opens in VMD or PyMOL if the rough look raises a question. That "
        "file is uncompressed text and it adds up -- 200 frames of a 13000-atom "
        "selection is 195 MB -- so take fewer frames of a smaller selection "
        "than you would for analysis."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-trjconv.html"
    inputs = (
        Port("traj", "traj", "trajectory"),
        Port("tpr", "tpr", "tpr"),
        Port("index", "index", "index", optional=True),
    )
    outputs = (Port("frames", "structure", "frames"),)
    params = (
        Param("mode", "choice", "Which frames", "every Nth",
              choices=["every Nth", "about this many"],
              help="'every Nth' is one trjconv call and starts immediately. "
                   "'about this many' has to count the frames first, and "
                   "counting means reading the whole trajectory -- half an hour "
                   "for a 46 GB file on a network share. Worth it when you do "
                   "not know how long the run is; not worth it twice."),
        Param("skip", "int", "Take every", 25, min=1, max=100000,
              help="Every Nth frame, counted in frames and not in time, so it "
                   "costs nothing to work out. There is no good default for "
                   "every run -- 25 is a few dozen pictures out of a thousand "
                   "frames and forty out of a thousand-and-one -- so look at "
                   "what it wrote and change it once."),
        Param("frames", "int", "How many frames", 30, min=2, max=250,
              help="Only used by 'about this many'. Thirty is enough to see a "
                   "motion; the browser thins it again above sixty."),
        Param("sel", "str", "Selection", "Protein", form="gmx.pick_groups",
              help="Which part of the system to show: the name of a group, or "
                   "several names with commas between them, such as 'Protein, "
                   "Ion'. 'Protein' for a fold, 'System' to see everything -- "
                   "which for a solvated run is mostly water. 'Fill this in "
                   "with a form…' lists every group this system has, with how "
                   "many atoms each holds, and lets you tick several."),
        Param("pbc", "choice", "Periodic boundary", "mol",
              choices=["mol", "atom", "whole", "nojump", "none", "lump"],
              help="'mol' keeps molecules in one piece, which is what makes a "
                   "protein stop exploding across the box edge. 'lump' is for "
                   "one lump in a box of gas or water -- a drop, a micelle: it "
                   "keeps molecules in one piece too, and then moves every "
                   "frame so that the lump sits in the middle of the box, so "
                   "the box edge never draws it cut in two. 'Centre the "
                   "selection' cannot do that on its own: the ordinary middle "
                   "of a lump cut in two lies in the gap between the parts."),
        Param("center", "bool", "Centre the selection", True,
              help="Puts the selection in the middle of the box, so it does not "
                   "walk out of view over the run."),
        Param("begin", "float", "-b (ps)", 0.0, advanced=True),
        Param("end", "float", "-e (ps)", 0.0, advanced=True),
        Param("size_limit", "int", "Stop above (MB)", 200, min=0, max=20000,
              advanced=True,
              help="A frame of a big selection is a lot of text: 200 frames of "
                   "13000 atoms is 195 MB of PDB, written into the run "
                   "directory and kept. Above this the node takes fewer frames "
                   "instead, and says so. 0 turns the limit off."),
        Param("output", "str", "Output name", "frames.pdb", advanced=True),
    )

    #: One PDB ATOM line is 81 bytes, and a model costs two more lines.
    BYTES_PER_ATOM_LINE = 81

    @staticmethod
    def _groups(text: str) -> List[str]:
        """The group names in the Selection box: one, or several split by commas."""
        return [name.strip() for name in str(text).split(",") if name.strip()]

    @staticmethod
    def _pick(plan: Plan, chosen: List[str], tpr: str, index: str) -> Tuple[str, str]:
        """The one group trjconv is asked for, and the index file it is in.

        One group and no index file is what this block always did, and it is
        left exactly as it was. Otherwise two steps come first.

        * With an index file wired in, trjconv would see only that file's
          groups, and "System" would not be found. So the file's groups and
          the system's own go into one file, the wired ones first, so a group
          the file names itself wins over the standard one of the same name.
        * With several groups, gmx select joins them into one: trjconv writes
          a single group, and nothing in between would do.
        """
        for name in chosen:
            if '"' in name:
                raise NodeError(f'a group name cannot hold a double quote ("): {name}')
        if index:
            # The system's own groups, as make_ndx lists them when told to
            # quit at once; then the wired file's, and the standard ones it
            # does not already have.
            plan.sh("printf 'q\\n' | {cmd} make_ndx -f " + shlex.quote(tpr)
                    + " -o standard.ndx > /dev/null", tool="gmx",
                    label="the system's own groups")
            plan.sh("awk '/^\\[/ { name = $0; gsub(/^\\[ *| *\\]$/, \"\", name); "
                    "keep = !(name in seen); seen[name] = 1 } keep' "
                    + shlex.quote(index) + " standard.ndx > groups.ndx",
                    label="every group in one file")
            index = "groups.ndx"
        if len(chosen) == 1:
            return chosen[0], index
        joined = "_".join(chosen)
        select = ["select", "-s", tpr, "-on", "shown.ndx", "-select",
                  f'"{joined}" ' + " or ".join(f'group "{name}"' for name in chosen)]
        if index:
            select[3:3] = ["-n", index]
        plan.sh("{cmd} " + " ".join(shlex.quote(a) for a in select), tool="gmx",
                label=f"{', '.join(chosen)} joined into one group")
        plan.notes.append(f"shows {len(chosen)} groups together, as one group "
                          f"called {joined}")
        return joined, "shown.ndx"

    @staticmethod
    def _facts(ctx: PlanContext, traj: str) -> dict:
        """What is already known about this trajectory, if anything.

        Only what is *known* -- reading a 46 GB trajectory to find out takes
        half an hour, and a node building its plan is not the place for that.
        The Files tab is where a scan is asked for, and once it has been the
        answer is here for good.
        """
        settings = getattr(ctx, "settings", None)
        raw = ctx.raw("traj")
        source = ""
        if isinstance(raw, dict):
            source = str(raw.get("path") or "")
        elif isinstance(raw, str):
            source = raw
        if not settings or not source:
            return {}
        try:
            from .. import facts
            return facts.known(settings, source) or {}
        except Exception:  # noqa: BLE001 - a fact nobody has is not an error
            return {}

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output", "frames.pdb") or "frames.pdb"
        if not out.lower().endswith((".pdb", ".ent")):
            raise NodeError("the frames have to go into a PDB: it is the only "
                            "format that holds several models in one file")
        sel = ctx.pstr("sel", "Protein") or "Protein"
        traj, tpr = ctx.require("traj"), ctx.require("tpr")
        centre = ctx.pbool("center", True)

        # '{cmd}' and not a literal 'gmx': the step has to go through the tool
        # the toolbox resolved, both so GMXRC is sourced before it runs and so
        # an installation whose binary is called gmx_mpi still gets used. A
        # shell step that spells the binary out runs whatever is on PATH, which
        # here was Ubuntu's /usr/bin/gmx 2021.4 reading a 2025.4 tpr -- and
        # what that produces is "listRanges does not have a first element with
        # value 0", which says nothing about versions at all.
        # 'lump' is not trjconv's: trjconv keeps the molecules whole, and a
        # step of this block's own moves the lump to the middle afterwards.
        pbc = ctx.pstr("pbc", "mol") or "mol"
        lump = pbc == "lump"
        argv = ["trjconv", "-s", tpr, "-f", traj, "-o", out,
                "-pbc", "mol" if lump else pbc]
        # One group, or several with commas between them. trjconv writes one
        # group, so several are joined into one first (see _pick).
        chosen = self._groups(ctx.pstr("sel", "Protein") or "Protein") or ["Protein"]
        sel, index = self._pick(plan, chosen, tpr, ctx.inp("index"))
        if index:
            argv += ["-n", index]
        begin, end = ctx.pfloat("begin", 0.0), ctx.pfloat("end", 0.0)
        if begin:
            argv += ["-b", f"{begin:g}"]
        if end:
            argv += ["-e", f"{end:g}"]
        if centre:
            argv.append("-center")
        # trjconv reads the group to centre on and the group to write, in that
        # order, from stdin. Escapes rather than real newlines, expanded by
        # printf %b: render_script indents every line of a multi-line step into
        # its subshell, and a literal newline inside the quotes would come back
        # as '  Protein'. GROMACS trims that and it works by luck.
        escape = "\\n"
        groups = f"{sel}{escape}{sel}{escape}" if centre else f"{sel}{escape}"
        command = "{cmd} " + " ".join(shlex.quote(a) for a in (argv + ctx.extra()))
        feed = f"printf '%b' {shlex.quote(groups)} | "

        facts = self._facts(ctx, traj)
        known_frames = int(facts.get("frames") or 0)
        limit_mb = ctx.pint("size_limit", 200)

        atoms = int(facts.get("atoms") or 0)
        per_frame = atoms * self.BYTES_PER_ATOM_LINE

        def fits(frames: int) -> int:
            """How many of those frames may be written before it is silly.

            The whole selection is assumed, which over-estimates whenever the
            selection is smaller than the system -- deliberately: a cap that
            errs towards writing less cannot surprise anybody with a 5 GB file
            in their run directory.
            """
            if not limit_mb or not per_frame or frames <= 2:
                return frames
            room = max(2, int(limit_mb * 1024 * 1024 / per_frame))
            return min(frames, room)

        def size_note(written: int, refused: int = 0) -> None:
            """What this will weigh -- and, if it was cut, that it was cut.

            Only the cap counts as being cut. Asking for 30 frames of a
            61-frame trajectory writes 21, because a stride is a whole number,
            and calling that a size limit would be blaming the wrong thing.
            """
            if not per_frame:
                return
            if refused:
                plan.notes.append(
                    f"{refused} frames of {atoms} atoms would be about "
                    f"{refused * per_frame / 1e6:.0f} MB of PDB; writing "
                    f"{written} instead to stay under {limit_mb} MB. Raise "
                    "'Stop above (MB)' or pick a smaller selection.")
            else:
                plan.notes.append(f"about {written * per_frame / 1e6:.0f} MB of PDB "
                                  f"({atoms} atoms x {written} frames)")

        if ctx.pstr("mode", "every Nth") == "about this many":
            wanted = max(2, ctx.pint("frames", 30))
            if known_frames:
                # Already read once, so the count costs nothing this time. This
                # is the whole reason the answer is kept: on a 46 GB trajectory
                # counting is half an hour of disk, and it used to be paid
                # again on every parameter change.
                asked = min(wanted, known_frames)
                target = fits(asked)
                skip = max(1, -(-known_frames // target))
                written = -(-known_frames // skip)
                size_note(written, asked if target < asked else 0)
                plan.sh(f"{feed}{command} -skip {skip}", tool="gmx",
                        label=f"every {_ordinal(skip)} of {known_frames} frames, {sel}")
                plan.notes.append(
                    f"{known_frames} frames known from a previous scan, so every "
                    f"{_ordinal(skip)} gives {written} of them without reading "
                    "the file to count them again")
            else:
                # The frame count comes from gmx check's summary table and not
                # from its "Last frame" line: past 2000 frames that line is
                # filtered out of the output entirely, and a node that silently
                # wrote every frame of a 57000-frame run would produce a 50 GB
                # PDB.
                plan.sh(
                    f"n=$({{cmd}} check -f {shlex.quote(traj)} 2>&1 "
                    "| awk '/^Step[ \t]/ {print $2; exit}'); "
                    f'n=${{n:-0}}; w={wanted}; '
                    'if [ "$n" -gt "$w" ] 2>/dev/null; then '
                    'skip=$(( (n + w - 1) / w )); else skip=1; fi; '
                    'echo ">> $n frames in the trajectory, taking every $skip"; '
                    f'{feed}{command} -skip "$skip"',
                    tool="gmx", label=f"about {wanted} frames of {sel}",
                )
                plan.notes.append(
                    f"counts the frames first, then takes about {wanted} of them "
                    "-- counting reads the whole trajectory. Click the file in "
                    "the Files tab and scan it once to skip this next time.")
        else:
            skip = max(1, ctx.pint("skip", 100))
            if known_frames:
                asked = -(-known_frames // skip)
                room = fits(asked)
                if room < asked:
                    skip = max(skip, -(-known_frames // room))
                    size_note(-(-known_frames // skip), asked)
                else:
                    size_note(asked)
            plan.sh(f"{feed}{command} -skip {skip}",
                    tool="gmx", label=f"every {_ordinal(skip)} frame of {sel}")
            plan.notes.append(f"every {_ordinal(skip)} frame of '{sel}', written as "
                              f"models in {out}")
        if lump:
            plan.files["whole_lump.py"] = _WHOLE_LUMP
            plan.step(["python", "whole_lump.py", out], tool="python",
                      label="the lump moved to the middle of the box")
            plan.notes.append("every frame moved so that the lump sits in the "
                              "middle of the box, in one piece")
        plan.outputs["frames"] = out
        return plan


_WHOLE_LUMP = r'''#!/usr/bin/env python3
"""Move every frame of a PDB of several models so one lump sits in the middle.

A drop in a box of gas, or a micelle in water, is one lump. The box repeats in
every direction, so a lump that happens to sit across an edge of the box is
drawn cut in two: part of it at one side of the box, the rest at the opposite
side. It is still one lump, and centring on its middle does not help, because
the ordinary middle of a lump cut in two lies in the gap between the parts.

So the middle is found the way the box repeats. Along each edge of the box,
every atom is given an angle: nothing at one end of the edge, a full turn at
the other end, where it would come back in. The average of those angles
points at where the atoms crowd together, whichever side of the edge they are
drawn on. Every frame is then moved so that point is in the middle of the
box, and each molecule that ends up outside is put back in through the
opposite side, whole. A rectangular box only: a slanted one is left as it
was. Needs nothing but Python.

usage: whole_lump.py frames.pdb      (the file is rewritten in place)
"""

import math
import os
import sys


def crowded(values, length):
    """Where along one edge of the box the atoms crowd together."""
    turn = 2.0 * math.pi / length
    s = sum(math.sin(v * turn) for v in values)
    c = sum(math.cos(v * turn) for v in values)
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return length / 2.0          # spread out evenly: nothing to move
    return (math.atan2(s, c) / turn) % length


def recentre(model, box):
    """One frame's lines, with every atom moved so the lump is in the middle."""
    atoms = [i for i, line in enumerate(model)
             if line.startswith(("ATOM", "HETATM"))]
    if not atoms or not box:
        return model
    xyz = [[float(model[i][30 + 8 * k:38 + 8 * k]) for k in range(3)]
           for i in atoms]
    shift = [box[k] / 2.0 - crowded([p[k] for p in xyz], box[k])
             for k in range(3)]
    out = list(model)
    key, wrap = None, [0.0, 0.0, 0.0]
    for n, i in enumerate(atoms):
        line = model[i]
        p = [xyz[n][k] + shift[k] for k in range(3)]
        # A molecule is the run of lines with the same residue; its first atom
        # decides which way the whole of it goes back into the box.
        if line[17:27] != key:
            key = line[17:27]
            wrap = [math.floor(p[k] / box[k]) * box[k] for k in range(3)]
        p = [p[k] - wrap[k] for k in range(3)]
        out[i] = line[:30] + "%8.3f%8.3f%8.3f" % tuple(p) + line[54:]
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.strip().splitlines()[-1])
    path = sys.argv[1]
    with open(path) as fh:
        lines = fh.read().splitlines(keepends=True)
    out, model, box = [], None, None
    frames, slanted = 0, False
    for line in lines:
        if line.startswith("CRYST1"):
            edges = [float(line[6 + 9 * k:15 + 9 * k]) for k in range(3)]
            angles = [float(line[33 + 7 * k:40 + 7 * k]) for k in range(3)]
            slanted = slanted or any(abs(a - 90.0) > 0.01 for a in angles)
            box = None if any(abs(a - 90.0) > 0.01 for a in angles) else edges
            # GROMACS writes it before each frame's MODEL line; kept in its
            # place wherever it is.
            (model if model is not None else out).append(line)
        elif line.startswith("MODEL"):
            model = [line]
        elif line.startswith("ENDMDL") and model is not None:
            out.extend(recentre(model + [line], box))
            frames += 1
            model = None
        elif model is not None:
            model.append(line)
        else:
            out.append(line)
    if model is not None:            # the last frame had no ENDMDL
        out.extend(recentre(model, box))
        frames += 1
    if not frames:                   # one frame, written without MODEL lines
        out = recentre(out, box)
        frames = 1
    with open(path + ".tmp", "w") as fh:
        fh.writelines(out)
    os.replace(path + ".tmp", path)
    if slanted:
        print("the box is not rectangular: frames in a slanted box were left "
              "as they were")
    print(f"{frames} frames: the lump moved to the middle of the box in each")


if __name__ == "__main__":
    main()
'''


_COMPARE = r'''#!/usr/bin/env python3
"""Put the same line from two or three graph files into one graph.

The first file sets the points along the bottom axis. The line from each other
file is read off at those points, joining its own points with straight lines,
so runs saved at different intervals still line up. Only the stretch that
every file covers is kept, so no line runs off into nothing. Needs nothing but
Python.

usage: compare.py out.xvg [--column N] [--title T] NAME FILE NAME FILE [NAME FILE]
"""

import argparse
import bisect
import sys


def quoted(line):
    parts = line.split('"')
    return parts[1] if len(parts) >= 3 else ""


def read(path, column):
    """The title, the two axis labels and the points of one plot file."""
    title = xlabel = ylabel = ""
    points = []
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("@"):
                low = line.lower()
                if " title " in low:
                    title = quoted(line)
                elif "xaxis" in low and "label" in low:
                    xlabel = quoted(line)
                elif "yaxis" in low and "label" in low:
                    ylabel = quoted(line)
                continue
            try:
                values = [float(v) for v in line.split()]
            except ValueError:
                continue
            if len(values) > column:
                points.append((values[0], values[column]))
    points.sort()
    return title, xlabel, ylabel, [p[0] for p in points], [p[1] for p in points]


def height(xs, ys, x):
    """The line's height at x, joining its points with straight lines."""
    i = bisect.bisect_left(xs, x)
    if i < len(xs) and xs[i] == x:
        return ys[i]
    lo, hi = i - 1, i
    share = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + share * (ys[hi] - ys[lo])


def clean(text):
    return text.replace('"', "'")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Put the same line from several "
                                             "plot files into one plot.")
    ap.add_argument("out")
    ap.add_argument("pairs", nargs="+", metavar="NAME FILE")
    ap.add_argument("--column", type=int, default=1,
                    help="which line of each file: 1 is the first")
    ap.add_argument("--title", default="")
    args = ap.parse_args(argv)
    if len(args.pairs) % 2 or len(args.pairs) < 4:
        sys.exit("give a name and a file for each plot, and at least two plots")

    graphs = []
    for name, path in zip(args.pairs[0::2], args.pairs[1::2]):
        title, xlabel, ylabel, xs, ys = read(path, args.column)
        if len(xs) < 2:
            sys.exit(f"{path} has fewer than two points in line {args.column}: is "
                     f"it a plot, and does it have that many lines?")
        graphs.append((name, path, title, xlabel, ylabel, xs, ys))
        print(f"{name}: {path}, {len(xs)} points, from {xs[0]:g} to {xs[-1]:g}")

    low = max(g[5][0] for g in graphs)
    high = min(g[5][-1] for g in graphs)
    if low > high:
        sys.exit("the plots do not overlap along the bottom axis, so there is "
                 "nothing to compare")
    for label, which in (("bottom axes", 3), ("side axes", 4)):
        names = sorted({g[which] for g in graphs if g[which]})
        if len(names) > 1:
            print(f"note: the {label} are labelled differently ("
                  + ", ".join(f"'{n}'" for n in names)
                  + "): are these the same measurement? The first one's label is used")

    first = graphs[0]
    xs = [x for x in first[5] if low <= x <= high]
    with open(args.out, "w") as fh:
        fh.write("# written by Comfy-gmx's 'Compare plots' block\n")
        fh.write("# columns: " + ", ".join([first[3] or "x"] + [g[0] for g in graphs]) + "\n")
        fh.write(f'@    title "{clean(args.title or first[2])}"\n')
        fh.write(f'@    xaxis  label "{clean(first[3])}"\n')
        fh.write(f'@    yaxis  label "{clean(first[4])}"\n')
        fh.write("@TYPE xy\n")
        for k, g in enumerate(graphs):
            fh.write(f'@ s{k} legend "{clean(g[0])}"\n')
        for x in xs:
            fh.write(f"{x:12.4f}" + "".join(f" {height(g[5], g[6], x):12.4f}"
                                           for g in graphs) + "\n")
    if low > min(g[5][0] for g in graphs) or high < max(g[5][-1] for g in graphs):
        print(f"kept the stretch every plot covers: {low:g} to {high:g}")
    print(f"{len(graphs)} plots in one, {len(xs)} points each, in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class CompareNode(Node):
    type = "view.compare"
    title = "Compare plots"
    category = CATEGORY
    color = "#3f6d7d"
    tool = "python"
    preview_kind = "plot"
    preview_port = "xvg"
    description = (
        "Draws two or three plots as one, so they can be compared line "
        "against line: the same measurement from two runs, say. Wire the "
        "plots in, give each a name for the key, and it draws them together "
        "inside the block.\n\n"
        "The first plot sets the points along the bottom axis, and the others "
        "are read off at the same points, so runs saved at different intervals "
        "still line up. Only the stretch that every plot covers is drawn. "
        "From a file that holds several lines, it takes the first; 'Which "
        "line of each plot' picks another."
    )
    inputs = (
        Port("first", "xvg", "the first plot"),
        Port("second", "xvg", "the second plot"),
        Port("third", "xvg", "a third plot", optional=True),
    )
    outputs = (Port("xvg", "xvg", "the plots together"),)
    params = (
        Param("name_first", "str", "Name of the first", "", placeholder="first",
              help="What the first plot's line is called in the key."),
        Param("name_second", "str", "Name of the second", "", placeholder="second"),
        Param("name_third", "str", "Name of the third", "", placeholder="third",
              advanced=True),
        Param("title", "str", "Title", "", placeholder="the first plot's title"),
        Param("column", "int", "Which line of each plot", 1, min=1, max=100,
              advanced=True,
              help="A plot file can hold several lines -- gmx energy writes one "
                   "for each thing it was asked for. 1 is the first. The same "
                   "line is taken from every file."),
        Param("output", "str", "Output name", "compare.xvg", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "compare.xvg"
        argv = ["python", "compare.py", out]
        for port in ("first", "second", "third"):
            value = ctx.raw(port)
            if value is None:
                if port == "third":
                    continue
                raise NodeError(f"input '{port}' is not connected")
            # Each plot under a name of its own. The same measurement from two
            # runs usually has the same file name -- ice.xvg and ice.xvg -- and
            # taken in under that name the second would land on the first, and
            # the block would draw one run against itself.
            own = value if isinstance(value, str) else (
                value.get("name") or value.get("path") or "graph.xvg")
            name = ctx.inp_as(port, f"{port}_{Path(str(own)).name}")
            argv += [ctx.pstr("name_" + port) or port, name]
        argv += ["--column", max(1, ctx.pint("column", 1))]
        if ctx.pstr("title"):
            argv += ["--title", ctx.pstr("title")]
        plan.files["compare.py"] = _COMPARE
        plan.step(argv, tool="python", label="put the plots together")
        plan.outputs["xvg"] = out
        return plan


NODES = [PreviewStructureNode, PreviewPlotNode, PreviewTrajectoryNode, CompareNode]
