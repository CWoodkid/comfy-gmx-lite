#!/usr/bin/env python3
"""Start Comfy-gmx lite inside an online Jupyter session.

Jupyter runs this, through jupyter-server-proxy, the first time somebody opens
<session address>/comfygmx/. It passes a free port number, and from then on
hands every request for that address to the editor listening there.

Three things happen before the editor starts:

1. Work out how many processors this session may use. An online session gets
   a share of a bigger machine. GROMACS left to itself counts every processor
   in that machine and starts a thread for each, and those threads then queue
   for the share this session is allowed, which makes a run many times slower.
2. Write the settings. GROMACS and Python are the ones installed in this
   environment, runs are kept in ~/.comfy-gmx-lite, and the setup questions
   the editor asks on a first start are marked as answered, since everything
   is installed already.
3. Start the editor on the port Jupyter gave, and tell it that Jupyter is the
   only way in (see the Shell tab, in main below).

    python3 binder/launch.py PORT
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def allowed_processors() -> int:
    """How many processors a simulation here may use, at least one."""
    # What JupyterHub or BinderHub says this session may use, when it says.
    try:
        limit = float(os.environ.get("CPU_LIMIT") or 0)
    except ValueError:
        limit = 0
    if limit > 0:
        return max(1, math.floor(limit))
    # The container's own limit. "max 100000" means none; "200000 100000"
    # means two processors' worth of time in every tenth of a second.
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            return max(1, math.floor(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    # The same limit on older systems, which keep it in two files.
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    # No limit: the processors this process may run on.
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return os.cpu_count() or 1


def write_settings(home: Path, threads: int) -> None:
    """Set what this environment decides, and leave anything else as it was."""
    path = home / "settings.json"
    try:
        settings = json.loads(path.read_text())
    except (OSError, ValueError):
        settings = {}
    settings.update({
        "data_dir": str(home),
        "gmxrc": "",            # gmx is on PATH already: it is in this environment
        "gmx_binary": "gmx",
        "setup_done": True,     # nothing to set up; it is all installed
    })
    # One process with as many threads as this session may use, and no
    # graphics card: an online session has none.
    settings["mdrun"] = {"ntomp": threads, "ntmpi": 1, "gpu_id": "", "extra": ""}
    home.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2))


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: launch.py PORT")
    port = sys.argv[1]
    home = Path(os.environ.get("COMFYGMX_HOME") or Path.home() / ".comfy-gmx-lite")
    threads = allowed_processors()
    write_settings(home, threads)
    print(f"Comfy-gmx lite: each simulation gets {threads} processor(s)", flush=True)

    # As run.sh does: a decimal comma from a non-English locale breaks the
    # reading of numbers downstream, and the log should appear as it is written.
    os.environ["LC_ALL"] = "C"
    os.environ["PYTHONUNBUFFERED"] = "1"
    # The Shell tab refuses a page opened at a name it does not know, such as
    # hub.2i2c.mybinder.org, to stop a trick that needs the browser and the
    # editor on the same computer. Here the editor listens only inside this
    # session and Jupyter lets nothing through without the session's token,
    # so that check is switched off. The check that refuses pages from other
    # websites stays on. (comfygmx/shell.py, behind_jupyter)
    os.environ["COMFYGMX_BEHIND_JUPYTER"] = "1"
    os.chdir(ROOT)
    os.execvp(sys.executable, [sys.executable, "-m", "comfygmx", "--data-dir", str(home),
                               "serve", "--port", port, "--no-browser"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
