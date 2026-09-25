"""Run engine: turns a graph into node work directories and running processes.

Design notes
------------
*Every node gets its own directory.*  Inputs are staged in by name, so the
command that runs is short, readable and reproducible by hand.

*Nodes are content-addressed.*  A node's signature covers its type, its
parameters and the signatures of everything upstream.  If a signature has been
completed before, the finished work directory is reused instead of re-running --
which matters when one node in the chain is a three-day mdrun.

*Large files are linked, not copied.*  Text-sized inputs are copied so a node
that rewrites a file in place cannot corrupt its upstream; trajectories and tprs
are hard-linked when possible and symlinked otherwise.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import stat
import threading
import time
import traceback
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Set

from .config import Settings
from .environments import Toolbox
from .graph import Graph, GraphError
from .nodes.base import NodeError, Plan, PlanContext, ToolMissing
from .registry import REGISTRY
from .runner import ProcessHandle, render_manual, render_script, render_step

#: Bumped whenever the shape of a stored output entry changes, so that entries
#: written by an older version are ignored rather than silently misread.
CACHE_VERSION = 2

#: Inputs at or below this size are copied; anything larger is linked.
COPY_LIMIT_BYTES = 4 * 1024 * 1024
MAX_LOG_LINES = 4000


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

class EventBus:
    """A run's messages, numbered, for any number of pages following it."""

    def __init__(self, history: int = 2000):
        self._lock = threading.Lock()
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._seq = 0
        self._condition = threading.Condition(self._lock)

    def emit(self, event: Dict[str, Any]) -> None:
        with self._condition:
            self._seq += 1
            event = dict(event)
            event["seq"] = self._seq
            event["t"] = time.time()
            self._history.append(event)
            self._condition.notify_all()

    def since(self, seq: int, timeout: float = 20.0) -> List[Dict[str, Any]]:
        with self._condition:
            pending = [e for e in self._history if e["seq"] > seq]
            if pending:
                return pending
            self._condition.wait(timeout)
            return [e for e in self._history if e["seq"] > seq]

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq


# --------------------------------------------------------------------------
# Staging helpers
# --------------------------------------------------------------------------

def _link_or_copy(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = source.stat().st_size
    except OSError:
        size = 0
    if size <= COPY_LIMIT_BYTES:
        shutil.copy2(source, target)
        # copy2 brings the mode along, and a read-only source makes a read-only
        # staged copy that the node it was staged for then cannot rewrite.
        _make_writable(target)
        return
    try:
        os.link(source, target)
        return
    except OSError:
        pass
    try:
        target.symlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def _make_writable(target: Path) -> None:
    try:
        target.chmod(target.stat().st_mode | stat.S_IWUSR)
    except OSError:
        pass


def _private_copy(target: Path) -> None:
    """Make sure writing to ``target`` cannot reach back to where it came from.

    A staged input over ``COPY_LIMIT_BYTES`` is a hard link or a symlink to the
    user's own file, so a node whose output happens to carry the same name --
    a topology read in and written out again, say -- would write straight
    through it and truncate the original.  Replacing it with a copy this run
    owns costs one file and removes the whole class of accident.
    """
    try:
        info = target.lstat()
    except OSError:
        return
    if stat.S_ISLNK(info.st_mode) and target.is_dir():
        # A staged folder is a link back to the node that made it. A node that
        # writes inside such a folder -- a CALVADOS run does, into the one its
        # setup wrote -- would be editing somebody else's finished result, and
        # if it is interrupted it leaves a half-written file there that the
        # next run reuses as though it were sound. Give it a real copy.
        source = target.resolve()
        spare = target.with_name(target.name + ".unshared")
        try:
            shutil.copytree(source, spare, symlinks=True)
            target.unlink()
            spare.rename(target)
        except OSError:
            shutil.rmtree(spare, ignore_errors=True)
        return
    if stat.S_ISDIR(info.st_mode):
        return
    shared = stat.S_ISLNK(info.st_mode) or info.st_nlink > 1
    if not shared and os.access(target, os.W_OK):
        return
    spare = target.with_name(target.name + ".unshared")
    try:
        shutil.copyfile(target, spare)          # follows a symlink, copies bytes
        target.unlink()
        spare.replace(target)
    except OSError:
        spare.unlink(missing_ok=True)
        return
    _make_writable(target)


def _output_names(plan: Plan):
    """The plain file names a plan says it will write."""
    for value in plan.outputs.values():
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key in ("file", "top"):
                if isinstance(value.get(key), str):
                    yield value[key]


def _stage_dir(source: Path, workdir: Path, dry: bool, on_dir=None) -> str:
    """Put a directory (a force field, say) into a node's work directory."""
    target = workdir / source.name
    if on_dir is not None:
        on_dir(source, target)
        return source.name
    if dry or not source.is_dir():
        return source.name
    try:
        if target.resolve() == source.resolve():
            return source.name
    except OSError:
        pass
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    try:
        # A force field is read-only text; a symlink is instant and costs nothing.
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)
    return source.name


def _materialise(plan: Plan, workdir: Path) -> Dict[str, Any]:
    """Turn a plan's declared outputs into concrete, absolute descriptors."""
    out: Dict[str, Any] = {}
    for port, value in plan.outputs.items():
        if isinstance(value, str):
            out[port] = {"kind": "file", "path": str(workdir / value), "name": value}
        elif isinstance(value, dict) and "value" in value:
            out[port] = {"kind": "text", "value": value["value"]}
        elif isinstance(value, dict) and "dir_path" in value:
            out[port] = {"kind": "dir", "path": str(workdir / value["dir_path"]),
                         "name": value["dir_path"]}
        elif isinstance(value, dict) and "file" in value:
            # A plain file that drags companions along -- a modified structure
            # and the residuetypes.dat that makes pdb2gmx accept it, say.
            out[port] = {
                "kind": "file",
                "path": str(workdir / value["file"]),
                "name": value["file"],
                "extra": [str(workdir / e) for e in (value.get("extra") or [])],
            }
        elif isinstance(value, dict):
            top = value.get("top")
            entry: Dict[str, Any] = {
                "dir": str(workdir),
                "glob": list(value.get("glob") or []),
                "extra": [str(workdir / e) for e in (value.get("extra") or [])],
                # Directories a topology needs beside it -- pdb2gmx writes
                # #include "./charmm36.ff/forcefield.itp" as a relative path, so
                # the force field has to follow the .top into every node that
                # reads it.
                "dirs": [str(workdir / d) for d in (value.get("dirs") or [])],
            }
            if top:
                entry["kind"] = "topology"
                entry["path"] = str(workdir / top)
                entry["name"] = top
            else:
                entry["kind"] = "bundle"
                # A bundle may still name the file the next node should look
                # at. Without that, a port described only by pattern has no
                # name at all before anything has run, and a node that needs
                # it reports itself as unconnected in the pre-run check.
                if value.get("name"):
                    entry["name"] = value["name"]
            out[port] = entry
        else:
            out[port] = {"kind": "text", "value": value}
    return out


