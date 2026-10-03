"""Paths, persisted settings and the shell prelude used for every command.

Two environment traps from day-to-day GROMACS use are handled here rather than
in each node:

* ``GMXRC`` is not ``set -u`` safe -- it reads ``$shell`` and ``$GMXLDLIB``
  before assigning them, so it is sourced with ``set +u +e`` and the shell
  options are restored afterwards.
* A non-English ``LC_NUMERIC`` makes ``printf "%.3f"`` emit ``0,000``, which
  then fails ``float()``.  Every command runs under ``LC_ALL=C``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"
MDP_DIR = PKG_DIR / "mdp"

#: The lite version keeps its runs, cache and saved graphs apart from the full
#: version's, so a class's runs never mix with research ones.
DEFAULT_HOME = Path(os.environ.get("COMFYGMX_HOME", Path.home() / ".comfy-gmx-lite"))

#: The full version's folder. Until the lite version has a settings file of
#: its own, it reads the full version's -- where GROMACS is, which conda --
#: but never its folders, and it never writes there.
FULL_HOME = Path.home() / ".comfy-gmx"

#: Settings that name the full version's own folders, so are not borrowed.
_NOT_BORROWED = ("data_dir", "output_dir", "workflow_dirs")


def _default_settings() -> Dict[str, Any]:
    return {
        # Where runs, uploads and saved workflows live.
        "data_dir": str(DEFAULT_HOME),
        # Where run directories are created. Blank means <data_dir>/runs. A
        # session can override it, so this is only the default offered to a new
        # one -- put it on the big disk rather than in a home directory.
        "output_dir": "",
        # Absolute path to a GMXRC to source, or "" to use whatever `gmx` is
        # already on PATH.
        "gmxrc": "",
        # `gmx`, `gmx_mpi`, `gmx_d`, ...
        "gmx_binary": "gmx",
        # Root of the conda/mamba installation used to activate tool envs.
        "conda_root": "",
        # Logical tool id -> {"env": <conda env name or "">, "command": <exe>}
        "tools": {},
        # Default resources handed to `gmx mdrun` when a node leaves them blank.
        "mdrun": {"ntomp": 0, "ntmpi": 0, "gpu_id": "", "extra": ""},
        # What a simulation does about other work on this computer. With
        # "auto" on, a simulation whose threads nobody set gets only the cores
        # nothing else is using, and keeps off a graphics card another
        # simulation holds -- or shares it, as "gpu_busy" says: "ask" (in the
        # page, when Run is pressed), "processor" or "share". When nothing
        # else is running it changes nothing. See resources.py.
        "resources": {"auto": True, "gpu_busy": "ask"},
        # Where atomistic GROMACS force fields (folders ending in .ff) that
        # did not come with GROMACS are kept. Blank means
        # <data_dir>/forcefields/gromacs; GROMACS is told about it through
        # GMXLIB, so "Topology (pdb2gmx)" lists whatever is dropped in there.
        "gmx_forcefield_dir": "",
        # Extra directories to search for GROMACS installations, on top of the
        # built-in list. Walked, not globbed, so any depth works.
        "gmx_search_roots": [],
        # Extra directories the Open dialog lists workflows from, on top of
        # <data_dir>/workflows and the ones that ship with Comfy-gmx.
        "workflow_dirs": [],
        # Prefix every command with nice/ionice so a run cannot swamp the box.
        "nice": True,
        # How many nodes may run at once when the graph allows it. A graph
        # where four analyses hang off one trajectory ran them one after
        # another though they share nothing but an input. Simulation nodes are
        # exempt: mdrun takes every core it can see, so it waits for the rest
        # and runs alone. Set to 1 for the old strictly-serial behaviour.
        "max_parallel_nodes": 3,
    }


class Settings:
    """Small JSON-backed settings store, loaded once per server process."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_HOME / "settings.json"
        self.data = _default_settings()
        self.load()

    # -- persistence ----------------------------------------------------
    def load(self) -> None:
        source = self.path
        borrowed = False
        if (not source.exists() and "COMFYGMX_HOME" not in os.environ
                and source == DEFAULT_HOME / "settings.json"):
            source = FULL_HOME / "settings.json"
            borrowed = True
        if source.exists():
            try:
                stored = json.loads(source.read_text())
            except (OSError, json.JSONDecodeError):
                return
            if isinstance(stored, dict) and borrowed:
                stored = {key: value for key, value in stored.items()
                          if key not in _NOT_BORROWED}
            if isinstance(stored, dict):
                merged = _default_settings()
                merged.update(stored)
                # keep nested defaults for keys the file predates
                for key in ("mdrun", "resources"):
                    base = _default_settings()[key]
                    value = stored.get(key)
                    # A hand-edited file with something else there gets
                    # the defaults rather than a server that will not start.
                    if isinstance(value, dict):
                        base.update(value)
                    merged[key] = base
                self.data = merged

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)

    # -- accessors ------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def update(self, patch: Dict[str, Any]) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    # -- derived paths --------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return Path(self.data["data_dir"]).expanduser()

    @property
    def runs_dir(self) -> Path:
        configured = str(self.data.get("output_dir") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return self.data_dir / "runs"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def gmx_forcefield_dir(self) -> Path:
        """Where your own atomistic force fields go, one folder ending in .ff each.

        GROMACS looks for a force field in the folder it was installed with and
        in whatever GMXLIB points at. Every GROMACS command this tool runs gets
        GMXLIB set to this folder, so a charmm36-jul2022.ff dropped in here is
        offered by name on the topology block like the built-in ones.
        """
        configured = str(self.data.get("gmx_forcefield_dir") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return self.data_dir / "forcefields" / "gromacs"

    def gmx_share_top(self) -> Optional[Path]:
        """The folder of force fields GROMACS itself was installed with."""
        gmxrc = str(self.data.get("gmxrc") or "").strip()
        roots = []
        if gmxrc:
            roots.append(Path(gmxrc).expanduser().resolve().parent.parent)
        binary = str(self.data.get("gmx_binary") or "gmx").split()[0]
        found = shutil.which(binary)
        if found:
            roots.append(Path(found).resolve().parent.parent)
        for root in roots:
            top = root / "share" / "gromacs" / "top"
            if top.is_dir():
                return top
        return None

    def gromacs_forcefields(self) -> Dict[str, Any]:
        """Every force field the topology block can offer, and where each is from."""
        def names(folder: Optional[Path]) -> List[str]:
            if not folder or not folder.is_dir():
                return []
            return sorted(p.name[:-3] for p in folder.iterdir()
                          if p.is_dir() and p.name.endswith(".ff")
                          and (p / "forcefield.itp").exists())
        top = self.gmx_share_top()
        return {
            "dir": str(self.gmx_forcefield_dir),
            "dir_exists": self.gmx_forcefield_dir.is_dir(),
            "user": names(self.gmx_forcefield_dir),
            "builtin": names(top),
            "gmx_top": str(top) if top else "",
        }

    @property
    def workflows_dir(self) -> Path:
        return self.data_dir / "workflows"

    @property
    def chunks_dir(self) -> Path:
        """Chunks the user built themselves, one JSON file each."""
        return self.data_dir / "chunks"

    @property
    def sources_dir(self) -> Path:
        """Checkouts of tools that are a repository rather than a package.

        Some tools are not `pip install`-able at all: they are a clone you run
        in place, because they read data files sitting next to the script.
        Those land here, one directory per tool, so upgrading is a `git pull`
        in a place both the installer and the nodes can find without guessing.
        """
        return self.data_dir / "src"

    def source_dir(self, tool_id: str) -> Path:
        """The checkout a repo-backed tool is actually run from.

        Normally ``<data_dir>/src/<tool_id>``, which the installer owns: it
        clones there, pulls there, and on a failed sparse clone deletes and
        re-clones there.  Setting ``tools.<id>.source`` points at a checkout
        the user maintains instead -- a fork, a clone on another disk -- and
        the installer then leaves it alone entirely.

        A symlink at the managed path does the same job until something
        replaces it, at which point the tool quietly goes back to stock with
        nothing said.  A recorded path cannot be overwritten by accident, and
        it is visible in the panel that claims the tool is installed.
        """
        override = self.source_override(tool_id)
        return Path(override).expanduser() if override else self.sources_dir / tool_id

    def source_override(self, tool_id: str) -> str:
        """The user's own checkout for this tool, or "" if the installer owns it."""
        entry = (self.data.get("tools") or {}).get(tool_id) or {}
        return str(entry.get("source") or "").strip()

    def workflow_roots(self) -> list:
        """Every directory the Open dialog lists, most specific first.

        Saving only ever writes to the first one; the rest are there so the
        examples and the packaged tutorials that ship with Comfy-gmx are
        reachable without hunting for them on disk.
        """
        roots = [{"label": "saved here", "path": self.workflows_dir, "writable": True}]
        bundled = PKG_DIR.parent / "workflows"
        if bundled.is_dir():
            roots.append({"label": "shipped with Comfy-gmx",
                          "path": bundled, "writable": False})
            tutorials = bundled / "tutorials"
            if tutorials.is_dir():
                roots.append({"label": "packaged tutorials",
                              "path": tutorials, "writable": False})
        for extra in self.data.get("workflow_dirs") or []:
            path = Path(str(extra)).expanduser()
            if path.is_dir() and all(path != r["path"] for r in roots):
                roots.append({"label": str(path), "path": path, "writable": True})
        return roots

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.runs_dir, self.uploads_dir,
                     self.workflows_dir, self.chunks_dir, self.sources_dir,
                     self.gmx_forcefield_dir):
            path.mkdir(parents=True, exist_ok=True)
        readme = self.gmx_forcefield_dir / "README.txt"
        if not readme.exists():
            readme.write_text(GMX_FORCEFIELD_README)


GMX_FORCEFIELD_README = """\
Your own GROMACS force fields go here.

A force field is a folder whose name ends in .ff -- charmm36-jul2022.ff,
amber14sb.ff, and so on -- with a forcefield.itp inside it. Unpack the
archive you downloaded and put the whole .ff folder in this one, next to
this file.

Every GROMACS command Comfy-gmx runs is told to look here (through the
GMXLIB setting), so the moment a .ff folder is in place it appears in the
"Force field" list on the "Topology (pdb2gmx)" block, alongside the ones
GROMACS was installed with. Nothing needs restarting.

Where to get them:
  CHARMM36      https://mackerell.umaryland.edu/charmm_ff.shtml  (GROMACS format)
  AMBER ff14SB  https://github.com/... or the GROMACS user contributions
  GROMOS, OPLS  ship with GROMACS already
"""


def detect_conda_root(settings: Settings | None = None) -> str:
    """Best-effort location of a conda/mamba install we can activate from."""
    if settings and settings.get("conda_root"):
        return str(Path(settings.get("conda_root")).expanduser())
    for var in ("CONDA_ROOT", "MAMBA_ROOT_PREFIX"):
        if os.environ.get(var):
            return os.environ[var]
    exe = os.environ.get("CONDA_EXE")
    if exe:
        # <root>/bin/conda
        return str(Path(exe).resolve().parent.parent)
    for candidate in ("conda", "mamba", "micromamba"):
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve().parent.parent)
    for guess in ("miniconda3", "miniforge3", "mambaforge", "anaconda3", "micromamba"):
        path = Path.home() / guess
        if (path / "etc" / "profile.d" / "conda.sh").exists():
            return str(path)
    return ""


def conda_activate_snippet(conda_root: str, env: str) -> str:
    """Shell lines that activate ``env``, or "" when nothing has to happen."""
    if not env:
        return ""
    if not conda_root:
        # Fall back to whatever `conda` resolves to at run time.
        return f'eval "$(conda shell.bash hook)"\nconda activate {env}'
    hook = Path(conda_root) / "etc" / "profile.d" / "conda.sh"
    return f'source "{hook}"\nconda activate {env}'


def gmxlib_snippet(folder: Path) -> str:
    """Tell GROMACS about the folder of force fields the user keeps."""
    if not folder or not folder.is_dir():
        return ""
    return f'export GMXLIB="{folder}${{GMXLIB:+:$GMXLIB}}"'


def gmxrc_snippet(gmxrc: str) -> str:
    """Source GMXRC without letting its unset-variable reads kill the shell."""
    if not gmxrc:
        return ""
    return (
        "__comfygmx_opts=$-\n"
        "set +u +e\n"
        f'source "{gmxrc}"\n'
        'case "$__comfygmx_opts" in *u*) set -u ;; esac\n'
        'case "$__comfygmx_opts" in *e*) set -e ;; esac\n'
        "unset __comfygmx_opts"
    )


SETTINGS = Settings()
