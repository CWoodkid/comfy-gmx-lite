"""First run: what this machine is, what is missing, and how to get it here.

A clone and one command should end at a working editor, on a machine with
nothing installed and a user who does not want to read an install guide first.
That is the whole job of this module.

There are three kinds of missing thing here and they are not interchangeable:

* **System packages** -- a compiler, ``cmake``, ``curl``. These come from the
  distribution's package manager, and that needs root.  Nothing here runs
  ``sudo`` behind a browser button: the password prompt would go to a terminal
  nobody is looking at, and a build that hangs forever on an invisible prompt is
  worse than one that never started.  The exact line is printed instead, to be
  run where the prompt is visible.
* **conda** -- goes into the user's home directory and needs no root at all,
  which is precisely why it *can* be a button.  Miniforge rather than Miniconda:
  its default channel is conda-forge, which is where every tool in the catalogue
  comes from anyway, and it carries none of the Anaconda licence question that a
  university-sized organisation would otherwise have to answer.
* **Tools** -- GROMACS and the rest, into conda environments.  Already handled
  by :meth:`Toolbox.install_script`; this only decides which to ask for, in what
  order, and skips the ones already here.

The OS-specific part is deliberately shallow: a family, a package manager, and a
table of package names.  Nothing else in Comfy-gmx contains an ``apt``, a ``dnf``
or a ``pacman`` -- this module is the one place allowed to know they exist, so
adding a distribution is one row in one table rather than a hunt.
"""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings, detect_conda_root
from .environments import CATALOG, Toolbox, env_name_for
from .runner import _heredoc

#: Where conda goes when we install it.  The conventional location, so a conda
#: installed here is one a user's own tooling will also find.
MINIFORGE_HOME = Path.home() / "miniforge3"

MINIFORGE_URL = "https://github.com/conda-forge/miniforge/releases/latest/download"

#: Where a rootless cmake goes. Its own environment rather than base, so it
#: can be deleted again from the Environments panel without taking conda
#: with it, and so nothing else acquires a cmake by accident.
BUILD_ENV = "comfygmx-build"


# --------------------------------------------------------------------------
# What this machine is
# --------------------------------------------------------------------------

#: Distribution id (or anything in ID_LIKE) -> family.  The families are what
#: the package tables are keyed on; the point of ID_LIKE is that a derivative
#: nobody has heard of still lands somewhere sensible.
_FAMILIES: Dict[str, str] = {}
for _family, _ids in {
    "arch": ("arch", "archlinux", "cachyos", "endeavouros", "manjaro", "garuda",
             "artix", "arcolinux", "steamos"),
    "debian": ("debian", "ubuntu", "linuxmint", "pop", "elementary", "raspbian",
               "zorin", "kali", "devuan", "mx"),
    "rhel": ("rhel", "fedora", "centos", "rocky", "almalinux", "ol", "oracle",
             "amzn", "scientific"),
    "suse": ("suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed", "sles",
             "sled"),
    "alpine": ("alpine",),
    "gentoo": ("gentoo", "funtoo"),
    "void": ("void",),
}.items():
    for _id in _ids:
        _FAMILIES[_id] = _family

#: family -> (manager binary, install verb, refresh command, needs root)
_MANAGERS: Dict[str, tuple] = {
    "arch": ("pacman", "pacman -S --needed --noconfirm", "", True),
    "debian": ("apt-get", "apt-get install -y", "apt-get update", True),
    "rhel": ("dnf", "dnf install -y", "", True),
    "suse": ("zypper", "zypper --non-interactive install", "", True),
    "alpine": ("apk", "apk add", "", True),
    "gentoo": ("emerge", "emerge --noreplace", "", True),
    "void": ("xbps-install", "xbps-install -Sy", "", True),
    # Homebrew refuses to run as root, and says so loudly. Never sudo this one.
    "macos": ("brew", "brew install", "", False),
}

