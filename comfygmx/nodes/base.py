"""Node definitions: ports, parameters and the plan a node emits.

A node never runs anything itself.  It returns a :class:`Plan` -- an ordered
list of :class:`Step` objects plus a map of output port -> produced file.  The
executor stages the inputs, materialises inline files, renders the steps into a
bash script and runs them.  The same rendering path produces the "copy the exact
command" preview, so what the UI shows is byte-for-byte what gets executed.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


def local_path(raw: str) -> str:
    """A user-supplied path, with ``~`` expanded and any ``file://`` taken off.

    A browser writes ``file:///home/me/x.pdb`` whenever it inserts a dragged
    file as text, and that is also what copying an address gives you.  It is a
    path with a scheme on the front; anything else is returned untouched.
    """
    import os
    import urllib.parse

    text = str(raw or "").strip()
    if text[:7].lower() == "file://":
        parsed = urllib.parse.urlparse(text)
        # file://host/path is somebody else's disk unless the host is ours.
        if parsed.netloc and parsed.netloc.lower() not in ("localhost", ""):
            return text
        text = urllib.parse.unquote(parsed.path) or text
    return os.path.expanduser(text)


#: Files at or below this are copied into a work directory; bigger ones are
#: linked.  Same threshold the executor stages inputs with.
COPY_LIMIT_BYTES = 4 * 1024 * 1024


def bring_in(source: str, target: str) -> str:
    """Shell that puts a file in the work directory without copying a large one.

    A small file is copied, so editing the original cannot reach back into a
    finished run.  Anything bigger is hard-linked, falling back to a symlink and
    then to a copy: a 46 GB trajectory copied once per run is thirty-five
    minutes and 46 GB of disk for a file that is already on this machine, and
    the executor already stages large inputs the same way.
    """
    src = shlex.quote(str(source))
    dst = shlex.quote(str(target))
    # ``stat -c`` is GNU; BSD stat -- which is what macOS has -- spells the same
    # thing ``-f%z`` and fails on -c. ``wc -c`` is in POSIX and needs neither.
    return (
        f'if [ "$(wc -c < {src} 2>/dev/null || echo 0)" -le {COPY_LIMIT_BYTES} ]; then '
        f'cp -f {src} {dst}; '
        f'else ln -f {src} {dst} 2>/dev/null '
        f'|| ln -sf {src} {dst} 2>/dev/null '
        f'|| cp -f {src} {dst}; fi'
    )


def copy_in(source: str, target: str) -> str:
    """Shell that copies a file in, whatever its size.

    The difference from `bring_in` matters for files somebody's own scripts
    also use. `bring_in` hard-links anything over a few megabytes, which is
    right for a trajectory nothing will ever rewrite -- but a hard link is the
    same file under two names, so a step that opens it for writing changes the
    original as well. The Martini force-field patch does exactly that, and one
    of these force fields is sixteen megabytes.

    So the files a topology names are always copied. A run costs a few
    megabytes more and cannot reach back into the folder it read from.
    """
    return f"cp -f {shlex.quote(str(source))} {shlex.quote(str(target))}"


# --------------------------------------------------------------------------
# Port and parameter descriptions
# --------------------------------------------------------------------------

#: Port data types.  Purely advisory for the executor, but the editor uses them
#: to colour the wires and to refuse obviously wrong connections.
PORT_TYPES = (
    "structure",   # .pdb / .gro / .g96
    "topology",    # .top plus the .itp files it includes
    "mdp",         # a run-parameter file
    "tpr",         # a portable binary run input
    "traj",        # .xtc / .trr
    "index",       # .ndx
    "xvg",         # tabular analysis output
    "posre",       # position-restraint itp
    "ffdir",       # a force-field directory (foo.ff)
    "file",        # anything else
    "text",        # a string carried between nodes
    "any",
)


@dataclass
class Port:
    name: str
    type: str = "any"
    label: str = ""
    optional: bool = False
    #: Name of a parameter that decides this port's type at runtime.  A loader
    #: does not know what it is carrying until somebody picks a file, and a
    #: grey wildcard that connects to anything is not an answer -- it is the
    #: absence of one.  The editor reads the parameter, colours the port and
    #: checks connections against it.
    follows: str = ""
    #: Same grammar as a Param's ``when``: the port is only drawn while the
    #: named box holds one of the listed values.  A merged block shows the
    #: ports of the choice that is picked, not all of them at once.
    when: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "when": self.when,
            "optional": self.optional,
            "follows": self.follows,
        }


@dataclass
class Param:
    """One editable widget on the node body."""

    name: str
    type: str = "str"          # str | int | float | bool | choice | text | file
    label: str = ""
    default: Any = None
    choices: Sequence[Any] = field(default_factory=tuple)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    help: str = ""
    advanced: bool = False     # hidden until the node is expanded
    #: For a hidden box: the heading it sits under inside the node's advanced
    #: drawer. A node with dozens of hidden boxes (the run parameters have
    #: more than fifty) is unusable as one long list, so boxes that share a
    #: section get a small drawer of their own there ("Temperature",
    #: "Output"), and only the one you open takes up room. Empty keeps the
    #: plain single list every other node has.
    section: str = ""
    #: When this box is shown at all: ``"source=the Protein Data Bank"`` means
    #: it appears only while the box called ``source`` holds that value.
    #: Several values are separated by ``|``. Empty means always.
    #:
    #: For boxes that only make sense one way round. A node that can take a
    #: file or a code from a database has a file chooser and a code box, and
    #: showing both at once is how somebody ends up filling in the wrong one --
    #: or, worse, not noticing the second is there at all.
    when: str = ""
    rows: int = 4              # for type="text"
    #: Let the box take the height of what is in it, rather than sticking at
    #: ``rows``. For text that is meant to be read rather than filled in.
    grow: bool = False
    placeholder: str = ""
    #: Name of a fill-in-the-blanks form for this box, or "" for none.
    #:
    #: Several boxes want a small language rather than a value -- the
    #: molecules at the end of a topology, index groups, the answers a GROMACS
    #: tool reads from its input. Typing one of those from memory is
    #: how an afternoon gets spent on a colon in the wrong place. A box that
    #: names a form gets a button beside it; the form asks the questions with
    #: dropdowns and boxes, shows the exact text it is about to write, and
    #: writes it here. The box itself stays editable, so knowing the syntax is
    #: still faster than clicking, and a line the form cannot make can still be
    #: typed.
    #:
    #: The name has to be one the browser knows: `comfygmx/web/js/forms.js`
    #: registers them, and the smoke test refuses a name nothing registers.
    form: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "default": self.default,
            "choices": list(self.choices),
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "help": self.help,
            "advanced": self.advanced,
            "section": self.section,
            "when": self.when,
            "rows": self.rows,
            "grow": self.grow,
            "placeholder": self.placeholder,
            "form": self.form,
        }


def extra_flags_param(hint: Optional[Dict[str, Any]] = None) -> Param:
    """The Extra flags box, worded for the command this node actually runs.

    The generic box -- "appended to the main command of this node", example
    ``-nsteps 5000 -maxwarn 1`` -- was the same on all seventy nodes, so it
    said nothing about the one in front of you and its example was wrong for
    nearly all of them.  Naming the command turns it into a box you can use
    without leaving the program, and the browser hangs that command's own flag
    list underneath it.
    """
    if not hint:
        return Param(
            name="extra_flags", type="text", label="Extra flags", default="",
            rows=2, advanced=True, placeholder="-nsteps 5000 -maxwarn 1",
            help="Appended verbatim to the main command of this node. "
                 "Shell-quoted, one or more flags, newlines allowed.",
        )
    command = hint["command"]
    common = (f"Appended verbatim to '{command}', after everything the boxes "
              "above set. Shell-quoted, one or more flags, newlines allowed.")
    if not hint.get("total"):
        # Nothing to list: a program the user points the node at by hand, or
        # one that was not installed where the flag catalogue was built.
        detail = " Comfy-gmx has no flag list for it here."
    elif not hint.get("available"):
        detail = (f" This node has a box of its own for every one of the "
                  f"{hint['total']} flags {command} takes, so there is not "
                  "usually anything to add.")
    else:
        detail = (f" The list under the box is the {hint['available']} it "
                  "takes that this node does not already set.")
    return Param(
        name="extra_flags", type="text", label=f"Extra flags for {command}",
        default="", rows=2, advanced=True,
        placeholder=hint.get("example") or "-flag value",
        help=common + detail,
    )


#: The box a node gets when it has no command to append to -- see
#: :func:`extra_flags_param`.  Kept as a name because the docs generator and
#: the layout tables both look for it.
EXTRA_FLAGS_PARAM = extra_flags_param()


ENV_OVERRIDE_PARAM = Param(
    name="env_override",
    type="str",
    label="Use this installation",
    default="",
    advanced=True,
    placeholder="blank = whatever this tool is set to",
    help="Run this node against a different installation than the one the tool is "
         "set to, so two versions can be compared in one graph. The box offers "
         "whatever is installed. For GROMACS, whose versions are builds rather "
         "than conda environments, it also takes a version like 2024.4 or a path "
         "to a GMXRC.",
)


# --------------------------------------------------------------------------
# Execution plan
# --------------------------------------------------------------------------

@dataclass
class Step:
    """One command inside a node."""

    argv: List[str] = field(default_factory=list)
    #: Logical tool id -- resolved to a binary and a conda env by the toolbox.
    tool: str = "shell"
    label: str = ""
    #: Text piped to the command's stdin (``gmx`` group selections live here).
    stdin: Optional[str] = None
    #: When true ``argv`` is a single string handed to ``bash -c``.
    shell: bool = False
    #: Non-zero exit does not abort the node.
    allow_fail: bool = False
    #: Keep argv[0] as written instead of replacing it with the tool's
    #: configured command. Almost every tool here is one program, possibly with
    #: sub-commands -- "gmx grompp" -- so replacing the first word is what lets
    #: somebody point the whole workflow at gmx_mpi. A few tools are instead a
    #: family of separate programs: bentopy ships bentopy-pack, bentopy-mask,
    #: bentopy-render and three more, and there is no plain "bentopy" to stand
    #: for them. For those the step names its own program and only the
    #: environment comes from the toolbox.
    own_command: bool = False
    #: Files this step pulls in from outside the workflow, as
    #: ``{"source": <absolute path>, "local": <name in the work directory>}``.
    #: Set by :meth:`Plan.bring`.  A run does not need it -- the command
    #: already names the path -- but an export does: these are the files that
    #: have to travel with the scripts, and the only ones whose absolute path
    #: must be rewritten to point inside the exported folder.
    imports: List[Dict[str, str]] = field(default_factory=list)

    def render(self) -> str:
        if self.shell:
            return self.argv[0] if self.argv else ""
        return " ".join(shlex.quote(str(a)) for a in self.argv)


@dataclass
class Plan:
    steps: List[Step] = field(default_factory=list)
    #: port name -> file name relative to the node work directory, or a dict
    #: ``{"top": name, "extra": [names]}`` for topology bundles, or a plain
    #: python value for ``text`` ports.
    outputs: Dict[str, Any] = field(default_factory=dict)
    #: relative name -> file content, written before the first step runs.
    files: Dict[str, str] = field(default_factory=dict)
    #: free-form remarks surfaced in the UI (warnings, chosen defaults, ...)
    notes: List[str] = field(default_factory=list)
    #: Input files this node writes to where they stand, rather than producing
    #: a new file.  A topology that a patcher edits in place is the case: the
    #: name has to stay the same, because the system topology includes it by
    #: name.  A staged input over a few megabytes is a hard link to the user's
    #: own file, so without this the patch would reach back and change the
    #: original.  Naming it here makes the executor give this run a copy of its
    #: own first.
    rewrites: List[str] = field(default_factory=list)

    def step(self, argv: Sequence[Any], tool: str = "shell", **kw: Any) -> Step:
        st = Step(argv=[str(a) for a in argv], tool=tool, **kw)
        self.steps.append(st)
        return st

    def sh(self, script: str, tool: str = "shell", **kw: Any) -> Step:
        st = Step(argv=[script], tool=tool, shell=True, **kw)
        self.steps.append(st)
        return st

    def bring(self, source: Any, local: str, label: str = "") -> Step:
        """Copy a file in from outside the workflow, and say that is what it is.

        The same as ``plan.sh(bring_in(...))`` with the source recorded, so an
        export can put the file in the folder and point the command at it
        instead of at a path that only exists on this machine.
        """
        name = Path(str(source)).name
        st = self.sh(bring_in(str(source), local), label=label or f"bring in {name}")
        st.imports = [{"source": str(source), "local": local}]
        return st


class NodeError(Exception):
    """Raised by a node when its parameters or inputs cannot produce a plan."""


class ToolMissing(NodeError):
    """The node is fine; the program it drives is not on this machine.

    A NodeError, so the editor and the executor keep reporting it exactly as
    before -- the person who wired the node still needs to be told. It is a
    separate type only so that a checker can tell the two kinds apart: a
    parameter that cannot produce a plan is a problem with the workflow, while
    a tool that was never installed is a fact about the machine, and counting
    the second as a failure makes the repository's own test suite fail on any
    machine that does not have every optional tool on it.
    """


def checkout_path(settings: Any, tool_id: str) -> Path:
    """Where a tool that is a checkout rather than a package lives.

    Asks the settings, which know whether the user pointed this tool at a
    checkout of their own.  Falls back to the default location when there are
    no settings at all, which happens in the tests and in `dry` previews built
    outside a server.
    """
    resolve = getattr(settings, "source_dir", None)
    if callable(resolve):
        return Path(resolve(tool_id))
    root = Path(getattr(settings, "sources_dir", Path.home() / ".comfy-gmx" / "src"))
    return root / tool_id


# --------------------------------------------------------------------------
# Context handed to Node.plan()
# --------------------------------------------------------------------------

class PlanContext:
    """What a node can see while it builds its plan.

    ``stage`` is supplied by the executor.  In *dry* mode it only computes the
    local file name an input would get, so a command preview works before any
    upstream node has run.
    """

    def __init__(
        self,
        node_id: str,
        node_type: str,
        params: Dict[str, Any],
        inputs: Dict[str, Any],
        workdir: Path,
        stage: Callable[[str], str],
        settings: Any = None,
        dry: bool = False,
    ):
        self.node_id = node_id
        self.node_type = node_type
        self.params = params or {}
        self.inputs = inputs or {}
        self.workdir = workdir
        self._stage = stage
        self.settings = settings
        self.dry = dry

    # -- parameters -----------------------------------------------------
    def p(self, name: str, default: Any = None) -> Any:
        value = self.params.get(name, default)
        return default if value is None else value

    def pstr(self, name: str, default: str = "") -> str:
        return str(self.p(name, default) or "").strip()

    def pint(self, name: str, default: int = 0) -> int:
        try:
            return int(float(self.p(name, default)))
        except (TypeError, ValueError):
            return default

    def pfloat(self, name: str, default: float = 0.0) -> float:
        try:
            return float(self.p(name, default))
        except (TypeError, ValueError):
            return default

    def pbool(self, name: str, default: bool = False) -> bool:
        value = self.p(name, default)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    def extra(self) -> List[str]:
        """The node's free-text extra flags, split the way a shell would."""
        raw = self.pstr("extra_flags")
        if not raw:
            return []
        try:
            return shlex.split(raw)
        except ValueError as exc:
            raise NodeError(f"could not parse extra flags: {exc}") from exc

    # -- inputs ---------------------------------------------------------
    def has(self, port: str) -> bool:
        return self.inputs.get(port) is not None

    def raw(self, port: str, default: Any = None) -> Any:
        value = self.inputs.get(port)
        return default if value is None else value

    def inp(self, port: str, default: Optional[str] = None) -> Optional[str]:
        """Local file name for a connected file port (staged into the workdir)."""
        value = self.inputs.get(port)
        if value is None:
            return default
        return self._stage(value)

    def require(self, port: str) -> str:
        name = self.inp(port)
        if not name:
            raise NodeError(f"input '{port}' is not connected")
        return name

    def inp_as(self, port: str, name: str) -> Optional[str]:
        """Like :meth:`inp`, but the file arrives under ``name``.

        Two inputs that share a name are kept apart anyway -- the second one
        arrives with a number in front, 2_ice.xvg. A node that takes several
        files of the same kind can pick clearer names itself: first_ice.xvg
        and second_ice.xvg say which port each one came in on.
        """
        value = self.inputs.get(port)
        if value is None:
            return None
        return self._stage(value, as_name=name)

    def staged_dirs(self, port: str) -> List[str]:
        """Directory names that came in on ``port`` and must go out again.

        A topology built against a local force field carries that directory with
        it; a node that rewrites the topology has to pass the reference on or the
        next grompp cannot resolve its #include lines.
        """
        value = self.inputs.get(port)
        if not isinstance(value, dict):
            return []
        import os.path
        return [os.path.basename(str(d).rstrip("/")) for d in (value.get("dirs") or [])]

    def text_in(self, port: str, default: str = "") -> str:
        value = self.inputs.get(port)
        if value is None:
            return default
        if isinstance(value, dict):
            return str(value.get("value", default))
        return str(value)


