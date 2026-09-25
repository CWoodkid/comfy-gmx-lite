#!/usr/bin/env bash
# Start the online copy built by build-image.sh, as one person's session on
# mybinder.org would be: one processor and 2 GB of memory. It prints the
# address to open in a browser, and how to stop it again.
#
#   binder/try-image.sh                       comfy-gmx-lite:latest on port 8899
#   binder/try-image.sh comfy-gmx-lite:v2     another image
#   PORT=9000 binder/try-image.sh             another port
#   CPUS=2 binder/try-image.sh                two processors, as a JupyterHub
#                                             of your own might give each person
#   CPUSET=20 binder/try-image.sh             only processor 20 of this machine,
#                                             to keep clear of other work on it
#
# Only this computer can reach it (127.0.0.1). Stopping it throws away
# everything done inside, as a Binder session does when it ends.
set -euo pipefail

image="${1:-comfy-gmx-lite:latest}"
port="${PORT:-8899}"
name="comfy-gmx-lite-try"
# A password of sorts for this session: the address below carries it.
token="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"

if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
  echo "one is running already -- stop it first:  docker stop $name" >&2
  exit 1
fi
docker run --rm -d --name "$name" --cpus "${CPUS:-1}" \
  ${CPUSET:+--cpuset-cpus "$CPUSET"} --memory 2g -p "127.0.0.1:$port:8888" \
  "$image" jupyter lab --ip 0.0.0.0 --port 8888 --no-browser \
  --ServerApp.token="$token" >/dev/null

# Wait until Jupyter answers, so the address works when it is printed.
for _ in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$port/api/status?token=$token"; then break; fi
  sleep 1
done
echo "open:  http://127.0.0.1:$port/comfygmx/?token=$token"
echo "stop:  docker stop $name"