#: What each requirement is called in each family.  Empty means "this family
#: has no package for it", which is not the same as "not needed".
_PACKAGES: Dict[str, Dict[str, List[str]]] = {
    "curl": {
        "arch": ["curl"], "debian": ["curl"], "rhel": ["curl"], "suse": ["curl"],
        "alpine": ["curl"], "gentoo": ["net-misc/curl"], "void": ["curl"],
        "macos": ["curl"],
    },
    "tar": {
        "arch": ["tar"], "debian": ["tar"], "rhel": ["tar"], "suse": ["tar"],
        "alpine": ["tar"], "gentoo": ["app-arch/tar"], "void": ["tar"],
        "macos": [],
    },
    "git": {
        "arch": ["git"], "debian": ["git"], "rhel": ["git"], "suse": ["git"],
        "alpine": ["git"], "gentoo": ["dev-vcs/git"], "void": ["git"],
        "macos": ["git"],
    },
    "python": {
        "arch": ["python"], "debian": ["python3"], "rhel": ["python3"],
        "suse": ["python3"], "alpine": ["python3"], "gentoo": ["dev-lang/python"],
        "void": ["python3"], "macos": ["python"],
    },
    "cmake": {
        "arch": ["cmake"], "debian": ["cmake"], "rhel": ["cmake"], "suse": ["cmake"],
        "alpine": ["cmake"], "gentoo": ["dev-build/cmake"], "void": ["cmake"],
        "macos": ["cmake"],
    },
    "toolchain": {
        "arch": ["base-devel"], "debian": ["build-essential"],
        "rhel": ["gcc", "gcc-c++", "make"], "suse": ["gcc", "gcc-c++", "make"],
        "alpine": ["build-base"], "gentoo": [], "void": ["base-devel"],
        # Apple ships the compiler through the command line tools, not brew.
        "macos": [],
    },
}


def _os_release() -> Dict[str, str]:
    """``/etc/os-release`` as a dict, or empty on anything that lacks it."""
    data: Dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            text = Path(path).read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            data[key.strip()] = value.strip().strip('"').strip("'")
        if data:
            break
    return data


def _family_of(release: Dict[str, str]) -> str:
    """Which package-manager family this distribution belongs to."""
    distro = (release.get("ID") or "").strip().lower()
    if distro in _FAMILIES:
        return _FAMILIES[distro]
    # ID_LIKE is a space-separated list, most-similar first: "cachyos arch" or
    # "rhel centos fedora". The first one recognised wins.
    for token in (release.get("ID_LIKE") or "").lower().split():
        if token in _FAMILIES:
            return _FAMILIES[token]
    return ""


def detect() -> Dict[str, Any]:
    """Everything about this machine that changes what the setup should do."""
    system = platform.system().lower()          # linux / darwin / windows
    release = _os_release() if system == "linux" else {}
    if system == "darwin":
        family = "macos"
        pretty = f"macOS {platform.mac_ver()[0]}".strip()
        distro = "macos"
    else:
        family = _family_of(release)
        distro = (release.get("ID") or system or "unknown").lower()
        pretty = release.get("PRETTY_NAME") or release.get("NAME") or system.title()

    manager, install, refresh, needs_root = _MANAGERS.get(family, ("", "", "", True))
    # A family's manager is only useful if it is actually installed. Homebrew in
    # particular is not there by default, and claiming otherwise would print a
    # command that cannot run.
    have_manager = bool(manager and shutil.which(manager))

    # Root already: everything below is doable without asking for a password.
    root_now = hasattr(os, "geteuid") and os.geteuid() == 0

    wsl = False
    if system == "linux":
        try:
            wsl = "microsoft" in Path("/proc/version").read_text(errors="replace").lower()
        except OSError:
            wsl = False

    return {
        "system": system,
        "distro": distro,
        "pretty": pretty,
        "version": release.get("VERSION_ID", ""),
        "family": family,
        "machine": platform.machine(),
        "kernel": platform.release(),
        "manager": manager if have_manager else "",
        "manager_expected": manager,
        "install_cmd": install if have_manager else "",
        "refresh_cmd": refresh if have_manager else "",
        "needs_sudo": bool(needs_root) and not root_now,
        "wsl": wsl,
        "python": platform.python_version(),
        "python_path": sys.executable,
        "supported": system in ("linux", "darwin"),
    }


