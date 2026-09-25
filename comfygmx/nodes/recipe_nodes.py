"""Blocks that used to be scripts in the tutorials.

Every one of these started life as a "Shell command" or "Python script" block
in a packaged tutorial, with the job written out in code.  The person
following the tutorial did not need to read that code -- but they could not
change what it did without reading it, and a block full of code is exactly
what somebody who came here to avoid code does not want to meet.

So each job is now a block with boxes: the numbers and names that were
hard-wired in the script are the boxes, the script travels inside the block,
and the block says in plain words what it is for.  Nothing about the work
changed; the scripts below are the tutorials' own, with their settings
lifted out.
"""

from __future__ import annotations

from typing import List

from .base import Node, NodeError, Param, PlanContext, Plan, Port

IO = "Input / Output"
IO_COLOR = "#4a6a4a"
ANALYSIS = "Analysis"
ANALYSIS_COLOR = "#3f7a6d"


def _lines(text: str) -> List[str]:
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


# ==========================================================================
# Edit a text file
# ==========================================================================

_EDIT_TEXT = r'''#!/usr/bin/env python3
"""Apply a short list of plain-language rules to a text file.

Rules, one per line (the words before the colon are the rule):

    replace: OLD => NEW
    delete lines containing: TEXT
    delete lines starting with: TEXT
    uncomment lines starting with: TEXT      (drops a leading ; or #)
    comment out lines starting with: TEXT    (puts a ; in front)
    first line: TEXT
    append: TEXT
    insert before line starting with: TEXT   (inserts the --insert file)
    insert after line starting with: TEXT

A rule that finds nothing to do is an error, unless the file already looks
the way the rule wants it -- then it says so and carries on, so running the
same graph twice is safe. --tolerate makes every no-op a plain remark.
"""
import argparse
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("target")
ap.add_argument("--rules", required=True)
ap.add_argument("--insert", default="")
ap.add_argument("--tolerate", action="store_true")
ap.add_argument("--check", default="", help="afterwards, this text must appear...")
ap.add_argument("--count", type=int, default=-1, help="...on exactly this many lines")
a = ap.parse_args()

text = open(a.source, encoding="utf-8", errors="replace").read()
insert = open(a.insert, encoding="utf-8").read() if a.insert else ""
rules = [ln.strip() for ln in open(a.rules, encoding="utf-8") if ln.strip()
         and not ln.strip().startswith("#")]
failures = []


def say(msg):
    print(">> " + msg)


def leading(line):
    return line[:len(line) - len(line.lstrip())]


def nothing(what, already):
    if already:
        say(what + " -- already the case; left alone")
    elif a.tolerate:
        say(what + " -- nothing matched; carrying on")
    else:
        failures.append(what + " -- nothing matched")


for rule in rules:
    head, _, rest = rule.partition(":")
    kind = " ".join(head.lower().split())
    arg = rest.strip()
    lines = text.split("\n")
    if kind == "replace":
        old, sep, new = arg.partition("=>")
        if not sep:
            failures.append(f"'{rule}': write it as  replace: OLD => NEW")
            continue
        old, new = old.strip(), new.strip()
        # Runs of spaces in OLD match any run of spaces in the file, and
        # the file's own spacing is kept when NEW has the same number of
        # words -- so "140   VC3B" finds the line however it is aligned.
        words = old.split()
        if len(words) > 1:
            pattern = re.compile(r"(\s+)".join(re.escape(w) for w in words))
            new_words = new.split()

            def swap(m, new_words=new_words):
                if len(new_words) == len(words):
                    out = new_words[0]
                    for i, w in enumerate(new_words[1:], 1):
                        out += m.group(i) + w
                    return out
                return new
            text, n = pattern.subn(swap, text)
            already = bool(new) and re.search(
                r"\s+".join(re.escape(w) for w in new.split()), text) is not None
        else:
            n = text.count(old)
            if n:
                text = text.replace(old, new)
            already = bool(new) and new in text
        if n:
            say(f"replaced '{old}' with '{new}' ({n} place{'s' if n != 1 else ''})")
        else:
            nothing(f"replace '{old}'", already)
    elif kind in ("delete lines containing", "delete lines starting with"):
        starts = kind.endswith("starting with")
        keep = [ln for ln in lines
                if not (ln.lstrip().startswith(arg) if starts else arg in ln)]
        n = len(lines) - len(keep)
        if n:
            text = "\n".join(keep)
            say(f"deleted {n} line{'s' if n != 1 else ''} "
                f"{'starting with' if starts else 'containing'} '{arg}'")
        else:
            nothing(f"delete lines {'starting with' if starts else 'containing'} '{arg}'", False)
    elif kind == "uncomment lines starting with":
        n = 0
        out = []
        for ln in lines:
            body = ln.lstrip()
            if body[:1] in (";", "#") and body[1:].lstrip().startswith(arg):
                out.append(leading(ln) + body[1:].lstrip())
                n += 1
            else:
                out.append(ln)
        if n:
            text = "\n".join(out)
            say(f"uncommented {n} line{'s' if n != 1 else ''} starting with '{arg}'")
        else:
            nothing(f"uncomment lines starting with '{arg}'",
                    any(ln.lstrip().startswith(arg) for ln in lines))
    elif kind == "comment out lines starting with":
        n = 0
        out = []
        for ln in lines:
            if ln.lstrip().startswith(arg):
                out.append(leading(ln) + ";" + ln.lstrip())
                n += 1
            else:
                out.append(ln)
        if n:
            text = "\n".join(out)
            say(f"commented out {n} line{'s' if n != 1 else ''} starting with '{arg}'")
        else:
            nothing(f"comment out lines starting with '{arg}'",
                    any(ln.lstrip()[:1] == ";" and ln.lstrip()[1:].lstrip().startswith(arg)
                        for ln in lines))
    elif kind == "first line":
        if lines and lines[0] == arg:
            nothing("first line", True)
        else:
            lines[0:1] = [arg]
            text = "\n".join(lines)
            say(f"first line is now '{arg}'")
    elif kind == "append":
        if arg in text:
            nothing(f"append '{arg}'", True)
        else:
            text = text.rstrip("\n") + "\n" + arg + "\n"
            say(f"appended '{arg}'")
    elif kind in ("insert before line starting with", "insert after line starting with"):
        if not insert.strip():
            failures.append(f"'{rule}': the 'Text to insert' box is empty")
            continue
        marker = next((ln for ln in insert.split("\n") if ln.strip()), "").strip()
        if marker and any(ln.strip() == marker for ln in lines):
            nothing(f"insert at '{arg}'", True)
            continue
        where = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith(arg)), None)
        if where is None:
            nothing(f"insert at line starting with '{arg}'", False)
            continue
        block = insert.rstrip("\n").split("\n")
        at = where if kind.startswith("insert before") else where + 1
        lines[at:at] = block + [""] if kind.startswith("insert before") else [""] + block
        text = "\n".join(lines)
        say(f"inserted {len(block)} line{'s' if len(block) != 1 else ''} "
            f"{'before' if kind.startswith('insert before') else 'after'} '{arg}'")
    else:
        failures.append(f"'{rule}': not a rule this block knows")

if a.check:
    wanted = re.compile(r"\s+".join(re.escape(w) for w in a.check.split()))
    n = sum(1 for ln in text.split("\n") if wanted.search(ln))
    if a.count >= 0 and n != a.count:
        failures.append(f"afterwards, '{a.check}' is on {n} line(s), not {a.count}")
    elif a.count < 0 and n == 0:
        failures.append(f"afterwards, '{a.check}' is not in the file at all")
    else:
        say(f"check passed: '{a.check}' is on {n} line(s)")

open(a.target, "w", encoding="utf-8").write(text)
if failures:
    for f in failures:
        print("!! " + f, file=sys.stderr)
    sys.exit(1)
say("written to " + a.target)
'''


