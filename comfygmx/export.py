"""A workflow as a folder of shell scripts, runnable without Comfy-gmx.

Two things people ask for, which turn out to be the same machinery:

* **This run, written down.**  A finished run already leaves a `command.sh`
  per node, but nothing that ties them together and nothing that records which
  GROMACS build or which conda environment answered.  That is a methods
  section, and it is assembly rather than new work.

* **Part of a workflow, moved somewhere else.**  Preparation, solvation,
  minimisation and equilibration on the workstation; production on a cluster.
  What has to travel is the commands *and* the files they read -- and the
  files a cluster cannot see are exactly the ones a naive copy of `command.sh`
  leaves behind, because Comfy-gmx stages inputs in Python rather than in the
  shell.

So the exporter plans every node exactly as a run would, but with the staging
recorded instead of performed.  Each staged file is then either

* produced by another exported node -- emitted as ``cp ../03_x/topol.top .``,
  a relative path that works wherever the folder is unpacked; or
* from outside the export -- copied into ``inputs/`` and emitted as
  ``cp ../inputs/protein.pdb .``.

Nothing in the result refers to Comfy-gmx, to this machine's home directory,
or to a run directory.  The one thing that cannot be made portable is where
conda and GROMACS live, so that is lifted into a single `env.sh` with this
machine's values as the defaults and a comment saying to change them.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import __version__
from .config import Settings
from .environments import CATALOG, Toolbox
from .executor import _link_or_copy, _materialise, make_stage
from .graph import Graph, GraphError
from .nodes.base import NodeError, PlanContext, Plan
from .registry import REGISTRY
from .runner import render_step, substitute_tool

#: Bumped when the layout of an exported folder changes.
BUNDLE_VERSION = 1


class ExportError(Exception):
    """The export cannot be written, with a reason a user can act on."""


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_") or "node"


@dataclass
class Staged:
    """One file or directory a node reads, and where it comes from."""

    source: Path
    name: str
    is_dir: bool = False
    #: Node id that produces it, or "" when it comes from outside the export.
    origin: str = ""
    #: Where it sits in the folder of the node that writes it. Not always
    #: ``name``: a file that arrives here as 2_md.xtc, because another input
    #: was already called md.xtc, is still md.xtc over there.
    inside: str = ""
    #: Its name in inputs/, for a file from outside the export. Two outside
    #: files with the same name are given different ones.
    stored: str = ""


@dataclass
class Exported:
    node_id: str
    node_type: str
    dirname: str
    plan: Plan
    staged: List[Staged] = field(default_factory=list)
    #: Files a step copies in itself (``Plan.bring``). They travel in inputs/
    #: like anything else from outside, but the step already emits its own
    #: copy, so they must not also appear in the staging block.
    imported: List[Staged] = field(default_factory=list)
    #: ``(source_dir_node, pattern)`` copies that only resolve at run time --
    #: a topology's companion .itp files, which do not exist yet.
    globs: List[Tuple[str, str]] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    #: Generated files that carry a machine-specific path, written as
    #: ``<name>.in`` with a token and substituted when the step runs.
    templated: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

def _plan_node(graph: Graph, node_id: str, workdir: Path, produced: Dict[str, Any],
               settings: Settings) -> Tuple[Plan, List[Staged]]:
    """Plan one node with its staging recorded rather than performed."""
    node = graph.nodes[node_id]
    node_type = node.get("type", "")
    if not REGISTRY.has(node_type):
        raise ExportError(f"{node_id}: unknown node type '{node_type}'")
    cls = REGISTRY.get(node_type)
    params = dict(cls.defaults())
    params.update(node.get("params") or {})

    inputs: Dict[str, Any] = {}
    for port, (source, source_port) in graph.incoming(node_id).items():
        inputs[port] = (produced.get(source) or {}).get(source_port)

    recorded: List[Staged] = []

    # Recorded *and* performed. A node may read an input while planning -- the
    # membrane node parses its template to know what it is building -- and a
    # plan made without the file is not the plan a run would make: it quietly
    # falls back to a one-lipid placeholder. So the files are put where the
    # node expects them, in a scratch tree that is deleted afterwards.
    def on_file(source: Path, target: Path) -> None:
        source = Path(source)
        recorded.append(Staged(source=source, name=target.name))
        if source.is_file():
            _link_or_copy(source, target)

    def on_dir(source: Path, target: Path) -> None:
        source = Path(source)
        recorded.append(Staged(source=source, name=target.name, is_dir=True))
        if source.is_dir() and not target.exists():
            try:
                target.symlink_to(source, target_is_directory=True)
            except OSError:
                pass

    ctx = PlanContext(
        node_id=node_id, node_type=node_type, params=params, inputs=inputs,
        workdir=workdir,
        stage=make_stage(workdir, dry=True, on_file=on_file, on_dir=on_dir),
        settings=settings,
        # Planned as a *dry* node: an exported workflow may never have run, so
        # the file an upstream node will write is not there to be inspected.
        # The only thing `dry` changes is whether a node checks that its input
        # exists; the commands it emits are the same either way.
        dry=True,
    )
    try:
        plan = cls().plan(ctx)
    except NodeError as exc:
        raise ExportError(f"{node_id} ({node_type}) cannot be planned: {exc}") from None
    except Exception as exc:                              # noqa: BLE001
        raise ExportError(f"{node_id} ({node_type}) failed to plan: {exc}") from None
    return plan, recorded


def _glob_sources(graph: Graph, node_id: str, produced: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Patterns a node copies out of an upstream directory.

    A topology arrives as ``topol.top`` plus whatever ``.itp`` files sit beside
    it, and which ones those are is only known once the producing node has run.
    Enumerating them now would export an empty list; emitting the pattern lets
    the shell answer the question at the moment it can be answered.
    """
    found: List[Tuple[str, str]] = []
    for port, (source, source_port) in graph.incoming(node_id).items():
        value = (produced.get(source) or {}).get(source_port)
        if not isinstance(value, dict):
            continue
        for pattern in value.get("glob") or []:
            found.append((source, pattern))
    return found


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