def system_command(plat: Dict[str, Any], packages: List[str]) -> str:
    """The one line that installs these packages here, sudo included if needed."""
    if not packages or not plat.get("install_cmd"):
        return ""
    sudo = "sudo " if plat.get("needs_sudo") else ""
    body = f"{sudo}{plat['install_cmd']} " + " ".join(packages)
    if plat.get("refresh_cmd"):
        body = f"{sudo}{plat['refresh_cmd']} && {body}"
    return body


# --------------------------------------------------------------------------
# What is missing
# --------------------------------------------------------------------------

#: id, display name, why it is wanted, the commands that prove it is here,
#: and whether the app is unusable without it.
_REQUIREMENTS = [
    ("curl", "curl", "downloads structures from RCSB, and every installer below",
     ["curl"], True),
    ("tar", "tar", "unpacks the archives those downloads arrive in", ["tar"], True),
    ("conda", "conda", "installs extra programs into environments of their own; "
     "the two tutorials need none", [], False),
    ("toolchain", "compiler", "only to build GROMACS from source",
     ["gcc", "g++", "make"], False),
    ("cmake", "cmake", "only to build GROMACS from source", ["cmake"], False),
    ("git", "git", "only to update Comfy-gmx itself", ["git"], False),
]


def _conda_status(settings: Settings) -> Dict[str, Any]:
    root = detect_conda_root(settings)
    if root and (Path(root) / "etc" / "profile.d" / "conda.sh").exists():
        return {"present": True, "root": root, "detail": root}
    if (MINIFORGE_HOME / "bin" / "conda").exists():
        # Installed, but nothing has told the settings about it yet.
        return {"present": True, "root": str(MINIFORGE_HOME), "detail": str(MINIFORGE_HOME),
                "unregistered": True}
    return {"present": False, "root": "", "detail": ""}


def _tool_status(box: Toolbox, tool_id: str) -> Dict[str, Any]:
    """Where this tool is, without spawning anything.

    On-disk only.  The Environments panel does the real probing -- running each
    tool's version check inside its environment -- and that is seconds per tool.
    First-run setup only needs to know whether to offer to install it.
    """
    spec = CATALOG[tool_id]
    # A tool that *is* a checkout is not installed until the checkout is there,
    # however complete its environment looks. Without this the installer sees
    # the environment, decides there is nothing to do, and the Environments
    # panel goes on reporting the tool as missing -- the two disagreeing about
    # the same tool, with no way to act on either.
    if spec.repo:
        source = box.settings.source_dir(tool_id)
        marker = spec.repo_marker
        if not source.is_dir() or (marker and not (source / marker).exists()):
            return {"present": False, "where": ""}
    if tool_id == "gmx":
        # The build a run will use, by the rule the runs follow: the GMXRC
        # saved in Settings, or else the gmx on the command path. Not the
        # first build found on disk: with several on one machine that is a
        # different answer, and it was the one named here while the runs
        # used another.
        use = box.gromacs_in_use()
        status = {"present": bool(use["path"]), "where": use["path"],
                  "version": use["version"], "how": use["how"]}
        if not use["path"]:
            # Builds on disk that no run would use: what to point Settings at.
            status["found"] = [{"version": build["version"], "path": build["path"]}
                               for build in box.gmxrc_candidates()]
        return status
    installs = box.installs_of(tool_id)
    live = [i for i in installs if not i.get("gone")]
    if live:
        return {"present": True, "where": f"conda environment {live[0]['env']}"}
    command = shlex.split(spec.command)[0] if spec.command else tool_id
    where = shutil.which(command) if command else ""
    if not where and spec.kind == "python" and command == "python":
        # What the runs will use instead where there is no "python", as on
        # Debian and Ubuntu: see Toolbox.resolve.
        where = shutil.which("python3") or ""
    if where:
        return {"present": True, "where": where}
    return {"present": False, "where": ""}


