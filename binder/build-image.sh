#!/usr/bin/env bash
# Build the online copy of Comfy-gmx lite on this machine, the way
# mybinder.org builds it: a Docker image, called comfy-gmx-lite unless you
# name another.
#
#   binder/build-image.sh                     build comfy-gmx-lite:latest
#   binder/build-image.sh comfy-gmx-lite:v2   build under another name
#   binder/try-image.sh                       then open it in a browser
#
# It builds from the files as they are in this folder now, saved or not.
#
# It needs Docker, and it uses repo2docker, the program Binder itself uses.
# The first time, it puts repo2docker -- and Docker's "buildx" add-on, if this
# Docker has none -- into a folder of their own and changes nothing else:
#   ~/.cache/comfy-gmx-lite-build   (or wherever COMFYGMX_BUILD_TOOLS says)
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
tools="${COMFYGMX_BUILD_TOOLS:-$HOME/.cache/comfy-gmx-lite-build}"
image="${1:-comfy-gmx-lite:latest}"
mkdir -p "$tools"

# repo2docker, in a Python environment of its own. tomli because repo2docker
# needs it on Python 3.10 and does not ask for it.
if [ ! -x "$tools/repo2docker/bin/repo2docker" ]; then
  echo "setting up repo2docker in $tools/repo2docker (once)"
  python3 -m venv "$tools/repo2docker"
  "$tools/repo2docker/bin/pip" install -q --upgrade pip
  "$tools/repo2docker/bin/pip" install -q jupyter-repo2docker tomli
fi

# repo2docker builds through Docker's buildx add-on, which Ubuntu's docker.io
# package leaves out. If it is missing, take it from conda-forge into the same
# folder, and show it to Docker for these builds only.
export DOCKER_CONFIG="$tools/docker"
mkdir -p "$DOCKER_CONFIG/cli-plugins"
if ! docker buildx version >/dev/null 2>&1; then
  if [ ! -x "$tools/buildx/bin/docker-buildx" ]; then
    conda=""
    for candidate in "${CONDA_EXE:-}" "$(command -v conda || true)" \
        "$HOME/miniconda3/bin/conda" "$HOME/miniforge3/bin/conda" \
        "$HOME/mambaforge/bin/conda" "$HOME/anaconda3/bin/conda"; do
      if [ -n "$candidate" ] && [ -x "$candidate" ]; then conda="$candidate"; break; fi
    done
    if [ -z "$conda" ]; then
      echo "Docker has no buildx add-on, and there is no conda here to fetch one with." >&2
      echo "Install it with your package manager (on Ubuntu: docker-buildx), then run this again." >&2
      exit 1
    fi
    echo "fetching Docker's buildx add-on from conda-forge into $tools/buildx (once)"
    "$conda" create -y -q -p "$tools/buildx" -c conda-forge --override-channels docker-buildx
  fi
  ln -sf "$tools/buildx/bin/docker-buildx" "$DOCKER_CONFIG/cli-plugins/docker-buildx"
fi

# repo2docker does not build at all when an image of the asked-for name is
# there already -- it says "Reusing existing image" and keeps the old one. So
# build under a name used only this once, then move the real name over to it.
# Parts that have not changed still come out of Docker's store of earlier
# builds, so a rebuild after a small change takes a minute or two.
# User 1000 called jovyan, as on mybinder.org, so that the image behaves there
# as it does here.
fresh="comfy-gmx-lite-build:$(date +%Y%m%d-%H%M%S)"
"$tools/repo2docker/bin/repo2docker" --no-run --image-name "$fresh" \
  --user-id 1000 --user-name jovyan "$repo"
docker tag "$fresh" "$image"
docker rmi "$fresh" >/dev/null
echo
echo "built $image -- now binder/try-image.sh $image"
