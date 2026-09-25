"""Structure preparation: cleaning a structure file before GROMACS reads it.

The cleaning node ships its own script, written with nothing but Python's own
standard library, so it runs under whatever Python is on PATH.
"""

from __future__ import annotations


from .base import Node, Param, Plan, PlanContext, Port

CATEGORY = "Structure preparation"
PREP_COLOR = "#3f6b8a"


# --------------------------------------------------------------------------
# clean_pdb.py -- embedded so the node has no import-time dependencies
# --------------------------------------------------------------------------

_CLEAN_SCRIPT = r'''#!/usr/bin/env python3
"""Trim a structure down to what a force field can actually parametrise.

Reads PDB and mmCIF. The two say the same things in very different ways: a PDB
record is fixed columns, so the residue name is always characters 18 to 20,
while mmCIF is a table with named columns in whatever order the file lists
them. An mmCIF read as though it were a PDB looks almost right -- its atom
lines do start with the word ATOM -- and every field taken out of it is
nonsense. What comes out is written as PDB either way, because that is what
the nodes after this one read.
"""
import argparse
import string
import sys

WATERS = {"HOH", "WAT", "TIP3", "SOL", "H2O", "DOD"}


def is_cif(path):
    """mmCIF or PDB? Decided by looking, not by the name on the end."""
    with open(path, errors="replace") as fh:
        for _ in range(200):
            line = fh.readline()
            if not line:
                break
            stripped = line.strip()
            if stripped.startswith("data_") or stripped.startswith("_atom_site."):
                return True
            if line[:6].strip() in ("ATOM", "HETATM", "CRYST1", "HEADER", "MODEL"):
                return False
    return path.lower().endswith((".cif", ".pdbx", ".mmcif"))


def _tokens(line):
    """Split one row of an mmCIF table, respecting quotes.

    Values are separated by spaces, and one that contains a space is quoted --
    an atom name like 'CA A' or a residue called "3'-something".
    """
    out, current, quote = [], "", ""
    for char in line.rstrip("\n"):
        if quote:
            if char == quote:
                quote = ""
                out.append(current)
                current = ""
            else:
                current += char
        elif char in "'\"":
            quote = char
        elif char.isspace():
            if current:
                out.append(current)
                current = ""
        else:
            current += char
    if current:
        out.append(current)
    return out


def cif_to_pdb_lines(path):
    """The atoms out of an mmCIF, written as PDB records.

    Only the atom table is carried across. mmCIF says far more than PDB can
    hold, and none of the rest is read further down this program.

    Chain names are the sticking point: mmCIF allows any length and PDB has
    one column, so a name longer than one character is given a letter and the
    swap is printed. If there are more chains than letters, or more atoms than
    a PDB serial number can count, this stops and says so rather than writing
    a file that is quietly wrong.
    """
    headers, rows = [], []
    in_loop = False
    reading = False
    with open(path, errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped == "loop_":
                in_loop, reading, headers = True, False, []
                continue
            if in_loop and stripped.startswith("_atom_site."):
                headers.append(stripped.split(".", 1)[1].split()[0])
                reading = True
                continue
            if in_loop and stripped.startswith("_"):
                # Some other table's headers: this is not the one.
                in_loop, reading, headers = False, False, []
                continue
            if not reading:
                continue
            if not stripped or stripped.startswith("#") or stripped.startswith("data_"):
                reading = False
                continue
            fields = _tokens(line)
            if len(fields) == len(headers):
                rows.append(fields)

    if not headers or not rows:
        raise SystemExit(
            "%s looks like mmCIF but has no _atom_site table in it, so there "
            "are no atoms to clean. Check the file downloaded properly." % path)

    where = {name: index for index, name in enumerate(headers)}

    def field(row, *names, **kw):
        for name in names:
            if name in where:
                value = row[where[name]]
                if value not in (".", "?"):
                    return value
        return kw.get("default", "")

    # One letter per chain, and the same letter every time. auth_asym_id is
    # the name the depositors used and the one every paper quotes.
    letters = list(string.ascii_uppercase + string.ascii_lowercase + string.digits)
    given, renamed = {}, []
    for row in rows:
        name = field(row, "auth_asym_id", "label_asym_id", default="A")
        if name in given:
            continue
        if len(name) == 1 and name not in given.values():
            given[name] = name
            continue
        spare = next((c for c in letters if c not in given.values()), "")
        if not spare:
            raise SystemExit(
                "this structure has more than %d chains, and a PDB file has one "
                "column for the chain name. Keep the chains you need with 'Keep "
                "chains' on this node and clean it again." % len(letters))
        given[name] = spare
        renamed.append((name, spare))

    if len(rows) > 99999:
        raise SystemExit(
            "this structure has %d atoms and a PDB file can number 99,999. It "
            "was downloaded as mmCIF for that reason. Keep fewer chains, or "
            "take it through a tool that works in mmCIF -- nothing after this "
            "node reads mmCIF." % len(rows))

    if renamed:
        print("chain names shortened for PDB: "
              + ", ".join("%s -> %s" % pair for pair in renamed))

    # An NMR bundle is one table with a model number column. Written out as
    # MODEL/ENDMDL records, so "first model only" works on it exactly as it
    # does on a PDB file, rather than being a second thing that has to be
    # written and kept in step.
    models = []
    for row in rows:
        number = field(row, "pdbx_PDB_model_num", default="1")
        if not models or models[-1][0] != number:
            models.append((number, []))
        models[-1][1].append(row)
    many = len(models) > 1

    lines = []
    last_chain = None
    serial = 0
    for index, (_number, rows_here) in enumerate(models, 1):
        if many:
            lines.append("MODEL     %4d\n" % index)
            last_chain = None
        for row in rows_here:
            serial += 1
            group = field(row, "group_PDB", default="ATOM")
            name = field(row, "auth_atom_id", "label_atom_id")
            altloc = field(row, "label_alt_id", default=" ") or " "
            resname = field(row, "auth_comp_id", "label_comp_id")
            chain = given.get(
                field(row, "auth_asym_id", "label_asym_id", default="A"), "A")
            resid = field(row, "auth_seq_id", "label_seq_id", default="1")
            icode = field(row, "pdbx_PDB_ins_code", default=" ") or " "
            element = field(row, "type_symbol")
            try:
                x = float(field(row, "Cartn_x", default="0"))
                y = float(field(row, "Cartn_y", default="0"))
                z = float(field(row, "Cartn_z", default="0"))
            except ValueError:
                continue
            try:
                occupancy = float(field(row, "occupancy", default="1"))
            except ValueError:
                occupancy = 1.0
            try:
                bfactor = float(field(row, "B_iso_or_equiv", default="0"))
            except ValueError:
                bfactor = 0.0
            try:
                number = int(resid)
            except ValueError:
                number = 1
            if last_chain is not None and chain != last_chain:
                lines.append("TER\n")
            last_chain = chain
            # An atom name of fewer than four characters starts one column in,
            # unless the element itself is two letters -- that column is what
            # tells a calcium (CA) from an alpha carbon (C, named CA).
            if len(name) >= 4 or len(element) == 2:
                atom_name = "%-4s" % name[:4]
            else:
                atom_name = " %-3s" % name[:3]
            lines.append(
                "%-6s%5d %s%1s%3s %1s%4d%1s   %8.3f%8.3f%8.3f%6.2f%6.2f"
                "          %2s\n"
                % (group[:6], serial, atom_name, altloc[:1], resname[:3], chain,
                   number, icode[:1], x, y, z, occupancy, bfactor, element[:2]))
        if many:
            lines.append("ENDMDL\n")
    if not many:
        lines.append("TER\n")
    return lines


class _nothing:
    """Stands in for the file when the atoms came from mmCIF and are a list."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--chains", default="", help="comma separated; blank keeps all")
    ap.add_argument("--drop-water", action="store_true",
                    help="throw away HOH/WAT; the solvation step puts water back")
    ap.add_argument("--drop-hetero", action="store_true",
                    help="throw away every HETATM: ligands, ions, sugars, buffer")
    ap.add_argument("--keep-hetero", default="", help="comma separated resnames to keep anyway")
    ap.add_argument("--strip-hydrogens", action="store_true",
                    help="remove all hydrogens, so pdb2gmx builds its own")
    ap.add_argument("--first-model", action="store_true",
                    help="keep MODEL 1 only, which is what an NMR ensemble needs")
    ap.add_argument("--first-altloc", action="store_true",
                    help="keep altloc A (or blank) where a residue has two positions")
    ap.add_argument("--renumber", action="store_true",
                    help="renumber residues from 1 per chain, gaps closed up")
    args = ap.parse_args()

    keep_chains = {c.strip() for c in args.chains.split(",") if c.strip()}
    keep_het = {c.strip().upper() for c in args.keep_hetero.split(",") if c.strip()}

    kept, dropped = 0, 0
    in_model = 0
    counters = {}
    seen_resid = {}
    out_lines = []

    if is_cif(args.infile):
        print("%s is mmCIF; its atoms are written out as PDB, which is what "
              "the nodes after this one read" % args.infile)
        source = cif_to_pdb_lines(args.infile)
    else:
        source = open(args.infile, errors="replace")

    with source if hasattr(source, "close") else _nothing() as _:
        for line in source:
            tag = line[:6].strip()
            if tag == "MODEL":
                in_model += 1
                if args.first_model and in_model > 1:
                    break
                continue
            if tag in ("ENDMDL", "END"):
                continue
            if tag == "TER":
                out_lines.append(line)
                continue
            if tag not in ("ATOM", "HETATM"):
                # SEQRES/SSBOND/CRYST1 carry information later stages want.
                if tag in ("SEQRES", "SSBOND", "CRYST1", "HELIX", "SHEET", "LINK"):
                    out_lines.append(line)
                continue

            resname = line[17:20].strip().upper()
            chain = line[21].strip()
            altloc = line[16]
            element = line[76:78].strip().upper() or line[12:16].strip()[:1]

            if keep_chains and chain not in keep_chains:
                dropped += 1
                continue
            if args.drop_water and resname in WATERS:
                dropped += 1
                continue
            if args.drop_hetero and tag == "HETATM" and resname not in keep_het:
                dropped += 1
                continue
            if args.strip_hydrogens and element in ("H", "D"):
                dropped += 1
                continue
            if args.first_altloc and altloc not in (" ", "", "A"):
                dropped += 1
                continue
            if args.first_altloc and altloc == "A":
                line = line[:16] + " " + line[17:]

            if args.renumber:
                key = (chain, line[22:27])
                if key not in seen_resid:
                    counters[chain] = counters.get(chain, 0) + 1
                    seen_resid[key] = counters[chain]
                line = line[:22] + "%4d " % seen_resid[key] + line[27:]

            out_lines.append(line)
            kept += 1

    with open(args.outfile, "w") as fh:
        fh.writelines(out_lines)
        fh.write("END\n")

    print("kept %d atoms, dropped %d" % (kept, dropped))
    if kept == 0:
        print("nothing survived the filters", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


class CleanPdbNode(Node):
    type = "prep.clean"
    title = "Clean structure"
    category = CATEGORY
    color = PREP_COLOR
    tool = "shell"
    extra_command = "clean_pdb.py"
    description = (
        "Tidies a structure before anything else touches it: drop the crystal waters, "
        "keep only the chains you want, remove ligands and ions, and pick one position "
        "where the experiment recorded two. Almost every structure from the PDB needs "
        "some of this, and doing it here is much easier than arguing with pdb2gmx "
        "afterwards."
    )
    inputs = (Port("structure", "structure", "structure"),)
    outputs = (Port("structure", "structure", "structure"),)
    params = (
        Param("chains", "str", "Keep chains", "", placeholder="A,B  (blank = all)",
              help="Right-click this node and choose \"What is in ...\" to list the "
                   "chains in whatever is wired into it, with residue ranges, and "
                   "tick the ones to keep."),
        Param("drop_water", "bool", "Remove water", True),
        Param("drop_hetero", "bool", "Remove heteroatoms", True,
              help="Ligands, ions and crystallisation additives. Keep the ones you need "
                   "by name below."),
        Param("keep_hetero", "str", "Keep these heteroatoms", "",
              placeholder="ZN,HEM,ATP",
              help="Right-click this node and choose \"What is in ...\" to see which "
                   "ones are actually there."),
        Param("strip_hydrogens", "bool", "Strip hydrogens", False,
              help="pdb2gmx -ignh does this anyway; useful when handing the file elsewhere."),
        Param("first_model", "bool", "First NMR model only", True,
              help="An NMR structure is a bundle: ten or twenty models of the "
                   "same molecule, one after another between MODEL and ENDMDL "
                   "records, all consistent with the same measurements. Read "
                   "as-is that is twenty copies of the protein sitting on top "
                   "of each other, which is not a system anybody meant to "
                   "simulate. This keeps the first and drops the rest. A "
                   "crystal structure has no MODEL records at all, so leaving "
                   "it on costs nothing."),
        Param("first_altloc", "bool", "First alternate location only", True),
        Param("renumber", "bool", "Renumber residues from 1", False,
              help="Convenient, but it breaks any residue numbers you took from a paper."),
        Param("output", "str", "Output name", "clean.pdb", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        out = ctx.pstr("output", "clean.pdb") or "clean.pdb"
        plan.files["clean_pdb.py"] = _CLEAN_SCRIPT
        argv = ["python3", "clean_pdb.py", structure, out]
        chains = ctx.pstr("chains")
        if chains:
            argv += ["--chains", chains]
        if ctx.pbool("drop_water", True):
            argv.append("--drop-water")
        if ctx.pbool("drop_hetero", True):
            argv.append("--drop-hetero")
        keep = ctx.pstr("keep_hetero")
        if keep:
            argv += ["--keep-hetero", keep]
        if ctx.pbool("strip_hydrogens"):
            argv.append("--strip-hydrogens")
        if ctx.pbool("first_model", True):
            argv.append("--first-model")
        if ctx.pbool("first_altloc", True):
            argv.append("--first-altloc")
        if ctx.pbool("renumber"):
            argv.append("--renumber")
        plan.step(argv + ctx.extra(), tool="shell", label="clean structure")
        plan.outputs["structure"] = out
        return plan


NODES = [CleanPdbNode]
