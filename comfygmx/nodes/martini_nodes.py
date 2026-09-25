"""Coarse-grained (Martini) nodes: the force field and the topology that uses it.

Martini needs its force-field .itp files next to the topology at grompp time.
The Martini tutorial fetches them with "Download file" blocks and hands them to
"Assemble topology", which writes a topology that includes them.
"""

from __future__ import annotations

from .base import Node, NodeError, Param, Plan, PlanContext, Port

CATEGORY = "Martini / coarse-grained"
MARTINI_COLOR = "#7a4a7a"


_COUNT_MOLECULES_SCRIPT = r"""
# Substitute @RESNAME tokens in a [ molecules ] block with the number of such
# molecules in a structure file. Counting runs of (resid, resname) rather than
# distinct resids: GROMACS wraps residue numbers at 100000, so distinct ids
# undercount a large box, while runs stay right as long as a molecule's atoms
# are contiguous -- which they must be for grompp to accept the file anyway.
#
# @RESNAME/N divides the atom count by N instead. Some builders number every
# bead as its own residue, which makes the run count come out as the bead
# count; giving the beads per molecule is the way out, and is what the
# tutorials do by hand with `grep -c POPC | / 12`.

import re
import sys


def residues(path):
    runs = {}
    atoms = {}
    previous = None

    if path.lower().endswith(".pdb"):
        with open(path) as handle:
            for line in handle:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                resid, resname = line[22:27], line[17:21].strip()
                atoms[resname] = atoms.get(resname, 0) + 1
                if (resid, resname) != previous:
                    runs[resname] = runs.get(resname, 0) + 1
                    previous = (resid, resname)
        return runs, atoms

    with open(path) as handle:
        lines = handle.read().splitlines()
    try:
        natoms = int(lines[1].strip())
    except (IndexError, ValueError):
        sys.exit("%s does not look like a .gro file" % path)
    for line in lines[2:2 + natoms]:
        resid, resname = line[0:5], line[5:10].strip()
        atoms[resname] = atoms.get(resname, 0) + 1
        if (resid, resname) != previous:
            runs[resname] = runs.get(resname, 0) + 1
            previous = (resid, resname)
    return runs, atoms


def main():
    structure, template, out = sys.argv[1:4]
    runs, atoms = residues(structure)
    text = open(template).read()

    problems = []

    def replace(match):
        name, per = match.group(1), match.group(2)
        if name not in runs:
            problems.append("no %s in %s" % (name, structure))
            return "0"
        if not per:
            return str(runs[name])
        per = int(per)
        total = atoms[name]
        if total % per:
            problems.append(
                "%d %s beads is not a whole number of %d-bead molecules"
                % (total, name, per)
            )
            return "0"
        return str(total // per)

    text = re.sub(r"@([A-Za-z0-9_+-]+)(?:/([0-9]+))?", replace, text)
    if problems:
        sys.exit("; ".join(sorted(set(problems))))
    for name in sorted(runs):
        print(">> %-8s %6d residues %6d beads" % (name, runs[name], atoms[name]))
    with open(out, "w") as handle:
        handle.write(text)


main()
"""


