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
        Param("sel", "str", "Selection", "Protein",
              help="An index group name. 'Protein' for a fold, 'System' to see "
                   "everything including the box -- which for a solvated run is "
                   "mostly water, so it is worth an index group."),
        Param("pbc", "choice", "Periodic boundary", "mol",
              choices=["mol", "atom", "whole", "nojump", "none"],
              help="'mol' keeps molecules in one piece, which is what makes a "
                   "protein stop exploding across the box edge."),
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
        argv = ["trjconv", "-s", tpr, "-f", traj, "-o", out,
                "-pbc", ctx.pstr("pbc", "mol") or "mol"]
        index = ctx.inp("index")
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
        plan.outputs["frames"] = out
        return plan


NODES = [PreviewStructureNode, PreviewPlotNode, PreviewTrajectoryNode]
