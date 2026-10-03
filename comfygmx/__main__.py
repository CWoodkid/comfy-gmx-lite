"""Command line entry point: ``python -m comfygmx``."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

from . import __version__, bootstrap
from .config import Settings
from .environments import Toolbox, system_report
from .executor import Executor
from .registry import REGISTRY
from .server import serve, PortInUse


DATA_DIR_HELP = (
    "keep runs, uploads and the settings file in DIR instead of the usual "
    "folder. The first time a folder is used it starts from the settings you "
    "already have, so nothing has to be set up again; after that the two are "
    "separate and neither one can change the other."
)


def cmd_serve(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not args.no_browser:
        url = f"http://localhost:{args.port}/"

        def open_later() -> None:
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001 - a headless box has no browser
                pass

        threading.Thread(target=open_later, daemon=True).start()
    try:
        serve(args.host, args.port, settings)
    except PortInUse as err:
        # Not a crash, and not worth a traceback: the usual reason is that the
        # server from last time is still running.
        print("")
        print(str(err))
        print("")
        return 1
    return 0


def cmd_nodes(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(REGISTRY.categories(), indent=2))
        return 0
    for category in REGISTRY.categories():
        print(f"\n{category['name']}")
        for spec in category["nodes"]:
            print(f"  {spec['type']:<28} {spec['title']}")
    print()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = system_report(settings)
    print(f"Comfy-gmx {__version__}")
    print(f"data directory : {report['data_dir']}")
    print(f"conda root     : {report['conda_root'] or '(not found)'}")
    print(f"conda envs     : {', '.join(e['name'] for e in report['conda_envs']) or '(none)'}")
    candidates = report["gmxrc_candidates"]
    if candidates:
        active = (settings.get("gmxrc") or "").strip()
        print(f"GROMACS found  : {len(candidates)} installation(s)")
        for candidate in candidates:
            mark = "*" if candidate["path"] == active else " "
            binaries = ", ".join(candidate["binaries"]) or "(no binary in bin/)"
            print(f"  {mark} {candidate['version'] or '?':>8}  {binaries:<14} {candidate['path']}")
        if active and not any(c["path"] == active for c in candidates):
            print(f"  * (configured) {active}")
        elif not active:
            print("    none selected -- set one in Settings, or rely on PATH")
    else:
        print("GROMACS found  : (none -- set one in Settings, or rely on PATH)")
    print("\ntools")
    box = Toolbox(settings)
    missing = 0
    advice = []
    # Measure the columns rather than guessing them: the longest tool name is
    # mdvcontainment and the longest environment name is longer still, and
    # fixed widths ran them into the version beside them.
    rows = list(box.survey())
    name_width = max([len(r["id"]) for r in rows] + [10]) + 2
    env_width = max([len(r.get("env") or "") for r in rows] + [8]) + 4
    for row in rows:
        mark = "ok " if row["found"] else "-- "
        detail = row["version"] if row["found"] else row.get("error", "")
        env = f"[{row['env']}]" if row.get("env") else ""
        print(f"  {mark}{row['id']:<{name_width}}{env:<{env_width}}{detail}")
        if not row["found"]:
            if row.get("troubleshooting"):
                advice.append((row["name"], row["troubleshooting"]))
            if not row.get("optional", True):
                missing += 1
    for name, text in advice:
        print(f"\n{name}:")
        for line in _wrap(text, 76):
            print(f"  {line}")
    if missing:
        print(f"\n{missing} required tool(s) missing")
    return 1 if missing else 0


def cmd_setup(args: argparse.Namespace) -> int:
    """First run: install what is missing, in the right order, for this OS.

    The terminal half of the one-button setup.  It may ask for a password,
    which is exactly why the root-needing part lives here and not behind a
    button in the browser -- here there is a prompt to type it into.
    """
    settings = _settings(args)
    if args.if_needed and settings.get("setup_done"):
        return 0

    state = bootstrap.survey(settings)
    plat = state["platform"]
    where = f"{plat['pretty']}"
    if plat["family"]:
        where += f" ({plat['family']}"
        where += f", {plat['manager']})" if plat["manager"] else ")"
    print(f"Comfy-gmx {__version__} setup")
    print(f"  machine   {where} · {plat['machine']} · Python {plat['python']}")
    if plat["wsl"]:
        print("            running under WSL, which is Linux as far as this is concerned")
    if not plat["supported"]:
        print(f"  {plat['system']} is not supported natively — use WSL2 on Windows")
        return 1
    print()

    for req in state["requirements"]:
        mark = "ok" if req["present"] else "--"
        detail = req["detail"] if req["present"] else f"missing — {req['why']}"
        print(f"  {mark}  {req['name']:<11} {detail}")
    print()

    # GROMACS is deliberately not part of this. Nothing runs without it, but it
    # is a source build -- forty minutes, and flags that matter -- so it belongs
    # in the dialog where those are chosen rather than behind this one command.
    gmx = next((tool for tool in state["tools"] if tool["id"] == "gmx"), None)
    # Builds on disk that a run would not use: listed only when a run would
    # find no GROMACS at all, so the one named below is always the one in use.
    found = (gmx.get("found") or []) if gmx else []
    saved = str(settings.get("gmxrc") or "").strip()
    if gmx and not gmx["present"] and saved:
        print(f"GROMACS: Settings name a GMXRC that is not there: {saved}")
    if gmx and not gmx["present"] and found:
        print("GROMACS is on this machine, but a run would not find it: there is no")
        print("  GMXRC in Settings that works, and no gmx on the command path. Found:")
        for build in found:
            print(f"    {build['version'] or '?':<9} {build['path']}")
        print("  Point Settings at one of these, or load one in this terminal")
        print("  (source <the GMXRC>) and start Comfy-gmx again.")
        print()
    elif gmx and not gmx["present"]:
        print("GROMACS is not installed, and this will not install it.")
        print("  It is built from source, not put into an environment. Open the editor")
        print("  and use Environments -> Build from source, which asks for the version")
        print("  and the flags, or point Settings at a GMXRC you already have.")
        print()
    elif gmx:
        # The one the runs will use, and how they find it.
        how = {"settings": "the GMXRC in Settings",
               "path": "the gmx on the command path"}.get(gmx.get("how", ""), "")
        version = f"{gmx['version']}  " if gmx.get("version") else ""
        print(f"GROMACS  {version}{gmx['where']}" + (f"  ({how})" if how else ""))
        print()

    wanted = [t["id"] for t in state["tools"] if t["default"]]
    if args.no_tools:
        wanted = []
    elif args.tools:
        wanted = [t.strip() for t in args.tools.split(",") if t.strip()]
    choices = {"tools": wanted, "init_shell": args.init_shell,
               "system": [r["id"] for r in state["requirements"]] if args.with_system else []}
    result = bootstrap.plan(settings, choices)

    if args.dry_run:
        print(result["script"] or "# nothing to do")
        return 0

    sudo = result["sudo_commands"]
    if sudo:
        print("Needs root — these install system packages:")
        for entry in sudo:
            print(f"  {entry['command']}")
            print(f"      ({entry['name']}: {entry['why']})")
        print()

    if not result["steps"]:
        print("Nothing left to install." if not sudo
              else "Nothing left that can be installed without root.")
        settings.update({"setup_done": True})
        settings.save()
        return 0

    print("Will install, no root needed:")
    for step in result["steps"]:
        print(f"  {step['name']:<24} {step.get('detail', '')}")
    for note in result["notes"]:
        print(f"  note: {note}")
    print()

    if sudo and _ask("Run the root commands above first?", default=False, args=args):
        for entry in sudo:
            print(f"\n$ {entry['command']}")
            subprocess.call(["bash", "-c", entry["command"]])
        print()

    if not _ask("Install the rest now?", default=True, args=args):
        print("Nothing was installed. The same choices are in the editor's "
              "Setup dialog whenever you want them.")
        return 0

    workdir = settings.data_dir / "setup"
    code = bootstrap.run(result["script"], workdir)
    installed = [s["id"].split(":", 1)[1] for s in result["steps"]
                 if s["id"].startswith("tool:")]
    bootstrap.remember(settings, result["conda_root"], installed)
    if code == 0:
        print("\nSetup finished. Start it with ./run.sh")
    else:
        print(f"\n{code} step(s) did not finish — the scripts are in {workdir} "
              "and can be re-run one at a time.")
    return 0 if code == 0 else 1


def _ask(question: str, default: bool, args: argparse.Namespace) -> bool:
    """Yes or no.  ``--yes`` answers yes; no terminal answers no.

    The second half matters: ``nohup ./start.sh`` has nobody to ask, and a
    launcher that quietly downloads 700 MB because nothing objected is not a
    convenience.  It says what it skipped instead.
    """
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        print(f"  {question} — not asking, there is no terminal here. "
              "Run `python3 -m comfygmx setup` yourself, or pass --yes.")
        return False
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def _node_names(values: Optional[List[str]]) -> Optional[List[str]]:
    """Accept --only a --only b as well as --only a,b."""
    if not values:
        return None
    names = [part.strip() for value in values for part in value.split(",")]
    return [n for n in names if n] or None


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.ensure_dirs()
    graph = json.loads(Path(args.workflow).read_text())
    executor = Executor(settings)
    run = executor.start(graph, only=_node_names(args.only),
                         force=_node_names(args.force), label=args.label or "",
                         output_dir=args.output_dir or "",
                         gpu_busy=getattr(args, "gpu_busy", "") or "")
    print(f"run {run.id} -> {run.workdir}")

    seen = 0
    while True:
        events = run.bus.since(seen, timeout=5.0)
        for event in events:
            seen = max(seen, event["seq"])
            if event["type"] == "log":
                print(f"[{event['node']}] {event['line']}")
            elif event["type"] == "node":
                print(f"== {event['node']}: {event['status']} {event.get('error', '')}".rstrip())
            elif event["type"] == "run":
                print(f"== run {event['status']}")
        # Pushed out after every batch. Sent to a file rather than a terminal,
        # Python holds printed lines in a buffer and writes them in blocks, so
        # `comfy-gmx run ... > log &` showed an empty file for the whole run
        # and there was no way to tell a slow step from a stuck one.
        sys.stdout.flush()
        if run.status in ("done", "error", "cancelled") and not events:
            break
    return 0 if run.status == "done" else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Check a workflow file without running or exporting anything.

    A workflow that takes hours to run should be checkable in a second:
    unknown node types, missing required inputs, links into or out of ports
    that do not exist, parameters the node does not have, a declared output
    file wired into a port expecting a different kind of file, cycles.
    """
    from .graph import Graph

    failed = 0
    for path in args.workflow:
        graph = Graph(json.loads(Path(path).read_text()))
        problems = graph.validate()
        errors = [p for p in problems if p["level"] == "error"]
        # Said first and separately: a node switched off in the editor is not
        # checked, and somebody reading this should know it was not missed.
        for node_id in graph.left_out:
            print(f"{path}: left out [{node_id}]: {graph.left_out_reason(node_id)}")
        if not problems:
            print(f"{path}: no problems found")
        else:
            print(f"{path}: {len(problems)} problem(s)")
            for p in problems:
                where = f" [{p['node']}]" if p["node"] else ""
                print(f"  {p['level']}{where}: {p['message']}")
        if errors:
            failed += 1
    return 1 if failed else 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export import export_workflow, ExportError

    settings = _settings(args)
    graph = json.loads(Path(args.workflow).read_text())
    slurm = None
    if args.slurm:
        slurm = {"partition": args.partition, "time": args.time,
                 "nodes": args.nodes, "ntasks": args.ntasks,
                 "cpus": args.cpus, "gpus": args.gpus,
                 "mem": args.mem, "exclude": args.exclude,
                 "nodelist": args.nodelist, "env_script": args.env_script,
                 "cpu_flag": args.cpu_flag,
                 "mode": "chain" if args.chain else "once"}
    try:
        result = export_workflow(
            graph, settings, args.dest,
            only=args.only or None,
            label=args.label or Path(args.workflow).stem,
            copy_inputs=not args.no_inputs,
            slurm=slurm,
            executor=Executor(settings),
        )
    except ExportError as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1

    print(f"exported to {result['path']}")
    for step in result["steps"]:
        print(f"  {step['dir']:<28} {step['type']:<22} {step['commands']} command(s)")
    if result["inputs"]:
        where = "copied into inputs/" if result["inputs_copied"] else "listed in inputs/MANIFEST.txt"
        print(f"  {len(result['inputs'])} input file(s) {where}"
              + (f" ({result['bytes']/1e6:.1f} MB)" if result["bytes"] else ""))
    if result["tools"]:
        print(f"  tools: {', '.join(result['tools'])} — check env.sh before running")
    if result.get("chain"):
        chain = result["chain"]
        print(f"  submit.sbatch chains {chain['step']} in {args.time} slots, "
              f"mdrun -maxh {chain['maxh']:g}, finished when "
              f"{chain['prefix']}.gro appears")
    return 0


