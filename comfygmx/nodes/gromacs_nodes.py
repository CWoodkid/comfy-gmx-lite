"""GROMACS nodes: system building, running, and the analysis suite.

Group selections that the command-line tools normally prompt for are exposed as
a "Groups" text box and piped in on stdin, one selection per line.  The rendered
command shown in the UI includes the heredoc, so a copy-paste really does
reproduce the run.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import List, Optional

from .base import Node, NodeError, Param, Plan, PlanContext, Port, local_path

BUILD = "Build system"
RUN = "Run"
ANALYSIS = "Analysis"
TRAJ = "Trajectory tools"

GMX_COLOR = "#2b5d8a"
RUN_COLOR = "#8a4b2b"
ANALYSIS_COLOR = "#3f7a6d"


def _groups(ctx: PlanContext, param: str = "groups") -> Optional[str]:
    """Turn the Groups box into stdin text for an interactive gmx tool."""
    raw = ctx.pstr(param)
    if not raw:
        return None
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines) + "\n" if lines else None


GROUPS_PARAM = Param(
    "groups", "text", "Groups (stdin)", "", rows=2, form="gmx.groups",
    placeholder="one selection per line, name or number",
    help="Piped to the tool's interactive prompts in order. Names work as well as "
         "numbers and survive an index file changing.",
)


# --------------------------------------------------------------------------
# System building
# --------------------------------------------------------------------------

class ForceFieldNode(Node):
    type = "gmx.forcefield"
    title = "Force field directory"
    category = BUILD
    color = GMX_COLOR
    tool = "shell"
    description = (
        "Stages a force field GROMACS does not ship with -- CHARMM36, for instance -- "
        "so pdb2gmx can use it without you needing write access to the GROMACS "
        "installation. Point it at an unpacked *.ff folder or give it an archive to "
        "download. Wire its output into pdb2gmx."
    )
    docs = "https://manual.gromacs.org/current/how-to/topology.html"
    outputs = (Port("ffdir", "ffdir", "force field"),)
    params = (
        Param("source", "choice", "Source", "directory", choices=["directory", "archive URL"]),
        Param("path", "file", "Local .ff directory", "",
              placeholder="/path/to/charmm36-jul2022.ff"),
        Param("url", "str", "Archive URL", "", advanced=True,
              placeholder="https://.../charmm36-feb2026_cgenff-5.0.ff.tgz",
              help="A .tgz/.tar.gz containing the .ff directory; downloaded and unpacked here."),
        Param("name", "str", "Force field name", "", advanced=True,
              placeholder="derived from the directory name",
              help="What to pass to pdb2gmx -ff: the directory name without the .ff suffix."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        source = ctx.pstr("source", "directory")
        if source == "directory":
            raw = ctx.pstr("path")
            if not raw:
                raise NodeError(
                    "no force field directory given. Point 'Local .ff directory' at "
                    "an unpacked *.ff folder, or set Source to 'archive URL' and give "
                    "the .tgz to fetch. If the force field you want is one GROMACS "
                    "ships -- amber*, charmm27, gromos*, oplsaa -- you do not need "
                    "this node at all: name it on pdb2gmx and delete this."
                )
            directory = Path(local_path(raw.rstrip("/")))
            if not ctx.dry and not directory.is_dir():
                raise NodeError(f"not a directory: {directory}")
            local = directory.name
            if not local.endswith(".ff"):
                plan.notes.append(
                    f"'{local}' does not end in .ff; pdb2gmx will not list it"
                )
            plan.sh(f'cp -rfL "{directory}" "{local}"', label=f"copy in {local}")
        else:
            url = ctx.pstr("url")
            if not url:
                raise NodeError("no archive URL given")
            plan.step(["curl", "-fsSL", "--retry", "3", "-o", "ff.tgz", url],
                      label="download force field")
            plan.step(["tar", "xzf", "ff.tgz"], label="unpack")
            # The name inside the archive is not knowable at plan time.
            plan.sh('local=$(find . -maxdepth 1 -type d -name "*.ff" | head -n1); '
                    'echo "unpacked ${local#./}"', label="report unpacked name")
            local = ctx.pstr("name")
            if not local:
                raise NodeError(
                    "set 'Force field name' when downloading: the directory inside the "
                    "archive cannot be known before it is fetched. It is the folder "
                    "name without .ff -- charmm36-jul2022 for "
                    "charmm36-jul2022.ff.tgz -- and it is what pdb2gmx gets as -ff."
                )
            if not local.endswith(".ff"):
                local += ".ff"

        plan.outputs["ffdir"] = {"dir_path": local}
        plan.notes.append(f"pdb2gmx -ff {local[:-3] if local.endswith('.ff') else local}")
        return plan


#: Refuses to hand a coarse-grained structure to an all-atom topology builder.
#: The failure without it is "Incomplete ring in HIS117" a minute later, which
#: names a residue rather than the actual problem, and reads like something to
#: repair rather than the wrong tool entirely.
_CHECK_ALL_ATOM_SCRIPT = r'''#!/usr/bin/env python3
# Is this an all-atom structure, or a coarse-grained one?
#
# Two independent signs, because either alone can be misread:
#
#   * The bead names. Martini gives its beads names no all-atom force field
#     uses -- BB for a protein backbone bead, PO4 and GL1/GL2 for a lipid head
#     and its linkers, C1A/D2B and so on for the tail segments.
#   * How many particles there are per residue. An all-atom amino acid runs
#     from 7 (glycine, with hydrogens) to about 25; a Martini one is 1 to 5.
import collections
import sys

MARTINI_NAMES = {
    "BB", "SC1", "SC2", "SC3", "SC4", "SC5",
    "PO4", "GL1", "GL2", "NC3", "NH3", "CNO", "GL0", "ROH", "AM1", "AM2",
    "W", "WF", "NA+", "CL-",
}


def looks_martini(name):
    if name in MARTINI_NAMES:
        return True
    # Tail beads: a letter, a digit, then A or B -- C1A, D2B, C4A.
    return (len(name) == 3 and name[0] in "CDT" and name[1].isdigit()
            and name[2] in "AB")


def read(path):
    names = collections.Counter()
    residues = set()
    chains = set()
    atoms = 0
    heavy_hydrogen = 0
    lowered = path.lower()
    with open(path, errors="replace") as handle:
        if lowered.endswith(".gro"):
            handle.readline()
            try:
                total = int(handle.readline().strip())
            except ValueError:
                total = 0
            for _ in range(total):
                line = handle.readline()
                if not line:
                    break
                atoms += 1
                names[line[10:15].strip()] += 1
                residues.add(line[0:10].strip())
        else:
            for line in handle:
                if line.startswith(("ATOM", "HETATM")):
                    atoms += 1
                    name = line[12:16].strip()
                    names[name] += 1
                    residues.add((line[21], line[22:27]))
                    if line[21].strip():
                        chains.add(line[21])
                    # Structures solved with neutrons carry deuterium instead
                    # of ordinary hydrogen, and the element column is the only
                    # safe way to spot it. Going by the name instead would
                    # accuse every Martini file in existence: an unsaturated
                    # lipid tail bead is called D2A, D3A and so on, so a
                    # membrane looks like thousands of deuteriums.
                    if line[76:78].strip().upper() == "D":
                        heavy_hydrogen += 1
                elif line.startswith("ENDMDL"):
                    break
    return atoms, len(residues), names, heavy_hydrogen, sorted(chains)


def warn_about_chains(chains, out):
    """Say it now, rather than let somebody find it in the viewer.

    A .gro file has no column for a chain letter. Hand pdb2gmx a sixteen-chain
    complex and ask for a .gro and it does the right thing -- the topology has
    all sixteen as separate molecules -- but the structure comes back as one
    continuous run of residues renumbered from 1, and it looks in every viewer
    like the chains have been welded together. Nothing warns you.
    """
    if len(chains) < 2 or not out.lower().endswith((".gro", ".g96")):
        return
    shown = " ".join(chains[:16]) + (" ..." if len(chains) > 16 else "")
    print("")
    print(f">> this structure has {len(chains)} chains: {shown}")
    print(f">> {out} is a .gro, and a .gro file has no column for a chain")
    print(">> letter. They will not be in it, and the residues come out")
    print(">> numbered straight through from 1, so it will look like one")
    print(">> continuous molecule.")
    print(">>")
    print(">> The topology is fine either way: each chain stays its own")
    print(">> molecule, in its own topol_Protein_chain_*.itp file.")
    print(">>")
    print(">> To keep the letters in the structure too, set 'Chain letters'")
    print(">> on this block to 'keep them: write a PDB instead'. Nothing else")
    print(">> has to change -- every GROMACS step after this reads a PDB.")
    print("")


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        atoms, residues, names, heavy_hydrogen, chains = read(path)
    except OSError as err:
        print(f">> could not read {path}: {err}")
        return 0
    if not atoms or not residues:
        return 0

    warn_about_chains(chains, out)

    if heavy_hydrogen > 10:
        print("")
        print(">> STOPPING: this structure was solved with neutrons, so its")
        print(">> hydrogens are written as deuterium.")
        print(">>")
        print(f">>     {heavy_hydrogen:,} of {atoms:,} particles are deuterium")
        print(">>")
        print(">> No force field has an entry for it. pdb2gmx would stop a long way")
        print(">> further in with something like 'Atom D1 in residue ARG 1 was not")
        print(">> found in rtp entry ARG', which names an atom and not the reason.")
        print(">> The switch that ignores hydrogens does not cover deuterium either:")
        print(">> it goes by the name, and these are not called H.")
        print(">>")
        print(">> What to do:")
        print(">>   * Put a 'Clean structure' node in front of this one and turn on")
        print(">>     'Strip hydrogens'. It drops deuterium as well, and pdb2gmx")
        print(">>     then adds ordinary hydrogens back where the force field wants")
        print(">>     them -- which is what you want anyway.")
        print(">>   * Or start from an X-ray structure of the same protein.")
        print(">>   * If you meant to keep them, turn off 'Check the structure is")
        print(">>     all-atom' on this node.")
        return 1

    beads = sum(count for name, count in names.items() if looks_martini(name))
    share = beads / atoms
    per_residue = atoms / residues
    hydrogens = sum(count for name, count in names.items() if name.startswith("H"))
    # Measured over every structure to hand, coarse-grained and not. The
    # coarse-grained ones carry 73% to 100% Martini bead names and no
    # hydrogens at all; the all-atom one carries none of those names and is
    # half hydrogen. The name share is the test, and plentiful hydrogens are
    # the veto -- an all-atom file straight out of the databank has no
    # hydrogens either, so their absence proves nothing on its own.
    #
    # Particles per residue is reported but not used to decide: one Martini
    # lipid is a single residue of twelve beads, so a membrane sits at 6-10
    # per residue and overlaps the all-atom range.
    if share < 0.40 or hydrogens > atoms * 0.10:
        return 0

    top = ", ".join(f"{name} x{count:,}" for name, count in names.most_common(6))
    print("")
    print(">> STOPPING: this looks like a coarse-grained structure, and this node")
    print(">> builds all-atom topologies.")
    print(">>")
    print(f">>     {atoms:,} particles over {residues:,} residues "
          f"-- {per_residue:.1f} each")
    print(f">>     {share * 100:.0f}% of them carry Martini bead names")
    print(f">>     commonest names: {top}")
    print(">>")
    print(">> In a coarse-grained model one bead stands for several atoms, so there")
    print(">> are no hydrogens, no ring atoms and no atom names an all-atom force")
    print(">> field recognises. pdb2gmx will look for a complete histidine ring,")
    print(">> not find one, and stop with something like 'Incomplete ring in")
    print(">> HIS117' -- which names a residue and hides the real problem.")
    print(">>")
    print(">> What to do instead:")
    print(">>   * A coarse-grained (Martini) system does not go through pdb2gmx")
    print(">>     at all. Its topology is put together from the Martini force-field")
    print(">>     files instead, which this version of Comfy-gmx does not do.")
    print(">>   * If this really is all-atom and the check is wrong, turn off")
    print(">>     'Check the structure is all-atom' on this node.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


class Pdb2gmxNode(Node):
    type = "gmx.pdb2gmx"
    title = "Topology (pdb2gmx)"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx pdb2gmx"
    description = (
        "Reads a protein or nucleic acid structure and writes the two files a "
        "simulation needs: a topology, which says what every atom is and how it is "
        "bonded, and a cleaned-up structure to match. You pick the force field -- the "
        "set of parameters that defines those bonds and charges -- and the water "
        "model. This is normally the first step after tidying a structure up."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-pdb2gmx.html"
    inputs = (
        Port("structure", "structure", "structure"),
        Port("ffdir", "ffdir", "force field", optional=True),
    )
    outputs = (
        Port("structure", "structure", "conf"),
        Port("topology", "topology", "topology"),
        Port("posre", "posre", "posre", optional=True),
    )
    params = (
        Param("forcefield", "choice", "Force field", "charmm36-jul2022",
              choices=["charmm36-jul2022", "charmm27", "amber99sb-ildn", "amber14sb",
                       "oplsaa", "gromos54a7", "amber03", "typed below"],
              help="Everything on this machine: the force fields GROMACS was "
                   "installed with, and any folder ending in .ff in your own "
                   "force-field folder. To add one you have not got, open "
                   "Software & environments and look under Force fields -- "
                   "CHARMM36 and its variants are listed there and fetch "
                   "themselves into the right folder in one click. The list "
                   "here fills in again as soon as that finishes."),
        Param("forcefield_custom", "str", "Force field, typed", "",
              when="forcefield=typed below", placeholder="charmm36-jul2022",
              help="For a force field that is not on this machine yet, or one "
                   "staged by a 'Force field directory' block. It is the folder "
                   "name without the .ff on the end, and it is handed to "
                   "pdb2gmx as -ff."),
        Param("water", "choice", "Water model", "tip3p",
              choices=["tip3p", "tip4p", "tip4pew", "tip5p", "spc", "spce", "none",
                       "typed below"],
              help="Three-site water (tip3p, spc, spce) is the usual choice and the one "
                   "most force fields were fitted with; tip4p and tip5p carry extra "
                   "charge sites and are slower. Each force field only knows some of "
                   "these -- CHARMM36 wants tip3p, AMBER takes tip3p or tip4pew. 'none' "
                   "is for a system with no water at all."),
        Param("water_custom", "str", "Water model, typed", "", when="water=typed below",
              placeholder="tips3p",
              help="For a water model the list does not have: the name must appear in "
                   "the force field's own watermodels.dat."),
        Param("chain_letters", "choice", "Chain letters", "",
              placeholder="lost, as a .gro cannot hold them",
              choices=["", "keep them: write a PDB instead"],
              help="A .gro file has no column for a chain letter. Ask pdb2gmx "
                   "for one and a structure with sixteen chains comes back as "
                   "one continuous run of residues numbered from 1, which is "
                   "why it looks like a single molecule afterwards.\n\n"
                   "The topology is not affected either way: it keeps every "
                   "chain as its own molecule, and you can see them as the "
                   "topol_Protein_chain_A.itp files beside it. What is lost is "
                   "the structure's own record of them, which is what you need "
                   "to look at chains, pick atoms by chain, or make an index "
                   "group per chain.\n\n"
                   "Choosing to keep them writes the structure as a PDB "
                   "instead, which has that column. The chain letters and each "
                   "chain's own residue numbering both survive, and every "
                   "GROMACS step after this reads a PDB just as happily as a "
                   ".gro.",
              advanced=False),
        Param("ignh", "bool", "Ignore input hydrogens (-ignh)", True,
              help="Rebuild hydrogens from the force field. Usually what you want for "
                   "a crystal structure."),
        Param("missing", "bool", "Continue on missing atoms (-missing)", False,
              help="Dangerous: lets pdb2gmx build a topology for an incomplete residue. "
                   "Fix the structure upstream instead when you can."),
        Param("ter", "bool", "Interactive termini (-ter)", False, advanced=True,
              help="When on, add the termini choices to the Groups box."),
        Param("chainsep", "choice", "Chain separation", "id_or_ter", advanced=True,
              choices=["id_or_ter", "id_and_ter", "ter", "id", "interactive"]),
        Param("merge", "choice", "Merge chains", "no", advanced=True,
              choices=["no", "all", "interactive"]),
        Param("posrefc", "float", "Restraint force constant", 1000.0, advanced=True,
              help="kJ mol^-1 nm^-2 written into the posre files."),
        Param("vsite", "choice", "Virtual sites (-vsite)", "none",
              choices=["none", "h", "aromatics"], advanced=True,
              help="Removes the fastest degrees of freedom so a longer time step "
                   "becomes stable. Changes the topology, not just the run settings."),
        Param("check_all_atom", "bool", "Check the structure is all-atom", True,
              advanced=True,
              help="Looks at the structure before running and stops if it is "
                   "coarse-grained -- Martini bead names, no hydrogens. This "
                   "node builds all-atom topologies, and handed beads it "
                   "fails a minute later with something like 'Incomplete ring "
                   "in HIS117', which names a residue and hides the real "
                   "problem. Turn it off only if it is wrong about your file."),
        Param("output", "str", "Output name", "processed.gro", advanced=True),
        GROUPS_PARAM,
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        out = ctx.pstr("output") or "processed.gro"
        if ctx.pstr("chain_letters"):
            # A .gro has nowhere to put a chain letter, so the only way to keep
            # them is to write the other format. Everything downstream reads a
            # PDB as happily, so this changes the ending and nothing else.
            base = out.rsplit(".", 1)[0] if "." in out else out
            out = base + ".pdb"
            plan.notes.append(
                "written as a PDB so the chain letters survive: a .gro file "
                "has no column for them, and would come back as one run of "
                "residues numbered from 1"
            )
        argv: List[str] = ["gmx", "pdb2gmx", "-f", structure, "-o", out, "-p", "topol.top"]

        # A staged directory wins over the typed name: it is what is actually here.
        staged = ctx.inp("ffdir")
        forcefield = ctx.pstr("forcefield")
        if forcefield == "typed below":
            forcefield = ctx.pstr("forcefield_custom").strip()
            if not forcefield and not staged:
                raise NodeError(
                    "the force field box says 'typed below' but nothing is "
                    "typed. Either type the name, or pick one from the list -- "
                    "and if the one you want is not in the list, Software & "
                    "environments has a Force fields section that fetches it."
                )
        if staged:
            staged_name = staged[:-3] if staged.endswith(".ff") else staged
            if forcefield and forcefield != staged_name:
                plan.notes.append(
                    f"using the connected force field '{staged_name}' rather than the "
                    f"'{forcefield}' typed on the node"
                )
            forcefield = staged_name
        if forcefield:
            argv += ["-ff", forcefield]
        else:
            plan.notes.append("no force field set: pdb2gmx will prompt on stdin")
        water = ctx.pstr("water")
        if water == "typed below":
            water = ctx.pstr("water_custom").strip()
            if not water:
                raise NodeError("the water model box says 'typed below' but nothing is typed")
        if water:
            argv += ["-water", water]
        if ctx.pbool("ignh", True):
            argv.append("-ignh")
        if ctx.pbool("missing"):
            argv.append("-missing")
            plan.notes.append("-missing is on: check the topology before trusting it")
        if ctx.pbool("ter"):
            argv.append("-ter")
        chainsep = ctx.pstr("chainsep")
        if chainsep and chainsep != "id_or_ter":
            argv += ["-chainsep", chainsep]
        merge = ctx.pstr("merge")
        if merge and merge != "no":
            argv += ["-merge", merge]
        posrefc = ctx.pfloat("posrefc", 1000.0)
        if posrefc and posrefc != 1000.0:
            argv += ["-posrefc", str(posrefc)]
        vsite = ctx.pstr("vsite", "none")
        if vsite and vsite != "none":
            argv += ["-vsite", vsite]
            plan.notes.append(
                f"-vsite {vsite}: the topology now contains virtual sites, so every "
                "later stage must use this topology"
            )

        # Before anything runs: is this even the right kind of structure? A
        # coarse-grained file gets a long way into pdb2gmx before failing on a
        # residue that is not the problem.
        if ctx.pbool("check_all_atom", True):
            plan.files["check_all_atom.py"] = _CHECK_ALL_ATOM_SCRIPT
            plan.step(["python3", "check_all_atom.py", structure, out],
                      tool="shell",
                      label="check the structure is all-atom")

        plan.step(argv + ctx.extra(), tool="gmx", label="gmx pdb2gmx", stdin=_groups(ctx))
        plan.outputs["structure"] = out
        plan.outputs["topology"] = {
            "top": "topol.top", "glob": ["*.itp", "*.prm"],
            # pdb2gmx writes a relative #include to the force field, so the
            # directory has to travel with the topology.
            "dirs": [staged] if staged else [],
        }
        plan.outputs["posre"] = {"glob": ["posre*.itp"]}
        return plan


class EditconfNode(Node):
    type = "gmx.editconf"
    title = "Define box (editconf)"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx editconf"
    description = (
        "Puts the molecule in a box, which is what a simulation actually runs "
        "in.\n\n"
        "The distance you set is the gap between the molecule and the wall. Too "
        "small and the molecule feels the copy of itself in the next box across "
        "the boundary, which is a common and quiet way to get wrong answers; "
        "1.0 nm is the usual smallest and 1.2 the usual choice.\n\n"
        "Right-click the node and choose \"Pick the box by eye\" to see the "
        "molecule drawn inside the box, what each shape costs in water, and how "
        "close the molecule comes to its own image -- rather than typing a "
        "number and hoping."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-editconf.html"
    inputs = (Port("structure", "structure", "structure"),)
    outputs = (Port("structure", "structure", "conf"),)
    params = (
        Param("box_type", "choice", "Box type", "dodecahedron",
              choices=["cubic", "triclinic", "dodecahedron", "octahedron"],
              help="All four leave the same room around the molecule and differ "
                   "only in how much of the corners is cut off -- which is water "
                   "you would otherwise pay to simulate.\n\n"
                   "A rhombic dodecahedron holds about 29% less water than a "
                   "cube, and a truncated octahedron about 23% less. For a "
                   "roughly round molecule the dodecahedron is the usual "
                   "choice.\n\n"
                   "Right-click and choose \"Pick the box by eye\" to see the "
                   "difference in actual numbers of water molecules."),
        Param("distance", "float", "Solute-box distance (nm)", 1.2, min=0.0, step=0.1,
              help="The gap between your molecule and the wall, so the closest "
                   "it comes to the copy of itself in the next box is twice "
                   "this.\n\n"
                   "It has to be more than the force field's cutoff -- usually "
                   "1.2 nm -- or the molecule interacts with its own image and "
                   "the run is quietly wrong. 1.0 nm is the usual smallest, 1.2 "
                   "the usual choice. Bigger is safer and costs water, and water "
                   "is most of what a run spends its time on.\n\n"
                   "The box GROMACS builds is this gap at each end plus the "
                   "distance between the two atoms of your molecule that are "
                   "furthest apart -- not its width. A long thin molecule "
                   "therefore needs a big box however thin it is.\n\n"
                   "'Pick it by eye' draws the molecule with the box around "
                   "it, and says for each shape how many water molecules it "
                   "would hold and how close your molecule comes to the copy "
                   "of itself next door."),
        Param("center", "bool", "Centre in box (-c)", True),
        Param("box", "str", "Explicit box (nm)", "",
              placeholder="e.g. 12 12 14 -- overrides the distance",
              help="Set this when the box size is dictated by a membrane patch, "
                   "or when you are building a system in layers and every piece "
                   "has to end up in the same unit cell."),
        Param("centre_at", "str", "Put the middle here (nm)", "",
              placeholder="e.g. 2.15 2.15 2.15",
              help="Where in the box the middle of the molecule goes, as three "
                   "numbers measured from the corner. Blank puts it in the "
                   "middle, which is what 'Centre in box' means.\n\n"
                   "This is how a system is built in layers. GROMACS measures "
                   "every box from the corner at (0,0,0), so to keep a slab "
                   "where it is while making the box twice as tall you ask for "
                   "the same box and a middle a quarter of the way up -- and to "
                   "put a second thing in the top half, three quarters of the "
                   "way up. Without it, asking for a taller box simply moves "
                   "the slab to the middle of it."),
        Param("princ", "bool", "Align principal axes (-princ)", False, advanced=True,
              help="Rotates the solute; needs a group on stdin."),
        Param("output", "str", "Output name", "boxed.gro", advanced=True),
        GROUPS_PARAM,
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        out = ctx.pstr("output") or "boxed.gro"
        argv = ["gmx", "editconf", "-f", structure, "-o", out]
        # An explicit middle replaces -c rather than joining it: -c means "in
        # the middle of the box", and asking for both is asking for two
        # different places at once. GROMACS takes the last one and says
        # nothing, which is how a layer quietly ends up centred.
        centre_at = ctx.pstr("centre_at").replace(",", " ").split()
        if centre_at:
            if len(centre_at) != 3:
                raise NodeError(
                    "'Put the middle here' wants three numbers -- x, y and z in "
                    f"nm, measured from the corner of the box. Got {len(centre_at)}: "
                    + " ".join(centre_at))
            argv += ["-center"] + centre_at
            plan.notes.append(
                "the middle of the molecule is put at "
                + ", ".join(centre_at) + " nm rather than in the middle of the box")
        elif ctx.pbool("center", True):
            argv.append("-c")
        box = ctx.pstr("box")
        shape = ctx.pstr("box_type", "dodecahedron")
        if box:
            argv += ["-box"] + box.replace(",", " ").split()
            # -box gives the lengths and -bt reshapes them, so asking for
            # "4.3 4.3 8.6" and leaving the shape at dodecahedron builds a
            # dodecahedron with those edges -- a 56 nm3 box where 160 was
            # wanted, reported only as a line of numbers in the log. If you
            # typed the lengths you meant a plain rectangular box.
            if shape != "triclinic":
                plan.notes.append(
                    f"box shape forced to triclinic: an explicit box of "
                    f"'{box}' gives the three edge lengths, and a "
                    f"{shape} would fold them into a different shape with "
                    "a smaller volume. Clear the explicit box if you wanted "
                    f"a {shape}.")
            shape = "triclinic"
        else:
            argv += ["-d", str(ctx.pfloat("distance", 1.2))]
        argv += ["-bt", shape]
        if ctx.pbool("princ"):
            argv.append("-princ")
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx editconf", stdin=_groups(ctx))
        plan.outputs["structure"] = out
        return plan


#: Builds a vdwradii.dat in the run folder, starting from the one GROMACS
#: ships and changing only the elements named.  `gmx solvate` looks in the
#: working directory before it looks in its own share directory, which is how
#: this takes effect without any flag.
_RADII_SCRIPT = r"""
set -e
__src=""
for __try in "$GMXDATA/top/vdwradii.dat" "$GMXLIB/vdwradii.dat"; do
  [ -f "$__try" ] && {{ __src="$__try"; break; }}
