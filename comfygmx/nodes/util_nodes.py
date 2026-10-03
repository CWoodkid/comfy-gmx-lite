"""Utility nodes: run parameters, free-form shell, and scripted analysis."""

from __future__ import annotations

from pathlib import Path

from ..mdp_options import BOXES, GROMACS_DEFAULTS, Box, _h
from ..templates import PRESET_INFO, PRESETS, merge_extra, parse_mdp, render_mdp
from .base import Node, NodeError, Param, PlanContext, Plan, Port, local_path

CATEGORY = "Parameters & scripting"


def _box_param(box: Box) -> Param:
    """A box from the table in mdp_options.py, as a parameter of the block."""
    return Param(box.param, box.kind, box.label, "",
                 choices=list(box.choices), help=box.help, when=box.when,
                 placeholder=box.placeholder,
                 advanced=bool(box.section), section=box.section)


class MdpNode(Node):
    type = "util.mdp"
    title = "Run parameters (.mdp)"
    category = CATEGORY
    color = "#6b5b8a"
    tool = "shell"
    description = (
        "The settings for a simulation: what kind of run, how long, how warm, what "
        "pressure, what to save and how often. Start from a preset (minimisation, "
        "NVT, NPT, production), from an .mdp file you already have, or from your "
        "own text, and change only what you care about. Every box shows the value "
        "the run will use; leave it empty to keep that value. The summary under "
        "the first boxes says in words what the settings add up to."
    )
    docs = "https://manual.gromacs.org/current/user-guide/mdp-options.html"
    outputs = (Port("mdp", "mdp", "mdp"),)
    params = (
        Param("mode", "choice", "Settings come from", "preset",
              choices=["preset", "manual", "file", "raw"],
              help=_h("""
                  Where this block gets its settings.

                  preset: a finished set of settings for a common job, used
                  exactly as published. The boxes show what it contains;
                  leave them empty to keep it that way.

                  manual: a preset edited here. Typing in any box while on
                  preset switches to this by itself, fills every box with the
                  preset's value, and names the file after the preset with
                  _edited added, so an edited file never passes for the
                  published one.

                  file: an .mdp file you already have. Its settings are read in,
                  and any box you fill in changes that setting on top of it.
                  That is how one hand-tuned file becomes three replicas with
                  different seeds.

                  raw: text you paste or type, written out exactly as it is,
                  comments and all. The boxes in the advanced drawer, under
                  Main settings and the other headings, show what the text
                  says, and typing in one of them rewrites that line of the
                  text.
                  """)),
        Param("preset", "choice", "Preset", "md_atomistic", choices=list(PRESETS.keys()),
              when="mode=preset|manual",
              help=_h("""
                  The published settings to start from. The name says the
                  job:

                      em_...    energy minimisation: removes clashes before anything moves
                      nvt_...   first warm-up: heats the system at a fixed volume
                      npt_...   second warm-up: lets the box settle at the right pressure
                      md_...    production: the run you analyse

                  The atomistic presets are for all-atom force fields such as
                  CHARMM36 or AMBER. The lysozyme_ presets copy the Lysozyme
                  tutorial exactly, one for each of its steps: ions, min, nvt,
                  npt and md. The summary under these boxes says what the
                  chosen one does.
                  """)),
        Param("path", "file", "The .mdp file", "", placeholder="/path/to/eq1_nvt.mdp",
              when="mode=file",
              help=_h("""
                  The .mdp file to start from, on this machine. Its options are
                  read in and written back out through the same writer as a
                  preset, with any box you fill in changed on top, so the
                  options survive but the file's own comments do not. For a
                  file on the web, put a Download file block in front of
                  grompp instead.
                  """)),
        Param("raw", "text", "The mdp text", "", rows=10, when="mode=raw",
              placeholder="; paste an .mdp file here\nintegrator = steep\nnsteps     = 5000",
              help=_h("""
                  The whole .mdp file, written out exactly as it is here,
                  comments included. Each line is an option, an equals sign and
                  a value; anything after a semicolon is a comment.

                  The summary above says in words what these settings do. The
                  boxes in the advanced drawer show the values the text sets,
                  and typing in one of them changes that line here instead of
                  adding a second one.
                  """)),
        *[_box_param(box) for box in BOXES if not box.section],
        Param("saved", "choice", "What goes into the trajectory", "",
              choices=["", "the whole system", "everything except the water"],
              when="mode!=raw",
              help=_h("""
                  Decide this before the run, not after. Leaving the water out
                  makes the file about three times smaller and is the usual
                  choice, but it also means you cannot start a new run from a
                  moment in the middle of this one, because there is no water
                  in the file to start from. That matters if you ever want to
                  go back to an interesting moment and repeat it with
                  different velocities.

                  For a 25,000-particle system the difference is about 110 MB
                  against 330 MB per microsecond. Empty keeps whatever the
                  preset says.
                  """)),
        *[_box_param(box) for box in BOXES if box.section],
        Param("filename", "str", "File name", "run.mdp", advanced=True,
              section="File and extra lines",
              help=_h("""
                  The name the settings are written under in the run folder,
                  which is also the file grompp is given. run.mdp when nobody
                  says; an edited preset writes itself as its name plus
                  _edited.mdp.
                  """)),
        Param("extra_flags", "text", "Extra mdp lines", "", rows=4, advanced=True,
              section="File and extra lines", when="mode!=raw",
              placeholder="pull = yes\npull-ngroups = 2",
              help=_h("""
                  Any mdp option that has no box here, one per line as option
                  = value: pulling, walls, free-energy settings, electric fields
                  and the rest. They are added last and win over everything
                  above. In raw mode, type them into the text instead.
                  """)),
    )

    #: Which box sets which mdp option. define is kept apart: it is not
    #: filled in with the others when a preset is edited, and NONE in it
    #: removes the preset's line rather than writing one.
    _WIDGET_MAP = {box.param: box.key for box in BOXES if box.param != "define"}

    #: GROMACS's own value for each box's option, used where neither the
    #: preset, the raw text nor the file sets it, so a box shows the number
    #: the run will really use rather than nothing. Where the numbers come
    #: from is said beside the table, in mdp_options.py.
    _GROMACS_DEFAULTS = dict(GROMACS_DEFAULTS)

    #: What the file is called when nobody has said. Kept as a constant because
    #: the browser renames it on the same rule when a preset is edited.
    DEFAULT_NAME = "run.mdp"

    @classmethod
    def edited_name(cls, preset: str) -> str:
        """What an edited preset writes itself as."""
        stem = (preset or "run").replace(" ", "_")
        return f"{stem}_edited.mdp"

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        name = ctx.pstr("filename") or self.DEFAULT_NAME
        if ctx.pstr("mode") == "manual" and name == self.DEFAULT_NAME:
            name = self.edited_name(ctx.pstr("preset"))
        if not name.endswith(".mdp"):
            name += ".mdp"

        if ctx.pstr("mode") == "raw":
            body = ctx.pstr("raw")
            if not body.strip():
                raise NodeError("mode is 'raw' but the raw mdp text box is empty")
            plan.files[name] = body.rstrip() + "\n"
            plan.outputs["mdp"] = name
            plan.notes.append("raw mode: the text is written out exactly as it is. "
                              "The boxes in the advanced drawer change its lines")
            return plan

        if ctx.pstr("mode") == "file":
            raw_path = ctx.pstr("path")
            if not raw_path:
                raise NodeError("mode is 'file' but no .mdp path is set")
            if raw_path.lower().startswith(("http://", "https://")):
                # Said plainly, because the obvious thing to try is pasting the
                # address of an .mdp from a tutorial page, and the message it
                # used to give printed the address with a slash missing -- the
                # path reader had already mangled it.
                raise NodeError(
                    "this box takes a file on this machine, not an address:\n\n"
                    f"    {raw_path}\n\n"
                    "Put a 'Download file' node in front of the grompp node and "
                    "wire it into grompp's mdp input instead. That way the file "
                    "is fetched once and kept with the run, rather than being "
                    "downloaded again every time.")
            source = Path(local_path(raw_path))
            if ctx.dry and not source.is_file():
                options = {}
            else:
                if not source.is_file():
                    raise NodeError(
                        f"no such .mdp: {raw_path}\n\n"
                        f"looked for it at {source}")
                options = parse_mdp(source.read_text())
            title = f"from {source}"
        else:
            preset_name = ctx.pstr("preset") or "md_atomistic"
            if preset_name not in PRESETS:
                raise NodeError(f"unknown preset '{preset_name}'")
            options = dict(PRESETS[preset_name])
            title = PRESET_INFO.get(preset_name, preset_name)
            if ctx.pstr("mode") == "manual":
                # Same starting point, different claim: this file is no longer
                # the published preset, and both the title inside it and the
                # name it is written under should say so rather than letting a
                # tuned run look like a stock one months later.
                title = (f"Started from the preset {preset_name}, then changed "
                         f"in this block. The preset: {title}")

        for param_name, mdp_key in self._WIDGET_MAP.items():
            value = ctx.pstr(param_name)
            if value:
                options[mdp_key] = value

        define = ctx.pstr("define")
        if define.upper() == "NONE":
            options.pop("define", None)
        elif define:
            options["define"] = define

        saved = ctx.pstr("saved")
        if saved.startswith("the whole"):
            options["compressed-x-grps"] = "System"
        elif saved.startswith("everything except"):
            options["compressed-x-grps"] = "non-Water"

        options = merge_extra(options, ctx.pstr("extra_flags"))
        plan.files[name] = render_mdp(options, title=title)
        plan.outputs["mdp"] = name
        plan.notes.append(title)

        # Two things worth saying out loud rather than leaving in a file.
        group = str(options.get("compressed-x-grps") or "").strip()
        if group and group.lower() not in ("system", ""):
            plan.notes.append(
                f"the trajectory will hold '{group}' and not the whole system, "
                "so it is about three times smaller -- and a new run cannot be "
                "started from a moment in the middle of it, because the water "
                "is not there")
        if str(options.get("coulombtype") or "").lower().startswith("reaction"):
            plan.notes.append(
                "reaction field, not PME: that is what Martini was fitted with, "
                "together with a 1.1 nm cut-off. Changing it to PME is not an "
                "upgrade, it is a different model. It also means a graphics "
                "card helps less here than in an all-atom run")
        return plan


