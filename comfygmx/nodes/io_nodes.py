"""Input and output nodes: getting structures in, getting results out."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Dict, List

from .base import (
    Node, NodeError, Param, Plan, PlanContext, Port, copy_in,
    local_path,
)

CATEGORY = "Input / Output"

_STRUCTURE_SUFFIXES = (".pdb", ".gro", ".cif", ".pdbx", ".ent", ".g96", ".mmcif")


#: The two answers to "where from". Spelled out rather than coded, because
#: they are what the box shows.
FROM_DISK = "a file on this machine"
FROM_PDB = "the Protein Data Bank"


def _bare_code(raw: str) -> str:
    """The code out of what was typed: 'pdb:1AKI' and '1aki' both give '1aki'."""
    text = str(raw or "").strip()
    if text.lower().startswith("pdb:"):
        text = text[4:].strip()
    return text.lower()


#: A PDB code as it is written: four characters, the first a digit -- 1AKI,
#: 6VXX. The longer form the PDB has begun issuing, pdb_00001abc, counts too.
#: Deliberately narrow: this is what decides whether a box holds a file name
#: or something to download, so a name that is merely short must not match.
_PDB_CODE_RE = re.compile(r"^(?:[1-9][A-Za-z0-9]{3}|pdb_[0-9]{4}[A-Za-z0-9]{4})$")


class LoadStructureNode(Node):
    type = "io.structure"
    title = "Load structure"
    category = CATEGORY
    color = "#2f6b52"
    tool = "shell"
    description = (
        "Brings a structure into the workflow, from this computer or from the "
        "Protein Data Bank. The first box says which.\n\n"
        "From this computer: the file is copied into the run folder, so nothing "
        "downstream can touch your original. Large files are linked rather than "
        "copied, so pointing at a big trajectory costs no disk.\n\n"
        "From the Protein Data Bank: give the four-character code -- 1AKI, 6VXX "
        "-- and it is downloaded. Needs an internet connection.\n\n"
        "Before running anything, right-click it. 'What is in ...' lists the "
        "chains and whatever else the file holds, and 'What is missing ...' "
        "shows which residues the experiment never resolved -- usually the "
        "thing that decides your next step."
    )
    outputs = (Port("structure", "structure", "structure"),)
    params = (
        Param("source", "choice", "Where from", FROM_DISK,
              choices=[FROM_DISK, FROM_PDB],
              help="Two ways to start a workflow, and this says which one.\n\n"
                   "'a file on this machine' copies a file you already have. "
                   "'the Protein Data Bank' downloads a deposited structure by "
                   "its four-character code, which is how most workflows begin "
                   "when there is no file yet.\n\n"
                   "The box below changes with it."),
        Param("path", "file", "File", "", placeholder="/path/to/protein.pdb",
              when=f"source={FROM_DISK}",
              help="An absolute path, or the name of something uploaded through "
                   "the browser. The button beside it opens a file browser."),
        Param("pdb_id", "str", "PDB code", "", placeholder="1AKI",
              when=f"source={FROM_PDB}",
              help="The four characters an entry is published under -- 1AKI, "
                   "6VXX. Case does not matter. The longer form the PDB has "
                   "begun issuing, pdb_00001abc, works too."),
        Param("format", "choice", "Download as", "pdb", choices=["pdb", "cif"],
              when=f"source={FROM_PDB}",
              help="Use cif for very large assemblies -- the old pdb format "
                   "cannot hold them."),
        Param("biological_assembly", "str", "Assembly", "", advanced=True,
              when=f"source={FROM_PDB}",
              placeholder="blank = the deposited coordinates, or 1, 2, ...",
              help="Fetches the biological unit, pdbID.pdbN, instead of what "
                   "was deposited."),
        Param("rename", "str", "Copy as", "", advanced=True,
              when=f"source={FROM_DISK}",
              placeholder="keeps the original file name"),
    )

    def _wanted_file(self, ctx: PlanContext, raw: str):
        """The file this box names, or None if it does not name one.

        Decided without touching the disk where it can be, because a plan is
        built for the preview long before anything is fetched or run: a slash
        or a structure suffix means a path whether or not it is there yet.
        """
        if "/" in raw or "\\" in raw:
            return Path(local_path(raw))
        if Path(raw).suffix.lower() in _STRUCTURE_SUFFIXES:
            return Path(local_path(raw))
        here = Path(local_path(raw))
        if here.exists():
            return here
        if ctx.settings is not None:
            uploaded = ctx.settings.uploads_dir / raw
            if uploaded.exists():
                return uploaded
        return None

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        code = ctx.pstr("pdb_id")
        raw = ctx.pstr("path")
        if ctx.pstr("source", FROM_DISK) == FROM_PDB:
            wanted = code or raw
            if not wanted:
                raise NodeError(
                    "no PDB code given -- 1AKI, 6VXX. Set 'Where from' back to "
                    f"'{FROM_DISK}' to load a file you already have")
            return self._download(plan, ctx, _bare_code(wanted))

        if not raw:
            if code:
                # The other box is filled in: do what was plainly meant rather
                # than complain about the empty one.
                plan.notes.append(
                    f"'Where from' says {FROM_DISK}, but the only thing filled "
                    f"in is a PDB code, so that is what this fetches")
                return self._download(plan, ctx, _bare_code(code))
            raise NodeError(
                "nothing to load: choose a file, or set 'Where from' to "
                f"'{FROM_PDB}' and give a code such as 1AKI")

        forced = raw.lower().startswith("pdb:")
        asked = raw[4:].strip() if forced else raw
        found = None if forced else self._wanted_file(ctx, asked)
        if found is None and (forced or _PDB_CODE_RE.match(asked)):
            # A workflow saved before this node had a "Where from" box put the
            # code in here. Still do the right thing by it, and say so.
            plan.notes.append(
                f"'{asked}' is not a file on this machine, so it was taken as a "
                f"PDB code. Set 'Where from' to '{FROM_PDB}' to say so plainly")
            return self._download(plan, ctx, _bare_code(asked))

        source = found if found is not None else Path(local_path(asked))
        if not ctx.dry and not source.exists():
            raise NodeError(
                f"there is no file '{source}'. Check the path, or set 'Where "
                f"from' to '{FROM_PDB}' if you meant a deposited structure")
        if source.suffix.lower() not in _STRUCTURE_SUFFIXES:
            plan.notes.append(
                f"'{source.suffix}' is not a structure suffix GROMACS reads directly"
            )
        local = ctx.pstr("rename") or source.name
        plan.bring(source, local)
        plan.outputs["structure"] = local
        return plan

    def _download(self, plan: Plan, ctx: PlanContext, code: str) -> Plan:
        """Fetch the deposited entry from the Protein Data Bank."""
        fmt = ctx.pstr("format", "pdb") or "pdb"
        assembly = ctx.pstr("biological_assembly")
        if assembly:
            remote = f"{code}.{'pdb' if fmt == 'pdb' else 'cif'}{assembly}"
            local = f"{code}_assembly{assembly}.{fmt}"
        else:
            remote = f"{code}.{fmt}"
            local = remote
        plan.step(["curl", "-fsSL", "--retry", "3", "-o", local,
                   f"https://files.rcsb.org/download/{remote}"],
                  label=f"download {remote}")
        plan.outputs["structure"] = local
        plan.notes.append(
            f"{code.upper()} is downloaded from the Protein Data Bank, so this "
            "node needs an internet connection. Point it at a file instead and "
            "nothing is downloaded")
        return plan


#: How an #include line in a topology is written.
_INCLUDE_RE = re.compile(r'#include\s+"([^"]+)"')


def included_files(top: Path, depth: int = 0, seen=None):
    """Every file a topology pulls in, and every file those pull in.

    A .top on its own is half a topology: the numbers that matter -- what atoms
    a molecule has, what it is charged, how it is bonded -- are in the .itp
    files it names, and grompp cannot do anything without them. They normally
    sit in the same folder, so this reads the #include lines and follows them
    there.

    Returns (files, directories, missing). A directory comes back when an
    include names one, which is how a force field arrives: pdb2gmx writes
    #include "charmm36.ff/forcefield.itp", so the whole folder has to travel,
    not the one file.

    Anything it cannot find is reported rather than guessed at: the force field
    includes that GROMACS resolves from its own share directory are supposed to
    be missing here, and so is a genuine mistake, and only the person looking at
    the node can tell those apart.
    """
    seen = seen if seen is not None else set()
    files, directories, missing = [], [], []
    real = top.resolve()
    if real in seen or depth > 8:
        return files, directories, missing
    seen.add(real)
    try:
        text = real.read_text(errors="replace")
    except OSError:
        return files, directories, missing
    here = real.parent
    for line in text.splitlines():
        line = line.split(";")[0]
        match = _INCLUDE_RE.search(line)
        if not match:
            continue
        named = match.group(1)
        target = (here / named)
        if not target.exists():
            missing.append(named)
            continue
        if "/" in named:
            # Inside a folder -- take the folder, since the include is written
            # relative to it and the rest of it will be wanted too.
            folder = (here / named.split("/")[0])
            if folder.is_dir() and folder not in directories:
                directories.append(folder)
            continue
        if target not in files:
            files.append(target)
            deeper = included_files(target, depth + 1, seen)
            for item in deeper[0]:
                if item not in files:
                    files.append(item)
            for item in deeper[1]:
                if item not in directories:
                    directories.append(item)
            missing.extend(deeper[2])
    return files, directories, missing


class LoadFileNode(Node):
    type = "io.file"
    title = "Load file"
    category = CATEGORY
    color = "#2f6b52"
    tool = "shell"
    description = (
        "The same as Load structure, for everything that is not a structure: "
        "topologies, settings files, index files, trajectories."
    )
    outputs = (Port("file", "any", "file", follows="kind"),)
    params = (
        Param("path", "file", "File", "", placeholder="/path/to/topol.top"),
        Param("kind", "choice", "Declared type", "auto",
              choices=["auto", "file", "topology", "mdp", "index", "traj", "tpr",
                       "structure", "xvg"],
              help="'auto' reads it off the file's name, which is right often "
                   "enough to be worth not typing. It decides the colour of the "
                   "output, which connections the editor will let you make, and "
                   "-- for a topology -- whether the .itp files beside it travel "
                   "with it on the wire. Set it by hand for a file whose name "
                   "does not say what it is."),
        Param("follow_includes", "bool", "Bring the files it includes", True,
              help="A .top on its own is half a topology: what each molecule is "
                   "made of lives in the .itp files it names, and nothing "
                   "downstream works without them. With this on, the #include "
                   "lines are read and every file they name that sits beside "
                   "the .top comes too -- including the ones those include in "
                   "turn, and a force-field folder if one is named. Anything it "
                   "cannot find is listed in the node's notes."),
        Param("includes", "text", "Also copy in", "", rows=3, advanced=True,
              form="files.list", placeholder="one path per line -- for files that live somewhere else",
              help="For files the topology needs that are NOT beside it, or that "
                   "it does not name. Anything sitting next to it is picked up "
                   "on its own by the setting above."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        raw = ctx.pstr("path")
        if not raw:
            raise NodeError("no file selected")
        source = Path(local_path(raw))
        if not source.is_absolute() and ctx.settings is not None:
            candidate = ctx.settings.uploads_dir / raw
            if candidate.exists():
                source = candidate
        if not ctx.dry and not source.exists():
            raise NodeError(f"file does not exist: {source}")
        plan.bring(source, source.name)

        extra = []
        for line in ctx.pstr("includes").splitlines():
            line = line.strip()
            if not line:
                continue
            include = Path(local_path(line))
            plan.bring(include, include.name)
            extra.append(include.name)

        kind = ctx.pstr("kind", "auto")
        if kind in ("", "auto"):
            kind = kind_of(source.name)
            plan.notes.append(f"read as a {kind} from the file name")

        folders: List[str] = []
        if kind == "topology" and ctx.pbool("follow_includes", True) and source.exists():
            found, directories, missing = included_files(source)
            for include in found:
                if include.name in extra or include.name == source.name:
                    continue
                # Copied, never linked. These are files your own scripts read,
                # and a big one would otherwise be hard-linked -- which is the
                # same file under two names, so a node that rewrites it here
                # would rewrite yours as well.
                step = plan.sh(copy_in(str(include), include.name),
                               label=f"bring in {include.name}")
                step.imports = [{"source": str(include), "local": include.name}]
                extra.append(include.name)
            for folder in directories:
                plan.sh(f"cp -a {shlex.quote(str(folder))} {shlex.quote(folder.name)}",
                        label=f"bring in {folder.name}")
                folders.append(folder.name)
            if found or directories:
                plan.notes.append(
                    "brought in " + ", ".join(
                        [f"{len(found)} file(s) it includes"] if found else []
                        + [f"the folder {d.name}" for d in directories]))
            if missing:
                # Not an error: the force-field includes GROMACS resolves from
                # its own installation are supposed to be missing here.
                plan.notes.append(
                    "not found beside the topology, so not copied: "
                    + ", ".join(sorted(set(missing))[:8])
                    + ". If grompp needs one of those, add it to 'Also copy in'")

        if kind == "topology":
            plan.outputs["file"] = {"top": source.name, "extra": extra,
                                    "dirs": folders}
        else:
            plan.outputs["file"] = source.name
            if extra:
                plan.notes.append("extra files copied in but not carried on the wire")
        return plan


#: What a file is, by the end of its name.  Shared with the editor, which
#: colours the loader's output with it and creates a dropped file with it --
#: the same table in two languages would drift within a week, so the browser's
#: copy is generated from this one by tools/generate_docs.py.
KIND_BY_SUFFIX = {
    "top": "topology",
    "itp": "file",
    "ndx": "index",
    "mdp": "mdp",
    "xtc": "traj", "trr": "traj", "tng": "traj", "dcd": "traj", "nc": "traj",
    "tpr": "tpr",
    "xvg": "xvg",
    "pdb": "structure", "gro": "structure", "g96": "structure",
    "cif": "structure", "pdbx": "structure", "mmcif": "structure",
    "ent": "structure",
}


def kind_of(name: str) -> str:
    """The declared type a file's name implies, or 'file' when it implies none."""
    suffix = Path(name).suffix.lstrip(".").lower()
    return KIND_BY_SUFFIX.get(suffix, "file")