def make_stage(workdir: Path, dry: bool, on_file=None,
               on_dir=None) -> Callable[[Any], Optional[str]]:
    """Build the ``stage`` callable handed to :class:`PlanContext`.

    ``on_file``/``on_dir`` replace the copy with something else, keeping the
    naming identical.  The exporter uses them to *record* what a node would
    stage instead of staging it -- the local names a command line refers to
    have to be exactly the ones a real run would produce, and the only way to
    guarantee that is to run the same code.
    """
    record = on_file is not None or on_dir is not None

    def bring(source: Path) -> None:
        if on_file is not None:
            on_file(source, workdir / source.name)
        elif source.exists():
            _link_or_copy(source, workdir / source.name)

    def stage(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            source = Path(value)
            if record or not dry:
                bring(source)
            return source.name
        if not isinstance(value, dict):
            return None

        kind = value.get("kind")
        if kind == "text":
            return None
        if kind == "dir":
            return _stage_dir(Path(value["path"]), workdir, dry, on_dir)

        for directory in value.get("dirs") or []:
            _stage_dir(Path(directory), workdir, dry, on_dir)

        names: List[str] = []
        if value.get("path"):
            source = Path(value["path"])
            names.append(source.name)
            if record or not dry:
                bring(source)
        for extra in value.get("extra") or []:
            source = Path(extra)
            if record or not dry:
                bring(source)
        source_dir = value.get("dir")
        if source_dir:
            base = Path(source_dir)
            for pattern in value.get("glob") or []:
                for match in sorted(base.glob(pattern)):
                    if match.is_file():
                        if record or not dry:
                            bring(match)
                        if not names:
                            names.append(match.name)
        # Only the last part of the name. A node may declare an output that
        # sits in a folder of its own -- "pylipid/sites_summary.csv" -- but
        # staging copies the file itself into the next node's folder and
        # nothing else. Handing on the name with the folder still on it points
        # the next node at a folder that is not there.
        if value.get("name"):
            plain = Path(value["name"]).name
            if plain not in names:
                names.insert(0, plain)
        return names[0] if names else None

    return stage


# --------------------------------------------------------------------------
# Dry planning (used for previews and the pre-flight check)
# --------------------------------------------------------------------------

def dry_plan(graph: Graph, settings: Settings) -> Dict[str, Dict[str, Any]]:
    """Build every node's plan without touching the filesystem."""
    results: Dict[str, Dict[str, Any]] = {}
    try:
        order = graph.topo_order()
    except GraphError as exc:
        return {"": {"error": str(exc), "plan": None, "outputs": {}}}

    produced: Dict[str, Dict[str, Any]] = {}
    for node_id in order:
        node = graph.nodes[node_id]
        node_type = node.get("type", "")
        entry: Dict[str, Any] = {"type": node_type, "error": "", "outputs": {}}
        if not REGISTRY.has(node_type):
            entry["error"] = f"unknown node type '{node_type}'"
            results[node_id] = entry
            continue
        cls = REGISTRY.get(node_type)
        params = dict(cls.defaults())
        params.update(node.get("params") or {})

        inputs: Dict[str, Any] = {}
        wired = graph.incoming(node_id)
        for port, (source, source_port) in wired.items():
            inputs[port] = (produced.get(source) or {}).get(source_port)

        workdir = Path(f"<{node_id}>")
        ctx = PlanContext(
            node_id=node_id, node_type=node_type, params=params, inputs=inputs,
            workdir=workdir, stage=make_stage(workdir, dry=True),
            settings=settings, dry=True,
        )
        try:
            plan = cls().plan(ctx)
        except ToolMissing as exc:
            entry["error"] = str(exc)
            entry["missing_tool"] = True
            results[node_id] = entry
            continue
        except NodeError as exc:
            entry["error"] = str(exc)
            # A node whose tool is missing takes everything downstream with it:
            # it produces no outputs, so the next node has nothing on the input
            # that should have carried them. Three things have to hold before
            # that counts as the same fact about the machine rather than a
            # defect: an upstream node was itself flagged, this node is
            # actually starved of an input it was wired for, and it declined
            # in the way a node declines -- a NodeError. A TypeError from a
            # broken node downstream of a missing tool is a real regression,
            # and flagging it too let those through the suite on every machine
            # without the optional checkouts.
            starved = any(inputs.get(port) is None for port in wired)
            if starved and any(results.get(source, {}).get("missing_tool")
                               for source, _ in wired.values()):
                entry["missing_tool"] = True
            results[node_id] = entry
            continue
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            entry["error"] = str(exc)
            results[node_id] = entry
            continue

        outputs = {}
        for port, value in plan.outputs.items():
            if isinstance(value, str):
                outputs[port] = {"kind": "file", "name": value}
            elif isinstance(value, dict) and "value" in value:
                outputs[port] = {"kind": "text", "value": value["value"]}
            elif isinstance(value, dict) and "dir_path" in value:
                outputs[port] = {"kind": "dir", "name": value["dir_path"],
                                 "path": value["dir_path"]}
            elif isinstance(value, dict) and "file" in value:
                outputs[port] = {"kind": "file", "name": value["file"],
                                 "extra": value.get("extra") or []}
            elif isinstance(value, dict):
                outputs[port] = {
                    "kind": "topology" if value.get("top") else "bundle",
                    "name": value.get("top") or value.get("name", ""),
                    "glob": value.get("glob") or [],
                    "extra": value.get("extra") or [],
                    "dirs": value.get("dirs") or [],
                }
            else:
                outputs[port] = {"kind": "text", "value": value}
        produced[node_id] = outputs
        entry["outputs"] = outputs
        entry["notes"] = plan.notes
        entry["files"] = list(plan.files.keys())
        entry["_plan"] = plan
        results[node_id] = entry
    return results


def preview_node(graph: Graph, node_id: str, settings: Settings) -> Dict[str, Any]:
    """Rendered commands for one node, exactly as they would be executed."""
    if node_id in graph.left_out:
        return {"error": graph.left_out_reason(node_id)}
    plans = dry_plan(graph, settings)
    entry = plans.get(node_id)
    if entry is None:
        return {"error": f"node '{node_id}' is not in the graph"}
    if entry.get("error"):
        return {"error": entry["error"]}
    plan: Plan = entry.pop("_plan")
    toolbox = Toolbox(settings)
    node = graph.nodes[node_id]
    env_override = (node.get("params") or {}).get("env_override", "") or ""

    def resolve(tool_id: str):
        return toolbox.resolve(tool_id, env_override)

    workdir = settings.runs_dir / "<run>" / f"{node_id}_{node.get('type','')}"
    return {
        "node": node_id,
        "type": node.get("type"),
        "workdir": str(workdir),
        "script": render_script(plan.steps, workdir, resolve,
                                nice=bool(settings.get("nice", True))),
        "manual": render_manual(plan.steps, workdir, resolve),
        "steps": [
            {"label": s.label, "tool": s.tool, "command": s.render(), "stdin": s.stdin or ""}
            for s in plan.steps
        ],
        "files": plan.files,
        "notes": plan.notes,
        "outputs": entry.get("outputs", {}),
        "error": "",
    }


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

#: What a run directory is called: the timestamp and the short id the executor
#: gives it. Nothing is deleted that does not match this *and* hold the
#: workflow.json every run writes -- an HTTP endpoint that removes directories
#: should be unable to remove anything but its own.
RUN_DIR_NAME = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def looks_like_run(path: Path) -> bool:
    return (path.is_dir() and bool(RUN_DIR_NAME.match(path.name))
            and (path / "workflow.json").is_file())


def resolve_output_dir(settings: Settings, output_dir: str = "") -> Path:
    """Where a run's directory should be created.

    A session may name its own folder; otherwise the configured default is
    used, which itself falls back to ``<data_dir>/runs``. A relative path is
    taken relative to the default rather than to whatever the server's working
    directory happens to be.
    """
    raw = (output_dir or "").strip()
    if not raw:
        return settings.runs_dir
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = settings.runs_dir / path
    return path


class NodeState:
    __slots__ = ("id", "type", "status", "started", "finished", "error",
                 "outputs", "notes", "log", "signature", "workdir", "returncode",
                 "progress")

    def __init__(self, node_id: str, node_type: str):
        self.id = node_id
        self.type = node_type
        self.status = "pending"
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.error = ""
        self.outputs: Dict[str, Any] = {}
        self.notes: List[str] = []
        self.log: Deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.signature = ""
        self.workdir = ""
        self.returncode: Optional[int] = None
        self.progress = ""

    def to_dict(self, with_log: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id, "type": self.type, "status": self.status,
            "started": self.started, "finished": self.finished,
            "error": self.error, "outputs": self.outputs, "notes": self.notes,
            "signature": self.signature, "workdir": self.workdir,
            "returncode": self.returncode, "progress": self.progress,
        }
        if with_log:
            data["log"] = list(self.log)
        return data


class Run:
    def __init__(self, run_id: str, graph: Graph, workdir: Path, label: str = "",
                 session: str = ""):
        self.id = run_id
        self.graph = graph
        self.workdir = workdir
        self.label = label
        #: Which browser session started this, so a reloaded page can find its
        #: own runs again among everyone else's.
        self.session = session
        self.status = "queued"
        self.created = time.time()
        self.finished: Optional[float] = None
        self.error = ""
        self.nodes: Dict[str, NodeState] = {}
        self.order: List[str] = []
        self.bus = EventBus()
        self.cancelled = False
        #: The processes in flight, by node. A dict rather than one handle
        #: because several nodes can be running at once, and Cancel has to
        #: reach every one of them.
        self.running: Dict[str, Any] = {}
        #: Every process group this run has ever started, kept after the node
        #: has finished with it. If a step leaves something behind -- a program
        #: that ignored the first stop, a child that outlived its parent --
        #: this is the only way left to find it and kill it.
        self.groups: Dict[str, int] = {}
        #: Which node the run is being held at, if any. A node can be marked
        #: "pause before this one" in the editor, and then the run stops there
        #: with everything before it finished, so you can look at what came out
        #: and change what happens next before letting it go on.
        self.paused: str = ""
        self.gate = threading.Condition()
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None

    def to_dict(self, with_log: bool = False) -> Dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "session": self.session,
            "status": self.status,
            "created": self.created, "finished": self.finished, "error": self.error,
            "workdir": str(self.workdir), "order": self.order,
            "nodes": {k: v.to_dict(with_log) for k, v in self.nodes.items()},
        }