#: Ticked by default in the setup dialog.  Nothing, in this version: the two
#: tutorials need GROMACS and a Python with numpy, and nothing else, and a
#: first run should not spend twenty minutes installing things nobody asked for.
#:
#: GROMACS is not here, and not because it is optional -- nothing runs without
#: it. It has no conda route any more, so getting it means a source build:
#: forty minutes, and flags that matter (GPU backend, MPI, SIMD). That belongs
#: in its own dialog where those are chosen, not behind one button that starts
#: compiling.
DEFAULT_TOOLS: List[str] = []


def survey(settings: Settings) -> Dict[str, Any]:
    """The machine, what it is missing, and what could be done about it."""
    plat = detect()
    box = Toolbox(settings)
    conda = _conda_status(settings)

    requirements: List[Dict[str, Any]] = []
    for req_id, name, why, commands, essential in _REQUIREMENTS:
        if req_id == "conda":
            present, detail = conda["present"], conda["detail"]
        else:
            found = [shutil.which(c) for c in commands]
            present = all(found)
            detail = next((f for f in found if f), "") or ""
        packages = _PACKAGES.get(req_id, {}).get(plat["family"], [])
        entry: Dict[str, Any] = {
            "id": req_id,
            "name": name,
            "why": why,
            "essential": essential,
            "present": present,
            "detail": detail,
            "kind": "conda" if req_id == "conda" else "system",
            "sudo": req_id != "conda" and bool(plat["needs_sudo"]),
            "command": "" if req_id == "conda" else system_command(plat, packages),
            "packages": packages,
        }
        if req_id == "toolchain" and plat["family"] == "macos" and not present:
            # There is no brew formula for Apple's own compiler.
            entry["command"] = "xcode-select --install"
            entry["sudo"] = False
        requirements.append(entry)

    tools: List[Dict[str, Any]] = []
    for tool_id, spec in CATALOG.items():
        if tool_id == "shell":
            continue
        status = _tool_status(box, tool_id)
        tools.append({
            "id": tool_id,
            "name": spec.name,
            "description": spec.description,
            "optional": spec.optional,
            "licence_key": spec.licence_key,
            "suggested_env": env_name_for(spec) if spec.conda_installable else "",
            "present": status["present"],
            "where": status["where"],
            # GROMACS only, for now: its version, whether a run finds it
            # through Settings or on the command path, and -- when a run would
            # find none -- the builds on disk that Settings could point at.
            "version": status.get("version", ""),
            "how": status.get("how", ""),
            "found": status.get("found", []),
            "default": tool_id in DEFAULT_TOOLS and not status["present"],
            # Not everything is a checkbox. GROMACS is a source build, which is
            # its own dialog with its own choices.
            "conda_installable": spec.conda_installable,
            "install_hint": spec.install_hint,
        })

    blocking = [r for r in requirements if r["essential"] and not r["present"]]
    missing_tools = [t for t in tools if not t["optional"] and not t["present"]]
    for tool in missing_tools:
        if not tool["conda_installable"]:
            blocking.append({"id": tool["id"]})
    return {
        "platform": plat,
        "requirements": requirements,
        "tools": tools,
        "conda": conda,
        "miniforge_home": str(MINIFORGE_HOME),
        # "Ready" means a graph could actually run: conda and curl are here and
        # GROMACS exists somewhere. Not "nothing is missing" -- most of the
        # catalogue is optional and always will be.
        "ready": not blocking and not missing_tools,
        "blocking": [r["id"] for r in blocking],
        "first_run": bool(settings.get("setup_done")) is False,
    }


# --------------------------------------------------------------------------
# Doing something about it
# --------------------------------------------------------------------------