#: What each kind of file is, in a few plain sentences, for somebody meeting
#: molecular dynamics for the first time. The editor shows the right one when
#: you point at a socket or at a dot on a box's wall, and Help lists them all.
#:
#: Keyed by the kind of file a socket carries. A socket that only says "file"
#: is looked up by its own name instead: an mdrun's energies, checkpoint and
#: log are all plain files as far as wiring goes, but they are nothing alike.
#: tools/smoke_test.py checks that every socket of every block finds an entry
#: here, so a new block cannot arrive without its files being explained.
FILE_GUIDE: Dict[str, Dict[str, str]] = {
    "structure": {
        "name": "Structure", "endings": ".gro, .pdb",
        "what": "Where every atom is at one moment: a single snapshot. A .pdb "
                "file is how the Protein Data Bank shares structures; a .gro "
                "file is GROMACS's own kind, and it also keeps the size of the "
                "box.",
    },
    "topology": {
        "name": "Topology", "endings": ".top",
        "what": "The recipe for the molecules: which atoms there are, which ones "
                "are bonded together, their charges and sizes, and how many of "
                "each molecule the system holds. The structure says where the "
                "atoms are; the topology says how they pull and push on each "
                "other. A .top file often reads in .itp files, one for each kind "
                "of molecule.",
    },
    "mdp": {
        "name": "Run settings", "endings": ".mdp",
        "what": "A plain text list of choices for one run: how many steps, how "
                "long each step is, the temperature, the pressure, and how far "
                "apart atoms still feel each other. The letters stand for "
                "molecular dynamics parameters.",
    },
    "tpr": {
        "name": "Run input", "endings": ".tpr",
        "what": "grompp checks the structure, the topology and the run settings "
                "against each other and packs all three into this one file. "
                "mdrun needs nothing else to start, and the measuring blocks "
                "read it to know which atom is which. It is not text: GROMACS "
                "can read it, a text editor cannot.",
    },
    "traj": {
        "name": "Trajectory", "endings": ".xtc, .trr",
        "what": "The film of the run: the positions of the atoms, saved again "
                "and again while the simulation goes on. An .xtc file keeps "
                "positions only, rounded to a thousandth of a nanometre to save "
                "space; a .trr file keeps them in full, and can hold speeds and "
                "forces too.",
    },
    "index": {
        "name": "Index", "endings": ".ndx",
        "what": "Named lists of atom numbers, such as Protein or Oxygens, so a "
                "block can work on one part of the system and leave out the "
                "rest.",
    },
    "xvg": {
        "name": "Graph data", "endings": ".xvg",
        "what": "A table of numbers ready to plot, such as temperature against "
                "time, with the title and the labels of the axes written at the "
                "top. Plain text; GROMACS's measuring tools all write it.",
    },
    "posre": {
        "name": "Position restraints", "endings": ".itp",
        "what": "A list of atoms to hold near where they started, each on a "
                "spring, while everything around them settles. pdb2gmx writes "
                "one for the protein.",
    },
    "ffdir": {
        "name": "Force field", "endings": "a folder ending in .ff",
        "what": "The rule book for a whole family of molecules: the size, charge "
                "and bond strengths of every kind of atom they are made of. "
                "pdb2gmx reads it to write the topology.",
    },
    # Sockets that only say "file", by their own name.
    "edr": {
        "name": "Energies", "endings": ".edr",
        "what": "Temperature, pressure, the different kinds of energy and more, "
                "noted down many times during the run. 'Energy terms' takes out "
                "the ones you ask for and turns them into a graph.",
    },
    "checkpoint": {
        "name": "Checkpoint", "endings": ".cpt",
        "what": "Everything needed to carry on a run exactly where it stopped, "
                "the speed of every atom included. The next run starts from it, "
                "so the molecules keep moving the way they were.",
    },
    "log": {
        "name": "Log", "endings": ".log",
        "what": "What mdrun wrote while it worked: the settings it used, the "
                "energies every so often, and at the end how fast it ran.",
    },
    "dat": {
        "name": "Secondary structure", "endings": ".dat",
        "what": "One line of letters for every saved frame, one letter for each "
                "piece of the protein: whether it is part of a helix, a strand, "
                "or neither.",
    },
    "radii": {
        "name": "Particle sizes", "endings": ".dat",
        "what": "How big each kind of atom counts as for this measurement. Left "
                "out, GROMACS uses its own list.",
    },
    "file": {
        "name": "A file", "endings": "any",
        "what": "Any file at all. What is inside depends on the block that "
                "wrote it.",
    },
}


