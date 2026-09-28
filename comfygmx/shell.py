"""A real shell for the Terminal drawer's Shell tab.

The drawer's Run tab follows a run. The Shell tab holds ordinary bash shells on
this machine, the same as terminal windows: nano, cp, rm, gmx, anything you
would type there. It can keep several, each in a numbered tab of its own, and
each with its own connection to this server. This file is the server's half.

Two pieces:

* The shell runs on a *pseudo-terminal*: the kind of connection a terminal
  window gives the programs in it. Through it a program learns the size of
  the screen, so nano and less can draw on all of it, and Ctrl+C reaches the
  program in front instead of the server.
* The page and the server talk over a *WebSocket*: one connection that stays
  open and carries bytes both ways, so every key press goes straight through
  and the screen changes as soon as the program writes. The few parts of the
  WebSocket rules that a browser uses are written out below, because this
  server uses nothing outside Python's own library.

A shell outlives its page by a minute. Reloading the page, or closing the tab
by accident, finds the same shell again with what was on its screen, so a
command started from it is not killed by a reload. After the minute it is
hung up, as closing a terminal window would.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import ipaddress
import json
import os
import select
import signal
import socket
import struct
import termios
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

#: How long a shell waits for its page to come back before it is hung up.
GRACE_SECONDS = 60.0
#: How much of the latest output is kept, to redraw the screen of a page that
#: comes back.
BACKLOG_BYTES = 256 * 1024
#: The most shells one server keeps at once, for all its pages and their tabs
#: together. The page is told, so + stops there. A page stuck reconnecting
#: through some fault must not be able to fill the machine with them.
MAX_SHELLS = 8
#: The largest message the page may send in one go: a big paste, not more.
MAX_MESSAGE = 4 * 1024 * 1024

#: Fixed by the WebSocket rules (RFC 6455): the server proves it understood
#: the request by mixing this into the key the browser sent.
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_TEXT, _BINARY, _CLOSE, _PING, _PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class ShellError(Exception):
    """A shell could not be started. The message is meant for the page."""


# --------------------------------------------------------------------------
# Who may have a shell
# --------------------------------------------------------------------------

def _name_in(host: str) -> str:
    """The machine name in a Host header, without its port."""
    host = host.strip().lower()
    if host.startswith("["):  # an IPv6 address, written [::1]:8188
        return host[1:host.find("]")] if "]" in host else ""
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def _allowed_name(name: str, bound: str) -> bool:
    if name in ("localhost", "127.0.0.1", "::1") or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    allowed = {socket.gethostname().lower(), (bound or "").lower()} | _listed_names()
    return name in allowed


def _listed_names() -> set:
    """The names given in COMFYGMX_ALLOWED_HOSTS, separated by commas."""
    extra = os.environ.get("COMFYGMX_ALLOWED_HOSTS", "")
    return {part.strip().lower() for part in extra.split(",") if part.strip()}


def foreign_page(headers: Any) -> Optional[str]:
    """Why a page from another website may not have a shell, or None.

    A browser does not stop one website from opening a WebSocket to another,
    as it does for most other requests. Any page open in the same browser
    could otherwise start a shell here. It says where it came from, though,
    in the Origin line, and only this server's own page may have one.
    Programs that are not browsers send no Origin; they could run commands
    as you anyway, so there is nothing to protect from them here.
    """
    origin = (headers.get("Origin") or "").strip()
    if not origin:
        return None
    host = (headers.get("Host") or "").strip().lower()
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme in ("http", "https") and parsed.netloc.lower() == host:
        return None
    # A proxy in front of Comfy-gmx can pass the request on under a name of
    # its own; the page's own name is then allowed when it is listed.
    if parsed.scheme in ("http", "https") and (parsed.hostname or "") in _listed_names():
        return None
    return (f"a page from {origin} asked for a shell; only the Comfy-gmx page "
            "itself may open one")


def behind_jupyter() -> bool:
    """True when binder/launch.py started this server in an online session.

    There the only way in is through Jupyter. This server listens on the
    session's inside address, 127.0.0.1, which no browser can reach, and
    Jupyter passes nothing on without the session's token. The trick the name
    check stops needs the browser and this server on the same computer, so it
    cannot happen there. Jupyter also passes on the name the page was opened
    at, such as hub.2i2c.mybinder.org, which differs from site to site and
    could not be listed in advance.
    """
    return os.environ.get("COMFYGMX_BEHIND_JUPYTER") == "1"


def unknown_name(headers: Any, bound: str) -> Optional[str]:
    """Why the name the page was opened at may not have a shell, or None.

    A web page can be made to reach this server under a name of its own
    choosing, by giving that name this machine's address. The Origin check
    above cannot see that, because the page and the server then share the
    name. So the shell also wants the page opened at localhost, at an IP
    address or at this machine's own name. In an online session it does not:
    see behind_jupyter().
    """
    if behind_jupyter():
        return None
    host = (headers.get("Host") or "").strip()
    name = _name_in(host)
    if name and _allowed_name(name, bound):
        return None
    return (f"the shell only answers a page opened at localhost, at an IP "
            f"address or at this machine's name, and this one was opened at "
            f"{host or 'no name at all'}. If you reach Comfy-gmx through "
            "another name, list it in COMFYGMX_ALLOWED_HOSTS (names separated "
            "by commas) before starting the server.")


# --------------------------------------------------------------------------
# The WebSocket, server end
# --------------------------------------------------------------------------

def accept_value(key: str) -> str:
    """The answer to the browser's Sec-WebSocket-Key."""
    digest = hashlib.sha1((key.strip() + _WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def _unmask(data: bytes, mask: bytes) -> bytes:
    """Undo the scrambling a browser applies to everything it sends.

    Done on the whole message as one big number, which is far quicker in
    Python than going byte by byte through a pasted file.
    """
    size = len(data)
    if not size:
        return data
    key = (mask * (size // 4 + 1))[:size]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(size, "big")


class Socket:
    """One open WebSocket to a page, as the server sees it."""

    def __init__(self, rfile: Any, wfile: Any, connection: Any = None) -> None:
        self.rfile = rfile
        self.wfile = wfile
        self.connection = connection
        self._lock = threading.Lock()
        self.closed = False

    def _send(self, opcode: int, payload: bytes) -> None:
        size = len(payload)
        if size < 126:
            head = struct.pack("!BB", 0x80 | opcode, size)
        elif size < 1 << 16:
            head = struct.pack("!BBH", 0x80 | opcode, 126, size)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 127, size)
        with self._lock:
            if self.closed:
                raise OSError("the page has gone")
            self.wfile.write(head + payload)
            flush = getattr(self.wfile, "flush", None)
            if flush:
                flush()

    def send_bytes(self, data: bytes) -> None:
        self._send(_BINARY, data)

    def send_json(self, message: Dict[str, Any]) -> None:
        self._send(_TEXT, json.dumps(message).encode("utf-8"))

    def _read(self, size: int) -> Optional[bytes]:
        data = b""
        while len(data) < size:
            try:
                chunk = self.rfile.read(size - len(data))
            except (OSError, ValueError):
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def receive(self) -> Optional[Tuple[int, bytes]]:
        """The next whole message as (kind, bytes), or None once it is over."""
        message = bytearray()
        kind = 0
        while True:
            head = self._read(2)
            if head is None:
                return None
            final, opcode = head[0] & 0x80, head[0] & 0x0F
            masked, size = head[1] & 0x80, head[1] & 0x7F
            if size == 126:
                more = self._read(2)
                if more is None:
                    return None
                size = struct.unpack("!H", more)[0]
            elif size == 127:
                more = self._read(8)
                if more is None:
                    return None
                size = struct.unpack("!Q", more)[0]
            if size > MAX_MESSAGE or len(message) + size > MAX_MESSAGE:
                self.close(1009, "message too big")
                return None
            mask = self._read(4) if masked else b""
            if mask is None:
                return None
            payload = self._read(size) if size else b""
            if payload is None:
                return None
            if masked:
                payload = _unmask(payload, mask)
            if opcode == _CLOSE:
                self.close()
                return None
            if opcode == _PING:
                try:
                    self._send(_PONG, payload)
                except OSError:
                    return None
                continue
            if opcode == _PONG:
                continue
            if opcode in (_TEXT, _BINARY):
                kind = opcode
            message += payload
            if final:
                return kind or _BINARY, bytes(message)

    def close(self, code: int = 1000, reason: str = "") -> None:
        """Say goodbye and let go of the connection. Safe to call twice."""
        with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                body = struct.pack("!H", code) + reason.encode("utf-8")[:120]
                self.wfile.write(struct.pack("!BB", 0x80 | _CLOSE, len(body)) + body)
                flush = getattr(self.wfile, "flush", None)
                if flush:
                    flush()
            except (OSError, ValueError):
                pass
        # Wakes the thread that is waiting for the page's next key, which
        # would otherwise wait for a page that is never going to write.
        if self.connection is not None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


# --------------------------------------------------------------------------
# The shell
# --------------------------------------------------------------------------

def _shell_program() -> str:
    for candidate in (os.environ.get("SHELL", ""), "/bin/bash", "/bin/sh"):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "/bin/sh"


def _environment() -> Dict[str, str]:
    """The server's own environment, told that it is now in a terminal.

    Some names are taken out: they would tell the programs in the shell that
    they are inside tmux or screen, or describe the size of a window that is
    not this one.
    """
    env = dict(os.environ)
    for name in ("TMUX", "TMUX_PANE", "STY", "WINDOW", "TERMCAP", "COLUMNS",
                 "LINES", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "VTE_VERSION",
                 "WINDOWID"):
        env.pop(name, None)
    # The kind of terminal the page imitates, so programs know which codes
    # move the cursor and set colours.
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    return env


def _window_size(cols: int, rows: int) -> bytes:
    return struct.pack("HHHH", rows, cols, 0, 0)


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _program_name(group: int) -> str:
    """The name of the program in front, as `ps` would show it.

    The programs of one command line share a group. In `seq 1 500 | less`
    the group is named after seq, which has finished long before anybody
    looks at less, so the name is that of the group's newest program still
    running. Read from /proc, which only Linux has.
    """
    newest, name = -1, ""
    try:
        entries = os.listdir("/proc")
    except OSError:
        entries = []
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            stat = Path(f"/proc/{entry}/stat").read_text()
        except OSError:
            continue
        # The name sits in brackets and may hold spaces or brackets itself.
        close = stat.rfind(")")
        fields = stat[close + 2:].split()
        # fields: state, parent, group, ...; Z is a program that has ended.
        if len(fields) > 2 and fields[2] == str(group) and fields[0] != "Z":
            if int(entry) > newest:
                newest, name = int(entry), stat[stat.find("(") + 1:close]
    return name or "a program"


def _start(argv: List[str], cwd: str, env: Dict[str, str], cols: int,
           rows: int) -> Tuple[int, int]:
    """Start the shell on a new pseudo-terminal. Returns (process id, our end)."""
    size = _window_size(cols, rows)
    pid, fd = os.forkpty()
    if pid == 0:
        # This is the new process, about to become the shell. As little as
        # possible happens here, and nothing that could wait on the server.
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, size)
            # Python ignores the "broken pipe" signal for itself, and a
            # program started from here would inherit that: `yes | head`
            # would then end with "yes: standard output: Broken pipe".
            for name in ("SIGPIPE", "SIGXFSZ"):
                number = getattr(signal, name, None)
                if number is not None:
                    signal.signal(number, signal.SIG_DFL)
            try:
                os.chdir(cwd)
            except OSError:
                pass
            os.execve(argv[0], argv, env)
        except BaseException:  # noqa: BLE001 - nothing can be done but say so
            pass
        try:
            os.write(2, b"the shell could not be started\r\n")
        except OSError:
            pass
        os._exit(127)
    return pid, fd


class ShellSession:
    """One shell and, while one is open, the page showing it."""

    def __init__(self, cwd: str = "", cols: int = 80, rows: int = 24,
                 on_end: Optional[Callable[["ShellSession"], None]] = None) -> None:
        self.id = uuid.uuid4().hex
        wanted = Path(os.path.expanduser(cwd)) if cwd else Path.home()
        self.cwd = str(wanted if wanted.is_dir() else Path.home())
        self.argv = [_shell_program(), "-i"]
        self.cols = _clamp(cols, 2, 1000, 80)
        self.rows = _clamp(rows, 2, 1000, 24)
        self.on_end = on_end
        self.lock = threading.Lock()
        self.socket: Optional[Socket] = None
        #: When the last page went away; the minute's grace counts from here.
        #: Set from the start, so a shell whose page never arrives ends too.
        self.detached_at: Optional[float] = time.monotonic()
        self.backlog = bytearray()
        #: The program in front, or "" when the shell is waiting at its prompt.
        self.program = ""
        self.alive = True
        self.exit_code: Optional[int] = None
        self._hang_up_now = False
        #: Held while the connection to the shell is used or closed. Once it
        #: is closed its number can be given to some other file, and a key
        #: press arriving just then must not be written into that.
        self._fd_lock = threading.Lock()
        try:
            self.pid, self.fd = _start(self.argv, self.cwd, _environment(),
                                       self.cols, self.rows)
        except OSError as exc:
            raise ShellError(f"could not start a shell: {exc}") from exc
        self._fd_open = True
        # Writing never waits with the lock held: a program that is not
        # reading its keyboard would otherwise hold up the hang-up as well.
        os.set_blocking(self.fd, False)
        threading.Thread(target=self._pump, name=f"shell-{self.id[:8]}",
                         daemon=True).start()

    # -- the page -------------------------------------------------------
    def attach(self, sock: Socket, fresh: bool) -> None:
        """Show this shell on a page, starting with what is on its screen."""
        with self.lock:
            old, self.socket = self.socket, sock
            self.detached_at = None
            sock.send_json({
                "type": "ready", "id": self.id, "cwd": self.cwd,
                "shell": self.argv[0], "again": not fresh,
                "program": self.program, "catchup": len(self.backlog),
                "most": MAX_SHELLS,
            })
            if self.backlog:
                sock.send_bytes(bytes(self.backlog))
        if old is not None and old is not sock:
            try:
                old.send_json({"type": "taken"})
            except OSError:
                pass
            old.close()

    def detach(self, sock: Socket) -> None:
        with self.lock:
            if self.socket is sock:
                self.socket = None
                self.detached_at = time.monotonic()

    def _tell(self, message: Dict[str, Any]) -> None:
        with self.lock:
            sock = self.socket
            if sock is None:
                return
            try:
                sock.send_json(message)
            except OSError:
                self.socket = None
                self.detached_at = time.monotonic()

    # -- the keyboard ---------------------------------------------------
    def write(self, data: bytes) -> None:
        """Type into the shell."""
        view = memoryview(data)
        while view:
            with self._fd_lock:
                if not self._fd_open:
                    return
                try:
                    done = os.write(self.fd, view)
                except (BlockingIOError, InterruptedError):
                    done = 0
                except OSError:
                    return
            view = view[done:]
            if view and not done:
                # The program is not reading as fast as this is typed (a
                # long paste): wait until it has taken some.
                try:
                    select.select([], [self.fd], [], 0.2)
                except (OSError, ValueError):
                    return

    def resize(self, cols: Any, rows: Any) -> None:
        cols = _clamp(cols, 2, 1000, self.cols)
        rows = _clamp(rows, 2, 1000, self.rows)
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        with self._fd_lock:
            if not self._fd_open:
                return
            try:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, _window_size(cols, rows))
            except OSError:
                pass

    def _close(self) -> None:
        with self._fd_lock:
            if self._fd_open:
                self._fd_open = False
                try:
                    os.close(self.fd)
                except OSError:
                    pass

    def hang_up(self) -> None:
        """End the shell as closing its window would, within half a second."""
        self._hang_up_now = True

    # -- the shell's side -----------------------------------------------
    def _keep(self, data: bytes) -> None:
        self.backlog += data
        extra = len(self.backlog) - BACKLOG_BYTES
        if extra > 0:
            del self.backlog[:extra]

    def _out(self, data: bytes) -> None:
        with self.lock:
            self._keep(data)
            sock = self.socket
            if sock is None:
                return
            try:
                sock.send_bytes(data)
            except OSError:
                self.socket = None
                self.detached_at = time.monotonic()

    def _look_at_front(self) -> None:
        """Tell the page when the program in front of the shell changes.

        And, while the shell waits at its prompt, which folder it is in, so
        the drawer can say so after a cd. Read from /proc, which only Linux
        has; elsewhere the drawer keeps showing the folder it started in.
        """
        try:
            group = os.tcgetpgrp(self.fd)
        except OSError:
            return
        program = "" if group in (self.pid, -1) else _program_name(group)
        folder = self.cwd
        if not program:
            try:
                folder = os.readlink(f"/proc/{self.pid}/cwd")
            except OSError:
                pass
        if program != self.program or folder != self.cwd:
            self.program = program
            self.cwd = folder
            self._tell({"type": "busy", "program": program, "cwd": folder})

    def _shell_ended(self) -> bool:
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            return False
        self.exit_code = os.waitstatus_to_exitcode(status)
        return True

    def _pump(self) -> None:
        """Pass everything the shell writes on to the page, until it ends."""
        hung_up = False
        while True:
            if self._hang_up_now or (
                    self.socket is None and self.detached_at is not None
                    and time.monotonic() - self.detached_at > GRACE_SECONDS):
                hung_up = True
                break
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if ready:
                try:
                    data = os.read(self.fd, 65536)
                except BlockingIOError:
                    continue
                except OSError:  # the shell and everything it started are gone
                    data = b""
                if not data:
                    break
                self._out(data)
            self._look_at_front()
            if self.exit_code is None and self._shell_ended():
                # A job left running in the background can keep the terminal
                # open after the shell has gone; what it printed last still
                # goes to the page, then the window is closed on it.
                while select.select([self.fd], [], [], 0.05)[0]:
                    try:
                        data = os.read(self.fd, 65536)
                    except OSError:  # nothing more, or nothing there at all
                        break
                    if not data:
                        break
                    self._out(data)
                break
        self._end(hung_up)

    def _end(self, hung_up: bool) -> None:
        self.alive = False
        if hung_up:
            # Closing our end is what hangs a terminal up: the shell is sent
            # the hang-up signal, passes it on to what it started, and ends.
            # Anything started with nohup carries on.
            self._close()
        deadline = time.monotonic() + 5.0
        while self.exit_code is None and not self._shell_ended():
            if time.monotonic() > deadline:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except OSError:
                    pass
                deadline = time.monotonic() + 5.0
            time.sleep(0.05)
        self._close()
        with self.lock:
            sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.send_json({"type": "exit", "code": self.exit_code,
                                "hung_up": hung_up})
            except OSError:
                pass
            sock.close()
        if self.on_end is not None:
            self.on_end(self)


class Shells:
    """Every shell this server has open, by the name the page knows it by."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._all: Dict[str, ShellSession] = {}

    def find_or_start(self, wanted: str, cwd: str = "", cols: Any = 80,
                      rows: Any = 24) -> Tuple[ShellSession, bool]:
        """The page's shell if it is still there, or a new one.

        Returns the shell and whether it is new.
        """
        with self._lock:
            found = self._all.get(wanted or "")
            if found is not None and found.alive:
                found.resize(cols, rows)
                return found, False
            if sum(1 for s in self._all.values() if s.alive) >= MAX_SHELLS:
                raise ShellError(
                    f"{MAX_SHELLS} shells are open already, which is as many as "
                    "one Comfy-gmx keeps. Close one you no longer need with the "
                    "× on its tab, or type exit in it. Shells in pages that were "
                    "closed end by themselves a minute later.")
            session = ShellSession(cwd, _clamp(cols, 2, 1000, 80),
                                   _clamp(rows, 2, 1000, 24), on_end=self._forget)
            self._all[session.id] = session
            return session, True

    def _forget(self, session: ShellSession) -> None:
        with self._lock:
            if self._all.get(session.id) is session:
                del self._all[session.id]

    def count(self) -> int:
        with self._lock:
            return sum(1 for s in self._all.values() if s.alive)


def converse(sock: Socket, session: ShellSession, fresh: bool) -> None:
    """Carry keys from the page to the shell until the page goes away.

    What the shell writes goes the other way on its own thread (_pump).
    """
    try:
        session.attach(sock, fresh)
    except OSError:
        session.detach(sock)
        return
    try:
        while True:
            message = sock.receive()
            if message is None:
                break
            kind, payload = message
            if kind == _BINARY:
                session.write(payload)
                continue
            try:
                data = json.loads(payload.decode("utf-8"))
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            what = data.get("type")
            if what == "input":
                session.write(str(data.get("data", "")).encode("utf-8"))
            elif what == "resize":
                session.resize(data.get("cols"), data.get("rows"))
            elif what == "hangup":
                session.hang_up()
    finally:
        session.detach(sock)
        sock.close()