class EditTextNode(Node):
    type = "util.edit_text"
    title = "Edit a text file"
    category = IO
    color = IO_COLOR
    tool = "python"
    description = (
        "Makes small, exact changes to a text file -- a topology, a settings "
        "file, a structure, a mapping file -- by rules written in plain words, "
        "and says what each rule did.\n\n"
        "This is the block for the little corrections that published files "
        "need: an #include that points at a file GROMACS no longer ships, an "
        "ion that is commented out, a residue name that is wrong on every "
        "line, a section a newer GROMACS insists on. Each rule is one line, "
        "such as  replace: OLD => NEW  or  uncomment lines starting with: NA.\n\n"
        "A rule that finds nothing is an error, unless the file already looks "
        "the way the rule wants -- then it says so and carries on, so the same "
        "graph can be run twice. The file that comes out keeps the kind of the "
        "file that went in: a topology stays a topology, a structure a structure."
    )
    inputs = (Port("file", "any", "file to edit"),)
    outputs = (Port("out", "any", "edited file", follows="output"),)
    params = (
        Param("rules", "text", "Rules, one per line", "", rows=4, form="text.rules",
              placeholder="replace: #include \"spc.itp\" => #include \"gromos43a1.ff/spc.itp\"",
              help="Write each rule as the words, a colon, then the text it "
                   "works on:\n\n"
                   "  replace: OLD => NEW\n"
                   "  delete lines containing: TEXT\n"
                   "  delete lines starting with: TEXT\n"
                   "  uncomment lines starting with: TEXT\n"
                   "  comment out lines starting with: TEXT\n"
                   "  first line: TEXT\n"
                   "  append: TEXT\n"
                   "  insert before line starting with: TEXT\n"
                   "  insert after line starting with: TEXT\n\n"
                   "The two insert rules put in whatever is in the 'Text to "
                   "insert' box. Rules run in order, top to bottom."),
        Param("insert", "text", "Text to insert", "", rows=4, advanced=True,
              help="Used by the 'insert before' and 'insert after' rules. "
                   "Several lines are fine; they go in as written."),
        Param("output", "str", "Output name", "edited.txt",
              help="Give it the right ending -- .top, .gro, .pdb, .map -- and "
                   "the next block sees a file of that kind."),
        Param("tolerate", "bool", "Carry on when a rule finds nothing", False,
              help="Off, a rule that changes nothing stops the graph, which is "
                   "how you find out the file is not what you thought. On, it "
                   "only says so."),
        Param("check", "str", "Afterwards, this text must be in the file", "",
              advanced=True, placeholder="e.g. VC3B"),
        Param("count", "int", "...on exactly this many lines (blank or -1 = any)", -1,
              advanced=True, min=-1),
        Param("carry", "str", "Also bring along files matching", "", advanced=True,
              placeholder="*.itp",
              help="A topology comes with its .itp files beside it. Name them "
                   "here and they travel on with the edited file to the next "
                   "block, the way they came in."),
        Param("pick", "str", "Which file, if several arrived together", "",
              advanced=True, placeholder="dppc.charmm36.map",
              help="A download that took several files out of an archive hands "
                   "them all on together, with the first one in front. Name the "
                   "one to edit here; blank means the one in front."),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        source = ctx.require("file")
        if ctx.pstr("pick").strip():
            source = ctx.pstr("pick").strip()
        out = ctx.pstr("output") or "edited.txt"
        rules = _lines(ctx.pstr("rules"))
        if not rules:
            # No rules is not an error: the file goes through unchanged, and
            # the note says so, which is how you notice the box is empty.
            plan.notes.append("no rules yet, so the file passes through unchanged -- "
                              "add one such as  replace: OLD => NEW")
        plan.files["edit_text.py"] = _EDIT_TEXT
        plan.files["rules.txt"] = "\n".join(rules) + "\n"
        argv = ["python", "edit_text.py", source, out, "--rules", "rules.txt"]
        insert = ctx.pstr("insert")
        if insert.strip():
            plan.files["insert.txt"] = insert.rstrip("\n") + "\n"
            argv += ["--insert", "insert.txt"]
        if ctx.pbool("tolerate"):
            argv.append("--tolerate")
        check = ctx.pstr("check").strip()
        if check:
            argv += ["--check", check, "--count", str(ctx.pint("count", -1))]
        plan.step(argv, tool="python", label="edit the file")
        globs = ctx.pstr("carry").split()
        if out.lower().endswith(".top") or globs:
            plan.outputs["out"] = {"top": out, "glob": globs or ["*.itp"],
                                   "dirs": ctx.staged_dirs("file")}
        else:
            plan.outputs["out"] = out
        for rule in rules:
            plan.notes.append(rule)
        return plan


# ==========================================================================
# Analyses that were scripts
# ==========================================================================

_AREA_PER_LIPID = r'''#!/usr/bin/env python3
"""Area per lipid, from the x and y sides of the box.

A flat bilayer fills the box in x and y, and there are two leaflets, so the
area each lipid takes up is (x * y) divided by half the lipids.
"""
import argparse
import sys

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("box_xvg")
ap.add_argument("out")
ap.add_argument("--lipids", type=int, default=0)
ap.add_argument("--structure", default="")
ap.add_argument("--names", default="")
ap.add_argument("--expected", type=float, default=0.0)
ap.add_argument("--expected-label", default="")
a = ap.parse_args()

lipids = a.lipids
if not lipids:
    if not a.structure:
        sys.exit("say how many lipids there are, or wire in the structure so they can be counted")
    names = set(a.names.split())
    seen = set()
    with open(a.structure, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    if a.structure.lower().endswith(".gro"):
        for line in lines[2:]:
            if len(line) > 10 and line[5:10].strip() in names:
                seen.add(line[:10])
    else:
        for line in lines:
            if line.startswith(("ATOM", "HETATM")) and line[17:21].strip() in names:
                seen.add((line[21:22], line[22:27], line[17:21]))
    lipids = len(seen)
    if not lipids:
        sys.exit("no residues called any of " + a.names + " in " + a.structure)
    print("counted %d lipids in %s" % (lipids, a.structure))

rows = []
for line in open(a.box_xvg):
    if line.startswith(("#", "@")):
        continue
    parts = line.split()
    if len(parts) >= 3:
        rows.append([float(p) for p in parts[:3]])
data = np.array(rows)
if not len(data):
    sys.exit("no numbers in " + a.box_xvg + " -- it should hold time, Box-X and Box-Y")

time, box_x, box_y = data[:, 0], data[:, 1], data[:, 2]
area = box_x * box_y / (lipids / 2.0)

with open(a.out, "w") as out:
    out.write("@ title \"Area per lipid\"\n")
    out.write("@ xaxis label \"time (ps)\"\n")
    out.write("@ yaxis label \"area per lipid (nm\\S2\\N)\"\n")
    for t, v in zip(time, area):
        out.write("%12.3f %10.5f\n" % (t, v))

half = len(area) // 2
print("area per lipid over the whole run : %.4f nm2 (sd %.4f)" % (area.mean(), area.std()))
print("over the second half only         : %.4f nm2 (sd %.4f)" % (area[half:].mean(), area[half:].std()))
print("")
if a.expected:
    print("%s: about %.2f nm2." % (a.expected_label or "Expected", a.expected))
print("If the second half is still drifting rather than sitting still, the run is")
print("not equilibrated yet and the number above is not worth quoting.")
'''


class AreaPerLipidNode(Node):
    type = "analysis.area_per_lipid"
    title = "Area per lipid"
    category = ANALYSIS
    color = ANALYSIS_COLOR
    tool = "python"
    description = (
        "The single most reported number about a membrane, and the first to "
        "compare with experiment: how much of the membrane's surface each "
        "lipid takes up.\n\n"
        "A flat bilayer fills the box in x and y, and there are two leaflets, "
        "so the area per lipid is the box's x times y, divided by half the "
        "lipids. Wire in the box sizes over time -- the 'Energy terms' block "
        "with Box-X and Box-Y -- and either say how many lipids there are or "
        "wire in the structure so they are counted.\n\n"
        "The curve matters as well as the average: the part at the start "
        "where it is still shrinking has not equilibrated, and should be left "
        "out of everything else you measure."
    )
    inputs = (
        Port("xvg", "xvg", "Box-X and Box-Y over time"),
        Port("structure", "structure", "to count the lipids", optional=True),
    )
    outputs = (Port("xvg", "xvg", "area per lipid over time"),)
    params = (
        Param("lipids", "int", "How many lipids in the box", 0, min=0,
              help="0 means count them from the structure wired in."),
        Param("names", "str", "Residue names that are lipids",
              "DSPC DPPC DOPC POPC POPE POPS DLPC DBPC DMPC CHOL",
              help="Only used when counting from the structure."),
        Param("expected", "float", "Value from experiment (nm2)", 0.0, min=0.0,
              help="Printed beside the answer for comparison. 0 prints nothing."),
        Param("expected_label", "str", "What that value is", "", advanced=True,
              placeholder="DSPC in the fluid phase"),
        Param("output", "str", "Output name", "area_per_lipid.xvg", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        xvg = ctx.require("xvg")
        out = ctx.pstr("output") or "area_per_lipid.xvg"
        plan.files["area_per_lipid.py"] = _AREA_PER_LIPID
        argv = ["python", "area_per_lipid.py", xvg, out]
        lipids = ctx.pint("lipids", 0)
        structure = ctx.inp("structure")
        if lipids:
            argv += ["--lipids", str(lipids)]
        elif structure:
            argv += ["--structure", structure, "--names", ctx.pstr("names")]
        else:
            raise NodeError("say how many lipids there are, or wire in the structure so "
                            "they can be counted")
        if ctx.pfloat("expected", 0.0) > 0:
            argv += ["--expected", str(ctx.pfloat("expected")),
                     "--expected-label", ctx.pstr("expected_label") or "Experiment"]
        plan.step(argv, tool="python", label="area per lipid")
        plan.outputs["xvg"] = out
        return plan


# ==========================================================================
# A membrane that formed standing up
# ==========================================================================

_LAY_FLAT = r'''#!/usr/bin/env python3
"""Turn a membrane so that it lies flat, in the xy plane, with z across it.

A bilayer that builds itself from lipids thrown into a cubic box forms in
whichever direction chance picks. Everything after that assumes the xy plane:
the pressure control that treats the membrane's area separately from its
height, the density profile along z, the area per lipid from the box's x and
y. The Martini tutorial says to check, and to turn the system with
gmx editconf -rotate when it is not flat. This does that check and that turn.

How it tells which way the membrane faces: the phosphate beads of a bilayer
sit in two thin sheets. Cut the box into thin slices across each direction in
turn; across the membrane most slices hold no phosphate at all, along it
every slice holds some. The direction with the most empty slices is the one
the membrane faces.

Turning it is a relabelling of the axes -- x, y, z become y, z, x, or z, x, y,
which is a proper rotation, not a mirror image -- applied to the positions,
the velocities and the box alike. Nothing moves relative to anything else.

usage: lay_flat.py in.gro out.gro [--beads PO4]
Standard library only.
"""

import argparse
import sys

SLICES = 30


def main(argv=None):
    ap = argparse.ArgumentParser(description="Turn a membrane flat.")
    ap.add_argument("structure")
    ap.add_argument("out")
    ap.add_argument("--beads", default="PO4",
                    help="the name of one bead per lipid on the membrane surface")
    args = ap.parse_args(argv)

    if not args.structure.lower().endswith(".gro"):
        sys.exit(f"{args.structure} is not a .gro file: this reads the box and the "
                 "speeds from a .gro, and a .pdb does not carry the speeds")
    with open(args.structure) as fh:
        lines = fh.read().splitlines()
    count = int(lines[1])
    atoms = lines[2:2 + count]
    box_fields = lines[2 + count].split()
    box = [float(v) for v in box_fields[:3]]

    def copy_unchanged(message):
        with open(args.out, "w") as fh:
            fh.write("\n".join(lines[:3 + count]) + "\n")
        print(message)
        return 0

    if len(box_fields) > 3 and any(float(v) != 0.0 for v in box_fields[3:]):
        return copy_unchanged("the box is not rectangular, so it was left as it is")

    surface = [(float(a[20:28]), float(a[28:36]), float(a[36:44]))
               for a in atoms if a[10:15].strip() == args.beads]
    if not surface:
        sys.exit(f"no bead called {args.beads} in {args.structure}: say which bead "
                 "marks the surface of the membrane")

    empty = []
    limit = max(1, int(0.01 * len(surface)))
    for k in range(3):
        slices = [0] * SLICES
        for p in surface:
            slices[int((p[k] % box[k]) / box[k] * SLICES) % SLICES] += 1
        empty.append(sum(1 for s in slices if s <= limit) / SLICES)
    facing = max(range(3), key=lambda k: empty[k])
    shares = ", ".join(f"{'xyz'[k]} {100 * empty[k]:.0f}%" for k in range(3))
    print(f"slices with no {args.beads} in them, across each direction: {shares}")

    if empty[facing] < 0.4:
        return copy_unchanged(
            "no flat membrane found: the lipids are not in two sheets yet. It may "
            "still be a clump, a micelle, or a membrane with a hole in it. Left "
            "as it is -- look at it, and run the self-assembly again or longer.")
    if facing == 2:
        return copy_unchanged("the membrane already lies flat in the xy plane: "
                              "nothing to turn")

    # new[i] = old[order[i]]: the axis the membrane faces becomes z
    order = (1, 2, 0) if facing == 0 else (2, 0, 1)
    out = [lines[0].rstrip() + f" (turned: {'xyz'[facing]} is now z)", lines[1]]
    for a in atoms:
        xyz = [a[20:28], a[28:36], a[36:44]]
        rest = a[44:]
        line = a[:20] + "".join(xyz[i] for i in order)
        if len(rest) >= 24:
            vel = [rest[0:8], rest[8:16], rest[16:24]]
            line += "".join(vel[i] for i in order) + rest[24:]
        else:
            line += rest
        out.append(line)
    out.append("".join(f"{box[i]:10.5f}" for i in order))
    with open(args.out, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"the membrane faced along {'xyz'[facing]}; the system was turned so "
          f"that it lies flat in the xy plane, as the next run expects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class LayFlatNode(Node):
    type = "build.lay_flat"
    title = "Turn the membrane flat"
    category = "Build system"
    color = "#2b5d8a"
    tool = "python"
    description = (
        "Turns a membrane so that it lies flat in the xy plane, with z across "
        "it -- the way everything after a self-assembly expects it to lie.\n\n"
        "A bilayer that builds itself in a cubic box forms in whichever "
        "direction chance picks, and two times out of three that is not flat. "
        "The Martini tutorial says to check and to turn it with gmx editconf "
        "-rotate; this does both. It finds the direction the membrane faces "
        "from where its surface beads sit -- two thin sheets -- and relabels "
        "the axes so that direction becomes z. Positions, speeds and the box "
        "turn together, so nothing moves relative to anything else.\n\n"
        "If there is no membrane yet, it says so and passes the structure on "
        "unchanged."
    )
    docs = "https://cgmartini.nl/docs/tutorials/Martini3/LipidsI/"
    inputs = (Port("structure", "structure", "structure"),)
    outputs = (Port("structure", "structure", "flat"),)
    params = (
        Param("beads", "str", "Bead on the membrane surface", "PO4",
              help="The name of one bead per lipid that sits on the membrane's "
                   "surface. PO4, the phosphate, for Martini phospholipids."),
        Param("output", "str", "Output name", "flat.gro", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        structure = ctx.require("structure")
        out = ctx.pstr("output") or "flat.gro"
        plan.files["lay_flat.py"] = _LAY_FLAT
        plan.step(["python", "lay_flat.py", structure, out,
                   "--beads", ctx.pstr("beads") or "PO4"],
                  tool="python", label="turn the membrane flat")
        plan.outputs["structure"] = out
        return plan


NODES = [EditTextNode, AreaPerLipidNode, LayFlatNode]