def file_guide_for(kind: str, name: str = "") -> Dict[str, str]:
    """The FILE_GUIDE entry for a socket, or {} when there is none."""
    loose = kind in ("file", "any")
    if loose and name in FILE_GUIDE:
        return FILE_GUIDE[name]
    return FILE_GUIDE.get(kind) or (FILE_GUIDE["file"] if loose else {})


class FetchUrlNode(Node):
    type = "io.fetch_url"
    title = "Download file"
    category = CATEGORY
    color = "#2f6b52"
    tool = "shell"
    extra_command = "curl"
    description = (
        "Downloads a file from a web address, and can unpack an archive and pick one "
        "file out of it. Tutorials that ship their input files as a zip are why this "
        "exists."
    )
    outputs = (
        # Typed by the name it will be saved under, the way the loader is
        # typed by the name it was pointed at: a downloaded .pdb is a
        # structure, and a grey wire that connects to anything says less than
        # the file does. "Save as", then the member taken out of an archive,
        # then the tail of the URL -- whichever of them is going to be the
        # name of the file that leaves this node.
        Port("file", "file", "file", follows="output"),
        Port("dir", "ffdir", "directory", optional=True),
    )
    params = (
        Param("url", "str", "URL", "", placeholder="https://example.org/inputs.zip"),
        Param("output", "str", "Save as", "", advanced=True,
              placeholder="blank = the name at the end of the URL"),
        Param("extract", "bool", "Unpack archive", False,
              help="Handles .zip, .tar, .tar.gz/.tgz and .tar.bz2."),
        Param("member", "text", "Files to take out", "", rows=3, form="text.globs",
              placeholder="*/kalp-AA.pdb",
              help="Shell globs matched against the unpacked tree, one per line. Every "
                   "match is copied out: the first one leaves on the 'file' port and "
                   "all of them together on 'dir'. Blank hands on the whole unpacked "
                   "tree instead."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        url = ctx.pstr("url")
        if not url:
            raise NodeError("no URL given")
        if not url.lower().startswith(("http://", "https://", "ftp://")):
            raise NodeError(f"not a downloadable URL: {url}")
        local = ctx.pstr("output") or url.rstrip("/").split("/")[-1].split("?")[0]
        if not local:
            raise NodeError("could not work out a file name; set 'Save as'")
        plan.step(["curl", "-fsSL", "--retry", "3", "-o", local, url] + ctx.extra(),
                  label=f"download {local}")

        if not ctx.pbool("extract"):
            plan.outputs["file"] = local
            return plan

        lower = local.lower()
        if lower.endswith(".zip"):
            unpack = f"unzip -o -q {local} -d unpacked"
        elif lower.endswith((".tar.gz", ".tgz")):
            unpack = f"mkdir -p unpacked && tar -xzf {local} -C unpacked"
        elif lower.endswith((".tar.bz2", ".tbz2")):
            unpack = f"mkdir -p unpacked && tar -xjf {local} -C unpacked"
        elif lower.endswith(".tar"):
            unpack = f"mkdir -p unpacked && tar -xf {local} -C unpacked"
        else:
            raise NodeError(f"do not know how to unpack '{local}'")
        plan.sh(unpack, label=f"unpack {local}")

        globs = [line.strip() for line in ctx.pstr("member").splitlines() if line.strip()]
        if not globs:
            plan.outputs["file"] = {"dir_path": "unpacked"}
            plan.outputs["dir"] = {"dir_path": "unpacked"}
            plan.notes.append("no member glob: the whole unpacked tree goes downstream")
            return plan

        plan.step(["mkdir", "-p", "picked"], label="make picked dir")
        names = []
        for pattern in globs:
            # -path matches the whole relative path, so a bare file name still
            # needs a leading */ from the user. Take the first hit in sorted
            # order: an archive that ships a worked copy of a file alongside the
            # starting one would otherwise pick a different member every run.
            name = pattern.rstrip("/").split("/")[-1]
            if any(ch in name for ch in "*?["):
                raise NodeError(
                    f"'{pattern}' ends in a wildcard; the last element has to be the "
                    "file name so the extracted copy has one"
                )
            names.append(name)
            plan.sh(
                f'__hit=$(find unpacked -path {shlex.quote("unpacked/" + pattern.lstrip("/"))} '
                f'| sort | head -n 1); '
                f'if [ -z "$__hit" ]; then '
                f'echo "no archive member matched {pattern}" >&2; exit 1; fi; '
                f'echo ">> taking $__hit"; cp -f "$__hit" picked/{shlex.quote(name)}',
                label=f"extract {name}",
            )
        plan.sh("cp -f picked/* . 2>/dev/null || true", label="copy members out")
        plan.outputs["file"] = {"file": names[0], "extra": names[1:]}
        plan.outputs["dir"] = {"dir_path": "picked"}
        return plan


NODES = [LoadStructureNode, LoadFileNode, FetchUrlNode]