def miniforge_script(target: Optional[Path] = None, init_shell: bool = False) -> str:
    """Install conda into the user's home.  No root, no shell files touched.

    Miniforge rather than Miniconda, for two reasons that both matter here: its
    default channel is conda-forge, which is where every package in the
    catalogue lives, and it does not carry Anaconda's commercial licence terms,
    which a university department would otherwise have to think about.
    """
    target = Path(target or MINIFORGE_HOME)
    lines = [
        "set -euo pipefail",
        "export LC_ALL=C",
        f'target={shlex.quote(str(target))}',
        'if [ -x "$target/bin/conda" ]; then',
        '  echo ">> conda is already installed at $target"',
        "  exit 0",
        "fi",
        "if command -v conda >/dev/null 2>&1; then",
        '  echo ">> conda is already on PATH at $(command -v conda)"',
        "  exit 0",
        "fi",
        'kernel=$(uname -s); machine=$(uname -m)',
        'tmp=$(mktemp -d)',
        "trap 'rm -rf \"$tmp\"' EXIT",
        # Miniforge names its assets after `uname -s`/`uname -m`, except that
        # older macOS assets say MacOSX where uname says Darwin. Trying both
        # costs one 404 and only on a Mac.
        'names="Miniforge3-${kernel}-${machine}.sh"',
        'if [ "$kernel" = "Darwin" ]; then names="$names Miniforge3-MacOSX-${machine}.sh"; fi',
        "got=",
        "for name in $names; do",
        '  echo ">> fetching $name"',
        f'  if curl -fL --retry 3 --retry-delay 2 -o "$tmp/miniforge.sh" '
        f'"{MINIFORGE_URL}/$name"; then got="$name"; break; fi',
        "done",
        'if [ -z "$got" ]; then',
        '  echo ">> no Miniforge build exists for ${kernel}-${machine}." >&2',
        '  echo ">> install conda yourself and point Settings at it." >&2',
        "  exit 1",
        "fi",
        'echo ">> installing into $target -- a couple of minutes"',
        'bash "$tmp/miniforge.sh" -b -p "$target"',
        '"$target/bin/conda" --version',
    ]
    if init_shell:
        lines += [
            'echo ">> adding conda to your shell startup"',
            '"$target/bin/conda" init bash || true',
            'if [ -n "${ZSH_VERSION:-}" ] || [ -x /bin/zsh ]; then '
            '"$target/bin/conda" init zsh || true; fi',
        ]
    else:
        lines.append(
            'echo ">> your shell startup files were left alone; '
            'Comfy-gmx sources this conda directly"')
    lines.append('echo ">> conda ready at $target"')
    return "\n".join(lines)


def _cmake_script(conda_root: str) -> str:
    """cmake from conda-forge, into its own environment, without root.

    Deliberately not into base: an environment can be deleted again from the
    panel, and nothing else picks up a cmake it did not ask for.
    """
    hook = Path(conda_root) / "etc" / "profile.d" / "conda.sh"
    return "\n".join([
        "set -euo pipefail",
        "export LC_ALL=C",
        f'source "{hook}"',
        f'if [ -x "{Path(conda_root) / "envs" / BUILD_ENV / "bin" / "cmake"}" ]; then',
        f'  echo ">> cmake is already in {BUILD_ENV}"',
        "  exit 0",
        "fi",
        f'echo ">> installing cmake into the {BUILD_ENV} environment (no root needed)"',
        f"conda create -y -n {BUILD_ENV} -c conda-forge cmake",
        f"conda activate {BUILD_ENV}",
        "cmake --version | head -n 1",
        f'echo ">> cmake ready; the GROMACS build will find it in {BUILD_ENV}"',
    ])


