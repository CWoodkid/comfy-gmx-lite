"""Tell Jupyter how to start the Comfy-gmx editor.

jupyter-server-proxy calls server() when the Jupyter server starts and
registers what it returns under the name given in pyproject.toml, "comfygmx".
The first time somebody opens <session address>/comfygmx/, it runs the command
with a free port in place of {port}, waits until the editor answers there, and
from then on passes that address through to it.
"""

import os
import sys
from pathlib import Path


def server() -> dict:
    # Where repo2docker put this repository: $REPO_DIR, which is the home
    # folder unless the image was built with a different target.
    repo = Path(os.environ.get("REPO_DIR") or Path.home())
    return {
        "command": [sys.executable, str(repo / "binder" / "launch.py"), "{port}"],
        # The editor starts in a second or two; a busy machine gets two minutes.
        "timeout": 120,
        "launcher_entry": {"enabled": True, "title": "Comfy-gmx lite"},
    }
