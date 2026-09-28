"""The local HTTP server.

Standard library only: ``ThreadingHTTPServer`` for the REST surface, static files
for the editor, and short repeated questions for live run logs.  Nothing to pip
install, which matters on a workstation where every tool already lives in its
own conda environment.
"""

from __future__ import annotations

import errno
import json
import mimetypes
import os
import posixpath
import re
import shutil
import sys
import signal
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, bootstrap, facts, flaghints, groups, shell
from .chunks import chunk_list, delete_chunk, save_chunk
from .config import WEB_DIR, Settings
from .environments import (CATALOG, Toolbox, _version_number, available_versions,
                           check_updates, env_name_for, forget_env,
                           gromacs_build_plan, install_requirements,
                           remember_install, remove_env_plan,
                           system_report)
from .executor import EventBus, Executor, dry_plan, preview_node, resolve_output_dir
from .graph import Graph, GraphError
from .nodes.base import local_path
from .registry import REGISTRY
from .runner import ProcessHandle
from .tutorials import (
    collection_of as tutorial_collection,
    get as get_tutorial,
    meta as tutorial_meta,
    tools_used as tutorial_tools,
    tutorial_list,
)
from .viz import (box_around, box_shapes, parse_composition,
                  parse_md_log, parse_sequence, parse_dssp, parse_structure,
                  parse_trajectory, parse_xvg)

MAX_BODY = 64 * 1024 * 1024
#: The most the built-in text editor will write. It exists for an mdp, an
#: index file, a note next to a run -- not for editing a trajectory by hand.
MAX_TEXT_WRITE = 512 * 1024


# --------------------------------------------------------------------------
# Background jobs (environment installs)
# --------------------------------------------------------------------------

class ScriptJob:
    def __init__(self, job_id: str, script: str, workdir: Path, label: str = "",
                 on_success: Optional[Callable[[], None]] = None,
                 on_finish: Optional[Callable[[str], None]] = None):
        self.id = job_id
        self.label = label
        self.script = script
        self.workdir = workdir
        self.status = "running"
        self.returncode: Optional[int] = None
        self.bus = EventBus()
        self.lines: List[str] = []
        self.handle: Optional[ProcessHandle] = None
        #: Whether the last thing appended was a progress redraw, and so may be
        #: overwritten by the next one.
        self._progress = False
        self.on_success = on_success
        #: Called however the job ends, with the status. A job that installs
        #: several things can fail on the last one having genuinely installed
        #: the first four, and forgetting those is how a working conda ends up
        #: unrecorded because a tool after it would not build.
        self.on_finish = on_finish
        #: True once the message saying how the job ended has been sent. The
        #: status changes earlier, before the steps that follow a success
        #: (recording what was installed), and a page told "finished" at
        #: that point would never hear how it ended.
        self.over = False

    def start(self) -> None:
        def worker() -> None:
            self.handle = ProcessHandle(self.script, self.workdir, on_line=self._on_line,
                                        on_progress=self._on_progress)
            try:
                self.returncode = self.handle.run()
            except Exception as exc:  # noqa: BLE001
                self._on_line(f"job failed to start: {exc}")
                self.returncode = 1
            if self.status != "cancelled":
                self.status = "done" if self.returncode == 0 else "error"
            if self.status == "done" and self.on_success is not None:
                try:
                    self.on_success()
                except Exception as exc:  # noqa: BLE001
                    self._on_line(f"post-install step failed: {exc}")
            if self.on_finish is not None:
                try:
                    self.on_finish(self.status)
                except Exception as exc:  # noqa: BLE001
                    self._on_line(f"recording what was installed failed: {exc}")
            self.bus.emit({"type": "job", "status": self.status, "rc": self.returncode})
            self.over = True

        threading.Thread(target=worker, name=f"job-{self.id}", daemon=True).start()

    def cancel(self) -> bool:
        """Stop a job that is still running.

        An hour-long build with no way to stop it is a trap: the only exit was
        finding the process group by hand. ProcessHandle already knows how --
        it is the same path a cancelled run takes -- it just had nothing
        wired to it here.
        """
        if self.status != "running":
            return False
        self.status = "cancelled"
        handle = self.handle
        if handle is not None:
            handle.cancel()
        self.bus.emit({"type": "job", "status": "cancelled", "rc": None})
        return True

    def _on_line(self, line: str) -> None:
        if self._progress:
            # A redraw is only ever the newest state of one line, so the next
            # real line replaces it rather than following it.
            self.lines[-1:] = [line]
            self._progress = False
        else:
            self.lines.append(line)
        if len(self.lines) > 5000:
            del self.lines[:1000]
        self.bus.emit({"type": "log", "line": line})

    def _on_progress(self, line: str) -> None:
        """A progress bar repainting itself, not a new line.

        Kept as one line rather than appended: a conda solve repaints several
        hundred times, and letting each be a line scrolled the real output away
        and then pushed the start of it out of the 5000-line buffer -- which
        looked, correctly, like the log was losing pieces of itself.
        """
        if self._progress and self.lines:
            self.lines[-1] = line
        else:
            self.lines.append(line)
        self._progress = True
        self.bus.emit({"type": "log", "line": line, "replace": True})


# --------------------------------------------------------------------------
# App state
# --------------------------------------------------------------------------

class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()
        self.executor = Executor(settings)
        self.toolbox = Toolbox(settings)
        self.jobs: Dict[str, ScriptJob] = {}
        #: The Terminal drawer's Shell tabs. See shell.py.
        self.shells = shell.Shells()
        self._sweep_cache()

    def _sweep_cache(self) -> None:
        """Forget cache entries whose files have been deleted, once, at start.

        Off the main thread: the check is a stat per output and the data
        directory can be on a network share, and none of it is needed before
        the first request. What it buys is an index that shrinks -- 86 of 150
        entries here pointed at runs deleted long ago, and lazily dropping
        them on lookup only ever reached the ones somebody asked for.
        """
        def run() -> None:
            try:
                result = self.executor.sweep_cache()
            except Exception:  # noqa: BLE001 - a tidy-up must never stop a start
                return
            if result["dropped"]:
                print(f"  cache       forgot {result['dropped']} entries whose "
                      f"files are gone, {result['left']} left")

        threading.Thread(target=run, name="cache-sweep", daemon=True).start()


# --------------------------------------------------------------------------
# Request handling
# --------------------------------------------------------------------------