_ENV_HEADER = """\
#!/usr/bin/env bash
# Where the programs live.  This is the only file that mentions a path
# specific to a machine -- change these to match wherever you unpacked this.
#
# Written on {host} by Comfy-gmx {version} on {when}.

CONDA_SH="${{CONDA_SH:-{conda_sh}}}"
GMXRC="${{GMXRC:-{gmxrc}}}"
GMX="${{GMX:-{gmx}}}"
"""

_ENV_BODY = """
# comfygmx_use <tool>  -- put one tool's environment on PATH, then prove it works.
comfygmx_use() {
  case "$1" in
    gmx)
      if [ -n "${GMXRC:-}" ]; then
        # GMXRC reads $shell and $GMXLDLIB before assigning them, so it is not
        # safe under `set -u`.
        set +u; . "$GMXRC"; set +e; set -u
      fi
      ;;
    shell) ;;
    *)
      local want="COMFYGMX_ENV_$1"
      local env="${!want-}"
      if [ -n "$env" ]; then
        if [ -z "${CONDA_SH:-}" ] || [ ! -r "${CONDA_SH:-}" ]; then
          echo "env.sh: CONDA_SH is not set to a readable conda.sh, and $1 needs the '$env' environment" >&2
          exit 1
        fi
        set +u; . "$CONDA_SH"; conda activate "$env"; set -u
      fi
      ;;
  esac
  comfygmx_prove "$1"
}

# comfygmx_prove <tool>  -- try the tool, rather than trust that its name exists.
#
# A name that is there is not a tool that works. A run script once picked its
# python by taking the first environment in a list that EXISTED. On the
# workstation that found the right one. On the cluster the same name was not
# there, so it fell through to the system python, which has no MDAnalysis --
# and every measurement inside the job failed silently while the simulation
# itself carried on happily for another two days.
#
# The same for GROMACS: on a machine without the graphics-card libraries, `gmx`
# is on PATH and every call fails with "libcufft.so.12: cannot open shared
# object file". Better to find that out in the first second than after a night
# in the queue.
comfygmx_prove() {
  local key="COMFYGMX_PROVE_$1"
  local probe="${!key-}"
  if [ -z "$probe" ]; then return 0; fi
  if eval "$probe" >/dev/null 2>&1; then return 0; fi
  echo "" >&2
  echo "env.sh: '$1' does not work on this machine." >&2
  echo "env.sh: what was tried:  $probe" >&2
  local want="COMFYGMX_ENV_$1"
  local env="${!want-}"
  if [ -n "$env" ]; then
    echo "env.sh: it was looked for in the conda environment '$env'." >&2
    echo "env.sh: if that environment is not on this machine, or is a" >&2
    echo "env.sh: different one here, edit the line for $1 at the top of" >&2
    echo "env.sh: this file, or make the environment." >&2
  fi
  echo "env.sh: stopping now rather than running and producing nothing." >&2
  exit 1
}

# A non-English LC_NUMERIC makes printf write "0,000", which then fails
# float(). Every command below runs under LC_ALL=C for that reason.
export LC_ALL=C
"""


def _probe_for(tool: str) -> str:
    """A one-line shell test that the tool really works, quoted for env.sh.

    Cheap on purpose: it runs before every step, and a step that takes minutes
    should not wait seconds to be told what it already knows.  Importing the
    module is the test for a python tool, because that is the thing that goes
    wrong -- an environment that is missing on this machine leaves the system
    python in its place, and the system python has none of these packages.
    """
    if tool == "gmx":
        return "'\"${GMX:-gmx}\" --version'"
    if tool == "shell":
        return ""
    spec = CATALOG.get(tool)
    if not spec:
        return ""
    if spec.kind == "python" and spec.module:
        command = spec.probe_command or spec.command or "python"
        return f"'{command} -c \"import {spec.module}\"'"
    if spec.command:
        return f"'command -v {spec.command}'"
    return ""


def _env_script(toolbox: Toolbox, tools: Sequence[str], settings: Settings,
                checkouts: Dict[str, str]) -> str:
    conda_sh = ""
    from .config import detect_conda_root
    root = detect_conda_root(settings)
    if root:
        conda_sh = str(Path(root) / "etc" / "profile.d" / "conda.sh")
    gmxrc = str(settings.get("gmxrc") or "")
    gmx = str(settings.get("gmx_binary") or "gmx")

    lines = [_ENV_HEADER.format(
        host=os.uname().nodename, version=__version__,
        when=time.strftime("%Y-%m-%d %H:%M"),
        conda_sh=conda_sh, gmxrc=gmxrc, gmx=gmx)]
    lines.append("# One per tool this workflow uses. Blank means "
                 "\"whatever is already on PATH\".")
    for tool in sorted(set(tools)):
        if tool in ("shell", "gmx"):
            continue
        env = toolbox.config_for(tool).get("env", "") if tool in CATALOG else ""
        lines.append(f'COMFYGMX_ENV_{tool}="{env}"')
    probes = {tool: _probe_for(tool) for tool in sorted(set(tools))}
    probes = {tool: probe for tool, probe in probes.items() if probe}
    if probes:
        lines.append("")
        lines.append("# How each tool is proved to work before it is used. A "
                     "name that exists")
        lines.append("# is not a tool that works -- see comfygmx_prove below. "
                     "Blank one out")
        lines.append("# to skip the check for that tool.")
        for tool, probe in probes.items():
            lines.append(f"COMFYGMX_PROVE_{tool}={probe}")
    if checkouts:
        lines.append("")
        lines.append("# Tools that are a checkout rather than a package: where "
                     "that checkout is.")
        for path, variable in sorted(checkouts.items(), key=lambda kv: kv[1]):
            lines.append(f'{variable}="${{{variable}:-{path}}}"')
    lines.append(_ENV_BODY)
    return "\n".join(lines)