done
if [ -z "$__src" ]; then
  echo ">> cannot find GROMACS's own vdwradii.dat to start from." >&2
  echo ">> It is normally at \$GMXDATA/top/vdwradii.dat. Is GMXRC sourced?" >&2
  exit 1
fi
cp "$__src" vdwradii.dat
for __pair in {edits}; do
  __name=${{__pair%%=*}}
  __value=${{__pair#*=}}
  # The file is "residue element radius", three columns, and '???' means any
  # residue. Only the wildcard rows are touched: a force field that names a
  # residue explicitly meant it.
  awk -v n="$__name" -v v="$__value" \
    '{{ if ($1 == "???" && toupper($2) == n) {{ printf "%-4s %-5s %s\n", $1, $2, v; next }} print }}' \
    vdwradii.dat > vdwradii.tmp && mv vdwradii.tmp vdwradii.dat
  echo ">> $__name is treated as $__value nm while the water is poured"
done
echo ">> vdwradii.dat written here, so solvate reads it instead of its own"
"""


class SolvateNode(Node):
    type = "gmx.solvate"
    title = "Solvate"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx solvate"
    description = (
        "Fills the empty space in the box with water, and adds the water it added to "
        "the topology's molecule list so the two agree. Without this the protein is "
        "simulated in vacuum."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-solvate.html"
    inputs = (
        Port("structure", "structure", "structure"),
        Port("topology", "topology", "topology", optional=True),
        Port("solvent_box", "structure", "solvent box", optional=True),
    )
    outputs = (
        Port("structure", "structure", "conf"),
        Port("topology", "topology", "topology", optional=True),
    )
    params = (
        Param("solvent", "combo", "Solvent box", "spc216.gro",
              choices=["spc216.gro", "tip4p.gro", "tip5p.gro", "water.gro"],
              help="spc216.gro works for every 3-point water model, TIP3P included; "
                   "tip4p.gro and tip5p.gro are for the 4- and 5-point models."),
        Param("scale", "float", "van der Waals scale (-scale)", 0.57, step=0.01, advanced=True,
              help="0.57 is GROMACS's own default: it gives a density close to "
                   "1000 g/l for a protein in water."),
        Param("maxsol", "int", "Max solvent molecules", 0, advanced=True,
              help="0 = fill the box completely."),
        Param("shell", "float", "Solvent shell (nm)", 0.0, advanced=True,
              help="Non-zero solvates only a shell around the solute."),
        Param("radius", "float", "Default vdW radius (-radius, nm)", 0.0, advanced=True,
              help="The size given to atoms that GROMACS's list of atom sizes does "
                   "not cover. 0 leaves GROMACS's own value, 0.105 nm."),
        Param("keep_water_out", "text", "Keep water out of (element, radius)", "",
              rows=3, advanced=True, placeholder="C 0.35",
              help="How big each kind of atom is treated as being, when solvate "
                   "decides whether a water will fit. One 'element radius' per "
                   "line, in nm.\n\n"
                   "Why you would want it: solvate only asks whether a water "
                   "overlaps an atom, so it happily fills the inside of an oil "
                   "layer, a lipid tail region or any other loosely packed "
                   "hydrophobic space -- water where no water belongs. Making "
                   "carbon bigger than it really is, 0.35 instead of 0.17, "
                   "closes those gaps.\n\n"
                   "This writes a vdwradii.dat beside the run, starting from "
                   "GROMACS's own and changing only the lines you name. It "
                   "affects nothing but where the waters are put; the run "
                   "afterwards uses the force field's real radii."),
        Param("output", "str", "Output name", "solvated.gro", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        out = ctx.pstr("output") or "solvated.gro"
        argv = ["gmx", "solvate", "-cp", structure, "-o", out]
        # A connected box wins: the named ones come from GROMACS' own share
        # directory and none of them is a Martini solvent.
        solvent = ctx.inp("solvent_box") or ctx.pstr("solvent")
        if solvent:
            argv += ["-cs", solvent]
        top = ctx.inp("topology")
        if top:
            argv += ["-p", top]
        else:
            plan.notes.append("no topology connected: [ molecules ] will not be updated")
        scale = ctx.pfloat("scale", 0.57)
        if scale and abs(scale - 0.57) > 1e-9:
            argv += ["-scale", str(scale)]
        maxsol = ctx.pint("maxsol", 0)
        if maxsol > 0:
            argv += ["-maxsol", str(maxsol)]
        shell = ctx.pfloat("shell", 0.0)
        if shell > 0:
            argv += ["-shell", str(shell)]
        radius = ctx.pfloat("radius", 0.0)
        if radius > 0:
            argv += ["-radius", str(radius)]

        # A radius table of our own, if asked for. solvate reads vdwradii.dat
        # from the working directory in preference to the one it ships, which
        # is a real feature and a well hidden one -- the tutorial that needs it
        # says "copy the file from $GMXLIB and edit it", and every reader then
        # has to find $GMXLIB.
        wanted = []
        for number, line in enumerate(ctx.pstr("keep_water_out").splitlines(), 1):
            line = line.split(";")[0].split("#")[0].strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) != 2:
                raise NodeError(
                    f"line {number} of 'Keep water out of' ({line!r}): one "
                    "element and one radius in nm per line, like 'C 0.35'.")
            try:
                float(parts[1])
            except ValueError:
                raise NodeError(
                    f"line {number} of 'Keep water out of' ({line!r}): "
                    f"'{parts[1]}' is not a number of nanometres.") from None
            wanted.append((parts[0].upper(), parts[1]))
        if wanted:
            edits = " ".join(f"{name}={value}" for name, value in wanted)
            # tool="gmx" rather than "shell": the file to start from lives in
            # GROMACS's own share directory, and only sourcing GMXRC says where
            # that is. A plain shell step has never heard of $GMXDATA.
            plan.sh(_RADII_SCRIPT.format(edits=shlex.quote(edits)),
                    tool="gmx", label="a radius table with your changes in it")
            plan.notes.append(
                "solvate will read vdwradii.dat from this folder rather than "
                "GROMACS's own: " + ", ".join(f"{n} {v} nm" for n, v in wanted))

        plan.step(argv + ctx.extra(), tool="gmx", label="gmx solvate")
        plan.outputs["structure"] = out
        if top:
            plan.outputs["topology"] = {"top": top, "glob": ["*.itp", "*.prm"],
                                        "dirs": ctx.staged_dirs("topology")}
        return plan


class GenionNode(Node):
    type = "gmx.genion"
    title = "Add ions"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx genion"
    description = (
        "Adds ions: enough to cancel the system's net charge, plus any salt you want "
        "at a chosen concentration. A charged box is not physical, so this is not "
        "optional. It also runs the throwaway preprocessing step genion needs, so you "
        "do not have to wire one up yourself."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-genion.html"
    inputs = (
        Port("structure", "structure", "structure"),
        Port("topology", "topology", "topology"),
        Port("mdp", "mdp", "mdp", optional=True),
        Port("index", "index", "index", optional=True),
    )
    outputs = (
        Port("structure", "structure", "conf"),
        Port("topology", "topology", "topology"),
    )
    params = (
        Param("neutral", "bool", "Neutralise (-neutral)", True),
        Param("concentration", "float", "Salt concentration (M)", 0.15, min=0.0, step=0.01,
              help="0 adds only the counter-ions needed for neutrality."),
        Param("pname", "combo", "Positive ion", "NA", choices=["NA", "K", "CA", "MG", "TMA"]),
        Param("nname", "combo", "Negative ion", "CL", choices=["CL", "BR", "IOD"]),
        Param("pq", "int", "Positive charge", 1, advanced=True),
        Param("nq", "int", "Negative charge", -1, advanced=True),
        Param("solvent_group", "str", "Group to replace", "SOL",
              help="The molecules swapped for ions: SOL, the water, in almost every "
                   "system."),
        Param("maxwarn", "int", "grompp -maxwarn", 1, advanced=True,
              help="The ion-generation grompp usually warns about a non-zero system "
                   "charge, which is exactly what this node is about to fix."),
        Param("output", "str", "Output name", "ions.gro", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        top = ctx.require("topology")
        out = ctx.pstr("output") or "ions.gro"

        mdp = ctx.inp("mdp")
        if not mdp:
            mdp = "ions.mdp"
            plan.files[mdp] = (
                "; minimal mdp, only used so grompp can write a tpr for genion\n"
                "integrator = steep\n"
                "nsteps     = 0\n"
                "cutoff-scheme = Verlet\n"
                "rcoulomb   = 1.1\n"
                "rvdw       = 1.1\n"
            )

        # -r as well as -c: a Martini minimisation mdp often carries
        # define = -DPOSRES, and grompp refuses to guess the reference.
        grompp = ["gmx", "grompp", "-f", mdp, "-c", structure, "-r", structure,
                  "-p", top, "-o", "ions.tpr",
                  "-maxwarn", str(ctx.pint("maxwarn", 1))]
        index = ctx.inp("index")
        if index:
            grompp += ["-n", index]
            index_guard(plan, index, structure)
        plan.step(grompp, tool="gmx", label="gmx grompp (for genion)")

        argv = ["gmx", "genion", "-s", "ions.tpr", "-o", out, "-p", top]
        if index:
            argv += ["-n", index]
        if ctx.pbool("neutral", True):
            argv.append("-neutral")
        conc = ctx.pfloat("concentration", 0.15)
        if conc > 0:
            argv += ["-conc", str(conc)]
        argv += ["-pname", ctx.pstr("pname", "NA"), "-nname", ctx.pstr("nname", "CL")]
        pq, nq = ctx.pint("pq", 1), ctx.pint("nq", -1)
        if pq != 1:
            argv += ["-pq", str(pq)]
        if nq != -1:
            argv += ["-nq", str(nq)]
        solvent = ctx.pstr("solvent_group", "SOL") or "SOL"
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx genion", stdin=solvent + "\n")

        plan.outputs["structure"] = out
        plan.outputs["topology"] = {"top": top, "glob": ["*.itp", "*.prm"],
                                    "dirs": ctx.staged_dirs("topology")}
        return plan


class InsertMoleculesNode(Node):
    type = "gmx.insert_molecules"
    title = "Insert molecules"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx insert-molecules"
    description = (
        "Packs copies of a molecule into a box without letting them overlap. Use it "
        "to add ligands, or a handful of lipids, to a system that already exists."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-insert-molecules.html"
    inputs = (
        Port("structure", "structure", "box", optional=True),
        Port("insert", "structure", "molecule"),
    )
    outputs = (Port("structure", "structure", "conf"),)
    params = (
        Param("nmol", "int", "Copies", 10, min=1),
        Param("try_count", "int", "Insertion attempts", 500, advanced=True),
        Param("radius", "float", "Exclusion radius (nm)", 0.0, advanced=True,
              help="0 uses the van der Waals radii from the database."),
        Param("seed", "int", "Random seed", 0, advanced=True, help="0 = pick one at random."),
        Param("box", "str", "Box (nm)", "", advanced=True,
              placeholder="10 10 10",
              help="Required when nothing is connected to the box port. Setting it "
                   "alongside a connected structure resizes that box before packing, "
                   "which is how a peptide alone becomes a peptide plus lipids."),
        Param("output", "str", "Output name", "inserted.gro", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "inserted.gro"
        argv = ["gmx", "insert-molecules", "-ci", ctx.require("insert"),
                "-nmol", str(ctx.pint("nmol", 10)), "-o", out]
        box_structure = ctx.inp("structure")
        box = ctx.pstr("box")
        if box_structure:
            argv += ["-f", box_structure]
        elif not box:
            raise NodeError("connect a box structure or set an explicit box")
        if box:
            argv += ["-box"] + box.replace(",", " ").split()
        tries = ctx.pint("try_count", 500)
        if tries and tries != 10:
            argv += ["-try", str(tries)]
        radius = ctx.pfloat("radius", 0.0)
        if radius > 0:
            argv += ["-radius", str(radius)]
        seed = ctx.pint("seed", 0)
        if seed:
            argv += ["-seed", str(seed)]
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx insert-molecules")
        plan.outputs["structure"] = out
        return plan


class MakeNdxNode(Node):
    type = "gmx.make_ndx"
    title = "Index groups (make_ndx)"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx make_ndx"
    description = (
        "Makes an index file: named groups of atoms -- 'the protein', 'the lipid "
        "headgroups' -- that later steps can refer to. The commands box is passed "
        "straight to make_ndx, so it reads exactly like the interactive session you "
        "would otherwise type by hand."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-make-ndx.html"
    inputs = (
        Port("structure", "structure", "structure"),
        Port("index", "index", "existing index", optional=True),
    )
    outputs = (Port("index", "index", "index"),)
    params = (
        Param("commands", "text", "make_ndx commands", "q\n", rows=6, form="gmx.ndx",
              placeholder='a P*\nname NEW PHOSPHATES\n"Protein" | "PHOSPHATES"\nq',
              help="One command per line. The trailing q is added for you if you "
                   "forget it.\n\n"
                   "Write NEW where make_ndx wants the number of the group you "
                   "have just made. make_ndx will only rename a group by its "
                   "number, and that number depends on how many groups it "
                   "invented for your system before you started -- which is "
                   "different for a protein in water and a protein in a "
                   "membrane, and has changed between GROMACS versions. NEW "
                   "counts it for you at the time, so 'name NEW Chain_A' "
                   "always renames the group the line above created."),
        Param("output", "str", "Output name", "index.ndx", advanced=True),
    )

    #: make_ndx commands that do not add a group. Everything else adds exactly
    #: one, which is how NEW knows what to count.
    _NOT_A_NEW_GROUP = ("name", "del", "keep", "q", "h", "help", "l", "list",
                        "case", "splitch", "splitres", "splitat")

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "index.ndx"
        make_folder(plan, out)
        structure = ctx.require("structure")
        argv = ["gmx", "make_ndx", "-f", structure, "-o", out]
        existing = ctx.inp("index")
        if existing:
            argv += ["-n", existing]
            index_guard(plan, existing, ctx.require("structure"))
        commands = [ln for ln in ctx.pstr("commands").splitlines()]
        while commands and not commands[-1].strip():
            commands.pop()
        if not commands or commands[-1].strip().lower() != "q":
            commands.append("q")

        made = 0
        offsets = []
        rewritten = []
        for line in commands:
            first = line.strip().split(" ")[0].lower() if line.strip() else ""
            if "NEW" in line.split("#")[0]:
                if made == 0:
                    raise NodeError(
                        "NEW means \"the group the line above just made\", and "
                        "nothing above this line makes one:\n\n    " + line.strip())
                if first in ("splitch", "splitres", "splitat"):
                    raise NodeError(
                        "splitting makes several groups at once, so NEW has "
                        "nothing single to point at:\n\n    " + line.strip())
                line = line.replace("NEW", "@%d@" % len(offsets), 1)
                offsets.append(made - 1)
            if first and first not in self._NOT_A_NEW_GROUP:
                made += 1
            rewritten.append(line)

        if not offsets:
            plan.step(argv + ctx.extra(), tool="gmx", label="gmx make_ndx",
                      stdin="\n".join(commands) + "\n")
            plan.outputs["index"] = out
            return plan

        # Ask make_ndx what groups it would invent for this structure on its
        # own -- typing nothing but q writes exactly those -- and count them.
        # The first group anything here makes is numbered after the last of
        # them, and each command after that adds one.
        probe = ["gmx", "make_ndx", "-f", structure, "-o", "_group_count.ndx"]
        if existing:
            probe += ["-n", existing]
        plan.step(probe, tool="gmx", stdin="q\n",
                  label="count the groups this structure already has")

        # printf rather than a here-document: the shell step is written out
        # indented, and an indented here-document terminator does not end
        # anything -- the script then runs off the end of the file.
        written = " ".join(shlex.quote(line) for line in rewritten)
        subs = "; ".join("s/@%d@/$((start+%d))/g" % (i, off)
                         for i, off in enumerate(offsets))
        plan.sh(
            "start=$(grep -c '^\\[' _group_count.ndx)\n"
            'echo "this structure already has $start groups, numbered 0 to $((start-1))"\n'
            "printf '%s\\n' " + written + " > _ndx_commands.txt\n"
            'sed -i "' + subs + '" _ndx_commands.txt\n'
            "echo '--- what make_ndx is being told ---'\n"
            "cat _ndx_commands.txt\n"
            "echo '-----------------------------------'\n"
            + " ".join(shlex.quote(a) for a in ["{cmd}"] + argv[1:] + list(ctx.extra()))
            + " < _ndx_commands.txt",
            tool="gmx", label="gmx make_ndx")
        plan.outputs["index"] = out
        return plan


class SelectNode(Node):
    type = "gmx.select"
    title = "Selection to index"
    category = BUILD
    color = GMX_COLOR
    tool = "gmx"
    extra_command = "gmx select"
    description = (
        "Turns a selection written in GROMACS's own selection language into an index "
        "group -- a more expressive way of picking atoms than make_ndx, when the group "
        "you want is 'within 0.5 nm of the protein' rather than a fixed list."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-select.html"
    inputs = (
        Port("structure", "structure", "structure"),
        Port("traj", "traj", "trajectory", optional=True),
    )
    outputs = (Port("index", "index", "index"),)
    params = (
        Param("selection", "text", "Selection", 'name BB', rows=3, form="gmx.select",
              placeholder='"TM" resid 520 to 555 and name BB'),
        Param("output", "str", "Output name", "selection.ndx", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        selection = ctx.pstr("selection")
        if not selection:
            raise NodeError("selection is empty")
        out = ctx.pstr("output") or "selection.ndx"
        make_folder(plan, out)
        argv = ["gmx", "select", "-s", ctx.require("structure"), "-on", out,
                "-select", selection]
        traj = ctx.inp("traj")
        if traj:
            argv += ["-f", traj]
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx select")
        plan.outputs["index"] = out
        return plan


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

class GromppNode(Node):
    type = "gmx.grompp"
    title = "Preprocess (grompp)"
    category = RUN
    color = RUN_COLOR
    tool = "gmx"
    extra_command = "gmx grompp"
    description = (
        "Bundles the structure, the topology and the settings file into the single "
        "input file that mdrun reads -- a .tpr. Think of it as packing everything the "
        "run needs into one box, and checking on the way that it all fits together. "
        "Most mistakes in a workflow surface here rather than during the run itself, "
        "which is a good thing: it takes seconds instead of hours."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-grompp.html"
    inputs = (
        Port("mdp", "mdp", "mdp"),
        Port("structure", "structure", "conf"),
        Port("topology", "topology", "topology"),
        Port("restraint", "structure", "restraint (-r)", optional=True),
        Port("index", "index", "index", optional=True),
        Port("checkpoint", "file", "checkpoint (-t)", optional=True),
    )
    outputs = (Port("tpr", "tpr", "tpr"),)
    params = (
        Param("output", "str", "Output name", "topol.tpr"),
        Param("maxwarn", "int", "-maxwarn", 0,
              help="Read every warning before raising this. A warning grompp emits is "
                   "usually about something that will bite during the run."),
        Param("restraint_from_conf", "bool", "Use conf as -r when unconnected", True,
              help="A restrained run needs reference coordinates; without -r grompp in "
                   "recent GROMACS refuses rather than guessing."),
        Param("output_mdp", "str", "Processed mdp name", "mdout.mdp", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "topol.tpr"
        structure = ctx.require("structure")
        argv = ["gmx", "grompp",
                "-f", ctx.require("mdp"),
                "-c", structure,
                "-p", ctx.require("topology"),
                "-o", out,
                "-po", ctx.pstr("output_mdp", "mdout.mdp") or "mdout.mdp"]
        restraint = ctx.inp("restraint")
        if restraint:
            argv += ["-r", restraint]
        elif ctx.pbool("restraint_from_conf", True):
            argv += ["-r", structure]
        index = ctx.inp("index")
        if index:
            argv += ["-n", index]
            index_guard(plan, index, structure)
        checkpoint = ctx.inp("checkpoint")
        if checkpoint:
            argv += ["-t", checkpoint]
        maxwarn = ctx.pint("maxwarn", 0)
        if maxwarn:
            argv += ["-maxwarn", str(maxwarn)]
            plan.notes.append(f"-maxwarn {maxwarn}: warnings are being suppressed")
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx grompp")
        plan.outputs["tpr"] = out
        return plan


class MdrunNode(Node):
    type = "gmx.mdrun"
    title = "Run MD (mdrun)"
    category = RUN
    color = RUN_COLOR
    tool = "gmx"
    extra_command = "gmx mdrun"
    description = (
        "Runs the simulation. This is the step that takes the time -- minutes for an "
        "energy minimisation, hours or days for production. Leave the thread counts "
        "at 0 and GROMACS works out how to use the machine, which is the right answer "
        "on a workstation you are not sharing. The tpr socket on the right hands "
        "back the same run file this was given, unchanged. Anything that reads a "
        "trajectory needs one beside it to know what the particles are, so taking "
        "both from here saves running a second wire back past this block to "
        "whichever one built it."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-mdrun.html"
    inputs = (
        Port("tpr", "tpr", "tpr"),
        Port("checkpoint", "file", "checkpoint (-cpi)", optional=True),
        Port("rerun", "traj", "walk through this instead (-rerun)", optional=True),
    )
    outputs = (
        Port("structure", "structure", "final conf"),
        Port("traj", "traj", "trajectory"),
        Port("edr", "file", "energy"),
        Port("log", "file", "log"),
        Port("checkpoint", "file", "checkpoint"),
        # The run file it was handed, straight back out. Everything that reads
        # a trajectory needs one beside it, and this is where that bites most:
        # without this socket, every analysis after a simulation needed a
        # second wire running all the way back past mdrun to the block that
        # built the run file. Called "tpr", like every other socket carrying
        # one; the description says what it is.
        Port("tpr", "tpr", "tpr"),
    )
    params = (
        Param("deffnm", "str", "Output prefix (-deffnm)", "md"),
        Param("ntomp", "int", "OpenMP threads (-ntomp)", 0, min=0,
              help="0: Comfy-gmx gives the simulation the cores nothing else is using "
                   "(Settings → This computer), and GROMACS picks when the computer is "
                   "free. A number here is used as it is."),
        Param("ntmpi", "int", "MPI ranks (-ntmpi)", 0, min=0),
        Param("gpu_id", "str", "GPU ids (-gpu_id)", "", placeholder="e.g. 0 or 01"),
        Param("nb", "choice", "Non-bonded on", "auto", choices=["auto", "cpu", "gpu"], advanced=True),
        Param("pme", "choice", "PME on", "auto", choices=["auto", "cpu", "gpu"], advanced=True),
        Param("bonded", "choice", "Bonded on", "auto", choices=["auto", "cpu", "gpu"], advanced=True),
        Param("update", "choice", "Update on", "auto", choices=["auto", "cpu", "gpu"], advanced=True,
              help="GPU update gives a large speedup but is incompatible with several "
                   "features, including pressure coupling with virtual sites."),
        Param("nsteps", "int", "Override nsteps", -2, advanced=True,
              help="-2 means 'use the value in the tpr'. -1 runs until -maxh."),
        Param("maxh", "float", "Wall-clock limit (h)", 0.0, advanced=True,
              help="Writes a checkpoint and stops cleanly just before this time."),
        Param("resume", "bool", "Resume from checkpoint (-cpi)", False,
              help="Continues an interrupted run using <prefix>.cpt in this directory."),
        Param("noappend", "bool", "-noappend", False, advanced=True),
        Param("pin", "choice", "Thread pinning (-pin)", "auto", choices=["auto", "on", "off"],
              advanced=True),
        Param("v", "bool", "Verbose (-v)", True,
              help="Prints step/time lines, which is what drives the progress readout."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        deffnm = ctx.pstr("deffnm", "md") or "md"
        argv = ["gmx", "mdrun", "-s", ctx.require("tpr"), "-deffnm", deffnm]
        if ctx.pbool("v", True):
            argv.append("-v")

        defaults = (ctx.settings.get("mdrun") if ctx.settings else {}) or {}
        ntomp = ctx.pint("ntomp", 0) or int(defaults.get("ntomp") or 0)
        ntmpi = ctx.pint("ntmpi", 0) or int(defaults.get("ntmpi") or 0)
        gpu_id = ctx.pstr("gpu_id") or str(defaults.get("gpu_id") or "")
        if ntomp:
            argv += ["-ntomp", str(ntomp)]
        if not ntmpi and ntomp:
            # GROMACS refuses -ntomp without -ntmpi once a GPU is in play, since
            # the two together over-determine the task assignment. One rank is
            # the right answer on a single workstation.
            ntmpi = 1
            plan.notes.append("-ntmpi 1 added: GROMACS rejects -ntomp on its own when a GPU is detected")
        if ntmpi:
            argv += ["-ntmpi", str(ntmpi)]
        if gpu_id:
            argv += ["-gpu_id", gpu_id]
        for flag in ("nb", "pme", "bonded", "update"):
            value = ctx.pstr(flag, "auto")
            if value and value != "auto":
                argv += [f"-{flag}", value]
        pin = ctx.pstr("pin", "auto")
        if pin and pin != "auto":
            argv += ["-pin", pin]
        nsteps = ctx.pint("nsteps", -2)
        if nsteps != -2:
            argv += ["-nsteps", str(nsteps)]
        maxh = ctx.pfloat("maxh", 0.0)
        if maxh > 0:
            argv += ["-maxh", str(maxh)]

        # Walking through a finished trajectory instead of simulating: every
        # frame is read from a file and its energy worked out again, with
        # whatever the run settings now ask to be reported separately. It is
        # how a protein-ligand interaction energy is obtained -- you cannot
        # ask for it after the fact any other way, because GROMACS only keeps
        # the totals unless it was told in advance to split them.
        rerun = ctx.inp("rerun")
        if rerun:
            argv += ["-rerun", rerun]
            plan.notes.append(
                "no simulation here: every frame of the connected trajectory "
                "is read back and its energy worked out again. Nothing moves, "
                "so the trajectory this writes is the one it read")

        checkpoint = ctx.inp("checkpoint")
        rename_parts = False
        if rerun and checkpoint:
            # Two different jobs: one carries a stopped run on, the other
            # reads a finished one back. Walking through wins, and the node
            # says so rather than quietly dropping the other wire.
            plan.notes.append(
                "a checkpoint is connected as well, and is being ignored: "
                "walking back through a trajectory does not continue anything, "
                "so there is nothing for it to continue from")
            checkpoint = ""
        if checkpoint:
            argv += ["-cpi", checkpoint]
            # The checkpoint was made in another node's folder, and only the
            # checkpoint itself was carried over. mdrun wants to go on writing
            # the log, trajectory and energy files it remembers; they are not
            # here, so it stops with "Some output files listed in the
            # checkpoint file are not present" and continues nothing.
            #
            # -noappend tells it to start fresh files instead. Those come out
            # called <prefix>.partNNNN.<ext>, which no other node would know to
            # look for, so a second step puts the ordinary names back.
            if not ctx.pbool("noappend"):
                argv.append("-noappend")
                rename_parts = True
                plan.notes.append(
                    "-noappend added: this run continues from another node's "
                    "checkpoint, and the files it would append to are not in "
                    "this folder")
        elif ctx.pbool("resume"):
            argv += ["-cpi", f"{deffnm}.cpt"]
        if ctx.pbool("noappend"):
            argv.append("-noappend")

        extra = ctx.extra() or str(defaults.get("extra") or "").split()
        plan.step(argv + extra, tool="gmx", label="gmx mdrun")
        if rename_parts:
            quoted = shlex.quote(deffnm)
            plan.sh(
                f'for __ext in log xtc trr edr gro; do\n'
                f'  __part=$(ls -1 {quoted}.part[0-9]*."$__ext" 2>/dev/null | tail -1)\n'
                f'  if [ -n "$__part" ] && [ ! -e {quoted}."$__ext" ]; then\n'
                f'    mv "$__part" {quoted}."$__ext"\n'
                f'    echo ">> $__part -> {deffnm}.$__ext"\n'
                f'  fi\n'
                f'done',
                tool="shell",
                label="give the continued run its ordinary file names")

        plan.outputs["structure"] = f"{deffnm}.gro"
        plan.outputs["traj"] = f"{deffnm}.xtc"
        plan.outputs["edr"] = f"{deffnm}.edr"
        plan.outputs["log"] = f"{deffnm}.log"
        plan.outputs["checkpoint"] = f"{deffnm}.cpt"
        # The run file goes out as it came in. It matches the trajectory beside
        # it, with one exception nothing here can see: compressed-x-grps in the
        # run settings makes the compressed trajectory hold only some of the
        # particles, and then it does not. That setting is rare and lives in
        # the mdp rather than on this block, so it is said in the socket's
        # description rather than guessed at here.
        plan.outputs["tpr"] = ctx.require("tpr")
        return plan


# --------------------------------------------------------------------------
# Trajectory handling
# --------------------------------------------------------------------------

class TrjconvNode(Node):
    type = "gmx.trjconv"
    title = "Process trajectory (trjconv)"
    category = TRAJ
    color = ANALYSIS_COLOR
    tool = "gmx"
    extra_command = "gmx trjconv"
    description = (
        "The general-purpose trajectory fixer: unwrap molecules broken across the box "
        "edge, centre on something, remove overall rotation, or keep every tenth frame "
        "to make a large file manageable. Almost every trajectory needs at least one "
        "pass through this before it can be analysed or looked at. The tpr socket "
        "on the right hands back the same run file this was given, unchanged, so a "
        "chain of these carries it along and whatever measures the result can take "
        "both from the same place. The one time it stops matching is when this is "
        "told to write out a single group rather than the whole system: the run "
        "file still describes every particle, and the block says so before it runs."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-trjconv.html"
    inputs = (
        Port("traj", "traj", "trajectory"),
        Port("tpr", "tpr", "tpr"),
        Port("index", "index", "index", optional=True),
    )
    outputs = (
        Port("traj", "traj", "trajectory"),
        # The run file it was given, handed straight back out. It is not
        # changed here and it is not written again: the socket exists so a
        # chain of these can carry it along. Nearly everything downstream needs
        # both the trajectory and a run file to read it with, and having to run
        # a second wire back to wherever the run file came from, past every
        # block in between, is a wire nobody enjoys drawing and one that is
        # easy to forget. See the note in plan() for when it stops matching.
        #
        # Called "tpr", like the socket it came in on and like the twenty-five
        # others in the catalogue. A socket label is read in a glance while
        # looking for something to join a wire to, and the eye is looking for
        # the same word it saw on the other end. An explanation belongs in the
        # block's own description, which is what the pointer resting on it
        # shows, not in the two words under the socket.
        Port("tpr", "tpr", "tpr"),
    )
    params = (
        Param("pbc", "choice", "-pbc", "mol",
              choices=["none", "mol", "res", "atom", "nojump", "cluster", "whole"]),
        Param("ur", "choice", "-ur", "compact", choices=["", "rect", "tric", "compact"]),
        Param("center", "bool", "-center", True),
        Param("fit", "choice", "-fit", "none",
              choices=["none", "rot+trans", "rotxy+transxy", "translation", "transxy", "progressive"],
              help="Fitting and -pbc/-center are mutually exclusive in one pass; run two "
                   "trjconv nodes if you need both."),
        Param("skip", "int", "-skip", 1, min=1, help="Keep every Nth frame."),
        Param("begin", "float", "-b (ps)", 0.0, advanced=True),
        Param("end", "float", "-e (ps)", 0.0, advanced=True, help="0 = to the end."),
        Param("dt", "float", "-dt (ps)", 0.0, advanced=True),
        Param("output", "str", "Output name", "traj_proc.xtc"),
        Param("groups", "text", "Groups (stdin)", "Protein\nSystem\n", rows=3, form="gmx.groups",
              help="Order matters: centring group first, then the output group. With "
                   "-fit the fit group comes first."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "traj_proc.xtc"
        argv = ["gmx", "trjconv", "-f", ctx.require("traj"), "-s", ctx.require("tpr"), "-o", out]
        index = ctx.inp("index")
        if index:
            argv += ["-n", index]
            index_guard(plan, index, ctx.require("tpr"))
        pbc = ctx.pstr("pbc", "mol")
        fit = ctx.pstr("fit", "none")
        if fit and fit != "none":
            argv += ["-fit", fit]
            if pbc and pbc != "none":
                plan.notes.append(
                    "-fit and -pbc in the same pass: trjconv will refuse; split into two nodes"
                )
        if pbc and pbc != "none":
            argv += ["-pbc", pbc]
            ur = ctx.pstr("ur")
            if ur:
                argv += ["-ur", ur]
            if ctx.pbool("center", True):
                argv.append("-center")
        skip = ctx.pint("skip", 1)
        if skip > 1:
            argv += ["-skip", str(skip)]
        begin = ctx.pfloat("begin", 0.0)
        if begin:
            argv += ["-b", str(begin)]
        end = ctx.pfloat("end", 0.0)
        if end:
            argv += ["-e", str(end)]
        dt = ctx.pfloat("dt", 0.0)
        if dt:
            argv += ["-dt", str(dt)]
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx trjconv", stdin=_groups(ctx))
        plan.outputs["traj"] = out

        # The run file goes out as it came in, so the next block can take both
        # from here. It describes every particle in the system; the trajectory
        # holds whichever group was named last in the Groups box. Those are the
        # same thing when that answer is System, and not otherwise.
        #
        # What happens then is worth knowing, and it is not what you would
        # hope. Measured here on GROMACS 2026.3: gmx rms handed a protein-only
        # trajectory and a whole-system run file printed one line,
        #
        #     WARNING: topology has 27970 atoms, whereas trajectory has 1960
        #
        # and carried on to produce a complete answer. It only stops when the
        # group asked for lies past the end of the shorter file, and then it
        # says "Trajectory has less atoms ... than what is required". So a
        # mismatch can be a crash, and can just as easily be a column of
        # numbers that looks fine. That is worth a word before it is run.
        run_file = ctx.require("tpr")
        plan.outputs["tpr"] = run_file
        answers = [line.strip() for line in (ctx.pstr("groups") or "").splitlines()
                   if line.strip()]
        written = answers[-1] if answers else ""
        if written and written.lower() not in ("system", "0"):
            plan.notes.append(
                f"this writes only '{written}', so the run file coming out of "
                "the tpr socket still describes every particle and no longer "
                "matches the trajectory beside it. A tool given both warns "
                "about the atom counts and carries on anyway, so the answer "
                "can be quietly wrong rather than refused. Either answer "
                "System here and cut the trajectory down later, or make a run "
                f"file that holds only '{written}' to go with it"
            )
        return plan


#: Refuses an index file that was written for a different, usually bigger,
#: system. This is the loudest failure in the whole program when it is missed:
#: GROMACS does not check that the numbers in an index file fit the structure
#: it was given, so it reads past the end of the frame and dies with a
#: segmentation fault and no explanation at all.
#:
#: It counts the atoms itself, so that the command a reader sees, in the
#: Command tab and in exported scripts, is one plain line:
#:     python3 check_index.py index.ndx heat.tpr gmx
_CHECK_INDEX_SCRIPT = r'''#!/usr/bin/env python3
# Does this index file belong to this structure?
#
#     python3 check_index.py INDEX STRUCTURE [HOW GROMACS IS CALLED]
#
# An index file is a list of atom NUMBERS -- 1, 2, 3 ... -- grouped under
# names. The numbers only mean anything against the file they were made from.
# Hand GROMACS a set of numbers written for a 504,661-atom system together
# with a 74,540-atom trajectory and it will happily ask for atom 504,661,
# which is not there. What follows is a segmentation fault.
#
# STRUCTURE is the file the next command reads its atoms from. Most kinds
# state their atom count at the very top, and it is read from there: an xtc
# holds it in bytes 4 to 8, so a 46 GB file answers at once. A run input file
# (.tpr) and a checkpoint (.cpt) are packed, and only GROMACS can read them:
# for those, "gmx dump" is asked, and stopped as soon as it has printed the
# count. The words after STRUCTURE say how GROMACS is called here, usually
# just "gmx"; they are only used for those two kinds.
import re
import struct
import subprocess
import sys
import threading


def atoms_in_header(path):
    """The atom count a file states about itself, or None."""
    lowered = path.lower()
    if lowered.endswith(".gro"):
        with open(path, errors="replace") as handle:
            handle.readline()
            try:
                return int(handle.readline().strip())
            except ValueError:
                return None
    if lowered.endswith((".pdb", ".ent", ".brk")):
        count = 0
        with open(path, errors="replace") as handle:
            for line in handle:
                if line.startswith(("ATOM", "HETATM")):
                    count += 1
                elif line.startswith("ENDMDL"):
                    break
        return count or None
    with open(path, "rb") as handle:
        head = handle.read(8)
    if len(head) == 8 and struct.unpack(">i", head[:4])[0] == 1995:     # xtc
        return struct.unpack(">ii", head)[1]
    return None


def atoms_from_gromacs(path, gromacs):
    """Ask "gmx dump" for the count; give it two minutes at most."""
    flag = "-cp" if path.lower().endswith(".cpt") else "-s"
    try:
        dump = subprocess.Popen(gromacs + ["dump", flag, path, "-quiet"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, errors="replace")
    except OSError:
        return None
    watchdog = threading.Timer(120, dump.kill)
    watchdog.start()
    found = None
    try:
        for line in dump.stdout:
            match = re.match(r"\s*#?n?atoms\s*=\s*(\d+)", line)
            if match:
                found = int(match.group(1))
                break
    finally:
        watchdog.cancel()
        dump.kill()
        dump.wait()
    return found


def read_index(path):
    groups, name, atoms, biggest = [], None, 0, 0
    with open(path, errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("["):
                if name is not None:
                    groups.append((name, atoms))
                name, atoms = line.strip("[] ").strip(), 0
            elif line and not line.startswith(";"):
                for word in line.split():
                    try:
                        number = int(word)
                    except ValueError:
                        continue
                    atoms += 1
                    if number > biggest:
                        biggest = number
    if name is not None:
        groups.append((name, atoms))
    return groups, biggest


def main():
    if len(sys.argv) < 3:
        print("usage: python3 check_index.py INDEX STRUCTURE [HOW GROMACS IS CALLED]")
        return 0
    index, structure, gromacs = sys.argv[1], sys.argv[2], sys.argv[3:] or ["gmx"]
    if structure.isdigit():
        atoms = int(structure)        # older scripts hand over the count itself
    else:
        try:
            atoms = atoms_in_header(structure) or atoms_from_gromacs(structure, gromacs)
        except OSError:
            atoms = None
    if not atoms:
        return 0                      # nothing to check against: let it run
    try:
        groups, biggest = read_index(index)
    except OSError as err:
        print(f">> could not read the index file: {err}")
        return 0                      # not our place to stop the run over this
    if not biggest or biggest <= atoms:
        return 0

    say = print
    say("")
    say(">> STOPPING: this index file does not belong to this structure.")
    say(">>")
    say(f">>     the structure holds        {atoms:>9,} atoms")
    say(f">>     the index file counts up to {biggest:>9,}")
    say(">>")
    say(">> An index file is a list of atom numbers, and those numbers only mean")
    say(">> something against the file they were made from. These were written for")
    say(">> a bigger system -- most often the one before the water was taken out.")
    say(">> Used here they reach past the end of the frame, and GROMACS does not")
    say(">> check for that: it reads whatever is at that address and dies with a")
    say(">> segmentation fault. That is what would have happened next.")
    say(">>")
    say(">> Ways out:")
    say(">>   * Disconnect the index file. GROMACS makes System, Protein, Water,")
    say(">>     Non-Water and the rest by itself from the structure, and those are")
    say(">>     usually the groups being asked for anyway.")
    say(">>   * Make an index for THIS structure: an 'Index groups (make_ndx)' node")
    say(">>     fed from the same file, and use what it produces.")
    say(">>   * If you keep several index files, the one you want is the one whose")
    say(f">>     numbers stop at or below {atoms:,}. Folders that hold a system and a")
    say(">>     trimmed copy of it usually hold an index for each, and the names")
    say(">>     differ by a word.")
    say(">>")
    say(">> What is in the index file you gave:")
    for name, count in groups:
        say(f">>     {name:<44} {count:>9,} atoms")
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


def make_folder(plan: Plan, name: str) -> None:
    """Create the folder an output name points into, before the tool needs it.

    `gmx select` will not make a missing folder. It stops with a bare
    "File input/output error" naming the path, which says nothing about what is
    wrong with it, and the path it names looks perfectly reasonable.
    """
    folder = str(Path(str(name or "").strip()).parent)
    if folder and folder not in (".", ".."):
        plan.sh(f"mkdir -p {shlex.quote(folder)}",
                label=f"make sure {folder}/ exists")


def index_guard(plan: Plan, index_file: str, against: str) -> None:
    """Stop before a mismatched index file kills GROMACS.

    `against` is whatever the command will read the structure from -- the tpr,
    the .gro, the pdb. The atom count comes from the file header where the
    format states one, and from ``gmx dump`` for a tpr or cpt, which do not.

    Not a note and not a warning: a run that goes ahead here ends in a
    segmentation fault, which says nothing about what was wrong.
    """
    if not index_file or not against:
        return
    plan.files["check_index.py"] = _CHECK_INDEX_SCRIPT
    # {cmd} becomes however GROMACS is called here (gmx, gmx_mpi, ...); the
    # script needs it only for a .tpr or .cpt, whose atom count only GROMACS
    # can read.
    plan.sh(
        "python3 check_index.py " + shlex.quote(index_file) + " "
        + shlex.quote(against) + " {cmd}",
        tool="gmx", label="check that the index file belongs to this structure",
    )


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

class EnergyNode(Node):
    type = "gmx.energy"
    title = "Energy terms"
    category = ANALYSIS
    color = ANALYSIS_COLOR
    tool = "gmx"
    extra_command = "gmx energy"
    description = (
        "Pulls numbers out of the energy file a run writes -- temperature, pressure, "
        "density, the potential energy -- as a table you can plot. The first thing to "
        "look at after equilibration: if temperature and pressure are not steady, "
        "nothing after this is worth reading."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-energy.html"
    inputs = (Port("edr", "file", "energy"),)
    outputs = (Port("xvg", "xvg", "xvg"),)
    params = (
        Param("terms", "text", "Terms", "Potential\nTemperature\nPressure\n", rows=4,
              form="gmx.terms",
              help="One per line, exactly as gmx energy lists them. Numbers work too."),
        Param("begin", "float", "-b (ps)", 0.0, advanced=True),
        Param("end", "float", "-e (ps)", 0.0, advanced=True),
        Param("output", "str", "Output name", "energy.xvg", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or "energy.xvg"
        argv = ["gmx", "energy", "-f", ctx.require("edr"), "-o", out]
        begin = ctx.pfloat("begin", 0.0)
        if begin:
            argv += ["-b", str(begin)]
        end = ctx.pfloat("end", 0.0)
        if end:
            argv += ["-e", str(end)]
        terms = _groups(ctx, "terms")
        if not terms:
            raise NodeError("no energy terms listed")
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx energy", stdin=terms)
        plan.outputs["xvg"] = out
        return plan


def _analysis_node(
    node_type: str,
    title: str,
    subcommand: str,
    output_flag: str,
    default_output: str,
    default_groups: str,
    description: str,
    extra_params: tuple = (),
    needs_traj: bool = True,
    group_help: str = "",
    selections: tuple = (),
    needs_index: bool = False,
    empty_result_note: str = "",
    radii_port: bool = False,
):
    """Build one of the many gmx analysis tools that share the same shape.

    Two interfaces exist side by side in modern GROMACS. The older tools
    (``rms``, ``rmsf``, ``density``, ``mindist``, ``clustsize``) prompt for
    index groups on stdin; the rewritten ones (``gyrate``, ``sasa``, ``hbond``,
    ``dssp``) take selection strings on the command line and never prompt.
    ``selections`` is a tuple of ``(Param, flag)`` pairs and switches a node to
    the second form -- piping groups at one of those would hang the run.
    """

    class _Analysis(Node):
        pass

    _Analysis.type = node_type
    _Analysis.title = title
    _Analysis.category = ANALYSIS
    _Analysis.color = ANALYSIS_COLOR
    _Analysis.tool = "gmx"
    _Analysis.extra_command = f"gmx {subcommand}"
    _Analysis.description = description
    _Analysis.docs = (
        "https://manual.gromacs.org/current/onlinehelp/gmx-"
        + subcommand.replace("_", "-")
        + ".html"
    )
    _Analysis.inputs = (
        Port("traj", "traj", "trajectory", optional=not needs_traj),
        Port("tpr", "tpr", "tpr"),
        Port("index", "index", "index", optional=True),
    ) + ((Port("radii", "file", "particle sizes", optional=True),)
         if radii_port else ())
    _Analysis.outputs = (Port("xvg", "xvg", "xvg"),)
    _selection_params = tuple(param for param, _ in selections)
    _Analysis.params = (
        _selection_params if selections else (
            Param("groups", "text", "Groups (stdin)", default_groups, rows=2, form="gmx.groups",
                  help=group_help or "One selection per line, in the order the tool asks."),
        )
    ) + (
        Param("begin", "float", "-b (ps)", 0.0, advanced=True),
        Param("end", "float", "-e (ps)", 0.0, advanced=True),
        Param("output", "str", "Output name", default_output, advanced=True),
    ) + tuple(extra_params)

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output") or default_output
        argv = ["gmx", subcommand, "-s", ctx.require("tpr"), output_flag, out]
        traj = ctx.inp("traj")
        if traj:
            argv += ["-f", traj]
        elif needs_traj:
            raise NodeError("no trajectory connected")
        index = ctx.inp("index")
        if index:
            argv += ["-n", index]
            index_guard(plan, index, ctx.require("tpr"))
        elif needs_index:
            # Most of these tools fall back to the groups inside the run input
            # when no index file is given. One does not: gmx clustsize stops
            # with the bare line "No index file specified" and no hint that an
            # index file would have been made for it in a second. So make one:
            # make_ndx with nothing typed at it writes exactly the groups the
            # run input already carries, which is what the fallback would have
            # used anyway.
            plan.step(["gmx", "make_ndx", "-f", ctx.require("tpr"),
                       "-o", "default_groups.ndx"],
                      tool="gmx", stdin="q\n",
                      label="write the run input's own groups to an index file")
            argv += ["-n", "default_groups.ndx"]
            plan.notes.append(
                "no index file was connected, so the groups already inside the "
                "run input are written to one first: gmx " + subcommand
                + " is the one tool here that will not fall back to them by "
                "itself")
        if radii_port:
            radii = ctx.inp("radii")
            if radii:
                # GROMACS only ever looks for a file called vdwradii.dat, in the
                # folder it is run from. It has no flag for it. So whatever file
                # was wired in gets copied to that name first.
                plan.sh("cp -f " + shlex.quote(radii) + " vdwradii.dat",
                        tool="gmx", label="use the particle sizes wired in")
            else:
                plan.notes.append(
                    "No particle sizes were wired in, so GROMACS is using its\n"
                    "own table, which lists atoms. On a coarse-grained system\n"
                    "that table has no entry for a bead and every one of them\n"
                    "falls back to a single default radius -- the number that\n"
                    "comes out is then not comparable with an atomistic one.\n"
                    "Wire in a vdwradii.dat written for your beads.")
        begin = ctx.pfloat("begin", 0.0)
        if begin:
            argv += ["-b", str(begin)]
        end = ctx.pfloat("end", 0.0)
        if end:
            argv += ["-e", str(end)]
        for param, flag in selections:
            value = ctx.pstr(param.name)
            if value:
                argv += [flag, value]
            elif not param.advanced:
                raise NodeError(f"{param.label} is empty; {subcommand} needs a selection")
        for param in extra_params:
            value = ctx.p(param.name)
            if value in (None, "", 0, False):
                continue
            flag = "-" + param.name.replace("_", "-")
            if param.type == "bool":
                argv.append(flag)
            else:
                argv += [flag, str(value)]
        if empty_result_note:
            plan.step(argv + ctx.extra(), tool="gmx", label=f"gmx {subcommand}",
                      stdin=None if selections else _groups(ctx), allow_fail=True)
            quoted = shlex.quote(out)
            plan.sh(
                f'if [ ! -s {quoted} ]; then\n'
                f'  echo ">> gmx {subcommand} wrote no {out}."\n'
                f'  echo ">>"\n'
                + "".join(f'  echo ">> {line}"\n' for line in
                          empty_result_note.splitlines())
                + f'  exit 1\n'
                f'fi',
                tool="shell", label="say what an empty result means")
        else:
            plan.step(argv + ctx.extra(), tool="gmx", label=f"gmx {subcommand}",
                      stdin=None if selections else _groups(ctx))
        plan.outputs["xvg"] = out
        return plan

    _Analysis.plan = plan
    _Analysis.__name__ = "".join(part.capitalize() for part in node_type.split(".")[-1].split("_")) + "Node"
    return _Analysis


RmsNode = _analysis_node(
    "gmx.rms", "RMSD", "rms", "-o", "rmsd.xvg", "Backbone\nBackbone\n",
    "How far the structure has moved from where it started, over time. The standard "
    "'has it settled' plot: a curve that rises then flattens means the protein found "
    "a stable shape; one still climbing at the end means the run was too short.",
    extra_params=(Param("tu", "choice", "Time unit", "ns",
                        choices=["ps", "ns", "us"], advanced=True),),
    group_help="First line: the group to fit on. Second line: the group to measure.",
)

RmsfNode = _analysis_node(
    "gmx.rmsf", "RMSF", "rmsf", "-o", "rmsf.xvg", "Backbone\n",
    "How much each part of the structure wobbles about its own average position. "
    "Shows which bits are floppy -- usually loops and the two ends -- and which are "
    "rigid. Comparable to the B-factors in a crystal structure.",
    extra_params=(Param("res", "bool", "Average per residue (-res)", True),),
)

GyrateNode = _analysis_node(
    "gmx.gyrate", "Radius of gyration", "gyrate", "-o", "gyrate.xvg", "",
    "How spread out the molecule is, as one number per frame. A protein that stays "
    "folded holds a steady value; one that is unfolding grows. Takes a selection "
    "string rather than prompting for a group.",
    selections=((Param("sel", "str", "Selection (-sel)", "Protein",
                       help="A GROMACS selection string, not an index group number."), "-sel"),),
    extra_params=(
        Param("tu", "choice", "Time unit", "ns", choices=["ps", "ns", "us"], advanced=True),
        Param("mode", "choice", "Weighting", "mass", choices=["mass", "geometry"],
              advanced=True),
    ),
)

PolystatNode = _analysis_node(
    "gmx.polystat", "Polymer size and stiffness", "polystat", "-o",
    "polystat.xvg", "System\n",
    "Measures how big the chains in a polymer box are, and how floppy. It takes one "
    "group, splits it into separate molecules by itself, and reports two things per "
    "frame: the end-to-end distance, which is the straight line from the first "
    "particle of a chain to the last, and the radius of gyration, which is how far "
    "the chain's mass sits from its own centre. Both are averaged over every chain "
    "in the group.\n\n"
    "The two together say something a single number cannot. A chain coiled like a "
    "random walk has an end-to-end distance about two and a half times its radius "
    "of gyration; a stiff rod has about three and a half. So the ratio is a "
    "measure of stiffness that does not depend on how long the chain is.\n\n"
    "Filling in the persistence length box as well answers the other question -- "
    "how far along the backbone you have to go before the chain has forgotten "
    "which way it was pointing, counted in bonds.",
    extra_params=(
        Param("p", "str", "Also write the persistence length to", "",
              advanced=True, placeholder="persist.xvg",
              help="Only meaningful if the group is the chain backbone with its "
                   "particles in bonded order. It is measured from the angle "
                   "between bonds an even number apart, because a backbone in "
                   "its all-trans shape has every second bond pointing the "
                   "same way and the odd ones would flatter it."),
        Param("i", "str", "Also write internal distances to", "",
              advanced=True, placeholder="intdist.xvg",
              help="The mean square distance between particles a given number "
                   "apart along the chain, averaged over the chain. For an "
                   "ideal coil this rises in a straight line."),
        Param("pc", "bool", "Average each chain's own shape too", False,
              advanced=True,
              help="Off, the shape is averaged over chains first and measured "
                   "after, which describes the average chain. On, each chain "
                   "is measured first -- which is what you want if you care "
                   "whether the chains differ from each other."),
    ),
    group_help="One line: the group holding the polymer chains. polystat splits "
               "it into molecules itself, so 'System' is right when the box "
               "holds nothing but polymer, and an index group naming just the "
               "chains is right when it does not.",
)


SasaNode = _analysis_node(
    "gmx.sasa", "SASA", "sasa", "-o", "sasa.xvg", "",
    "How much of the molecule's surface is exposed to the solvent around it. Used to "
    "watch a pocket open and close, or a buried core become exposed as something "
    "unfolds. -surface is what gets measured, -output an optional part of it to "
    "report separately.",
    selections=(
        (Param("surface", "str", "Surface (-surface)", "Protein"), "-surface"),
        (Param("output_sel", "str", "Report subset (-output)", "", advanced=True,
               placeholder="e.g. \"Hydrophobic\" group ..."), "-output"),
    ),
    extra_params=(Param("probe", "float", "Probe radius (nm)", 0.14, advanced=True),),
    radii_port=True,
)

MindistNode = _analysis_node(
    "gmx.mindist", "Minimum distance", "mindist", "-od", "mindist.xvg",
    "Protein\nProtein\n",
    "The closest approach between two groups, frame by frame. Two uses: watching a "
    "contact form or break, and checking the box was big enough -- if a molecule "
    "comes close to its own image across the boundary, it was not, and the run has "
    "to be done again.",
    extra_params=(Param("pi", "bool", "Periodic image check (-pi)", False),),
    group_help="Two lines: the two groups. With -pi only the first is used.",
)

DensityNode = _analysis_node(
    "gmx.density", "Density profile", "density", "-o", "density.xvg", "System\n",
    "Density along one axis of the box. For a membrane this is the standard check "
    "that it looks like a membrane: water outside, lipid tails in the middle, and "
    "headgroups in two peaks where the two meet.",
    extra_params=(
        Param("d", "choice", "Axis", "Z", choices=["X", "Y", "Z"]),
        Param("sl", "int", "Slices", 100),
        Param("center", "bool", "Centre the profile (-center)", False,
              help="Puts the middle of the chosen group at zero on the axis, "
                   "so a membrane's two leaflets come out symmetric.\n\n"
                   "With this on, the tool asks TWO questions -- what to "
                   "centre on, then what to measure -- so the groups box "
                   "needs two lines, e.g. 'System' twice. One line leaves "
                   "the second question unanswered and the run stops with "
                   "'Cannot read from input'."),
    ),
)

MsdNode = _analysis_node(
    "gmx.msd", "How far things wander (msd)", "msd", "-o", "msd.xvg", "System\n",
    "How far a molecule has moved from where it started, averaged over the "
    "group and plotted against time. The slope of the straight part is the "
    "diffusion coefficient, and GROMACS prints it at the end of the run.\n\n"
    "For a lipid in a membrane, ask for the two directions in the plane only "
    "-- a lipid does not go anywhere across the membrane, and averaging that "
    "in halves the answer for no reason.\n\n"
    "Feed it a trajectory with -pbc nojump applied first. Without that, a "
    "molecule that crosses the wall of the box is put back on the other side, "
    "the distance it appears to have moved jumps by a box length, and the "
    "answer is nonsense.\n\n"
    "If it stops with '-dt cannot be larger than -trestart', it is complaining "
    "about a setting you did not touch. It measures from several starting "
    "points along the trajectory and averages them, and by default those are "
    "10 ps apart -- which is less than the gap between frames in most "
    "coarse-grained runs. Set 'How often to start again' to the frame spacing "
    "or more.",
    extra_params=(
        Param("lateral", "choice", "In the plane across", "",
              choices=["", "x", "y", "z"],
              help="For something that only moves in a sheet -- a lipid in a "
                   "membrane. Name the direction the sheet is NOT in: a "
                   "membrane lying flat, with water above and below, is "
                   "'z'.\n\n"
                   "Counting the direction it cannot move in would halve the "
                   "answer for no reason. Leave it blank for ordinary "
                   "diffusion in three dimensions."),
        Param("type", "choice", "Along one direction only", "",
              choices=["", "x", "y", "z"], advanced=True,
              help="Diffusion along a single direction. Rarely what you "
                   "want; leave it alone unless you have a reason. It cannot "
                   "be combined with the box above."),
        Param("trestart", "float", "How often to start again (ps)", 0.0,
              help="It does not measure from the first frame only. It starts "
                   "again every so often along the trajectory and averages "
                   "all those, which is what makes the curve smooth.\n\n"
                   "0 leaves GROMACS's own choice of 10 ps. That is fine for "
                   "an all-atom run and too small for most coarse-grained "
                   "ones, where frames are further apart than that -- and "
                   "then it stops with a complaint about -dt, which you never "
                   "set. Put the gap between your frames here, or more."),
        Param("beginfit", "float", "Fit the slope from (ps)", 0.0, advanced=True,
              help="0 lets GROMACS choose. The first part of the curve is "
                   "not straight -- a molecule rattles about in its cage "
                   "before it starts to wander -- so the fit should start "
                   "after that."),
        Param("endfit", "float", "Fit the slope to (ps)", 0.0, advanced=True,
              help="0 lets GROMACS choose. The end of the curve is the "
                   "noisiest part, because fewer pairs of frames are that far "
                   "apart, so it is usually worth stopping before it."),
    ),
    group_help="One group per line. Each gets its own curve.",
)


HbondNode = _analysis_node(
    "gmx.hbond", "Hydrogen bonds", "hbond", "-num", "hbnum.xvg", "",
    "Counts hydrogen bonds between two groups over time. The two selections must be "
    "either the same or completely separate -- overlapping ones are not allowed. "
    "Note that GROMACS measures the donor-acceptor-H angle where several other "
    "packages use donor-H-acceptor, so counts do not always compare directly.",
    selections=(
        (Param("r", "str", "Reference (-r)", "Protein"), "-r"),
        (Param("t", "str", "Target (-t)", "Protein"), "-t"),
    ),
    extra_params=(
        Param("hbr", "float", "Donor-acceptor cutoff (nm)", 0.35, advanced=True),
        Param("hba", "float", "Angle cutoff (deg)", 30.0, advanced=True),
    ),
)


class DsspNode(Node):
    type = "gmx.dssp"
    title = "Secondary structure (dssp)"
    category = ANALYSIS
    color = ANALYSIS_COLOR
    tool = "gmx"
    extra_command = "gmx dssp"
    preview_kind = "dssp"
    preview_port = "dat"
    description = (
        "Assigns secondary structure -- helix, sheet, turn, coil -- to every residue "
        "in every frame. Shows you whether the fold held up over the run, and where "
        "it did not.\n\n"
        "The answer is a picture, not a number, so the node draws it: residue up "
        "the side, time along the bottom, a colour per kind of structure. A helix "
        "that holds is a solid band; one that frays is a band that goes grey from "
        "one end. That is the file on the 'assignments' output -- one line a "
        "frame, one letter a residue -- and it is what you read to judge the run.\n\n"
        "The 'counts' output is the same thing summed: how many residues were in "
        "each kind of structure, frame by frame, which is the curve to wire into "
        "a Preview plot when you want a number to fall out."
    )
    docs = "https://manual.gromacs.org/current/onlinehelp/gmx-dssp.html"
    inputs = (
        Port("traj", "traj", "trajectory"),
        Port("tpr", "tpr", "tpr"),
        Port("index", "index", "index", optional=True),
    )
    outputs = (
        Port("dat", "file", "assignments"),
        Port("xvg", "xvg", "counts"),
    )
    params = (
        Param("sel", "str", "Selection (-sel)", "Protein"),
        Param("tu", "choice", "Time unit", "ns", choices=["ps", "ns", "us"]),
        Param("output", "str", "Assignment file", "dssp.dat", advanced=True),
        Param("output_num", "str", "Counts file", "dssp_num.xvg", advanced=True),
        Param("hbond", "choice", "H-bond criterion", "energy",
              choices=["energy", "geometry"], advanced=True),
        Param("polypro", "bool", "Detect polyproline helices", True, advanced=True),
        Param("begin", "float", "-b (ps)", 0.0, advanced=True),
        Param("end", "float", "-e (ps)", 0.0, advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        dat = ctx.pstr("output", "dssp.dat") or "dssp.dat"
        num = ctx.pstr("output_num", "dssp_num.xvg") or "dssp_num.xvg"
        sel = ctx.pstr("sel", "Protein")
        if not sel:
            raise NodeError("selection is empty")
        argv = ["gmx", "dssp", "-s", ctx.require("tpr"), "-f", ctx.require("traj"),
                "-sel", sel, "-o", dat, "-num", num, "-tu", ctx.pstr("tu", "ns")]
        index = ctx.inp("index")
        if index:
            argv += ["-n", index]
            index_guard(plan, index, ctx.require("tpr"))
        hbond = ctx.pstr("hbond", "energy")
        if hbond and hbond != "energy":
            argv += ["-hbond", hbond]
        if not ctx.pbool("polypro", True):
            argv.append("-nopolypro")
        begin = ctx.pfloat("begin", 0.0)
        if begin:
            argv += ["-b", str(begin)]
        end = ctx.pfloat("end", 0.0)
        if end:
            argv += ["-e", str(end)]
        plan.step(argv + ctx.extra(), tool="gmx", label="gmx dssp")
        plan.outputs["dat"] = dat
        plan.outputs["xvg"] = num
        return plan


ClustsizeNode = _analysis_node(
    "gmx.clustsize", "Cluster size", "clustsize", "-nc", "clustsize.xvg", "Protein\n",
    "Tracks how molecules clump together: how many clusters there are and how big "
    "the largest is, frame by frame. For aggregation and self-assembly, where the "
    "question is whether anything stuck together at all.",
    extra_params=(Param("cut", "float", "Cutoff (nm)", 0.35),),
    needs_index=True,
    group_help="One group: the molecules that are supposed to clump. Peptides "
               "aggregating is the usual case, so this starts at Protein; for "
               "lipids finding each other, type the lipid's name instead.\n\n"
               "Not System. With the water in, everything touches everything "
               "and the answer is one cluster in every frame.",
    empty_result_note=(
        "The usual reason is that the group never came apart: with the water\n"
        "included, or a cutoff much larger than a bond, every particle is in\n"
        "one cluster in every frame. There is then no range to plot and gmx\n"
        "stops with a line about Lo, Mid and Hi, which is its colour scale\n"
        "complaining rather than anything about your system.\n"
        "\n"
        "Choose the molecules that are supposed to clump -- POPC, or your\n"
        "peptide -- instead of System, and start from a cutoff near a bond\n"
        "length, 0.35 nm."
    ),
)


PrincipalNode = _analysis_node(
    "gmx.principal", "Moments of inertia", "principal", "-om", "moi.xvg", "System\n",
    "How hard a group of atoms is to spin, about each of its three natural "
    "axes.\n\n"
    "The three numbers come out smallest-axis-first for a long thin thing and "
    "all-equal for a round one, so they are a plain way of asking what shape "
    "something is and whether it is turning. For a straight molecule the number "
    "about its own long axis is zero: there is nothing off that line to swing.\n"
    "\n"
    "The usual reason to reach for this is checking a hand-built molecule. If "
    "you have redistributed the mass of a molecule onto dummy sites -- which is "
    "how a straight molecule is built at all -- these three numbers are how you "
    "find out whether the model you built spins like the real thing.\n\n"
    "It also writes the three axes themselves, as paxis1.xvg, paxis2.xvg and "
    "paxis3.xvg beside the file named below.",
    group_help="One group, and usually one molecule rather than the whole box: "
               "the moments of inertia of a boxful of separate molecules "
               "average out to something about the box, not about a molecule.\n"
               "\n"
               "An index node with the command 'splitres 0' makes one group per "
               "molecule, which is what you want here.",
)


# --------------------------------------------------------------------------
# A topology to match a structure
# --------------------------------------------------------------------------


NODES = [ForceFieldNode, Pdb2gmxNode, EditconfNode, SolvateNode, GenionNode, InsertMoleculesNode, MakeNdxNode, SelectNode, GromppNode, MdrunNode, TrjconvNode, EnergyNode, RmsNode, RmsfNode, GyrateNode, PolystatNode, SasaNode, MindistNode, DensityNode, HbondNode, DsspNode, ClustsizeNode, PrincipalNode, MsdNode]


# ---------------------------------------------------------------------------
# Index groups by what the molecules ARE, not by whatever number make_ndx
# happens to hand out.
# ---------------------------------------------------------------------------
_INDEX_BY_KIND = r'''
import argparse
import sys


def read_list(text):
    return set(text.replace(",", " ").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gro")
    ap.add_argument("ndx")
    ap.add_argument("--amino", required=True)
    ap.add_argument("--lipids", required=True)
    ap.add_argument("--lipid-prefixes", default="")
    ap.add_argument("--solvent", required=True)
    ap.add_argument("--water", default="W WF PW SOL HOH")
    ap.add_argument("--extra", default="")          # file: name: RES RES ...
    ap.add_argument("--per-lipid", action="store_true")
    a = ap.parse_args()

    amino = read_list(a.amino)
    lipids = read_list(a.lipids)
    prefixes = a.lipid_prefixes.replace(",", " ").split()
    solvent = read_list(a.solvent)
    water = read_list(a.water)
    extra = []
    if a.extra:
        for line in open(a.extra):
            line = line.split("#")[0].strip()
            if ":" in line:
                name, members = line.split(":", 1)
                extra.append((name.strip().replace(" ", "_"), read_list(members)))

    with open(a.gro) as fh:
        fh.readline()
        n = int(fh.readline())
        resnames = [fh.readline()[5:10].strip() for _ in range(n)]

    def kind(rn):
        base = rn.split("_")[0]
        for name, members in extra:
            if rn in members or base in members:
                return "extra:" + name
        if rn in amino:
            return "protein"
        if base in lipids or any(base.startswith(p) for p in prefixes):
            return "membrane"
        if rn in solvent or rn in water:
            return "solvent"
        return None

    groups = {"System": list(range(1, n + 1)), "Protein": [], "Membrane": [],
              "Solvent": [], "Non_Water": [], "Protein_Membrane": []}
    per_lipid = {}
    for name, _ in extra:
        groups[name] = []
    unknown = {}
    for i, rn in enumerate(resnames, 1):
        k = kind(rn)
        if k is None:
            unknown[rn] = unknown.get(rn, 0) + 1
            continue
        if k.startswith("extra:"):
            groups[k[6:]].append(i)
            groups["Protein_Membrane"].append(i)
            groups["Non_Water"].append(i)
        elif k == "protein":
            groups["Protein"].append(i)
            groups["Protein_Membrane"].append(i)
            groups["Non_Water"].append(i)
        elif k == "membrane":
            groups["Membrane"].append(i)
            groups["Protein_Membrane"].append(i)
            groups["Non_Water"].append(i)
            per_lipid.setdefault(rn.split("_")[0], []).append(i)
        else:
            groups["Solvent"].append(i)
            if rn not in water:
                groups["Non_Water"].append(i)
    if unknown:
        print("FATAL: residues that fit no group:", file=sys.stderr)
        for rn, c in sorted(unknown.items(), key=lambda x: -x[1]):
            print(f"    {rn:<8} {c} atoms", file=sys.stderr)
        print("  Add them to one of the lists in this block, or name them in "
              "'Extra groups'.", file=sys.stderr)
        sys.exit(1)
    if a.per_lipid:
        for name, idx in sorted(per_lipid.items()):
            groups[name] = idx

    with open(a.ndx, "w") as fh:
        for name, idx in groups.items():
            if not idx and name not in ("System",):
                continue
            fh.write(f"[ {name} ]\n")
            for i in range(0, len(idx), 15):
                fh.write(" ".join(f"{j:5d}" for j in idx[i:i + 15]) + "\n")
            fh.write("\n")
    print(f"  {a.ndx}: groups from {n} atoms")
    for name, idx in groups.items():
        if idx:
            print(f"    {name:<24} {len(idx):>8}")


main()
'''


class IndexByKindNode(Node):
    type = "gmx.index_by_kind"
    title = "Index groups by what the molecules are"
    category = BUILD
    color = GMX_COLOR
    tool = "python"
    extra_command = ""
    description = (
        "Writes an index file whose groups are decided by what each molecule "
        "IS -- protein, membrane lipid, water, ion -- read from the residue "
        "names, so the groups stay right when the system changes.\n\n"
        "make_ndx picks groups by number ('13 | 14 | 15'), and a number that "
        "shifts as soon as the composition or ordering changes is how the wrong "
        "group gets frozen or heated. Here 'Membrane' means every lipid, whatever "
        "the lipids are, and the run settings can name their groups in words.\n\n"
        "Groups written: System, Protein, Membrane, Solvent, Protein_Membrane, "
        "Non_Water (everything but water -- the usual group to save in the "
        "trajectory), any extra groups you name, and, if asked, one group per "
        "lipid type. Every atom must land in exactly one kind; anything that "
        "fits no list stops this block rather than being dropped in silence."
    )
    inputs = (Port("structure", "structure", "structure"),)
    outputs = (Port("index", "index", "index"),)
    params = (
        Param("extra", "text", "Extra groups", "", rows=2,
              placeholder="Antigen: AGC\nLigand: LIG",
              help="One per line: a group name, a colon, then the residue names "
                   "that belong in it. These count with the protein and membrane "
                   "in Protein_Membrane and Non_Water -- a ligand should be "
                   "temperature-controlled with the molecules it sits in, never "
                   "with the water."),
        Param("per_lipid", "bool", "Also one group per lipid type", True),
        Param("amino", "text", "Residue names that are protein",
              "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER "
              "THR TRP TYR VAL HISH HISE HISD ASPP GLUP LYSN CYSH", rows=2,
              advanced=True),
        Param("lipids", "text", "Residue names that are lipids",
              "CHOL PSM DPSM CER", rows=1, advanced=True,
              help="Exact names. The prefixes below catch the rest."),
        Param("lipid_prefixes", "str", "...and names starting with",
              "POP DOP DPP DLP PIP PAP PUP DAP", advanced=True),
        Param("solvent", "text", "Residue names that are water or ions",
              "W WF PW SOL HOH NA CL NA+ CL- ION K CA MG", rows=1, advanced=True),
        Param("output", "str", "Output name", "index.ndx", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        gro = ctx.require("structure")
        out = ctx.pstr("output") or "index.ndx"
        plan.files["index_by_kind.py"] = _INDEX_BY_KIND
        argv = ["python", "index_by_kind.py", gro, out,
                "--amino", ctx.pstr("amino"), "--lipids", ctx.pstr("lipids"),
                "--lipid-prefixes", ctx.pstr("lipid_prefixes"),
                "--solvent", ctx.pstr("solvent")]
        if ctx.pstr("extra").strip():
            plan.files["extra_groups.txt"] = ctx.pstr("extra") + "\n"
            argv += ["--extra", "extra_groups.txt"]
        if ctx.pbool("per_lipid", True):
            argv.append("--per-lipid")
        plan.step(argv, tool="python", label="sort every atom into a group by name")
        plan.outputs["index"] = out
        return plan


NODES += [IndexByKindNode]


# --------------------------------------------------------------------------
# Families of look-alike blocks, folded into one block with a choice box
# --------------------------------------------------------------------------

from .merged import merged_node  # noqa: E402

_BY_TYPE = {cls.type: cls for cls in NODES}

MeasureNode = merged_node(
    node_type="gmx.measure",
    title="Measure something, frame by frame",
    category=ANALYSIS,
    color=ANALYSIS_COLOR,
    tool="gmx",
    description=(
        "One block for the everyday measurements: pick what to measure at the "
        "top, and the boxes that measurement needs appear below it. Each choice "
        "runs the matching GROMACS tool and writes a curve you can wire into a "
        "Preview plot.\n\n"
        "Which one do you want? RMSD says whether the structure has settled; "
        "RMSF says which parts of it are floppy; radius of gyration says whether "
        "it is folded or coming apart; exposed surface watches a pocket open; "
        "closest approach watches a contact form or checks the box was big "
        "enough; a density profile is how you check a membrane looks like a "
        "membrane; how far things wander gives a diffusion coefficient; "
        "hydrogen bonds counts them between two groups; cluster size is for "
        "things that clump; moments of inertia tell you the shape of something.\n\n"
        "Every one needs the trajectory and the run input (tpr). Most take "
        "index groups typed one per line; the newer tools take a selection "
        "instead, and the box changes to match."
    ),
    choice="measure",
    choice_label="What to measure",
    choice_help="Each choice is one GROMACS tool, named in brackets. The boxes "
                "below change to fit the one you pick.",
    members=[
        ("RMSD: how far it moved from the start (rms)", "rms", _BY_TYPE["gmx.rms"]),
        ("RMSF: how much each part wobbles (rmsf)", "rmsf", _BY_TYPE["gmx.rmsf"]),
        ("Radius of gyration: how spread out it is (gyrate)", "gyrate", _BY_TYPE["gmx.gyrate"]),
        ("Exposed surface area (sasa)", "sasa", _BY_TYPE["gmx.sasa"]),
        ("Closest approach of two groups (mindist)", "mindist", _BY_TYPE["gmx.mindist"]),
        ("Density profile along an axis (density)", "density", _BY_TYPE["gmx.density"]),
        ("How far things wander (msd)", "msd", _BY_TYPE["gmx.msd"]),
        ("Hydrogen bonds between two groups (hbond)", "hbond", _BY_TYPE["gmx.hbond"]),
        ("Cluster size (clustsize)", "clustsize", _BY_TYPE["gmx.clustsize"]),
        ("Polymer size and stiffness (polystat)", "polystat", _BY_TYPE["gmx.polystat"]),
        ("Moments of inertia (principal)", "principal", _BY_TYPE["gmx.principal"]),
    ],
    inputs=(
        Port("traj", "traj", "trajectory"),
        Port("tpr", "tpr", "tpr"),
        Port("index", "index", "index", optional=True),
        Port("radii", "file", "particle sizes", optional=True,
             when="measure=Exposed surface area (sasa)"),
    ),
    outputs=(Port("xvg", "xvg", "xvg"),),
)

IndexNode = merged_node(
    node_type="gmx.index",
    title="Index groups",
    category=BUILD,
    color=GMX_COLOR,
    tool="gmx",
    description=(
        "Makes the index file: the list of named groups of atoms that the run "
        "settings and the analysis tools refer to -- which atoms are the "
        "protein, which the membrane, which the water.\n\n"
        "Three ways to make one, from safest to most hands-on. 'By what the "
        "molecules are' reads the structure and names groups by what they are, "
        "so Protein, Membrane and Solvent mean the same thing in every system; "
        "start here. 'From a selection' takes one selection written in GROMACS's "
        "own words, such as 'name BB' or 'resname POPC'. 'By typing make_ndx "
        "commands' is the classic interactive tool with its commands typed in "
        "advance -- powerful, but the group numbers it uses shift when the "
        "system changes."
    ),
    choice="how",
    choice_label="How to make the groups",
    members=[
        ("by what the molecules are: protein, membrane, solvent", "kind",
         _BY_TYPE["gmx.index_by_kind"]),
        ("from a selection (gmx select)", "select", _BY_TYPE["gmx.select"]),
        ("by typing make_ndx commands", "ndx", _BY_TYPE["gmx.make_ndx"]),
    ],
    inputs=(
        Port("structure", "structure", "structure"),
        Port("index", "index", "existing index", optional=True,
             when="how=by typing make_ndx commands"),
        Port("traj", "traj", "trajectory", optional=True,
             when="how=from a selection (gmx select)"),
    ),
    outputs=(Port("index", "index", "index"),),
)

NODES += [MeasureNode, IndexNode]