class _CountingReader:
    """The request stream, counting what comes off it.

    This exists so the dispatcher can tell whether a handler read the body it
    was sent.  On a keep-alive HTTP/1.1 connection an unread body is not
    harmless: it stays in the socket, and the next request on that connection
    is parsed starting from it -- which is how a POST with a ``{}`` body ends
    up answered with ``Unsupported method ('{}GET')`` one request later.
    Counting here rather than in each handler means a handler that has no use
    for its body does not have to remember to read one anyway.
    """

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        data = self._wrapped.read(size)
        self.count += len(data)
        return data

    def readline(self, size: int = -1) -> bytes:
        data = self._wrapped.readline(size)
        self.count += len(data)
        return data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class Handler(BaseHTTPRequestHandler):
    server_version = f"ComfyGmx/{__version__}"
    protocol_version = "HTTP/1.1"
    app: App = None  # type: ignore[assignment]
    #: This request's parsed body once something has asked for it. Reset at the
    #: start of every request; see _body().
    _body_cache: Optional[Dict[str, Any]] = None

    # -- plumbing -------------------------------------------------------
    def setup(self) -> None:
        super().setup()
        self.rfile = _CountingReader(self.rfile)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter default log
        if os.environ.get("COMFYGMX_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200) -> None:
        self._send(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status)

    def _body(self) -> Dict[str, Any]:
        """What the browser sent with this request, as a dict.

        Read once and remembered. The bytes can only be taken off the socket
        one time, so a handler that asks twice -- and several do, because it
        reads better than passing the body down -- used to sit there waiting
        for a second copy that was never coming.
        """
        if self._body_cache is not None:
            return self._body_cache
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._body_cache = {}
            return self._body_cache
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        self._body_cache = json.loads(raw.decode("utf-8")) if raw else {}
        return self._body_cache

    # -- routing --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _drain(self, before: int) -> None:
        """Read past anything of the request body the handler did not want.

        Several handlers take no arguments and never look at the body the
        browser sent them, and one -- upload -- refuses early on some
        requests and returns without reading the file. Either way the bytes
        are still in the socket, and this connection is reused.
        """
        try:
            unread = int(self.headers.get("Content-Length") or 0) - (
                self.rfile.count - before)
            while unread > 0:
                chunk = self.rfile.read(min(1 << 16, unread))
                if not chunk:
                    return
                unread -= len(chunk)
        except (OSError, ValueError):
            pass  # the connection is gone, which drains it just as well

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        self.query = urllib.parse.parse_qs(parsed.query)
        # One handler object serves every request on a kept-open connection,
        # so last request's body must not leak into this one.
        self._body_cache: Optional[Dict[str, Any]] = None
        consumed_before = self.rfile.count
        try:
            for pattern, verbs, handler in ROUTES:
                if method not in verbs:
                    continue
                match = pattern.match(path)
                if match:
                    handler(self, *match.groups())
                    return
            if method == "GET":
                self._static(path)
                return
            self._error("no such endpoint", 404)
        except GraphError as exc:
            self._error(str(exc), 400)
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._error(f"{type(exc).__name__}: {exc}", 500)
            except BrokenPipeError:
                pass
        finally:
            self._drain(consumed_before)

    def q(self, name: str, default: str = "") -> str:
        values = self.query.get(name)
        return values[0] if values else default

    # -- static ---------------------------------------------------------
    def _static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        clean = posixpath.normpath(path).lstrip("/")
        target = (WEB_DIR / clean).resolve()
        try:
            target.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._error("forbidden", 403)
            return
        if not target.is_file():
            self._error("not found", 404)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # -- following a run or a job -----------------------------------------
    def _follow(self, bus: EventBus, is_finished: Callable[[], bool]) -> None:
        """What has happened since the page last asked, as one short reply.

        The page keeps asking "anything new since message N?" (the ``since``
        in the address). If something is waiting, the answer goes back at
        once. If not, the question is held open for up to ``wait`` seconds
        (10 unless the page says otherwise), and answered the moment
        something happens -- so the page still hears of each step as it
        happens, not ten seconds late.

        This used to be one reply that stayed open for the whole run, adding
        a message whenever there was news. On mybinder.org that did not work:
        the servers in front of its GESIS site hold such a reply back until it
        is complete, so the page heard nothing until the run was over. Worse,
        while that one reply was open the page sent nothing else, and
        mybinder.org closes a copy that has had no requests for ten minutes:
        a Lipids I run was shut down half way through. Short replies get
        through at once, and each question counts as the copy being in use.

        ``finished`` says the work is over and nothing more will come.
        """
        seq = int(self.q("since", "0") or 0)
        try:
            wait = min(max(float(self.q("wait", "10") or 10), 0.0), 25.0)
        except ValueError:
            wait = 10.0
        events = bus.since(seq, timeout=0)
        if not events and not is_finished():
            events = bus.since(seq, timeout=wait)
        if events:
            seq = max(seq, max(event["seq"] for event in events))
        finished = is_finished()
        if finished:
            # A run is marked over a moment before its last message -- the
            # one that says how it ended -- is sent. Wait that moment, so the
            # page learns whether it ended well, not just that it ended.
            late = bus.since(seq, timeout=0.5)
            events = events + late
        self._json({"events": events, "finished": finished})


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def h_info(self: Handler) -> None:
    settings = self.app.settings
    self._json({
        "version": __version__,
        "nodes": len(REGISTRY.specs()),
        "data_dir": str(settings.data_dir),
        "python": os.sys.version.split()[0],
        # The folders the file browser offers as one-click jumps. Here rather
        # than guessed in the browser: only this side knows where the uploads
        # went or what the output folder resolves to when it is left blank.
        "home": str(Path.home()),
        "uploads_dir": str(settings.uploads_dir),
        "output_dir": str(resolve_output_dir(settings, "")),
    })


def h_nodes(self: Handler) -> None:
    # The file-type table rides along with the catalogue rather than living in
    # the browser as a second copy: the same map in two languages drifts.
    from .nodes.io_nodes import FILE_GUIDE, KIND_BY_SUFFIX
    categories = REGISTRY.categories()
    # The force-field list on the topology block is read off the disk each
    # time the catalogue is asked for, so a .ff folder dropped into the
    # user's force-field folder shows up on the next page load.
    try:
        found = self.app.settings.gromacs_forcefields()
        names = found["user"] + [n for n in found["builtin"] if n not in found["user"]]
        # The way out for a force field that is not on this machine: one
        # staged by a 'Force field directory' block, or one being fetched
        # while the page is open. Always last, so the real ones come first.
        if names:
            names = names + ["typed below"]
    except Exception:
        found, names = {}, []
    if names:
        for category in categories:
            for spec in category.get("nodes", []):
                if spec.get("type") != "gmx.pdb2gmx":
                    continue
                for param in spec.get("params", []):
                    if param.get("name") == "forcefield":
                        param["choices"] = names
                        param["help"] = (param.get("help", "") +
                                         f"\n\nYour force-field folder: {found['dir']}"
                                         + (f"\nGROMACS's own: {found['gmx_top']}"
                                            if found.get("gmx_top") else ""))
                        break
    self._json({"categories": categories,
                "file_kinds": dict(KIND_BY_SUFFIX),
                "file_guide": FILE_GUIDE})


def h_gmx_forcefields(self: Handler) -> None:
    """The atomistic force fields GROMACS can see, and the folder for more."""
    self._json(self.app.settings.gromacs_forcefields())


def h_open_folder(self: Handler) -> None:
    """Open a folder in the desktop's file manager.

    Used by the force-field panel, so a downloaded folder can be dropped in,
    and by the button beside each tab's run folder.

    A folder, and only ever a folder. That is the part that matters: handing
    a *file* to the desktop starts whatever program is registered for it, and
    that would be a way to run something. Opening a directory starts a file
    manager looking at it and nothing else.

    The folder itself is not fenced off to a short list any more. The Files
    tab of this same page already walks the whole disk and can copy, move and
    delete anywhere, so refusing to merely *show* a folder while allowing it
    to be deleted was a lock on the wrong door -- and it meant the run folder
    button could not work for anybody who had pointed a tab somewhere of their
    own choosing.

    An empty path means the folder runs are written to, worked out here rather
    than passed in, so the button needs to know nothing.
    """
    import subprocess
    raw = str(self._body().get("path") or "").strip()
    settings = self.app.settings
    wanted = (Path(local_path(raw)) if raw
              else resolve_output_dir(settings, ""))
    try:
        resolved = wanted.expanduser().resolve()
    except OSError:
        self._error("that folder does not exist", 404)
        return
    if not resolved.is_dir():
        # Saying which of the two it is saves a puzzled minute: a file that is
        # plainly there being called missing reads like a bug.
        why = (f"{resolved} is a file, not a folder" if resolved.exists()
               else f"there is no folder at {resolved}")
        self._error(why, 404)
        return
    opener = shutil.which("xdg-open") or shutil.which("open")
    if not opener or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                          or sys.platform == "darwin"):
        self._json({"opened": False, "path": str(resolved),
                    "why": "no desktop to open it in -- copy the path instead"})
        return
    subprocess.Popen([opener, str(resolved)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    self._json({"opened": True, "path": str(resolved)})


def h_mdp_presets(self: Handler) -> None:
    """Every preset's actual options, so the editor can show them.

    The run-parameters node has thirteen widgets and a preset has thirty-odd
    options; leaving the widgets blank means "keep the preset's value", which
    is right but says nothing about what that value *is*. With the table here
    the node can show it -- and can fill it in the moment somebody edits one,
    so an edited preset is a complete parameter set rather than a diff against
    something invisible.
    """
    from .templates import PRESETS, PRESET_INFO
    from .nodes.util_nodes import MdpNode
    self._json({"presets": {name: {str(k): v for k, v in options.items()}
                            for name, options in PRESETS.items()},
                "info": dict(PRESET_INFO),
                # Which widget corresponds to which mdp option, from the node
                # itself rather than a second copy in the browser: the same map
                # in two languages drifts, and this one decides what a preset
                # shows you.
                "widgets": dict(MdpNode._WIDGET_MAP),
                # What GROMACS uses for an option nobody set, so a box can show
                # that number too instead of the words "preset default".
                "gromacs_defaults": dict(MdpNode._GROMACS_DEFAULTS),
                "default_name": MdpNode.DEFAULT_NAME})


def h_flags(self: Handler) -> None:
    """Every flag one command accepts, marked up for the node that asked.

    Not part of ``/api/nodes``: the flag lists together are five times the
    size of the whole node catalogue, and a graph of forty nodes needs at most
    the one list somebody has opened.
    """
    command = self.q("command")
    if not command:
        self._error("no command given", 400)
        return
    self._json(flaghints.reference(command, self.q("node", ""), REGISTRY,
                                   self.app.settings))


def h_chunks(self: Handler) -> None:
    self._json({"chunks": chunk_list(self.app.settings)})


def h_chunk_save(self: Handler) -> None:
    """Save a selection as a chunk of the user's own."""
    try:
        record = save_chunk(self.app.settings, self._body())
    except ValueError as exc:
        self._error(str(exc))
        return
    self._json({"chunk": record})


def h_chunk_delete(self: Handler, chunk_id: str) -> None:
    try:
        removed = delete_chunk(self.app.settings, urllib.parse.unquote(chunk_id))
    except ValueError as exc:
        self._error(str(exc), 403)
        return
    if removed is None:
        self._error("no such chunk", 404)
        return
    self._json({"deleted": chunk_id})


def h_tutorials(self: Handler) -> None:
    self._json({"tutorials": tutorial_list(), "meta": tutorial_meta()})


def h_tutorial(self: Handler, tutorial_id: str) -> None:
    try:
        tutorial = get_tutorial(tutorial_id)
    except KeyError:
        self._error("no such tutorial", 404)
        return
    payload = dict(tutorial)
    # The per-tutorial meta is its collection's: two collections ship,
    # with different authors and different papers to cite.
    payload["meta"] = tutorial_collection(tutorial)
    # Which tools it needs, read off the graph, and which of those are here.
    needs = tutorial_tools(tutorial)
    present = {row["id"]: row for row in bootstrap.survey(self.app.settings)["tools"]}
    payload["needs"] = {
        "all": [_tool_state(present, tool) for tool in needs["all"]],
        "groups": [{"title": group["title"],
                    "tools": [_tool_state(present, tool) for tool in group["tools"]]}
                   for group in needs["groups"]],
    }
    self._json(payload)


def _tool_state(present: Dict[str, Any], tool_id: str) -> Dict[str, Any]:
    row = present.get(tool_id) or {}
    return {"id": tool_id, "name": row.get("name", tool_id),
            "present": bool(row.get("present")), "where": row.get("where", "")}


def h_settings_get(self: Handler) -> None:
    self._json(self.app.settings.data)


def h_settings_post(self: Handler) -> None:
    patch = self._body()
    self.app.settings.update(patch)
    self.app.settings.save()
    self.app.settings.ensure_dirs()
    self._json(self.app.settings.data)


def h_environment(self: Handler) -> None:
    report = system_report(self.app.settings)
    if self.q("probe", "1") != "0":
        report["tools"] = self.app.toolbox.survey()
    self._json(report)


def h_probe(self: Handler) -> None:
    tool = self._body().get("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    self._json(self.app.toolbox.probe(tool))


def h_source(self: Handler) -> None:
    """Read or set the checkout a repo-backed tool is run from.

    GET reports where it is now and whether the installer owns it.  POST with
    {"tool","path"} records a checkout of the user's own -- a fork, a clone on
    another disk -- and an empty path hands the tool back to the installer.

    Checked before it is accepted, because the failure this replaces is silent:
    a wrong path here means the node reports the tool missing at run time,
    which is a long way from where the mistake was made.
    """
    if self.command == "GET":
        tool = self.q("tool", "")
        if tool not in CATALOG:
            self._error(f"unknown tool '{tool}'", 404)
            return
        spec = CATALOG[tool]
        settings = self.app.settings
        self._json({
            "tool": tool,
            "repo": spec.repo,
            "path": str(settings.source_dir(tool)),
            "override": settings.source_override(tool),
            "default": str(settings.sources_dir / tool),
            "marker": spec.repo_marker,
        })
        return

    body = self._body()
    tool = body.get("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    spec = CATALOG[tool]
    if not spec.repo:
        self._error(f"{spec.name} is a package, not a checkout, so there is "
                    f"nothing to point somewhere else", 400)
        return

    raw = str(body.get("path") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            self._error(f"{raw} is not an absolute path", 400)
            return
        if not path.is_dir():
            self._error(f"{path} is not a directory", 400)
            return
        if spec.repo_marker and not (path / spec.repo_marker).exists():
            self._error(f"{path} does not look like {spec.name}: "
                        f"there is no {spec.repo_marker} in it", 400)
            return
        # Recording the managed path as an override would work but would then
        # claim the installer must not touch its own directory.
        if path.resolve() == (self.app.settings.sources_dir / tool).resolve():
            raw = ""
        else:
            raw = str(path)

    before = self.app.settings.source_dir(tool)
    tools = dict(self.app.settings.get("tools") or {})
    entry = dict(tools.get(tool) or {})
    if raw:
        entry["source"] = raw
    else:
        entry.pop("source", None)
    tools[tool] = entry
    self.app.settings.update({"tools": tools})
    self.app.settings.save()
    self.app.toolbox.refresh()

    # A node signature covers the graph, not the machine, so a result built by
    # the checkout that is no longer being run would otherwise be reused with
    # nothing said -- the exact silent substitution this setting exists to
    # stop. Only this tool's nodes are forgotten; everything else stands.
    forgot = 0
    if self.app.settings.source_dir(tool) != before:
        forgot = self.app.executor.forget_tool(tool)

    self._json({
        "tool": tool,
        "path": str(self.app.settings.source_dir(tool)),
        "override": self.app.settings.source_override(tool),
        "forgot": forgot,
        "probe": self.app.toolbox.probe(tool),
    })


def h_installs(self: Handler) -> None:
    """Which environments hold a tool, and which one is being used.

    GET lists them; POST with {"tool","env"} switches the active one, which is
    all that "use version X from now on" needs to mean.
    """
    if self.command == "GET":
        tool = self.q("tool", "")
        if tool and tool not in CATALOG:
            self._error(f"unknown tool '{tool}'", 404)
            return
        box = self.app.toolbox
        wanted = [tool] if tool else [t for t in CATALOG if t != "shell"]
        self._json({"installs": {t: box.installs_of(t) for t in wanted}})
        return

    body = self._body()
    tool = body.get("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    env = str(body.get("env") or "").strip()
    tools = dict(self.app.settings.get("tools") or {})
    entry = dict(tools.get(tool) or {})
    entry["env"] = env
    tools[tool] = entry
    self.app.settings.update({"tools": tools})
    self.app.settings.save()
    self.app.toolbox.refresh()
    self._json({"tool": tool, "env": env,
                "probe": self.app.toolbox.probe(tool)})


def h_job_cancel(self: Handler, job_id: str) -> None:
    job = self.app.jobs.get(job_id)
    if job is None:
        self._error("no such job", 404)
        return
    self._json({"job": job_id, "cancelled": job.cancel(), "status": job.status})


def h_versions(self: Handler) -> None:
    """Which versions of one tool could be installed."""
    tool = self.q("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    self._json(available_versions(self.app.settings, tool))


def h_updates(self: Handler) -> None:
    """Installed against newest available, for everything at once.

    Slow on purpose and behind a button for that reason: a conda search is
    twenty seconds a package, and doing it on every visit to the dialog would
    make the dialog feel broken.
    """
    body = self._body() if self.command == "POST" else {}
    self._json({"tools": check_updates(self.app.settings, body.get("tools"))})


def h_gromacs_plan(self: Handler) -> None:
    """The flags, the prefix and the script for a source build, before it runs."""
    plan = gromacs_build_plan(self.app.settings, self._body())
    if plan.get("error"):
        self._error(plan["error"])
        return
    self._json(plan)


def h_gromacs_build(self: Handler) -> None:
    """Run that build, and register what it produced if it succeeds."""
    body = self._body()
    plan = gromacs_build_plan(self.app.settings, body)
    if plan.get("error"):
        self._error(plan["error"])
        return
    job_id = uuid.uuid4().hex[:10]
    workdir = self.app.settings.data_dir / "installs" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    app = self.app

    def remember() -> None:
        # An MPI build installs gmx_mpi and no gmx at all, so the binary name
        # is registered alongside the GMXRC. Getting that wrong leaves every
        # node reporting "not found" against a perfectly good install.
        app.settings.update({"gmxrc": plan["gmxrc"], "gmx_binary": plan["binary"]})
        app.settings.save()
        app.toolbox.refresh()

    job = ScriptJob(job_id, plan["script"], workdir,
                    label=f"build GROMACS {plan['version']}", on_success=remember)
    app.jobs[job_id] = job
    job.start()
    self._json({"job": job_id, "prefix": plan["prefix"], "gmxrc": plan["gmxrc"],
                "binary": plan["binary"], "workdir": str(workdir)})


# --------------------------------------------------------------------------
# First-run setup
# --------------------------------------------------------------------------

def h_setup(self: Handler) -> None:
    """What this machine is and what it is missing. Cheap: nothing is run."""
    self._json(bootstrap.survey(self.app.settings))


def h_setup_plan(self: Handler) -> None:
    """What the button would do, before it does it."""
    self._json(bootstrap.plan(self.app.settings, self._body()))


def h_setup_run(self: Handler) -> None:
    """Install conda and the chosen tools, as one job with one log.

    Only the part that needs no root. Anything that does comes back from the
    plan as text for a terminal, and is not smuggled into this script.
    """
    body = self._body()
    result = bootstrap.plan(self.app.settings, body)
    if not result["steps"]:
        self._error("nothing to install -- everything asked for is already here")
        return
    job_id = uuid.uuid4().hex[:10]
    workdir = self.app.settings.data_dir / "setup" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    app = self.app
    installed = [s["id"].split(":", 1)[1] for s in result["steps"]
                 if s["id"].startswith("tool:")]

    def remember(status: str) -> None:
        # Whatever happened, keep what actually landed. Setup is several steps
        # and they do not stand or fall together: recording nothing because the
        # last one failed loses the conda the first one installed.
        bootstrap.remember(app.settings, result["conda_root"], installed,
                           complete=status == "done")
        app.toolbox.refresh()

    job = ScriptJob(job_id, result["script"], workdir,
                    label="first-run setup", on_finish=remember)
    app.jobs[job_id] = job
    job.start()
    self._json({"job": job_id, "workdir": str(workdir),
                "steps": [{"id": s["id"], "name": s["name"]} for s in result["steps"]],
                "conda_root": result["conda_root"]})


def h_setup_done(self: Handler) -> None:
    """Stop offering the first-run dialog.

    Set when setup finishes and also when it is dismissed: someone who
    already has their tools should not be asked again on every start.
    """
    self.app.settings.update({"setup_done": True})
    self.app.settings.save()
    self._json({"setup_done": True})


def h_requirements(self: Handler) -> None:
    """What has to be here before this tool can be installed at all."""
    tool = self.q("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    self._json(install_requirements(self.app.settings, tool))


def h_env_remove(self: Handler) -> None:
    """Delete a conda environment, once it is clear what that costs.

    Two steps on purpose. Without ``confirm`` it answers with what would go and
    which tools resolve through it; with ``confirm`` it runs. Deleting a couple
    of gigabytes because a button was next to the wrong row is not a thing to
    do on one click.
    """
    body = self._body()
    plan = remove_env_plan(self.app.settings, body.get("env", ""))
    if plan.get("error"):
        self._error(plan["error"])
        return
    if not body.get("confirm"):
        self._json({k: v for k, v in plan.items() if k != "script"})
        return

    env = plan["env"]
    job_id = uuid.uuid4().hex[:10]
    workdir = self.app.settings.data_dir / "installs" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    app = self.app

    def tidy(status: str) -> None:
        # Only once it is actually gone: a failed removal that forgot the
        # environment anyway would leave a working install nothing points at.
        if status == "done":
            forget_env(app.settings, env)
        app.toolbox.refresh()

    job = ScriptJob(job_id, plan["script"], workdir,
                    label=f"remove {env}", on_finish=tidy)
    app.jobs[job_id] = job
    job.start()
    self._json({"job": job_id, "env": env, "path": plan["path"]})


def h_install_script(self: Handler) -> None:
    body = self._body()
    tool = body.get("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    try:
        script = self.app.toolbox.install_script(tool, body.get("env", ""),
                                                 body.get("version", ""))
    except ValueError as exc:
        self._error(str(exc))
        return
    self._json({"script": script})


def h_install(self: Handler) -> None:
    body = self._body()
    tool = body.get("tool", "")
    if tool not in CATALOG:
        self._error(f"unknown tool '{tool}'", 404)
        return
    version = str(body.get("version") or "").strip()
    env = (body.get("env") or env_name_for(CATALOG[tool], version)).strip()
    short = install_requirements(self.app.settings, tool)
    if short["missing"] and not body.get("anyway"):
        self._error(f"{CATALOG[tool].name} cannot be installed yet: "
                    + ", ".join(short["missing"]) + " missing")
        return
    try:
        script = self.app.toolbox.install_script(tool, env, version)
    except ValueError as exc:
        self._error(str(exc))
        return
    job_id = uuid.uuid4().hex[:10]
    workdir = self.app.settings.data_dir / "installs" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    app = self.app

    def remember() -> None:
        # Recorded, not merely pointed at: installing a second version should
        # leave the first one findable rather than replacing the only pointer
        # to it.
        remember_install(app.settings, tool, env, version)
        app.toolbox.refresh()

    job = ScriptJob(job_id, script, workdir, label=f"install {tool} into {env}",
                    on_success=remember)
    self.app.jobs[job_id] = job
    job.start()
    self._json({"job": job_id, "env": env, "script": script})


def h_job(self: Handler, job_id: str) -> None:
    job = self.app.jobs.get(job_id)
    if job is None:
        self._error("no such job", 404)
        return
    self._json({"id": job.id, "label": job.label, "status": job.status,
                "returncode": job.returncode, "lines": job.lines[-500:]})


def h_job_events(self: Handler, job_id: str) -> None:
    job = self.app.jobs.get(job_id)
    if job is None:
        self._error("no such job", 404)
        return
    self._follow(job.bus, lambda: job.over)


def h_validate(self: Handler) -> None:
    graph = Graph(self._body().get("graph") or {})
    self._json({"problems": graph.validate(), "left_out": graph.left_out_summary()})


def h_plan(self: Handler) -> None:
    graph = Graph(self._body().get("graph") or {})
    plans = dry_plan(graph, self.app.settings)
    summary = {}
    for node_id, entry in plans.items():
        summary[node_id] = {
            "type": entry.get("type", ""),
            "error": entry.get("error", ""),
            "outputs": entry.get("outputs", {}),
            "notes": entry.get("notes", []),
            # Whether the error is "this graph is wrong" or "this machine has
            # not got that program". The editor colours them differently, so
            # the flag has to survive this re-serialisation.
            "missing_tool": bool(entry.get("missing_tool")),
        }
    order: List[str] = []
    try:
        order = graph.topo_order()
    except GraphError:
        pass
    self._json({"plans": summary, "order": order,
                "problems": graph.validate(),
                # Switched off in the editor, or depending on something that
                # is: left out of everything above, and said so here so the
                # editor can show which and why.
                "left_out": graph.left_out_summary(),
                "signatures": graph.signatures(order) if order else {},
                # What pressing Run would actually do. Rides along with the
                # check the editor already asks for after every edit, because
                # it costs a hash per node and a dict lookup, and a second
                # round trip for it would be the expensive part.
                "forecast": self.app.executor.forecast(
                    graph, only=self._body().get("only") or None,
                    isolate=bool(self._body().get("isolate")))})


def workflow_tools(app, graph: Graph, recorded: Dict[str, Any],
                   probe: bool = False) -> Dict[str, Any]:
    """Which programs this workflow needs, and which of them are not here.

    A workflow is a list of nodes, and every node names the program it drives.
    Somebody handed a workflow built on another machine has no way of knowing
    what it will want until it stops halfway through -- so this answers the
    question before anything runs.

    ``recorded`` is what the file itself says about the versions it was built
    with, written in when it was saved here. Missing for a file from an older
    Comfy-gmx, or from somebody who never had the tool either: then there is no
    version to match and only "the newest" is on offer.

    Nothing is run: presence is decided from what is on disk, the way first-run
    setup decides it, so this is quick enough to answer every time a workflow
    is opened.
    """
    box = app.toolbox
    wanted: Dict[str, Dict[str, Any]] = {}
    for node_id, node in graph.nodes.items():
        node_type = node.get("type", "")
        if not REGISTRY.has(node_type):
            continue
        cls = REGISTRY.get(node_type)
        tool_id = getattr(cls, "tool", "") or ""
        # "shell" is bash, "python" is the one running this: neither is
        # something anybody has to go and install.
        if tool_id in ("", "shell", "python") or tool_id not in CATALOG:
            continue
        entry = wanted.setdefault(tool_id, {"id": tool_id, "nodes": [], "titles": []})
        entry["nodes"].append(node_id)
        title = cls.title or node_type
        if title not in entry["titles"]:
            entry["titles"].append(title)

    tools = []
    for tool_id, entry in sorted(wanted.items()):
        spec = CATALOG[tool_id]
        status = bootstrap._tool_status(box, tool_id)
        here = ""
        for install in box.installs_of(tool_id):
            if install.get("gone"):
                continue
            here = install.get("version") or install.get("guess") or ""
            if install.get("active"):
                break
        if not here and tool_id == "gmx":
            # The build actually in use, not merely the first one found: with
            # several GROMACS installations on a machine those are different
            # answers, and the wrong one would be written into the workflow.
            configured = str(box.settings.get("gmxrc") or "").strip()
            found = box.gmxrc_candidates()
            chosen = next((f for f in found if f.get("path") == configured), None)
            here = ((chosen or (found[0] if found else {})).get("version") or "")
        if probe and status["present"] and not here:
            # Asked for only when a workflow is being written out, because it
            # runs each tool's version check and that is a second or two each.
            try:
                answer = box.probe(tool_id, timeout=8.0)
                # The number out of the banner: a program answers with a whole
                # sentence, and a sentence is no use to the machine that has to
                # match it later.
                here = (_version_number(answer.get("version", ""))
                        if answer.get("found") else "")
            except Exception:
                here = ""
        tools.append({
            **entry,
            "name": spec.name,
            "description": spec.description,
            "optional": spec.optional,
            "present": bool(status["present"]),
            "where": status["where"],
            "version": here,
            # What the file says it was built with, if it says anything.
            "wanted": str((recorded.get(tool_id) or {}).get("version") or ""
                          if isinstance(recorded.get(tool_id), dict)
                          else (recorded.get(tool_id) or "")),
            "installable": bool(spec.conda_installable),
            "licence_key": spec.licence_key,
            "versions_from": spec.versions_from,
        })
    return {
        "tools": tools,
        "missing": [t["id"] for t in tools if not t["present"]],
        # What to write into a workflow saved here, so the next machine knows
        # what it was built against.
        "stamp": {t["id"]: {"version": t["version"]} for t in tools if t["version"]},
    }


def h_graph_tools(self: Handler) -> None:
    """What a workflow needs installed, and what this machine has not got."""
    body = self._body()
    graph = Graph(body.get("graph") or {})
    recorded = body.get("tools") or {}
    if not isinstance(recorded, dict):
        recorded = {}
    self._json(workflow_tools(self.app, graph, recorded,
                              probe=bool(body.get("probe"))))


def h_preview(self: Handler) -> None:
    body = self._body()
    graph = Graph(body.get("graph") or {})
    node_id = body.get("node", "")
    self._json(preview_node(graph, node_id, self.app.settings))


def h_run(self: Handler) -> None:
    body = self._body()
    run = self.app.executor.start(
        body.get("graph") or {},
        only=body.get("only") or None,
        force=body.get("force") or None,
        label=body.get("label", ""),
        output_dir=body.get("output_dir", "") or "",
        session=body.get("session", "") or "",
        # "just these nodes", as opposed to "these and everything they need"
        isolate=bool(body.get("isolate")),
    )
    reused = [node_id for node_id, state in run.nodes.items()
              if self.app.executor.cached_result(state.signature)
              and node_id not in (body.get("force") or [])]
    self._json({"run": run.id, "order": run.order, "workdir": str(run.workdir),
                "reused": reused,
                "will_run": [n for n in run.order if n not in set(reused)]})


def h_export(self: Handler) -> None:
    """Write a workflow out as a folder of shell scripts.

    Nothing about the result depends on Comfy-gmx: it is the same commands,
    with the staging Comfy-gmx does in Python written out as shell and every
    machine-specific path lifted into one ``env.sh``.  ``nodes`` exports a
    slice of the graph -- prepare here, produce elsewhere -- and what that
    slice reads from the nodes left out has to have been produced already.
    """
    from .export import export_workflow, ExportError

    body = self._body()
    dest = str(body.get("dest") or "").strip()
    if not dest:
        self._error("where should it go?", 400)
        return
    try:
        result = export_workflow(
            body.get("graph") or {},
            self.app.settings,
            dest,
            only=body.get("nodes") or None,
            label=body.get("label", "") or "",
            copy_inputs=body.get("copy_inputs", True),
            slurm=body.get("slurm") or None,
            executor=self.app.executor,
        )
    except ExportError as exc:
        self._error(str(exc), 400)
        return
    self._json(result)


def h_output_dir(self: Handler) -> None:
    """Resolve and check a candidate output directory before a run needs it.

    The UI calls this while the user is typing a path, so it reports what it
    would do rather than doing it: whether the directory exists, whether it can
    be written to, and how much room is left. Nothing is created here.
    """
    body = self._body()
    settings = self.app.settings
    target = resolve_output_dir(settings, body.get("path", "") or "")

    # Every one of these can raise: a path under a 0700 directory answers
    # PermissionError to exists(), not False. Report that as the answer rather
    # than letting it become a 500.
    def is_dir(path: Path) -> bool:
        try:
            return path.is_dir()
        except OSError:
            return False

    def exists_ok(path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return False

    exists = is_dir(target)
    probe = target
    while not exists_ok(probe) and probe.parent != probe:
        probe = probe.parent
    try:
        writable = os.access(probe, os.W_OK | os.X_OK)
    except OSError:
        writable = False

    free = 0
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        pass

    problem = ""
    if not is_dir(probe):
        problem = f"{probe} is not a directory, or is not readable"
    elif not writable:
        problem = f"no permission to write in {probe}"

    self._json({
        "path": str(target),
        "exists": exists,
        "creates": "" if exists else str(target),
        "writable": writable,
        "free_bytes": free,
        "problem": problem,
        "default": str(settings.runs_dir),
    })


def h_runs(self: Handler) -> None:
    self._json({"runs": self.app.executor.list_runs()})


def h_run_detail(self: Handler, run_id: str) -> None:
    run = self.app.executor.get(run_id)
    if run is None:
        self._error("no such run", 404)
        return
    self._json(run.to_dict(with_log=self.q("log", "0") == "1"))


def h_run_events(self: Handler, run_id: str) -> None:
    run = self.app.executor.get(run_id)
    if run is None:
        self._error("no such run", 404)
        return
    self._follow(run.bus, lambda: run.status in ("done", "error", "cancelled"))


def h_run_cancel(self: Handler, run_id: str) -> None:
    """Stop a run. Ask again and it stops harder -- see Executor.cancel."""
    hard = bool(self._body().get("hard") or self._body().get("force"))
    self._json(self.app.executor.cancel(run_id, hard=hard))


def h_run_resume(self: Handler, run_id: str) -> None:
    """Let a run that is being held at a node carry on."""
    self._json(self.app.executor.resume(run_id, self._body().get("graph") or None))


def h_run_input(self: Handler, run_id: str) -> None:
    """Type a line into whatever is running, or close its input (Ctrl-D)."""
    body = self._body()
    self._json(self.app.executor.send_input(
        run_id, str(body.get("node") or ""), str(body.get("text") or ""),
        eof=bool(body.get("eof"))))


def h_shell(self: Handler) -> None:
    """The Terminal drawer's Shell tab: a real bash, over a WebSocket.

    Everything about the shell itself is in shell.py. This part answers the
    browser's request to open the connection, and then hands it over.
    """
    headers = self.headers
    # Whatever the answer, this connection is not used for another request.
    self.close_connection = True
    foreign = shell.foreign_page(headers)
    if foreign:
        # Not a Comfy-gmx page. It is told nothing more than no.
        self._error(foreign, 403)
        return
    if (headers.get("Upgrade") or "").lower() != "websocket":
        self._error("this address is for the Terminal drawer's Shell tab, "
                    "which opens it as a WebSocket", 400)
        return
    if (headers.get("Sec-WebSocket-Version") or "").strip() != "13":
        self._send(426, b"only WebSocket version 13", "text/plain; charset=utf-8",
                   {"Sec-WebSocket-Version": "13"})
        return
    key = (headers.get("Sec-WebSocket-Key") or "").strip()
    if not key:
        self._error("no Sec-WebSocket-Key", 400)
        return
    # The connection is opened even when the shell is then refused: a
    # browser shows the page nothing of a refused opening, only that it
    # failed, and the reason is what somebody needs in order to fix it.
    self.send_response(101, "Switching Protocols")
    self.send_header("Upgrade", "websocket")
    self.send_header("Connection", "Upgrade")
    self.send_header("Sec-WebSocket-Accept", shell.accept_value(key))
    self.end_headers()
    self.wfile.flush()
    sock = shell.Socket(self.rfile, self.wfile, self.connection)
    why = shell.unknown_name(headers, self.server.server_address[0])
    if not why:
        try:
            session, fresh = self.app.shells.find_or_start(
                self.q("id"), self.q("cwd"), self.q("cols", "80"), self.q("rows", "24"))
        except shell.ShellError as exc:
            why = str(exc)
    if why:
        try:
            sock.send_json({"type": "refused", "why": why})
        except OSError:
            pass
        sock.close()
        return
    shell.converse(sock, session, fresh)


def h_node_log(self: Handler, run_id: str, node_id: str) -> None:
    run = self.app.executor.get(run_id)
    if run is None or node_id not in run.nodes:
        self._error("no such run or node", 404)
        return
    state = run.nodes[node_id]
    self._json({"node": node_id, "status": state.status, "log": list(state.log),
                "workdir": state.workdir, "notes": state.notes, "error": state.error})


def h_run_folders(self: Handler) -> None:
    """The run directories under one folder, with what each is worth."""
    raw = self.q("root") or ""
    root = Path(local_path(raw)) if raw else resolve_output_dir(self.app.settings, "")
    if not root.is_dir():
        self._error(f"no such folder: {root}", 404)
        return
    self._json(self.app.executor.run_folders(root))


def h_run_folder_delete(self: Handler) -> None:
    """Delete one run directory. Only ever a run directory -- see looks_like_run."""
    path = Path(local_path(str(self._body().get("path") or "")))
    result = self.app.executor.remove_run_folder(path)
    if result.get("error"):
        self._error(result["error"])
        return
    self._json(result)


def h_cache(self: Handler) -> None:
    """What the node cache is holding. See Executor.cache_stats."""
    self._json(self.app.executor.cache_stats())


def h_cache_clear(self: Handler) -> None:
    self._json({"cleared": self.app.executor.clear_cache()})


# -- workflows --------------------------------------------------------------

_SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,120}$")


def h_workflows(self: Handler) -> None:
    roots = self.app.settings.workflow_roots()
    items = []
    seen = set()
    for root in roots:
        for path in sorted(root["path"].glob("*.json")):
            try:
                stat = path.stat()
            except OSError:
                continue
            # A name in an earlier root wins: your own copy of an example
            # should be what opens, not the shipped one.
            key = (root["label"], path.stem)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "name": path.stem, "path": str(path),
                "source": root["label"], "writable": bool(root["writable"]),
                "size": stat.st_size, "modified": stat.st_mtime,
            })
    self._json({
        "workflows": items,
        "directory": str(self.app.settings.workflows_dir),
        "roots": [{"label": r["label"], "path": str(r["path"]),
                   "writable": bool(r["writable"])} for r in roots],
    })


def _find_workflow(settings, name: str) -> Optional[Path]:
    for root in settings.workflow_roots():
        candidate = root["path"] / f"{name}.json"
        if candidate.is_file():
            return candidate
    return None


def h_workflow_save(self: Handler) -> None:
    body = self._body()
    name = (body.get("name") or "").strip()
    if not _SAFE_NAME.match(name):
        self._error("workflow names may contain letters, digits, space, dot, dash and underscore")
        return
    path = self.app.settings.workflows_dir / f"{name}.json"
    path.write_text(json.dumps(body.get("graph") or {}, indent=2))
    self._json({"saved": name, "path": str(path)})


def h_workflow_load(self: Handler, name: str) -> None:
    path = _find_workflow(self.app.settings, name)
    if path is None:
        self._error("no such workflow", 404)
        return
    self._json({"name": name, "graph": json.loads(path.read_text()),
                "path": str(path)})


def h_workflow_delete(self: Handler, name: str) -> None:
    # Only ever from the directory Save writes to. The shipped examples and
    # tutorials are read-only on purpose.
    path = self.app.settings.workflows_dir / f"{name}.json"
    if not path.is_file():
        found = _find_workflow(self.app.settings, name)
        if found is not None:
            self._error(f"{found} is not yours to delete: it ships with Comfy-gmx")
            return
    if path.is_file():
        path.unlink()
    self._json({"deleted": name})


# -- files ------------------------------------------------------------------

def h_files(self: Handler) -> None:
    raw = self.q("path") or str(Path.home())
    directory = Path(local_path(raw))
    if not directory.is_dir():
        self._error(f"not a directory: {directory}", 404)
        return
    entries = []
    try:
        for child in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith(".") and self.q("hidden") != "1":
                continue
            try:
                stat = child.stat()
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size, mtime = 0, 0
            entries.append({"name": child.name, "path": str(child),
                            "dir": child.is_dir(), "size": size, "modified": mtime})
    except PermissionError:
        self._error("permission denied", 403)
        return
    self._json({"path": str(directory), "parent": str(directory.parent), "entries": entries})


def h_files_find(self: Handler) -> None:
    """Look for files by name, in a folder and everything under it.

    Filtering what is on screen only reaches the folder you are standing in,
    and a run puts its results in a folder per node -- so "where did that .gro
    go" is a question about the whole tree. This walks it.

    Bounded three ways, because a mistyped path can be somebody's entire home
    directory: it stops after enough matches to be useful, after enough
    directories to be sure, and after a couple of seconds either way. When it
    stops early it says so, rather than quietly showing part of the answer.
    """
    raw = self.q("path") or str(Path.home())
    needle = (self.q("q") or "").strip().lower()
    if not needle:
        self._json({"path": raw, "entries": [], "complete": True})
        return
    root = Path(local_path(raw))
    if not root.is_dir():
        self._error(f"not a directory: {root}", 404)
        return

    limit = 400
    deadline = time.monotonic() + 2.5
    seen_dirs = 0
    entries: List[Dict[str, Any]] = []
    complete = True
    show_hidden = self.q("hidden") == "1"
    for here, dirs, names in os.walk(str(root), onerror=lambda err: None):
        seen_dirs += 1
        if not show_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(names) + sorted(dirs):
            if not show_hidden and name.startswith("."):
                continue
            if needle not in name.lower():
                continue
            full = os.path.join(here, name)
            try:
                stat = os.stat(full)
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size, mtime = 0, 0
            entries.append({"name": name, "path": full, "dir": os.path.isdir(full),
                            "size": size, "modified": mtime,
                            # Where it is, relative to what was searched, so a
                            # list of forty files is still readable.
                            "where": os.path.relpath(here, str(root))})
            if len(entries) >= limit:
                complete = False
                break
        if not complete or seen_dirs > 20000 or time.monotonic() > deadline:
            complete = complete and seen_dirs <= 20000 and time.monotonic() <= deadline
            break
    self._json({"path": str(root), "parent": str(root.parent), "entries": entries,
                "complete": complete, "searched": seen_dirs})


#: A name typed into "New folder" or "New file". One path component, nothing
#: that climbs out of the directory it is being created in.
def _one_name(raw: str) -> str:
    name = str(raw or "").strip().strip("/")
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("that is a name, not a path: one folder or file name, "
                         "no slashes")
    return name


def _paths_from(body) -> List[str]:
    raw = body.get("paths")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    return [local_path(str(item)) for item in raw if str(item).strip()]


def h_files_copy(self: Handler) -> None:
    """Copy files and folders into another folder. Never over anything."""
    from . import fileops
    body = self._body()
    result = fileops.transfer(_paths_from(body),
                              local_path(str(body.get("destination") or "")),
                              self.app.settings, move=False)
    if result.get("error"):
        self._error(result["error"])
        return
    self._json(result)


def h_files_move(self: Handler) -> None:
    """Move files and folders into another folder. Never over anything."""
    from . import fileops
    body = self._body()
    result = fileops.transfer(_paths_from(body),
                              local_path(str(body.get("destination") or "")),
                              self.app.settings, move=True)
    if result.get("error"):
        self._error(result["error"])
        return
    self._json(result)


def h_files_delete(self: Handler) -> None:
    """Put things in the trash, or get rid of them when told plainly.

    The reply for something on another disk is deliberately not an error: it
    carries how big each one is, so the panel can say what it would cost to
    copy and offer the other choice, rather than just refusing.
    """
    from . import fileops
    body = self._body()
    result = fileops.delete(_paths_from(body), self.app.settings,
                            forever=bool(body.get("forever")))
    if result.get("error"):
        self._error(result["error"])
        return
    self._json(result)


def h_files_rename(self: Handler) -> None:
    """Give one file or folder a different name, where it already is."""
    from . import fileops
    body = self._body()
    result = fileops.rename(local_path(str(body.get("path") or "")),
                            str(body.get("name") or ""), self.app.settings)
    if result.get("error"):
        self._error(result["error"])
        return
    self._json(result)


def h_mkdir(self: Handler) -> None:
    """Create one directory inside another.

    Here so that choosing where a run goes does not mean leaving the browser to
    make the folder first. Only one level, and only under a directory that
    already exists: a typo should be a message, not a tree of empty folders in
    a place nobody meant.
    """
    body = self._body()
    parent = Path(local_path(str(body.get("path") or "")))
    if not parent.is_dir():
        self._error(f"not a directory: {parent}", 404)
        return
    try:
        name = _one_name(body.get("name"))
    except ValueError as exc:
        self._error(str(exc))
        return
    target = parent / name
    if target.exists():
        self._error(f"{name} is already there")
        return
    try:
        target.mkdir()
    except OSError as exc:
        self._error(f"could not create {target}: {exc.strerror or exc}")
        return
    self._json({"path": str(target), "name": name})


def h_write(self: Handler) -> None:
    """Write a text file: a new one, or the edited contents of an existing one.

    Small files only. This is for an mdp, an index file, a note beside a run --
    the things you would otherwise alt-tab to an editor for. Anything that
    needs a real editor should be opened in one.
    """
    body = self._body()
    raw_path = str(body.get("path") or "")
    text = str(body.get("text") or "")
    if len(text.encode("utf-8")) > MAX_TEXT_WRITE:
        self._error(f"that is over {MAX_TEXT_WRITE // 1024} kB; write it with an editor")
        return
    if body.get("name"):
        parent = Path(local_path(raw_path))
        if not parent.is_dir():
            self._error(f"not a directory: {parent}", 404)
            return
        try:
            target = parent / _one_name(body.get("name"))
        except ValueError as exc:
            self._error(str(exc))
            return
        if target.exists() and not body.get("overwrite"):
            self._error(f"{target.name} is already there")
            return
    else:
        target = Path(local_path(raw_path))
        if target.is_dir():
            self._error(f"{target} is a directory")
            return
        if not target.parent.is_dir():
            self._error(f"no such folder: {target.parent}", 404)
            return
    try:
        target.write_text(text)
    except OSError as exc:
        self._error(f"could not write {target}: {exc.strerror or exc}")
        return
    self._json({"path": str(target), "name": target.name,
                "size": target.stat().st_size})


def h_file(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    if self.q("download") == "1":
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype,
                   {"Content-Disposition": f'attachment; filename="{path.name}"'})
        return
    limit = int(self.q("bytes", "200000") or 200000)
    size = path.stat().st_size
    with path.open("rb") as fh:
        if self.q("tail") == "1" and size > limit:
            fh.seek(size - limit)
        data = fh.read(limit)
    self._json({"path": str(path), "size": size, "truncated": size > limit,
                "text": data.decode("utf-8", errors="replace")})


def h_stat(self: Handler) -> None:
    """What is at this path?  Answers the canvas when a file is dropped on it.

    A drop that carries a real path is worth a great deal more than one that
    only carries the bytes: the node can point at the original file instead of
    at a copy, which matters when the original is a 15 GB trajectory. This
    endpoint is how the browser finds out whether the path it was handed is
    one this machine can actually see.
    """
    raw = self.q("path") or ""
    path = Path(local_path(raw))

    # Anything under a directory this user cannot traverse answers OSError
    # rather than False, and a dropped path is exactly the sort of thing that
    # lands somewhere unreadable.
    def probe(fn: Callable[[], bool]) -> bool:
        try:
            return bool(fn())
        except OSError:
            return False

    is_dir = probe(path.is_dir)
    is_file = probe(path.is_file)
    size = 0
    if is_file:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
    self._json({
        "path": str(path),
        "name": path.name,
        "exists": is_dir or is_file,
        "dir": is_dir,
        "file": is_file,
        "size": size,
        "readable": probe(lambda: os.access(path, os.R_OK)),
    })


def h_copy(self: Handler) -> None:
    """Copy a file the server can already see to somewhere else on this machine.

    The Save button beside a structure -- in a preview node, in the Viewer tab --
    needs the copy to happen where the file is.  A browser download would pull
    the bytes through the page and hand them to the download folder, which is
    the wrong place and the wrong route for something already sitting on the
    same disk.
    """
    body = self._body()
    source = Path(local_path(body.get("source") or ""))
    if not source.is_file():
        self._error(f"nothing to copy at {source}", 404)
        return
    raw_dest = (body.get("destination") or "").strip()
    if not raw_dest:
        self._error("no folder to save into")
        return
    directory = Path(local_path(raw_dest))
    name = os.path.basename((body.get("name") or "").strip() or source.name)
    if not name:
        self._error("no file name")
        return

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        self._error(f"cannot create {directory}: {exc}", 403)
        return

    target = directory / name
    if target.exists():
        if target.resolve() == source.resolve():
            self._error("that is the file itself")
            return
        mode = body.get("on_exists") or "overwrite"
        if mode == "stop":
            self._error(f"{name} is already in {directory}; nothing written", 409)
            return
        if mode == "timestamp":
            stamp = time.strftime("%Y%m%d-%H%M%S")
            target = directory / (f"{target.stem}_{stamp}{target.suffix}")
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        self._error(f"cannot write {target}: {exc}", 403)
        return
    self._json({"path": str(target), "name": target.name,
                "size": target.stat().st_size})


def h_upload(self: Handler) -> None:
    name = os.path.basename(self.q("name") or "")
    if not name:
        self._error("missing ?name=")
        return
    length = int(self.headers.get("Content-Length") or 0)
    if length <= 0:
        self._error(f"{name} is empty")
        return
    if length > MAX_BODY:
        self._error(
            f"{name} is {length / 1e6:.0f} MB; uploads stop at "
            f"{MAX_BODY // (1024 * 1024)} MB. Point a node at the file where it "
            f"already is instead of copying it in.")
        return
    # A drop on the canvas has nowhere in particular to go and lands in the
    # uploads folder; a drop on the file browser means "put it here".
    directory = self.q("dir") or ""
    target = (Path(local_path(directory)) if directory
              else self.app.settings.uploads_dir) / name
    if directory and not target.parent.is_dir():
        self._error(f"not a directory: {target.parent}", 404)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = length
    with target.open("wb") as fh:
        while remaining > 0:
            chunk = self.rfile.read(min(1 << 20, remaining))
            if not chunk:
                break
            fh.write(chunk)
            remaining -= len(chunk)
    self._json({"path": str(target), "name": name, "size": target.stat().st_size})


# -- visualisation ----------------------------------------------------------

def h_viz_structure(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    self._json(parse_structure(path, int(self.q("max", "40000") or 40000)))


#: Structures fetched to answer "what is in it" are kept, so asking twice
#: about the same entry does not download it twice.
_RCSB = "https://files.rcsb.org/download/"


def _viz_source(self: Handler):
    """The file a "what is in it" question is about: a path, or a PDB id.

    Returns ``(path, fetched)`` or ``None`` after having already answered with
    an error.  A fetched entry is kept, so asking twice about the same one does
    not download it twice.
    """
    pdb_id = (self.q("pdb") or "").strip().lower()
    if not pdb_id:
        path = Path(local_path(self.q("path")))
        if not path.is_file():
            self._error("not a file", 404)
            return None
        return path, ""

    if not pdb_id.isalnum() or len(pdb_id) not in (4, 8):
        self._error(f"'{pdb_id}' does not look like a PDB identifier")
        return None
    fmt = "cif" if (self.q("format") or "pdb").lower() == "cif" else "pdb"
    cache = self.app.settings.data_dir / "cache" / "rcsb"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{pdb_id}.{fmt}"
    if not target.is_file():
        url = f"{_RCSB}{pdb_id}.{fmt}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = response.read()
        except Exception as exc:  # noqa: BLE001 - urllib raises many things
            self._error(f"could not fetch {url}: {exc}", 502)
            return None
        target.write_bytes(body)
    return target, str(target)


def h_viz_composition(self: Handler) -> None:
    """Chains, residue ranges and molecule species, before anything is run.

    This is what stops you having to open the file somewhere else to find out
    which chain letters to type into a cleaning node.
    """
    found = _viz_source(self)
    if found is None:
        return
    path, fetched = found
    data = parse_composition(path)
    if fetched:
        data["fetched"] = fetched
    self._json(data)


def h_viz_box_around(self: Handler) -> None:
    """How big a box this molecule needs, so one can be chosen by eye.

    There is no box yet, here is a molecule: how much room does it want.  What decides that is
    one number -- the distance between the two atoms furthest apart -- and it
    is not something you can read off a screen, so it is measured here.
    """
    found = _viz_source(self)
    if found is None:
        return
    path, _fetched = found
    data = box_around(path)
    if not data.get("error"):
        data["shapes"] = box_shapes(data["span"]["diameter"], 1.0,
                                    data.get("n_solute", 0))
    self._json(data)


def h_input_file(self: Handler) -> None:
    """Which file a node's input port will actually read.

    Not the same question as "what did the user type into a load node": the
    file wanted here is the one an earlier node produced, which exists only
    once that node has run. So it is looked up among the finished results,
    exactly the way running one node on its own looks up its inputs.
    """
    body = self._body()
    found = _wired_file(self, Graph(body.get("graph") or {}),
                        str(body.get("node") or ""), str(body.get("port") or ""))
    if found is not None:
        self._json(found)


def _wired_file(self: Handler, graph: Graph, node_id: str,
                port: str) -> Optional[Dict[str, str]]:
    """The file an earlier node hands to one input, from the finished results.

    Sends the reason and returns None when there is no such file yet.
    """
    if node_id in graph.left_out:
        self._error(graph.left_out_reason(node_id), 400)
        return None
    if node_id not in graph.nodes:
        self._error("no such node in this graph", 400)
        return None
    wired = graph.incoming(node_id).get(port)
    if not wired:
        self._error(f"nothing is connected to '{port}'", 400)
        return None
    source, source_port = wired
    # By the name on the block, which is what the page shows. Two blocks can
    # share one, so which socket it feeds is said as well.
    named = f"{graph._name(source)}, which hands this block its '{port}',"
    signatures = graph.signatures()
    stored = self.app.executor.cached_result(signatures.get(source, ""))
    if not stored:
        self._error(
            f"{named} has not been run yet, so the file it would hand over does "
            "not exist. Run up to it first, then come back", 404)
        return None
    value = (stored.get("outputs") or {}).get(source_port) or {}
    path = value.get("path") or ""
    if not path or not Path(path).exists():
        self._error(f"{named} ran, but the file it produced is not there any more", 404)
        return None
    return {"path": path, "name": Path(path).name, "node": source,
            "port": source_port}


def h_graph_groups(self: Handler) -> None:
    """Every group of atoms a block reading this system can be asked for.

    What the Preview trajectory block's form offers: the groups GROMACS makes
    for the system by itself, and those of an index file wired in, put
    together the way the block puts them together when it runs. They exist
    only once the run file does, so this asks the finished results, as
    h_input_file does.
    """
    body = self._body()
    graph = Graph(body.get("graph") or {})
    node_id = str(body.get("node") or "")
    tpr = _wired_file(self, graph, node_id, "tpr")
    if tpr is None:
        return
    index = ""
    if graph.incoming(node_id).get("index"):
        found = _wired_file(self, graph, node_id, "index")
        if found is None:
            return
        index = found["path"]
    try:
        listed = groups.all_groups(tpr["path"], index, self.app.toolbox)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        self._error(str(exc), 500)
        return
    self._json({"groups": listed, "from": tpr["name"],
                "index": Path(index).name if index else ""})


def h_viz_sequence(self: Handler) -> None:
    """The deposited sequence against what the coordinates actually hold.

    The answer to "how much of this is missing, and is it a loop or a tail".
    """
    found = _viz_source(self)
    if found is None:
        return
    path, fetched = found
    data = parse_sequence(path)
    if fetched:
        data["fetched"] = fetched
    self._json(data)


def h_viz_xvg(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    self._json(parse_xvg(path, int(self.q("max", "4000") or 4000)))


def h_viz_dssp(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    self._json(parse_dssp(path, int(self.q("frames", "600") or 600),
                          int(self.q("residues", "900") or 900)))


def h_gmx_ff_catalog(self: Handler) -> None:
    """What force fields are here, and what can be fetched.

    Read off the disk each time. Somebody who has just installed one, or
    dropped a folder in by hand, should see it without restarting anything.
    """
    from . import forcefields as ffs
    self._json(ffs.catalog(self.app.settings))


def h_gmx_ff_install(self: Handler) -> None:
    """Fetch one force field into the folder the topology block reads.

    Runs as a job with a log, the same as installing a tool, because a
    download that fails should say why in the same place everything else does.
    """
    from . import forcefields as ffs
    body = self._body()
    known = ffs.BY_ID.get(str(body.get("id") or "").strip())
    if known is not None:
        url, name = known.url, known.id
    else:
        try:
            url = ffs.check_url(str(body.get("url") or ""))
            name = ffs.clean_name(str(body.get("name") or ""))
        except ValueError as exc:
            self._error(str(exc))
            return
    into = self.app.settings.gmx_forcefield_dir
    job_id = uuid.uuid4().hex[:10]
    workdir = self.app.settings.data_dir / "installs" / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    job = ScriptJob(job_id, ffs.install_script(url, name, into), workdir,
                    label=f"fetch the {name} force field")
    self.app.jobs[job_id] = job
    job.start()
    self._json({"job": job_id, "name": name, "url": url, "dir": str(into)})


def h_traj_facts(self: Handler) -> None:
    """How many frames, how far apart, how many atoms.

    Reading a trajectory to count its frames is minutes on a large one, so the
    answer is kept and this only scans when asked to: without ``scan=1`` it
    reports what is already known, or that nothing is.
    """
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    entry = facts.known(self.app.settings, str(path))
    if entry:
        self._json({"known": True, **entry})
        return
    if self.q("scan") != "1":
        size = path.stat().st_size
        self._json({"known": False, "size": size, "path": str(path),
                    "note": "counting the frames means reading the whole file"})
        return
    result = facts.scan(self.app.settings, str(path), self.app.toolbox)
    if result.get("error"):
        self._error(result["error"])
        return
    self._json({"known": True, **result})


def h_viz_trajectory(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    # Deliberately small. This is a rough look played inside a node, and every
    # frame is three numbers per atom on the wire: 40 x 4000 is about 3 MB of
    # JSON, where 60 x 20000 would be thirty.
    self._json(parse_trajectory(path, int(self.q("frames", "40") or 40),
                                int(self.q("atoms", "4000") or 4000)))


def h_viz_log(self: Handler) -> None:
    path = Path(local_path(self.q("path")))
    if not path.is_file():
        self._error("not a file", 404)
        return
    self._json(parse_md_log(path))


def h_run_files(self: Handler, run_id: str) -> None:
    run = self.app.executor.get(run_id)
    if run is None:
        self._error("no such run", 404)
        return
    out = []
    for node_id, state in run.nodes.items():
        if not state.workdir:
            continue
        directory = Path(state.workdir)
        if not directory.is_dir():
            continue
        files = []
        for child in sorted(directory.iterdir()):
            if child.is_file():
                files.append({"name": child.name, "path": str(child),
                              "size": child.stat().st_size})
        out.append({"node": node_id, "type": state.type, "workdir": str(directory),
                    "files": files})
    # The run's own directory as well as each node's: the file browser opens
    # there, and deriving it from a node work directory guesses.
    self._json({"run": run_id, "directory": str(run.workdir), "nodes": out})


ROUTES: List[Tuple[re.Pattern, Tuple[str, ...], Callable]] = [
    (re.compile(r"^/api/info$"), ("GET",), h_info),
    (re.compile(r"^/api/nodes$"), ("GET",), h_nodes),
    (re.compile(r"^/api/flags$"), ("GET",), h_flags),
    (re.compile(r"^/api/mdp/presets$"), ("GET",), h_mdp_presets),
    (re.compile(r"^/api/library/gmx_forcefields$"), ("GET",), h_gmx_forcefields),
    (re.compile(r"^/api/forcefields$"), ("GET",), h_gmx_ff_catalog),
    (re.compile(r"^/api/forcefields/install$"), ("POST",), h_gmx_ff_install),
    (re.compile(r"^/api/open_folder$"), ("POST",), h_open_folder),
    (re.compile(r"^/api/traj$"), ("GET",), h_traj_facts),
    (re.compile(r"^/api/files/mkdir$"), ("POST",), h_mkdir),
    (re.compile(r"^/api/files/copy$"), ("POST",), h_files_copy),
    (re.compile(r"^/api/files/move$"), ("POST",), h_files_move),
    (re.compile(r"^/api/files/delete$"), ("POST",), h_files_delete),
    (re.compile(r"^/api/files/rename$"), ("POST",), h_files_rename),
    (re.compile(r"^/api/files/write$"), ("POST",), h_write),
    (re.compile(r"^/api/chunks$"), ("GET",), h_chunks),
    (re.compile(r"^/api/chunks$"), ("POST",), h_chunk_save),
    (re.compile(r"^/api/chunks/([^/]+)$"), ("DELETE",), h_chunk_delete),
    (re.compile(r"^/api/output-dir$"), ("POST",), h_output_dir),
    (re.compile(r"^/api/tutorials$"), ("GET",), h_tutorials),
    (re.compile(r"^/api/tutorials/([A-Za-z0-9_-]+)$"), ("GET",), h_tutorial),
    (re.compile(r"^/api/settings$"), ("GET",), h_settings_get),
    (re.compile(r"^/api/settings$"), ("POST",), h_settings_post),
    (re.compile(r"^/api/environment$"), ("GET",), h_environment),
    (re.compile(r"^/api/environment/probe$"), ("POST",), h_probe),
    (re.compile(r"^/api/environment/versions$"), ("GET",), h_versions),
    (re.compile(r"^/api/environment/installs$"), ("GET", "POST"), h_installs),
    (re.compile(r"^/api/environment/source$"), ("GET", "POST"), h_source),
    (re.compile(r"^/api/environment/updates$"), ("POST",), h_updates),
    (re.compile(r"^/api/environment/gromacs/plan$"), ("POST",), h_gromacs_plan),
    (re.compile(r"^/api/environment/gromacs/build$"), ("POST",), h_gromacs_build),
    (re.compile(r"^/api/environment/install/script$"), ("POST",), h_install_script),
    (re.compile(r"^/api/environment/install$"), ("POST",), h_install),
    (re.compile(r"^/api/environment/remove$"), ("POST",), h_env_remove),
    (re.compile(r"^/api/environment/requirements$"), ("GET",), h_requirements),
    (re.compile(r"^/api/setup$"), ("GET",), h_setup),
    (re.compile(r"^/api/setup/plan$"), ("POST",), h_setup_plan),
    (re.compile(r"^/api/setup/run$"), ("POST",), h_setup_run),
    (re.compile(r"^/api/setup/done$"), ("POST",), h_setup_done),
    (re.compile(r"^/api/jobs/([A-Za-z0-9-]+)/events$"), ("GET",), h_job_events),
    (re.compile(r"^/api/jobs/([A-Za-z0-9-]+)/cancel$"), ("POST",), h_job_cancel),
    (re.compile(r"^/api/jobs/([A-Za-z0-9-]+)$"), ("GET",), h_job),
    (re.compile(r"^/api/graph/validate$"), ("POST",), h_validate),
    (re.compile(r"^/api/graph/plan$"), ("POST",), h_plan),
    (re.compile(r"^/api/graph/preview$"), ("POST",), h_preview),
    (re.compile(r"^/api/graph/tools$"), ("POST",), h_graph_tools),
    (re.compile(r"^/api/run$"), ("POST",), h_run),
    (re.compile(r"^/api/export$"), ("POST",), h_export),
    (re.compile(r"^/api/runs$"), ("GET",), h_runs),
    # Before the /api/runs/<id> patterns below: "folders" is a valid run id as
    # far as that regex is concerned, and the first match wins.
    (re.compile(r"^/api/runs/folders$"), ("GET",), h_run_folders),
    (re.compile(r"^/api/runs/folders/delete$"), ("POST",), h_run_folder_delete),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/events$"), ("GET",), h_run_events),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/cancel$"), ("POST",), h_run_cancel),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/input$"), ("POST",), h_run_input),
    (re.compile(r"^/api/shell$"), ("GET",), h_shell),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/resume$"), ("POST",), h_run_resume),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/files$"), ("GET",), h_run_files),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)/nodes/([^/]+)/log$"), ("GET",), h_node_log),
    (re.compile(r"^/api/runs/([A-Za-z0-9-]+)$"), ("GET",), h_run_detail),
    (re.compile(r"^/api/cache$"), ("GET",), h_cache),
    (re.compile(r"^/api/cache$"), ("DELETE",), h_cache_clear),
    (re.compile(r"^/api/workflows$"), ("GET",), h_workflows),
    (re.compile(r"^/api/workflows$"), ("POST",), h_workflow_save),
    (re.compile(r"^/api/workflows/([^/]+)$"), ("GET",), h_workflow_load),
    (re.compile(r"^/api/workflows/([^/]+)$"), ("DELETE",), h_workflow_delete),
    (re.compile(r"^/api/files$"), ("GET",), h_files),
    (re.compile(r"^/api/files/find$"), ("GET",), h_files_find),
    (re.compile(r"^/api/file$"), ("GET",), h_file),
    (re.compile(r"^/api/stat$"), ("GET",), h_stat),
    (re.compile(r"^/api/copy$"), ("POST",), h_copy),
    (re.compile(r"^/api/upload$"), ("PUT", "POST"), h_upload),
    (re.compile(r"^/api/viz/structure$"), ("GET",), h_viz_structure),
    (re.compile(r"^/api/viz/composition$"), ("GET",), h_viz_composition),
    (re.compile(r"^/api/viz/box-around$"), ("GET",), h_viz_box_around),
    (re.compile(r"^/api/graph/input-file$"), ("POST",), h_input_file),
    (re.compile(r"^/api/graph/groups$"), ("POST",), h_graph_groups),
    (re.compile(r"^/api/viz/sequence$"), ("GET",), h_viz_sequence),
    (re.compile(r"^/api/viz/xvg$"), ("GET",), h_viz_xvg),
    (re.compile(r"^/api/viz/dssp$"), ("GET",), h_viz_dssp),
    (re.compile(r"^/api/viz/trajectory$"), ("GET",), h_viz_trajectory),
    (re.compile(r"^/api/viz/log$"), ("GET",), h_viz_log),
]


class PortInUse(Exception):
    """The port is taken, with something readable to say about it."""


def _who_has_the_port(host: str, port: int) -> str:
    """Is the thing already on this port us? And can we name the process?

    Answered by asking it, rather than by digging through /proc: a Comfy-gmx
    answers /api/info and says its version, and anything else does not. That
    also covers the case where the other server is somebody else's, or in a
    container, where no local process id would have been found anyway.
    """
    import json as _json
    import urllib.error
    import urllib.request

    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
    try:
        with urllib.request.urlopen(
                f"http://{shown}:{port}/api/info", timeout=3) as answer:
            info = _json.loads(answer.read())
        if "version" in info:
            return "comfygmx"
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return "something else"


def _port_advice(host: str, port: int) -> str:
    """What to do about a port that is already taken."""
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
    lines = [f"Port {port} on this machine is already taken."]
    if _who_has_the_port(host, port) == "comfygmx":
        lines += [
            "",
            "It is Comfy-gmx, already running. Nothing is wrong -- open it:",
            "",
            f"    http://{shown}:{port}/",
            "",
            "If you meant to restart it, so that a change to the code is picked",
            "up, stop the one that is running first:",
            "",
            '    pkill -f "comfygmx serve"',
            "    ./run.sh",
            "",
            "Or leave it alone and start a second one somewhere else:",
            "",
            f"    ./run.sh --port {port + 1}",
        ]
    else:
        lines += [
            "",
            "It is not Comfy-gmx -- something else is listening there. Either",
            "stop that, or use another port:",
            "",
            f"    ./run.sh --port {port + 1}",
        ]
    return "\n".join(lines)


def build_server(host: str, port: int, settings: Settings) -> ThreadingHTTPServer:
    app = App(settings)
    handler = type("BoundHandler", (Handler,), {"app": app})
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as err:
        # "Address already in use" arrived as a twenty-line Python traceback,
        # which says nothing about what to do and reads like a crash. It is
        # the most ordinary thing that can happen when starting this: the
        # server from last time is still up.
        if err.errno == errno.EADDRINUSE:
            raise PortInUse(_port_advice(host, port)) from None
        raise
    httpd.daemon_threads = True
    return httpd


def serve(host: str = "127.0.0.1", port: int = 8189,
          settings: Optional[Settings] = None) -> None:
    settings = settings or Settings()
    httpd = build_server(host, port, settings)
    shown = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
    print(f"Comfy-gmx {__version__}")
    print(f"  editor      http://{shown}:{port}/")
    print(f"  data        {settings.data_dir}")
    print(f"  node types  {len(REGISTRY.specs())}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  NOTE: bound to a non-loopback address. Anything that can reach this")
        print("        port can read your files and run commands as you.")
    # Ctrl-C already unwinds through the finally below and then through the
    # atexit hooks, which is what stops the membrane builder. `kill` does not:
    # Python's default SIGTERM handler exits without running them, and the
    # Streamlit child would keep its port for the rest of the login session.
    # Raising KeyboardInterrupt from the handler puts both signals on the same
    # path rather than adding a second shutdown route to keep in step.
    def on_term(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            try:
                signal.signal(number, on_term)
            except (ValueError, OSError):
                pass  # not the main thread, or the platform refuses it

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()