def _checkout_vars(settings: Settings, tools: Sequence[str]) -> Dict[str, str]:
    """Absolute checkout paths that appear in commands, and their variables.

    Some tools are a directory rather than a package -- the command says
    ``ln -sfn /home/you/OpenMembraneBuilder/src src``.  That path is a fact
    about one machine, exactly like where conda lives, so it is lifted into
    env.sh rather than left to be found and edited in a node's script.
    """
    found: Dict[str, str] = {}
    for tool in sorted(set(tools)):
        spec = CATALOG.get(tool)
        if not spec or not spec.repo:
            continue
        path = str(settings.source_dir(tool)).rstrip("/")
        if path:
            found[path] = f"COMFYGMX_SRC_{tool}"
    return found


#: Stands in for the GROMACS binary while a command is being rendered, and is
#: swapped for "$GMX" afterwards. It cannot be written as `"$GMX"` directly:
#: every token goes through shlex.quote, which turns that into '"$GMX"' -- a
#: literal six-character program name that no shell will expand. The token is
#: made of characters shlex.quote leaves alone, so it survives to be replaced.
_GMX_TOKEN = "@COMFYGMX_GMX@"


def _resumable(argv: Sequence[str], prefix: str, maxh: float) -> List[str]:
    """An mdrun that picks up where the last slot left off.

    Two branches rather than one line with ``-cpi`` on it: ``-cpi`` naming a
    checkpoint that does not exist is an error, so the first segment of a chain
    would fail before it started. This is the shape your own production script
    uses, and it is the reason it survives a queue.
    """
    kept: List[str] = []
    skip = 0
    for index, token in enumerate(argv):
        if skip:
            skip -= 1
            continue
        # Whatever the node was configured with is replaced: the slot decides
        # the wall-clock limit, and the checkpoint decides the resume.
        if token in ("-cpi", "-maxh"):
            skip = 1
            continue
        if token in ("-append", "-noappend"):
            continue
        kept.append(token)
    base = " ".join(shlex.quote(str(t)) for t in kept)
    checkpoint = shlex.quote(f"{prefix}.cpt")
    return [
        f'if [ -f {checkpoint} ]; then',
        f'  echo "continuing from {prefix}.cpt"',
        f'  {base} -cpi {checkpoint} -append -maxh {maxh:g}',
        "else",
        f'  echo "no checkpoint; starting {prefix} fresh"',
        f"  {base} -maxh {maxh:g}",
        "fi",
    ]


def _command_script(item: Exported, dirnames: Dict[str, str], toolbox: Toolbox,
                    checkouts: Dict[str, str],
                    chain: Optional[Dict[str, Any]] = None) -> str:
    out = [
        "#!/usr/bin/env bash",
        "# " + (f"{item.node_id} -- {item.node_type}"),
        "set -euo pipefail",
        'cd "$(dirname "${BASH_SOURCE[0]}")"',
        '. ../env.sh',
        "",
    ]

    copies: List[str] = []
    for staged in item.staged:
        if staged.origin:
            source = f"../{dirnames[staged.origin]}/{staged.inside or staged.name}"
        else:
            source = f"../inputs/{staged.stored or staged.name}"
        flag = "-r " if staged.is_dir else ""
        copies.append(f"cp -f {flag}{shlex.quote(source)} ./{shlex.quote(staged.name)}")
    for origin, pattern in item.globs:
        if origin not in dirnames:
            continue
        # Resolved by the shell when this runs, not now: the files a topology
        # drags along are written by the node upstream, which may not have run.
        # One loop per pattern: a value holding several ("*.itp *.txt") must
        # give the directory prefix to each of them, not only to the first.
        for piece in pattern.split():
            copies.append(f'for f in ../{dirnames[origin]}/{piece}; do '
                          f'[ -e "$f" ] && cp -f "$f" .; done; true')
    if copies:
        out.append("# inputs")
        out += copies
        out.append("")

    if item.templated:
        out.append("# generated files that name a path on the machine that "
                   "wrote them")
        expr = "".join(f' -e "s|@{v}@|${{{v}}}|g"' for v in sorted(checkouts.values()))
        for name in item.templated:
            out.append(f"sed{expr} {shlex.quote(name + '.in')} > {shlex.quote(name)}")
        out.append("")

    stored = {str(e.source): e.stored for e in item.imported if e.stored}
    last_tool = ""
    for step in item.plan.steps:
        if step.imports:
            # The command names an absolute path on the machine that exported
            # this. Rewritten to the copy that travelled in inputs/, which is
            # the whole point of putting the file there.
            for entry in step.imports:
                source = Path(entry["source"])
                name = stored.get(str(source), source.name)
                out.append(f"cp -f ../inputs/{shlex.quote(name)} "
                           f"./{shlex.quote(entry['local'])}")
            out.append("")
            continue
        tool = step.tool or "shell"
        if tool != last_tool:
            # "shell" is not an environment, it is the absence of one.
            if tool != "shell":
                out.append(f"comfygmx_use {shlex.quote(tool)}")
            last_tool = tool
        resolved = toolbox.resolve(tool)
        command = _GMX_TOKEN if tool == "gmx" else resolved.command
        rendered = render_step(step, command)["command"]
        for path, variable in checkouts.items():
            rendered = rendered.replace(path, f'${{{variable}}}')
        if step.stdin:
            body = step.stdin if step.stdin.endswith("\n") else step.stdin + "\n"
            rendered = f"{rendered} <<'COMFYGMX_STDIN'\n{body}COMFYGMX_STDIN"
        if step.label:
            out.append(f"# {step.label}")
        if step.allow_fail:
            rendered = f"{rendered} || true"
        if (chain and chain.get("step") == item.dirname and not step.shell
                and "mdrun" in " ".join(step.argv[:2])):
            out += _resumable(substitute_tool(step, command), chain["prefix"],
                              chain["maxh"])
        else:
            out.append(rendered)
        out.append("")

    # One pass at the end so both branches above are covered.
    return "\n".join(out).rstrip().replace(_GMX_TOKEN, '"$GMX"') + "\n"


