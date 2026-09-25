#!/usr/bin/env bash
# Does Comfy-gmx work on this machine? Run it and paste the last block back.
#
#   ./tools/check_platform.sh
#
# Nothing is installed and nothing is changed. It reports what is here, runs a
# real two-node graph through the executor, and starts the server for four
# seconds to see whether it answers.
set -u
cd "$(dirname "$0")/.."
export LC_ALL=C

PYTHON="${COMFYGMX_PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi

pass=0; warn=0; fail=0
note() { printf '  %-9s %s\n' "$1" "$2"; }
ok()   { note "ok"   "$1"; pass=$((pass + 1)); }
soft() { note "note" "$1"; warn=$((warn + 1)); }
bad()  { note "FAIL" "$1"; fail=$((fail + 1)); }

echo "== the machine =="
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  note "distro" "${PRETTY_NAME:-$NAME} (${ID}${ID_LIKE:+, like $ID_LIKE})"
fi
note "kernel" "$(uname -srm)"
note "shell"  "${BASH_VERSION:-unknown} at ${BASH:-$(command -v bash)}"
note "locale" "LANG=${LANG:-unset} LC_NUMERIC=${LC_NUMERIC:-unset}"

echo
echo "== Python =="
if [ -z "$PYTHON" ]; then
  bad "no python3 on PATH -- nothing here can run"
else
  note "python" "$($PYTHON -V 2>&1) at $(command -v "$PYTHON")"
  if "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    ok "3.9 or newer, which is all this needs"
  else
    bad "older than 3.9 -- pyproject asks for >=3.9"
  fi
  if "$PYTHON" -c 'import sys; sys.path.insert(0, "."); import comfygmx.registry' 2>/dev/null; then
    ok "comfygmx imports"
  else
    bad "comfygmx does not import -- run this from the repository"
  fi
fi

echo
echo "== commands the generated scripts use =="
need() {
  local tool="$1" why="$2"
  if command -v "$tool" >/dev/null 2>&1; then ok "$tool -- $why"
  else bad "$tool is missing -- $why"; fi
}
want() {
  local tool="$1" why="$2"
  if command -v "$tool" >/dev/null 2>&1; then ok "$tool -- $why"
  else soft "$tool is missing -- $why"; fi
}
need bash   "every node runs a bash script"
need curl   "fetching from RCSB and OPM, and the GROMACS tarball"
need tar    "unpacking archives and the GROMACS source"
need sed    "used by several generated scripts"
need awk    "used by the conda environment check"
for tool in wc cp ln head tail sort cut chmod mktemp grep; do
  need "$tool" "coreutils"
done
want nice   "runs are niced so they do not fight your desktop"
want ionice "Linux only; the script checks for it before using it"

echo
echo "== optional, only for what uses them =="
want conda  "installing tools into environments -- ./start.sh installs it for you"
want gmx    "GROMACS itself -- or point the GMXRC at a build in Settings"
for tool in cmake make g++ gcc; do
  want "$tool" "only needed to build GROMACS from source"
done

echo
echo "== a real graph through the executor =="
if [ -n "$PYTHON" ]; then
  if "$PYTHON" tools/check_platform.py; then ok "a two-node run finished and produced its file"
  else bad "the run did not finish -- the output above says where it stopped"; fi
else
  bad "skipped: no python"
fi

echo
echo "== the server =="
if [ -n "$PYTHON" ]; then
  port=8${RANDOM:0:3}
  [ "$port" -lt 8100 ] && port=8765
  "$PYTHON" -m comfygmx serve --port "$port" >/tmp/comfygmx-check.log 2>&1 &
  server=$!
  sleep 4
  code=$(curl -s -m 5 -o /tmp/comfygmx-nodes.json -w '%{http_code}' "http://127.0.0.1:$port/api/nodes" 2>/dev/null)
  page=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/" 2>/dev/null)
  kill "$server" 2>/dev/null
  wait "$server" 2>/dev/null
  if [ "$code" = "200" ] && [ "$page" = "200" ]; then
    count=$("$PYTHON" -c "
import json
d = json.load(open('/tmp/comfygmx-nodes.json'))
print(sum(len(c['nodes']) for c in d['categories']))" 2>/dev/null || echo '?')
    ok "served the editor and $count node types on port $port"
  else
    bad "the server did not answer (api $code, page $page) -- see /tmp/comfygmx-check.log"
  fi
fi

echo
echo "======================================================================"
echo "  Comfy-gmx platform check: $pass ok, $warn note(s), $fail failure(s)"
if [ "$fail" -eq 0 ]; then
  echo "  Nothing is in the way. Notes above are optional pieces, not problems."
  [ "$warn" -gt 0 ] && echo "  ./start.sh installs the missing optional pieces for you."
else
  echo "  The FAIL lines are what to fix; everything else is fine."
fi
echo "  $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}") · $($PYTHON -V 2>&1)"
echo "======================================================================"
[ "$fail" -eq 0 ]