class NoteNode(Node):
    type = "util.note"
    title = "Note"
    category = CATEGORY
    color = "#5a5233"
    tool = "shell"
    runs_commands = False
    description = (
        "A sticky note. It never runs; it is there so a workflow can explain itself "
        "to whoever opens it next -- including you, later."
    )
    params = (
        # grow=True: the box takes the height of what is in it. A note is the
        # one box whose whole purpose is to be read, and six rows with a
        # scrollbar means the reader sees the first four lines of a page.
        Param("text", "text", "Note", "", rows=6, grow=True,
              placeholder="What is this branch for?"),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        # Deliberately nothing. This used to hand the note's own text back as a
        # run note, so every note appeared twice on the same card: once in the
        # box you type into and once again underneath it. One copy is enough,
        # and it should be the one you can edit.
        return Plan()


class ShellNode(Node):
    type = "util.shell"
    title = "Shell command"
    category = CATEGORY
    color = "#4a4a4a"
    tool = "shell"
    #: Not on the palette in this version, which keeps to the blocks its
    #: tutorials use. Kept because the tests of the part that runs graphs --
    #: in what order, what stops, what carries on -- are written with it: it
    #: is the one block whose work can be anything, including nothing.
    hidden = True
    description = (
        "Runs a shell script of your own, for anything Comfy-gmx has no node for. The "
        "files wired in are placed in the working directory under the names shown on "
        "the ports. Pick a tool to borrow its environment -- 'gmx' sources GMXRC, the "
        "others activate their conda environment -- and write {cmd} where the tool's "
        "command should go."
    )
    inputs = (
        Port("in1", "any", "in1", optional=True),
        Port("in2", "any", "in2", optional=True),
        Port("in3", "any", "in3", optional=True),
        Port("in4", "any", "in4", optional=True),
    )
    outputs = (Port("out", "file", "out"),)
    params = (
        Param("script", "text", "Script", "ls -la\n", rows=8,
              help="Bash. $IN1/$IN2/$IN3/$IN4 hold the staged input file names; write "
                   "your result to the file named in 'Output file'. Each input is "
                   "ALREADY in this folder under its own name -- so a plain "
                   "cp \"$IN1\" that-name fails with 'same file'. To lay a file out "
                   "under a fixed name, guard it: "
                   "[ \"$IN1\" -ef wanted.gro ] || cp \"$IN1\" wanted.gro"),
        Param("output", "str", "Output file", "out.txt"),
        Param("tool", "choice", "Run under", "shell",
              choices=["shell", "gmx", "python"],
              help="Whose environment to run in. 'gmx' sources GMXRC; the rest "
                   "activate the conda environment registered for that tool. {cmd} in "
                   "the script is replaced by the resolved command."),
        Param("carry", "text", "Files to carry with the output", "", rows=2,
              form="files.list",
              advanced=True, placeholder="*.itp",
              help="Globs, one per line. Matching files travel downstream beside the "
                   "output, which is how a script that rewrites a topology hands on "
                   "the .itp files it includes."),
        Param("env", "str", "Conda env", "", advanced=True,
              help="Optional environment to activate before the script runs. Overrides "
                   "the one that comes with the tool above."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        script = ctx.pstr("script")
        if not script:
            raise NodeError("script is empty")
        assignments = []
        for index, port in enumerate(("in1", "in2", "in3", "in4"), start=1):
            name = ctx.inp(port) or ""
            assignments.append(f'IN{index}="{name}"')
        body = "\n".join(assignments + [script])
        plan.sh(body, tool=ctx.pstr("tool", "shell") or "shell", label="shell script")
        out = ctx.pstr("output") or "out.txt"
        # Split on any whitespace, not lines only: "*.itp *.txt" typed on one
        # line used to become ONE glob, and only the first pattern got the
        # directory prefix downstream -- the second matched nothing, silently.
        globs = ctx.pstr("carry").split()
        if globs:
            # A .top plus the itps it includes: the same shape a topology port
            # carries, so this can be wired straight into grompp.
            plan.outputs["out"] = {"top": out, "glob": globs,
                                   "dirs": ctx.staged_dirs("in1")}
        else:
            plan.outputs["out"] = out
        return plan

NODES = [MdpNode, ShellNode, NoteNode]