_RUN_ALL = """\
#!/usr/bin/env bash
# Every step of this workflow, in order.
#
#   ./run_all.sh              run all of it
#   ./run_all.sh --from 03    start at step 03 and carry on
#   ./run_all.sh --until 05   run everything before step 05 and stop
#   ./run_all.sh --only 05    run just step 05
#   ./run_all.sh --list       print the steps and stop
#
# Each step is a directory holding its own command.sh; running one by hand
# does the same thing as running it from here.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

STEPS=(
%(steps)s)

FROM=""; ONLY=""; UNTIL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --until) UNTIL="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --list) printf '%%s\\n' "${STEPS[@]}"; exit 0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \\{0,1\\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

started=0
for step in "${STEPS[@]}"; do
  if [ -n "$UNTIL" ] && [[ "$step" == "$UNTIL"* ]]; then break; fi
  if [ -n "$ONLY" ] && [[ "$step" != "$ONLY"* ]]; then continue; fi
  if [ -n "$FROM" ] && [ "$started" -eq 0 ]; then
    if [[ "$step" == "$FROM"* ]]; then started=1; else continue; fi
  fi
  echo "== $step"
  bash "$step/command.sh"
done
echo "== done"
"""


def _run_all(items: Sequence[Exported]) -> str:
    steps = "".join(f"  {shlex.quote(i.dirname)}\n" for i in items)
    return _RUN_ALL % {"steps": steps}


#: The options this workflow did not set, kept as lines to switch on rather
#: than prose to look up. Written for somebody who has never used a cluster:
#: the names are one machine's and almost certainly not theirs, so each one
#: says what it is for, not just what it is called.
_SBATCH_EXAMPLES = """\
# ---------------------------------------------------------------------------
# THINGS THIS FILE DID NOT SET
#
# To switch one on, delete the extra "#" at the start of its line. The values
# are examples of the shape each line takes. The names in them come from one
# particular cluster and are almost certainly not yours.
#
##SBATCH -A my_account
#     Which project pays for the machine time. Most shared clusters insist on
#     this and turn the job away outright when it is missing, rather than
#     queueing it. The sacctmgr command near the top prints the projects you
#     belong to.
#
##SBATCH --mem=10G
#     How much memory the job may use, all together. Ask for too little and it
#     is killed part way through, with nothing else said about why. A big
#     solvated membrane needs a great deal more than a small peptide.
#
##SBATCH --mem-per-cpu=2G
#     The same thing said per processor instead of in total. Use one or the
#     other, never both.
#
##SBATCH --gres=gpu:1
#     Reserve one GPU, any kind.
#
##SBATCH --gres=gpu:a100:1
#     Reserve one GPU of a named kind, on a queue that has more than one kind.
#     Run  sinfo -o '%P %G'  on the cluster to see the names it uses.
#
##SBATCH --gres=gpu:nvidia_h200_mig_1g.18gb:1
#     Some clusters cut a big GPU into slices and hand out a slice. You
#     normally wait less for one, and a small system does not need more.
#
##SBATCH --nodelist=node07
#     Insist on one named machine. Useful when repeating a speed test, and a
#     good way to wait a long time otherwise.
#
##SBATCH -x node03,node09
#     Keep off named machines -- one you know is broken, say.
#
##SBATCH --qos=long
#     Some clusters have named sets of extra rules that let a job run longer
#     than its queue normally allows. Your admins will know if yours does.
#
##SBATCH -D /scratch/you/this-folder
#     Which folder to start in. Only needed if you submit from somewhere else.
#
##SBATCH --mail-type=END,FAIL --mail-user=you@example.org
#     Email you when the job ends or fails.
# ---------------------------------------------------------------------------

# Make GROMACS available. env.sh next to this file holds the paths from the
# computer you exported on, which are not this cluster's. So on a cluster you
# normally load its own copy of GROMACS first, and let that one win.
#
# . /etc/profile.d/modules.sh
# module load gromacs/2025.4
"""

def _cluster_prelude(options: Dict[str, Any]) -> str:
    """Two things a cluster job often needs before GROMACS is even started.

    An environment script to source -- the copy of GROMACS that actually runs
    on the compute nodes is often not the one the login node sees -- and a
    guard for a processor feature the build needs. A GROMACS built with
    AVX-512 dies instantly on a machine without it and prints NOTHING, which
    looks exactly like the job vanishing; saying so plainly is worth a line.
    """
    out = []
    env_script = str(options.get("env_script") or "").strip()
    if env_script:
        out.append(
            "# The GROMACS that actually runs on these nodes. Sourced first so\n"
            "# it wins over anything env.sh would otherwise pick up.\n"
            f"source {shlex.quote(env_script)}\n")
    flag = str(options.get("cpu_flag") or "").strip()
    if flag:
        out.append(
            f"# This GROMACS build needs the processor feature '{flag}'. On a\n"
            "# machine without it GROMACS dies at once and prints nothing at all,\n"
            "# which looks exactly like the job vanishing. Say so instead.\n"
            f"if ! grep -qm1 {shlex.quote(flag)} /proc/cpuinfo; then\n"
            f"    echo \"FATAL: $(hostname) has no {flag}, and this GROMACS needs it.\"\n"
            "    exit 1\n"
            "fi\n")
    return ("\n" + "\n".join(out)) if out else ""


_SBATCH_ONCE = """\
#!/bin/bash
{preamble}{directives}

# Comfy-gmx wrote this as a starting point, not as a finished submission. Every
# value above came either from the export dialog or from a default, and none of
# them has been checked against your cluster. Running
#
#     sbatch --test-only submit.sbatch
#
# on the cluster will tell you what is wrong before a real submission does.

{examples}
cd "${{SLURM_SUBMIT_DIR:-$PWD}}"
bash run_all.sh
"""

