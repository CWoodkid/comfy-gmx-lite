#!/usr/bin/env bash
# One command, from a fresh clone to a working editor.
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-}" in
  -h|--help|help)
    cat <<'HELP'
start.sh — from a fresh clone to a working editor, in one command

  ./start.sh                first run: install what is missing, then start
  ./start.sh --setup        ask the setup questions again
  ./start.sh --no-setup     skip the check and start straight away
  ./start.sh --port 9000    anything else goes to the server: see ./run.sh --help
  ./start.sh --data-dir DIR keep runs, uploads and the settings under DIR

After the first run this costs one settings-file read and starts immediately,
so it is the one to use every day.

Nothing here needs root. Where a system package is missing it prints the line
for your distribution rather than running it, so the password prompt lands in a
terminal you are looking at rather than behind a button.

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
export PYTHONUNBUFFERED=1

SETUP="if-needed"
ARGS=()
# --data-dir has to reach the setup step as well as the server, or the two
# halves of this script read and write two different settings files.
DATA_DIR=()
expect_dir=0
for arg in "$@"; do
  if [ "$expect_dir" = 1 ]; then
    expect_dir=0; DATA_DIR=(--data-dir "$arg"); ARGS+=("$arg"); continue
  fi
  case "$arg" in
    --setup)      SETUP="always" ;;
    --no-setup)   SETUP="never" ;;
    --data-dir)   expect_dir=1; ARGS+=("$arg") ;;
    --data-dir=*) DATA_DIR=("$arg"); ARGS+=("$arg") ;;
    *)            ARGS+=("$arg") ;;
  esac
done

# What this system calls Python, for the one message that cannot use Python.
python_hint() {
  (
    id=""; like=""
    if [ -r /etc/os-release ]; then . /etc/os-release; id="${ID:-}"; like="${ID_LIKE:-}"; fi
    case " $id $like " in
      *arch*|*cachyos*)             echo "sudo pacman -S --needed python" ;;
      *debian*|*ubuntu*)            echo "sudo apt-get install -y python3" ;;
      *fedora*|*rhel*|*centos*)     echo "sudo dnf install -y python3" ;;
      *suse*)                       echo "sudo zypper install -y python3" ;;
      *alpine*)                     echo "sudo apk add python3" ;;
      *)  if [ "$(uname -s)" = "Darwin" ]; then echo "brew install python"
          else echo "install Python 3.9 or newer from your package manager"; fi ;;
    esac
  )
}

PYTHON="${COMFYGMX_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "Comfy-gmx needs Python 3.9 or newer, and this machine has none." >&2
  echo "  $(python_hint)" >&2
  echo "Then run ./start.sh again." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "Comfy-gmx needs Python 3.9 or newer; $PYTHON is $("$PYTHON" -V 2>&1)." >&2
  echo "  $(python_hint)" >&2
  exit 1
fi

case "$SETUP" in
  if-needed) "$PYTHON" -m comfygmx setup --if-needed ${DATA_DIR[@]+"${DATA_DIR[@]}"} || true ;;
  always)    "$PYTHON" -m comfygmx setup ${DATA_DIR[@]+"${DATA_DIR[@]}"} || true ;;
esac

exec "$PYTHON" -m comfygmx serve ${ARGS[@]+"${ARGS[@]}"}
