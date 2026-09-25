#!/usr/bin/env python3
"""Run a real two-node graph, on whatever this machine is.

Deliberately uses nodes that need nothing installed: loading a structure is a
shell copy and cleaning it is a stdlib Python script. If this works, the parts
of Comfy-gmx that are Comfy-gmx work here, and everything left is a question
about the simulation tools rather than about the platform.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from comfygmx.config import Settings        # noqa: E402
from comfygmx.executor import Executor      # noqa: E402

TINY = textwrap.dedent("""\
    SEQRES   1 A    3  ALA GLY SER
    ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
    ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00  0.00           C
    ATOM      3  CA  GLY A   2       2.458   1.000   0.000  1.00  0.00           C
    HETATM    4  O   HOH A 101       9.000   9.000   9.000  1.00  0.00           O
    END
""")


def main() -> int:
    home = pathlib.Path(tempfile.mkdtemp(prefix="comfygmx-check-"))
    structure = home / "tiny.pdb"
    structure.write_text(TINY)
    settings_file = home / "settings.json"
    settings_file.write_text(json.dumps({"data_dir": str(home / "data")}))

    graph = {
        "nodes": [
            {"id": "load", "type": "io.structure", "params": {"path": str(structure)}},
            {"id": "clean", "type": "prep.clean", "params": {"drop_water": True}},
        ],
        "links": [{"from_node": "load", "from_port": "structure",
                   "to_node": "clean", "to_port": "structure"}],
    }

    run = Executor(Settings(settings_file)).start(graph, session="check")
    run.thread.join(timeout=180)
    print(f"  run {run.status} in {home}")
    for state in run.nodes.values():
        print("    %-6s %-9s %s" % (state.id, state.status, state.error or ""))

    produced = pathlib.Path(run.nodes["clean"].workdir) / "clean.pdb"
    if run.status != "done" or not produced.is_file():
        return 1
    text = produced.read_text()
    kept = sum(1 for line in text.splitlines() if line.startswith("ATOM"))
    print(f"    clean.pdb: {kept} atoms kept, water dropped: {'HOH' not in text}")
    return 0 if kept == 3 and "HOH" not in text else 1


if __name__ == "__main__":
    raise SystemExit(main())
