#!/usr/bin/env bash
# The setup questions, on their own.
#
# ./start.sh runs this before opening the editor, and skips it once it has been
# answered. This is the same thing without the editor: for setting a machine up
# over ssh, for a second machine, or for answering the questions again after
# installing conda somewhere new.
set -euo pipefail
cd "$(dirname "$0")"

# A decimal comma from a non-English locale breaks float parsing downstream.
export LC_ALL=C
export PYTHONUNBUFFERED=1

case "${1:-}" in
  -h|--help|help)
    cat <<'HELP'
setup.sh — install what this machine is missing, and answer nothing twice

  ./setup.sh                ask what is missing and offer to install it
  ./setup.sh --if-needed    do nothing if it has been answered before
  ./setup.sh --check        report what is reachable and change nothing
  ./setup.sh --dry-run      print the script it would run, and run nothing
  ./setup.sh --yes          take every default without asking

Anything else goes straight to `python3 -m comfygmx setup`, which also has
--tools, --no-tools, --with-system and --init-shell; see its own --help.

It finds conda (or offers to put one in your home directory), then installs
each simulation tool into its own environment. Your shell startup files are
left alone: Comfy-gmx reaches that conda directly rather than through your
PATH.

It never asks for your password. Where a system package needs root -- a
compiler, cmake -- it prints the line for your distribution instead, to paste
into a terminal where you can see the prompt.

Nothing here is required. Every one of these choices can be made later in the
Environments panel, and a tool you never use never has to be installed.

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

PYTHON="${COMFYGMX_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "Comfy-gmx needs Python 3.9 or newer, and this machine has none." >&2
  exit 1
fi

# --check is the read-only one, and it is a different subcommand rather than a
# flag on setup: "tell me what is here" and "install what is not" are not the
# same question, and only one of them should ever write anything.
if [ "${1:-}" = "--check" ]; then
  exec "$PYTHON" -m comfygmx check
fi
exec "$PYTHON" -m comfygmx setup "$@"
