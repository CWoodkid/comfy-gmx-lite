"""The groups of atoms a system offers, for the boxes that ask for one by name.

A GROMACS tool asks "which group?" and offers a numbered list: System,
Protein, Water and so on, plus whatever an index file adds. That list exists
only once there is a run file to read it from, so a box cannot know it in
advance. This reads it the way the tools do, for the forms that offer it.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def read_ndx(path: str) -> List[Dict[str, Any]]:
    """The groups in an index file, in order, with how many atoms each holds."""
    groups: List[Dict[str, Any]] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        text = line.strip()
        if text.startswith("[") and text.endswith("]"):
            groups.append({"name": text[1:-1].strip(), "atoms": 0})
        elif groups and text:
            groups[-1]["atoms"] += len(text.split())
    return groups


def system_groups(tpr: str, toolbox: Any, timeout: float = 120.0) -> List[Dict[str, Any]]:
    """The groups GROMACS makes for a system by itself, as make_ndx lists them.

    make_ndx told to quit at once writes exactly the standard list into its
    output file, which is easier to read than the table it prints.
    """
    resolved = toolbox.resolve("gmx")
    with tempfile.TemporaryDirectory() as work:
        out = Path(work) / "standard.ndx"
        script = (f"{resolved.prelude}\nprintf 'q\\n' | {resolved.command} make_ndx "
                  f"-f {shlex.quote(str(tpr))} -o {shlex.quote(str(out))}")
        done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              timeout=timeout, cwd=work)
        if not out.is_file():
            said = [line for line in (done.stderr or done.stdout or "").splitlines()
                    if line.strip()]
            raise RuntimeError(f"gmx make_ndx could not read {Path(tpr).name}"
                               + (f": {said[-1].strip()}" if said else ""))
        return read_ndx(str(out))


def all_groups(tpr: str, index: str, toolbox: Any) -> List[Dict[str, Any]]:
    """Every group a block reading this system can be asked for.

    An index file's own groups first, then the system's standard ones it does
    not already name -- the order the Preview trajectory block puts them in
    when it runs, so a group the file defines itself wins over a standard one
    of the same name.
    """
    listed = read_ndx(index) if index else []
    seen = {group["name"] for group in listed}
    for group in system_groups(tpr, toolbox):
        if group["name"] not in seen:
            listed.append(group)
            seen.add(group["name"])
    return listed
