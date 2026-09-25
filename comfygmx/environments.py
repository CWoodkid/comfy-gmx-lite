"""Discovery and installation of the external programs Comfy-gmx drives.

Nothing here is required for the server to start.  A node declares a *logical*
tool id (``gmx``, ``martinize2``, ``coby``, ...); the :class:`Toolbox` turns that
into a concrete command plus the shell prelude needed to reach it -- a ``GMXRC``
to source, or a conda environment to activate.  Users can point every tool at an
installation they already have, or let Comfy-gmx build a conda environment.
"""

from __future__ import annotations

import concurrent.futures
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings, conda_activate_snippet, detect_conda_root, gmxlib_snippet, gmxrc_snippet


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

@dataclass
class ToolSpec:
    id: str
    name: str
    description: str
    #: "gromacs" (GMXRC based), "python" (importable module), "binary"
    kind: str = "binary"
    command: str = ""
    #: what to invoke for the version check when it differs from ``command``
    #: (e.g. the tool is run as ``python -m X`` but probed by importing X)
    probe_command: str = ""
    #: how to check it: argv appended to the probe command
    version_args: List[str] = field(default_factory=lambda: ["--version"])
    #: python module to import when kind == "python"
    module: str = ""
    #: conda channels + packages used by the one-click installer
    conda_channels: List[str] = field(default_factory=lambda: ["conda-forge"])
    conda_packages: List[str] = field(default_factory=list)
    pip_packages: List[str] = field(default_factory=list)
    suggested_env: str = ""
    homepage: str = ""
    notes: str = ""
    #: Shown when the tool is missing or fails to run. For what to do about it,
    #: as opposed to `notes`, which is a caveat worth knowing either way.
    troubleshooting: str = ""
    optional: bool = True
    #: Installing this one is not the end of it -- MODELLER wants a licence key
    #: pasted in afterwards, and until it is there every run fails at import.
    #: The editor puts a button on the row when this is set.
    licence_key: bool = False
    #: Where a version list comes from when asked: "conda", "pip", "gromacs"
    #: (released tarballs), or "" for tools with nothing to query.
    versions_from: str = ""
    #: Whether a conda environment is a way to get this tool at all.  GROMACS
    #: says no: the conda package is one build with one set of choices baked in
    #: -- no GPU, no MPI, SIMD for whatever machine made it -- and having it
    #: sitting in an environment alongside a real build is a reliable way to
    #: run the wrong `gmx` for a week without noticing.  Build it, or point at
    #: a build you already have.
    conda_installable: bool = True
    #: Shown where the Install button would be, when there isn't one.
    install_hint: str = ""
    #: This tool runs GROMACS itself, so its commands need GMXRC sourced as
    #: well as their own environment activated. cg2at is the case: it energy
    #: minimises and equilibrates every fragment it fits, by calling gmx.
    needs_gmx: bool = False
    #: Extra requirement ids from REQUIREMENTS that installing this needs on
    #: PATH. conda is implied for anything that goes into an environment, and
    #: git is worked out from a pip package that is a git URL, so this is only
    #: for what neither of those catches.
    needs: List[str] = field(default_factory=list)
    #: Some tools are a repository you run in place rather than a package you
    #: import: they read data files sitting beside the script, so pip has
    #: nothing to install and the checkout *is* the installation.  Setting this
    #: clones it to ``<data_dir>/src/<id>`` during install, and makes the tool
    #: count as missing until that directory is there.
    repo: str = ""
    #: A tag or branch to pin the clone to.  Blank tracks the default branch.
    repo_ref: str = ""
    #: A file that must exist inside the checkout for it to be one.  Used to
    #: tell an incomplete clone from a working one, and to check a directory
    #: the user points at before accepting it as their own checkout.
    repo_marker: str = ""
    #: The only parts of the repository worth having, as a sparse checkout.
    #: Not premature tidiness: hoomd3_phosphorylation keeps 1.1 GB of built
    #: distributions and 76 MB of paper in its tree, so a full clone is 2.1 GB
    #: and a sparse one is 2.6 MB.  Blank takes the whole thing.
    repo_paths: List[str] = field(default_factory=list)
    #: Bash appended after the packages are installed and before the tool is
    #: verified, with the environment already activated and ``$COMFYGMX_SRC``
    #: pointing at the checkout.  For a tool that has to compile something.
    post_install: str = ""

    def primary(self, kind: str = "") -> str:
        """The package that *is* this tool, out of the list it installs with.

        Not simply the first one. insane installs ``setuptools<81`` before
        ``insane`` -- a version pin that has to go on first -- and taking the
        first package made "is there an update" answer about setuptools, which
        is on version 84 and always will be newer than anything.
        """
        packages = list(self.pip_packages if kind == "pip" else self.conda_packages)
        if not packages:
            return ""
        wanted = {self.id.lower(), (self.module or "").lower()} - {""}

        def bare(name: str) -> str:
            return re.split(r"[<>=!\[]", name, 1)[0].strip().lower().replace("-", "_")

        for name in packages:
            if bare(name) in {w.replace("-", "_") for w in wanted}:
                return name
        # Otherwise the last one: pins and interpreters are put first here, and
        # the thing being installed is what the list builds up to.
        return packages[-1]


CATALOG: Dict[str, ToolSpec] = {
    "gmx": ToolSpec(
        id="gmx",
        name="GROMACS",
        description="Simulation engine: pdb2gmx, editconf, solvate, genion, grompp, mdrun and the analysis suite.",
        kind="gromacs",
        command="gmx",
        version_args=["--version"],
        conda_packages=[],
        suggested_env="",
        homepage="https://manual.gromacs.org/",
        notes="Built from source and reached through GMXRC. There is no conda route: "
              "that package is one build with the choices already made -- no GPU, no "
              "MPI, SIMD for the machine that built it -- and a second gmx sitting in "
              "an environment is a good way to run the wrong one without noticing.",
        troubleshooting=(
            "Point Settings at an existing GMXRC, or use Build from source, which "
            "asks for the version and the flags -- GPU backend, MPI, SIMD level -- "
            "and registers what it produces."
        ),
        optional=False,
        versions_from="gromacs",
        conda_installable=False,
        install_hint="built from source, or pointed at an existing install",
    ),
    "python": ToolSpec(
        id="python",
        name="Analysis Python",
        description="Interpreter used by the analysis and helper-script nodes (MDAnalysis, numpy, matplotlib).",
        kind="python",
        command="python",
        module="MDAnalysis",
        version_args=["-c", "import MDAnalysis;print(MDAnalysis.__version__)"],
        conda_packages=["mdanalysis", "numpy", "matplotlib", "scipy"],
        suggested_env="md_analysis",
        homepage="https://www.mdanalysis.org/",
    ),
    "shell": ToolSpec(
        id="shell",
        name="System shell",
        description="Plain bash; always available.",
        kind="binary",
        command="bash",
        version_args=["--version"],
        optional=False,
    ),
}


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

@dataclass
class ResolvedTool:
    id: str
    command: str
    env: str = ""
    prelude: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "command": self.command, "env": self.env, "prelude": self.prelude}


#: How long a listing of conda environments stays good for. Long enough to
#: spare a directory scan per resolved step, short enough that an environment
#: created by the installer is picked up without restarting the server.
ENV_CACHE_SECONDS = 3.0