_SBATCH_CHAIN = """\
#!/bin/bash
{preamble}{directives}

# WHAT THIS FILE DOES
#
# The simulation needs longer than one turn in the queue, so it is done in
# turns. This file prepares everything once, runs the simulation for as long as
# the queue allows, saves its place, and hands itself back to the queue to
# carry on from there. It repeats until the simulation has finished.
#
# Each piece of that, and why it is there:
#
#   * mdrun is given  -maxh {maxh:g}  -- slightly less than the {time} you
#     asked for. It then stops itself in good order and saves its place,
#     instead of being cut off half way through writing a file.
#
#   * "Saving its place" means a checkpoint file. The next turn picks it up
#     with  -cpi.  The first turn has no checkpoint yet, so the script looks
#     for the file before using the flag: -cpi with nothing to read is an
#     error, which is why this is a question and not simply a flag.
#
#   * If the simulation ends with an error, the script does NOT hand itself
#     back to the queue. Repeating a crash all weekend helps nobody.
#
#   * It also stops if the GROMACS log has constraint failures in it (they
#     appear as "LINCS WARNING"). Ending without an error message is not proof
#     that a turn went well: GROMACS can carry on after these and keep
#     producing numbers that nobody should use.
#
#   * The whole run is finished when {prefix}.gro appears. GROMACS only writes
#     that file at the very last step, so its existence -- not a counter -- is
#     what ends the chain.
#
#   * The job name is passed again with  -J  when the script hands itself back.
#     Slurm reads the "#SBATCH" lines before the script runs, so they cannot
#     see anything the script works out for itself. Without -J, every turn
#     would fall back to the name at the top and you could not tell one chain
#     from another in the queue.

{examples}
cd "${{SLURM_SUBMIT_DIR:-$PWD}}"

CHAIN_STEP="{chain_step}"
PREFIX="{prefix}"
JOB_TAG="${{SLURM_JOB_NAME:-{job}}}"

echo "$(date -Is)  host $(hostname)  job ${{SLURM_JOB_ID:-none}}"

# --- everything before the long step, done once ----------------------------
if [ ! -e .prepared ]; then
    echo "== preparing"
    bash run_all.sh --until "$CHAIN_STEP" || exit 1
    touch .prepared
else
    echo "== preparation already done (.prepared exists; delete it to redo)"
fi

# --- the long step, one turn at a time --------------------------------------
echo "== $CHAIN_STEP"
bash "$CHAIN_STEP/command.sh"
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo "!! $CHAIN_STEP exited $STATUS. Not asking for another turn."
    echo "!! Read $CHAIN_STEP/$PREFIX.log and the slurm error file."
    exit 1
fi

LOG="$CHAIN_STEP/$PREFIX.log"
if [ -f "$LOG" ] && tail -20000 "$LOG" | grep -qi "LINCS WARNING\\|Constraint error"; then
    echo "!! constraint failures in this turn. Not asking for another."
    tail -20000 "$LOG" | grep -i -m5 "LINCS WARNING\\|Constraint error"
    exit 1
fi

if [ -f "$CHAIN_STEP/$PREFIX.gro" ]; then
    echo "== finished: $CHAIN_STEP/$PREFIX.gro written"
    exit 0
fi

echo "== turn used up, asking for another"

# Handing on to the next turn, and checking that it really happened.
#
# Three ways this has failed silently, all of which looked exactly like an
# ordinary success from the outside:
#
#   * the card was asked for by name without the "gpu:" in front. sbatch
#     refused the whole thing, printed the reason where nobody was looking,
#     and this job still exited 0.
#   * "no card wanted" was passed on as an empty value, and a shell treats
#     empty as missing, so a later turn quietly fell back to a default and
#     took a card it was not meant to have.
#   * the request was one no machine in the queue could ever satisfy. The new
#     job sat there marked PENDING for the reason ReqNodeNotAvail, which looks
#     exactly like waiting for a busy queue, and would have waited for ever.
#
# So: check that a job number came back, and then check the new job could
# actually run. Neither costs anything.
SUBMITTED=$(sbatch -J "$JOB_TAG" "${{SLURM_SUBMIT_DIR:-$PWD}}/submit.sbatch" 2>&1)
SENT=$?
echo "$SUBMITTED"
NEXT=$(printf '%s' "$SUBMITTED" | grep -oE '[0-9]+' | tail -1)
if [ $SENT -ne 0 ] || [ -z "$NEXT" ]; then
    echo "!! No job number came back, so the chain stops here." >&2
    echo "!! Whatever sbatch printed above is the reason. Nothing else will" >&2
    echo "!! tell you: the job you are reading the output of ended perfectly" >&2
    echo "!! well, and the simulation is simply not going to carry on." >&2
    exit 1
fi
echo "== the next turn is job $NEXT"

# A job can be accepted and still be one that can never start. The reason
# field is the only place that says so.
sleep 5
WHY=$(squeue -h -j "$NEXT" -o '%r' 2>/dev/null | tr -d ' ')
case "$WHY" in
    ReqNodeNotAvail*|BadConstraints|PartitionNodeLimit|PartitionTimeLimit|\
PartitionConfig|InvalidAccount|InvalidQOS|QOSGrpCpuLimit|AssocMaxJobsLimit)
        echo "!! Job $NEXT is in the queue but cannot run: $WHY" >&2
        echo "!! That is not a busy queue, it is a request no machine here can" >&2
        echo "!! meet -- usually a wrong queue name, a card name that does not" >&2
        echo "!! exist, or more of something than the queue allows. It is left" >&2
        echo "!! in the queue so you can look at it:" >&2
        echo "!!     scontrol show job $NEXT" >&2
        echo "!! and to take it out again:" >&2
        echo "!!     scancel $NEXT" >&2
        exit 1
        ;;
esac
echo "== job $NEXT is waiting its turn normally${{WHY:+ ($WHY)}}"
"""


