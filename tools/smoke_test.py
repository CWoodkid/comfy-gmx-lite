#!/usr/bin/env python3
"""Static checks that do not need GROMACS installed.

Verifies that the registry loads, that every chunk and shipped workflow refers
to real nodes/ports/parameters, and that every node can build a plan when its
required inputs are satisfied with dummy values.

    python3 tools/smoke_test.py
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from comfygmx.chunks import CHUNKS                     # noqa: E402
from comfygmx.config import Settings                   # noqa: E402
from comfygmx.executor import dry_plan                 # noqa: E402
from comfygmx.graph import Graph                       # noqa: E402
from comfygmx.nodes.io_nodes import file_guide_for    # noqa: E402
from comfygmx.nodes.base import (NodeError, PlanContext,   # noqa: E402
                                 ToolMissing)

from comfygmx.registry import REGISTRY                 # noqa: E402
from comfygmx.tutorials import TUTORIALS               # noqa: E402
from comfygmx.runner import render_manual, render_script  # noqa: E402
from comfygmx.environments import CATALOG, Settings, Toolbox   # noqa: E402

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def check_registry() -> None:
    specs = REGISTRY.specs()
    check(len(specs) > 0, "registry is empty")
    seen = set()
    for spec in specs:
        cls = REGISTRY.get(spec["type"])
        check(spec["type"] not in seen, f"duplicate type {spec['type']}")
        seen.add(spec["type"])
        check(bool(spec["title"]), f"{spec['type']} has no title")
        check(bool(spec["description"]), f"{spec['type']} has no description")
        names = [p["name"] for p in spec["params"]]
        check(len(names) == len(set(names)), f"{spec['type']} has duplicate parameters")
        # The Extra flags box exists exactly where there is a command to
        # append to. A box on a node that copies files is a box whose contents
        # go nowhere; check_plans below proves the declaration is true.
        declared = bool(cls.extra_command)
        own = "extra_flags" in {p.name for p in cls.params}
        check(("extra_flags" in names) == (declared or own),
              f"{spec['type']} declares extra_command={cls.extra_command!r} but "
              f"{'has no' if declared else 'has an'} extra-flags box")
        if declared:
            hint = spec["flag_hint"] or {}
            check(bool(hint), f"{spec['type']} has no flag hint")
            check(hint.get("command") == cls.extra_command,
                  f"{spec['type']} hint names {hint.get('command')!r}")
        for port in spec["inputs"] + spec["outputs"]:
            check(bool(port["type"]), f"{spec['type']} port {port['name']} has no type")
            # Pointing at any socket says what kind of file it carries.
            check(bool(file_guide_for(port["type"], port["name"])),
                  f"{spec['type']} port {port['name']} ({port['type']}) has no "
                  "explanation in FILE_GUIDE, comfygmx/nodes/io_nodes.py")
    print(f"registry: {len(specs)} node types, {len(REGISTRY.categories())} categories, "
          "every socket explained")


def check_flag_hints() -> None:
    """The flag reference must describe the flags the commands really have.

    Two ways it can rot without anything noticing.  A curated example names a
    flag that a later release removed -- ``gmx gyrate -p`` was real until the
    selection-based tool replaced the legacy one, and an example nobody can
    run is worse than no example.  And a command in the catalogue that no node
    runs any more is dead weight nothing will ever show.
    """
    from comfygmx import flaghints

    for command, examples in flaghints.EXAMPLES.items():
        real = flaghints.spellings(command)
        if not real:
            continue  # nothing here could ask that program; taken on trust
        for example in examples:
            head = example.split(" ", 1)[0]
            check(head in real,
                  f"flag example '{example}' names {head}, which {command} "
                  "does not accept -- rerun tools/harvest_flags.py and fix "
                  "EXAMPLES in comfygmx/flaghints.py")

    in_use = set(flaghints.commands_in_use(REGISTRY))
    stored = set((flaghints.load().get("commands") or {}))
    for command in sorted(stored - in_use):
        failures.append(f"flags.json has '{command}', which no node runs")
    missing = [c for c in sorted(in_use - stored)]
    shown = 0
    for _, cls in REGISTRY.items():
        hint = cls.flag_hint()
        if not hint:
            continue
        shown += 1
        example = hint["example"]
        if example:
            real = flaghints.spellings(hint["command"])
            check(not real or example.split(" ")[0] in real,
                  f"{cls.type}: shows the example '{example}', which "
                  f"{hint['command']} does not accept")
    print(f"flag hints: {shown} nodes, {len(stored)} commands, "
          f"{sum(len(v.get('flags') or []) for v in flaghints.load()['commands'].values())} flags"
          + (f"; not harvested here: {', '.join(missing)}" if missing else ""))


def check_graph(name: str, graph: dict) -> None:
    types = {}
    for node in graph.get("nodes", []):
        if not REGISTRY.has(node["type"]):
            failures.append(f"{name}: unknown node type {node['type']}")
            continue
        types[node["id"]] = node["type"]
        known = {p.name for p in REGISTRY.get(node["type"]).all_params()}
        for key in (node.get("params") or {}):
            check(key in known, f"{name}: {node['id']} has unknown parameter '{key}'")
    # A group either names its members -- the editor then measures them -- or
    # carries explicit bounds. Naming a node that is not there leaves a box
    # around nothing, which is silent unless it is checked here.
    seen_titles = set()
    for group in graph.get("groups") or []:
        title = group.get("title") or ""
        check(bool(title), f"{name}: a group with no title")
        check(title not in seen_titles, f"{name}: two groups both called '{title}'")
        seen_titles.add(title)
        members = group.get("nodes") or []
        check(bool(members) or bool(group.get("bounds")),
              f"{name}: group '{title}' names neither members nor bounds")
        for member in members:
            check(member in types,
                  f"{name}: group '{title}' names unknown node '{member}'")
        check(bool(group.get("color")), f"{name}: group '{title}' has no colour")
    for link in graph.get("links", []):
        if link["from_node"] not in types or link["to_node"] not in types:
            failures.append(f"{name}: link references a missing node: {link}")
            continue
        src = REGISTRY.get(types[link["from_node"]])
        dst = REGISTRY.get(types[link["to_node"]])
        check(link["from_port"] in {p.name for p in src.outputs},
              f"{name}: no output '{link['from_port']}' on {types[link['from_node']]}")
        check(link["to_port"] in {p.name for p in dst.inputs},
              f"{name}: no input '{link['to_port']}' on {types[link['to_node']]}")


def check_chunks() -> None:
    grouped = 0
    for chunk in CHUNKS:
        check_graph(f"chunk {chunk['id']}", chunk["graph"])
        if chunk["graph"].get("groups"):
            grouped += 1
    print(f"chunks: {len(CHUNKS)} checked, {grouped} carry coloured groups")


def check_workflows() -> None:
    count = 0
    for path in sorted((ROOT / "workflows").rglob("*.json")):
        graph = json.loads(path.read_text())
        check_graph(f"workflow {path.relative_to(ROOT)}", graph)
        problems = [p for p in Graph(graph).validate() if p["level"] == "error"]
        # An example workflow legitimately has unconnected inputs the user fills
        # in (a file path, a starting structure); only structural errors matter.
        for problem in problems:
            if "not connected" in problem["message"]:
                continue
            failures.append(f"workflow {path.name}: {problem['message']}")
        count += 1
    print(f"workflows: {count} checked")


def check_tutorials() -> None:
    packaged = 0
    unavailable = set()
    for tutorial in TUTORIALS:
        for key in ("id", "number", "name", "status", "source", "summary"):
            check(bool(tutorial.get(key)), f"tutorial {tutorial.get('id')} is missing {key}")
        graph = tutorial.get("graph")
        if not graph:
            check(tutorial["status"] != "packaged",
                  f"tutorial {tutorial['id']} claims to be packaged but has no graph")
            continue
        packaged += 1
        check_graph(f"tutorial {tutorial['id']}", graph)
        ids = {node["id"] for node in graph["nodes"]}
        for step in tutorial.get("steps", []):
            check(bool(step.get("summary")), f"{tutorial['id']}: a step has no summary")
            for node_id in step.get("nodes", []):
                check(node_id in ids,
                      f"{tutorial['id']}: step '{step['title']}' names unknown node "
                      f"'{node_id}'")
        # Everything reachable must plan; only user-supplied paths may be blank.
        prepared = json.loads(json.dumps(graph))
        for node in prepared["nodes"]:
            params = node.setdefault("params", {})
            if node["type"] == "gmx.forcefield" and not params.get("path"):
                params["path"] = "/tmp/example.ff"
        for node_id, entry in dry_plan(Graph(prepared), Settings()).items():
            if not entry.get("error"):
                continue
            # This suite checks the checkout, not the machine it runs on. A
            # tutorial that drives OpenMembraneBuilder cannot plan where
            # OpenMembraneBuilder was never installed, and calling that a
            # failure made the whole suite red on any machine missing an
            # optional tool -- which is most of them.
            if entry.get("missing_tool"):
                unavailable.add(tutorial["id"])
                continue
            failures.append(f"tutorial {tutorial['id']}: {node_id} "
                            f"({entry.get('type')}): {entry['error']}")
    print(f"tutorials: {len(TUTORIALS)} listed, {packaged} packaged and planned"
          + (f", {len(unavailable)} need a tool this machine has not got"
             if unavailable else ""))


#: What a file name has to end in for each kind of port.  Used to catch a
#: download wired to the wrong place.
_LOOKS_LIKE = {
    "structure": (".gro", ".pdb", ".g96", ".brk", ".ent", ".esp", ".tpr", ".cif"),
    "topology": (".top", ".itp"),
    "mdp": (".mdp",),
    "index": (".ndx",),
    "traj": (".xtc", ".trr", ".gro", ".pdb", ".tng", ".cpt"),
    "tpr": (".tpr",),
    "xvg": (".xvg", ".dat"),
    "posre": (".itp",),
}


def check_downloaded_files() -> None:
    """A download names only its first file; catch one wired somewhere wrong.

    A block that pulls several files out of an archive copies all of them into
    the next block's folder but can only NAME one -- the first in its list.
    Wire such a download straight into a port that wants a settings file, and
    the settings file it needs is sitting right there while the command is
    handed a trajectory instead.

    Nothing complains at the time.  What happens is a confusing failure much
    later: GROMACS refusing an extension, or Backward stopping several hundred
    lines in with a bare "name 'topres' is not defined".  Both were real.

    The fix in a graph is the "Take one file out" block, which says which one
    is meant.
    """
    spec = {node["type"]: node
            for category in REGISTRY.categories() for node in category["nodes"]}
    checked = 0
    for tutorial in TUTORIALS:
        graph = tutorial.get("graph")
        if not graph:
            continue
        nodes = {node["id"]: node for node in graph["nodes"]}
        for link in graph.get("links") or []:
            source = nodes.get(link["from_node"])
            if not source or source["type"] != "io.fetch_url":
                continue
            members = [line.strip() for line
                       in (source.get("params") or {}).get("member", "").splitlines()
                       if line.strip()]
            if len(members) < 2:
                continue
            first = members[0].rstrip("/").split("/")[-1]
            ending = "." + first.rsplit(".", 1)[-1].lower() if "." in first else ""
            target = nodes.get(link["to_node"])
            if not target:
                continue
            ports = {port["name"]: port["type"]
                     for port in spec.get(target["type"], {}).get("inputs", [])}
            allowed = _LOOKS_LIKE.get(ports.get(link["to_port"], ""))
            checked += 1
            if allowed and ending not in allowed:
                failures.append(
                    f"{tutorial['id']}: the download '{link['from_node']}' hands on "
                    f"{first}, but {link['to_node']} wants a "
                    f"{ports.get(link['to_port'])} on its {link['to_port']} input. "
                    "Put a 'Take one file out' block in between.")
    print(f"downloads: {checked} connection(s) from multi-file downloads checked")


#: What a stub input file is called for each kind of port. A node is allowed
#: to check the ending of a file it is given, so the stub has to look like the
#: real thing.
STUB_ENDINGS = {"structure": "pdb", "traj": "xtc", "tpr": "tpr", "topology": "top",
                "index": "ndx", "ndx": "ndx", "mdp": "mdp", "csv": "csv",
                "xvg": "xvg", "posre": "itp", "image": "png", "energy": "edr",
                "text": "txt", "file": "dat", "any": "dat", "ffdir": "ff"}

#: A few nodes want one particular kind of structure and say so plainly. The
#: stub follows them rather than the general rule above.
STUB_ENDINGS_BY_NODE = {"prep.declash": {"structure": "gro"}}


def check_plans() -> None:
    """Every node must build a plan when all of its inputs are supplied.

    Optional ports are filled too: several nodes accept any one of a set of
    inputs (insert-molecules wants a box *or* an explicit size, check wants a
    trajectory *or* a tpr), and this pass is about catching plan-time crashes,
    not about exercising every combination.
    """
    settings = Settings()
    toolbox = Toolbox(settings)
    planned = 0
    absent = 0

    for spec in REGISTRY.specs():
        cls = REGISTRY.get(spec["type"])
        inputs = {}
        for port in cls.inputs:
            if port.type == "text":
                inputs[port.name] = {"kind": "text", "value": "x"}
            elif port.type == "topology":
                inputs[port.name] = {"kind": "topology", "path": "/tmp/topol.top",
                                     "name": "topol.top", "dir": "/tmp", "glob": []}
            else:
                # The port name is in the file name, so two ports of the same
                # kind get two different files. They would in a real graph --
                # they come from two different blocks -- and a node that
                # notices when two of its inputs are the same file was failing
                # here on an artefact of the stub rather than on anything it
                # would ever meet.
                # The ending matters: a node may refuse a structure that is not
                # a .pdb or .gro, and it is right to. Naming the stub after the
                # port's type gave it endings like ".structure", which no real
                # file has, so a node with a sensible check failed here on the
                # stub rather than on anything it would ever be given.
                ending = STUB_ENDINGS_BY_NODE.get(spec["type"], {}).get(
                    port.name, STUB_ENDINGS.get(port.type, port.type))
                inputs[port.name] = {
                    "kind": "file",
                    "path": f"/tmp/in_{port.name}.{ending}",
                    "name": f"in_{port.name}.{ending}"}
        params = dict(cls.defaults())
        params["extra_flags"] = EXTRA_SENTINEL
        # Nodes that cannot plan without a user-supplied value get a plausible one.
        for key, value in (("path", "/tmp/input.pdb"), ("pdb_id", "1ubq"),
                           ("destination", "/tmp/out"), ("selection", "name BB"),
                           ("script", "echo hi"), ("mutations", "A:1 THR->TPO"),
                           ("url", "https://example.org/inputs.pdb"),
                           ("group1", "a_7_43"), ("molecules", "MOL"), ("smiles", "CCO"),
                           # Blocks that work through a list of files typed one per
                           # line cannot plan from an empty box, and should not: an
                           # empty list is a question, not a default. The test gives
                           # them a plausible line so the rest of the block is still
                           # exercised.
                           ("records", "/tmp/run_rep1.npz"), ("files", "rep1,/tmp/hinge_rep1.csv"),
                           ("jobs", "/tmp/ref.fasta | /tmp/all.fasta | a protein | 4,7"),
                           ("positions", "4,7"), ("root", "/tmp/runs"),
                           ("fastas", "/tmp/ref.fasta"), ("spec_text", "[]"),
                           ("pieces", "/tmp/piece1.xtc"), ("structures", "/tmp/one.pdb"),
                           ("fits", "/tmp/rep1_prot_fit.xtc"), ("plans", "/tmp/plan_rep1.tsv"),
                           ("logs", "/tmp/md.log"), ("entries", "8WXE /tmp/8WXE.cif"),
                           ("groups", "System\n"), ("name", "em.mdp")):
            if key in params and not params[key]:
                params[key] = value
        workdir = Path("/tmp/comfygmx-smoke")
        ctx = PlanContext(
            node_id="smoke", node_type=spec["type"], params=params, inputs=inputs,
            workdir=workdir, stage=lambda value: (value or {}).get("name") or "in.dat",
            settings=settings, dry=True,
        )
        try:
            plan = cls().plan(ctx)
        except ToolMissing:
            # Not a fault in the node: the program it drives is not on this
            # machine. Counted, so the summary line stays honest about how
            # much of the catalogue was actually exercised.
            absent += 1
            continue
        except NodeError as exc:
            failures.append(f"{spec['type']}: could not plan with defaults: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{spec['type']}: {type(exc).__name__}: {exc}")
            continue
        try:
            render_script(plan.steps, workdir, toolbox.resolve)
            render_manual(plan.steps, workdir, toolbox.resolve)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{spec['type']}: rendering failed: {exc}")
        _check_steps(spec["type"], plan)
        _check_extra_command(spec["type"], cls, plan, toolbox)
        planned += 1
    print(f"plans: {planned} nodes planned and rendered"
          + (f", {absent} skipped -- their tool is not installed here"
             if absent else ""))


#: Put in the Extra flags box of every node, to find out where it comes out.
EXTRA_SENTINEL = "--zz-smoke-sentinel"


def _check_extra_command(node_type: str, cls, plan, toolbox) -> None:
    """``extra_command`` must name the command the box really feeds.

    It is a claim made in a class attribute and consumed by the browser --
    which builds the box's wording, its example and its flag list out of it --
    so nothing in the running program would notice it going stale. Planning
    the node with a sentinel in the box says where the text actually lands.
    """
    if "extra_flags" in {p.name for p in cls.params}:
        return  # the node worded its own box and means something else by it
    landed = [step for step in plan.steps if EXTRA_SENTINEL in step.render()]
    landed += [name for name, body in plan.files.items()
               if EXTRA_SENTINEL in str(body)]
    if not cls.extra_command:
        check(not landed,
              f"{node_type}: extra flags are passed to something, but the node "
              "declares no extra_command, so the box is not offered at all")
        return
    if not landed:
        failures.append(
            f"{node_type}: declares extra_command={cls.extra_command!r} but the "
            "box's text reaches no command -- typing in it would do nothing")
        return
    # The last word identifies it: argv[0] is '{cmd}' or 'gmx' by the time the
    # toolbox is done with it, and what says which command ran is 'grompp'.
    token = cls.extra_command.split()[-1]
    step = landed[0]
    where = step.render() if hasattr(step, "render") else str(step)
    if hasattr(step, "tool") and "{cmd}" in where:
        # A step that says {cmd} has the binary put in by the toolbox, so the
        # name to look for is only there after the same substitution.
        where = where.replace("{cmd}", toolbox.resolve(step.tool).command)
    check(re.search(rf"(?:^|[\s/'\"]){re.escape(token)}(?:$|[\s'\"])", where) is not None,
          f"{node_type}: declares extra_command={cls.extra_command!r} but its "
          f"flags land on: {where.strip()[:90]}")


#: Binaries that only exist inside an environment the toolbox sets up.
MANAGED_BINARIES = ("gmx", "gmx_mpi", "gmx_mpi_d", "martinize2", "insane",
                    "COBY", "TS2CG", "obabel", "mkdssp")
#: A binary at the start of a command: beginning of the script, or after a
#: pipe, a semicolon, &&, or an opening $( -- but not inside a quoted message.
_INVOCATION = re.compile(
    r"(?:^|[|;&]\s*|\$\(\s*)(" + "|".join(MANAGED_BINARIES) + r")\s", re.M)


def _check_steps(node_type: str, plan) -> None:
    """A shell step that spells a managed binary out runs the wrong one.

    ``plan.step`` substitutes the tool the toolbox resolved; ``plan.sh`` only
    does it where the script says ``{cmd}``, and a step declared ``tool="shell"``
    never gets the environment sourced at all.  Write ``gmx`` into a shell step
    and it runs whatever is on PATH -- which on this machine is Ubuntu's
    /usr/bin/gmx 2021.4, reading a tpr written by 2025.4, failing with
    "listRanges does not have a first element with value 0".  Nothing in that
    message mentions a version, and the node looked broken for a day.
    """
    for step in plan.steps:
        if not step.shell:
            continue
        script = step.argv[0] if step.argv else ""
        found = _INVOCATION.search(script)
        if found:
            failures.append(
                f"{node_type}: a shell step runs '{found.group(1)}' by name. Use "
                "'{cmd}' so the toolbox substitutes the right binary, and pass "
                f"tool=\"...\" so its environment is sourced first")
        if "{cmd}" in script and step.tool == "shell":
            failures.append(
                f"{node_type}: a shell step uses {{cmd}} but is declared "
                "tool=\"shell\", so nothing is substituted into it")


def check_dry_run() -> None:
    """A whole example workflow must plan end to end."""
    path = ROOT / "workflows" / "atomistic-protein-in-water.json"
    if not path.exists():
        return
    graph = json.loads(path.read_text())
    for node in graph["nodes"]:
        if node["type"] == "io.structure":
            node.setdefault("params", {})["path"] = "/tmp/input.pdb"
    plans = dry_plan(Graph(graph), Settings())
    for node_id, entry in plans.items():
        if entry.get("error"):
            failures.append(f"dry run: {node_id} ({entry.get('type')}): {entry['error']}")
    print(f"dry run: {len(plans)} nodes planned")


def check_export() -> None:
    """A workflow exports to scripts that name no path from this machine.

    The point of an export is that it runs somewhere else, so the test is not
    "did it write files" but "is there anything in them that only exists
    here". A home directory or a run directory in a command is the whole
    failure, and it is silent until somebody unpacks the folder on a cluster.
    """
    from comfygmx.export import export_workflow, ExportError

    path = ROOT / "workflows" / "atomistic-protein-in-water.json"
    if not path.exists():
        return
    graph = json.loads(path.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        stand_in = Path(tmp) / "input.pdb"
        stand_in.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000\n")
        for node in graph["nodes"]:
            if node["type"] in ("io.structure", "io.file"):
                node.setdefault("params", {})["path"] = str(stand_in)
        dest = Path(tmp) / "bundle"
        try:
            result = export_workflow(graph, Settings(), dest,
                                     label="smoke", slurm={"partition": "x"})
        except ExportError as exc:
            failures.append(f"export: {exc}")
            return

        for name in ("run_all.sh", "env.sh", "METHODS.md", "workflow.json",
                     "submit.sbatch"):
            if not (dest / name).exists():
                failures.append(f"export: no {name} in the bundle")
        for step in result["steps"]:
            script = dest / step["dir"] / "command.sh"
            if not script.exists():
                failures.append(f"export: no command.sh for {step['dir']}")

        # env.sh is the one file allowed to name this machine.
        here = [str(Path.home()), str(Settings().data_dir)]
        for script in sorted(dest.rglob("command.sh")):
            text = script.read_text()
            for absolute in here:
                if absolute in text:
                    failures.append(
                        f"export: {script.relative_to(dest)} names {absolute}, "
                        f"which does not exist on another machine")
        steps = (dest / "run_all.sh").read_text()
        for step in result["steps"]:
            if step["dir"] not in steps:
                failures.append(f"export: run_all.sh does not run {step['dir']}")

        # "$GMX" has to survive rendering. Every token goes through
        # shlex.quote, which turns it into '"$GMX"' -- a six-character program
        # name no shell expands, and a bundle that fails on the first command.
        for script in sorted(dest.rglob("command.sh")):
            text = script.read_text()
            if "'\"$GMX\"'" in text or "'$GMX'" in text:
                failures.append(f"export: {script.relative_to(dest)} quotes "
                                f"$GMX so it cannot expand")

        # A chain around the last mdrun, resuming only when there is something
        # to resume from.
        chained = Path(tmp) / "chained"
        try:
            result = export_workflow(graph, Settings(), chained, label="smoke",
                                     slurm={"partition": "x", "time": "02:00:00",
                                            "mode": "chain"})
        except ExportError as exc:
            failures.append(f"export: chain refused -- {exc}")
            return
        chain = result.get("chain") or {}
        if not chain:
            failures.append("export: chain mode reported no chain step")
        elif abs(chain["maxh"] - 1.95) > 0.001:
            failures.append(f"export: -maxh {chain['maxh']} is not just under "
                            f"a 2 h slot")
        else:
            step = (chained / chain["step"] / "command.sh").read_text()
            for wanted in (f"if [ -f {chain['prefix']}.cpt ]", "-cpi", "-maxh 1.95"):
                if wanted not in step:
                    failures.append(f"export: chained step has no {wanted!r}")
            submit = (chained / "submit.sbatch").read_text()
            # The behaviour, not the wording: a crash and a bad log both have
            # to stop the chain, the job name has to be carried over, and the
            # preparation has to run only up to the long step.
            for wanted in ("Not asking for another", "LINCS WARNING",
                           "sbatch -J", "--until"):
                if wanted not in submit:
                    failures.append(f"export: submit.sbatch has no {wanted!r}")
    print(f"export: {len(result['steps'])} steps written, no local paths in "
          f"them, chain resumes {chain.get('step', '?')} at "
          f"-maxh {chain.get('maxh', 0):g}")


def check_forms() -> None:
    """Every box that names a fill-in-the-blanks form has one.

    The name is written in Python and the form is written in JavaScript, so
    nothing but a check like this connects the two: a box naming a form that
    does not exist would show a button that says "no form for coby.membrane"
    and nothing else, and only when somebody pressed it.

    Also runs the round-trip test if node is installed -- it proves a form
    reads back what it writes, which is what stops one quietly dropping a
    setting it was not asked about.
    """
    forms = Path(ROOT / "comfygmx" / "web" / "js" / "forms.js").read_text()
    registered = set(re.findall(r"registerField\('([^']+)'", forms))
    check(bool(registered), "forms.js registers no forms at all")

    used = {}
    for node_type, cls in sorted(REGISTRY.items()):
        for param in cls.params:
            name = getattr(param, "form", "")
            if name:
                used.setdefault(name, []).append(f"{node_type}.{param.name}")
    for name, where in sorted(used.items()):
        check(name in registered,
              f"{where[0]} asks for the form '{name}', which forms.js does not have")

    # The button is drawn by the editor; a box whose type has no widget would
    # get one that opens a form and then writes into nothing.
    for node_type, cls in sorted(REGISTRY.items()):
        for param in cls.params:
            if getattr(param, "form", ""):
                check(param.type in ("text", "str"),
                      f"{node_type}.{param.name} has a form but is a {param.type} box")

    node = shutil.which("node")
    if not node:
        print(f"forms: {sum(len(v) for v in used.values())} boxes over "
              f"{len(used)} forms, {len(registered)} registered "
              "(round-trip test skipped -- node is not installed)")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "forms_roundtrip.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the form round-trip test failed:\n" + (proc.stdout or proc.stderr))
    print(f"forms: {sum(len(v) for v in used.values())} boxes over "
          f"{len(used)} of {len(registered)} forms, reading back what they write")


def check_dialogs() -> None:
    """A dialog opened from inside a dialog leaves the first one alone.

    There is one dialog in the page and a second layer above it for the file
    browser, because a form that is half filled in cannot be re-drawn from
    anything -- nothing in it has been saved yet. `tools/dialog_layers.js`
    loads the browser file with a stand-in for the page and checks the rules;
    it needs node, and says so rather than passing quietly when node is not
    there.
    """
    markup = (ROOT / "comfygmx" / "web" / "index.html").read_text()
    for element in ("submodal-backdrop", "submodal-body", "submodal-footer",
                    "submodal-title", "submodal-close"):
        check(element in markup, f"the second dialog layer has no {element}")

    api = (ROOT / "comfygmx" / "web" / "js" / "api.js").read_text()
    check("subModal(" in api and "closeSubModal(" in api,
          "api.js has no second dialog layer")
    panels = (ROOT / "comfygmx" / "web" / "js" / "panels.js").read_text()
    check("UI.modalOpen()" in panels,
          "the file browser no longer asks whether a dialog is already open, so "
          "it will replace one instead of stacking on it")

    node = shutil.which("node")
    if not node:
        print("dialogs: two layers present (behaviour test skipped -- node is "
              "not installed)")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "dialog_layers.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the dialog layering test failed:\n" + (proc.stdout or proc.stderr))
    print("dialogs: a second dialog leaves the first one's contents alone")


def check_file_picker() -> None:
    """Getting back out of a folder, and finding a file in one.

    The picker had a small "↑ .." row and nothing else: no Up, no Back, and no
    way to look for a name. Run in node with a stand-in for the page, so it
    needs neither a browser nor a server.
    """
    node = shutil.which("node")
    if not node:
        print("file picker: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "file_picker.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the file picker test failed:\n" + (proc.stdout or proc.stderr))
    print("file picker: Up, Back, and a search that looks underneath")


def check_viewer_turn() -> None:
    """Dragging sideways spins the structure, rather than rolling it.

    The view was turned by two angles, which can only ever describe a
    turntable -- and a turntable has one axis it cannot get away from. On a
    membrane box, tilted right over to be seen upright, that axis ends up
    pointing at the camera and dragging sideways spun the picture in the plane
    of the screen. Run in node with a stand-in for the page.
    """
    node = shutil.which("node")
    if node:
        proc = subprocess.run([node, str(ROOT / "tools" / "viewer_turn.js")],
                              capture_output=True, text=True)
        check(proc.returncode == 0,
              "the viewer turning test failed:\n" + (proc.stdout or proc.stderr))
    else:
        print("viewer turning: the arithmetic is skipped -- node is not installed")

    # And every picture you can turn is the same renderer, so the fix reaches
    # all of them rather than the one it was reported on. Worth pinning: the
    # obvious way to add a second kind of preview is to copy the first, and a
    # copied renderer is a second idea of which way is up.
    web = ROOT / "comfygmx" / "web" / "js"
    viewer = (web / "viewer.js").read_text()
    check(viewer.count("function createStructureView") == 1,
          "there is more than one renderer in viewer.js")
    users = [line.strip() for line in viewer.splitlines()
             if "createStructureView(" in line and "function" not in line]
    check(len(users) == 2,
          "the renderer is built in %d places, expected 2 -- the Viewer tab and "
          "the previews inside nodes:\n  %s" % (len(users), "\n  ".join(users)))
    check("if (kind === 'plot' || kind === 'dssp') return this.buildFlat" in viewer,
          "which previews are flat and which can be turned is decided somewhere "
          "else now -- check every turnable kind still goes through buildSpatial")
    for other in sorted(web.glob("*.js")):
        if other.name == "viewer.js":
            continue
        text = other.read_text()
        # A kept orientation, not the canvas's own ctx.rotate() for sideways
        # axis labels -- that is drawing, not a view anybody turns.
        held = re.findall(r"\brot\s*[:=.]|\.rot\b", text)
        check(not held,
              "%s keeps a rotation of its own (%s); there should be one, in "
              "viewer.js" % (other.name, ", ".join(sorted(set(held)))))

    # Every node that draws something you can turn, so a new one is noticed.
    spatial = sorted(spec["type"] for spec in REGISTRY.specs()
                     if (spec.get("preview") or {}).get("kind")
                     not in (None, "plot", "dssp"))
    # Only the ones registered here: the lite version keeps two of them.
    expected = [name for name in (
        "analysis.conservation", "io.save_structure", "ligand.build", "ligand.martini3",
        "ligand.place_by_overlay", "omb.build", "phos.beads", "view.structure",
        "view.trajectory") if REGISTRY.has(name)]
    check(spatial == expected,
          "the nodes drawing a turnable picture are now %s -- if that is a new "
          "one, check it goes through the same renderer" % spatial)
    print("viewer turning: sideways spins it about the middle of the screen at "
          "any tilt, in all %d previews and the Viewer tab" % len(spatial))


def check_param_boxes() -> None:
    """A node's boxes appear and disappear with the one that controls them.

    "Load structure" takes a file or a code from the Protein Data Bank, and one
    box that quietly accepted either was not something anybody could see. Run
    in node with a stand-in for the page.
    """
    node = shutil.which("node")
    if not node:
        print("parameter boxes: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "param_when.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the parameter box test failed:\n" + (proc.stdout or proc.stderr))
    print("parameter boxes: they appear and disappear with the box that controls them")


def check_mdp_boxes() -> None:
    """The run-parameters boxes show the value the run will use.

    Left empty, a box on "Run parameters (.mdp)" means "whatever the preset
    says", and used to say only "preset default" wherever the preset was
    silent -- and, in raw mode, everywhere, while quietly ignoring anything
    typed there. tools/mdp_boxes.js checks the editor's side. Here: every
    GROMACS default the server sends belongs to a box, so none is sent for
    nothing.
    """
    from comfygmx.nodes.util_nodes import MdpNode
    stray = sorted(set(MdpNode._GROMACS_DEFAULTS) - set(MdpNode._WIDGET_MAP.values()))
    check(not stray, f"GROMACS defaults for options no box shows: {stray}")
    node = shutil.which("node")
    if not node:
        print("run-parameter boxes: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "mdp_boxes.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the run-parameter box test failed:\n" + (proc.stdout or proc.stderr))
    print("run-parameter boxes: every value on show from the start, and raw mode "
          "edits the text")


def check_trajectory_groups() -> None:
    """Preview trajectory shows one group or several, from any list it offers.

    trjconv writes one group, and with an index file it knows only that file's
    groups. So several groups are joined by gmx select first, and an index file
    is merged with the system's own groups -- the same list the block's form
    offers, read by comfygmx.groups. One group and no index file must stay
    exactly the command it always was, so no saved result goes stale.
    """
    import tempfile
    from comfygmx import groups
    from comfygmx.graph import Graph
    from comfygmx.executor import dry_plan

    def steps(sel, index=False):
        nodes = [{"id": "f", "type": "io.file", "params": {"path": "/tmp/md.xtc"}},
                 {"id": "t", "type": "io.file", "params": {"path": "/tmp/md.tpr"}},
                 {"id": "v", "type": "view.trajectory", "params": {"sel": sel}}]
        links = [{"from_node": "f", "from_port": "file", "to_node": "v", "to_port": "traj"},
                 {"from_node": "t", "from_port": "file", "to_node": "v", "to_port": "tpr"}]
        if index:
            nodes.append({"id": "n", "type": "io.file", "params": {"path": "/tmp/ice.ndx"}})
            links.append({"from_node": "n", "from_port": "file", "to_node": "v",
                          "to_port": "index"})
        entry = dry_plan(Graph({"nodes": nodes, "links": links}), Settings())["v"]
        if entry.get("error"):
            return ["error: " + entry["error"]]
        return [step.argv[0] for step in entry["_plan"].steps]

    one = steps("Protein")
    check(one == ["printf '%b' 'Protein\\nProtein\\n' | {cmd} trjconv -s md.tpr -f md.xtc "
                  "-o frames.pdb -pbc mol -center -skip 25"],
          f"groups: one group and no index file is no longer the old command: {one}")
    two = steps("Protein, Ion")
    check(len(two) == 2 and two[0].startswith("{cmd} select ")
          and '\'"Protein_Ion" group "Protein" or group "Ion"\'' in two[0]
          and "-n shown.ndx" in two[1] and "Protein_Ion\\nProtein_Ion" in two[1],
          f"groups: two groups are not joined into one before trjconv: {two}")
    merged = steps("Oxygens, System", index=True)
    check(len(merged) == 4 and "make_ndx" in merged[0] and "ice.ndx standard.ndx" in merged[1]
          and "-n groups.ndx" in merged[2] and "-n shown.ndx" in merged[3],
          f"groups: an index file is not merged with the system's own groups: {merged}")
    quoted = steps('Pro"tein')
    check(quoted[0].startswith("error:"), "groups: a name with a quote in it was let through")

    with tempfile.TemporaryDirectory() as work:
        ndx = Path(work) / "two.ndx"
        ndx.write_text("[ Oxygens ]\n1 5 9\n13\n[ Water ]\n1 2 3 4\n")
        read = groups.read_ndx(str(ndx))
    check(read == [{"name": "Oxygens", "atoms": 4}, {"name": "Water", "atoms": 4}],
          f"groups: an index file was read wrongly: {read}")
    print("trajectory groups: one group as before, several joined, and an index "
          "file merged with the system's own groups")


def check_canvas_panning() -> None:
    """Can you move the canvas about on a laptop trackpad?

    It could be dragged with the middle mouse button, and with Alt and the
    left button. Neither reaches a laptop: a trackpad has no middle button to
    press, and on Linux the desktop usually takes Alt-drag to move the window.
    Two fingers sliding, which is how you move around everywhere else on a
    laptop, arrived as the wheel turning and zoomed. `tools/canvas_pan.js`
    loads the editor with a stand-in for the page and checks the rule.
    """
    node = shutil.which("node")
    if not node:
        print("canvas panning: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "canvas_pan.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the canvas panning test failed:\n" + (proc.stdout or proc.stderr))
    print("canvas panning: the wheel still zooms on a mouse, two fingers slide "
          "on a trackpad, and a pinch zooms either way")


def check_wire_cutting() -> None:
    """Can you hit a wire, and can you cut one in a single gesture?

    A wire is drawn two pixels wide, so right-clicking one took several tries,
    and worse on a trackpad or with the canvas zoomed out. Every wire is now
    drawn twice: once visibly, and once in a wide invisible stroke that catches
    the pointer. Holding Ctrl while right-clicking cuts it outright instead of
    offering a one-item menu. `tools/wire_cutting.js` loads the editor with a
    stand-in for the page and checks both.
    """
    node = shutil.which("node")
    if not node:
        print("wire cutting: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "wire_cutting.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the wire cutting test failed:\n" + (proc.stdout or proc.stderr))
    print("wire cutting: a wire is a 14 px target at every zoom, a plain "
          "right-click still offers the menu, and Ctrl and right-click cuts it "
          "outright -- Cmd on a Mac")


def check_chunk_inputs() -> None:
    """What does a chunk take in, and can it be pointed somewhere else at once?

    A chunk is eight or nineteen blocks in a coloured box. Pointing one at a
    different structure meant opening the blocks and finding the two or three
    that mention a file. The box now has sockets on its title bar, and an
    Inputs window listing the same things in words. `tools/chunk_inputs.js`
    checks what that list holds and, just as important, what it leaves out.
    """
    node = shutil.which("node")
    if not node:
        print("chunk inputs: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "chunk_inputs.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the chunk inputs test failed:\n" + (proc.stdout or proc.stderr))
    print("chunk inputs: a chunk says what it takes in and what it hands out, "
          "tells its needed ones from its optional ones, numbers repeated "
          "blocks, and keeps its title bar through a rename")


def check_switch_off_editor() -> None:
    """The editor's half of switching blocks off: the switch, what it saves,
    Ctrl + Alt + click and Ctrl+M, and how a block that will not run is shown.
    The run's half is check_switched_off. `tools/switch_off.js` loads the
    editor with a stand-in for the page."""
    node = shutil.which("node")
    if not node:
        print("switch off (editor): skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "switch_off.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the switch-off editor test failed:\n" + (proc.stdout or proc.stderr))
    print("switch off (editor): one switch both ways, saved only when set, whole "
          "chunks, both shortcuts, and the reason shown on blocks left out")


def check_cached_tags() -> None:
    """The dashed "cached" tag on the blocks the next Run would reuse comes
    back by itself when a run ends. It used to wait for the next edit, such
    as dragging a box. `tools/cached_tags.js` loads the editor and the page
    with a stand-in for the page and for the server."""
    node = shutil.which("node")
    if not node:
        print("cached tags: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "cached_tags.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the cached-tag test failed:\n" + (proc.stdout or proc.stderr))
    print("cached tags: back by themselves when a run ends, and the line beside "
          "Run with them")


def check_workflow_tools() -> None:
    """A workflow says which programs it needs, and which versions it used.

    Somebody handed a workflow built on another machine has no way of seeing
    what it will want: every node drives some program, and the first sign that
    one is missing used to be the run stopping on the fourth node an hour in.

    The version matters as much as the program. Two versions of GROMACS do not
    always give the same numbers, so a workflow saved here writes down what it
    was built against, and the machine that opens it can offer that version as
    well as the newest.

    Presence is faked here, because the answer must not depend on what happens
    to be installed on the machine running the tests.
    """
    from comfygmx import bootstrap as boot
    from comfygmx.server import workflow_tools

    graph = Graph({
        "nodes": [
            {"id": "load", "type": "io.structure", "params": {}},
            {"id": "ice", "type": "build.ice", "params": {}},
            {"id": "grompp", "type": "gmx.grompp", "params": {}},
            {"id": "grompp2", "type": "gmx.grompp", "params": {}},
            {"id": "note", "type": "util.note", "params": {}},
        ],
        "links": [],
    })

    def report(present: bool, recorded: dict, probe: bool = False) -> dict:
        """What the server says about this graph on a machine that has
        GROMACS 2026.3, or has no GROMACS at all."""
        found = [{"path": "/opt/gromacs/bin/GMXRC", "version": "2026.3"}] if present else []

        class FakeBox:
            settings = Settings()

            def installs_of(self, tool_id):
                return []

            def gmxrc_candidates(self):
                return found

            def probe(self, tool_id, timeout=8.0):
                return ({"found": True, "version": "GROMACS version 2026.3"}
                        if present else {"found": False})

        class FakeApp:
            toolbox = FakeBox()

        was = boot._tool_status
        boot._tool_status = lambda box, tool_id: (
            {"present": True, "where": "/opt/gromacs/bin/GMXRC"}
            if present and tool_id == "gmx" else {"present": False, "where": ""})
        try:
            return workflow_tools(FakeApp(), graph, recorded, probe=probe)
        finally:
            boot._tool_status = was

    # A workflow built with 2025.4, opened on a machine with no GROMACS.
    away = report(False, {"gmx": {"version": "2025.4"}})
    named = {tool["id"]: tool for tool in away["tools"]}
    check(set(named) == {"gmx"},
          "the programs a workflow needs came out as %s -- 'Load structure', the "
          "ice builder (plain Python) and a note need nothing installed"
          % sorted(named))
    check(away["missing"] == ["gmx"], "the missing list is %s" % away["missing"])
    wanted = named.get("gmx", {})
    check(wanted.get("wanted") == "2025.4",
          "THE BUG: the version the workflow was built with was not carried "
          "through, so only 'the newest' could be offered: %r" % wanted.get("wanted"))
    check(wanted.get("nodes") == ["grompp", "grompp2"],
          "a tool does not say which nodes need it: %s" % wanted.get("nodes"))
    check(len(wanted.get("titles") or []) == 1,
          "two nodes of the same kind were listed twice: %s" % wanted.get("titles"))
    check("gmx" not in away["stamp"],
          "a program that is not here was recorded as if it were: %s" % away["stamp"])
    probed = report(False, {}, probe=True)
    check(probed["stamp"].get("gmx", {}).get("version", "") == "",
          "a missing program must not be probed for a version")

    # The same workflow on a machine that has GROMACS 2026.3.
    home = report(True, {})
    here = {tool["id"]: tool for tool in home["tools"]}
    check(home["missing"] == [], "nothing should be missing here: %s" % home["missing"])
    check(here.get("gmx", {}).get("version") == "2026.3",
          "the version in use here is %r" % here.get("gmx", {}).get("version"))
    check(home["stamp"].get("gmx", {}).get("version") == "2026.3",
          "a workflow saved here would not record which GROMACS built it: %s"
          % home["stamp"])

    # The dialog itself, in node with a stand-in for the page.
    node = shutil.which("node")
    if not node:
        print("workflow tools: dialog skipped -- node is not installed")
    else:
        proc = subprocess.run([node, str(ROOT / "tools" / "workflow_tools.js")],
                              capture_output=True, text=True)
        check(proc.returncode == 0,
              "the workflow tools dialog test failed:\n" + (proc.stdout or proc.stderr))
    print("workflow tools: GROMACS is the one program needed, it is reported "
          "missing where it is missing, and the version it was built with is "
          "offered alongside the newest")


def check_node_stacking() -> None:
    """Clicking a node brings it in front of the ones drawn over it.

    Nodes were drawn in the order they were added, and clicking one did not
    change that, so a node covered by a later one was unreachable -- you could
    see a corner of it and not get at its boxes. On a graph loaded from a file
    the order is whatever the file held, so which node was buried was not even
    predictable. `tools/node_stacking.js` loads the editor with a stand-in for
    the page and checks the order follows the clicks.
    """
    node = shutil.which("node")
    if not node:
        print("node stacking: skipped -- node is not installed")
        return
    proc = subprocess.run([node, str(ROOT / "tools" / "node_stacking.js")],
                          capture_output=True, text=True)
    check(proc.returncode == 0,
          "the node stacking test failed:\n" + (proc.stdout or proc.stderr))
    print("node stacking: the node you touched last is the one in front")


def check_port_in_use() -> None:
    """Starting a second server on a busy port explains itself.

    "Address already in use" arrived as a twenty-line Python traceback ending
    in OSError, which reads like a crash and says nothing about what to do.
    It is the most ordinary thing that can happen when starting this: the
    server from last time is still running. Worse, it is exactly what somebody
    gets when they follow a "restart it" instruction that only says how to
    start one.
    """
    import socket
    from comfygmx.server import PortInUse, build_server

    held = socket.socket()
    held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    said = None
    try:
        build_server("127.0.0.1", port, Settings())
    except PortInUse as err:
        said = str(err)
    except OSError as err:
        failures.append("THE BUG: a busy port still comes out as a raw OSError "
                        f"instead of an explanation: {err}")
    else:
        failures.append("a busy port did not stop the server from starting")
    finally:
        held.close()
    if said is None:
        return

    check("already taken" in said, "the message does not say the port is taken")
    check("--port" in said, "the message does not offer another port")
    check("Traceback" not in said, "the message is a traceback")
    check(str(port) in said, "the message does not say which port")
    print("busy port: explained rather than thrown")


def check_transcript_calls() -> None:
    """Nothing writes to the transcript with the wrong number of arguments.

    `Terminal.push(session, entry)` and `Terminal.note(session, event, title)`
    both want the session first. Three places in the install dialogs passed a
    bare string instead, which throws on the spot -- and because the throw
    happened inside the promise that had just started the install, the server
    went ahead while the browser showed nothing at all. `Terminal.say(text)`
    exists for those callers now; this makes sure nobody drifts back.
    """
    def top_level_commas(text: str) -> int:
        depth = commas = 0
        quote = ""
        for ch in text:
            if quote:
                if ch == quote:
                    quote = ""
                continue
            if ch in "\"'`":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                commas += 1
        return commas

    web = ROOT / "comfygmx" / "web" / "js"
    wants_session = {"push": 2, "note": 3}
    for path in sorted(web.glob("*.js")):
        text = path.read_text()
        for name, least in wants_session.items():
            for match in re.finditer(rf"Terminal\.{name}\(", text):
                start = match.end()
                depth, end = 1, start
                while end < len(text) and depth:
                    if text[end] == "(":
                        depth += 1
                    elif text[end] == ")":
                        depth -= 1
                    end += 1
                args = text[start:end - 1]
                line = text[:start].count("\n") + 1
                check(top_level_commas(args) + 1 >= least,
                      f"{path.name}:{line} calls Terminal.{name} with one "
                      f"argument; it wants the session first. Use "
                      f"Terminal.say(text, who) from a dialog.")

    # And the dialogs that can be opened from inside another one all ask first.
    panels = (web / "panels.js").read_text() + (web / "files.js").read_text()
    check(panels.count("UI.modalOpen()") >= 4,
          "fewer dialogs than expected check whether one is already open before "
          "replacing it -- the file browser, the folder picker, the GROMACS "
          "builder and the missing-residues table should all stack")
    print("transcript: every Terminal call passes a session; "
          f"{panels.count('UI.modalOpen()')} dialogs stack rather than replace")


def check_load_structure() -> None:
    """One box takes a file or a PDB code, and tells them apart.

    "Load structure" and "Fetch from RCSB" were two nodes doing the same job:
    put a structure at the start of the workflow. They are one now, and the
    single box decides. What has to stay true:

      * a path is copied in, as it always was
      * a four-character code is downloaded instead
      * a file wins over a code that looks like it -- a file called 1aki on
        this machine is the one you can see, so it is the one meant
      * pdb:1aki insists on the download anyway
      * a name that is merely short is NOT a code: mistaking a file name for
        one would quietly fetch a stranger's protein
      * the old node still plans, so a workflow built with it keeps working,
        and it is out of the palette rather than out of the catalogue
    """
    settings = Settings()
    cls = REGISTRY.get("io.structure")

    def plan_for(path: str, folder=None, **params):
        values = dict(cls.defaults())
        values["path"] = path
        values.update(params)
        ctx = PlanContext(
            node_id="load", node_type="io.structure", params=values, inputs={},
            workdir=Path(folder or "/tmp/comfygmx-smoke"),
            stage=lambda value: (value or {}).get("name") or "in.dat",
            settings=settings, dry=False,
        )
        return cls().plan(ctx)

    def downloads(plan):
        return [" ".join(step.argv) for step in plan.steps
                if "files.rcsb.org" in " ".join(step.argv)]

    with tempfile.TemporaryDirectory() as folder:
        home = Path(folder)
        (home / "protein.pdb").write_text("ATOM\n")
        (home / "1aki").write_text("ATOM\n")            # a file with a code's name

        got = plan_for(str(home / "protein.pdb"))
        check(not downloads(got) and got.outputs.get("structure") == "protein.pdb",
              "a path was not simply copied in: %s" % got.outputs)

        got = plan_for("1aki")
        check(len(downloads(got)) == 1 and got.outputs.get("structure") == "1aki.pdb",
              "THE BUG: a PDB code was not downloaded -- steps were %s"
              % [s.argv for s in got.steps])
        check("1aki.pdb" in downloads(got)[0],
              "the download does not ask for 1aki.pdb: %s" % downloads(got)[0])

        got = plan_for("1aki", format="cif", biological_assembly="1")
        check(downloads(got) and "1aki.cif1" in downloads(got)[0],
              "the assembly and format were not passed on: %s" % downloads(got))

        # A file of that name on this machine is the one meant.
        import os
        was = os.getcwd()
        try:
            os.chdir(home)
            got = plan_for("1aki")
            check(not downloads(got),
                  "THE BUG: a file called 1aki was ignored in favour of "
                  "downloading the entry of the same name")
            got = plan_for("pdb:1aki")
            check(len(downloads(got)) == 1,
                  "pdb:1aki did not insist on the download")
        finally:
            os.chdir(was)

        # Not a code: nothing here is fetched by accident.
        for name in ("protein", "results", "min.gro", "sub/1aki"):
            try:
                got = plan_for(name)
            except NodeError:
                continue                       # no such file: the right answer
            check(not downloads(got),
                  "THE BUG: '%s' was taken for a PDB code and downloaded" % name)

    # Which of the two ways the node is being used is a box of its own now,
    # because a single box that took either was not something anybody could
    # see. The boxes below it appear and disappear with it.
    from comfygmx.nodes.io_nodes import FROM_DISK, FROM_PDB

    got = plan_for("", source=FROM_PDB, pdb_id="6vxx")
    check(len(downloads(got)) == 1 and "6vxx.pdb" in downloads(got)[0],
          "THE BUG: 'from the Protein Data Bank' with a code did not download "
          "it: %s" % [s.argv for s in got.steps])
    try:
        plan_for("", source=FROM_PDB)
        failures.append("asking for a download with no code was allowed through")
    except NodeError as exc:
        check(FROM_DISK in str(exc),
              "the complaint about an empty code box does not say how to load a "
              "file instead: %s" % exc)
    with tempfile.TemporaryDirectory() as folder:
        home = Path(folder)
        (home / "protein.pdb").write_text("ATOM\n")
        got = plan_for(str(home / "protein.pdb"), source=FROM_DISK)
        check(not downloads(got), "'a file on this machine' downloaded something")

    boxes = {p["name"]: p for p in REGISTRY.get("io.structure").spec()["params"]}
    check(boxes["source"]["choices"] == [FROM_DISK, FROM_PDB],
          "the two ways are written as %s" % boxes["source"]["choices"])
    for name, expect in (("path", FROM_DISK), ("rename", FROM_DISK),
                         ("pdb_id", FROM_PDB), ("format", FROM_PDB),
                         ("biological_assembly", FROM_PDB)):
        check(boxes[name]["when"] == f"source={expect}",
              "THE BUG: '%s' says it is shown when %r, which does not match any "
              "value the 'Where from' box can hold -- so it would never appear"
              % (name, boxes[name]["when"]))

    specs = {spec["type"]: spec for spec in REGISTRY.specs()}
    # The lite version has no old fetch node at all: nothing it ships uses one.
    if "io.fetch_pdb" in specs:
        check(specs["io.fetch_pdb"]["hidden"] is True,
              "the old fetch node is still offered in the palette")
    check(specs["io.structure"]["hidden"] is False,
          "the merged node is hidden, which leaves nothing to load a structure with")
    palette = Path("comfygmx/web/js/app.js").read_text()
    check("spec.hidden" in palette,
          "the palette does not know to skip hidden nodes")
    print("load structure: a path is copied, a code is downloaded, a file of "
          "the same name wins, and the old node still plans")


def check_clean_cif() -> None:
    """Cleaning a structure works on mmCIF as well as PDB.

    Reported after fetching an entry in cif format: the cleaning step said it
    had kept 798 atoms and written clean.pdb, and clean.pdb held mmCIF text.
    Nothing failed, which is what made it bad -- an mmCIF atom row does start
    with the word ATOM, so a reader that trusts fixed columns takes every field
    from the wrong place and carries the rows through unchanged.

    The two formats say the same things very differently: PDB is fixed columns,
    mmCIF is a table whose columns are named and may come in any order. What
    has to stay true:

      * the same entry cleaned from mmCIF and from PDB gives the same atoms
      * what comes out is PDB, whatever went in, because nothing after this
        node reads mmCIF
      * water, heteroatoms, second positions and extra models are dropped by
        what they are, not by where they happen to sit on the line
      * a chain name too long for PDB's one column is given a letter, and the
        swap is printed rather than silently applied
    """
    from comfygmx.nodes.prep_nodes import _CLEAN_SCRIPT

    # Two atoms of a residue in chain A, the same in a chain whose mmCIF name
    # is three letters, a water, a zinc, a second position for one atom, and a
    # second model. Written in a column order that is NOT the usual one, since
    # reading by name rather than by position is the whole point.
    header = (
        "data_TEST\n#\nloop_\n"
        "_atom_site.group_PDB\n_atom_site.id\n_atom_site.auth_asym_id\n"
        "_atom_site.auth_comp_id\n_atom_site.auth_seq_id\n"
        "_atom_site.label_alt_id\n_atom_site.auth_atom_id\n"
        "_atom_site.Cartn_x\n_atom_site.Cartn_y\n_atom_site.Cartn_z\n"
        "_atom_site.occupancy\n_atom_site.B_iso_or_equiv\n"
        "_atom_site.type_symbol\n_atom_site.pdbx_PDB_model_num\n")
    rows = [
        "ATOM   1  A   LYS 1 . N   1.000 2.000 3.000 1.00 10.00 N 1",
        "ATOM   2  A   LYS 1 . CA  1.500 2.500 3.500 1.00 11.00 C 1",
        "ATOM   3  A   LYS 1 B CA  9.500 9.500 9.500 0.50 11.00 C 1",
        "ATOM   4  AAA GLY 7 . N   4.000 5.000 6.000 1.00 12.00 N 1",
        "HETATM 5  A   ZN  90 . ZN  7.000 7.000 7.000 1.00 13.00 ZN 1",
        "HETATM 6  A   HOH 91 . O   8.000 8.000 8.000 1.00 14.00 O 1",
        "ATOM   7  A   LYS 1 . N   0.000 0.000 0.000 1.00 10.00 N 2",
    ]
    cif = header + "\n".join(rows) + "\n#\n"

    with tempfile.TemporaryDirectory() as folder:
        home = Path(folder)
        (home / "clean_pdb.py").write_text(_CLEAN_SCRIPT)
        (home / "in.cif").write_text(cif)

        run = subprocess.run(
            [sys.executable, "clean_pdb.py", "in.cif", "out.pdb",
             "--drop-water", "--drop-hetero", "--first-model", "--first-altloc"],
            cwd=home, capture_output=True, text=True)
        if run.returncode != 0:
            failures.append("cleaning an mmCIF failed: " + run.stdout + run.stderr)
            return
        written = (home / "out.pdb").read_text()
        atoms = [line for line in written.splitlines()
                 if line.startswith(("ATOM", "HETATM"))]

        check(all(len(line) >= 54 and line[30:38].strip() for line in atoms),
              "THE BUG: what came out is not PDB at all -- the first line is\n  "
              + (atoms[0] if atoms else "(nothing)"))
        check("_atom_site" not in written and "data_" not in written,
              "THE BUG: mmCIF text was copied straight into the .pdb")
        check(len(atoms) == 3,
              "expected 3 atoms after the filters, got %d:\n  %s"
              % (len(atoms), "\n  ".join(atoms)))
        names = [line[12:16].strip() for line in atoms]
        check(names == ["N", "CA", "N"],
              "the atoms that survived are %s -- the second position, the zinc, "
              "the water and the second model should all have gone" % names)
        residues = {line[17:20].strip() for line in atoms}
        check(residues == {"LYS", "GLY"},
              "the residue names came out as %s, so they were read from the "
              "wrong place on the line" % residues)
        check(atoms[0][21] == "A" and atoms[2][21] not in ("", " "),
              "the chain column is empty or wrong: %r" % [line[21] for line in atoms])
        check(atoms[2][21] != "A",
              "the three-letter chain was folded into chain A instead of being "
              "given a letter of its own")
        check("chain names shortened" in run.stdout,
              "a chain was renamed without saying so: %s" % run.stdout)
        check("mmCIF" in run.stdout,
              "it does not say the file was mmCIF and has been written as PDB")

        # A PDB in, a PDB out: the old path is untouched.
        (home / "in.pdb").write_text(
            "ATOM      1  N   LYS A   1       1.000   2.000   3.000  1.00 10.00"
            "           N\n"
            "HETATM    2  O   HOH A  91       8.000   8.000   8.000  1.00 14.00"
            "           O\n")
        plain = subprocess.run(
            [sys.executable, "clean_pdb.py", "in.pdb", "plain.pdb", "--drop-water"],
            cwd=home, capture_output=True, text=True)
        kept = [line for line in (home / "plain.pdb").read_text().splitlines()
                if line.startswith(("ATOM", "HETATM"))]
        check(plain.returncode == 0 and len(kept) == 1,
              "cleaning an ordinary PDB changed: %s%s" % (plain.stdout, plain.stderr))
        check("mmCIF" not in plain.stdout,
              "a PDB was mistaken for mmCIF")
        print("clean structure: mmCIF and PDB give the same atoms, and what "
              "comes out is always PDB")


def check_chain_names() -> None:
    """COMPND says what each chain is, and the panel shows it once per molecule.

    The records wrap across lines and repeat a molecule for every chain it
    covers, so the two things worth pinning are that a wrapped name is
    rejoined and that four chains of one protein become one entry, not four.
    """
    from comfygmx.viz import parse_composition
    from comfygmx.seqmap import parse_sequence

    pdb = (
        "HEADER    IMMUNE SYSTEM                           10-MAY-23   TEST\n"
        "COMPND    MOL_ID: 1;\n"
        "COMPND   2 MOLECULE: T-CELL SURFACE GLYCOPROTEIN CD3 ZETA CHAIN;\n"
        "COMPND   3 CHAIN: A, B, a, b;\n"
        "COMPND   4 MOL_ID: 2;\n"
        "COMPND   5 MOLECULE: T CELL RECEPTOR DELTA VARIABLE 1,T CELL RECEPTOR\n"
        "COMPND   6 DELTA CONSTANT;\n"
        "COMPND   7 CHAIN: M;\n"
    )
    for index, chain in enumerate("ABabM"):
        pdb += (f"ATOM  {index + 1:5d}  CA  ALA {chain}{index + 1:4d}"
                f"       0.000   0.000   0.000  1.00  0.00           C\n")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.pdb"
        path.write_text(pdb)
        data = parse_composition(path)

    groups = {g["description"]: g["chains"] for g in data.get("molecules", [])}
    zeta = "T-cell surface glycoprotein CD3 zeta chain"
    if groups.get(zeta) != ["A", "B", "a", "b"]:
        failures.append(f"chain names: expected A B a b for CD3 zeta, got "
                        f"{groups.get(zeta)}")
    wrapped = [d for d in groups if d.startswith("T cell receptor delta")]
    if not wrapped:
        failures.append("chain names: no entry for the wrapped MOLECULE record")
    elif "delta constant" not in wrapped[0]:
        failures.append(f"chain names: continuation line lost -- {wrapped[0]!r}")
    # Lower-cased for reading, but the parts that are names stay upright.
    if "CD3" not in zeta or zeta.startswith("T-CELL"):
        failures.append(f"chain names: {zeta!r} is not the case RCSB shows")
    per_chain = {c["id"]: c.get("molecule", "") for c in data["chains"]}
    if per_chain.get("M", "") == "":
        failures.append("chain names: the chain row carries no molecule for its tooltip")

    # The missing-residues dialog reads a different parser, and needs the same
    # answer: a chain letter alone is not much to choose by.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.pdb"
        path.write_text(pdb)
        sequenced = parse_sequence(path)
    named = {c["id"]: c.get("molecule", "") for c in sequenced.get("chains", [])}
    if named.get("A") != zeta:
        failures.append(f"chain names: the sequence view calls chain A "
                        f"{named.get('A')!r}, not {zeta!r}")
    print(f"chain names: {len(groups)} molecule(s) over "
          f"{len(data['chains'])} chains, wrapped records rejoined")


def check_script_help() -> None:
    """Every ./script answers --help, and says what the others are called.

    The names are not guessable -- somebody who has met ./run.sh has no way to
    know that the setup questions live in ./setup.sh -- so each one carries the
    list, and a script that stops carrying it is a script somebody's help ends
    at.
    """
    scripts = ["run.sh", "start.sh", "setup.sh", "install.sh"]
    for name in scripts:
        try:
            done = subprocess.run(["bash", str(ROOT / name), "--help"],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            failures.append(f"{name} --help: {exc}")
            continue
        text = done.stdout
        if done.returncode != 0:
            failures.append(f"{name} --help exited {done.returncode}")
        elif len(text) < 200:
            failures.append(f"{name} --help printed {len(text)} characters")
        else:
            for other in scripts:
                check(other in text, f"{name} --help does not mention {other}")
    print(f"script help: {len(scripts)} entry points answer --help")


def check_scheduler() -> None:
    """Nodes run at once where the graph allows it, and only where it allows it.

    The riskiest change in the executor: it used to be one node at a time in
    topological order, which was hard to get wrong. Four things have to stay
    true, and none of them is visible from reading a graph -- so they are run.
    """
    import shutil as _shutil
    import tempfile
    import time as _time
    from comfygmx.executor import Executor

    def node(nid, script):
        return {"id": nid, "type": "util.shell", "pos": [0, 0],
                "params": {"script": script, "output": "out.txt"}}

    def link(a, b):
        return {"from_node": a, "from_port": "out", "to_node": b, "to_port": "in1"}

    def finish(executor, run, patience=30.0):
        deadline = _time.monotonic() + patience
        while run.status in ("queued", "running") and _time.monotonic() < deadline:
            _time.sleep(0.05)
        return run

    tmp = tempfile.mkdtemp(prefix="comfygmx-sched-")
    try:
        settings = Settings()

        def go(graph, limit, cls=Executor, wait=True):
            settings.set("max_parallel_nodes", limit)
            executor = cls(settings)
            ids = [n["id"] for n in graph["nodes"]]
            run = executor.start(graph, output_dir=tmp, force=ids)
            return executor, (finish(executor, run) if wait else run)

        # Independent work overlaps; the same graph serially takes four times
        # as long. Timed rather than counted: the point is the wall clock.
        fan = {"nodes": [node("a", "sleep 0.6"), node("b", "sleep 0.6"),
                         node("c", "sleep 0.6"), node("d", "sleep 0.6")], "links": []}
        start = _time.monotonic()
        go(fan, 4)
        wide = _time.monotonic() - start
        start = _time.monotonic()
        go(fan, 1)
        narrow = _time.monotonic() - start
        check(wide < narrow * 0.7,
              f"four independent nodes took {wide:.1f}s at once against "
              f"{narrow:.1f}s one at a time -- they are not overlapping")

        # A dependency is still a dependency.
        chain = {"nodes": [node("a", "true"), node("b", "sleep 0.3"), node("c", "true")],
                 "links": [link("a", "b"), link("b", "c")]}
        _, run = go(chain, 4)
        states = run.nodes
        check(states["a"].finished <= states["b"].started
              and states["b"].finished <= states["c"].started,
              "a chain of three nodes did not run in order")

        # A failure stops what is downstream of it and nothing else.
        mixed = {"nodes": [node("bad", "exit 3"), node("after", "true"),
                           node("apart", "true")], "links": [link("bad", "after")]}
        _, run = go(mixed, 3)
        check(run.nodes["bad"].status == "error", "a failing node did not report error")
        check(run.nodes["after"].status == "skipped",
              "a node downstream of a failure was not skipped")
        check(run.nodes["apart"].status == "done",
              "an unrelated node was skipped because something else failed")

        # A heavy node takes the machine to itself.
        class Solo(Executor):
            HEAVY = frozenset({"util.shell"})

        heavy = {"nodes": [node("x", "sleep 0.4"), node("y", "sleep 0.4"),
                           node("z", "sleep 0.4")], "links": []}
        start = _time.monotonic()
        go(heavy, 4, cls=Solo)
        alone = _time.monotonic() - start
        check(alone > 1.0,
              f"three heavy nodes finished in {alone:.1f}s at a limit of four -- "
              "they ran together, and mdrun would be fighting itself for cores")

        # Cancel reaches every process, not just the last one started.
        long = {"nodes": [node("p", "sleep 20"), node("q", "sleep 20"),
                          node("r", "sleep 20")], "links": []}
        executor, run = go(long, 3, wait=False)
        deadline = _time.monotonic() + 8
        while len(run.running) < 3 and _time.monotonic() < deadline:
            _time.sleep(0.05)
        live = len(run.running)
        executor.cancel(run.id)
        finish(executor, run, patience=15)
        check(live == 3, f"only {live} of three nodes were running before the cancel")
        check(run.status == "cancelled", f"cancelled run reports {run.status}")
        check(all(state.status in ("cancelled", "skipped")
                  for state in run.nodes.values()),
              "a node survived the cancel: "
              + str({n: s.status for n, s in run.nodes.items()}))
        print("scheduler: overlap, order, failure, heavy-alone and cancel checked "
              f"({wide:.1f}s wide against {narrow:.1f}s serial)")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


def check_switched_off() -> None:
    """A node switched off in the editor, and everything that depends on it,
    is left out of checking, running and exporting -- and nothing else is.

    The reason it exists: a half-wired node added to try something out used to
    stop the whole workflow from running, because its missing inputs are an
    error. Switched off, it has to stop getting in the way everywhere at once,
    since checking, running, "run this chunk" and exporting scripts each read
    the graph for themselves.
    """
    import shutil as _shutil
    import time as _time
    from comfygmx.executor import Executor
    from comfygmx.export import ExportError, export_workflow
    from comfygmx.graph import Graph, GraphError

    def shell(nid, script="true", **extra):
        return {"id": nid, "type": "util.shell", "pos": [0, 0], "title": nid.upper(),
                "params": {"script": script, "output": "out.txt"}, **extra}

    def link(a, b, port="in1"):
        return {"from_node": a, "from_port": "out", "to_node": b, "to_port": port}

    # A test node with nothing wired into its required inputs, hanging there.
    stray = {"id": "stray", "type": "gmx.trjconv", "pos": [0, 0], "params": {},
             "title": "Test trjconv"}
    graph = {"nodes": [shell("a"), shell("b"), dict(stray)],
             "links": [link("a", "b")]}
    errors = [p for p in Graph(graph).validate() if p["level"] == "error"]
    check(any(p["node"] == "stray" for p in errors),
          "switch off: the half-wired test node is not an error to begin with, "
          "so this check proves nothing")
    graph["nodes"][2]["off"] = True
    switched = Graph(graph)
    check(not [p for p in switched.validate() if p["level"] == "error"],
          "switch off: THE POINT -- a switched-off node still stops the "
          "workflow with its missing inputs: "
          + str([p for p in switched.validate() if p["level"] == "error"]))
    check("switched off" in switched.left_out_reason("stray"),
          "switch off: the reason for leaving it out does not say it is "
          f"switched off ({switched.left_out_reason('stray')!r})")
    check(set(switched.nodes) == {"a", "b"},
          f"switch off: the rest of the graph changed ({sorted(switched.nodes)})")

    # Reuse of earlier results must not notice: a node's answer depends only
    # on it and what feeds it, and a switched-off bystander feeds nothing.
    without = Graph({"nodes": [shell("a"), shell("b")], "links": [link("a", "b")]})
    check(switched.signatures() == without.signatures(),
          "switch off: switching off an unrelated node changes what the others "
          "are remembered as, so their earlier results would not be reused")

    # Downstream goes too, through a needed wire or an optional one, however
    # far, and says which switched-off node it was because of.
    chain = {"nodes": [shell("a"), shell("b", off=True), shell("c"), shell("d"),
                       shell("e")],
             "links": [link("a", "b"), link("b", "c"), link("c", "d", "in2"),
                       link("a", "e")]}
    g = Graph(chain)
    check(set(g.left_out) == {"b", "c", "d"} and set(g.nodes) == {"a", "e"},
          "switch off: what depends on a switched-off node is not left out with "
          f"it (left out {sorted(g.left_out)}, kept {sorted(g.nodes)})")
    check(g.left_out.get("d") == "b" and "'B'" in g.left_out_reason("d"),
          "switch off: a node left out two steps down does not name the "
          f"switched-off node it depends on ({g.left_out_reason('d')!r})")
    check(all(l["from_node"] not in g.left_out and l["to_node"] not in g.left_out
              for l in g.links),
          "switch off: wires to or from a left-out node are still in the graph")

    # No "off" anywhere: exactly the graph it always was.
    plain = Graph({"nodes": [shell("a"), shell("b")], "links": [link("a", "b")]})
    check(not plain.left_out and set(plain.nodes) == {"a", "b"},
          "switch off: a workflow with nothing switched off lost a node")

    tmp = tempfile.mkdtemp(prefix="comfygmx-off-")
    try:
        executor = Executor(Settings())

        def finish(run, patience=30.0):
            deadline = _time.monotonic() + patience
            while run.status in ("queued", "running") and _time.monotonic() < deadline:
                _time.sleep(0.05)
            return run

        def started(**kwargs):
            """The run, or the reason it would not start, as text."""
            try:
                return finish(executor.start(output_dir=tmp, **kwargs)), ""
            except GraphError as exc:
                return None, str(exc)

        # Runs, with the switched-off node simply absent.
        runnable = {"nodes": [shell("a"), shell("b"), dict(stray, off=True)],
                    "links": [link("a", "b")]}
        run, refused = started(graph_data=runnable, force=["a", "b"])
        check(run is not None and run.status == "done" and "stray" not in run.nodes,
              "switch off: THE POINT -- the workflow did not run around the "
              f"switched-off node ({refused or (run.status, sorted(run.nodes))})")

        # Asked for by name.
        run, refused = started(graph_data=runnable, only=["stray"])
        check(run is None and "switched off" in refused,
              "switch off: running a switched-off node on its own "
              + ("started a run" if run else f"says {refused!r} instead of that "
                 "it is switched off"))
        # "Run this chunk" names every node in the box; the switched-off one is
        # skipped and the rest run.
        run, refused = started(graph_data=runnable, only=["a", "stray"], force=["a"])
        check(run is not None and run.status == "done" and set(run.nodes) == {"a"},
              "switch off: running a chunk with one node switched off did not "
              f"run the others ({refused or (run.status, sorted(run.nodes))})")
        run, refused = started(graph_data={"nodes": [dict(stray, off=True)],
                                           "links": []})
        check(run is None and "every node is switched off" in refused,
              f"switch off: everything off says {refused or 'nothing, and ran'}")

        # Exported scripts leave it out too.
        dest = Path(tmp) / "bundle"
        try:
            result = export_workflow(runnable, Settings(), dest, label="off")
            dirs = [step["dir"] for step in result["steps"]]
            check(dirs and not any("stray" in d for d in dirs),
                  "switch off: the exported scripts include the switched-off "
                  f"node ({dirs})")
        except ExportError as exc:
            check(False, f"switch off: exporting scripts stopped at the "
                  f"switched-off node ({exc})")
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)
    print("switch off: a switched-off node stops blocking, takes what depends on "
          "it along, and is left out of runs, chunk runs and exported scripts; "
          "nothing else changes")


def check_executables() -> None:
    """Every script the docs say to run with ./ must be executable *in git*.

    Not on disk -- on disk is not what a clone gets. This repository is
    developed on an SMB share, where `core.fileMode` is false and git records
    644 no matter what `chmod` was run. A script that arrives non-executable
    fails with "Permission denied", the user chmods it to get on with their
    day, and git then sees a modified tracked file that blocks the next pull.
    Which is exactly what happened, once.
    """
    entry_points = ["install.sh", "run.sh", "setup.sh", "start.sh",
                    "tools/check_platform.sh", "binder/postBuild",
                    "binder/build-image.sh", "binder/try-image.sh"]
    try:
        listing = subprocess.run(["git", "ls-files", "-s"] + entry_points,
                                 cwd=ROOT, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        print("executables: skipped (no git here)")
        return
    if listing.returncode != 0:
        print("executables: skipped (not a git checkout)")
        return
    modes = {}
    for line in listing.stdout.splitlines():
        mode, _, rest = line.partition(" ")
        modes[rest.split("\t", 1)[-1]] = mode
    for path in entry_points:
        mode = modes.get(path)
        if mode is None:
            failures.append(f"executables: {path} is not tracked")
        elif mode != "100755":
            failures.append(
                f"executables: {path} is committed as {mode}, so a fresh clone "
                "cannot run it -- git update-index --chmod=+x " + path)
    print(f"executables: {len(entry_points)} entry points checked")


def check_install_scripts() -> None:
    """What the Install button generates, for every tool and with a version asked for.

    Every assertion here exists because the generator got it wrong once. A pip
    package that declares extras -- vermouth[mdtraj], where the extra is what
    makes -dssp work at all -- lost them the moment a version was chosen. A
    version was pinned onto both package lists, which for a pip tool means the
    only conda package there is, so asking for martinize2 0.15.0 generated
    `conda create ... python=0.15.0`.

    The check is that the version lands on the package that *is* the tool and
    nowhere else. An earlier version of this grepped for the literal string
    `python=9.9.9`, which is one symptom of that rule being broken; it passed
    while four tools generated `git=9.9.9`, `openmm=9.9.9`, `mdanalysis=9.9.9`
    and a git URL with `==` bolted on.
    """
    toolbox = Toolbox(Settings())
    checked = 0
    for tool_id, spec in CATALOG.items():
        if not spec.conda_installable:
            continue
        checked += 1
        try:
            plain = toolbox.install_script(tool_id)
        except Exception as err:                          # noqa: BLE001
            failures.append(f"install scripts: {tool_id}: {err}")
            continue
        for package in spec.pip_packages:
            if "[" in package and package[package.index("["):package.index("]") + 1] \
                    not in plain:
                failures.append(f"install scripts: {tool_id} drops the extras from "
                                f"{package} -- the extra is a dependency")

        wanted = spec.primary(spec.versions_from) if spec.versions_from in (
            "pip", "conda") else ""
        try:
            script = toolbox.install_script(tool_id, version="9.9.9")
        except ValueError:
            # A tool with no listable index, or one installed straight from a
            # repository, has no version to ask for and says so. Refusing is
            # the documented behaviour; what must never happen is generating a
            # command with the version on the wrong package.
            if wanted and "://" not in wanted:
                failures.append(f"install scripts: {tool_id} refuses a version it "
                                f"should accept ({wanted})")
            continue
        if not wanted:
            failures.append(f"install scripts: {tool_id} accepted a version although "
                            "its versions cannot be listed")
            continue
        # Exactly one package carries it, and it is the tool's own.
        carriers = [word for line in script.splitlines()
                    for word in line.replace("'", " ").split()
                    if "9.9.9" in word]
        name = re.split(r"[<>=!\[]", wanted, 1)[0].strip()
        if not carriers:
            failures.append(f"install scripts: {tool_id} ignores the version asked for")
        for carrier in carriers:
            if not carrier.startswith(name):
                failures.append(
                    f"install scripts: {tool_id} puts the version on {carrier!r}, "
                    f"which is not {name} -- the package that is the tool")
        for package in spec.pip_packages:
            if "[" in package and package[package.index("["):package.index("]") + 1] \
                    not in script:
                failures.append(f"install scripts: {tool_id} drops the extras from "
                                f"{package} when a version is pinned")
    print(f"install scripts: {checked} tools rendered, with and without a version")


def check_trajectory_carries_its_run_file() -> None:
    """The trajectory blocks hand their run file along, and say when it stops matching.

    Nearly everything downstream of a trajectory needs both the trajectory and
    a run file to read it with. Without a socket to pass the run file on, every
    one of those blocks needed a second wire running back past everything in
    between to wherever the run file came from. In the standard analysis chunk
    that was six wires nobody could see the point of, and forgetting one showed
    up as "required input 'tpr' is not connected" with no hint of where to get
    it.

    The catch is that the run file describes every particle while the
    trajectory holds only the group that was asked for. When those differ, a
    GROMACS tool given both warns about the atom counts and carries on, so the
    answer can be quietly wrong rather than refused. The block has to say so.
    """
    from comfygmx.graph import Graph
    from comfygmx.executor import dry_plan
    from comfygmx.registry import REGISTRY

    block = REGISTRY.get("gmx.trjconv")
    if "tpr" not in [port.name for port in block.outputs]:
        failures.append("run file: the trajectory block has no tpr socket, so "
                        "everything after it has to be wired back by hand")
        return

    def planned(answers):
        graph = Graph({"nodes": [
            {"id": "f", "type": "io.file", "params": {"path": "/tmp/md.xtc"}},
            {"id": "t", "type": "io.file", "params": {"path": "/tmp/md.tpr"}},
            {"id": "c", "type": "gmx.trjconv",
             "params": {"pbc": "mol", "groups": answers}}],
            "links": [
                {"from_node": "f", "from_port": "file", "to_node": "c", "to_port": "traj"},
                {"from_node": "t", "from_port": "file", "to_node": "c", "to_port": "tpr"}]})
        return dry_plan(graph, Settings())["c"]

    whole = planned("Protein\nSystem\n")
    handed = (whole.get("outputs") or {}).get("tpr") or {}
    if "md.tpr" not in str(handed.get("name") or handed.get("path") or handed):
        failures.append("run file: the tpr socket does not hand out the run "
                        f"file it was given, it hands out {handed}")
        return
    if any("no longer matches" in note for note in whole.get("notes", [])):
        failures.append("run file: it warns that the run file does not match "
                        "even when the whole system was written, which teaches "
                        "people to ignore the warning")
        return

    part = planned("Protein\nProtein\n")
    if not any("no longer matches" in note for note in part.get("notes", [])):
        failures.append("run file: writing only one group says nothing about "
                        "the run file no longer matching the trajectory, and a "
                        "tool given both carries on rather than refusing")
        return

    # And the chunk really is wired through, so it needs two wires and not eight.
    chunk = json.loads((ROOT / "workflows" / "analysis-standard.json").read_text())
    wired = {(link["from_node"], link["from_port"], link["to_node"], link["to_port"])
             for link in chunk["links"]}
    for source, target in (("pbc", "fit"), ("fit", "rms"), ("fit", "rmsf"),
                           ("fit", "rg")):
        if (source, "tpr", target, "tpr") not in wired:
            failures.append(f"run file: the standard analysis chunk does not "
                            f"carry the run file from {source} to {target}, so "
                            "that branch has to be wired up by hand")
            return
    # And the run chunk and the analysis chunk must not both do the box fix.
    # They used to hold the very same block, set the very same way, so running
    # then analysing read and wrote the whole trajectory twice for no gain. On
    # a 46 GB trajectory off a share at 21 MB/s that is most of an hour.
    from comfygmx.chunks import CHUNKS

    def chunk(name):
        found = [c for c in CHUNKS if c["id"] == name]
        return found[0]["graph"] if found else None

    run_chunk, analysis = chunk("production"), chunk("analysis_basic")
    if run_chunk is None or analysis is None:
        failures.append("run file: the production or analysis chunk is gone")
        return
    fixers = [n for n in run_chunk["nodes"] if n["type"] == "gmx.trjconv"]
    if fixers:
        failures.append(
            "run file: the production chunk ends with a trjconv block again, "
            "and the analysis chunk starts with the same one, so running then "
            "analysing passes over the whole trajectory twice")
        return
    # Both blocks in the analysis chunk are trjconv, so counting them proves
    # nothing: one fixes the box and the other takes out the tumbling. What has
    # to be there is one that actually fixes the box, which is the one with
    # -pbc set to something.
    fixes_box = [n for n in analysis["nodes"]
                 if n["type"] == "gmx.trjconv"
                 and (n.get("params") or {}).get("pbc", "none") != "none"]
    if not fixes_box:
        failures.append(
            "run file: nothing in the analysis chunk fixes the box any more. "
            "Measuring a trajectory whose molecules are split across the box "
            "edge gives numbers rather than an error, so nothing would say so")
        return
    if not any(n["type"] == "gmx.mdrun" for n in run_chunk["nodes"]):
        failures.append("run file: the production chunk has no mdrun in it")
        return
    wired = {(l["from_node"], l["from_port"], l["to_node"], l["to_port"])
             for l in analysis["links"]}
    for source, target in (("pbc", "fit"), ("fit", "rms"), ("fit", "rmsf"),
                           ("fit", "rg")):
        if (source, "tpr", target, "tpr") not in wired:
            failures.append(f"run file: the analysis chunk does not carry the "
                            f"run file from {source} to {target}")
            return

    print("run file: the trajectory and simulation blocks hand their run file "
          "on, both chunks carry it, and the box fix happens once rather than "
          "twice when a run is joined to an analysis")


def check_file_tidying() -> None:
    """Copy, move, rename and delete, and the things they must refuse.

    A file panel that can act is a file panel that can lose somebody's work, so
    the refusals matter more than the actions. Two rules: nothing is written
    over, and nothing is destroyed on the first press. Everything here runs in
    a throwaway folder with a throwaway data directory.
    """
    import shutil
    import tempfile

    from comfygmx import fileops

    with tempfile.TemporaryDirectory() as room:
        room = Path(room)
        (room / "a" / "deep").mkdir(parents=True)
        (room / "b").mkdir()
        (room / "a" / "one.txt").write_text("one\n")
        (room / "a" / "deep" / "two.txt").write_text("two\n")
        (room / "b" / "one.txt").write_text("something else\n")
        settings = Settings()
        settings.set("data_dir", str(room / "data"))

        def ok(label, result, want):
            if result.get("error"):
                failures.append(f"tidying: {label} was refused: "
                                + " ".join(result["error"].split())[:90])
                return False
            if want and not want():
                failures.append(f"tidying: {label} said it worked and did not")
                return False
            return True

        def refused(label, result):
            if not result.get("error"):
                failures.append(f"tidying: {label} was allowed, and must not be")
                return False
            return True

        # A folder, with what is inside it.
        if not ok("copying a folder",
                  fileops.transfer([str(room / "a" / "deep")], str(room / "b"), settings),
                  lambda: (room / "b" / "deep" / "two.txt").is_file()):
            return
        # Never over anything.
        if not refused("copying onto a name already in use",
                       fileops.transfer([str(room / "a" / "one.txt")],
                                        str(room / "b"), settings)):
            return
        if (room / "b" / "one.txt").read_text() != "something else\n":
            failures.append("tidying: the file it refused to write over was "
                            "written over anyway")
            return
        if not refused("putting a folder inside itself",
                       fileops.transfer([str(room / "a")],
                                        str(room / "a" / "deep"), settings)):
            return
        # Moving really moves.
        if not ok("moving a file",
                  fileops.transfer([str(room / "a" / "one.txt")],
                                   str(room / "b" / "deep"), settings, move=True),
                  lambda: (room / "b" / "deep" / "one.txt").is_file()
                  and not (room / "a" / "one.txt").exists()):
            return
        if not ok("renaming",
                  fileops.rename(str(room / "b" / "deep" / "one.txt"), "new.txt", settings),
                  lambda: (room / "b" / "deep" / "new.txt").is_file()):
            return
        if not refused("a rename with a slash in it",
                       fileops.rename(str(room / "b" / "deep" / "new.txt"),
                                      "sub/x.txt", settings)):
            return

        # Delete goes to the trash, keeping its name and its contents.
        result = fileops.delete([str(room / "b" / "deep")], settings)
        if not ok("deleting to the trash", result,
                  lambda: not (room / "b" / "deep").exists()):
            return
        binned = list((room / "data" / "trash").glob("*-deep"))
        if len(binned) != 1 or not (binned[0] / "new.txt").is_file():
            failures.append("tidying: what was deleted is not in the trash, or "
                            "did not arrive whole")
            return

        # And the guard rail. Asked of the predicate, never by calling delete
        # on a real path: a check that proves a guard works by trying the thing
        # the guard prevents is one edit away from being the accident. An
        # earlier version of this did exactly that, and only the fact that the
        # test could not rename /usr without being root kept it harmless.
        for label, target in (
                ("the root of the filesystem", "/"),
                ("a top-level folder", "/usr"),
                ("your home directory", str(Path.home())),
                ("the data folder itself", str(room / "data")),
                ("a folder holding the data folder", str(room)),
        ):
            if not fileops.too_important(Path(target), settings):
                failures.append(f"tidying: {label} ({target}) would be moved or "
                                "deleted on request, and must never be")
                return
        # That the guard is actually consulted, proved on a path of our own
        # that is guarded for a reason nothing else here relies on.
        if not refused("deleting the data folder",
                       fileops.delete([str(room / "data")], settings)):
            return
        if not refused("moving the data folder",
                       fileops.transfer([str(room / "data")], str(room / "b"),
                                        settings, move=True)):
            return

    print("tidying: copy, move, rename and delete-to-trash all work, and the "
          "five paths that must never go stay put")


def check_chain_letters_survive() -> None:
    """A structure with chains must not quietly come out as one molecule.

    A .gro file has no column for a chain letter. Hand pdb2gmx a sixteen-chain
    complex and ask for a .gro and it does the right thing by the topology --
    every chain its own molecule -- but the structure comes back as one
    continuous run of residues renumbered from 1, and it looks in every viewer
    as if the chains have been welded together. Nothing said so.

    Two things are checked: the box that keeps them really changes what is
    written, and the block says something when they are about to be lost.
    """
    import subprocess
    import tempfile

    from comfygmx.graph import Graph
    from comfygmx.executor import dry_plan
    from comfygmx.nodes.gromacs_nodes import _CHECK_ALL_ATOM_SCRIPT

    def built(params):
        g = Graph({"nodes": [
            {"id": "s", "type": "io.structure",
             "params": {"source": "file", "path": "/tmp/x.pdb"}},
            {"id": "t", "type": "gmx.pdb2gmx", "params": params}],
            "links": [{"from_node": "s", "from_port": "structure",
                       "to_node": "t", "to_port": "structure"}]})
        plan = dry_plan(g, Settings())["t"]
        if plan.get("error"):
            return None, plan["error"]
        for step in plan["_plan"].steps:
            argv = step.argv or []
            if len(argv) > 1 and argv[1] == "pdb2gmx" and "-o" in argv:
                return argv[argv.index("-o") + 1], ""
        return None, "no pdb2gmx step"

    plain, err = built({"forcefield": "charmm36-jul2022"})
    if err or not plain.endswith(".gro"):
        failures.append(f"chain letters: the usual output is {plain or err}, "
                        "not the .gro it has always been")
        return
    kept, err = built({"forcefield": "charmm36-jul2022",
                       "chain_letters": "keep them: write a PDB instead"})
    if err or not kept.endswith(".pdb"):
        failures.append("chain letters: asking to keep them still writes "
                        f"{kept or err}, which cannot hold a chain letter")
        return

    # And the warning, on a two-chain structure asking for a .gro.
    lines = []
    for chain, resid in (("A", 1), ("A", 2), ("B", 1), ("B", 2)):
        for index, (name, element) in enumerate(
                [("N", "N"), ("CA", "C"), ("C", "C"), ("O", "O")], start=1):
            # Column for column: 1-6 ATOM, 7-11 serial, 13-16 name, 17 is
            # the alternate-location letter, 18-20 residue, 22 the chain. Get
            # the alternate-location column wrong and the chain moves one to
            # the left, which is a fine way to write a test that fails for a
            # reason that has nothing to do with what it is testing.
            lines.append(
                f"ATOM  {index:5d} {name:<4s} ALA {chain}{resid:4d}    "
                f"{1.0 + index:8.3f}{2.0:8.3f}{3.0:8.3f}  1.00  0.00"
                f"          {element:>2s}")
    with tempfile.TemporaryDirectory() as room:
        room = Path(room)
        (room / "two.pdb").write_text("\n".join(lines) + "\nEND\n")
        (room / "check.py").write_text(_CHECK_ALL_ATOM_SCRIPT)
        said = {}
        for wanted in ("out.gro", "out.pdb"):
            done = subprocess.run([sys.executable, "check.py", "two.pdb", wanted],
                                  cwd=room, capture_output=True, text=True)
            said[wanted] = done.stdout
    if "2 chains" not in said["out.gro"]:
        failures.append("chain letters: a two-chain structure written to a .gro "
                        "gets no warning that the chains will not be in it")
        return
    if "chains" in said["out.pdb"]:
        failures.append("chain letters: it warns about losing chains even when "
                        "writing a PDB, which keeps them")
        return
    print("chain letters: kept by writing a PDB, and a structure about to lose "
          "them says so first")


def check_following_a_run() -> None:
    """The page follows a run by asking, over and over, what is new.

    It used to be one reply that stayed open for the whole run. The servers in
    front of mybinder.org hold such a reply back until it is complete, so a run
    there showed nothing until it was over; and with nothing else asked of it,
    mybinder.org closed the copy as unused half way through a run. Now each
    question gets a short, complete reply:

    - nothing new: the question waits (``wait`` seconds), then says so;
    - news while it waits: the answer goes back at once, not at the end of
      the wait, so the page still sees each step as it happens;
    - ``since``: only what the page has not seen yet;
    - the end: "finished", together with the message saying how the run
      ended, even though the run is marked over a moment before that
      message is sent.
    """
    import threading
    import time

    from comfygmx.executor import EventBus
    from comfygmx.server import Handler

    class Pretend:
        """Just enough of a request handler for one question."""

        def __init__(self, **query):
            self.query = query
            self.replies = []

        def q(self, name, default=""):
            return str(self.query.get(name, default))

        def _json(self, data, status=200):
            self.replies.append(data)

    def ask(bus, is_finished, **query):
        handler = Pretend(**query)
        began = time.monotonic()
        Handler._follow(handler, bus, is_finished)
        took = time.monotonic() - began
        if len(handler.replies) != 1:
            failures.append(f"following a run: {len(handler.replies)} replies "
                            "to one question instead of one")
            return {"events": [], "finished": False}, took
        return handler.replies[0], took

    bus = EventBus()
    state = {"over": False}
    over = lambda: state["over"]  # noqa: E731

    answer, took = ask(bus, over, since=0, wait=2)
    if answer["events"] or answer["finished"] or not 1.8 <= took <= 3.5:
        failures.append("following a run: a question with nothing new should "
                        f"wait about 2 s and say so; it took {took:.1f} s and "
                        f"said {answer}")
        return

    threading.Timer(0.5, lambda: bus.emit({"type": "log", "line": "step 1"})).start()
    answer, took = ask(bus, over, since=0, wait=10)
    if [e.get("line") for e in answer["events"]] != ["step 1"] or took > 2.0:
        failures.append("following a run: news that came while a question "
                        f"waited should be answered at once; it took {took:.1f} s "
                        f"and said {answer}")
        return
    seen = answer["events"][-1]["seq"]

    bus.emit({"type": "log", "line": "step 2"})
    answer, _ = ask(bus, over, since=seen, wait=10)
    if [e.get("line") for e in answer["events"]] != ["step 2"]:
        failures.append("following a run: asking since the last message seen "
                        f"should give only the new one; it gave {answer}")
        return
    seen = answer["events"][-1]["seq"]

    # The run is marked over first; the message saying how it ended follows
    # a moment later. A question asked in between must still carry it.
    state["over"] = True
    threading.Timer(0.2, lambda: bus.emit({"type": "run", "status": "error"})).start()
    answer, took = ask(bus, over, since=seen, wait=10)
    if not answer["finished"] or [e.get("status") for e in answer["events"]] != ["error"]:
        failures.append("following a run: the end should come with the message "
                        f"saying how the run ended; it said {answer}")
        return
    if took > 2.0:
        failures.append(f"following a run: the last answer took {took:.1f} s")
        return
    print("following a run: quiet questions wait and say so, news is answered "
          f"at once, and the end comes with how it ended ({took:.1f} s)")


class _ShellPage:
    """A stand-in for the page's Shell tab: the browser's end of a WebSocket.

    Written out here rather than taken from a package, like the server end in
    comfygmx/shell.py. A browser scrambles ("masks") what it sends, so this
    does too; the server would be right to refuse it otherwise.
    """

    def __init__(self, port: int, query: str = "", host: str = "",
                 origin: str = "") -> None:
        import base64
        import os
        import socket
        host = host or f"127.0.0.1:{port}"
        origin = origin if origin else f"http://{host}"
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /api/shell{query} HTTP/1.1\r\nHost: {host}\r\n"
            f"Origin: {origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                break
            head += chunk
        self.status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        self.messages: list = []   # what the server sent, as they came
        self.screen = b""          # everything the shell wrote, joined up
        self.over = False

    def _exactly(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
        return data

    def send(self, message) -> None:
        import json
        import os
        import struct
        payload = json.dumps(message).encode()
        mask = os.urandom(4)
        size = len(payload)
        head = (struct.pack("!BB", 0x81, 0x80 | size) if size < 126
                else struct.pack("!BBH", 0x81, 0x80 | 126, size))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def type(self, text: str) -> None:
        self.send({"type": "input", "data": text})

    def _one(self) -> None:
        import json
        import struct
        first, second = self._exactly(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._exactly(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._exactly(8))[0]
        payload = self._exactly(size)
        opcode = first & 0x0F
        if opcode == 0x8:
            self.over = True
            raise ConnectionError("closed")
        if opcode == 0x2:
            self.screen += payload
            self.messages.append(("bytes", payload))
        elif opcode == 0x1:
            self.messages.append(("json", json.loads(payload)))

    def until(self, wanted, seconds: float = 10.0) -> bool:
        """Read until wanted(self) is true; False if it never became true."""
        import socket
        import time
        end = time.monotonic() + seconds
        while not wanted(self):
            left = end - time.monotonic()
            if left <= 0 or self.over:
                return False
            self.sock.settimeout(left)
            try:
                self._one()
            except (socket.timeout, ConnectionError, OSError):
                return wanted(self)
        return True

    def said(self, kind: str) -> list:
        return [m for tag, m in self.messages if tag == "json" and m.get("type") == kind]

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def check_shell() -> None:
    """The Terminal drawer's Shell tab, against a real server and a real bash.

    What has to stay true:

      * a page from another website gets no shell, and neither does a page
        opened at a name the server does not know (the shell could otherwise
        be reached by any web page open in the same browser)
      * the shell starts in the folder asked for, at the size of the page's
        screen, and follows the page when it changes size
      * what is typed arrives, and what the shell writes comes back
      * `yes | head` ends quietly, without "Broken pipe"
      * Ctrl+C reaches the program in front, and the page is told which
        program that is
      * a page that comes back finds the same shell, with its screen
      * `exit` ends it, and a shell left without a page is hung up
    """
    import os
    import tempfile
    import threading
    import time

    from comfygmx import shell as shell_module
    from comfygmx.server import build_server

    try:
        httpd = build_server("127.0.0.1", 0, Settings())
    except OSError as exc:
        print(f"shell: skipped ({exc})")
        return
    port = httpd.server_address[1]
    shells = httpd.RequestHandlerClass.app.shells
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    folder = Path(tempfile.mkdtemp(prefix="shell-check-"))
    pages = []
    # The test's shells read your ~/.bashrc like any other, but keep what is
    # typed into them out of your own bash history.
    history_before = os.environ.get("HISTFILE")
    os.environ["HISTFILE"] = str(folder / "history")

    def page(query: str = "", **kw) -> _ShellPage:
        opened = _ShellPage(port, query, **kw)
        pages.append(opened)
        return opened

    try:
        # Another website's page: no shell, and no connection either.
        stranger = page("", origin="http://example.org")
        check("403" in stranger.status,
              f"shell: a page from another website was answered {stranger.status!r}, not refused")
        # A page opened at a name the server does not know: told why.
        renamed = page("", host=f"example.org:{port}")
        renamed.until(lambda p: p.said("refused"), 5)
        why = renamed.said("refused")
        check(bool(why) and "COMFYGMX_ALLOWED_HOSTS" in why[0].get("why", ""),
              "shell: a page opened at an unknown name was not refused with the "
              f"reason (it got {renamed.messages[:2]!r})")
        check(shells.count() == 0, f"shell: {shells.count()} shell(s) started for refused pages")
        # Behind a proxy the page's name differs from the server's; listed in
        # COMFYGMX_ALLOWED_HOSTS, it may have a shell.
        listed_before = os.environ.get("COMFYGMX_ALLOWED_HOSTS")
        os.environ["COMFYGMX_ALLOWED_HOSTS"] = "hub.example.org"
        try:
            proxied = page("", origin="https://hub.example.org")
            proxied.until(lambda p: p.said("ready") or p.said("refused"), 10)
            check(bool(proxied.said("ready")),
                  "shell: a page from a name listed in COMFYGMX_ALLOWED_HOSTS got no shell "
                  f"({proxied.status!r}, {proxied.messages[:1]!r})")
            if proxied.said("ready"):
                proxied.type("exit\r")
                proxied.until(lambda p: p.said("exit"), 10)
        finally:
            if listed_before is None:
                os.environ.pop("COMFYGMX_ALLOWED_HOSTS", None)
            else:
                os.environ["COMFYGMX_ALLOWED_HOSTS"] = listed_before
        unlisted = page("", origin="https://hub.example.org")
        check("403" in unlisted.status,
              f"shell: the same page, no longer listed, was answered {unlisted.status!r}")
        # In an online session (binder/launch.py) the page is reached only
        # through Jupyter, which asks for the session's token first and passes
        # the page's own name on: hub.example.org rather than this server's.
        # There the name check is left out. The check on pages from other
        # websites is not.
        jupyter_before = os.environ.get("COMFYGMX_BEHIND_JUPYTER")
        os.environ["COMFYGMX_BEHIND_JUPYTER"] = "1"
        try:
            online = page("", host="hub.example.org", origin="https://hub.example.org")
            online.until(lambda p: p.said("ready") or p.said("refused"), 10)
            check(bool(online.said("ready")),
                  "shell: behind Jupyter, the session's own page got no shell "
                  f"({online.status!r}, {online.messages[:1]!r})")
            if online.said("ready"):
                online.type("exit\r")
                online.until(lambda p: p.said("exit"), 10)
            intruder = page("", host="hub.example.org", origin="https://example.org")
            check("403" in intruder.status,
                  "shell: behind Jupyter, a page from another website was answered "
                  f"{intruder.status!r}, not refused")
        finally:
            if jupyter_before is None:
                os.environ.pop("COMFYGMX_BEHIND_JUPYTER", None)
            else:
                os.environ["COMFYGMX_BEHIND_JUPYTER"] = jupyter_before
        deadline = time.monotonic() + 5
        while shells.count() and time.monotonic() < deadline:
            time.sleep(0.1)

        # The real page.
        first = page(f"?cwd={folder}&cols=100&rows=30")
        check("101" in first.status, f"shell: the page's own request was answered {first.status!r}")
        ready = first.until(lambda p: p.said("ready"), 10) and first.said("ready")[0]
        check(bool(ready) and ready.get("cwd") == str(folder),
              f"shell: it did not start in the folder asked for ({ready!r})")
        first.type("stty size; pwd; yes | head -2; echo marker-$((6*7)); echo pid=$$\r")
        got = first.until(lambda p: b"pid=" in p.screen.split(b"marker-42")[-1]
                          and b"marker-42" in p.screen, 15)
        text = first.screen.decode(errors="replace")
        check(got, f"shell: typing did not come back as output: {text[-400:]!r}")
        check("30 100" in text, "shell: the shell did not start at the page's size (30 rows, 100 columns)")
        check(str(folder) in text, "shell: pwd did not print the folder it started in")
        check("Broken pipe" not in text, "shell: `yes | head` ended with 'Broken pipe'")
        pid_line = [line for line in text.splitlines() if line.startswith("pid=")]
        shell_pid = pid_line[-1].strip()[4:] if pid_line else ""

        first.send({"type": "resize", "cols": 120, "rows": 40})
        first.type("stty size\r")
        check(first.until(lambda p: b"40 120" in p.screen, 10),
              "shell: after the page grew to 40 rows and 120 columns, stty did not say so")

        first.type("sleep 30\r")
        check(first.until(lambda p: any(m.get("program") == "sleep" for m in p.said("busy")), 5),
              "shell: the page was not told that sleep was running in front")
        first.type("\x03")
        check(first.until(lambda p: p.said("busy") and p.said("busy")[-1].get("program") == "", 5),
              "shell: Ctrl+C did not stop sleep and bring the prompt back")

        # The page goes away and comes back: the same shell, with its screen.
        first.close()
        time.sleep(0.3)
        again = page(f"?id={ready.get('id', '')}&cols=120&rows=40")
        back = again.until(lambda p: p.said("ready"), 10) and again.said("ready")[0]
        check(bool(back) and back.get("again") is True and back.get("id") == ready.get("id"),
              f"shell: a page coming back did not find its shell ({back!r})")
        again.until(lambda p: b"marker-42" in p.screen, 5)
        check(b"marker-42" in again.screen, "shell: a page coming back did not get the screen back")
        again.type("echo pid=$$\r")
        again.until(lambda p: p.screen.count(b"pid=") >= 2, 10)
        check(f"pid={shell_pid}" in again.screen.decode(errors="replace").split("marker-42")[-1],
              "shell: the page that came back is talking to a different shell")

        again.type("exit\r")
        ended = again.until(lambda p: p.said("exit"), 10) and again.said("exit")[0]
        check(bool(ended) and ended.get("code") == 0,
              f"shell: `exit` did not end it with code 0 ({ended!r})")
        time.sleep(0.2)
        check(shells.count() == 0, "shell: the server still counts a shell after `exit`")

        # A shell whose page never comes back is hung up after the grace time.
        keep = shell_module.GRACE_SECONDS
        shell_module.GRACE_SECONDS = 1.0
        try:
            lonely = page("?cols=80&rows=24")
            lonely.until(lambda p: p.said("ready"), 10)
            lonely.type("echo pid=$$\r")
            lonely.until(lambda p: b"pid=" in p.screen.split(b"$$")[-1], 10)
            found = [line for line in lonely.screen.decode(errors="replace").splitlines()
                     if line.startswith("pid=")]
            lonely_pid = int(found[-1].strip()[4:]) if found else 0
            lonely.close()
            deadline = time.monotonic() + 8
            while shells.count() and time.monotonic() < deadline:
                time.sleep(0.2)
            check(shells.count() == 0, "shell: a shell left without its page was not hung up")

            def running(pid: int) -> bool:
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False

            deadline = time.monotonic() + 8
            while lonely_pid and running(lonely_pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            alive = bool(lonely_pid) and running(lonely_pid)
            check(lonely_pid and not alive,
                  f"shell: the hung-up shell (process {lonely_pid}) is still running")
        finally:
            shell_module.GRACE_SECONDS = keep
    except OSError as exc:
        failures.append(f"shell: {exc}")
    finally:
        for opened in pages:
            opened.close()
        httpd.shutdown()
        httpd.server_close()
        if history_before is None:
            os.environ.pop("HISTFILE", None)
        else:
            os.environ["HISTFILE"] = history_before
        # The shells write their history as they end, which can be a moment
        # after the test has finished with them.
        time.sleep(0.5)
        shutil.rmtree(folder, ignore_errors=True)
    print("shell: two strangers refused, a listed name let in, and an online session's "
          "own page behind Jupyter; typing, size, Ctrl+C, coming back, exit and hang-up "
          "checked")


def check_keepalive() -> None:
    """A POST whose body nobody reads must not poison the connection.

    The server speaks HTTP/1.1, so a browser sends several requests down one
    socket. A handler that takes no arguments and never reads the body it was
    sent leaves those bytes in the socket, and the *next* request on that
    connection is parsed starting from them:

        Error code: 501
        Message: Unsupported method ('{}GET').

    which is what "Could not reach the builder" looked like from the outside,
    intermittently, depending on which connection the browser reused. The
    dispatcher drains the remainder now; this is the test that says so.

    Only endpoints that do nothing are used -- cancelling jobs and runs that do
    not exist -- because this runs on a real server with the real settings.
    """
    import re
    import socket
    import threading

    from comfygmx.server import build_server

    try:
        httpd = build_server("127.0.0.1", 0, Settings())
    except OSError as exc:
        print(f"keep-alive: skipped ({exc})")
        return
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def talk(sock, raw: bytes) -> str:
        """One request, one whole response -- headers and the body they declare."""
        sock.sendall(raw)
        sock.settimeout(10)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                return data.decode(errors="replace")
            data += chunk
        head, rest = data.split(b"\r\n\r\n", 1)
        match = re.search(rb"Content-Length:\s*(\d+)", head, re.I)
        want = int(match.group(1)) if match else 0
        while len(rest) < want:
            chunk = sock.recv(4096)
            if not chunk:
                break
            rest += chunk
        return head.split(b"\r\n", 1)[0].decode(errors="replace")

    endpoints = ["/api/jobs/does-not-exist/cancel", "/api/runs/does-not-exist/cancel"]
    try:
        for path in endpoints:
            sock = socket.create_connection(("127.0.0.1", port), timeout=10)
            try:
                body = b"{}"
                talk(sock, (
                    f"POST {path} HTTP/1.1\r\nHost: x\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    f"Connection: keep-alive\r\n\r\n"
                ).encode() + body)
                second = talk(sock, b"GET /api/info HTTP/1.1\r\nHost: x\r\n"
                                    b"Connection: close\r\n\r\n")
            finally:
                sock.close()
            if "200 OK" not in second:
                failures.append(
                    f"keep-alive: after POST {path} the next request on the same "
                    f"connection got {second!r} -- an unread request body is "
                    "still in the socket")
    except OSError as exc:
        failures.append(f"keep-alive: {exc}")
    finally:
        httpd.shutdown()
        httpd.server_close()
    print(f"keep-alive: {len(endpoints)} body-ignoring endpoints checked")


def check_layouts() -> None:
    """No shipped graph may have a node standing on another node.

    Positions are written as a table of (column, row) and node heights are a
    property of the browser, so the two drift apart every time a node grows a
    parameter.  They had drifted a long way: the measured height table was one
    error line short on every row -- 28 px, the red line a node carries when
    nothing is wired into it yet -- and twelve node types were missing from it
    altogether and falling back to a guess.  Six of the fifteen shipped
    workflows had a note lying across the node below it.

    Checked in pixels here rather than in the browser so it runs anywhere, and
    the numbers come from the same table the layout does, so this says the
    layout is self-consistent.  tools/measure_node_heights.js is what keeps
    that table honest against the real thing.
    """
    from comfygmx.tutorial_graph import height_of, width_of

    def overlaps(nodes):
        found = []
        for index, a in enumerate(nodes):
            for b in nodes[index + 1:]:
                ax, ay = a["pos"]
                bx, by = b["pos"]
                if (min(ax + width_of(a), bx + width_of(b)) - max(ax, bx) > 0
                        and min(ay + height_of(a), by + height_of(b)) - max(ay, by) > 0):
                    found.append(f"{a['id']} and {b['id']}")
        return found

    graphs = []
    for chunk in CHUNKS:
        graphs.append((f"chunk {chunk['id']}", chunk["graph"]["nodes"]))
    for tutorial in TUTORIALS:
        graph = (tutorial.get("graph") or {}).get("nodes")
        if graph:
            graphs.append((f"tutorial {tutorial['id']}", graph))
    for path in sorted(ROOT.glob("workflows/**/*.json")):
        data = json.loads(path.read_text())
        if data.get("nodes"):
            graphs.append((f"workflow {path.name}", data["nodes"]))

    bad = 0
    for name, nodes in graphs:
        clashes = overlaps(nodes)
        if clashes:
            bad += 1
            failures.append(f"{name}: {len(clashes)} overlapping node(s) -- "
                            f"{', '.join(clashes[:3])}")

    # And the boxes drawn round the groups. A group has no bounds of its own --
    # the editor draws a box around wherever its members ended up -- so two
    # groups whose members share a row produce two boxes lying across each
    # other even though no node overlaps any other. It looks like a mistake,
    # and it is one: a stage should read as a block.
    group_bad = 0
    group_graphs = 0
    for tutorial in TUTORIALS:
        graph = tutorial.get("graph") or {}
        nodes = {n["id"]: n for n in graph.get("nodes") or []}
        groups = graph.get("groups") or []
        if len(groups) < 2:
            continue
        group_graphs += 1
        boxes = {}
        for group in groups:
            members = [nodes[i] for i in group["nodes"] if i in nodes]
            if not members:
                continue
            boxes[group["title"]] = (
                min(m["pos"][0] for m in members),
                min(m["pos"][1] for m in members),
                max(m["pos"][0] + width_of(m) for m in members),
                max(m["pos"][1] + height_of(m) for m in members))
        titles = list(boxes)
        hits = []
        for i, one in enumerate(titles):
            for other in titles[i + 1:]:
                a, b = boxes[one], boxes[other]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    hits.append(f"\"{one}\" and \"{other}\"")
        if hits:
            group_bad += 1
            failures.append(
                f"tutorial {tutorial['id']}: the boxes drawn round "
                f"{' and '.join(hits[:2])} lie across each other")
    print(f"layouts: {len(graphs)} graphs checked, {len(graphs) - bad} clear; "
          f"group boxes in {group_graphs} tutorials, "
          f"{group_graphs - group_bad} clear")


def check_doc_counts() -> None:
    """The node counts written in the docs must match the catalogue.

    docs/tutorials.md and docs/tutorial-runs.md both say how many blocks each
    packaged tutorial has, and a tutorial gains a block now and then. Five of
    the nine numbers had gone stale before anyone noticed, so they are checked
    here rather than trusted.
    """
    import re

    want = {}
    for tutorial in TUTORIALS:
        nodes = (tutorial.get("graph") or {}).get("nodes")
        if nodes:
            want[tutorial["name"]] = len(nodes)

    for name in ("docs/tutorials.md", "docs/tutorial-runs.md"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if "|" not in line:
                continue
            hit = next((t for t in want if t in line), None)
            if not hit:
                continue
            # Every number on the line, because the tutorial's own number and
            # its node count sit in neighbouring cells and either could be
            # read as the other. The rule is simply that the real count has to
            # appear somewhere on the line.
            numbers = {int(n) for n in re.findall(r"\d+", line)}
            if want[hit] not in numbers:
                failures.append(
                    f"{name}: the line for \"{hit}\" does not mention its "
                    f"node count, which is {want[hit]} -- it says "
                    f"{sorted(numbers)}")
    print(f"doc counts: {len(want)} packaged tutorials checked against the docs")


#: Five notes from the ice tutorial, with the height each one actually
#: rendered at in the browser. Kept as a fixture because the layout of every
#: packaged tutorial is spaced by the estimate, and an estimate that drifts
#: 40 px low puts a note through the node underneath it.
MEASURED_NOTE_HEIGHTS = [
    # Measured 2026-09-26 in the browser, note card 536 px wide, after the
    # two runs at 300 K and 200 K became one heating run.
    (328, "note_what"), (360, "note_build"), (440, "note_heat"),
    (519, "note_read"),
]


def check_note_heights() -> None:
    """How tall a note is drawn, against how tall the layout thought it was.

    The estimate has to be right, and where it is not it has to be too big
    rather than too small: a note that reserves a pixel too many costs nothing
    and one that reserves a pixel too few sits on top of the next node.
    """
    from comfygmx.tutorial_graph import note_height
    from comfygmx.tutorials import get as tutorial

    notes = {n["id"]: (n.get("params") or {}).get("text", "")
             for n in tutorial("ice_melting")["graph"]["nodes"]
             if n.get("type") == "util.note"}
    worst = 0
    for measured, name in MEASURED_NOTE_HEIGHTS:
        if name not in notes:
            failures.append(f"note heights: the fixture names {name}, which the "
                            "ice tutorial no longer has -- remeasure")
            continue
        estimate = note_height(notes[name])
        if estimate < measured:
            failures.append(
                f"note heights: {name} is drawn {measured} px tall and the "
                f"layout reserves only {estimate} -- it will overlap")
        worst = max(worst, abs(estimate - measured))
    # The two halves of the same rule live in two languages, so they are
    # compared rather than trusted: the browser stops growing the box at
    # GROW_MAX_PX and the layout reserves space up to NOTE_CAP. If those drift
    # apart, every long note either overlaps the node below it or floats in a
    # pool of empty canvas.
    import re
    from comfygmx.tutorial_graph import NOTE_CAP
    js = (ROOT / "comfygmx/web/js/graph.js").read_text()
    hit = re.search(r"GROW_MAX_PX\s*=\s*(\d+)", js)
    if not hit:
        failures.append("note heights: graph.js no longer sets GROW_MAX_PX")
    elif int(hit.group(1)) != NOTE_CAP:
        failures.append(
            f"note heights: the browser stops a note growing at "
            f"{hit.group(1)} px and the layout reserves up to {NOTE_CAP}")
    from comfygmx.tutorial_graph import NOTE_WRAP
    wrap = re.search(r"GROW_WRAP\s*=\s*(\d+)", js)
    if not wrap:
        failures.append("note heights: graph.js no longer sets GROW_WRAP")
    elif int(wrap.group(1)) != NOTE_WRAP:
        failures.append(
            f"note heights: the browser wraps a note at {wrap.group(1)} "
            f"characters and the layout at {NOTE_WRAP}")
    print(f"note heights: {len(MEASURED_NOTE_HEIGHTS)} real notes, "
          f"estimate never short, worst {worst} px over; "
          f"both halves cap at {NOTE_CAP} px")


def check_tutorials_measured() -> None:
    """Every packaged tutorial has to say what it came out as when it was run.

    The panel shows this under "What it came out as here", so somebody whose
    own run has just finished has something to compare against. Three of the
    eleven had no such text and nobody noticed, because until recently nothing
    displayed it.
    """
    # PLACEHOLDER is what gets written while a tutorial's own run is still
    # going. It reads as filled in and is not, which is worse than empty.
    missing = [t["name"] for t in TUTORIALS
               if t.get("status") == "packaged"
               and (not t.get("measured")
                    or "PLACEHOLDER" in str(t.get("measured"))
                    or "PLACEHOLDER" in str(t.get("runtime", "")))]
    if missing:
        failures.append(
            "packaged tutorials with no record of what they produced: "
            + ", ".join(missing))
    packaged = sum(1 for t in TUTORIALS if t.get("status") == "packaged")
    print(f"tutorial results: {packaged - len(missing)}/{packaged} packaged "
          f"tutorials say what they came out as")


def check_box_maths() -> None:
    """The box the "pick it by eye" panel promises is the one GROMACS builds.

    Both numbers on that panel are worked out here rather than by running
    anything, so both are pinned against real runs. On lysozyme with hydrogens
    on, the two furthest atoms are 5.0101 nm apart, and `gmx editconf` builds a
    7.01008 nm cube at -d 1.0, a dodecahedron of 7.01008 x 7.01008 x 4.95687
    and an octahedron of 7.01008 x 6.60917 x 5.72371. `gmx solvate` then put
    10,644, 7,339 and 8,097 waters into those, and 12,596 into the cube at
    -d 1.2.
    """
    from comfygmx.viz import box_shapes, solute_span

    edges = {row["type"]: row["edge"] for row in box_shapes(5.0101, 1.0)}
    if abs(edges["cubic"] - 7.01008) > 0.001:
        failures.append(f"box edge at -d 1.0 is {edges['cubic']}, editconf builds 7.01008")

    # The volume each shape keeps, checked against the box vectors editconf
    # writes: the determinant of the three vectors is the volume.
    want_volume = {
        "cubic": 7.01008 ** 3,
        "dodecahedron": 7.01008 * 7.01008 * 4.95687,
        "octahedron": 7.01008 * 6.60917 * 5.72371,
    }
    for row in box_shapes(5.0101, 1.0):
        if row["type"] not in want_volume:
            continue
        off = abs(row["volume"] - want_volume[row["type"]]) / want_volume[row["type"]]
        if off > 0.005:
            failures.append(
                f"{row['type']} volume {row['volume']:.1f} nm3, editconf's box is "
                f"{want_volume[row['type']]:.1f}")

    measured = {("cubic", 1.0): 10644, ("cubic", 1.2): 12596,
                ("dodecahedron", 1.0): 7339, ("octahedron", 1.0): 8097}
    worst = 0.0
    for (shape, distance), real in measured.items():
        row = next(r for r in box_shapes(5.0101, distance, 1960) if r["type"] == shape)
        off = abs(row["waters"] - real) / real
        worst = max(worst, off)
        if off > 0.03:
            failures.append(
                f"water estimate for a {shape} at -d {distance} is {row['waters']}, "
                f"gmx solvate put in {real}")

    # And the measurement the whole thing rests on: the two furthest atoms.
    # A cube of side 3 has its corners 3*sqrt(3) apart.
    corners = [(x, y, z) for x in (0.0, 3.0) for y in (0.0, 3.0) for z in (0.0, 3.0)]
    span = solute_span(corners)
    if abs(span["diameter"] - 3 * 3 ** 0.5) > 0.001:
        failures.append(f"the widest distance across a 3 nm cube came out as "
                        f"{span['diameter']}, not {3 * 3 ** 0.5:.4f}")

    print(f"box maths: 3 shapes and 4 water counts checked against real runs, "
          f"worst {worst * 100:.1f}% out")


CHECKS = (
    check_registry,
    check_flag_hints,
    check_chunks,
    check_workflows,
    check_tutorials,
    check_plans,
    check_dry_run,
    check_export,
    check_chain_names,
    check_load_structure,
    check_clean_cif,
    check_forms,
    check_dialogs,
    check_workflow_tools,
    check_node_stacking,
    check_canvas_panning,
    check_wire_cutting,
    check_chunk_inputs,
    check_switch_off_editor,
    check_cached_tags,
    check_param_boxes,
    check_mdp_boxes,
    check_viewer_turn,
    check_file_picker,
    check_port_in_use,
    check_transcript_calls,
    check_scheduler,
    check_switched_off,
    check_executables,
    check_install_scripts,
    check_script_help,
    check_keepalive,
    check_shell,
    check_trajectory_carries_its_run_file,
    check_trajectory_groups,
    check_file_tidying,
    check_chain_letters_survive,
    check_following_a_run,
    check_layouts,
    check_downloaded_files,
    check_box_maths,
    check_doc_counts,
    check_note_heights,
    check_tutorials_measured,
)


def main() -> int:
    for check_one in CHECKS:
        check_one()
    if failures:
        print(f"\n{len(failures)} problem(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