def _wrap(text: str, width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _settings(args: argparse.Namespace) -> Settings:
    """The saved settings, from the folder the command was pointed at.

    ``--data-dir`` has to move the *whole* set, not only where runs are
    written. It used to read the settings file in the default folder and then
    change one entry, so a second folder ran with the first folder's GROMACS
    path, tool environments and thread limits -- and no message to say so.
    """
    home = getattr(args, "data_dir", None)
    if not home:
        return _ready(Settings())
    home = Path(home).expanduser()
    own = home / "settings.json"
    if own.exists():
        settings = Settings(own)
    else:
        # First time this folder is used. Start from the settings that are
        # already there rather than from nothing, so pointing the tool at a
        # bigger disk does not mean finding GROMACS and conda all over again.
        # From here on the two files go their own way.
        settings = Settings()
        settings.path = own
    settings.set("data_dir", str(home))
    if not settings.path.exists():
        settings.save()
    return _ready(settings)


def _ready(settings: Settings) -> Settings:
    settings.ensure_dirs()
    return settings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="comfy-gmx",
        description="Comfy-gmx lite: molecular dynamics with GROMACS, as blocks wired together in a browser.",
    )
    parser.add_argument("--version", action="version", version=f"comfy-gmx {__version__}")
    parser.add_argument("--data-dir", help=DATA_DIR_HELP)
    sub = parser.add_subparsers(dest="command")

    # The same flag is offered on every subcommand as well, because
    # "serve --data-dir X" is what people type and the only form the
    # start-up scripts can pass along. SUPPRESS keeps a subcommand that
    # was not given the flag from wiping a value typed before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS,
                        help=DATA_DIR_HELP)

    p_serve = sub.add_parser("serve", help="start the local server (default)",
                             parents=[common])
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8189)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    p_nodes = sub.add_parser("nodes", help="list the available node types",
                             parents=[common])
    p_nodes.add_argument("--json", action="store_true")
    p_nodes.set_defaults(func=cmd_nodes)

    p_check = sub.add_parser("check",
                             help="report which external tools are reachable",
                             parents=[common])
    p_check.set_defaults(func=cmd_check)

    p_setup = sub.add_parser("setup", help="install what this machine is missing",
                             parents=[common])
    p_setup.add_argument("--yes", "-y", action="store_true",
                         help="do not ask; take the defaults")
    p_setup.add_argument("--dry-run", action="store_true", dest="dry_run",
                         help="print the script instead of running it")
    p_setup.add_argument("--if-needed", action="store_true", dest="if_needed",
                         help="do nothing at all if setup has run before")
    p_setup.add_argument("--tools", default="",
                         help="comma-separated tool ids instead of the defaults")
    p_setup.add_argument("--no-tools", action="store_true", dest="no_tools",
                         help="conda and system packages only")
    p_setup.add_argument("--with-system", action="store_true", dest="with_system",
                         help="also offer the optional system packages (compiler, cmake)")
    p_setup.add_argument("--init-shell", action="store_true", dest="init_shell",
                         help="also add conda to your shell startup files")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run",
                           help="execute a saved workflow without the browser",
                           parents=[common])
    p_run.add_argument("workflow")
    p_run.add_argument("--only", action="append",
                       help="run only this node and whatever feeds it; repeat "
                            "the flag, or separate several with commas")
    p_run.add_argument("--force", action="append",
                       help="ignore the cache for this node; repeat the flag, "
                            "or separate several with commas")
    p_run.add_argument("--label", default="")
    p_run.add_argument("--output-dir", default="", dest="output_dir",
                       help="where to create the run directory "
                            "(default: the configured output folder)")
    p_run.add_argument("--gpu-busy", default="", dest="gpu_busy",
                       choices=["processor", "share"],
                       help="when another simulation is using the graphics card: "
                            "run on the processor only, or share the card. "
                            "Default: what Settings says, and the processor "
                            "only where Settings says to ask")
    p_run.set_defaults(func=cmd_run)

    p_validate = sub.add_parser(
        "validate",
        help="check a workflow file for wiring mistakes without running it",
        parents=[common])
    p_validate.add_argument("workflow", nargs="+",
                            help="one or more workflow .json files")
    p_validate.set_defaults(func=cmd_validate)

    p_export = sub.add_parser(
        "export",
        help="write a workflow out as a folder of shell scripts you can move",
        parents=[common])
    p_export.add_argument("workflow")
    p_export.add_argument("dest", help="directory to create (must be empty)")
    p_export.add_argument("--only", action="append",
                          help="export just this node; repeat for more. What "
                               "they read from nodes left out must already "
                               "have been produced by a run.")
    p_export.add_argument("--label", default="")
    p_export.add_argument("--no-inputs", action="store_true", dest="no_inputs",
                          help="do not copy input files in; list them in "
                               "inputs/MANIFEST.txt instead")
    p_export.add_argument("--slurm", action="store_true",
                          help="also write a submit.sbatch to edit")
    p_export.add_argument("--chain", action="store_true",
                          help="make that submit.sbatch resubmit itself: the "
                               "simulation runs for --time, checkpoints, and "
                               "carries on in the next slot until it finishes")
    p_export.add_argument("--partition", default="")
    p_export.add_argument("--time", default="24:00:00")
    p_export.add_argument("--nodes", default=1, type=int)
    p_export.add_argument("--ntasks", default=1, type=int)
    p_export.add_argument("--cpus", default=8, type=int)
    p_export.add_argument("--gpus", default="")
    p_export.add_argument("--mem", default="",
                          help="memory for the whole job, e.g. 24G")
    p_export.add_argument("--exclude", default="",
                          help="machines to keep off, comma-separated")
    p_export.add_argument("--nodelist", default="",
                          help="a machine to insist on")
    p_export.add_argument("--env-script", default="", dest="env_script",
                          help="a script to source before anything runs -- the "
                               "GROMACS that works on the compute nodes")
    p_export.add_argument("--cpu-flag", default="", dest="cpu_flag",
                          help="a processor feature the GROMACS build needs, "
                               "e.g. avx512f; the job stops with a clear "
                               "message on a machine without it")
    p_export.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args((argv or []) + ["serve"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