_SBATCH_PREAMBLE = """\
# ---------------------------------------------------------------------------
# HOW TO USE THIS FILE
#
# A cluster is a large set of computers shared by many people. You do not run
# work on them yourself. You hand this file to a program called Slurm:
#
#     sbatch submit.sbatch
#
# and it puts you in a queue. When your turn comes it runs the commands at the
# bottom of this file on one of the machines, and saves everything they print
# into a file next to this one.
#
# The lines starting with "#SBATCH" are not comments -- they are your request:
# how long you need, how many processors, which queue. Anything else starting
# with "#" really is a comment.
#
# Comfy-gmx filled these in from what you typed when you exported, or from a
# default. It has never spoken to your cluster, so treat every value below as a
# guess to be checked. These commands, run on the cluster after you log in,
# answer nearly all of it:
#
#   sinfo -s
#       Lists the queues -- Slurm calls them "partitions" -- and how busy each
#       one is. A queue is a set of machines with its own rules: one may hold
#       the machines with GPUs, another may allow longer jobs.
#
#   sinfo -o '%P %l %c %m %G'
#       The same list with the numbers: queue name, longest job it allows,
#       processors per machine, memory per machine, and GPUs.
#
#   scontrol show partition NAME
#       Everything about one queue.
#
#   sacctmgr -n show assoc user=$USER format=account,partition
#       Which project your work is charged to, and which queues you may use.
#       Many clusters refuse a job that does not name a project.
#
#   sbatch --test-only submit.sbatch
#       A rehearsal. Slurm reads this file and says whether it would accept it,
#       and roughly when it would start, without queueing anything. Do this
#       first: it catches a wrong queue name in about a second.
# ---------------------------------------------------------------------------
"""


def _directives(job: str, partition: str, walltime: str, nodes: Any, ntasks: Any,
                cpus: Any, gres: str, mem: str = "", exclude: str = "",
                nodelist: str = "") -> str:
    """The #SBATCH block, each line saying in plain words what it asks for.

    Built rather than templated so the notes line up whatever length the values
    happen to be. A wall of bare flags is a wall nobody edits with any
    confidence -- and every one of these has to be checked against the cluster
    before the first submission.
    """
    rows: List[Tuple[str, str, str]] = [
        ("--job-name", job,
         "a name for this job, so you can find it in the queue"),
        ("--partition", partition,
         "which queue to join. `sinfo -s` lists them"),
        ("--time", walltime,
         "how long you are asking for. Stopped at it, finished or not"),
        ("--nodes", str(nodes),
         "how many machines. Leave at 1 unless told otherwise"),
        ("--ntasks-per-node", str(ntasks),
         "copies of the program per machine. 1 for a normal mdrun"),
        ("--cpus-per-task", str(cpus),
         "processors the program may use. mdrun reads this as -ntomp"),
    ]
    if gres:
        rows.append(("--gres", gres,
                     "GPUs to reserve, and the gpu: in front is part of the "
                     "name. `sinfo -o '%P %G'` lists them"))
    if mem:
        rows.append(("--mem", mem,
                     "memory for the whole job. A big solvated box needs more "
                     "than the queue's default"))
    if exclude:
        rows.append(("--exclude", exclude,
                     "keep off these machines -- ones your GROMACS build "
                     "cannot run on, or one everybody shares"))
    if nodelist:
        rows.append(("--nodelist", nodelist,
                     "insist on this machine. Left to itself the queue packs "
                     "jobs onto one node, where they fight for its memory"))
    rows += [
        ("--output", "slurm-%x-%j.out",
         "where its printed output goes. %x = job name, %j = job number"),
        ("--error", "slurm-%x-%j.err", "where its error messages go"),
    ]
    stems = [f"#SBATCH {flag}={value}" for flag, value, _ in rows]
    width = max(len(stem) for stem in stems) + 2
    lines = []
    for stem, (_, _, comment) in zip(stems, rows):
        lines.append(f"{stem:<{width}}# {comment}" if comment else stem)
    return "\n".join(lines)


def _sbatch(options: Dict[str, Any], label: str, chain: Optional[Dict[str, Any]]) -> str:
    """A submission file: one turn in the queue, or a chain that resumes itself.

    ``chain`` is ``{"step": <directory>, "prefix": <deffnm>, "maxh": <hours>}``
    when the export ends in a simulation that can save its place and carry on,
    and None otherwise -- a workflow with no mdrun in it has nothing to resume,
    and offering to chain one would produce a file that ran the whole thing
    again every turn.
    """
    gpus = str(options.get("gpus") or "").strip()
    gres = f"gpu:{gpus}" if gpus and gpus != "0" else ""
    job = _slug(label or "comfygmx")
    walltime = options.get("time") or "24:00:00"
    common = dict(
        job=job,
        time=walltime,
        preamble=_SBATCH_PREAMBLE,
        directives=_directives(
            job,
            options.get("partition") or "CHANGEME_no_partition_set",
            walltime,
            options.get("nodes") or 1,
            options.get("ntasks") or 1,
            options.get("cpus") or 8,
            gres,
            str(options.get("mem") or "").strip(),
            str(options.get("exclude") or "").strip(),
            str(options.get("nodelist") or "").strip()),
        examples=_SBATCH_EXAMPLES + _cluster_prelude(options),
    )
    if not chain:
        return _SBATCH_ONCE.format(**common)
    return _SBATCH_CHAIN.format(chain_step=chain["step"], prefix=chain["prefix"],
                                maxh=chain["maxh"], **common)


def _walltime_hours(text: str) -> float:
    """Hours in a Slurm walltime, or 0 if it is not one this understands.

    Slurm accepts minutes, mm:ss, hh:mm:ss, d-hh, d-hh:mm and d-hh:mm:ss.
    Only what is needed to put -maxh a little under the slot is handled; an
    unparseable value means no -maxh rather than a wrong one.
    """
    text = str(text or "").strip()
    if not text:
        return 0.0
    days = 0.0
    if "-" in text:
        head, _, text = text.partition("-")
        try:
            days = float(head)
        except ValueError:
            return 0.0
    parts = text.split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(numbers) == 1:
        hours = days * 24 + (numbers[0] / 60 if not days else numbers[0])
    elif len(numbers) == 2:
        hours = days * 24 + (numbers[0] / 60 + numbers[1] / 3600 if not days
                             else numbers[0] + numbers[1] / 60)
    else:
        hours = days * 24 + numbers[0] + numbers[1] / 60 + numbers[2] / 3600
    return hours