# --------------------------------------------------------------------------
# The node base class
# --------------------------------------------------------------------------

class Node:
    """Subclass, set the class attributes, implement :meth:`plan`."""

    type: str = ""
    title: str = ""
    category: str = "Misc"
    description: str = ""
    color: str = "#3b4a5a"
    #: logical tool this node needs; surfaced in the environment checker
    tool: str = "shell"
    inputs: Sequence[Port] = ()
    outputs: Sequence[Port] = ()
    params: Sequence[Param] = ()
    #: link to upstream documentation, shown in the node's help popover
    docs: str = ""
    #: The command this node's *Extra flags* box is appended to, spelled the
    #: way you would type it: "gmx grompp", "gmx solvate", "clean_pdb.py".
    #: It is what gives the box its example and its flag list, and
    #: ``tools/smoke_test.py`` checks the claim by planning the node with a
    #: sentinel flag and finding which command it landed on.  Empty means this
    #: node has no single command -- it copies a file, writes a config, draws a
    #: picture -- and then it gets no Extra flags box at all.
    extra_command: str = ""
    #: Whether this node ever runs a command. A sticky note does not, so it has
    #: no use for a box asking which installation to run it against -- and a
    #: box that cannot do anything is worse than no box, because somebody will
    #: fill it in and wonder why nothing changed.
    runs_commands: bool = True
    #: Bumped when this block has been corrected in a way that changes what it
    #: produces from the same inputs -- a fix to the script it carries inside
    #: it. Nothing already computed is thrown away by a block that leaves this
    #: at nought, so an mdrun that took a day stays reusable; but a block that
    #: raises it gets a fresh signature, and a result made by the old version
    #: is no longer handed back as though it were still right. Changing a
    #: box's default already has that effect on its own, so this is only for a
    #: correction the boxes do not show.
    revision: int = 0
    #: Kept for graphs that already use it, but not offered in the palette:
    #: something else does the job now, and this node's own description says
    #: what. Old workflows go on loading and running exactly as before -- the
    #: node is still registered, still plans, still runs. It is only missing
    #: from the list you pick from.
    hidden: bool = False
    #: For a hidden node that has been folded into a bigger one: where a graph
    #: that still names this node should go instead.  ``{"type": "gmx.measure",
    #: "params": {"measure": "RMSD (rms)"}, "rename": {"old": "new"}}`` -- the
    #: new type, the choice that makes it behave like this node, and any boxes
    #: that changed name on the way.  The editor and the runner both convert a
    #: node on the way in, so an old graph opens as the new blocks and the
    #: person never meets a block they cannot find in the palette.
    replaced_by: Optional[Dict[str, Any]] = None
    #: When set, the editor draws the file this node produces inside the node
    #: body, the way an image node shows its image.  ``preview_kind`` says how
    #: to draw it and ``preview_port`` says which output holds the file.
    preview_kind: str = ""     # "" | "structure" | "plot" | "dssp" | "trajectory"
    preview_port: str = ""

    def plan(self, ctx: PlanContext) -> Plan:  # pragma: no cover - interface
        raise NotImplementedError

    # -- introspection --------------------------------------------------
    @classmethod
    def flag_hint(cls) -> Optional[Dict[str, Any]]:
        """Per-node help for the Extra flags box, or None if it has no box."""
        from .. import flaghints
        return flaghints.hint(cls)

    @classmethod
    def all_params(cls) -> List[Param]:
        params = list(cls.params)
        names = {p.name for p in params}
        # A node that spells out its own extra_flags box -- the mdp node calls
        # it "Extra mdp lines" -- keeps it; one with nothing to append to gets
        # no box, rather than a box that silently goes nowhere.
        if "extra_flags" not in names and cls.extra_command:
            params.append(extra_flags_param(cls.flag_hint()))
        if ENV_OVERRIDE_PARAM.name not in names and cls.runs_commands:
            params.append(ENV_OVERRIDE_PARAM)
        return params

    @classmethod
    def defaults(cls) -> Dict[str, Any]:
        return {p.name: p.default for p in cls.all_params()}

    @classmethod
    def spec(cls) -> Dict[str, Any]:
        return {
            "type": cls.type,
            "title": cls.title or cls.type,
            "category": cls.category,
            "description": cls.description,
            "color": cls.color,
            "tool": cls.tool,
            "docs": cls.docs,
            "hidden": cls.hidden,
            "replaced_by": cls.replaced_by,
            "flag_hint": cls.flag_hint(),
            "preview": ({"kind": cls.preview_kind, "port": cls.preview_port}
                        if cls.preview_kind else None),
            "inputs": [p.to_dict() for p in cls.inputs],
            "outputs": [p.to_dict() for p in cls.outputs],
            "params": [p.to_dict() for p in cls.all_params()],
        }