class TopologyMergeNode(Node):
    type = "martini.merge_top"
    title = "Assemble topology"
    category = CATEGORY
    color = MARTINI_COLOR
    tool = "shell"
    description = (
        "Writes the topology file that ties a coarse-grained system together: the "
        "force field include at the top, then each molecule's own file, then the count "
        "of every molecule in the box. The usual way to join a martinized protein to a "
        "membrane a builder produced."
    )
    inputs = (
        Port("header", "text", "include header", optional=True),
        Port("itp", "file", "molecule itps", optional=True),
        Port("ff", "file", "force field itps", optional=True),
        Port("topology", "topology", "builder topology", optional=True),
        Port("structure", "structure", "count from", optional=True),
    )
    outputs = (Port("topology", "topology", "topology"),)
    params = (
        Param("defines", "text", "#define lines", "", rows=2, form="top.defines",
              placeholder="GO_VIRT",
              help="One symbol per line, written as #define at the very top. This is "
                   "how the Go network (GO_VIRT) and the water bias (WBIAS) are "
                   "switched on; without it their #ifdef blocks are dead text."),
        Param("includes", "text", "Extra #include lines", "", rows=4, form="top.includes",
              placeholder='#include "ff/martini_v3.0.0.itp"'),
        Param("itp_files", "text", "Molecule itps to include", "molecule_0.itp", rows=3,
              form="files.list", help="One per line; each becomes an #include after the force field."),
        Param("system_name", "str", "System name", "Comfy-gmx system"),
        Param("molecules", "text", "[ molecules ]", "", rows=6, form="top.molecules",
              placeholder="molecule_0   1\nPOPC       @POPC\nW          @W",
              help="Blank copies the [ molecules ] block out of the connected "
                   "topology, which is what you want when a builder wrote one. Write "
                   "@RESNAME instead of a number to have it counted from the structure "
                   "on the 'count from' port -- that is how a box packed by "
                   "insert-molecules and solvate gets its counts, since neither tool "
                   "writes them. @RESNAME/12 divides the bead count by 12 instead, for "
                   "a builder that numbers every bead as its own residue."),
        Param("extra_molecules", "text", "More lines for [ molecules ]", "",
              rows=3, placeholder="W @W",
              help="Added to the end of the list the builder wrote.\n\n"
                   "This is for anything that arrived after the builder "
                   "finished. A builder that places lipids and nothing else "
                   "writes a topology with lipids and nothing else in it; add "
                   "water afterwards and the topology no longer matches the "
                   "structure, and grompp stops saying the two disagree about "
                   "how many particles there are.\n\n"
                   "One molecule per line, name then number. Write @NAME "
                   "instead of a number and it is counted from the structure "
                   "on the 'count from' input -- 'W @W' means as many waters "
                   "as there really are."),
        Param("rename", "text", "Rename molecules", "", rows=2, form="top.rename",
              placeholder="Protein molecule_0",
              help="'<old> <new>' pairs applied to the copied [ molecules ] block. "
                   "Two programs can give the same molecule two different names; "
                   "grompp then stops because a name in [ molecules ] matches no "
                   "molecule it knows, and this is where the two names are made to "
                   "agree."),
        Param("output", "str", "Output name", "system.top", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        out = ctx.pstr("output", "system.top") or "system.top"
        header = ctx.text_in("header")
        builder_top = ctx.inp("topology")
        ctx.inp("itp")
        ctx.inp("ff")

        lines = ["; assembled by Comfy-gmx", ""]
        for symbol in [ln.strip() for ln in ctx.pstr("defines").splitlines() if ln.strip()]:
            lines.append(symbol if symbol.startswith("#define") else f"#define {symbol}")
        if lines[-1] != "":
            lines.append("")
        if header:
            lines.append(header)
        extra_includes = [ln.strip() for ln in ctx.pstr("includes").splitlines() if ln.strip()]
        lines += extra_includes
        for name in [ln.strip() for ln in ctx.pstr("itp_files").splitlines() if ln.strip()]:
            lines.append(f'#include "{name}"')
        lines += ["", "[ system ]", ctx.pstr("system_name", "Comfy-gmx system"), "",
                  "[ molecules ]"]
        molecules = ctx.pstr("molecules")
        plan.files["_top_head.txt"] = "\n".join(lines) + "\n"

        renames = []
        for line in ctx.pstr("rename").splitlines():
            parts = line.split()
            if not parts:
                continue
            if len(parts) != 2:
                raise NodeError(f"rename needs two names per line, got '{line.strip()}'")
            renames.append(tuple(parts))

        if renames and molecules.strip():
            plan.notes.append("renames only apply to a copied [ molecules ] block")

        extra = ctx.pstr("extra_molecules")
        if extra.strip() and molecules.strip():
            plan.notes.append(
                "the extra lines are ignored: they are for adding to a "
                "builder's own list, and this node is writing the whole list "
                "itself")
            extra = ""

        if molecules.strip():
            structure = ctx.inp("structure")
            if "@" in molecules:
                if not structure:
                    raise NodeError(
                        "the [ molecules ] block uses @RESNAME but nothing is "
                        "connected to the 'count from' port"
                    )
                plan.files["_molecules_template.txt"] = molecules.rstrip() + "\n"
                plan.files["_count_molecules.py"] = _COUNT_MOLECULES_SCRIPT
                plan.step(["python", "_count_molecules.py", structure,
                           "_molecules_template.txt", "_molecules.txt"],
                          tool="python", label="count molecules")
            else:
                plan.files["_molecules.txt"] = molecules.rstrip() + "\n"
            plan.sh(f"cat _top_head.txt _molecules.txt > {out}", label="assemble top")
        elif builder_top:
            # Pull everything after the builder's [ molecules ] header.
            plan.sh(
                "awk '/^ *\\[ *molecules *\\]/{flag=1;next} flag' "
                f"{builder_top} > _molecules.txt",
                label="extract [ molecules ]",
            )
            for old_name, new_name in renames:
                plan.sh(
                    "sed -i -E 's/^([[:space:]]*)"
                    + old_name.replace("+", "\\+")
                    + "([[:space:]]|$)/\\1"
                    + new_name
                    + "\\2/' _molecules.txt",
                    label=f"rename {old_name} -> {new_name}",
                )
            tail = ""
            if extra.strip():
                structure = ctx.inp("structure")
                if "@" in extra:
                    if not structure:
                        raise NodeError(
                            "the extra [ molecules ] lines use @NAME but "
                            "nothing is connected to the 'count from' port, "
                            "so there is nothing to count")
                    plan.files["_extra_template.txt"] = extra.rstrip() + "\n"
                    plan.files["_count_molecules.py"] = _COUNT_MOLECULES_SCRIPT
                    plan.step(["python", "_count_molecules.py", structure,
                               "_extra_template.txt", "_extra.txt"],
                              tool="python", label="count what was added")
                else:
                    plan.files["_extra.txt"] = extra.rstrip() + "\n"
                tail = " _extra.txt"
            plan.sh(f"cat _top_head.txt _molecules.txt{tail} > {out}",
                    label="assemble top")
        else:
            raise NodeError(
                "give a [ molecules ] block or connect a builder topology to copy it from"
            )
        plan.outputs["topology"] = {"top": out, "glob": ["*.itp", "*.prm"],
                                    "dirs": ctx.staged_dirs("topology")}
        return plan


NODES = [TopologyMergeNode]
