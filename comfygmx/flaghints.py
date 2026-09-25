"""What can go in a node's *Extra flags* box, and what each flag means.

Every node carries an Extra flags box so a flag we did not model is still
reachable.  For a long time every one of those boxes offered the same example
-- ``-nsteps 5000 -maxwarn 1`` -- on the node that runs ``gmx sasa`` as
readily as on the one that runs ``grompp``, so it told you nothing about the
node in front of you and its example was wrong for nearly all of them.  A box
you have to leave the program to use is barely a box.

So each node names the command its extra flags are appended to, in
``Node.extra_command``, and this module turns that name into

* an example built from a flag that command really has,
* the flag list itself, one line of definition each, in the command's own
  words,
* a mark on every flag the node already sets, because those are the ones that
  must *not* be typed again -- GROMACS refuses a flag given twice.

Nothing here is invented.  The definitions come from the programs:
``gmx help <subcommand>`` prints a machine-readable OPTIONS block, a script
Comfy-gmx writes itself has its flags in its ``add_argument`` calls, and a
third-party program is asked for ``--help``.  ``tools/harvest_flags.py`` does
that once and checks the answers in as ``data/flags.json``, so a user without
martinize2 installed still gets martinize2's list; a command missing from the
file -- because the tool it belongs to was not installed on the machine that
harvested -- is asked for on demand and remembered for the session.

A node with no single command -- one that copies files, writes a config, draws
a picture -- leaves ``extra_command`` empty and gets no box at all, which is
more honest than a box whose contents go nowhere.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DATA_FILE = Path(__file__).parent / "data" / "flags.json"

#: Commands that are scripts Comfy-gmx writes into the work directory.  Their
#: flags come from the ``add_argument`` calls in the source, read rather than
#: run: a script that imports a program it drives at the top could not print
#: even its list of flags without that program installed.
EMBEDDED = {
    "clean_pdb.py": "prep_nodes:_CLEAN_SCRIPT",
}

#: Programs we did not write, and how to make each one print its options.
#: ``argv`` may name a script under the sources directory the installer checks
#: things out into; ``{src}`` is expanded when the command is run.
THIRD_PARTY: Dict[str, Dict[str, Any]] = {
    "curl": {"tool": "shell", "command": "curl", "argv": ["--help", "all"]},
}


#: Examples worth putting in front of somebody, in the order they are tried:
#: a node that already has a box for the first one gets the second.  Anything
#: not listed here gets an example built from the command's own first
#: unmodelled option, which is always a flag that command accepts and is at
#: worst uninteresting.
EXAMPLES = {
    "gmx grompp": ["-maxwarn 1", "-pp processed.top"],
    "gmx mdrun": ["-noddcheck -rdd 2.0", "-pin on"],
    "gmx pdb2gmx": ["-ignh", "-heavyh"],
    "gmx editconf": ["-princ", "-rotate 0 0 90"],
    "gmx solvate": ["-scale 0.57", "-shell 1.0"],
    "gmx genion": ["-rmin 0.6"],
    "gmx trjconv": ["-dt 1000", "-fit rot+trans"],
    "gmx make_ndx": ["-natoms 65199"],
    "gmx energy": ["-nmol 128", "-fluct_props"],
    "gmx rms": ["-tu ns", "-what rhodev"],
    "gmx rmsf": ["-res", "-fit"],
    "gmx gyrate": ["-selrpos res_com", "-tu ns"],
    "gmx sasa": ["-probe 0.26", "-ndots 48"],
    "gmx mindist": ["-pi", "-respertime"],
    "gmx density": ["-center", "-symm"],
    "gmx hbond": ["-dist hbdist.xvg", "-ang hbang.xvg"],
    "gmx dssp": ["-hmode gromacs", "-polypro"],
    "gmx clustsize": ["-mol", "-cut 0.35"],
    "gmx select": ["-selrpos res_com", "-seltype res_com"],
    "gmx insert-molecules": ["-try 100", "-rot xyz"],
    "curl": ["--limit-rate 2M", "-u user:password"],
}


#: Flags that are true of every GROMACS tool and interesting on none of them.
#: An example built out of one of these is a wasted example.
_DULL = {"-v", "-nov", "-quiet", "-noquiet", "-h", "-nice", "-backup",
         "-nobackup", "-version", "-copyright", "-cite", "-debug", "-hidden",
         "-w", "-now", "-nowarn", "-xvg", "-verbose", "--verbose", "--debug",
         "-[no]v", "-[no]quiet", "-[no]backup", "-[no]w", "-[no]h"}

#: Type token -> something plausible to put after the flag in an example.
_SAMPLE = {
    "<int>": "1", "<real>": "1.0", "<time>": "1000", "<string>": "text",
    "<enum>": "", "<vector>": "1 1 1", "<selection>": "'name CA'",
    "<file>": "file.dat", "<value>": "value", "<dir>": "somewhere",
}

_LITERAL_FLAG = re.compile(r"""["'](-{1,2}[A-Za-z][\w-]*)["']""")

_CACHE: Optional[Dict[str, Any]] = None
#: Commands harvested from the local machine because the shipped file has no
#: entry for them.  Session-only: the checked-in file is the harvester's.
_LIVE: Dict[str, Dict[str, Any]] = {}


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------

def load() -> Dict[str, Any]:
    """The harvested flag catalogue, read once."""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(DATA_FILE.read_text())
        except (OSError, ValueError):
            _CACHE = {"commands": {}}
    return _CACHE


def forget() -> None:
    """Drop what was read and what was harvested live; used by the tools."""
    global _CACHE
    _CACHE = None
    _LIVE.clear()


def entry_for(command: str) -> Dict[str, Any]:
    if command in _LIVE:
        return _LIVE[command]
    return (load().get("commands") or {}).get(command) or {}


def commands_in_use(registry: Any) -> List[str]:
    """Every distinct command the nodes append their extra flags to."""
    seen = []
    for _, cls in registry.items():
        command = getattr(cls, "extra_command", "")
        if command and command not in seen:
            seen.append(command)
    return sorted(seen)


def flags_for(command: str) -> List[Dict[str, Any]]:
    return list(entry_for(command).get("flags") or [])


def source_of(command: str) -> str:
    return str(entry_for(command).get("source") or "")


# --------------------------------------------------------------------------
# Reading a program's help
# --------------------------------------------------------------------------

#: ``Options to specify input files:`` and friends, plus ``Other options:``.
_SECTION = re.compile(
    r"^(Options to specify (?P<what>[\w/ ]+) files|Other options)\s*:\s*$")
#: An option line starts at exactly one space.  Its description is indented far
#: further, which is what keeps a wrapped description from looking like a flag.
_OPTION = re.compile(r"^ (-\[no\][\w-]+|-[\w-]+)(?P<rest>\s.*)?$")


def _split_rest(rest: str) -> Dict[str, Any]:
    """``[<.mdp>]  (grompp.mdp)  (Opt.)`` -> type, default, optional."""
    text = (rest or "").strip()
    optional = False
    if text.endswith("(Opt.)"):
        optional = True
        text = text[: -len("(Opt.)")].rstrip()
    default = ""
    if text.endswith(")"):
        # The default is the last balanced (...) group; the type may itself
        # contain brackets -- '[<.xvg> [...]]' -- so scan from the right.
        depth = 0
        for i in range(len(text) - 1, -1, -1):
            if text[i] == ")":
                depth += 1
            elif text[i] == "(":
                depth -= 1
                if depth == 0:
                    default = text[i + 1:-1]
                    text = text[:i].rstrip()
                    break
    return {"takes": text, "default": default, "optional": optional}


def parse_gmx_help(text: str) -> List[Dict[str, Any]]:
    """The OPTIONS block of ``gmx help <cmd>`` as a list of flags."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "OPTIONS")
    except StopIteration:
        return []
    flags: List[Dict[str, Any]] = []
    section = "other"
    current: Optional[Dict[str, Any]] = None
    for line in lines[start + 1:]:
        heading = _SECTION.match(line.strip())
        if heading:
            current = None
            what = (heading.group("what") or "").strip()
            section = what if what in ("input", "output", "input/output") else "other"
            continue
        match = _OPTION.match(line)
        if match:
            current = {"flag": match.group(1), "section": section, "what": "",
                       **_split_rest(match.group("rest") or "")}
            flags.append(current)
            continue
        if current is not None and line.strip():
            # Descriptions are wrapped; join them back into one sentence.
            current["what"] = (current["what"] + " " + line.strip()).strip()
        elif not line.strip():
            current = None
    return flags


def parse_add_arguments(source: str) -> List[Dict[str, Any]]:
    """Flags of an argparse script, from its ``add_argument`` calls."""
    tree = ast.parse(source)
    flags: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        names = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        named = [n for n in names if n.startswith("-")]
        if not named:
            continue  # a positional argument is not something to type in the box
        keywords = {kw.arg: kw.value.value for kw in node.keywords
                    if kw.arg and isinstance(kw.value, ast.Constant)}
        action = str(keywords.get("action") or "")
        takes = "" if action in ("store_true", "store_false", "count") \
            else f"<{keywords.get('metavar') or 'value'}>"
        default = keywords.get("default", "")
        flags.append({
            "flag": named[0],
            "aliases": named[1:],
            "takes": takes,
            "default": "" if default in (None, "") else str(default),
            "optional": True,
            "section": "other",
            "what": str(keywords.get("help") or "").strip(),
        })
    return flags


_HELP_OPTION = re.compile(r"^\s{1,10}(-[^\s,]+)((?:,\s*-[^\s,]+)*)(\s.*)?$")
_HELP_HEADING = re.compile(
    r"^(positional arguments|options|optional arguments|[A-Z][\w ]+)\s*:\s*$")


#: One flag inside an option spec, with the metavar argparse aligns after it.
_SPEC_FLAG = re.compile(r"^(-[^\s,]+)")
_SPEC_METAVAR = re.compile(r"^(<[^>]*>|[A-Z][A-Z0-9_]*(?:\s*\[[^\]]*\])?"
                           r"(?:\s+\.\.\.)?)")


def split_option_spec(text: str) -> Dict[str, Any]:
    """``--alt-svc <file name> Enable alt-svc`` -> names, what it takes, the rest.

    Every program spells this line slightly differently and the naive reading
    -- first word is the flag, second is the type -- gets most of them wrong.
    ``-a, --append`` puts two names first; curl writes ``<file name>`` with a
    space inside the brackets; argparse writes ``--program PROGRAM, -program
    PROGRAM``, repeating the metavar after each alias.  So walk it: a flag,
    optionally a metavar, and either a comma and another flag or the end of
    the spec.
    """
    names: List[str] = []
    takes = ""
    rest = text.strip()
    while True:
        flag = _SPEC_FLAG.match(rest)
        if not flag:
            break
        name = flag.group(1)
        rest = rest[flag.end():].lstrip()
        if "=" in name:
            # optparse, which PDBFixer still uses: '--pdbid=PDBID'.
            name, _, attached = name.partition("=")
            takes = takes or f"<{attached.strip().lower()}>"
        names.append(name)
        metavar = _SPEC_METAVAR.match(rest)
        if metavar:
            takes = takes or f"<{metavar.group(1).strip().strip('<>').lower()}>"
            rest = rest[metavar.end():].lstrip()
        if rest.startswith(","):
            rest = rest[1:].lstrip()
            continue
        break
    return {"names": names, "takes": takes, "what": rest.strip()}


def parse_help_output(text: str) -> List[Dict[str, Any]]:
    """Flags of a program that prints an argparse-shaped ``--help``.

    The headings are optional.  curl prints ``Usage:`` and then two hundred
    options with no ``options:`` line anywhere, so a parser that waits for one
    finds nothing at all; when no heading ever arrives, every option-shaped
    line counts.
    """
    lines = text.splitlines()
    headed = any(_HELP_HEADING.match(line.strip()) for line in lines)
    flags: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    listing = not headed
    for line in lines:
        stripped = line.strip()
        if not stripped:
            current = None
            continue
        if headed and _HELP_HEADING.match(stripped):
            listing = "positional" not in stripped.lower()
            current = None
            continue
        if not listing:
            continue
        match = _HELP_OPTION.match(line.rstrip())
        if match and not line.startswith("       "):
            # argparse aligns the description into its own column, so where
            # there is a run of spaces the description is everything after it
            # and nothing in it can be mistaken for a metavar.
            columns = re.split(r"\s{2,}", stripped, maxsplit=1)
            spec = split_option_spec(columns[0])
            what = columns[1].strip() if len(columns) > 1 else spec["what"]
            names = spec["names"] or [stripped.split()[0]]
            # The long spelling is the one worth showing: '--append' says what
            # it does where '-a' does not.
            long_first = sorted(names, key=lambda n: (not n.startswith("--"),
                                                      names.index(n)))
            current = {"flag": long_first[0],
                       "aliases": [n for n in names if n != long_first[0]],
                       "takes": spec["takes"], "default": "", "optional": True,
                       "section": "other", "what": what}
            flags.append(current)
        elif current is not None:
            current["what"] = (current["what"] + " " + stripped).strip()
    return flags


#: insane and its descendants: a flag, the description, then ``( default )``.
_LOOSE_OPTION = re.compile(
    r"^\s{1,8}(-[\w-]+)\s\s+(?P<what>.*?)\s*(?:\(\s*(?P<default>[^()]*?)\s*\)\s*)?$")


def parse_loose_help(text: str) -> List[Dict[str, Any]]:
    """Flags of a program that prints ``-flag   what it does ( default )``."""
    flags: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = _LOOSE_OPTION.match(line.rstrip())
        if not match:
            continue
        default = (match.group("default") or "").strip()
        if default in ("None", "[]", "-"):
            default = ""
        flags.append({"flag": match.group(1), "aliases": [], "takes": "",
                      "default": default, "optional": True, "section": "other",
                      "what": match.group("what").strip()})
    return flags


def parse_table_help(text: str) -> List[Dict[str, Any]]:
    """Flags of a program that prints a table: option, type, default, what.

    TS2CG's, and it is a table of fixed columns rather than sentences, so the
    columns are what has to be read.  ``------`` in the type column is how it
    spells a switch.
    """
    lines = text.splitlines()
    flags: List[Dict[str, Any]] = []
    seen_header = False
    for line in lines:
        stripped = line.strip()
        if not seen_header:
            seen_header = (stripped.startswith("option")
                           and stripped.endswith("description"))
            continue
        if not stripped.startswith("-") or stripped.startswith("---"):
            continue
        cells = re.split(r"\s{2,}", stripped)
        if len(cells) < 2:
            continue
        kind = cells[1] if len(cells) > 1 else ""
        takes = "" if set(kind) <= set("-") else f"<{kind}>"
        default = cells[2] if len(cells) > 2 else ""
        if set(default) <= set("-"):
            default = ""
        flags.append({"flag": cells[0], "aliases": [], "takes": takes,
                      "default": default, "optional": True, "section": "other",
                      "what": cells[3] if len(cells) > 3 else ""})
    return flags


# --------------------------------------------------------------------------
# Asking the programs
# --------------------------------------------------------------------------

def embedded_source(where: str) -> str:
    """``prep_nodes:_CLEAN_SCRIPT`` -> the text of that script."""
    module_name, _, attribute = where.partition(":")
    module = __import__(f"comfygmx.nodes.{module_name}", fromlist=[attribute])
    source = getattr(module, attribute, None)
    if not isinstance(source, str):
        raise ValueError(f"{where} is not an embedded script")
    return source


def run_help(toolbox: Any, tool_id: str, argv: Sequence[str],
             command: str = "", timeout: float = 90.0) -> str:
    """Run a help command inside whatever environment the tool lives in."""
    resolved = toolbox.resolve(tool_id)
    binary = command or resolved.command or tool_id
    # "{src}/<tool>/x.py" is the checkout, which the user may have pointed
    # somewhere else; expand that form first so an override is honoured.
    settings = toolbox.settings
    src = str(getattr(settings, "sources_dir", ""))
    resolve = getattr(settings, "source_dir", None)
    checkout = str(resolve(tool_id)) if callable(resolve) else f"{src}/{tool_id}"
    parts = [str(a).replace("{src}/" + tool_id, checkout).replace("{src}", src)
             for a in argv]
    script = f"{resolved.prelude}\n{binary} {' '.join(parts)}"
    try:
        done = subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"!! {exc}"
    # Kept apart rather than merged with 2>&1. GROMACS block-buffers its help
    # and writes its parting quotation unbuffered to stderr, so merging drops
    # the quote into the middle of the option table -- which cost 'gmx hbond
    # -dt' its description, and would have cost a different flag on a
    # different machine. Both streams are read because some programs print
    # their help on stderr.
    return (done.stdout or "") + "\n" + (done.stderr or "")


#: Not worth offering: -h prints help instead of running the node, and
#: --version does the same.  A list that starts with them wastes its first
#: two lines on the two flags that break the step.
_NOT_WORTH_LISTING = {"-h", "--help", "-help", "--version", "-version", "-V",
                      "--changes", "--changelog", "--version_changes"}


def _worth_listing(flags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [f for f in flags if f["flag"] not in _NOT_WORTH_LISTING]


def harvest(command: str, toolbox: Any, timeout: float = 90.0) -> Dict[str, Any]:
    """One command's flag list, from whichever source knows about it."""
    if command.startswith("gmx "):
        sub = command.split(" ", 1)[1].split(" ")[0]
        text = run_help(toolbox, "gmx", ["help", sub], timeout=timeout)
        flags = _worth_listing(parse_gmx_help(text))
        if not flags:
            return {"error": f"'gmx help {sub}' printed no options"}
        version = re.search(r"GROMACS - gmx, ([\w.]+)", text)
        return {"flags": flags,
                "source": f"gmx help {sub}"
                          + (f" (GROMACS {version.group(1)})" if version else "")}
    if command in EMBEDDED:
        try:
            flags = _worth_listing(parse_add_arguments(embedded_source(EMBEDDED[command])))
        except (ValueError, SyntaxError) as exc:
            return {"error": str(exc)}
        return {"flags": flags, "source": f"the {command} Comfy-gmx runs"}
    if command in THIRD_PARTY:
        spec = THIRD_PARTY[command]
        text = run_help(toolbox, spec["tool"], spec["argv"], spec.get("command", ""),
                        timeout=timeout)
        reader = {"loose": parse_loose_help, "table": parse_table_help}.get(
            spec.get("parse", ""), parse_help_output)
        flags = _worth_listing(reader(text))
        if not flags:
            first = (text.strip().splitlines() or [""])[0][:80]
            return {"error": f"{command} printed no options ({first})"}
        # "TS2CG PCG -h", not "TS2CG PCG PCG -h": the subcommand is part of
        # the command's name as well as the first argument.
        words = [str(a) for a in spec["argv"]
                 if "{src}" not in str(a) and not command.endswith(str(a))]
        return {"flags": flags, "source": " ".join([command] + words)}
    return {"error": "nothing here knows how to ask this command for its flags"}


def harvest_live(command: str, settings: Any) -> Dict[str, Any]:
    """Ask the local machine about a command the shipped file does not have.

    The catalogue is harvested on one machine and cannot cover a tool that
    machine did not have installed.  Rather than show an empty list to
    somebody who *does* have it, ask, and keep the answer for this session.
    """
    if command in _LIVE:
        return _LIVE[command]
    from .environments import Toolbox
    # Short, because this runs inside a request: the browser is waiting for a
    # list to draw. A program that is not installed fails in milliseconds; one
    # that hangs must not hold the connection for a minute and a half.
    result = harvest(command, Toolbox(settings), timeout=20.0)
    # A failure is remembered too. Otherwise every open of that reference
    # shells out again to be told the same thing.
    _LIVE[command] = {} if result.get("error") else {
        "source": result["source"], "flags": result["flags"], "live": True}
    return _LIVE[command]


# --------------------------------------------------------------------------
# What a node already puts on the command line
# --------------------------------------------------------------------------

def modelled_by(cls: Any, command: str = "") -> List[str]:
    """Flags this node writes itself, so the box must not repeat them.

    Two sources, because neither alone is enough.  The literals in the node's
    ``plan`` are most of it, but a node that builds a flag out of a parameter
    name -- the analysis nodes do, ``-probe`` from ``probe`` -- leaves no
    literal to find.  So a parameter whose name *is* a flag of this command
    counts as modelled too; checking the guess against the real flag list is
    what stops ``begin`` and ``output`` claiming flags that do not exist.
    """
    command = command or getattr(cls, "extra_command", "")
    found = set()
    plan = getattr(cls, "plan", None)
    try:
        source = inspect.getsource(plan) if plan is not None else ""
    except (OSError, TypeError):
        source = ""
    for match in _LITERAL_FLAG.finditer(source):
        found.add(match.group(1))
    flags = flags_for(command)
    real = {flag["flag"] for flag in flags}
    # A node writes whichever spelling is shorter and the list stores the one
    # that explains itself, so '-i' in the source is '--infile' in the list.
    for flag in flags:
        for alias in flag.get("aliases") or []:
            real.add(alias)
            if alias in found:
                found.add(flag["flag"])
    for param in getattr(cls, "params", ()) or ():
        for guess in ("-" + param.name.replace("_", "-"),
                      "--" + param.name.replace("_", "-")):
            if guess in real:
                found.add(guess)
    # '-[no]v' is how GROMACS spells a switch; a node writes '-v' or '-nov'.
    for flag in flags:
        name = flag["flag"]
        if name.startswith("-[no]"):
            stem = name[len("-[no]"):]
            if f"-{stem}" in found or f"-no{stem}" in found:
                found.add(name)
    return sorted(found)


def spellings(command: str) -> set:
    """Every way of writing a flag of this command that the command accepts.

    Three ways, all real: the name in the list, an alias (``-u`` for
    ``--user``), and -- GROMACS only -- the negative of a switch, since
    ``-[no]ddcheck`` in the help means both ``-ddcheck`` and ``-noddcheck``
    work.
    """
    names = set()
    for flag in flags_for(command):
        name = flag["flag"]
        names.add(name)
        names.update(flag.get("aliases") or [])
        if name.startswith("-[no]"):
            stem = name[len("-[no]"):]
            names.add(f"-{stem}")
            names.add(f"-no{stem}")
    return names


def example_for(command: str, modelled: Sequence[str] = ()) -> str:
    """Something real to show in the empty box.

    A curated example where one is worth showing, otherwise the command's own
    first option this node has not already taken -- which is always a flag
    that command accepts, and is at worst uninteresting.
    """
    taken = set(modelled)
    listed = spellings(command)
    for curated in EXAMPLES.get(command, ()):
        head = curated.split(" ", 1)[0]
        if head in taken:
            continue
        # Checked against the command's own list, so a curated example cannot
        # outlive the flag it names -- and cannot have been wrong to begin
        # with. Where there is no list to check against, it is taken on trust.
        if listed and head.lstrip("-") and head not in listed:
            continue
        return curated

    def rank(flag: Dict[str, Any]) -> tuple:
        # A flag that takes a value shows more of how the box works than a
        # switch does, and anything in _DULL shows nothing at all.
        return (flag["flag"] in _DULL, not flag.get("takes"))

    free = [f for f in flags_for(command)
            if f["flag"] not in taken and f.get("section", "other") == "other"]
    for flag in sorted(free, key=rank):
        name = flag["flag"]
        if name.startswith("-[no]"):
            return "-" + name[len("-[no]"):]
        takes = flag.get("takes") or ""
        sample = _SAMPLE.get(takes) or str(flag.get("default") or "")
        if not sample and takes:
            sample = takes.strip("<>").upper()
        return f"{name} {sample}".strip()
    return ""


def hint(cls: Any) -> Optional[Dict[str, Any]]:
    """The small block of per-node help that travels with the node's spec.

    The flag list itself does not travel with it: ``gmx mdrun`` alone has over
    a hundred, and sending every command's list to the browser along with the
    node catalogue would cost more than the catalogue.  The browser asks for
    one list when somebody opens one node's reference.
    """
    command = getattr(cls, "extra_command", "")
    if not command:
        return None
    modelled = modelled_by(cls, command)
    flags = flags_for(command)
    taken = set(modelled)
    listed = {f["flag"] for f in flags}
    return {
        "command": command,
        "docs": getattr(cls, "docs", "") or "",
        "source": source_of(command),
        "example": example_for(command, modelled),
        # Only the ones the reference will actually show as taken: a node
        # writes '-o' on plenty of commands whose help calls it something
        # else, and counting those makes 'sets 4 of 1' out of one flag.
        "modelled": [f for f in modelled if f in listed],
        "available": sum(1 for f in flags if f["flag"] not in taken),
        "total": len(flags),
    }


def reference(command: str, node_type: str = "", registry: Any = None,
              settings: Any = None) -> Dict[str, Any]:
    """The full flag list for one command, marked up for one node.

    ``used`` means the node sets that flag itself.  Those are shown, greyed,
    with the widget that owns them named, rather than hidden: somebody looking
    for ``-tu`` should find out that the node has a box for it, not conclude
    the command has no such flag.
    """
    entry = entry_for(command)
    if not entry.get("flags") and settings is not None:
        entry = harvest_live(command, settings) or entry
    cls = None
    if node_type and registry is not None and registry.has(node_type):
        cls = registry.get(node_type)
    modelled = set(modelled_by(cls, command)) if cls is not None else set()
    labels: Dict[str, str] = {}
    if cls is not None:
        for param in getattr(cls, "params", ()) or ():
            for guess in ("-" + param.name.replace("_", "-"),
                          "--" + param.name.replace("_", "-")):
                labels[guess] = param.label or param.name
    flags = []
    for flag in entry.get("flags") or []:
        name = flag["flag"]
        bare = "-" + name[len("-[no]"):] if name.startswith("-[no]") else name
        flags.append({**flag, "used": name in modelled or bare in modelled,
                      "widget": labels.get(name) or labels.get(bare, "")})
    return {
        "command": command,
        "source": entry.get("source", ""),
        "docs": entry.get("docs", ""),
        "flags": flags,
    }