class Executor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.runs: Dict[str, Run] = {}
        self._lock = threading.Lock()
        # Runs execute concurrently, one thread each, and every one of them
        # reads and writes the shared cache index. Without this lock two runs
        # finishing a node at the same moment can lose one of the entries.
        self._cache_lock = threading.Lock()
        self._cache_path = settings.data_dir / "cache" / "index.json"
        self._cache: Dict[str, Any] = {}
        self._load_cache()
        # How long each kind of node has taken here, so a forecast can say
        # "about two hours" instead of "3 nodes". Kept per node type rather
        # than per node: the question is how long a solvate takes on this
        # machine, and the answer does not depend on which solvate it was.
        self._timing_path = settings.data_dir / "cache" / "timings.json"
        self._timings: Dict[str, List[float]] = {}
        try:
            self._timings = json.loads(self._timing_path.read_text())
        except (OSError, json.JSONDecodeError):
            self._timings = {}
        self._timing_seen = self._stamp(self._timing_path)

    # -- cache ----------------------------------------------------------
    def _load_cache(self) -> None:
        try:
            self._cache = json.loads(self._cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            self._cache = {}
        self._cache_seen = self._stamp(self._cache_path)

    @staticmethod
    def _stamp(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _refresh(self) -> None:
        """Re-read the index and the timings if another process wrote them.

        The server holds them in memory; `comfy-gmx run` on the command line is
        a second process writing the same two files. Without this the editor
        goes on believing a graph will run for an hour after the terminal has
        already run it -- and the forecast made that visible, since it says out
        loud what the cache thinks.
        """
        stamp = self._stamp(self._cache_path)
        if stamp and stamp != getattr(self, "_cache_seen", 0.0):
            try:
                self._cache = json.loads(self._cache_path.read_text())
                self._cache_seen = stamp
            except (OSError, json.JSONDecodeError):
                pass
        stamp = self._stamp(self._timing_path)
        if stamp and stamp != getattr(self, "_timing_seen", 0.0):
            try:
                self._timings = json.loads(self._timing_path.read_text())
                self._timing_seen = stamp
            except (OSError, json.JSONDecodeError):
                pass

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._cache, indent=1))
        tmp.replace(self._cache_path)
        self._cache_seen = self._stamp(self._cache_path)

    @staticmethod
    def _entry_alive(entry: Dict[str, Any]) -> bool:
        """Are this entry's files still where it says they are?

        The one question the cache has to keep asking. A user deleting a run
        directory is expected -- that is what "I do not need these results" is
        -- and the answer is that the node runs again, not that anything
        breaks.
        """
        if entry.get("version") != CACHE_VERSION:
            return False
        if not Path(entry.get("workdir", "")).is_dir():
            return False
        for value in (entry.get("outputs") or {}).values():
            if value.get("absent"):
                # Never written in the first place; nothing to have lost.
                continue
            path = value.get("path")
            if path and not Path(path).exists():
                return False
        return True

    def _cache_lookup(self, signature: str) -> Optional[Dict[str, Any]]:
        with self._cache_lock:
            entry = self._cache.get(signature)
            if not entry:
                return None
            if self._entry_alive(entry):
                return entry
            # Dropped *and written out*. Popping from the dict alone left the
            # dead entry in index.json until something else happened to save,
            # so an index only ever shrank by accident: 86 of 150 entries here
            # pointed at files deleted months ago.
            self._cache.pop(signature, None)
            self._save_cache()
            return None

    def cached_result(self, signature: str) -> Optional[Dict[str, Any]]:
        """The stored result for a signature, or None. Public: the server asks
        this to tell a caller which nodes a run will reuse rather than run."""
        return self._cache_lookup(signature) if signature else None

    def sweep_cache(self, limit: float = 20.0) -> Dict[str, int]:
        """Drop every entry whose files are gone. Runs once at startup.

        Lazily dropping them on lookup only reaches the entries somebody
        happens to ask for; the rest sit in the index forever, making it
        slower to load and its size a lie. Bounded by a deadline because a
        data directory on a network share should delay a start, not prevent
        one.
        """
        deadline = time.monotonic() + limit
        with self._cache_lock:
            signatures = list(self._cache)
        dropped, checked = 0, 0
        for signature in signatures:
            if time.monotonic() > deadline:
                break
            with self._cache_lock:
                entry = self._cache.get(signature)
                if entry is None:
                    continue
                checked += 1
                if not self._entry_alive(entry):
                    self._cache.pop(signature, None)
                    dropped += 1
        if dropped:
            with self._cache_lock:
                self._save_cache()
        return {"checked": checked, "dropped": dropped,
                "left": len(signatures) - dropped}

    #: Durations kept per node type. Enough to have a median that survives one
    #: freak run, few enough that a machine that got faster is believed within
    #: an afternoon.
    TIMING_SAMPLES = 9

    def _record_timing(self, node_type: str, seconds: float) -> None:
        if seconds <= 0 or not node_type:
            return
        with self._cache_lock:
            samples = self._timings.setdefault(node_type, [])
            samples.append(round(seconds, 2))
            del samples[:-self.TIMING_SAMPLES]
            try:
                self._timing_path.parent.mkdir(parents=True, exist_ok=True)
                self._timing_path.write_text(json.dumps(self._timings, indent=1))
                self._timing_seen = self._stamp(self._timing_path)
            except OSError:
                pass  # a timing that cannot be written is not worth a failed run

    def estimate(self, node_type: str) -> Optional[float]:
        """The median time this kind of node has taken here, if it ever has."""
        samples = sorted(self._timings.get(node_type) or [])
        if not samples:
            return None
        middle = len(samples) // 2
        if len(samples) % 2:
            return samples[middle]
        return (samples[middle - 1] + samples[middle]) / 2

    def forecast(self, graph: Graph, force: Optional[Set[str]] = None,
                 only: Optional[List[str]] = None,
                 isolate: bool = False) -> Dict[str, Any]:
        """What pressing Run would actually do, before pressing it.

        Check says what is broken. Nothing said what is *expensive*: a graph of
        fifty nodes where forty-seven are cached and three will run looks
        exactly like one where all fifty will, and the difference is an
        afternoon. Signatures are pure -- they are computed from the graph, not
        from running it -- so this costs nothing but a hash per node.
        """
        force = force or set()
        with self._cache_lock:
            self._refresh()
        try:
            order = graph.topo_order()
        except GraphError as exc:
            return {"error": str(exc)}
        if only:
            # The switched-off ones are not run, the same as in start().
            only = [c for c in only if c in graph.nodes]
        if only:
            # "Run selected" means those nodes and everything they need, which
            # is the same set the run itself takes. "Run just this" means the
            # named nodes and nothing else.
            keep = set(only) if isolate else graph.upstream_closure(set(only))
            order = [n for n in order if n in keep]
        signatures = graph.signatures(order)
        nodes = []
        seconds, unknown = 0.0, 0
        for node_id in order:
            node_type = graph.nodes[node_id].get("type", "")
            cached = node_id not in force and bool(
                self._cache_lookup(signatures.get(node_id, "")))
            entry = {"node": node_id, "type": node_type, "cached": cached}
            if not cached:
                guess = self.estimate(node_type)
                if guess is None:
                    unknown += 1
                else:
                    seconds += guess
                    entry["estimate"] = guess
            nodes.append(entry)
        will_run = [n for n in nodes if not n["cached"]]
        return {
            "nodes": nodes,
            "total": len(nodes),
            "cached": len(nodes) - len(will_run),
            "will_run": len(will_run),
            # Never a single number pretending to be a promise: the parts it
            # has never seen are counted separately and said out loud.
            "seconds": seconds,
            "unknown": unknown,
        }

    def _cache_store(self, signature: str, entry: Dict[str, Any]) -> None:
        # An output the run never wrote is remembered as such. An mdrun
        # declares a compressed trajectory whether or not the settings write
        # one, and treating "never existed" as "deleted" made the liveness
        # check below throw the whole entry away -- so every run whose
        # settings kept only the full-precision trajectory was re-run from
        # scratch, forever, and nothing said why.
        for value in (entry.get("outputs") or {}).values():
            if isinstance(value, dict):
                path = value.get("path")
                if path and not Path(path).exists():
                    value["absent"] = True
        with self._cache_lock:
            # Two runs going at once are two separate programs, and each
            # writes the whole index file. Without picking up what the
            # other one wrote first, whoever saves last erases the other's
            # finished work -- the node then re-runs later for no visible
            # reason, or an old result comes back from the dead. So: read
            # what is on disk, keep anything new in it, then add ours.
            if self._stamp(self._cache_path) != getattr(self, "_cache_seen", 0.0):
                try:
                    on_disk = json.loads(self._cache_path.read_text())
                    for key, value in on_disk.items():
                        self._cache.setdefault(key, value)
                except (OSError, json.JSONDecodeError):
                    pass
            self._cache[signature] = entry
            self._save_cache()

    def clear_cache(self) -> int:
        with self._cache_lock:
            count = len(self._cache)
            self._cache = {}
            self._save_cache()
        return count

    def forget_tool(self, tool_id: str) -> int:
        """Drop cached results produced by one tool's nodes.

        A signature covers the graph -- node types, parameters, upstream files
        -- and deliberately not the machine, so that swapping conda channels
        does not invalidate every result on disk. That leaves one case where
        the graph is unchanged but the program behind it is not: pointing a
        tool at a different checkout. Reusing a result built by the copy that
        is no longer being run is the silent wrong answer this is here to
        prevent, so those entries go and the nodes run again.
        """
        types = {name for name, cls in REGISTRY.items()
                 if getattr(cls, "tool", "") == tool_id}
        if not types:
            return 0
        with self._cache_lock:
            dropped = [sig for sig, entry in self._cache.items()
                       if entry.get("type") in types]
            for sig in dropped:
                del self._cache[sig]
            if dropped:
                self._save_cache()
        return len(dropped)

    def run_folders(self, root: Path, limit: float = 6.0) -> Dict[str, Any]:
        """Every run directory under one folder, with what it is worth keeping.

        The question this answers is "which of these sixteen folders is the
        gigabyte". Size is counted in blocks and each inode once, because a
        large input hard-linked into four runs is one file on the disk and
        adding it up four times reports a directory holding 3 GB as 12.

        The rest is what makes deleting safe to decide: how many cache entries
        still point into it, and whether it is one of the folders a re-run
        leaves behind holding nothing but a workflow.json -- the results of
        *that* run are in the older folder it reused, so "keep the newest,
        delete the old one" is backwards.
        """
        deadline = time.monotonic() + limit
        with self._cache_lock:
            self._refresh()
            entries = list(self._cache.values())
        referenced: Dict[str, int] = {}
        for entry in entries:
            workdir = Path(entry.get("workdir", ""))
            referenced[str(workdir.parent)] = referenced.get(str(workdir.parent), 0) + 1

        found, total, complete = [], 0, True
        try:
            children = sorted(root.iterdir(), reverse=True)
        except OSError as exc:
            return {"error": f"cannot read {root}: {exc.strerror or exc}"}
        for child in children:
            if not looks_like_run(child):
                continue
            seen: set = set()
            bytes_here, files, nodes = 0, 0, 0
            for entry_path in child.iterdir() if child.is_dir() else []:
                if entry_path.is_dir():
                    nodes += 1
            for base, _dirs, names in os.walk(child, onerror=lambda err: None):
                for name in names:
                    try:
                        info = os.lstat(os.path.join(base, name))
                    except OSError:
                        continue
                    files += 1
                    key = (info.st_dev, info.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                    bytes_here += info.st_blocks * 512
                if time.monotonic() > deadline:
                    complete = False
                    break
            total += bytes_here
            try:
                when = child.stat().st_mtime
            except OSError:
                when = 0.0
            found.append({
                "path": str(child), "name": child.name, "modified": when,
                "bytes": bytes_here, "files": files, "nodes": nodes,
                "cached": referenced.get(str(child), 0),
                # One file and no node directories: a re-run that reused
                # everything and produced nothing of its own.
                "bookkeeping": nodes == 0 and files <= 2,
            })
            if not complete:
                break
        return {"root": str(root), "runs": found, "bytes": total,
                "partial": not complete}

    def remove_run_folder(self, path: Path) -> Dict[str, Any]:
        """Delete one run directory, and only ever a run directory."""
        if not looks_like_run(path):
            return {"error": f"{path} is not a run directory (a run is named "
                             "like 20260826-140650-5a7c8e and holds a "
                             "workflow.json)"}
        # Whatever pointed at it is dropped now rather than being found dead
        # later. The lookup would survive it either way -- an entry whose files
        # are gone is dropped on sight -- but the index should not carry
        # sixteen dead entries because somebody tidied up.
        dropped = 0
        with self._cache_lock:
            for signature, entry in list(self._cache.items()):
                if str(Path(entry.get("workdir", "")).parent) == str(path):
                    del self._cache[signature]
                    dropped += 1
            if dropped:
                self._save_cache()
        try:
            shutil.rmtree(path)
        except OSError as exc:
            return {"error": f"could not delete {path}: {exc.strerror or exc}"}
        return {"deleted": str(path), "forgot": dropped}

    def cache_stats(self, limit: float = 3.0) -> Dict[str, Any]:
        """What the cache is holding, for the panel that offers to clear it.

        Two numbers that are easy to confuse and matter differently. *live* is
        how many node results could be reused right now; *stale* is entries
        whose files somebody has since deleted, which cost nothing and vanish
        the next time they are looked up. And the disk figure is the size of
        the run directories those results live in -- clearing the index frees
        none of it, because the index is a few kB of JSON and the gigabytes are
        the runs themselves. A button that says "clear" wants that said out
        loud before it is pressed.
        """
        deadline = time.monotonic() + limit
        live = stale = 0
        directories: Dict[str, int] = {}
        newest = 0.0
        with self._cache_lock:
            entries = list(self._cache.values())
        for entry in entries:
            if not self._entry_alive(entry):
                stale += 1
                continue
            workdir = Path(entry.get("workdir", ""))
            live += 1
            newest = max(newest, float(entry.get("created") or 0))
            # The run directory, not the node's: a run of forty nodes is forty
            # entries and one directory, and it is the directory you would
            # delete.
            directories.setdefault(str(workdir.parent), 0)
        # Sized on a deadline, and only the directories still referenced. A
        # data directory on a network share should make this late, not hang it.
        total, complete = 0, True
        seen: set = set()
        for directory in directories:
            for root, _dirs, names in os.walk(directory, onerror=lambda err: None):
                for name in names:
                    try:
                        info = os.lstat(os.path.join(root, name))
                    except OSError:
                        continue
                    key = (info.st_dev, info.st_ino)
                    if key in seen:
                        continue  # hard-linked into several runs; counted once
                    seen.add(key)
                    total += info.st_blocks * 512
                if time.monotonic() > deadline:
                    complete = False
                    break
            if not complete:
                break
        return {
            "entries": len(entries), "live": live, "stale": stale,
            "runs": len(directories), "bytes": total, "partial": not complete,
            "newest": newest, "index": str(self._cache_path),
            "index_bytes": (self._cache_path.stat().st_size
                            if self._cache_path.exists() else 0),
        }

    # -- runs -----------------------------------------------------------
    def list_runs(self) -> List[Dict[str, Any]]:
        with self._lock:
            runs = sorted(self.runs.values(), key=lambda r: r.created, reverse=True)
        return [
            {"id": r.id, "label": r.label, "session": r.session, "status": r.status,
             "created": r.created, "finished": r.finished, "nodes": len(r.nodes),
             "workdir": str(r.workdir)}
            for r in runs
        ]

    def get(self, run_id: str) -> Optional[Run]:
        return self.runs.get(run_id)

    def start(
        self,
        graph_data: Dict[str, Any],
        only: Optional[List[str]] = None,
        force: Optional[List[str]] = None,
        label: str = "",
        output_dir: str = "",
        session: str = "",
        isolate: bool = False,
    ) -> Run:
        graph = Graph(graph_data)
        problems = [p for p in graph.validate() if p["level"] == "error"]
        if problems:
            raise GraphError("; ".join(f"{p['node']}: {p['message']}" for p in problems))

        # Nodes switched off in the editor were taken out when the graph was
        # read. Asked for by name, as "run this chunk" does with every node in
        # the box, the switched-off ones are simply not run and the rest are.
        # Only when nothing asked for is left is there something to say, and
        # then it is why -- not "there is no node called n5".
        if only:
            kept = [c for c in only if c not in graph.left_out]
            if not kept:
                raise GraphError("; ".join(
                    dict.fromkeys(graph.left_out_reason(c) for c in only)))
            only = kept
        if force:
            force = [c for c in force if c not in graph.left_out]

        # A name that is not in the graph used to sail past here and come back
        # as "the graph has a cycle involving: ..." from the sort below, which
        # is a baffling thing to be told when all you did was mistype a node.
        for chosen in list(only or []) + list(force or []):
            if chosen not in graph.nodes:
                near = sorted(n for n in graph.nodes if chosen.lower() in n.lower())
                raise GraphError(
                    f"there is no node called '{chosen}' in this workflow"
                    + (f" -- did you mean {' or '.join(near)}?" if near else
                       f" -- it has: {', '.join(sorted(graph.nodes))}"))

        subset: Optional[Set[str]] = None
        seed: Dict[str, Dict[str, Any]] = {}
        if only and isolate:
            # "Just these, nothing else." Everything they need has to come from
            # a previous run instead, which is what the store of finished
            # results is for -- look the answers up now, and refuse clearly if
            # one of them was never worked out.
            subset = set(only)
            seed = self._borrow_upstream(graph, subset)
        elif only:
            subset = graph.upstream_closure(set(only))
        order = graph.topo_order(subset)
        if not order:
            if graph.left_out and not graph.nodes:
                raise GraphError(
                    "nothing to run: every node is switched off, or depends on "
                    "one that is")
            raise GraphError("nothing to run")

        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        workdir = resolve_output_dir(self.settings, output_dir) / run_id
        try:
            workdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GraphError(f"cannot create the output directory {workdir}: {exc}") from exc

        run = Run(run_id, graph, workdir, label, session)
        run.order = order
        signatures = graph.signatures()
        for node_id in order:
            state = NodeState(node_id, graph.nodes[node_id].get("type", ""))
            state.signature = signatures.get(node_id, "")
            run.nodes[node_id] = state

        (workdir / "workflow.json").write_text(json.dumps(graph_data, indent=2))
        with self._lock:
            self.runs[run_id] = run

        # Forcing a node means "run it again, its answer may be different".
        # Everything fed by it is then suspect too. A node is remembered by
        # what it is and what it is wired to, not by the bytes it produced --
        # so without this a forced node writes a new file and the node next
        # door hands back the result it worked out from the old one, with
        # "cached" beside it and nothing to say the two disagree.
        force_set = set(force or [])
        for node_id in list(force_set):
            if node_id in graph.nodes:
                force_set |= graph.downstream(node_id)
        run.thread = threading.Thread(
            target=self._execute, args=(run, force_set, seed),
            name=f"run-{run_id}", daemon=True
        )
        run.status = "running"
        run.thread.start()
        return run

    def cancel(self, run_id: str, hard: bool = False) -> Dict[str, Any]:
        """Stop a run. Press it again and it stops harder.

        Returns straight away. Stopping a program politely means giving it a
        few seconds to tidy up, and waiting for that here made the Cancel
        button sit there doing nothing -- so the waiting happens in the
        background and the button stays live. Pressing it a second time (or
        asking for `hard`) skips the polite part and kills everything now,
        including anything a node left behind when it finished.
        """
        run = self.runs.get(run_id)
        if run is None:
            return {"cancelled": False, "hard": False,
                    "error": "that run is not on this server any more -- "
                             "it was probably restarted since the run started"}
        insist = hard or run.cancelled
        run.cancelled = True
        # A run held at a node is sitting in a wait; wake it so it can notice.
        with run.gate:
            run.paused = ""
            run.gate.notify_all()
        with run.lock:
            handles = list(run.running.values())
            groups = dict(run.groups)
        for handle in handles:
            threading.Thread(target=handle.cancel, kwargs={"hard": insist},
                             daemon=True, name=f"cancel-{run_id}").start()
        swept = 0
        if insist:
            # Sweep the leftovers as well: a node whose own process finished
            # can still have children running, and they are nobody's handle.
            live = {id(h): getattr(h, "pgid", None) for h in handles}
            for pgid in groups.values():
                if pgid is None or pgid in live.values():
                    continue
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    swept += 1
                except (ProcessLookupError, PermissionError, OSError):
                    pass
        run.bus.emit({"type": "run", "status": "cancelling", "run": run_id,
                      "hard": insist})
        if insist:
            run.bus.emit({"type": "log", "node": "",
                          "line": "!! killing everything this run started"})
        return {"cancelled": True, "hard": insist, "swept": swept,
                "running": len(handles)}

    def resume(self, run_id: str, graph_data: Optional[Dict[str, Any]] = None
               ) -> Dict[str, Any]:
        """Let a held run carry on, with whatever the editor says now.

        The graph is taken again on the way past, so a value changed while the
        run was held is the value that gets used. Only the values may change:
        if nodes or wires have been added or removed the run would no longer
        match what it has already done, so those are refused and it carries on
        with what it had.
        """
        run = self.runs.get(run_id)
        if run is None:
            return {"resumed": False, "error": "that run is not on this server any more"}
        if not run.paused:
            return {"resumed": False, "error": "that run is not being held anywhere"}
        node_id = run.paused
        note = ""
        if graph_data:
            try:
                fresh = Graph(graph_data)
            except GraphError as exc:
                return {"resumed": False, "error": str(exc)}
            same = (set(fresh.nodes) == set(run.graph.nodes)
                    and all(fresh.nodes[n].get("type") == run.graph.nodes[n].get("type")
                            for n in fresh.nodes)
                    and sorted(map(_link_key, fresh.links))
                    == sorted(map(_link_key, run.graph.links)))
            if same:
                run.graph = fresh
                signatures = fresh.signatures()
                for other, state in run.nodes.items():
                    if state.status in ("pending", "paused"):
                        state.signature = signatures.get(other, state.signature)
                note = "picked up the current settings"
            else:
                note = ("the graph has changed shape since this run started, so it "
                        "carries on with the one it began with. Cancel and run "
                        "again to use the new one")
                run.bus.emit({"type": "log", "node": node_id, "line": "!! " + note})
        with run.gate:
            run.paused = ""
            run.gate.notify_all()
        return {"resumed": True, "node": node_id, "note": note}

    def send_input(self, run_id: str, node_id: str, text: str = "",
                   eof: bool = False) -> Dict[str, Any]:
        """Type something into a running step, or close its input.

        This is what makes the terminal drawer a terminal: a command that stops
        to ask a question can be answered instead of the run being thrown away.
        """
        run = self.runs.get(run_id)
        if run is None:
            return {"sent": False, "error": "no such run"}
        with run.lock:
            handles = dict(run.running)
        handle = handles.get(node_id) if node_id else None
        if handle is None:
            if len(handles) == 1:
                node_id, handle = next(iter(handles.items()))
            elif not handles:
                return {"sent": False, "error": "nothing is running just now"}
            else:
                return {"sent": False,
                        "error": "several nodes are running -- click the one "
                                 "you want to answer first"}
        ok = handle.eof() if eof else handle.send(text)
        if ok:
            # Into the node's own log as well as the drawer, so the record of
            # what was typed survives in the run folder.
            line = "^D (input closed)" if eof else f"> {text}"
            state = run.nodes.get(node_id)
            if state is not None:
                self._log(run, state, line)
            else:
                run.bus.emit({"type": "log", "node": node_id, "line": line})
        return {"sent": bool(ok), "node": node_id,
                "error": "" if ok else "that command is no longer reading input"}

    # -- execution ------------------------------------------------------

    #: Node types that take the machine while they run. Two mdruns at once is
    #: not twice the work done: with ntomp left at 0 each one takes every core
    #: it can see, and they spend the run fighting each other for them. These
    #: wait for everything else to finish and run on their own.
    HEAVY = frozenset({"gmx.mdrun", "phos.run", "cg.calvados_run", "omb.build"})

    #: How long a cancelled run waits for its nodes to actually stop before it
    #: reports itself cancelled anyway. ProcessHandle gives a step SIGTERM and
    #: then SIGKILL five seconds later, so anything still alive after this is
    #: something the operating system could not stop for us -- an NFS read
    #: stuck in D state, a child that escaped its process group. Whatever it
    #: is, the *run* is over: leaving the editor saying "running" for ever
    #: because one process would not die is the worst of both.
    CANCEL_GRACE = 20.0

    def _sweep(self, run: Run) -> int:
        """Kill every process group this run ever started. Returns how many."""
        with run.lock:
            groups = list(run.groups.values())
        killed = 0
        for pgid in groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError, OSError):
                pass
        return killed

    def _parallel_limit(self) -> int:
        try:
            limit = int(self.settings.get("max_parallel_nodes", 3) or 1)
        except (TypeError, ValueError):
            limit = 1
        return max(1, min(limit, 16))

    def _borrow_upstream(self, graph: Graph, subset: Set[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch the finished results of everything feeding into `subset`.

        Running one node on its own only works if the files its inputs point at
        already exist somewhere. They do, if those nodes have been run before:
        every finished node's outputs are kept. This collects them, and says
        plainly which node has not been run yet when one is missing, rather
        than starting a run that would quietly re-do half the graph.
        """
        with self._cache_lock:
            self._refresh()
        signatures = graph.signatures()
        seed: Dict[str, Dict[str, Any]] = {}
        missing: List[str] = []
        for node_id in sorted(subset):
            for port, (source, _source_port) in graph.incoming(node_id).items():
                if source in subset or source in seed:
                    continue
                stored = self._cache_lookup(signatures.get(source, ""))
                if stored:
                    seed[source] = stored["outputs"]
                    continue
                title = graph.nodes.get(source, {}).get("type", source)
                missing.append(f"{source} ({title}) -> {node_id}.{port}")
        if missing:
            raise GraphError(
                "these nodes have never finished, so there is no result to feed "
                "in: " + "; ".join(missing)
                + ". Run the chain once (\"Run up to here\"), then this node "
                  "can be re-run on its own."
            )
        return seed

    def _execute(self, run: Run, force: Set[str],
                 seed: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """Run the graph, several nodes at once where the graph allows it.

        The order was strictly serial, which for a graph of four analyses
        hanging off one trajectory meant running them one after another though
        they share nothing but an input. Now a node starts as soon as
        everything it depends on has settled, up to a limit -- with one rule
        on top: a node in HEAVY runs alone.

        At a limit of 1 this is exactly what it always did, one node at a time
        in topological order, which is what the setting drops to if any of this
        turns out to be a mistake.
        """
        with self._cache_lock:
            self._refresh()
        toolbox = Toolbox(self.settings)
        # Results borrowed from earlier runs, for nodes this run is not going
        # to touch. Empty for an ordinary run.
        produced: Dict[str, Dict[str, Any]] = dict(seed or {})
        run.bus.emit({"type": "run", "status": "running", "run": run.id})

        limit = self._parallel_limit()
        index_of = {node_id: index for index, node_id in enumerate(run.order)}
        waiting = list(run.order)
        running: Dict[str, threading.Thread] = {}
        failures: List[str] = []
        gate = threading.Condition()

        def settled(node_id: str) -> bool:
            return run.nodes[node_id].status not in ("pending", "running", "paused")

        def ready(node_id: str) -> bool:
            return all(settled(src) for _, (src, _) in
                       run.graph.incoming(node_id).items() if src in run.nodes)

        def worker(node_id: str) -> None:
            try:
                ok = self._settle_node(run, index_of[node_id], node_id, produced,
                                       toolbox, force)
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                state = run.nodes[node_id]
                state.status = "error"
                state.error = str(exc)
                state.finished = time.time()
                self._log(run, state, "".join(traceback.format_exc()).rstrip())
                run.bus.emit({"type": "node", "node": node_id, "status": "error",
                              "error": state.error})
                ok = False
            with gate:
                running.pop(node_id, None)
                if not ok:
                    failures.append(node_id)
                gate.notify_all()

        abandon_at: Optional[float] = None
        while waiting or running:
            with gate:
                if run.cancelled:
                    if abandon_at is None:
                        abandon_at = time.monotonic() + self.CANCEL_GRACE
                    elif time.monotonic() > abandon_at:
                        for node_id in list(running) + list(waiting):
                            state = run.nodes[node_id]
                            if state.status in ("pending", "running"):
                                state.status = "cancelled"
                                state.finished = time.time()
                                run.bus.emit({"type": "node", "node": node_id,
                                              "status": "cancelled"})
                        stuck = list(running)
                        running.clear()
                        waiting.clear()
                        if stuck:
                            # Last resort before walking away: kill every
                            # process group this run started. Anything that
                            # survives this is something the operating system
                            # could not stop for us.
                            killed = self._sweep(run)
                            run.bus.emit({"type": "log", "node": stuck[0],
                                          "line": "!! "
                                          + ", ".join(stuck)
                                          + " would not stop; killed "
                                          + f"{killed} leftover process group"
                                          + ("" if killed == 1 else "s")})
                        break
                launched = True
                while launched:
                    launched = False
                    for node_id in list(waiting):
                        if len(running) >= limit:
                            break
                        if not ready(node_id):
                            continue
                        heavy = run.graph.nodes[node_id].get("type", "") in self.HEAVY
                        if heavy and running:
                            continue  # it gets the machine to itself
                        if running and any(
                                run.graph.nodes[other].get("type", "") in self.HEAVY
                                for other in running):
                            break     # something already has it
                        waiting.remove(node_id)
                        thread = threading.Thread(
                            target=worker, args=(node_id,),
                            name=f"node-{node_id}", daemon=True)
                        running[node_id] = thread
                        launched = True
                        thread.start()
                if not running and waiting:
                    # Nothing runnable and nothing running: whatever is left is
                    # downstream of something that never settled. Settle it.
                    for node_id in list(waiting):
                        waiting.remove(node_id)
                        state = run.nodes[node_id]
                        state.status = "skipped"
                        state.error = state.error or "nothing upstream produced output"
                        run.bus.emit({"type": "node", "node": node_id,
                                      "status": "skipped", "error": state.error})
                    continue
                if running:
                    gate.wait(0.5)

        failed = bool(failures)
        run.finished = time.time()
        if run.cancelled:
            run.status = "cancelled"
        elif failed:
            run.status = "error"
        else:
            run.status = "done"
        run.bus.emit({"type": "run", "status": run.status, "run": run.id})

    def _settle_node(self, run: Run, index: int, node_id: str,
                     produced: Dict[str, Dict[str, Any]], toolbox: Toolbox,
                     force: Set[str]) -> bool:
        """One node from pending to settled. True unless it failed.

        Lifted out of the loop it used to be the body of, unchanged: the cache
        lookup, the work directory, the run, and what each outcome means. What
        changed is that several of these can be in flight at once, so it
        touches only its own state -- everything shared (the cache index, the
        event bus) already has its own lock, and `produced` is only ever read
        for nodes that settled before this one started.
        """
        state = run.nodes[node_id]
        if run.cancelled:
            state.status = "skipped"
            run.bus.emit({"type": "node", "node": node_id, "status": "skipped"})
            return True

        node = run.graph.nodes[node_id]
        node_type = node.get("type", "")
        upstream_failed = [
            src for _, (src, _) in run.graph.incoming(node_id).items()
            if src in run.nodes and run.nodes[src].status in ("error", "skipped")
        ]
        if upstream_failed:
            state.status = "skipped"
            state.error = f"upstream node {upstream_failed[0]} did not produce output"
            run.bus.emit({"type": "node", "node": node_id, "status": "skipped",
                          "error": state.error})
            return True

        # Reuse a previous identical computation.
        cached = None if node_id in force else self._cache_lookup(state.signature)
        if cached:
            state.status = "cached"
            state.workdir = cached["workdir"]
            state.outputs = cached["outputs"]
            state.notes = cached.get("notes", [])
            state.started = state.finished = time.time()
            produced[node_id] = state.outputs
            run.bus.emit({"type": "node", "node": node_id, "status": "cached",
                          "workdir": state.workdir, "outputs": state.outputs})
            return True

        if node.get("pause") and not run.cancelled:
            # Marked "pause before this node" in the editor. Wait here with
            # everything before it finished, which is exactly what is needed to
            # look at a file this node is about to read and decide what it
            # should do with it.
            state.status = "paused"
            run.bus.emit({"type": "node", "node": node_id, "status": "paused"})
            run.bus.emit({"type": "run", "status": "paused", "run": run.id,
                          "node": node_id})
            self._log(run, state,
                      "|| held here. Change what this node should do, then press "
                      "Continue.")
            with run.gate:
                run.paused = node_id
                while run.paused == node_id and not run.cancelled:
                    run.gate.wait(0.5)
            if run.cancelled:
                state.status = "cancelled"
                run.bus.emit({"type": "node", "node": node_id, "status": "cancelled"})
                return True
            # The editor may have changed this node while we waited, so read it
            # again rather than using the copy taken before the pause.
            node = run.graph.nodes.get(node_id, node)
            node_type = node.get("type", node_type)
            state.type = node_type
            run.bus.emit({"type": "run", "status": "running", "run": run.id})

        workdir = run.workdir / f"{index:02d}_{node_id}_{node_type.replace('.', '_')}"
        workdir.mkdir(parents=True, exist_ok=True)
        state.workdir = str(workdir)
        state.status = "running"
        state.started = time.time()
        run.bus.emit({"type": "node", "node": node_id, "status": "running",
                      "workdir": state.workdir})

        rc = self._run_node(run, state, node, workdir, produced, toolbox)

        state.finished = time.time()
        state.returncode = rc
        if run.cancelled and rc != 0:
            state.status = "cancelled"
            run.bus.emit({"type": "node", "node": node_id, "status": "cancelled"})
            return False
        if rc != 0:
            state.status = "error"
            state.error = f"exit code {rc}"
            run.bus.emit({"type": "node", "node": node_id, "status": "error",
                          "error": state.error})
            return False

        state.status = "done"
        produced[node_id] = state.outputs
        if state.started and state.finished:
            self._record_timing(node_type, state.finished - state.started)
        self._cache_store(state.signature, {
            "version": CACHE_VERSION,
            "workdir": str(workdir), "outputs": state.outputs,
            "notes": state.notes, "type": node_type, "created": time.time(),
        })
        run.bus.emit({"type": "node", "node": node_id, "status": "done",
                      "outputs": state.outputs, "notes": state.notes})
        return True

    def _run_node(self, run, state, node, workdir, produced, toolbox) -> int:
        node_type = node.get("type", "")
        cls = REGISTRY.get(node_type)
        params = dict(cls.defaults())
        params.update(node.get("params") or {})

        inputs: Dict[str, Any] = {}
        for port, (source, source_port) in run.graph.incoming(state.id).items():
            inputs[port] = (produced.get(source) or {}).get(source_port)

        ctx = PlanContext(
            node_id=state.id, node_type=node_type, params=params, inputs=inputs,
            workdir=workdir, stage=make_stage(workdir, dry=False),
            settings=self.settings, dry=False,
        )
        plan = cls().plan(ctx)
        state.notes = list(plan.notes)

        for name, content in plan.files.items():
            target = workdir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        # A node is allowed to name an output after one of its inputs.  Break
        # any sharing first, so that stays a local rewrite.
        for name in _output_names(plan):
            _private_copy(workdir / name)
        # ...and any input the node says it edits where it stands.
        for name in plan.rewrites:
            _private_copy(workdir / name)

        if not plan.steps:
            state.outputs = _materialise(plan, workdir)
            return 0

        env_override = params.get("env_override", "") or ""

        def resolve(tool_id: str):
            return toolbox.resolve(tool_id, env_override)

        script = render_script(plan.steps, workdir, resolve,
                               nice=bool(self.settings.get("nice", True)))
        (workdir / "command.sh").write_text(render_manual(plan.steps, workdir, resolve))

        # A minimisation with -v prints a line for every step, thousands a
        # second, and each one used to become its own progress event on top
        # of its log line. The browser could not keep up and froze. Progress
        # is now sent at most a few times a second; the last value always
        # gets through, because the next line that changes it sends it.
        last_sent = [0.0]

        def on_line(line: str) -> None:
            self._log(run, state, line)
            progress = _progress_hint(line)
            if progress and progress != state.progress:
                state.progress = progress
                now = time.monotonic()
                if now - last_sent[0] >= 0.25:
                    last_sent[0] = now
                    run.bus.emit({"type": "progress", "node": state.id, "progress": progress})

        def on_step(kind: str, index: int, rc: Optional[int]) -> None:
            if kind != "BEGIN":
                return
            step = plan.steps[index] if index < len(plan.steps) else None
            command = ""
            if step is not None:
                # The command as it will actually be run, not the node's argv:
                # a terminal that prints "editconf -f x" when the shell runs
                # "gmx editconf -f x" is showing you something you cannot paste.
                try:
                    command = render_step(step, resolve(step.tool).command)["command"]
                except Exception:                             # noqa: BLE001
                    command = step.render()
            run.bus.emit({"type": "step", "node": state.id, "index": index,
                          "label": step.label if step else "", "command": command})

        def on_waiting(waiting: bool) -> None:
            # Somebody's command has stopped and is asking a question. Say so
            # loudly: without this the run just looks like it has gone quiet.
            run.bus.emit({"type": "waiting", "node": state.id,
                          "waiting": bool(waiting)})
            if waiting:
                self._log(run, state,
                          "?? this command is waiting for an answer -- type it "
                          "in the terminal drawer below")

        handle = ProcessHandle(script, workdir, on_line=on_line, on_step=on_step,
                               on_waiting=on_waiting)
        with run.lock:
            run.running[state.id] = handle
        # A cancel that arrived while this was being set up would otherwise be
        # missed by a process that had not started yet.
        if run.cancelled:
            handle.cancel()
        try:
            starter = threading.Thread(target=_note_group, args=(run, state.id, handle),
                                       daemon=True, name=f"pgid-{state.id}")
            starter.start()
            rc = handle.run()
        finally:
            with run.lock:
                run.running.pop(state.id, None)
                # Remembered after the fact on purpose: this is what a second
                # press of Cancel uses to hunt down anything left behind.
                if handle.pgid is not None:
                    run.groups[state.id] = handle.pgid

        state.outputs = _materialise(plan, workdir)
        missing = [
            value.get("name") for value in state.outputs.values()
            if value.get("kind") == "file" and value.get("path")
            and not Path(value["path"]).exists()
        ]
        if rc == 0 and missing:
            state.notes.append("declared outputs were not produced: " + ", ".join(missing))
        return rc

    def _log(self, run: Run, state: NodeState, line: str) -> None:
        state.log.append(line)
        run.bus.emit({"type": "log", "node": state.id, "line": line})


def _link_key(link: Dict[str, Any]):
    """One wire, as something two graphs can be compared on."""
    return (link["from_node"], link["from_port"], link["to_node"], link["to_port"])


def _note_group(run, node_id: str, handle) -> None:
    """Write down the process group as soon as the step has one.

    A run cancelled while a node is still going needs the number too, and the
    node only fills it in after the program has actually started -- so this
    watches for it rather than reading it once and finding nothing.
    """
    for _ in range(200):
        pgid = getattr(handle, "pgid", None)
        if pgid is not None:
            with run.lock:
                run.groups[node_id] = pgid
            return
        if handle.returncode is not None:
            return
        time.sleep(0.05)


def _progress_hint(line: str) -> str:
    """Pull a human-readable progress marker out of an mdrun/grompp line."""
    stripped = line.strip()
    if stripped.startswith("step ") or stripped.startswith("Step "):
        return stripped[:90]
    if "imb F" in stripped and stripped.startswith("step"):
        return stripped[:90]
    if stripped.startswith("Writing final coordinates"):
        return "writing final coordinates"
    if stripped.startswith("Performance:"):
        return stripped[:90]
    return ""