def plan(settings: Settings, choices: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What first-run setup would do, as steps and as one runnable script.

    Everything in the returned script runs as the user.  Anything needing root
    comes back in ``sudo_commands`` as text to run in a terminal, because a
    password prompt behind a web button has nowhere to appear.
    """
    choices = dict(choices or {})
    state = survey(settings)
    plat = state["platform"]
    wanted_tools = choices.get("tools")
    if wanted_tools is None:
        wanted_tools = [t["id"] for t in state["tools"] if t["default"]]
    wanted_tools = [t for t in wanted_tools if t in CATALOG and t != "shell"]

    steps: List[Dict[str, Any]] = []
    notes: List[str] = []
    sudo_commands: List[Dict[str, str]] = []

    # GROMACS has no conda route, so the build toolchain stopped being optional
    # the moment GROMACS went missing: it is the only way to get the one thing
    # nothing runs without. When GROMACS is already here they go back to being
    # what they were, things you only need if you want to build another one.
    gmx = next((tool for tool in state["tools"] if tool["id"] == "gmx"), None)
    build_needed = set()
    if gmx and not gmx["present"]:
        build_needed = {"cmake", "toolchain"}

    # 1. System packages -- reported, never run for the user.
    for req in state["requirements"]:
        if req["present"] or req["kind"] != "system":
            continue
        if not req["command"]:
            notes.append(
                f"{req['name']} is missing and this does not know how to install it on "
                f"{plat['pretty']} — install it with whatever this system uses.")
            continue
        wanted = (req["essential"] or req["id"] in build_needed
                  or req["id"] in (choices.get("system") or []))
        if not wanted:
            continue
        why = req["why"]
        if req["id"] in build_needed:
            why = ("needed to build GROMACS, which is the only way to get it and "
                   "the one thing nothing runs without")
        sudo_commands.append({
            "id": req["id"], "name": req["name"], "why": why,
            "command": req["command"],
        })

    # 2. conda, which needs no root and so can simply be done. This version
    # needs it only as a place to put things: a tool that lives in an
    # environment, or cmake for a GROMACS build on a machine that has none.
    # The two tutorials need neither, so without one of those conda is not
    # installed unless somebody asks for it.
    conda_root = state["conda"]["root"] or str(MINIFORGE_HOME)
    short = {req["id"] for req in state["requirements"]
             if req["kind"] == "system" and not req["present"]}
    conda_wanted = bool(wanted_tools) or bool(build_needed and short == {"cmake"})
    if not state["conda"]["present"] and choices.get("conda", conda_wanted):
        steps.append({
            "id": "conda",
            "name": "conda (Miniforge)",
            "detail": f"into {conda_root} — 120 MB to download, 700 MB on disk",
            "script": miniforge_script(Path(conda_root), bool(choices.get("init_shell"))),
        })
    elif state["conda"].get("unregistered"):
        notes.append(f"conda was found at {conda_root} and will be remembered.")

    # 2b. cmake without root, when that is all the build is short of.
    #
    # This is the difference between ./start.sh leaving a machine that can
    # build GROMACS and one that cannot. The system package needs a password
    # nobody can be asked for here; conda is about to exist anyway and needs
    # none. The build script looks inside environments and puts what it finds
    # on its own PATH, so a cmake here is one the build will actually use.
    if build_needed and short == {"cmake"} and choices.get("conda_cmake", True):
        steps.append({
            "id": "cmake",
            "name": "cmake (into a conda environment)",
            "env": BUILD_ENV,
            "detail": f"conda environment {BUILD_ENV}, no root needed",
            "script": _cmake_script(conda_root),
        })

    # 3. The tools, into their own environments.
    box = Toolbox(settings)
    by_id = {t["id"]: t for t in state["tools"]}
    for tool_id in wanted_tools:
        known = by_id.get(tool_id) or {}
        if known.get("present") and not choices.get("force"):
            continue
        spec = CATALOG[tool_id]
        if not spec.conda_installable:
            notes.append(f"{spec.name} is {spec.install_hint or 'installed separately'} "
                         "-- it is not part of this script.")
            continue
        env = env_name_for(spec)
        steps.append({
            "id": f"tool:{tool_id}",
            "name": spec.name,
            "env": env,
            "detail": f"conda environment {env}",
            # The conda that is about to exist, not the one that does: without
            # this the generated script falls back to `conda shell.bash hook`
            # and fails on exactly the machine this feature is for.
            "script": box.install_script(tool_id, env, conda_root=conda_root),
        })
        if spec.licence_key:
            notes.append(f"{spec.name} needs its licence key pasted in afterwards — "
                         "the Environments panel has a button for it.")

    return {
        "platform": plat,
        "steps": steps,
        "notes": notes,
        "sudo_commands": sudo_commands,
        "conda_root": conda_root,
        "script": render(steps) if steps else "",
        "ready": state["ready"],
        "tools": state["tools"],
        "requirements": state["requirements"],
    }


def render(steps: List[Dict[str, Any]]) -> str:
    """One script that runs every step, and survives any of them failing.

    Not ``set -e`` at the top level on purpose: an optional tool that will not
    install is a reason to carry on and say so at the end, not a reason to
    abandon the four that would have worked.  Each step is written out as its
    own file first, so a failed one can be read, edited and re-run by hand.
    """
    lines = [
        "#!/usr/bin/env bash",
        "# Generated by Comfy-gmx first-run setup. Safe to run by hand.",
        "set -uo pipefail",
        "export LC_ALL=C",
        "",
        "__done=0; __skipped=0; __failed=0; __failures=''",
        "run_step() {",
        '  local id="$1" name="$2" file="$3"',
        '  printf "\\n>>> %s\\n" "$name"',
        '  if bash "$file"; then',
        "    __done=$((__done + 1))",
        "  else",
        "    __failed=$((__failed + 1))",
        '    __failures="$__failures $id"',
        '    printf ">>> %s did not finish -- carrying on. Re-run it with: bash %s\\n" \\',
        '      "$name" "$file" >&2',
        "  fi",
        "}",
        "",
    ]
    for index, step in enumerate(steps, 1):
        name = str(step.get("id", "")).replace(":", "-").replace("/", "-") or f"step{index}"
        filename = f"setup-{index:02d}-{name}.sh"
        lines.append(f"cat > {shlex.quote(filename)} " + _heredoc(step["script"], "STEP"))
        lines.append(f"run_step {shlex.quote(step['id'])} {shlex.quote(step['name'])} "
                     f"{shlex.quote(filename)}")
        lines.append("")
    lines += [
        'printf "\\n%s\\n" "======================================================"',
        'printf "  setup: %d done, %d failed\\n" "$__done" "$__failed"',
        'if [ "$__failed" -gt 0 ]; then',
        '  printf "  did not finish:%s\\n" "$__failures"',
        '  printf "  everything else is installed and usable.\\n"',
        "fi",
        'printf "%s\\n" "======================================================"',
        'exit "$__failed"',
    ]
    return "\n".join(lines)


def remember(settings: Settings, conda_root: str, tools: List[str],
             complete: bool = True) -> None:
    """Record what setup actually produced, so nothing has to be found again.

    Called however the job ended, not only when it succeeded.  Setup is several
    steps and they do not stand or fall together: a run where conda installed
    and one tool then failed has still installed conda, and throwing that away
    because of the failure leaves a working conda that nothing knows about.

    ``complete`` is what marks setup as done -- a partial run should still be
    offered the dialog next time, because it still has something to finish.
    """
    from .environments import Toolbox, remember_install   # circular at module level

    patch: Dict[str, Any] = {}
    if complete:
        patch["setup_done"] = True
    if conda_root and (Path(conda_root) / "etc" / "profile.d" / "conda.sh").exists():
        patch["conda_root"] = conda_root
    if patch:
        settings.update(patch)
        settings.save()

    # Built after conda_root is saved, so it looks in the place setup just made.
    box = Toolbox(settings)
    for tool_id in tools:
        spec = CATALOG.get(tool_id)
        if spec is None:
            continue
        env = env_name_for(spec)
        # That the environment directory exists proves nothing -- a conda
        # transaction that rolls back leaves the directory behind. Ask whether
        # the tool is in it, which is the same check the panel uses.
        if any(i.get("env") == env and not i.get("gone") for i in box.installs_of(tool_id)):
            remember_install(settings, tool_id, env)
    # A conda GROMACS is a `gmx` on the environment's PATH rather than a GMXRC,
    # and leaving a stale gmxrc pointing at nothing would beat it.
    if "gmx" in tools and not str(settings.get("gmxrc") or "").strip():
        settings.update({"gmx_binary": "gmx"})
        settings.save()


def sudo_block(plan_result: Dict[str, Any]) -> str:
    """The root-needing part, as something to paste into a terminal."""
    commands = plan_result.get("sudo_commands") or []
    if not commands:
        return ""
    return "\n".join(c["command"] for c in commands)


def run(script: str, workdir: Path, echo=print) -> int:
    """Run a setup script in the foreground, streaming it.  Used by the CLI."""
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "setup.sh"
    path.write_text(script)
    path.chmod(0o755)
    proc = subprocess.Popen(["bash", str(path)], cwd=str(workdir),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        echo(line.rstrip("\n"))
    return proc.wait()
