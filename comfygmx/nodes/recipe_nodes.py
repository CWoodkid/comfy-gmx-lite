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

from .base import Node, Param, PlanContext, Plan, Port

IO = "Input / Output"
IO_COLOR = "#4a6a4a"


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


NODES = [EditTextNode]
