#!/usr/bin/env bash
# Optional convenience installer.
set -euo pipefail
cd "$(dirname "$0")"
export LC_ALL=C

case "${1:-}" in
  -h|--help|help)
    cat <<'HELP'
install.sh — put a `comfy-gmx-lite` command on your PATH

  ./install.sh

Optional, and it is worth saying why: Comfy-gmx has no Python dependencies, so
./run.sh works straight from a clone and nothing here is needed to use it. This
script does two things -- `pip install --user -e .`, so `comfy-gmx-lite` works from
any directory, and a report of which simulation tools it can already see.

It is the one place anything uses the *system* pip. Every tool install runs the
pip inside its own conda environment instead. On a distribution that ships
Python without pip, or marks the interpreter externally managed (PEP 668), this
says which it hit and stops -- ./start.sh needs none of it.

To set the simulation tools up, use ./setup.sh; to start without installing
anything, ./run.sh.

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

PYTHON="${COMFYGMX_PYTHON:-python3}"

echo "== installing the comfy-gmx-lite command =="
# The only place anything here uses the *system* pip. Every tool install runs
# pip from inside a conda environment, which brings its own. Distributions have
# started shipping Python without pip (Arch) and marking the interpreter
# externally managed under PEP 668 (Arch, Debian 12+, Fedora 38+), so this says
# which it hit rather than letting pip's own message do the explaining.
if ! "$PYTHON" -c "import pip" >/dev/null 2>&1; then
  echo "This needs pip, and $PYTHON has none." >&2
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    case " $(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}") " in
      *arch*|*cachyos*)         echo "  sudo pacman -S --needed python-pip" >&2 ;;
      *debian*|*ubuntu*)        echo "  sudo apt-get install -y python3-pip" >&2 ;;
      *fedora*|*rhel*|*centos*) echo "  sudo dnf install -y python3-pip" >&2 ;;
      *suse*)                   echo "  sudo zypper install -y python3-pip" >&2 ;;
      *alpine*)                 echo "  sudo apk add py3-pip" >&2 ;;
    esac
  fi
  echo >&2
  echo "Nothing else needs it: ./start.sh and ./run.sh work without pip, and" >&2
  echo "every tool install uses the pip inside its own conda environment." >&2
  echo "This script only puts a 'comfy-gmx-lite' command on your PATH." >&2
  exit 1
fi
if ! "$PYTHON" -m pip install --user -e . 2>&1 | tee /tmp/comfygmx-pip.$$; then
  if grep -q "externally-managed-environment" /tmp/comfygmx-pip.$$; then
    echo >&2
    echo "This Python is marked externally managed (PEP 668), so pip will not" >&2
    echo "install into it. Either use a virtual environment, or skip this" >&2
    echo "script entirely -- ./start.sh needs none of it." >&2
  fi
  rm -f /tmp/comfygmx-pip.$$
  exit 1
fi
rm -f /tmp/comfygmx-pip.$$

echo
echo "== checking the simulation tools =="
"$PYTHON" -m comfygmx check || true

cat <<'MSG'

Nothing above needs to be green to start. Open the Environments panel in the
browser to point each tool at an existing installation, or to have Comfy-gmx
build a conda environment for it.

  ./run.sh
MSG
