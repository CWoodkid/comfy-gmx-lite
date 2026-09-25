#!/usr/bin/env bash
# Start the Comfy-gmx server. No arguments needed; everything else is optional.
set -euo pipefail
cd "$(dirname "$0")"

# --help before anything else: a machine with no Python at all should still be
# able to find out what this does. Every one of these scripts answers it.
case "${1:-}" in
  -h|--help|help)
    cat <<'HELP'
run.sh — start the Comfy-gmx server

  ./run.sh                  open http://localhost:8189 in your browser
  ./run.sh --port 9000      somewhere else
  ./run.sh --host 0.0.0.0   listen on every interface (see the warning below)
  ./run.sh --no-browser     start it, do not open anything
  ./run.sh --data-dir DIR   keep runs, uploads and the settings under DIR

This starts the server and nothing else. It installs nothing, checks nothing
and asks nothing; if a tool is missing you find out in the Environments panel.
For a fresh clone use ./start.sh, which sets things up first.

The server runs commands on this machine as you, so --host is exactly as safe
as handing somebody a shell. Leave it on localhost unless you know why not.

Environment:
  COMFYGMX_PYTHON   the interpreter to use, if `python3` is not the one you want

Runs and settings live in ~/.comfy-gmx-lite unless you pass --data-dir.

Four scripts, and each one answers --help:

  ./start.sh    from a fresh clone: install what is missing, then open the editor
  ./run.sh      just start the server
  ./setup.sh    the setup questions on their own, without starting anything
  ./install.sh  optional: put a `comfy-gmx-lite` command on your PATH

When something is wrong, one more says what:

  ./tools/check_platform.sh  ten seconds: can this machine run it at all

Underneath them all is `python3 -m comfygmx`, which has more: `check` reports
which tools it can reach, `nodes` lists the node types, and `run` executes a
saved workflow with no browser at all.
HELP
    exit 0 ;;
esac

# A decimal comma from a non-English locale breaks float parsing downstream.
export LC_ALL=C
# so the startup banner appears immediately even when the output is redirected
export PYTHONUNBUFFERED=1

PYTHON="${COMFYGMX_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "no python interpreter found; set COMFYGMX_PYTHON to one" >&2
  exit 1
fi

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit("Comfy-gmx needs Python 3.9 or newer, found %d.%d" % sys.version_info[:2])
PY

exec "$PYTHON" -m comfygmx serve "$@"
