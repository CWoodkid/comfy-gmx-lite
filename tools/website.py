"""Write the parts of the tutorial website that come straight from the tutorials.

The website (the folder website/, turned into pages by MkDocs) explains each
box of each tutorial in words of its own, and shows how to build that box by
hand. The facts on those pages -- which blocks, which settings, which wires,
which commands -- are not typed in by hand. They come from the tutorials
themselves, so that a page can never describe a box that is no longer there.
This script writes them into website/_generated/, and every page pulls in the
files that belong to it. A page's own words stay in the page.

For each box of each tutorial it writes two files:

  <tutorial>/box-<n>-build.md      the blocks to add, in order, each with the
                                   settings that differ from a fresh block and
                                   the wires that go into it
  <tutorial>/box-<n>-commands.md   what every block runs: the GROMACS
                                   commands, and the run-parameter files

and for each tutorial one more, <tutorial>/boxes.json: every box's blocks in
the order the pages number them. tools/website_pictures.js reads it to put
the same numbers on the blocks in the pictures.

The commands are the ones "Export scripts" writes for the same box, so they
are exactly what the editor would run, with plain file names.

Run it after any change to a tutorial or to a block's settings, and commit
what it writes. The self-test runs it with --check, and fails if the files
here and the tutorials disagree.

  python3 tools/website.py           write website/_generated/
  python3 tools/website.py --check   only say whether they are up to date
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comfygmx.config import Settings            # noqa: E402
from comfygmx.export import export_workflow     # noqa: E402
from comfygmx.graph import Graph                # noqa: E402
from comfygmx.nodes.util_nodes import MdpNode   # noqa: E402
from comfygmx.registry import REGISTRY          # noqa: E402
from comfygmx.templates import PRESETS          # noqa: E402
from comfygmx.tutorials import TUTORIALS        # noqa: E402

OUT = ROOT / "website" / "_generated"

# Circled numbers, the same ones the pictures carry on each block.
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# A value longer than this, or on more than one line, is shown as a block of
# text to copy rather than inside a sentence.
SHORT = 60


def port_colours() -> dict:
    """The colour of each kind of file, as the editor draws its dots
    (PORT_COLORS in graph.js), so the page's dots match the canvas."""
    js = (ROOT / "comfygmx" / "web" / "js" / "graph.js").read_text()
    block = re.search(r"const PORT_COLORS = \{(.*?)\};", js, re.S)
    return dict(re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", block.group(1))) if block else {}


COLOURS = port_colours()


def dot(kind: str) -> str:
    """A small coloured dot, the colour of a socket that carries `kind`."""
    colour = COLOURS.get(kind, COLOURS.get("any", "#8d97a5"))
    return f'<span class="socket" style="background:{colour}" title="{kind}"></span>'


def number(i: int) -> str:
    return CIRCLED[i - 1] if 0 < i <= len(CIRCLED) else f"({i})"


def show(value, param=None) -> str:
    """A setting's value, the way the box on the block shows it, on one line
    of a table. A box that takes one entry per line shows them in a row."""
    if isinstance(value, bool):
        return "ticked" if value else "not ticked"
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    if not lines:
        # A list to choose from calls its empty choice "(default)" (graph.js).
        if param and param.get("type") in ("choice", "combo") and "" in param.get("choices", []):
            return "`(default)`"
        return "*empty*"
    if len(lines) == 1:
        return f"`{lines[0]}`"
    return ", ".join(f"`{line}`" for line in lines) + " (one on each line)"


def squash(key) -> str:
    """An mdp option's name with - and _ left out, so that tau-t and tau_t
    are the same option, as GROMACS takes them (mdpSquash in graph.js)."""
    return re.sub(r"[-_]", "", str(key).strip().lower())


class Tutorial:
    """One tutorial, read once: its graph, its boxes, and what every block in
    them is (title, where it sits in the list, its sockets and settings)."""

    def __init__(self, entry: dict):
        self.id = entry["id"]
        self.name = entry["name"]
        self.graph = entry["graph"]
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        # The order to build in. Blocks that ship switched off (the extra
        # boxes) count too: they are built like any other, only not run.
        everything_on = copy.deepcopy(self.graph)
        for node in everything_on["nodes"]:
            node.pop("off", None)
        self.order = Graph(everything_on).topo_order()
        self.boxes = []
        self.box_of = {}
        for index, group in enumerate(self.graph.get("groups", []), start=1):
            members = set(group.get("nodes", []))
            # Notes explain; they are not part of what gets built.
            blocks = [n for n in self.order
                      if n in members and self.nodes[n]["type"] != "util.note"]
            self.boxes.append({"n": index, "title": group["title"], "blocks": blocks})
            for node_id in blocks:
                self.box_of[node_id] = index
        self.specs = {t: REGISTRY.get(t).spec() for t in {n["type"] for n in self.graph["nodes"]}}

    def spec(self, node_id: str) -> dict:
        return self.specs[self.nodes[node_id]["type"]]

    def label(self, node_id: str) -> str:
        """A block's name on the page: its number in its box, and its title."""
        box = self.box_of.get(node_id)
        if box is None:
            return f"**{self.spec(node_id)['title']}**"
        position = self.boxes[box - 1]["blocks"].index(node_id) + 1
        return f"{number(position)} **{self.spec(node_id)['title']}**"

    def port(self, node_id: str, name: str, side: str) -> dict:
        for port in self.spec(node_id)[side]:
            if port["name"] == name:
                return port
        return {"name": name, "label": name, "type": "any"}

    def mdp_edited(self, node_id: str) -> bool:
        """Is this a run-parameters block that starts from a preset and
        changes some of its values?"""
        node = self.nodes[node_id]
        return node["type"] == "util.mdp" and (node.get("params") or {}).get("mode") == "manual"

    def fresh(self, node_id: str, param: dict) -> str:
        """What a box shows before anybody types in it. An empty box on the
        run-parameters block shows, in grey, the value the run will use: the
        preset's, else GROMACS's own (_placeholder in graph.js)."""
        node = self.nodes[node_id]
        params = node.get("params") or {}
        key = MdpNode._WIDGET_MAP.get(param["name"])
        if node["type"] == "util.mdp" and key and params.get("mode", "preset") in ("preset", "manual"):
            preset = params.get("preset") or "md_atomistic"
            options = {squash(k): v for k, v in PRESETS.get(preset, {}).items()}
            value = options.get(squash(key))
            if value is not None and str(value).strip():
                return f"`{value}` (from {preset})"
            default = MdpNode._GROMACS_DEFAULTS.get(key)
            if default is not None and str(default).strip():
                return f"`{default}` (GROMACS default)"
            return f"*not set by {preset}*"
        return show(param["default"], param)

    def changed(self, node_id: str) -> list:
        """The settings of a block that differ from a fresh one, in the order
        the block shows them, each with where to find it on the block."""
        node = self.nodes[node_id]
        params = node.get("params") or {}
        out = []
        for param in self.spec(node_id)["params"]:
            name = param["name"]
            if name not in params or params[name] == param["default"]:
                continue
            # Where the box is on the block, as graph.js decides it
            # (_placement): on the face, or in the drawer called "advanced",
            # under a heading of its own when it has one. In "raw" mode the
            # run-parameters block moves its value boxes into the drawer under
            # "Main settings"; the tutorials change none of those, so only
            # the boxes that are really changed are placed here.
            where = ""
            if param.get("advanced"):
                where = "in the drawer **advanced**"
                if param.get("section"):
                    where += f", under **{param['section']}**"
            out.append({"param": param, "value": params[name], "where": where})
        return out


def build_page(t: Tutorial, box: dict) -> str:
    """The blocks of one box, in the order to add them, with their settings
    and the wires that go into each."""
    lines = [
        f"<!-- Written by tools/website.py from the tutorial '{t.name}'. "
        "Do not edit: run the script again instead. -->",
        "",
    ]
    for position, node_id in enumerate(box["blocks"], start=1):
        spec = t.spec(node_id)
        lines.append(f"### {number(position)} {spec['title']}")
        lines.append("")
        lines.append(f"In the list on the left, under **{spec['category']}**. "
                     f"Click it, or drag it onto the canvas.")
        lines.append("")
        settings = t.changed(node_id)
        if not settings:
            lines.append("Leave its settings as they are.")
            lines.append("")
        if t.mdp_edited(node_id):
            # What the block does by itself when a preset's value is typed
            # over (PARAM_FOLLOWS in graph.js), said before the table that
            # would otherwise look like it asks for things done in a row.
            lines.append("Pick the **Preset** first. The moment you type into one of "
                         "its boxes, **Settings come from** turns to `manual` by itself, "
                         "every box fills in with the preset's value, and **File name** "
                         "becomes the preset's name with `_edited` added. Then change "
                         "these:")
            lines.append("")
        long_ones = []
        short_ones = []
        for item in settings:
            text = str(item["value"])
            if "\n" in text.strip() or len(text) > SHORT:
                long_ones.append(item)
            else:
                short_ones.append(item)
        if short_ones:
            lines.append("| setting | set it to | a fresh block has |")
            lines.append("| --- | --- | --- |")
            for item in short_ones:
                param = item["param"]
                where = f" ({item['where']})" if item["where"] else ""
                lines.append(f"| **{param['label']}**{where} | {show(item['value'], param)} "
                             f"| {t.fresh(node_id, param)} |")
            lines.append("")
        for item in long_ones:
            param = item["param"]
            where = f", {item['where']}" if item["where"] else ""
            lines.append(f"Into **{param['label']}**{where}, copy this "
                         "(the button at its top right copies it):")
            lines.append("")
            lines.append("```text")
            lines.append(str(item["value"]).rstrip("\n"))
            lines.append("```")
            lines.append("")
        wires = [link for link in t.graph.get("links", []) if link["to_node"] == node_id]
        if wires:
            lines.append("Wires into it, each from a dot on the right of one block "
                         "to the dot of the same colour on the left of this one:")
            lines.append("")
            lines.append("| from | its dot | into this block's dot |")
            lines.append("| --- | --- | --- |")
            for link in wires:
                source = link["from_node"]
                out_port = t.port(source, link["from_port"], "outputs")
                in_port = t.port(node_id, link["to_port"], "inputs")
                where = t.label(source)
                source_box = t.box_of.get(source)
                if source_box and source_box != box["n"]:
                    where += f" in box *{t.boxes[source_box - 1]['title']}*"
                lines.append(f"| {where} | {dot(out_port['type'])} {out_port['label']} "
                             f"| {dot(in_port['type'])} {in_port['label']} |")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def exported(t: Tutorial) -> dict:
    """What every block runs, from "Export scripts": block id -> (the lines
    of its commands, the files it writes for later blocks to use). Switched-off
    blocks are switched on first, so the extra boxes have commands too."""
    graph = copy.deepcopy(t.graph)
    for node in graph["nodes"]:
        node.pop("off", None)
    found = {}
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "export"
        export_workflow(graph, Settings(), dest, copy_inputs=False)
        for folder in sorted(dest.iterdir()):
            if not folder.is_dir():
                continue
            node_id = folder.name.split("_", 1)[1]
            script = (folder / "command.sh").read_text().splitlines()
            # Everything after the line that loads env.sh, without the lines
            # that copy inputs in from the folders before it or choose a
            # program: those are how the exported folders are wired, not what
            # the block does. By hand, in one folder, nothing needs copying.
            start = next((i + 1 for i, line in enumerate(script) if line.startswith(". ../env.sh")), 0)
            body = [line.replace('"$GMX"', "gmx") for line in script[start:]
                    if not line.startswith(("cp -f ", "comfygmx_use "))
                    and not re.match(r"for f in \.\./\S+; do .*cp -f", line)
                    and line != "# inputs"]
            while body and not body[0].strip():
                body.pop(0)
            while body and not body[-1].strip():
                body.pop()
            files = {p.name: p.read_text() for p in sorted(folder.glob("*.mdp"))}
            found[node_id] = (body, files)
    return found


def preview_only(node_type: str, body: list) -> bool:
    """A preview block that only looks at a file: it draws in the page and
    runs nothing worth showing."""
    if not node_type.startswith("view."):
        return False
    commands = [line for line in body if line.strip() and not line.startswith("#")]
    return all(re.match(r"(wc|ls|head|true)\b", line) for line in commands)


# The marker the exported scripts put around answers typed in for a program.
ANSWERS = "<<'COMFYGMX_STDIN'"


def commands_page(t: Tutorial, box: dict, runs: dict) -> str:
    """What each block of one box runs."""
    lines = [
        f"<!-- Written by tools/website.py from the tutorial '{t.name}'. "
        "Do not edit: run the script again instead. -->",
        "",
    ]
    if any(ANSWERS in line for node_id in box["blocks"] for line in runs.get(node_id, ([], {}))[0]):
        lines.append("Some programs stop and ask a question, such as which group of atoms "
                     "to use. The lines between `<<'COMFYGMX_STDIN'` and `COMFYGMX_STDIN` "
                     "are the answers, given in advance. Typing a command by hand, you can "
                     "leave them out and answer the questions yourself.")
        lines.append("")
    for position, node_id in enumerate(box["blocks"], start=1):
        spec = t.spec(node_id)
        body, files = runs.get(node_id, ([], {}))
        # A bold line rather than a heading: the build list above already
        # gives each block a heading, and the page's contents need it once.
        lines.append(f"**{number(position)} {spec['title']}**")
        lines.append("")
        if preview_only(spec["type"], body):
            lines.append("Draws its file inside the block. It runs no program.")
            lines.append("")
        elif any(line.strip() for line in body):
            lines.append("```bash")
            lines.extend(body)
            lines.append("```")
            lines.append("")
        elif not files:
            lines.append("Runs no program.")
            lines.append("")
        for name, text in files.items():
            lines.append(f"It writes the run-parameter file `{name}`, which later blocks read:")
            lines.append("")
            lines.append(f'??? abstract "{name}"')
            lines.append("")
            lines.append("    ```ini")
            lines.extend(f"    {line}" if line else "" for line in text.rstrip("\n").splitlines())
            lines.append("    ```")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def everything() -> dict:
    """Every generated file: its path under website/_generated, and its text."""
    files = {}
    for entry in TUTORIALS:
        if entry.get("status") != "packaged":
            continue
        t = Tutorial(entry)
        runs = exported(t)
        for box in t.boxes:
            files[f"{t.id}/box-{box['n']}-build.md"] = build_page(t, box)
            files[f"{t.id}/box-{box['n']}-commands.md"] = commands_page(t, box, runs)
        files[f"{t.id}/boxes.json"] = json.dumps(
            [{"n": b["n"], "title": b["title"], "blocks": b["blocks"]} for b in t.boxes],
            indent=1) + "\n"
    return files


def main(argv: list) -> int:
    check = "--check" in argv
    wanted = everything()
    stale = []
    for name, text in wanted.items():
        path = OUT / name
        if not path.exists() or path.read_text() != text:
            stale.append(name)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
    leftover = sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()
                      and str(p.relative_to(OUT)) not in wanted) if OUT.exists() else []
    if check:
        if stale or leftover:
            for name in stale:
                print(f"out of date: website/_generated/{name}")
            for name in leftover:
                print(f"no longer made by any tutorial: website/_generated/{name}")
            print("run python3 tools/website.py, and commit what it writes")
            return 1
        print(f"website: {len(wanted)} generated files match the tutorials")
        return 0
    for name in leftover:
        (OUT / name).unlink()
    print(f"website: {len(wanted)} files in website/_generated, {len(stale)} rewritten, "
          f"{len(leftover)} removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