class Toolbox:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._env_names: Optional[set] = None
        self._env_names_at = 0.0
        self._gmx_found: Optional[List[Dict[str, Any]]] = None
        self._gmx_found_at = 0.0

    # -- configuration --------------------------------------------------
    def _known_envs(self) -> set:
        now = time.monotonic()
        if self._env_names is None or now - self._env_names_at > ENV_CACHE_SECONDS:
            self._env_names = {env["name"] for env in self.conda_envs()}
            self._env_names_at = now
        return self._env_names

    def refresh(self) -> None:
        """Forget what environments and builds exist; call after making one."""
        self._env_names = None
        self._gmx_found = None

    def gromacs_choice(self, text: str) -> Optional[Dict[str, str]]:
        """A GROMACS build named by an override, or None if it names something else.

        Takes a path to a GMXRC, the directory above one, or the version of a
        build already discovered -- "2024.4" is what somebody types when they
        want that node run against the old one.
        """
        text = (text or "").strip()
        if not text:
            return None
        candidate = Path(os.path.expanduser(text))
        for guess in (candidate, candidate / "GMXRC", candidate / "bin" / "GMXRC"):
            if guess.is_file():
                binaries = sorted(
                    child.name for child in guess.parent.iterdir()
                    if self._BINARY_RE.match(child.name) and os.access(child, os.X_OK)
                ) if guess.parent.is_dir() else []
                return {"path": str(guess), "binary": binaries[0] if binaries else "gmx"}
        if "/" in text or text in self._known_envs():
            # A path that does not exist, or a conda environment: not ours.
            return None
        for found in self._gmx_cache():
            if text in (found.get("version") or "") or text == Path(found["prefix"]).name:
                return {"path": found["path"],
                        "binary": (found.get("binaries") or ["gmx"])[0]}
        return None

    def _gmx_cache(self) -> List[Dict[str, Any]]:
        """Discovered GROMACS builds, remembered briefly.

        Finding them walks a dozen directory trees, and resolve() is called once
        per step -- doing it every time would put a filesystem walk between each
        command and the next.
        """
        now = time.monotonic()
        if self._gmx_found is None or now - self._gmx_found_at > 60.0:
            self._gmx_found = self.gmxrc_candidates()
            self._gmx_found_at = now
        return self._gmx_found

    def installs_of(self, tool_id: str) -> List[Dict[str, Any]]:
        """Every conda environment that actually holds this tool.

        On-disk checks only -- no subprocess, no activation -- so this is cheap
        enough to answer for every tool at once whenever the panel opens. It
        finds environments made outside Comfy-gmx too, which is the point: an
        install you already had is as valid as one this made.
        """
        spec = CATALOG.get(tool_id)
        if spec is None:
            return []
        recorded = {i.get("env"): i.get("version", "")
                    for i in _recorded(self.settings, tool_id) if i.get("env")}
        active = (self.config_for(tool_id).get("env") or "").strip()
        found = []
        for env in self.conda_envs():
            name = env["name"]
            if not self._env_contains(name, spec):
                continue
            found.append({
                "env": name,
                "version": recorded.get(name, ""),
                "active": name == active,
                # A version guessed from the directory name is better than
                # nothing and much cheaper than probing every environment.
                "guess": _version_from_prefix(Path(env["path"]), spec),
            })
        for name, version in recorded.items():
            if not any(f["env"] == name for f in found):
                found.append({"env": name, "version": version,
                              "active": name == active, "guess": "", "gone": True})
        found.sort(key=lambda f: (not f["active"], f["env"]))
        return found

    def _env_contains(self, env: str, spec: "ToolSpec") -> bool:
        """Cheap on-disk check that ``env`` really holds this tool."""
        root = detect_conda_root(self.settings)
        if not root:
            return False
        prefix = Path(root) / "envs" / env
        if not prefix.is_dir():
            return False
        if spec.kind == "python" and spec.module:
            for site in prefix.glob("lib/python*/site-packages"):
                if (site / spec.module).exists():
                    return True
                if list(site.glob(spec.module + "*.py")):
                    return True
                if list(site.glob(spec.module + "-*.dist-info")):
                    return True
            return False
        binary = shlex.split(spec.command)[0] if spec.command else spec.id
        return (prefix / "bin" / binary).exists()

    def _envs_holding(self, spec: "ToolSpec") -> List[str]:
        """Names of the conda environments that really contain this tool.

        On-disk checks only, so this stays cheap.  Deliberately not written in
        terms of installs_of(), which asks config_for() which environment is in
        use -- that would ask this question to answer itself.
        """
        return [name for name in self._known_envs()
                if self._env_contains(name, spec)]

    def _adopt_env(self, spec: "ToolSpec") -> str:
        """Which environment to use for a tool nobody has configured by hand.

        Prefer the one this program would have made itself.  Failing that, take
        the environment the tool is actually in, but only when there is exactly
        one -- with two or more there is no way to tell which was meant, and
        picking the wrong one is worse than admitting we do not know.

        The point of looking beyond our own naming is that an install you
        already had counts.  PyLipID sitting in somebody's own analysis
        environment is installed; reporting it missing because the name does not
        match ours would be reporting on our own bookkeeping, not on the tool.
        """
        if not spec:
            return ""
        holders = self._envs_holding(spec)
        if spec.suggested_env and spec.suggested_env in holders:
            return spec.suggested_env
        if len(holders) == 1:
            return holders[0]
        return ""

    def config_for(self, tool_id: str) -> Dict[str, Any]:
        tools = self.settings.get("tools") or {}
        entry = tools.get(tool_id) or {}
        spec = CATALOG.get(tool_id)
        env = entry.get("env", "") or ""
        if not env and spec and "env" not in entry:
            # Nothing configured yet: find where the tool actually is.  Adopting
            # an environment merely because its name matches would attribute the
            # tool to the wrong place and quietly rely on PATH falling through
            # to wherever it really lives.
            env = self._adopt_env(spec)
        return {
            "env": env,
            "command": entry.get("command", "") or (spec.command if spec else tool_id),
            "source": self.settings.source_override(tool_id),
        }

    def resolve(self, tool_id: str, env_override: str = "") -> ResolvedTool:
        spec = CATALOG.get(tool_id)
        cfg = self.config_for(tool_id)
        env = (env_override or cfg["env"]).strip()
        command = cfg["command"]
        prelude_parts: List[str] = []

        if tool_id == "shell":
            # Steps tagged "shell" already carry a concrete command; only the
            # optional environment activation is ours to add.
            return ResolvedTool(
                id=tool_id,
                command="",
                env=env,
                prelude=conda_activate_snippet(detect_conda_root(self.settings), env)
                if env else "",
            )

        if tool_id == "gmx":
            command = self.settings.get("gmx_binary") or "gmx"
            if cfg["command"] and cfg["command"] not in ("gmx", ""):
                command = cfg["command"]
            gmxrc = (self.settings.get("gmxrc") or "").strip()
            # GROMACS is the one tool whose versions are not conda environments,
            # so the per-node override has to be able to name a build instead:
            # a path to a GMXRC, or the version of one already found.
            chosen = self.gromacs_choice(env_override)
            if chosen:
                gmxrc = chosen["path"]
                command = chosen["binary"]
                env = ""
            if gmxrc:
                prelude_parts.append(gmxrc_snippet(gmxrc))
            # After GMXRC, which sets GMXLIB itself: the user's own force
            # field folder goes in front of it.
            prelude_parts.append(gmxlib_snippet(self.settings.gmx_forcefield_dir))

        if spec is not None and spec.needs_gmx:
            # First, so that activating the tool's own environment afterwards
            # cannot be undone by GMXRC's changes to PATH.
            gmxrc = (self.settings.get("gmxrc") or "").strip()
            if gmxrc:
                prelude_parts.append(gmxrc_snippet(gmxrc))
            prelude_parts.append(gmxlib_snippet(self.settings.gmx_forcefield_dir))

        if env:
            prelude_parts.append(
                conda_activate_snippet(detect_conda_root(self.settings), env)
            )

        if spec and spec.kind == "python" and command in ("", "python"):
            # Inside a conda environment "python" is always there, and is that
            # environment's own. Outside one it may not be: Debian and Ubuntu
            # have only "python3" unless a package adds the shorter name.
            command = "python" if (env or shutil.which("python")) else "python3"

        return ResolvedTool(
            id=tool_id,
            command=command or tool_id,
            env=env,
            prelude="\n".join(p for p in prelude_parts if p),
        )

    # -- discovery ------------------------------------------------------
    def conda_envs(self) -> List[Dict[str, str]]:
        root = detect_conda_root(self.settings)
        found: List[Dict[str, str]] = []
        seen = set()
        if root:
            base = Path(root)
            if base.exists():
                found.append({"name": "base", "path": str(base)})
                seen.add(str(base))
            for env_dir in sorted((base / "envs").glob("*")):
                if env_dir.is_dir() and str(env_dir) not in seen:
                    found.append({"name": env_dir.name, "path": str(env_dir)})
                    seen.add(str(env_dir))
        return found

    #: Where to look for GROMACS installations. A source build is rarely at a
    #: predictable depth -- ``~/soft/gromacs/gromacs-2024.4/inst/cuda-mpi`` is
    #: as normal as ``/usr/local/gromacs`` -- so these are walked rather than
    #: globbed at a fixed level.
    DEFAULT_SEARCH_ROOTS = (
        "~/soft", "~/software", "~/opt", "~/apps", "~/local", "~/programs",
        "~/tools", "~/gromacs", "~/src", "~/.local",
        "/usr/local", "/opt", "/software", "/apps", "/usr/share/gromacs",
    )

    #: Directory names that cannot contain an install prefix and are expensive
    #: to walk.
    _PRUNE = {
        ".git", ".hg", ".svn", "__pycache__", "node_modules", ".cache", ".conda",
        "site-packages", "dist-packages", "pkgs", ".npm", ".cargo", ".rustup",
        "envs", "doc", "docs", "man", "include", "src", "tests", "test",
        "CMakeFiles", ".git-crypt", "top",
    }

    #: The names a GROMACS binary can have.
    _BINARY_RE = re.compile(r"^gmx(_mpi)?(_d)?$")

    def search_roots(self) -> List[str]:
        configured = self.settings.get("gmx_search_roots") or []
        roots = list(configured) + list(self.DEFAULT_SEARCH_ROOTS)
        out: List[str] = []
        for root in roots:
            expanded = str(Path(os.path.expanduser(str(root))))
            if expanded not in out:
                out.append(expanded)
        return out

    def gmxrc_candidates(self, max_depth: int = 7) -> List[Dict[str, Any]]:
        """Every GMXRC we can find, with the binaries and version beside it.

        The binary name is not cosmetic: an MPI build installs ``gmx_mpi`` and
        no ``gmx`` at all, so a candidate is only usable together with the name
        of the binary that actually sits next to it.
        """
        found: Dict[str, Dict[str, Any]] = {}

        def record(gmxrc: Path) -> None:
            try:
                key = str(gmxrc.resolve())
            except OSError:
                key = str(gmxrc)
            if key in found:
                return
            bindir = gmxrc.parent
            prefix = bindir.parent
            binaries = []
            try:
                for child in sorted(bindir.iterdir()):
                    if self._BINARY_RE.match(child.name) and os.access(child, os.X_OK):
                        binaries.append(child.name)
            except OSError:
                pass
            found[key] = {
                "path": str(gmxrc),
                "prefix": str(prefix),
                "binaries": binaries,
                "version": _prefix_version(prefix),
            }

        for root in self.search_roots():
            base = Path(root)
            if not base.is_dir():
                continue
            base_depth = len(base.parts)
            try:
                walker = os.walk(base, followlinks=False, onerror=lambda err: None)
                for dirpath, dirnames, filenames in walker:
                    current = Path(dirpath)
                    if len(current.parts) - base_depth >= max_depth:
                        dirnames[:] = []
                        continue
                    if "GMXRC" in filenames and current.name == "bin":
                        record(current / "GMXRC")
                        # The rest of an install prefix holds nothing we want.
                        dirnames[:] = []
                        continue
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and d not in self._PRUNE
                    ]
            except OSError:
                continue

        # Anything already on PATH, wherever it lives.
        for name in ("gmx", "gmx_mpi", "gmx_d", "gmx_mpi_d"):
            which = shutil.which(name)
            if not which:
                continue
            guess = Path(which).resolve().parent / "GMXRC"
            if guess.exists():
                record(guess)

        return sorted(found.values(), key=lambda row: row["path"])

    def probe(self, tool_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Run the tool's version check inside its configured environment."""
        spec = CATALOG.get(tool_id)
        if spec is None:
            return {"id": tool_id, "found": False, "error": "unknown tool"}
        resolved = self.resolve(tool_id)
        probe_command = spec.probe_command or resolved.command
        # shlex.quote, not manual quoting: several version checks are python
        # -c snippets that contain single quotes of their own.
        args = " ".join(shlex.quote(a) for a in spec.version_args)
        head = shlex.split(probe_command)[0] if probe_command else ""
        script = "\n".join(
            filter(
                None,
                [
                    "export LC_ALL=C",
                    # without pipefail the exit status would be head's, not the tool's
                    "set -o pipefail",
                    resolved.prelude,
                    f"command -v {shlex.quote(head)} >/dev/null 2>&1 || "
                    f'{{ echo "COMFYGMX_MISSING"; exit 127; }}',
                    # The first 25 lines are enough to read, but the rest still
                    # has to be swallowed. A bare `| head` closes the pipe on a
                    # tool that is still writing, the tool dies of it, and with
                    # pipefail on that reads as a broken tool -- so anything
                    # whose help text runs past 25 lines was reported as
                    # failing its version check while working perfectly.
                    f"{probe_command} {args} 2>&1 | "
                    "{ head -n 25; cat >/dev/null; }",
                ],
            )
        )
        try:
            proc = subprocess.run(
                ["bash", "-lc", script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return {
                "id": tool_id,
                "found": False,
                "env": resolved.env,
                "command": resolved.command,
                "error": f"version check timed out after {timeout:.0f}s",
            }
        except OSError as exc:
            return {"id": tool_id, "found": False, "error": str(exc)}

        missing = "COMFYGMX_MISSING" in output
        found = proc.returncode == 0 and not missing
        # For a tool that *is* a checkout, working imports are only half of it.
        # Without the clone there is no program to run, and reporting it as
        # installed sends the user to a node that fails instead of to the
        # installer that would fix it.
        if found and spec.repo:
            source = self.settings.source_dir(tool_id)
            mine = bool(self.settings.source_override(tool_id))
            complaint = ""
            if not source.is_dir() or not any(source.iterdir()):
                complaint = (f"the environment is there but the checkout at "
                             f"{source} is not")
            elif spec.repo_marker and not (source / spec.repo_marker).exists():
                complaint = (f"{source} does not look like {spec.name}: there "
                             f"is no {spec.repo_marker} in it")
            if complaint:
                if mine:
                    complaint += " -- it is the checkout you pointed this tool at"
                return {
                    "id": tool_id,
                    "name": spec.name,
                    "troubleshooting": spec.troubleshooting,
                    "found": False,
                    "env": resolved.env,
                    "command": resolved.command,
                    "version": "",
                    "output": output.strip()[:4000],
                    "error": complaint,
                    "source": str(source),
                    "source_override": self.settings.source_override(tool_id),
                }
        return {
            "id": tool_id,
            "name": spec.name,
            "troubleshooting": "" if found else spec.troubleshooting,
            "found": found,
            "env": resolved.env,
            "command": resolved.command,
            "version": _summarise_version(output) if found else "",
            "output": output.strip()[:4000],
            "error": "" if found else ("not found on PATH" if missing else "version check failed"),
            "source": str(self.settings.source_dir(tool_id)) if spec and spec.repo else "",
            "source_override": (self.settings.source_override(tool_id)
                                if spec and spec.repo else ""),
        }

    def survey(self) -> List[Dict[str, Any]]:
        rows = []
        for tool_id, spec in CATALOG.items():
            if tool_id == "shell":
                continue
            status = self.probe(tool_id)
            status.update(
                {
                    "description": spec.description,
                    "homepage": spec.homepage,
                    "notes": spec.notes,
                    "troubleshooting": spec.troubleshooting,
                    "optional": spec.optional,
                    "suggested_env": spec.suggested_env,
                    "licence_key": spec.licence_key,
                    "versions_from": spec.versions_from,
                    "conda_installable": spec.conda_installable,
                    "install_hint": spec.install_hint,
                    # The package that *is* the tool. The install dialog is only
                    # ever handed a survey row, so a field it needs has to be
                    # here and not only in the catalogue listing.
                    "primary": (spec.primary(spec.versions_from)
                                if spec.versions_from in ("pip", "conda") else ""),
                    # Repo-backed tools only. "source" and "source_override"
                    # come from probe(), which every caller reads; only the
                    # installer-managed location is added here.
                    "repo": spec.repo,
                    "source_default": (str(self.settings.sources_dir / tool_id)
                                       if spec.repo else ""),
                }
            )
            rows.append(status)
        return rows

    # -- installation ---------------------------------------------------
    def install_script(self, tool_id: str, env: str = "", version: str = "",
                       conda_root: str = "") -> str:
        """Bash that creates/updates a conda env holding ``tool_id``.

        ``version`` pins the first package, which is the one the tool is: a
        version asked for and quietly ignored is worse than one refused.

        ``conda_root`` overrides where conda is expected to be.  First-run setup
        needs that: it installs conda and the tools in one script, so at the
        moment this text is generated the conda it must activate does not exist
        yet, and detection would fall back to ``conda shell.bash hook`` -- which
        fails on precisely the machine that feature exists for.
        """
        spec = CATALOG.get(tool_id)
        if spec is None:
            raise KeyError(tool_id)
        if not spec.conda_installable:
            raise ValueError(
                f"{spec.name} is not installed into an environment. "
                + (spec.install_hint or "Install it yourself and point Settings at it."))
        env = (env or spec.suggested_env or f"comfygmx-{tool_id}").strip()
        version = (version or "").strip()
        if version and not re.match(r"^[A-Za-z0-9._+-]{1,32}$", version):
            raise ValueError(f"'{version}' is not a version number")
        # Refused rather than dropped, for the reason in this method's docstring:
        # a tool whose versions cannot be listed has no version to ask for, and
        # pinning one anyway used to stamp it on whatever package came last.
        if version and spec.versions_from not in ("pip", "conda"):
            raise ValueError(
                f"{spec.name} does not come from an index that can be listed, so "
                "there is no version to choose -- install it without one.")

        def pinned(packages: List[str], glue: str, kind: str) -> List[str]:
            """Pin the package that is the tool, not whatever is first in the list."""
            target = spec.primary(kind)
            # A version answers "which martinize2", so it belongs on the list the
            # version was read from. Pinning both lists put the tool's version on
            # the interpreter instead -- asking for martinize2 0.15.0 generated
            # `conda create ... python=0.15.0`, which conda cannot solve -- because
            # a pip tool's conda list holds nothing but python.
            # Not `(spec.versions_from or kind) != kind`: that collapses to
            # False when versions_from is empty, so the five tools with no
            # listable index went on pinning both lists -- and a pip tool's
            # conda list is nothing but the interpreter and its dependencies,
            # so the version landed on whichever package happened to be last
            # (`git=9.9.9`, `openmm=9.9.9`). A tool whose versions cannot be
            # listed cannot be pinned at all.
            if spec.versions_from != kind:
                return list(packages)
            if not version or target not in packages:
                return list(packages)
            # A requirement that names a repository takes its version as a
            # @ref, not ==, so `git+https://...==1.2` is not a thing pip can
            # parse. Refuse rather than generate it.
            if re.match(r"^[a-z0-9+.-]+\+", target) or "://" in target:
                raise ValueError(
                    f"{spec.name} is installed straight from a repository, so it "
                    "has no version to ask for; install it and it is whatever "
                    "that repository's default branch says.")
            # Keep any extras: vermouth[mdtraj] pinned to a version has to stay
            # vermouth[mdtraj]==x.y, or asking for a particular martinize2 would
            # quietly install one that cannot do secondary structure. The split
            # above already leaves the bracket on `base`.
            base = re.split(r"[<>=!]", target, 1)[0].strip()
            return [f"{base}{glue}{version}" if pkg == target else pkg
                    for pkg in packages]
        root = conda_root or detect_conda_root(self.settings)
        hook = (
            f'source "{Path(root) / "etc" / "profile.d" / "conda.sh"}"'
            if root
            else 'eval "$(conda shell.bash hook)"'
        )
        channels = " ".join(f"-c {c}" for c in spec.conda_channels)
        lines = [
            "set -euo pipefail",
            "export LC_ALL=C",
            hook,
            f'if conda env list | awk \'{{print $1}}\' | grep -qx "{env}"; then',
            f'  echo ">> conda environment {env} already exists, updating it"',
            "else",
            f'  echo ">> creating conda environment {env}"',
            f"  conda create -y -n {env} {channels} "
            + " ".join(pinned(spec.conda_packages, "=", "conda") or ["python=3.11"]),
            "fi",
            f"conda activate {env}",
        ]
        if spec.conda_packages:
            lines.append(f"conda install -y {channels} "
                         + " ".join(pinned(spec.conda_packages, "=", "conda")))
        if spec.pip_packages:
            lines.append("python -m pip install --upgrade "
                         + " ".join(shlex.quote(pkg)
                                    for pkg in pinned(spec.pip_packages, "==", "pip")))

        # A tool that is a repository rather than a package.  Cloned, or pulled
        # if it is already there, so re-running the installer is an update
        # instead of a failure -- and so a checkout the user has been editing
        # is not silently thrown away.
        if spec.repo and self.settings.source_override(tool_id):
            # The checkout is the user's: a fork, or a clone they are editing.
            # Cloning over it, pulling it or deleting it are all wrong, and the
            # dependencies are what they came here for anyway.
            source = self.settings.source_dir(tool_id)
            # post_install is the exception: the ashbaugh plugin has to be
            # compiled inside the checkout it will be imported from, so say so
            # rather than promise more than is true.
            note = ("the build step below still writes into it"
                    if spec.post_install
                    else "it is yours to update; nothing here will touch it")
            lines += [
                f'echo ">> using your own {spec.name} checkout at {source}"',
                f'echo ">> {note}"',
                f"export COMFYGMX_SRC={shlex.quote(str(source))}",
            ]
        elif spec.repo:
            source = Path(self.settings.sources_dir) / tool_id
            ref = f" --branch {shlex.quote(spec.repo_ref)}" if spec.repo_ref else ""
            # A sparse partial clone where one is asked for, falling back to a
            # plain shallow clone: --filter needs a server that offers it and
            # sparse-checkout needs git 2.25, and neither is worth failing an
            # install over when the whole repository would also do.
            if spec.repo_paths:
                wanted = " ".join(shlex.quote(part) for part in spec.repo_paths)
                clone = (
                    f'  {{ git clone --depth 1 --filter=blob:none --sparse{ref} '
                    f'{shlex.quote(spec.repo)} "$COMFYGMX_SRC" '
                    f'&& git -C "$COMFYGMX_SRC" sparse-checkout set {wanted}; }} '
                    f'|| {{ echo ">> sparse clone unavailable, taking the whole '
                    f'repository"; rm -rf "$COMFYGMX_SRC"; '
                    f'git clone --depth 1{ref} {shlex.quote(spec.repo)} '
                    f'"$COMFYGMX_SRC"; }}'
                )
            else:
                clone = (f'  git clone --depth 1{ref} {shlex.quote(spec.repo)} '
                         f'"$COMFYGMX_SRC"')
            lines += [
                f"export COMFYGMX_SRC={shlex.quote(str(source))}",
                f'mkdir -p {shlex.quote(str(source.parent))}',
                'if [ -d "$COMFYGMX_SRC/.git" ]; then',
                f'  echo ">> updating the {spec.name} checkout"',
                '  git -C "$COMFYGMX_SRC" pull --ff-only || '
                'echo ">> could not fast-forward; leaving the checkout as it is"',
                "else",
                f'  echo ">> cloning {spec.name}"',
                clone,
                "fi",
            ]

        if spec.post_install:
            lines += [f'echo ">> finishing the {spec.name} install"',
                      spec.post_install]

        # Verify rather than assume. A package can install cleanly and still be
        # unusable -- a missing transitive import shows up on first run, not
        # during pip's dependency resolution -- and reporting success on pip's
        # exit code alone sends the user off to debug a "working" install.
        probe_command = spec.probe_command or spec.command or tool_id
        head = shlex.split(probe_command)[0] if probe_command else tool_id
        args = " ".join(shlex.quote(a) for a in spec.version_args)
        lines += [
            "set +e",
            f'echo ">> checking that {spec.name} actually runs"',
            f"command -v {shlex.quote(head)} >/dev/null 2>&1",
            "__found=$?",
            f"{probe_command} {args} > /tmp/comfygmx-verify.$$ 2>&1",
            "__rc=$?",
            'if [ "$__found" -ne 0 ]; then',
            f'  echo ">> FAILED: {shlex.quote(head)} is not on PATH in {env}" >&2',
            "  exit 1",
            "fi",
            'if [ "$__rc" -ne 0 ]; then',
            f'  echo ">> FAILED: {spec.name} is installed but does not run:" >&2',
            "  tail -n 20 /tmp/comfygmx-verify.$$ >&2",
            "  rm -f /tmp/comfygmx-verify.$$",
            "  exit 1",
            "fi",
            "rm -f /tmp/comfygmx-verify.$$",
            f'echo ">> {spec.name} installed into {env} and verified"',
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Removing an environment
# --------------------------------------------------------------------------

#: Environment names conda will accept. Validated because the name goes into a
#: shell command, and because "" would mean the active environment.
_ENV_RE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")

#: Never removable, whatever anyone asks.
PROTECTED_ENVS = {"base", "root"}


def remove_env_plan(settings: Settings, env: str) -> Dict[str, Any]:
    """What removing ``env`` would delete, and the script that does it.

    Checked before it is offered rather than after it fails: the name has to be
    one conda would accept, it has to be an environment that exists, it must not
    be base, and it is worth saying which tools are about to stop resolving.
    """
    env = str(env or "").strip()
    if not _ENV_RE.match(env):
        return {"error": f"'{env}' is not an environment name"}
    if env.lower() in PROTECTED_ENVS:
        return {"error": "the base environment is not removable from here"}

    box = Toolbox(settings)
    known = {row["name"]: row for row in box.conda_envs()}
    if env not in known:
        return {"error": f"there is no conda environment called '{env}'"}

    root = detect_conda_root(settings)
    if not root:
        return {"error": "no conda installation found to remove it with"}

    # Which tools were resolving through it, so the dialog can say so before
    # rather than leave someone wondering why four nodes went red.
    holds = [spec.name for spec in CATALOG.values()
             if spec.id != "shell" and any(i.get("env") == env and not i.get("gone")
                                           for i in box.installs_of(spec.id))]
    active = [spec.id for spec in CATALOG.values()
              if (box.config_for(spec.id).get("env") or "") == env]

    hook = Path(root) / "etc" / "profile.d" / "conda.sh"
    script = "\n".join([
        "set -euo pipefail",
        "export LC_ALL=C",
        f'source "{hook}"',
        f'echo ">> removing conda environment {env}"',
        f"conda env remove -y -n {shlex.quote(env)}",
        # conda exits 0 having done nothing if it decides the environment is
        # not one of its own, so the absence is checked rather than assumed.
        f'if [ -d {shlex.quote(str(Path(known[env]["path"])))} ]; then',
        f'  echo ">> FAILED: {known[env]["path"]} is still there" >&2',
        "  exit 1",
        "fi",
        f'echo ">> {env} removed"',
    ])
    return {"env": env, "path": known[env]["path"], "holds": holds,
            "active_for": active, "script": script}


def forget_env(settings: Settings, env: str) -> None:
    """Drop an environment from the settings after it has gone.

    Leaving the record behind would have the panel offering an environment that
    is not there any more, and `installs_of` marking it "gone" forever.
    """
    tools = dict(settings.get("tools") or {})
    changed = False
    for tool_id, entry in list(tools.items()):
        entry = dict(entry or {})
        installs = [i for i in (entry.get("installs") or []) if i.get("env") != env]
        if len(installs) != len(entry.get("installs") or []):
            entry["installs"] = installs
            changed = True
        if (entry.get("env") or "") == env:
            # Fall back to the newest one still standing, or to PATH.
            entry["env"] = installs[-1]["env"] if installs else ""
            changed = True
        tools[tool_id] = entry
    if changed:
        settings.update({"tools": tools})
        settings.save()


def _prefix_version(prefix: Path) -> str:
    """Read the version out of an install prefix without running anything."""
    for pattern in ("share/cmake/gromacs*/gromacs-config-version.cmake",
                    "share/cmake/gromacs*/gromacs*-config-version.cmake"):
        for candidate in sorted(prefix.glob(pattern)):
            try:
                text = candidate.read_text(errors="replace")
            except OSError:
                continue
            match = re.search(r'PACKAGE_VERSION\s+"([^"]+)"', text)
            if match:
                return match.group(1)
    # Fall back to whatever looks like a version in the path.
    match = re.search(r"(\d{4}\.\d+(\.\d+)?)", str(prefix))
    return match.group(1) if match else ""


#: Lines that carry a number but are not a version.
_NOT_A_VERSION = re.compile(
    r"deprecat|warning|traceback|futurewarning|userwarning|^\s*File \"|"
    r"^\s*import\s|site-packages", re.IGNORECASE)


def _summarise_version(output: str) -> str:
    fallback = ""
    for line in output.splitlines():
        line = line.strip()
        if not line or len(line) >= 200:
            continue
        if _NOT_A_VERSION.search(line):
            continue
        if re.search(r"\b\d+\.\d+(\.\d+)?\b", line):
            return line
        if not fallback:
            fallback = line
    return fallback[:200]


def _version_from_prefix(prefix: Path, spec: ToolSpec) -> str:
    """A version read off directory names inside an environment.

    MODELLER lays itself out as ``lib/modeller-10.7``; a pip package leaves a
    ``name-1.2.3.dist-info``. Neither is authoritative -- probing is -- but
    probing eleven environments costs eleven conda activations, and this costs
    a directory listing.
    """
    module = (spec.module or spec.id).lower()
    for pattern in (f"lib/{module}-*",
                    f"lib/python*/site-packages/{module}-*.dist-info",
                    f"lib/python*/site-packages/{module}-*.egg-info"):
        for path in prefix.glob(pattern):
            name = re.sub(r"\.(dist|egg)-info$", "", path.name)
            match = re.search(r"-(\d[\w.]*?)$", name)
            if match:
                return match.group(1).rstrip(".")
    return ""


def disk_usage(settings: Settings, limit: float = 4.0) -> List[Dict[str, Any]]:
    """What each part of the data directory is using.

    Free space alone does not tell you that two abandoned GROMACS build trees
    are sitting in installs/ -- 1.8 GB went unnoticed here until somebody
    looked. Walked rather than shelled out to du, and given a deadline: a data
    directory on a slow share should make the panel late, not hang it.
    """
    deadline = time.monotonic() + limit
    # Each inode once, and blocks rather than apparent size -- what du counts.
    # Large inputs are hard-linked into every run that uses them, so adding up
    # file sizes reported 50 GB of a directory holding 3.1 GB, which is the kind
    # of number that sends somebody deleting their own results.
    seen: set = set()
    out = []
    for child in sorted(settings.data_dir.glob("*")):
        total, files, complete = 0, 0, True
        targets = [child] if child.is_file() else []
        if child.is_file():
            info = child.lstat()
            total, files = info.st_blocks * 512, 1
            seen.add((info.st_dev, info.st_ino))
        else:
            for root, _dirs, names in os.walk(child, onerror=lambda err: None):
                for name in names:
                    try:
                        info = os.lstat(os.path.join(root, name))
                    except OSError:
                        continue
                    files += 1
                    key = (info.st_dev, info.st_ino)
                    if info.st_nlink > 1:
                        if key in seen:
                            continue
                        seen.add(key)
                    total += info.st_blocks * 512
                if time.monotonic() > deadline:
                    complete = False
                    break
        out.append({"name": child.name, "bytes": total, "files": files,
                    "partial": not complete,
                    "entries": sum(1 for _ in child.glob("*")) if child.is_dir() else 0})
    out.sort(key=lambda row: -row["bytes"])
    return out


def system_report(settings: Settings) -> Dict[str, Any]:
    """Everything the Environment panel needs in one call."""
    box = Toolbox(settings)
    data_dir = settings.data_dir
    usage: Dict[str, Any] = {}
    try:
        total, used, free = shutil.disk_usage(data_dir if data_dir.exists() else Path.home())
        usage = {"total": total, "used": used, "free": free}
    except OSError:
        pass
    return {
        "conda_root": detect_conda_root(settings),
        "conda_envs": box.conda_envs(),
        # Which environments hold which tool, so a node can be pointed at one
        # version while everything else keeps using another.
        "installs": {s.id: box.installs_of(s.id)
                     for s in CATALOG.values() if s.id != "shell"},
        "gmxrc_candidates": box.gmxrc_candidates(),
        "data_dir": str(data_dir),
        "disk": usage,
        "usage": disk_usage(settings),
        "locale": {k: os.environ.get(k, "") for k in ("LANG", "LC_ALL", "LC_NUMERIC")},
        "catalog": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "kind": s.kind,
                "homepage": s.homepage,
                "notes": s.notes,
                "troubleshooting": s.troubleshooting,
                "optional": s.optional,
                "suggested_env": s.suggested_env,
                "conda_packages": s.conda_packages,
                "pip_packages": s.pip_packages,
                # The package that *is* the tool, so the install dialog can say
                # which version its default actually installs when the catalogue
                # holds one back on purpose.
                "primary": (s.primary(s.versions_from)
                            if s.versions_from in ("pip", "conda") else ""),
                "conda_channels": s.conda_channels,
            }
            for s in CATALOG.values()
            if s.id != "shell"
        ],
        "settings": json.loads(json.dumps(settings.data)),
    }


# --------------------------------------------------------------------------
# What else is out there
# --------------------------------------------------------------------------

GROMACS_INDEX = "https://ftp.gromacs.org/gromacs/"
_PYPI = "https://pypi.org/pypi/{}/json"
_TARBALL = re.compile(r"gromacs-(\d+(?:\.\d+)*)\.tar\.gz")


def version_key(text: str):
    """Sortable form of a version string, digits compared as numbers.

    ``2026.3`` after ``2025.4`` and ``10.7`` after ``9.25``, which plain string
    comparison gets backwards in both cases.
    """
    out = []
    for part in re.findall(r"\d+|[A-Za-z]+", str(text or "")):
        out.append((0, int(part), "") if part.isdigit() else (1, 0, part.lower()))
    return out


def _newest(versions: List[str]) -> str:
    """The newest *release*, not the newest upload.

    An index carries release candidates and dev builds; offering 1.1.dev0 as
    the version to move to would be answering a question nobody asked.
    """
    if not versions:
        return ""
    final = [v for v in versions if not re.search(r"[A-Za-z]", v)]
    return max(final or versions, key=version_key)


def _pypi_versions(package: str, timeout: float = 20.0) -> List[str]:
    """Straight from PyPI rather than through ``pip index``.

    ``pip index versions`` is marked experimental, wants a recent pip, and costs
    a subprocess and an environment activation to answer a question that is one
    JSON document.
    """
    name = re.split(r"[<>=!\[]", package, 1)[0].strip()
    if not name or "/" in name or name.startswith("git+"):
        return []
    try:
        with urllib.request.urlopen(_PYPI.format(name), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:                                        # noqa: BLE001
        return []
    releases = [v for v, files in (data.get("releases") or {}).items() if files]
    return sorted(set(releases), key=version_key)


def _conda_versions(settings: Settings, spec: ToolSpec, timeout: float = 120.0) -> List[str]:
    package = (spec.primary("conda") or spec.id).split("=")[0]
    channels: List[str] = []
    for channel in spec.conda_channels:
        channels += ["-c", channel]
    root = detect_conda_root(settings)
    conda = str(Path(root) / "condabin" / "conda") if root else "conda"
    try:
        proc = subprocess.run([conda, "search", "--json"] + channels + [package],
                              capture_output=True, text=True, timeout=timeout)
        data = json.loads(proc.stdout or "{}")
    except Exception:                                        # noqa: BLE001
        return []
    entries = data.get(package) or []
    if not isinstance(entries, list):
        return []
    return sorted({str(e.get("version")) for e in entries if e.get("version")},
                  key=version_key)


def gromacs_releases(timeout: float = 25.0) -> List[str]:
    """Every released tarball on the GROMACS ftp index.

    Read rather than hard-coded: a list baked into the source is out of date the
    day after it is written, and the index is one request.
    """
    try:
        with urllib.request.urlopen(GROMACS_INDEX, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception:                                        # noqa: BLE001
        return []
    return sorted(set(_TARBALL.findall(body)), key=version_key)


def available_versions(settings: Settings, tool_id: str) -> Dict[str, Any]:
    """What versions of a tool could be installed, newest last."""
    spec = CATALOG.get(tool_id)
    if spec is None:
        return {"id": tool_id, "error": "unknown tool", "versions": []}
    source = spec.versions_from
    if source == "gromacs":
        versions = gromacs_releases()
    elif source == "pip":
        versions = _pypi_versions(spec.primary("pip") or spec.id)
    elif source == "conda":
        versions = _conda_versions(settings, spec)
    else:
        return {"id": tool_id, "source": "", "versions": [],
                "note": f"{spec.name} is not installed from an index this can query"}
    return {"id": tool_id, "source": source, "versions": versions,
            "latest": _newest(versions)}


def _version_number(text: str) -> str:
    """The version out of a banner: ``GROMACS version 2025.4`` -> ``2025.4``."""
    match = re.search(r"\b(\d+(?:\.\d+)+(?:[-.][A-Za-z0-9]+)?)\b", str(text or ""))
    return match.group(1) if match else str(text or "").strip()


def check_updates(settings: Settings, tools: Optional[List[str]] = None,
                  workers: int = 6) -> List[Dict[str, Any]]:
    """Installed version against newest available, for every tool at once.

    Deliberately behind a button rather than folded into the environment
    survey: a conda search is twenty seconds a package, and paying that on every
    visit to the dialog would make the dialog feel broken.
    """
    toolbox = Toolbox(settings)
    wanted = [t for t in (tools or list(CATALOG))
              if t in CATALOG and t != "shell" and CATALOG[t].versions_from]

    def one(tool_id: str) -> Dict[str, Any]:
        probe = toolbox.probe(tool_id)
        found = available_versions(settings, tool_id)
        installed = _version_number(probe.get("version", ""))
        latest = found.get("latest", "")
        newer = bool(installed and latest
                     and version_key(latest) > version_key(installed))
        return {
            "id": tool_id,
            "name": CATALOG[tool_id].name,
            "present": probe.get("found", False),
            "installed": installed,
            "raw": probe.get("version", ""),
            "latest": latest,
            # Newest last everywhere else; the editor wants newest first.
            "versions": list(reversed(found.get("versions", [])))[:60],
            "source": found.get("source", ""),
            "newer": newer,
            "note": found.get("note", ""),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, wanted))


# --------------------------------------------------------------------------
# Building GROMACS the way you actually want it
# --------------------------------------------------------------------------

#: What ``-DGMX_GPU`` will take. "none" is not a value cmake knows; it means
#: leave the flag off.
GPU_BACKENDS = ("none", "CUDA", "OpenCL", "SYCL", "HIP")

#: Only the ones worth choosing by hand. AUTO detects the build machine, which
#: is wrong exactly when the build machine is not the run machine.
SIMD_CHOICES = ("AUTO", "SSE2", "SSE4.1", "AVX_128_FMA", "AVX_256", "AVX2_128",
                "AVX2_256", "AVX_512", "ARM_NEON_ASIMD", "ARM_SVE", "None")


def gromacs_build_plan(settings: Settings, options: Dict[str, Any]) -> Dict[str, Any]:
    """Everything about a source build: the flags, the prefix, the script.

    A source build is what the conda package cannot give you -- GPU support,
    MPI, a SIMD level chosen for the machine it will run on -- and it is also
    an hour of somebody's afternoon, so what it is going to do is worked out
    and shown before anything starts.
    """
    version = str(options.get("version") or "").strip()
    if not re.match(r"^\d+(\.\d+)*$", version):
        return {"error": f"'{version}' is not a GROMACS version number"}

    default_prefix = Path(os.path.expanduser("~/soft/gromacs")) / f"gromacs-{version}"
    prefix = Path(os.path.expanduser(str(options.get("prefix") or default_prefix)))
    gpu = str(options.get("gpu") or "none")
    if gpu not in GPU_BACKENDS:
        return {"error": f"'{gpu}' is not a GPU backend cmake knows"}
    simd = str(options.get("simd") or "AUTO")
    if simd not in SIMD_CHOICES:
        return {"error": f"'{simd}' is not a SIMD level this offers"}
    mpi = bool(options.get("mpi"))
    double = bool(options.get("double"))
    own_fftw = options.get("own_fftw", True)
    tests = bool(options.get("tests"))
    jobs = max(1, int(options.get("jobs") or (os.cpu_count() or 4)))
    suffix = str(options.get("suffix") or "").strip()

    flags = [
        f"-DCMAKE_INSTALL_PREFIX={shlex.quote(str(prefix))}",
        f"-DGMX_BUILD_OWN_FFTW={'ON' if own_fftw else 'OFF'}",
        f"-DGMX_MPI={'ON' if mpi else 'OFF'}",
        f"-DGMX_DOUBLE={'ON' if double else 'OFF'}",
        f"-DGMX_SIMD={simd}",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    if gpu != "none":
        flags.append(f"-DGMX_GPU={gpu}")
    if suffix:
        flags.append(f"-DGMX_BINARY_SUFFIX={shlex.quote(suffix)}")
        flags.append(f"-DGMX_LIBS_SUFFIX={shlex.quote(suffix)}")
    for extra in shlex.split(str(options.get("extra_cmake") or "")):
        flags.append(extra)

    # An MPI build installs gmx_mpi and no gmx at all, so the binary name is
    # part of the answer, not a detail: registering the wrong one leaves every
    # node reporting "gmx: not found" against a perfectly good install.
    binary = "gmx"
    if mpi:
        binary += "_mpi"
    if double:
        binary += "_d"
    binary += suffix

    tarball = f"gromacs-{version}.tar.gz"
    url = f"{GROMACS_INDEX}{tarball}"
    parent = prefix.parent
    writable = os.access(parent if parent.exists() else parent.parent, os.W_OK)

    # Is this already built? Read off the prefix rather than running anything:
    # the dialog re-plans on every keystroke and an hour-long build must not be
    # started twice by accident.
    existing = ""
    gmxrc_here = prefix / "bin" / "GMXRC"
    if gmxrc_here.is_file():
        existing = _prefix_version(prefix) or "an unknown version"
    force = bool(options.get("force"))

    # What the build needs, worked out before any of the return paths: a
    # dialog that says "already installed" should still be able to say the
    # machine could not build another one anyway.
    toolchain = missing_toolchain(settings)
    # Whether the chosen backend could build at all. cmake finds this out too,
    # ninety seconds in, as `Could not find a package configuration file
    # provided by "HIP"`. Knowing first is a disabled option instead of a
    # failed build.
    gpus = gpu_support()
    gpu_state = gpus["backends"].get(gpu, {"available": True, "note": "",
                                           "command": "", "url": "",
                                           "driver_ok": True, "runtime_ok": True})
    gpu_usable = (gpu_state["available"] and gpu_state.get("driver_ok", True)
                  and gpu_state.get("runtime_ok", True))

    lines = [
        "set -euo pipefail",
        "export LC_ALL=C",
        f'echo ">> GROMACS {version} -> {prefix}"',
    ]
    # A build tool that exists but is not on PATH -- cmake inside a conda
    # environment is the usual one -- is put on PATH here rather than reported
    # as missing. Only that directory, and only when something needed is in it:
    # this is not activating the environment, which would bring its libraries
    # and its idea of a compiler along with it.
    for found in toolchain["elsewhere"]:
        lines += [
            f'echo ">> using the {found["command"]} from the {found["env"]} '
            f'environment: {found["path"]}"',
            f'export PATH="{found["bin"]}:$PATH"',
        ]
    if existing and not force:
        # Belt as well as braces: the dialog says so too, but a script that can
        # be copied and run by hand has to refuse on its own.
        lines += [
            f'echo ">> {prefix}/bin/GMXRC already exists ({existing})."',
            "echo '>> Nothing to do. Tick the rebuild box to replace it, or "
            "choose a different prefix to keep both.'",
            "exit 0",
        ]
        return {
            "version": version, "prefix": str(prefix),
            "gmxrc": str(prefix / "bin" / "GMXRC"), "binary": binary,
            "flags": flags, "jobs": jobs, "writable": writable,
            "existing": existing, "already": True, "toolchain": toolchain,
            "gpus": gpus, "gpu_ok": gpu_usable, "gpu_state": gpu_state,
            "notes": [f"{prefix} already holds GROMACS {existing}. Building would "
                      "replace it -- point the prefix somewhere else to keep both, "
                      "or tick the box to rebuild in place."],
            "script": "\n".join(lines),
        }
    lines += [
        'echo ">> checking the toolchain"',
        "for tool in cmake make curl tar; do",
        '  command -v "$tool" >/dev/null 2>&1 || '
        '{ echo ">> FAILED: $tool is not on PATH" >&2; exit 1; }',
        "done",
        'command -v c++ >/dev/null 2>&1 || command -v g++ >/dev/null 2>&1 || '
        '{ echo ">> FAILED: no C++ compiler on PATH" >&2; exit 1; }',
    ]
    if mpi:
        lines.append('command -v mpicc >/dev/null 2>&1 || '
                     'echo ">> WARNING: no mpicc on PATH; cmake will look for MPI itself"')
    if gpu == "CUDA":
        lines.append('command -v nvcc >/dev/null 2>&1 || '
                     'echo ">> WARNING: no nvcc on PATH; the CUDA build will fail '
                     'unless cmake finds the toolkit another way"')
    lines += [
        "cmake --version | head -n 1",
        # Where the source is unpacked, so the cleanup at the end can name it
        # rather than removing whatever it happens to be standing in.
        '__here=$(pwd)',
        f'echo ">> downloading {tarball}"',
        f"curl -fsSL -o {shlex.quote(tarball)} {shlex.quote(url)}",
        f"tar xf {shlex.quote(tarball)}",
        f"cd gromacs-{version}",
        "mkdir -p build && cd build",
        'echo ">> configuring"',
        "cmake .. " + " ".join(flags),
        f'echo ">> building with {jobs} job(s) -- this is the long part"',
        f"make -j{jobs}",
    ]
    if tests:
        lines += ['echo ">> running the test suite"', f"make -j{jobs} check"]
    lines += [
        'echo ">> installing"',
        "make install",
        f'echo ">> done: {prefix}/bin/GMXRC"',
        f"ls -l {shlex.quote(str(prefix / 'bin'))}",
    ]
    if not options.get("keep_build"):
        # Only after a successful install, and only these two names. The tree is
        # most of a gigabyte and the install prefix is what was wanted; on a
        # failure `set -e` has already stopped short of here, which is right,
        # because a failed build is exactly when you want to look at it.
        lines += [
            'cd "$__here"',
            f'rm -rf "$__here/gromacs-{version}" "$__here/gromacs-{version}.tar.gz"',
            'echo ">> removed the build tree; the install itself is untouched"',
        ]

    notes = []
    if gpu != "none" and not gpu_state.get("driver_ok", True):
        here = ", ".join(gpu_state.get("drivers_here") or []) or "none"
        notes.append(
            f"{gpu} needs a driver this machine is not running (loaded: {here}). "
            "Comfy-gmx will not install a graphics driver -- that is a kernel "
            "module, usually a reboot, and getting it wrong costs you the "
            f"display. See {gpu_state.get('driver_url') or 'your vendor'}.")
    if gpu != "none" and gpu_state.get("driver_ok", True) \
            and not gpu_state.get("runtime_ok", True):
        notes.append(
            f"the {gpu_state.get('runtime')} runtime library is not where the "
            "loader would find it. GROMACS would build and then fail to start; "
            "this usually means the driver is only half installed.")
    if not gpu_state["available"]:
        notes.append(f"{gpu} was chosen, and its toolkit is not installed here. "
                     "The build would get through downloading and unpacking and "
                     "then stop at cmake.")
    if gpu_state.get("note") and gpu != "none":
        notes.append(gpu_state["note"])
    if gpu == "none" and gpus["suggested"] == "none" and gpus["devices"]:
        notes.append("CPU only, which is the right choice here: "
                     + ", ".join(f"{d['vendor']}"
                                 + (" integrated" if d.get("integrated") else "")
                                 for d in gpus["devices"])
                     + " has no usable GROMACS backend on this machine.")
    for found in toolchain["elsewhere"]:
        notes.append(f"{found['command']} is not on PATH but is in the "
                     f"{found['env']} environment; the build puts that directory "
                     "on its own PATH rather than activating anything.")
    if toolchain["missing"]:
        notes.append("this machine cannot build it yet: "
                     + ", ".join(toolchain["missing"]) + " missing.")
    if existing:
        notes.append(f"{prefix} already holds GROMACS {existing} and this will "
                     "replace it.")
    if not writable:
        notes.append(f"{parent} is not writable by you. Either choose a prefix under "
                     "your home directory, or copy the script and run it yourself "
                     "with sudo -- this will not ask for a password on your behalf.")
    if gpu == "none" and not mpi and gpus["suggested"] != "none":
        notes.append(f"no GPU, on a machine where {gpus['suggested']} would work. "
                     "Fine if you meant it; GROMACS is perfectly good on CPUs.")
    if simd == "AUTO":
        notes.append("SIMD is AUTO, which detects the machine doing the building. "
                     "Set it explicitly if that is not the machine that will run it.")
    if tests:
        notes.append("the test suite roughly doubles the build time.")

    return {
        "version": version,
        "prefix": str(prefix),
        "gmxrc": str(prefix / "bin" / "GMXRC"),
        "binary": binary,
        "flags": flags,
        "jobs": jobs,
        "notes": notes,
        "writable": writable,
        "existing": existing,
        "already": False,
        "toolchain": toolchain,
        "gpus": gpus,
        "gpu_ok": gpu_usable,
        "gpu_state": gpu_state,
        "script": "\n".join(lines),
    }


# --------------------------------------------------------------------------
# What this machine could actually build GROMACS against
# --------------------------------------------------------------------------

#: PCI vendor id -> who makes it. Read from /sys, which needs no tools.
_GPU_VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}

#: Each GPU backend, what proves its toolkit is installed, and how to get it.
#: Packages only where they are genuinely in the distribution's own repositories
#: -- naming one that does not exist is worse than naming none.
_GPU_TOOLKITS = {
    "CUDA": {
        "vendor": "NVIDIA",
        "probes": ["nvcc"],
        "prefixes": ["/usr/local/cuda*/bin/nvcc", "/opt/cuda*/bin/nvcc"],
        "packages": {"arch": ["cuda"], "debian": ["nvidia-cuda-toolkit"]},
        "url": "https://developer.nvidia.com/cuda-downloads",
        "drivers": ("nvidia", "nvidia_drm"),
        "runtime": "libcuda.so.1",
        "driver_url": "https://www.nvidia.com/download/index.aspx",
    },
    "HIP": {
        "vendor": "AMD",
        "probes": ["hipcc"],
        "prefixes": ["/opt/rocm*/bin/hipcc"],
        "packages": {"arch": ["rocm-hip-sdk"]},
        "url": "https://rocm.docs.amd.com/",
        "drivers": ("amdgpu",),
        "runtime": "libamdhip64.so",
        "driver_url": "https://rocm.docs.amd.com/projects/install-on-linux/",
        "note": "ROCm supports discrete Radeon cards. The integrated Radeon in a "
                "Ryzen APU is not on its support list, and GROMACS on one is "
                "usually slower than the CPU it shares memory with.",
    },
    "SYCL": {
        "vendor": "Intel",
        "probes": ["icpx", "acpp", "syclcc"],
        "prefixes": ["/opt/intel/oneapi/compiler/*/bin/icpx"],
        "packages": {},
        "url": "https://www.intel.com/content/www/us/en/developer/tools/oneapi/dpc-compiler.html",
        "drivers": ("i915", "xe"),
        "runtime": "",
        "driver_url": "https://dgpu-docs.intel.com/",
    },
    "OpenCL": {
        "vendor": "",
        "probes": ["clinfo"],
        "prefixes": ["/etc/OpenCL/vendors/*.icd", "/usr/lib*/libOpenCL.so*",
                     "/usr/lib/*/libOpenCL.so*"],
        "packages": {"arch": ["opencl-headers", "ocl-icd"],
                     "debian": ["opencl-headers", "ocl-icd-opencl-dev"]},
        "url": "https://www.khronos.org/opencl/",
        "drivers": (),
        "runtime": "libOpenCL.so.1",
        "driver_url": "",
        "note": "GROMACS has deprecated its OpenCL backend in favour of SYCL.",
    },
}


def _has_library(name: str) -> bool:
    """Is this shared library where the dynamic loader would find it?

    The runtime half of GPU support, and a different thing from the toolkit: a
    build needs nvcc, a run needs libcuda.so.1, and that one comes with the
    driver rather than with the SDK. Installing the toolkit and nothing else
    gets you a GROMACS that compiles and then cannot start.
    """
    try:
        listing = subprocess.run(["ldconfig", "-p"], capture_output=True,
                                 text=True, timeout=15)
        if listing.returncode == 0 and name in listing.stdout:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    for directory in ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu",
                      "/opt/rocm/lib", "/usr/local/cuda/lib64"):
        if glob.glob(str(Path(directory) / (name + "*"))):
            return True
    return False


def gpu_devices() -> List[Dict[str, str]]:
    """Which graphics devices this machine has, from /sys.

    No lspci, no vendor tools: the PCI vendor id is a file, and that is enough
    to say whether choosing CUDA on a machine with only an AMD card is a
    mistake.
    """
    found = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        if "-" in card.name:                     # card0-DP-1 and friends are outputs
            continue
        try:
            vendor = (card / "device" / "vendor").read_text().strip().lower()
        except OSError:
            continue
        name = _GPU_VENDORS.get(vendor)
        if not name:
            continue
        entry = {"card": card.name, "vendor": name}
        # Which kernel driver is bound. A card with nouveau, or none at all,
        # cannot run CUDA however much toolkit is installed.
        try:
            entry["driver"] = (card / "device" / "driver").resolve().name
        except OSError:
            pass
        # AMD exposes its VRAM size, which is how an APU carve-out gives itself
        # away: a discrete card does not have 512 MB.
        try:
            total = int((card / "device" / "mem_info_vram_total").read_text().strip())
            entry["vram"] = str(total)
            if name == "AMD" and total < 2 * 1024 ** 3:
                entry["integrated"] = "yes"
        except (OSError, ValueError):
            pass
        found.append(entry)
    return found


def gpu_support() -> Dict[str, Any]:
    """Which GPU backends could actually be built here, and what is missing.

    cmake finds this out too, about ninety seconds in, and says
    ``Could not find a package configuration file provided by "HIP"``. Knowing
    beforehand is the difference between a disabled option and a failed build.
    """
    from . import bootstrap                      # circular at module level

    plat = bootstrap.detect()
    devices = gpu_devices()
    vendors = {device["vendor"] for device in devices}

    backends: Dict[str, Any] = {"none": {"available": True, "found": "",
                                         "note": "CPU only.", "command": "", "url": ""}}
    for name, spec in _GPU_TOOLKITS.items():
        found = next((shutil.which(p) for p in spec["probes"] if shutil.which(p)), "")
        if not found:
            for pattern in spec["prefixes"]:
                hit = sorted(glob.glob(pattern))
                if hit:
                    found = hit[-1]
                    break
        packages = spec["packages"].get(plat["family"], [])
        note = spec.get("note", "")
        if spec["vendor"] and vendors and spec["vendor"] not in vendors:
            note = (f"This machine has no {spec['vendor']} graphics "
                    f"({', '.join(sorted(vendors))} instead). " + note).strip()

        # Three separate things, and only one of them is ours to help with.
        # The kernel driver makes the card work at all; the runtime library is
        # what a built GROMACS loads; the toolkit is what building needs. A
        # toolkit with no driver builds fine and then fails at the first mdrun.
        wanted_drivers = spec.get("drivers") or ()
        drivers = {d.get("driver", "") for d in devices if d["vendor"] == spec["vendor"]}
        driver_ok = (not wanted_drivers
                     or any(d in wanted_drivers for d in drivers))
        runtime = spec.get("runtime") or ""
        runtime_ok = (not runtime) or _has_library(runtime)

        backends[name] = {
            "available": bool(found),
            "found": found,
            "note": note,
            "command": bootstrap.system_command(plat, packages) if packages else "",
            "url": spec["url"],
            "vendor": spec["vendor"],
            "driver_ok": driver_ok,
            "drivers_here": sorted(d for d in drivers if d),
            "driver_url": spec.get("driver_url", ""),
            "runtime": runtime,
            "runtime_ok": runtime_ok,
        }

    # What to pick, if anything. An integrated Radeon is not a recommendation:
    # ROCm does not support it and the CPU beside it is faster.
    suggested = "none"
    for device in devices:
        if device.get("integrated") == "yes":
            continue
        for name, spec in _GPU_TOOLKITS.items():
            state = backends[name]
            if (spec["vendor"] == device["vendor"] and state["available"]
                    and state["driver_ok"] and state["runtime_ok"]):
                suggested = name
                break
        if suggested != "none":
            break
    return {"devices": devices, "backends": backends, "suggested": suggested,
            "vendors": sorted(vendors)}


#: What a source build needs on PATH, and why, so a missing one can say which.
#: Every external thing an install or a build can want, with the commands that
#: prove it is here, which package provides it, and why it is wanted.  One
#: table so a tool declares what it needs by name and the checking is shared.
REQUIREMENTS = {
    "cmake":  (["cmake"], "cmake", "configures the build"),
    "make":   (["make"], "toolchain", "runs it"),
    "c++":    (["c++", "g++", "clang++"], "toolchain", "compiles it"),
    "curl":   (["curl"], "curl", "fetches the source"),
    "tar":    (["tar"], "tar", "unpacks it"),
    "git":    (["git"], "git", "pip installs this one straight from a git repository"),
    # Not a system package: setup installs it, so its route is that dialog.
    "conda":  (["conda"], "", "creates and activates the environment"),
}

#: What a GROMACS source build needs.
BUILD_TOOLCHAIN = ["cmake", "make", "c++", "curl", "tar"]


def check_requirements(settings: Optional[Settings] = None,
                       wants: Optional[List[str]] = None) -> Dict[str, Any]:
    """Which of these are absent, where copies are hiding, and how to fix it.

    Whatever is going to run checks these too -- it has to, a generated script
    can be copied to another machine -- but by then the dialog has promised
    something. Knowing beforehand turns "FAILED: cmake is not on PATH", two
    seconds into a build, into a disabled button next to the line that fixes it.

    It looks inside conda environments as well, because "not on PATH" and "not
    installed" are different problems with different answers. Something sitting
    in an environment nobody activated fails exactly like nothing at all, and
    being told to install what you already have is not much of an answer.
    """
    from . import bootstrap                      # circular at module level

    wants = list(wants if wants is not None else BUILD_TOOLCHAIN)
    settings = settings or Settings()

    env_bins: List[tuple] = []
    try:
        for env in Toolbox(settings).conda_envs():
            env_bins.append((env["name"], Path(env["path"]) / "bin"))
    except Exception:                            # noqa: BLE001 - no conda is fine
        pass

    missing, packages, elsewhere = [], [], []
    conda_missing = False
    for want in wants:
        names, package, why = REQUIREMENTS.get(want, ([want], "", ""))
        if any(shutil.which(name) for name in names):
            continue
        if want == "conda":
            # conda is not something to send anyone to a package manager for;
            # first-run setup installs it, and that is where to point.
            conda_missing = not bool(detect_conda_root(settings))
            if conda_missing:
                missing.append(f"conda ({why})")
            continue
        # Found in an environment is not the same as absent: a build script can
        # put that directory on its own PATH, which is a fix rather than an error.
        hit = None
        for env_name, bin_dir in env_bins:
            hit = next((bin_dir / name for name in names if (bin_dir / name).exists()), None)
            if hit is not None:
                elsewhere.append({"command": want, "env": env_name,
                                  "path": str(hit), "bin": str(bin_dir)})
                break
        if hit is not None:
            continue
        missing.append(f"{want} ({why})")
        if package:
            packages.append(package)

    plat = bootstrap.detect()
    names = []
    for package in dict.fromkeys(packages):
        names.extend(bootstrap._PACKAGES.get(package, {}).get(plat["family"], []))

    routes = []
    if conda_missing:
        routes.append({
            "kind": "setup",
            "label": "conda comes from first-run setup",
            "command": "",
            "needs_root": False,
            "note": "Open Set up this machine and let it install conda; nothing here "
                    "needs root.",
        })
    if names:
        command = bootstrap.system_command(plat, list(dict.fromkeys(names)))
        if command:
            routes.append({
                "kind": "system",
                "label": f"With {plat['manager']}, on {plat['pretty']}",
                "command": command,
                "needs_root": bool(plat["needs_sudo"]),
                "note": "Needs root, so run it in a terminal where the password "
                        "prompt is visible.",
            })

    # cmake is the one piece of a build that can be had without root. A compiler
    # cannot, so the rootless routes are offered only when cmake is the whole
    # problem -- otherwise they solve half of it and it still fails.
    only_cmake = bool(missing) and all(m.startswith("cmake") for m in missing)
    conda_root = detect_conda_root(settings)
    if only_cmake and conda_root:
        routes.append({
            "kind": "conda",
            "label": "From conda, which is already here and needs no root",
            "command": f"{Path(conda_root) / 'bin' / 'conda'} install -y -n base "
                       "-c conda-forge cmake",
            "needs_root": False,
            "note": "Goes into the base environment, so it is on PATH whenever conda "
                    "is. Restart the server afterwards.",
        })
    if only_cmake and _pip_usable():
        routes.append({
            "kind": "pip",
            "label": "From PyPI, which ships real cmake binaries",
            "command": "python3 -m pip install --user cmake",
            "needs_root": False,
            "note": "Puts it in ~/.local/bin, which has to be on your PATH.",
        })

    return {
        "missing": missing,
        "command": routes[0]["command"] if routes else "",
        "distro": plat["pretty"],
        "elsewhere": elsewhere,
        "routes": routes,
        "pip": _pip_usable(),
    }


def missing_toolchain(settings: Optional[Settings] = None) -> Dict[str, Any]:
    """What a GROMACS source build is short of."""
    return check_requirements(settings, BUILD_TOOLCHAIN)


def install_requirements(settings: Settings, tool_id: str) -> Dict[str, Any]:
    """What has to be here before this tool can be installed at all.

    conda always, because that is where it goes, plus whatever the recipe
    itself reaches for -- TS2CG is a pip install straight from a git URL, which
    is a clone, which needs git.
    """
    spec = CATALOG.get(tool_id)
    if spec is None:
        raise KeyError(tool_id)
    wants: List[str] = []
    if spec.conda_installable:
        wants.append("conda")
    if spec.repo or any(str(pkg).startswith(("git+", "git://"))
                        for pkg in spec.pip_packages):
        wants.append("git")
    wants.extend(spec.needs)
    result = check_requirements(settings, list(dict.fromkeys(wants)))
    result["tool"] = tool_id
    result["checked"] = list(dict.fromkeys(wants))
    return result


def _pip_usable() -> bool:
    """Is there a pip here, and would it be allowed to install anything?

    Two separate questions and both have to be yes. Arch does not install pip
    with Python at all, and most current distributions -- Arch, Debian 12,
    Fedora 38 and up -- mark the system interpreter externally managed under
    PEP 668, which makes `pip install --user` refuse rather than proceed.
    Suggesting it in either case is advice that produces an error message.
    """
    import importlib.util
    import sysconfig

    if importlib.util.find_spec("pip") is None and not shutil.which("pip3"):
        return False
    for key in ("stdlib", "purelib"):
        try:
            marker = Path(sysconfig.get_path(key)) / "EXTERNALLY-MANAGED"
        except (KeyError, TypeError):
            continue
        if marker.exists():
            return False
    return True


# --------------------------------------------------------------------------
# Several versions of the same tool, side by side
# --------------------------------------------------------------------------

def env_name_for(spec: ToolSpec, version: str = "") -> str:
    """Where a given version of a tool should be installed.

    Without a version, the conventional name -- ``modeller``. With one,
    ``modeller-10.6``, so asking for a second version installs it beside the
    first instead of over the top of it. Someone who wants them in the same
    place can still say so; the point is that the default does not silently
    replace a working install.
    """
    base = spec.suggested_env or f"comfygmx-{spec.id}"
    version = re.sub(r"[^A-Za-z0-9._+-]", "", str(version or "").strip())
    return f"{base}-{version}" if version else base


def _recorded(settings: Settings, tool_id: str) -> List[Dict[str, str]]:
    entry = (settings.get("tools") or {}).get(tool_id) or {}
    found = entry.get("installs")
    return list(found) if isinstance(found, list) else []


def remember_install(settings: Settings, tool_id: str, env: str, version: str = "") -> None:
    """Note that this tool is now in this environment, without forgetting the
    others. The newest one becomes the active one, which is what someone who
    just asked for it expects; switching back is one click."""
    tools = dict(settings.get("tools") or {})
    entry = dict(tools.get(tool_id) or {})
    installs = [dict(i) for i in _recorded(settings, tool_id) if i.get("env") != env]
    installs.append({"env": env, "version": str(version or "")})
    installs.sort(key=lambda i: version_key(i.get("version") or ""))
    entry["installs"] = installs
    entry["env"] = env
    tools[tool_id] = entry
    settings.update({"tools": tools})
    settings.save()