def _chain_target(graph: Graph, items: Sequence[Exported],
                  walltime: str) -> Optional[Dict[str, Any]]:
    """The step a chain would resume, or None if there is nothing to resume.

    The last mdrun in the export: everything before it is preparation that runs
    once, and it is the one that will not finish inside a slot.
    """
    for item in reversed(list(items)):
        if item.node_type != "gmx.mdrun":
            continue
        params = dict(graph.nodes[item.node_id].get("params") or {})
        hours = _walltime_hours(walltime)
        if hours <= 0:
            return None
        return {"step": item.dirname,
                "prefix": str(params.get("deffnm") or "md"),
                # Under the slot by 2.5%, floored at three minutes: enough for
                # mdrun to finish the step it is on and write the checkpoint.
                "maxh": round(max(hours - max(hours * 0.025, 0.05), 0.05), 3)}
    return None


def _methods(items: Sequence[Exported], toolbox: Toolbox, graph_data: Dict[str, Any],
             label: str, external: Sequence[Staged], settings: Settings) -> str:
    lines = [
        f"# {label or 'Workflow'}",
        "",
        f"Exported by Comfy-gmx {__version__} on {time.strftime('%Y-%m-%d %H:%M')}, "
        f"from {os.uname().nodename}.",
        "",
        "## Running it",
        "",
        "```bash",
        "# check env.sh first -- it holds the only machine-specific paths",
        "./run_all.sh",
        "```",
        "",
        "## Steps",
        "",
        "| # | node | type | commands |",
        "|---|---|---|---|",
    ]
    for index, item in enumerate(items):
        lines.append(f"| {index:02d} | `{item.node_id}` | `{item.node_type}` | "
                     f"{len(item.plan.steps)} |")

    lines += ["", "## Tools these steps use", ""]
    seen: Set[str] = set()
    for item in items:
        seen.update(item.tools)
    seen.discard("shell")
    if seen:
        lines += ["| tool | version here | environment |", "|---|---|---|"]
        for tool in sorted(seen):
            probe = toolbox.probe(tool) if tool in CATALOG else {}
            lines.append(f"| {tool} | {probe.get('version') or '(not probed)'} | "
                         f"`{probe.get('env') or 'PATH'}` |")
        lines += ["",
                  "Versions are what answered **on the machine this was exported "
                  "from**. They are recorded so a result can be traced, not to "
                  "claim anything about where it runs next."]
    else:
        lines.append("None -- every step is plain shell.")

    if external:
        lines += ["", "## Files that travelled with it", "",
                  "Copied into `inputs/` because they came from outside the "
                  "exported steps.", "",
                  "| file | size | came from |", "|---|---|---|"]
        for staged in external:
            try:
                size = staged.source.stat().st_size
                human = f"{size/1e6:.1f} MB" if size >= 1e6 else f"{size/1e3:.1f} kB"
            except OSError:
                human = "?"
            lines.append(f"| `{staged.stored or staged.name}` | {human} | `{staged.source}` |")

    lines += ["", "## The graph", "",
              "`workflow.json` is the workflow this came from; opening it in "
              "Comfy-gmx reproduces the editor state exactly.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The export itself
# --------------------------------------------------------------------------

def export_workflow(
    graph_data: Dict[str, Any],
    settings: Settings,
    dest: Any,
    *,
    only: Optional[Sequence[str]] = None,
    label: str = "",
    copy_inputs: bool = True,
    slurm: Optional[Dict[str, Any]] = None,
    executor: Any = None,
) -> Dict[str, Any]:
    """Write ``graph_data`` to ``dest`` as a folder of shell scripts.

    ``only`` exports exactly those nodes.  Anything they read that is produced
    by a node left out has to exist already -- that is what makes "prepare
    here, produce there" work, and what makes exporting the middle of a
    workflow nobody has run refuse rather than write something broken.
    """
    graph = Graph(graph_data)
    try:
        order = graph.topo_order()
    except GraphError as exc:
        raise ExportError(str(exc)) from None

    wanted = [n for n in order if not only or n in set(only)]
    if not wanted:
        raise ExportError("no nodes selected to export")
    missing = sorted(set(only or ()) - set(order))
    if missing:
        raise ExportError(f"not in this workflow: {', '.join(missing)}")

    dest = Path(dest).expanduser()
    if dest.exists() and any(dest.iterdir()):
        raise ExportError(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)

    dirnames = {node_id: f"{i:02d}_{_slug(node_id)}"
                for i, node_id in enumerate(wanted)}
    selected = set(wanted)
    toolbox = Toolbox(settings)

    # Boundary nodes: their outputs have to come from a previous run, because
    # nothing in the export will produce them.
    produced: Dict[str, Any] = {}
    signatures = graph.signatures(order)
    unavailable: List[str] = []
    for node_id in order:
        if node_id in selected:
            continue
        entry = None
        if executor is not None:
            entry = executor.cached_result(signatures.get(node_id, ""))
        if entry:
            produced[node_id] = entry.get("outputs") or {}
        else:
            unavailable.append(node_id)

    # Checked before anything is planned. A node whose upstream was left out
    # and never run reports itself as "input not connected", which is true of
    # the plan and useless as an explanation -- the wire is there, the result
    # behind it is not.
    orphans: List[str] = []
    for node_id in wanted:
        for port, (source, _) in graph.incoming(node_id).items():
            if source in selected or source in produced:
                continue
            orphans.append(f"'{node_id}' reads {port} from '{source}', which is "
                           f"not in this export and has no stored result")
    if orphans:
        shutil.rmtree(dest, ignore_errors=True)
        raise ExportError(
            "this export has nothing to read:\n  - " + "\n  - ".join(orphans)
            + "\n\nRun the workflow once so those results are cached, or add "
              "those nodes to the export.")

    scratch = Path(tempfile.mkdtemp(prefix="comfygmx-export-"))
    items: List[Exported] = []
    for node_id in wanted:
        workdir = scratch / dirnames[node_id]
        workdir.mkdir(parents=True, exist_ok=True)
        plan, staged = _plan_node(graph, node_id, workdir, produced, settings)
        # What this node brings in from outside has to be on disk too, or the
        # node downstream of it plans against a file that is not there.
        for step in plan.steps:
            for entry in step.imports:
                source = Path(entry["source"])
                if source.is_file():
                    _link_or_copy(source, workdir / entry["local"])
        globs = _glob_sources(graph, node_id, produced)
        produced[node_id] = _materialise(plan, workdir)

        # Where each staged file comes from: another exported step, or outside.
        for entry in staged:
            for source_id in selected:
                if source_id == node_id:
                    continue
                root = scratch / dirnames[source_id]
                try:
                    inside = entry.source.relative_to(root)
                except ValueError:
                    continue
                entry.origin = source_id
                entry.inside = inside.as_posix()
                break

        item = Exported(node_id=node_id, node_type=graph.nodes[node_id].get("type", ""),
                        dirname=dirnames[node_id], plan=plan, staged=staged,
                        globs=[g for g in globs if g[0] in selected],
                        tools=[s.tool or "shell" for s in plan.steps])
        items.append(item)

    # An input that is neither produced here nor sitting on disk means a node
    # upstream has to run first. Said plainly and all at once, rather than as
    # a broken script discovered on the cluster.
    blocked: List[str] = []
    external: List[Staged] = []
    for item in items:
        for step in item.plan.steps:
            for entry in step.imports:
                source = Path(entry["source"])
                item.imported.append(Staged(source=source, name=source.name))
        for entry in list(item.staged) + item.imported:
            if entry.origin:
                continue
            if entry.source.exists():
                external.append(entry)
            else:
                blocked.append(f"{item.node_id} needs {entry.name}, which "
                               f"{'no exported step writes' if not unavailable else 'is written by a step left out'}"
                               f" and is not on disk ({entry.source})")
    if blocked:
        shutil.rmtree(scratch, ignore_errors=True)
        hint = ""
        if unavailable:
            hint = ("\n\nLeft out of the export and never run: "
                    + ", ".join(unavailable)
                    + ". Run the workflow once, or include those nodes.")
        shutil.rmtree(dest, ignore_errors=True)
        raise ExportError("this export would not run:\n  - "
                          + "\n  - ".join(blocked) + hint)

    # One name in inputs/ for each file from outside. Two different files with
    # the same name -- md.xtc from two runs -- used to share a single copy
    # there, and every step that wanted either of them was handed the first.
    holders: Dict[str, str] = {}      # name in inputs/ -> the file it holds
    for entry in external:
        key = str(entry.source)
        name, number = entry.source.name, 1
        while holders.get(name, key) != key:
            number += 1
            name = f"{number}_{entry.source.name}"
        holders[name] = key
        entry.stored = name

    # -- write it out ---------------------------------------------------
    shutil.rmtree(scratch, ignore_errors=True)
    for node_id in wanted:
        (dest / dirnames[node_id]).mkdir(parents=True, exist_ok=True)

    tools: List[str] = []
    for item in items:
        tools += item.tools
    checkouts = _checkout_vars(settings, tools)

    # A chain only makes sense around something that checkpoints. Asked for on
    # a workflow with no mdrun in it, there is nothing to resume and every slot
    # would run the whole thing again, so it is refused rather than written.
    chain = None
    if slurm and str(slurm.get("mode") or "once") == "chain":
        chain = _chain_target(graph, items, slurm.get("time") or "")
        if chain is None:
            shutil.rmtree(dest, ignore_errors=True)
            raise ExportError(
                "a resubmitting chain needs a simulation to resume and a "
                "walltime to size it against. This export has "
                + ("no mdrun step in it" if not any(
                    i.node_type == "gmx.mdrun" for i in items)
                   else f"a walltime this does not understand: "
                        f"{slurm.get('time')!r}")
                + ". Export it as a one-off run instead.")

    inputs_dir = dest / "inputs"
    if external:
        inputs_dir.mkdir(exist_ok=True)
    copied_bytes = 0
    for entry in external:
        target = inputs_dir / (entry.stored or entry.name)
        if target.exists():
            continue
        if not copy_inputs:
            continue
        try:
            if entry.is_dir:
                shutil.copytree(entry.source, target, dirs_exist_ok=True)
            else:
                shutil.copyfile(entry.source, target)
                copied_bytes += target.stat().st_size
        except OSError as exc:
            raise ExportError(f"could not copy {entry.source}: {exc}") from None
    if external and not copy_inputs:
        (inputs_dir / "MANIFEST.txt").write_text(
            "# Bring these here before running. One per line: name, then where\n"
            "# it was on the machine this was exported from.\n"
            + "".join(f"{e.stored or e.name}\t{e.source}\n" for e in external))

    for item in items:
        target = dest / item.dirname
        for name, content in (item.plan.files or {}).items():
            tokenised = content
            for path_text, variable in checkouts.items():
                tokenised = tokenised.replace(path_text, f"@{variable}@")
            path = target / (name if tokenised == content else name + ".in")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tokenised)
            if tokenised != content:
                item.templated.append(name)
        script = target / "command.sh"
        script.write_text(_command_script(item, dirnames, toolbox, checkouts, chain))
        script.chmod(0o755)

    (dest / "env.sh").write_text(_env_script(toolbox, tools, settings, checkouts))
    run_all = dest / "run_all.sh"
    run_all.write_text(_run_all(items))
    run_all.chmod(0o755)
    (dest / "workflow.json").write_text(json.dumps(graph_data, indent=2))
    (dest / "METHODS.md").write_text(
        _methods(items, toolbox, graph_data, label, external, settings))
    if slurm:
        (dest / "submit.sbatch").write_text(_sbatch(slurm, label, chain))

    return {
        "path": str(dest),
        "bundle_version": BUNDLE_VERSION,
        "steps": [{"dir": i.dirname, "node": i.node_id, "type": i.node_type,
                   "commands": len(i.plan.steps)} for i in items],
        "inputs": [{"name": e.name, "source": str(e.source)} for e in external],
        "inputs_copied": bool(copy_inputs and external),
        "bytes": copied_bytes,
        "tools": sorted({t for t in tools if t != "shell"}),
        "slurm": bool(slurm),
        "chain": dict(chain) if chain else None,
    }
