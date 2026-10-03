"""Fitting a simulation to what this computer has free.

A simulation started with nothing said about threads lets GROMACS decide, and
GROMACS decides as if it had the computer to itself: one thread on every core,
each thread fixed ("pinned") to its core, and the graphics card if there is
one. When another simulation is already running, that goes badly for both.
Six of the new threads land on cores the other simulation has pinned, the
threads of a simulation wait for each other at every step, and so the new one
crawls at the pace of its slowest thread while the old one loses most of its
speed. On a workstation that happened with the ice tutorial: 15 ps in eleven
minutes, where 200 ps take a minute, and the long run beside it dropped to a
fifth of its speed.

So just before a simulation starts, this looks at the computer for about half
a second:

- which cores this program may use at all (a page started under ``taskset``,
  or inside a container, may only use some);
- how busy each core is;
- which cores another running simulation holds, because its threads are
  pinned there, or because it was itself started on a few cores only;
- whether another simulation is using the graphics card.

Then it decides. When nothing else is running and every core is ours, it
changes nothing: GROMACS chooses, as it always has. Otherwise the simulation
is kept to the free cores (``taskset``), told to start one part with that
many threads (``-ntmpi 1 -ntomp N``), and, when another simulation holds
the graphics card, either kept off it or allowed to share it, as the person
chose. Anything the person set on the block or in Settings -- threads, pinning,
the graphics card -- is theirs and is left alone.

Two more rules keep simulations that start close together apart. Each
simulation leaves a short note of the cores it was given, also when it was
given the whole computer, so one starting a few seconds later -- another
session, another page -- keeps off them before the first has shown up. And
when every core is already held by other simulations, a new one waits and
looks again every few seconds, rather than start on their cores: a thread
on a core another simulation holds slows that simulation for the whole of
its run, while waiting costs the new one only time.

Everything here is a look, never a change: nothing is written to another
program, and a computer this cannot read (a Mac, Windows) simply gets the old
behaviour, with a line in the log saying so. Exported scripts never see any of
it: the choice is made at the moment a simulation starts, on this computer,
and an exported script runs on another.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

#: What happens when every graphics card this program may use is busy with
#: another simulation. "ask" is answered in the page when Run is pressed; a
#: run nobody could ask about (the command line, or a card that became busy
#: after Run was pressed) treats it as "processor".
GPU_POLICIES = ("ask", "processor", "share")

#: A core counts as busy when something used at least this share of it while
#: we watched. A pinned simulation uses its cores fully; a browser, an editor
#: or a terminal uses a few per cent.
BUSY_SHARE = 0.5

#: A graphics card counts as busy with other work, even without a simulation
#: on it, when it is at least this busy. Drawing the desktop and an idle
#: molecule viewer stay well below.
GPU_BUSY_PERCENT = 80.0

#: GROMACS refuses more OpenMP threads than this in one process (the limit
#: is 64 in older versions). A computer with more free cores than this gets
#: this many.
MAX_THREADS = 64

#: How long another Comfy-gmx's choice of cores is honoured before its
#: simulation shows up on its own. GROMACS reads its input before it starts
#: its threads, and a big system can take a while.
CLAIM_SECONDS = 90.0

#: How often a simulation that waits for cores to come free looks again, in
#: seconds. A look takes about half a second.
WAIT_SECONDS = 15.0

#: Names of the GROMACS programs that run simulations.
_GMX_NAMES = re.compile(r"^(gmx|mdrun)(_mpi)?(_d)?$")

#: mdrun options that set threads, pinning or the graphics card. Any of them
#: on the command line means the person decided, and that part is left alone.
#: The thread list also holds the options that fix how many parts GROMACS
#: splits into (-dd, -ddorder, -gputasks, -multidir): "one part with N
#: threads" cannot be added to those without a clash.
_THREAD_FLAGS = ("-nt", "-ntmpi", "-ntomp", "-ntomp_pme", "-npme", "-dd", "-ddorder",
                 "-gputasks", "-multidir")
_PIN_FLAGS = ("-pin", "-pinoffset", "-pinstride")
_GPU_FLAGS = ("-nb", "-pme", "-pmefft", "-bonded", "-update", "-gpu_id",
              "-gputasks")


# ---------------------------------------------------------------- reading

def parse_cpu_list(text: str) -> Set[int]:
    """'0-3,8,10-11' -> {0, 1, 2, 3, 8, 10, 11}. Empty or broken -> empty."""
    cores: Set[int] = set()
    for part in (text or "").strip().split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                low, high = part.split("-", 1)
                cores.update(range(int(low), int(high) + 1))
            else:
                cores.add(int(part))
        except ValueError:
            return set()
    return cores


def cpu_list(cores: Iterable[int]) -> str:
    """{0, 1, 2, 3, 8, 10, 11} -> '0-3,8,10-11', the way taskset writes it."""
    ordered = sorted(set(cores))
    parts: List[str] = []
    start = previous = None
    for core in ordered:
        if start is None:
            start = previous = core
        elif core == previous + 1:
            previous = core
        else:
            parts.append(f"{start}-{previous}" if previous != start else str(start))
            start = previous = core
    if start is not None:
        parts.append(f"{start}-{previous}" if previous != start else str(start))
    return ",".join(parts)


def parse_proc_stat(text: str) -> Dict[int, Tuple[int, int]]:
    """Per core: (busy time, total time) from the text of /proc/stat.

    Busy is everything but waiting: idle and iowait are left out, and nice is
    counted, because a simulation started with ``nice`` is still a simulation.
    """
    out: Dict[int, Tuple[int, int]] = {}
    for line in text.splitlines():
        if not line.startswith("cpu") or line.startswith("cpu "):
            continue
        fields = line.split()
        try:
            core = int(fields[0][3:])
            values = [int(v) for v in fields[1:]]
        except ValueError:
            continue
        if len(values) < 4:
            continue
        # guest and guest_nice are already inside user and nice.
        total = sum(values[:8])
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        out[core] = (total - idle, total)
    return out


def core_load(first: Dict[int, Tuple[int, int]],
              second: Dict[int, Tuple[int, int]]) -> Dict[int, float]:
    """Share of each core that was busy between two readings of /proc/stat."""
    load: Dict[int, float] = {}
    for core, (busy2, total2) in second.items():
        busy1, total1 = first.get(core, (busy2, total2))
        spent = total2 - total1
        load[core] = max(0.0, min(1.0, (busy2 - busy1) / spent)) if spent > 0 else 0.0
    return load


def parse_cuda_visible(value: Optional[str]) -> Optional[List[str]]:
    """CUDA_VISIBLE_DEVICES as a list of tokens, or None when it is not set.

    An empty list means no card is visible: the variable is set to nothing,
    or to a value CUDA reads as "none" (-1 stops the list there).
    """
    if value is None:
        return None
    tokens: List[str] = []
    for token in value.split(","):
        token = token.strip()
        if not token or token.startswith("-"):
            break
        tokens.append(token)
    return tokens


@dataclass
class Simulation:
    """Another simulation found running on this computer."""
    pid: int
    command: str
    #: Cores it holds: the ones its threads are pinned to, or, when it was
    #: started on a few cores only, those.
    cores: Set[int] = field(default_factory=set)
    pinned: bool = False


@dataclass
class Card:
    """One graphics card, as nvidia-smi describes it."""
    index: int
    uuid: str
    name: str
    #: The other simulations using it, as (pid, command).
    users: List[Tuple[int, str]] = field(default_factory=list)
    #: How busy it is, in per cent, or None when nvidia-smi does not say.
    utilization: Optional[float] = None

    @property
    def busy(self) -> bool:
        return bool(self.users) or (
            self.utilization is not None and self.utilization >= GPU_BUSY_PERCENT)


@dataclass
class Snapshot:
    """What this computer looked like for a moment."""
    #: Every core the computer has switched on.
    cores: Set[int] = field(default_factory=set)
    #: The cores this program may run on.
    allowed: Set[int] = field(default_factory=set)
    #: A container's limit on processor use, in cores; None when there is none.
    quota: Optional[float] = None
    #: Share of each core that was busy while we watched.
    load: Dict[int, float] = field(default_factory=dict)
    simulations: List[Simulation] = field(default_factory=list)
    #: Cores claimed a moment ago by another Comfy-gmx for a simulation that
    #: may not be visible yet, with who claimed them.
    claimed: Dict[int, str] = field(default_factory=dict)
    #: core -> the other logical cores on the same physical core.
    siblings: Dict[int, Set[int]] = field(default_factory=dict)
    #: The graphics cards, or None when nvidia-smi is not there to ask.
    cards: Optional[List[Card]] = None
    #: CUDA_VISIBLE_DEVICES as this program has it (None: not set).
    cuda_visible: Optional[str] = None
    #: What could not be read, in words.
    problems: List[str] = field(default_factory=list)
    #: False where there is no /proc to read: then the cores are not judged.
    readable: bool = True


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _cgroup_quota() -> Optional[float]:
    """A container's processor limit in cores, or None.

    Binder and ``docker run --cpus`` give a share of the processor rather
    than a set of cores: the cores all look free, but only so much of them
    may be used. Read from the cgroup files, walking up from this process's
    own group, since the limit may sit on any group above it.
    """
    limits: List[float] = []
    # cgroup v2: one tree, "max 100000" or "<quota> <period>" in cpu.max.
    own = ""
    for line in _read("/proc/self/cgroup").splitlines():
        if line.startswith("0::"):
            own = line[3:].strip()
    if own:
        parts = [p for p in own.split("/") if p]
        for depth in range(len(parts), -1, -1):
            group = "/sys/fs/cgroup/" + "/".join(parts[:depth])
            text = _read(group.rstrip("/") + "/cpu.max").split()
            if len(text) == 2 and text[0] != "max":
                try:
                    limits.append(int(text[0]) / int(text[1]))
                except (ValueError, ZeroDivisionError):
                    pass
    # cgroup v1: cpu.cfs_quota_us is -1 when there is no limit.
    try:
        quota = int(_read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").strip() or "-1")
        period = int(_read("/sys/fs/cgroup/cpu/cpu.cfs_period_us").strip() or "0")
        if quota > 0 and period > 0:
            limits.append(quota / period)
    except ValueError:
        pass
    return min(limits) if limits else None


def _is_simulation(pid: int) -> Optional[str]:
    """The command line of a running GROMACS simulation, or None."""
    raw = _read(f"/proc/{pid}/cmdline")
    if not raw:
        return None
    argv = [a for a in raw.split("\0") if a]
    if not argv:
        return None
    program = os.path.basename(argv[0])
    # "gmx mdrun ..." or the old stand-alone "mdrun ...".
    if _GMX_NAMES.match(program) and ("mdrun" in argv[1:2] or program.startswith("mdrun")):
        return " ".join(argv)
    return None


def _thread_cores(pid: int) -> Tuple[Set[int], Set[int]]:
    """(cores its threads are pinned to, cores the process may use)."""
    pinned: Set[int] = set()
    allowed = parse_cpu_list(_status_field(f"/proc/{pid}/status", "Cpus_allowed_list"))
    try:
        threads = os.listdir(f"/proc/{pid}/task")
    except OSError:
        threads = []
    for tid in threads:
        mine = parse_cpu_list(_status_field(f"/proc/{pid}/task/{tid}/status",
                                            "Cpus_allowed_list"))
        if len(mine) == 1:
            pinned |= mine
    return pinned, allowed


def _status_field(path: str, name: str) -> str:
    for line in _read(path).splitlines():
        if line.startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def find_simulations(own: Set[int], cores: Set[int]) -> List[Simulation]:
    """Every other GROMACS simulation running here, and the cores it holds.

    Only GROMACS simulations are looked at for held cores. The system keeps
    small helper programs of its own fixed to every single core; reading
    those as "this core is taken" would leave nothing free.
    """
    found: List[Simulation] = []
    try:
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return found
    for pid in pids:
        if pid in own:
            continue
        command = _is_simulation(pid)
        if command is None:
            continue
        pinned, allowed = _thread_cores(pid)
        if pinned:
            found.append(Simulation(pid, command, pinned & cores or pinned, True))
        elif allowed and cores and not cores <= allowed:
            # Started on a few cores only, as this module starts them: those
            # are its own, whether or not it happened to be busy on all of
            # them while we watched.
            found.append(Simulation(pid, command, allowed & cores, False))
        else:
            found.append(Simulation(pid, command, set(), False))
    return found


def _nvidia_smi(args: Sequence[str]) -> Optional[str]:
    tool = shutil.which("nvidia-smi")
    if not tool:
        return None
    try:
        done = subprocess.run([tool, *args], capture_output=True, text=True,
                              timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_cards(gpus: str, apps: str, own: Set[int],
                is_simulation: Callable[[int], Optional[str]]) -> List[Card]:
    """Graphics cards from two nvidia-smi listings.

    ``gpus``: index, uuid, name, utilization -- one card a line.
    ``apps``: gpu_uuid, pid, process_name, used_memory -- one program a line.
    A program counts as a simulation when its command line says so, or, when
    that cannot be read (another user's program, a container), when its name
    is one of GROMACS's.
    """
    cards: List[Card] = []
    by_uuid: Dict[str, Card] = {}
    for line in gpus.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        try:
            utilization = float(parts[3]) if len(parts) > 3 else None
        except ValueError:
            utilization = None           # "[N/A]" on cards that do not say
        card = Card(index=index, uuid=parts[1], name=parts[2], utilization=utilization)
        cards.append(card)
        by_uuid[card.uuid] = card
    for line in apps.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        card = by_uuid.get(parts[0])
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if card is None or pid in own:
            continue
        command = is_simulation(pid)
        if command is None and _GMX_NAMES.match(os.path.basename(parts[2])):
            command = parts[2]
        if command is not None:
            card.users.append((pid, command))
    return cards


# ------------------------------------------------- claims between programs

def _claims_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "comfygmx" / "core-claims.json"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class Claims:
    """Cores just handed to a simulation that has not shown up yet.

    Two pages pressing Run in the same second would otherwise both see the
    same free cores and both take them: GROMACS reads its input before it
    starts any thread, so for a few seconds the first one is invisible. A
    small file under ~/.cache, shared by every Comfy-gmx of this user, the
    lite and the full version alike, holds each choice for a minute and a
    half -- by then the simulation holds its cores itself. Taken under a
    lock, so two choices cannot interleave. Where locking is not possible
    (Windows) there are no claims, and only what is running counts.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _claims_path()
        self._handle = None

    def __enter__(self) -> "Claims":
        try:
            import fcntl
        except ImportError:                 # Windows: no claims
            return self
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = open(str(self.path) + ".lock", "a+")
            fcntl.flock(self._handle, fcntl.LOCK_EX)
        except OSError:
            self._handle = None
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._handle is not None:
            try:
                import fcntl
                fcntl.flock(self._handle, fcntl.LOCK_UN)
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def _load(self) -> List[Dict[str, Any]]:
        try:
            entries = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    def current(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Claims still standing: made less than CLAIM_SECONDS ago, by a
        program that is still running."""
        if self._handle is None:
            return []
        now = time.time() if now is None else now
        return [e for e in self._load()
                if now - float(e.get("at", 0)) < CLAIM_SECONDS
                and _pid_alive(int(e.get("pid", 0) or 0))]

    def add(self, cores: Set[int], who: str, now: Optional[float] = None) -> str:
        """Claim these cores; returns the claim's name, for :meth:`release`."""
        if self._handle is None or not cores:
            return ""
        now = time.time() if now is None else now
        token = f"{os.getpid()}-{now:.6f}-{id(cores)}"
        entries = self.current(now)
        entries.append({"pid": os.getpid(), "cores": sorted(cores), "who": who,
                        "at": now, "token": token})
        self._save(entries)
        return token

    def release(self, tokens: Iterable[str]) -> None:
        """Give claims back: the simulation they were for has ended.

        Without this a claim stood for its full minute and a half, and the
        next simulation of the same run -- a heating straight after its
        minimisation -- found every core claimed by one that had finished.
        """
        tokens = {t for t in tokens if t}
        if self._handle is None or not tokens:
            return
        entries = [e for e in self.current() if e.get("token") not in tokens]
        self._save(entries)

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(entries))
            tmp.replace(self.path)
        except OSError:
            pass


# ------------------------------------------------------------- the look

def take_snapshot(sample: float = 0.5, own: Optional[Set[int]] = None,
                  claims: Optional[Claims] = None,
                  look_at_cards: bool = True) -> Snapshot:
    """Look at this computer for about ``sample`` seconds. Never raises."""
    snap = Snapshot()
    own = set(own or set()) | {os.getpid()}
    snap.cuda_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if not os.path.exists("/proc/stat"):
        snap.readable = False
        snap.problems.append("this computer has no /proc to read the cores from "
                             f"({sys.platform})")
    else:
        try:
            snap.cores = parse_cpu_list(_read("/sys/devices/system/cpu/online")) \
                or set(range(os.cpu_count() or 1))
            if hasattr(os, "sched_getaffinity"):
                snap.allowed = set(os.sched_getaffinity(0)) & snap.cores or set(snap.cores)
            else:
                snap.allowed = set(snap.cores)
            snap.quota = _cgroup_quota()
            for core in snap.cores:
                siblings = parse_cpu_list(_read(
                    f"/sys/devices/system/cpu/cpu{core}/topology/thread_siblings_list"))
                if len(siblings) > 1:
                    snap.siblings[core] = siblings - {core}
            first = parse_proc_stat(_read("/proc/stat"))
            time.sleep(max(0.0, sample))
            second = parse_proc_stat(_read("/proc/stat"))
            snap.load = core_load(first, second)
            if not snap.load:
                snap.problems.append("/proc/stat could not be read")
            snap.simulations = find_simulations(own, snap.cores)
            if claims is not None:
                for entry in claims.current():
                    for core in entry.get("cores") or []:
                        snap.claimed[int(core)] = str(entry.get("who") or "another Comfy-gmx")
        except Exception as exc:                      # noqa: BLE001
            snap.readable = False
            snap.problems.append(f"the cores could not be read: {exc}")
    if look_at_cards:
        snap.cards = look_at_graphics_cards(own)
    return snap


def look_at_graphics_cards(own: Set[int]) -> Optional[List[Card]]:
    """The NVIDIA graphics cards and who uses them, or None without nvidia-smi."""
    gpus = _nvidia_smi(["--query-gpu=index,uuid,name,utilization.gpu",
                        "--format=csv,noheader,nounits"])
    if gpus is None:
        return None
    apps = _nvidia_smi(["--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
                        "--format=csv,noheader,nounits"]) or ""
    return parse_cards(gpus, apps, own, _is_simulation)


# ------------------------------------------------------------ the choice

@dataclass
class Decision:
    """What a simulation gets, and why, in words for its log."""
    #: Cores to keep it to, for taskset; None: no restriction.
    cores: Optional[Set[int]] = None
    #: Threads to start; None: GROMACS decides.
    threads: Optional[int] = None
    #: True for an MPI build of GROMACS, which has no thread-MPI: then only
    #: -ntomp is given, and the one process it is started as is the one part.
    mpi: bool = False
    #: Value for CUDA_VISIBLE_DEVICES; None: leave the cards as they are.
    cuda_visible: Optional[str] = None
    #: The cores the simulation will run on, to be written in the claims
    #: file so that another starting at the same moment keeps off them;
    #: None when that is not known (threads set by hand, say).
    claim: Optional[Set[int]] = None
    #: True when every core this program may use is held by other
    #: simulations: this one should wait, not start on their cores.
    wait: bool = False
    lines: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return (self.cores is not None or self.threads is not None
                or self.cuda_visible is not None)


def explicit(argv: Sequence[str]) -> Dict[str, bool]:
    """Which parts of the resources this command line already decides."""
    words = set(argv)
    return {
        "threads": any(flag in words for flag in _THREAD_FLAGS),
        "pin": any(flag in words for flag in _PIN_FLAGS),
        "gpu": any(flag in words for flag in _GPU_FLAGS),
    }


def _who(snapshot: Snapshot, cores: Set[int]) -> str:
    """Plain words for what holds these cores."""
    names = []
    for sim in snapshot.simulations:
        if sim.cores & cores:
            names.append(f"another simulation (process {sim.pid}: {_short(sim.command)})")
    claimed = {snapshot.claimed[c] for c in cores if c in snapshot.claimed}
    names += sorted(claimed)
    return ", ".join(dict.fromkeys(names)) or "other programs"


def _short(command: str, width: int = 60) -> str:
    return command if len(command) <= width else command[: width - 3] + "..."


def _cores(cores: Iterable[int]) -> str:
    """'core 17' or 'cores 6-16,18-23': the log names one core or several."""
    cores = set(cores)
    return ("core " if len(cores) == 1 else "cores ") + cpu_list(cores)


def _threads(count: int) -> str:
    return f"{count} thread" + ("" if count == 1 else "s")


def decide(snapshot: Snapshot, argv: Sequence[str], *,
           gpu_policy: str = "processor", mpi: bool = False,
           can_restrict: bool = True, launcher: bool = False) -> Decision:
    """The resources for one simulation, given what the computer looks like.

    ``argv`` is the mdrun command line as planned: whatever it already says
    about threads, pinning or cards stays. ``gpu_policy`` is "processor" or
    "share" ("ask" counts as "processor": nobody is there to answer). ``mpi``
    is true for an MPI build of GROMACS, which has no -ntmpi (no thread-MPI).
    ``can_restrict`` is false when taskset is missing. ``launcher`` is true
    when GROMACS is started through mpirun or the like, which then decides
    the threads and cores itself.
    """
    decision = Decision(mpi=mpi)
    told = explicit(argv)
    lines = decision.lines

    # -- the cores --------------------------------------------------------
    if not snapshot.readable:
        lines.append("could not look at this computer's cores ("
                     + "; ".join(snapshot.problems or ["unknown reason"])
                     + "): GROMACS chooses the threads itself, as usual")
    elif launcher:
        lines.append("GROMACS is started through an MPI launcher (mpirun or the "
                     "like), which decides the threads and cores, so they are "
                     "left as they are")
    elif told["threads"] or told["pin"]:
        lines.append("threads or pinning are set on this block or in Settings, "
                     "so they are left as they are")
        held = set()
        for sim in snapshot.simulations:
            held |= sim.cores
        if held and not told["pin"]:
            lines.append(f"note: {_cores(held)} {'is' if len(held) == 1 else 'are'} "
                         f"held by {_who(snapshot, held)}")
    else:
        _decide_cores(snapshot, decision, can_restrict)
    if decision.wait:
        return decision     # the cards are looked at again when it starts

    # -- the graphics cards ------------------------------------------------
    if told["gpu"]:
        busy = [c for c in (snapshot.cards or []) if c.busy]
        lines.append("the graphics card is set on this block or in Settings, "
                     "so it is left as it is"
                     + (f" (card {busy[0].index} is in use by "
                        f"{_card_users(busy[0])})" if busy else ""))
    else:
        _decide_cards(snapshot, decision, gpu_policy)
    return decision


def _decide_cores(snapshot: Snapshot, decision: Decision, can_restrict: bool) -> None:
    lines = decision.lines
    allowed = set(snapshot.allowed or snapshot.cores)
    held: Set[int] = set()
    for sim in snapshot.simulations:
        held |= sim.cores
    held |= set(snapshot.claimed)
    # A pinned simulation's core shares its physical core with its sibling;
    # threads there would slow it as surely as threads on the core itself.
    near = set()
    for core in held:
        near |= snapshot.siblings.get(core, set())
    busy = {c for c, share in snapshot.load.items() if share >= BUSY_SHARE}
    taken = (held | near | busy) & allowed
    free = sorted(allowed - taken)
    restricted = allowed != snapshot.cores
    limit = snapshot.quota

    if not taken and not restricted and limit is None:
        lines.append("nothing else is running on the "
                     + ("one core" if len(allowed) == 1 else f"{len(allowed)} cores")
                     + ": GROMACS chooses the threads itself, as usual")
        # GROMACS will take all of them. Claimed, so that a simulation
        # starting a few seconds later does not see a free computer too.
        decision.claim = set(allowed)
        return

    if free:
        chosen = free
        if limit is not None and len(chosen) > max(1, int(limit)):
            # A container's share of the processor: fewer threads, on the
            # least busy cores.
            keep = max(1, int(limit))
            chosen = sorted(sorted(chosen, key=lambda c: (snapshot.load.get(c, 0.0), c))[:keep])
            worth = "1 core's" if limit == 1 else f"{limit:g} cores'"
            lines.append(f"this program may use {worth} worth of the processor, "
                         f"so it starts {_threads(keep)}")
        if len(chosen) > MAX_THREADS:
            chosen = chosen[:MAX_THREADS]
            lines.append(f"more free cores than GROMACS takes in one process: "
                         f"{MAX_THREADS} are used")
    else:
        pool = sorted(allowed - held - near)
        if not pool:
            # Every core we may use is held by another simulation. A thread
            # on one of them would slow that simulation for the whole of its
            # run -- its threads wait for each other at every step -- so
            # this one waits instead, and the executor looks again.
            decision.wait = True
            holding = {c for c in held
                       if c in allowed or snapshot.siblings.get(c, set()) & allowed}
            lines.append(f"every core this program may use is held by "
                         f"{_who(snapshot, holding)}: this simulation waits for "
                         "cores to come free, rather than slow that down")
            return
        # Every core is busy, but not with simulations: one thread on the
        # least busy of them. Slow, but it runs, and it disturbs no
        # simulation.
        chosen = sorted(pool, key=lambda c: (snapshot.load.get(c, 0.0), c))[:1]
        lines.append("every core this program may use is busy: this simulation "
                     "gets one thread, and will be slow")

    mine = held & allowed
    if mine:
        lines.append(f"{_cores(mine)} {'is' if len(mine) == 1 else 'are'} held by "
                     f"{_who(snapshot, mine)}")
    halves = near & allowed - held
    if halves:
        # Named with the held cores they share with: those are not always
        # in the line above, which names only the cores this program may use.
        partners = {c for c in held if snapshot.siblings.get(c, set()) & halves}
        lines.append(f"{_cores(halves)} "
                     + ("shares a physical core" if len(halves) == 1
                        else "share physical cores")
                     + f" with held {_cores(partners)}, so "
                     + ("it is" if len(halves) == 1 else "they are") + " left alone too")
    other_busy = (busy & allowed) - held - near
    if other_busy:
        lines.append(f"{_cores(other_busy)} {'is' if len(other_busy) == 1 else 'are'} "
                     "busy with other programs")
    if restricted:
        lines.append(f"this program may only use {_cores(allowed)}")

    decision.threads = len(chosen)
    decision.claim = set(chosen)
    if set(chosen) != allowed:
        if can_restrict:
            decision.cores = set(chosen)
        else:
            lines.append("taskset is not installed, so the simulation cannot be "
                         "kept to those cores; it only starts fewer threads")
    if decision.cores:
        where = _cores(chosen)
    else:
        where = "the core it may use" if len(chosen) == 1 else "the cores it may use"
    lines.append(f"this simulation gets {where}: {_threads(len(chosen))} "
                 f"({' '.join(flags_for(decision)[:4 if not decision.mpi else 2])})")


def _card_users(card: Card) -> str:
    if card.users:
        return ", ".join(f"another simulation (process {pid}: {_short(cmd)})"
                         for pid, cmd in card.users)
    return f"other work ({card.utilization:g} % busy)"


def visible_cards(cards: Optional[List[Card]], cuda_visible: Optional[str]
                  ) -> Optional[List[Card]]:
    """The cards this program may use, given CUDA_VISIBLE_DEVICES.

    None when the variable names a card nvidia-smi does not list (a MIG
    slice, say): then nobody here can tell which card that is.
    """
    if not cards:
        return []
    tokens = parse_cuda_visible(cuda_visible)
    if tokens is None:
        return list(cards)
    visible: List[Card] = []
    for token in tokens:
        match = [c for c in cards if c.uuid == token or str(c.index) == token]
        if not match:
            return None
        visible.extend(m for m in match if m not in visible)
    return visible


def gpu_question(cards: Optional[List[Card]], cuda_visible: Optional[str]
                 ) -> Optional[Dict[str, Any]]:
    """What to tell the person when every card we may use is busy, else None.

    Asked when Run is pressed: a card that is free, or no card at all, needs
    no question.
    """
    visible = visible_cards(cards, cuda_visible)
    if not visible:
        return None
    if any(not c.busy for c in visible):
        return None
    return {
        "cards": [{"index": c.index, "name": c.name,
                   "users": [{"pid": pid, "command": cmd} for pid, cmd in c.users],
                   "utilization": c.utilization} for c in visible],
        "message": "; ".join(f"graphics card {c.index} ({c.name}) is in use by "
                             f"{_card_users(c)}" for c in visible),
    }


def _decide_cards(snapshot: Snapshot, decision: Decision, policy: str) -> None:
    lines = decision.lines
    cards = snapshot.cards
    if not cards:
        return                        # no NVIDIA card, or nothing to ask
    visible = visible_cards(cards, snapshot.cuda_visible)
    if visible is None:
        lines.append(f"the graphics cards are set by CUDA_VISIBLE_DEVICES="
                     f"{snapshot.cuda_visible}, which is left as it is")
        return
    if not visible:
        return                        # this program sees no card at all
    busy = [c for c in visible if c.busy]
    if not busy:
        return
    free = [c for c in visible if not c.busy]
    for card in busy:
        lines.append(f"graphics card {card.index} ({card.name}) is in use by "
                     f"{_card_users(card)}")
    if free:
        decision.cuda_visible = ",".join(c.uuid for c in free)
        lines.append("this simulation uses "
                     + ", ".join(f"card {c.index}" for c in free)
                     + ", which " + ("is" if len(free) == 1 else "are") + " free")
    elif policy == "share":
        lines.append("this simulation shares " + ("it" if len(busy) == 1 else "them")
                     + ", as chosen")
    else:
        decision.cuda_visible = ""
        why = "as chosen" if policy == "processor" else (
            "since nobody was asked when this run started: Settings says to ask, "
            "and a run that could not ask keeps off the card")
        lines.append(f"this simulation runs on the processor only, {why}")


def wrap_for(decision: Decision) -> List[str]:
    """The words to put in front of the mdrun command."""
    words: List[str] = []
    if decision.cuda_visible is not None:
        words += ["env", f"CUDA_VISIBLE_DEVICES={decision.cuda_visible}"]
    if decision.cores:
        words += ["taskset", "-c", cpu_list(decision.cores)]
    return words


def flags_for(decision: Decision) -> List[str]:
    """The options to add to the mdrun command.

    One part with all the threads (``-ntmpi 1 -ntomp N``), never ``-nt N``.
    With ``-nt`` GROMACS splits the box into one piece per thread, and it
    refuses a number of pieces with a large prime factor: 17 free cores --
    a 24-core computer with six held and one busy -- stopped a heating run
    with "contains a large prime factor 17". One part never splits the box,
    so any number of free cores works, and a tiny box can never be too
    small to split. It costs some speed: on the ice tutorial's heating run,
    18 threads as one part ran at 207 ns/day against 238 with -nt 18. A
    computer with nothing else running is not touched at all, so GROMACS
    still splits a big system its own way there.
    """
    if decision.threads is None:
        return []
    words = ([] if decision.mpi else ["-ntmpi", "1"]) + ["-ntomp", str(decision.threads)]
    if decision.cores:
        # Kept to a set of cores from outside, GROMACS must not try to fix
        # its threads to cores of its own choosing.
        words += ["-pin", "off"]
    return words


def is_mdrun(argv: Sequence[str]) -> bool:
    return len(argv) >= 2 and argv[1] == "mdrun"


_LAUNCHERS = ("mpirun", "mpiexec", "srun", "aprun")


def has_launcher(command: str) -> bool:
    """True when GROMACS is started through mpirun or the like.

    The launcher then decides how many copies run and where: telling each of
    them to use every free core would start that many times too many threads.
    """
    try:
        words = command.split()
    except AttributeError:
        return False
    return any(os.path.basename(word) in _LAUNCHERS for word in words)


def is_mpi_command(command: str) -> bool:
    """True when the configured GROMACS is an MPI build (gmx_mpi), which has
    no -ntmpi, or is started through a launcher."""
    try:
        words = command.split()
    except AttributeError:
        return False
    return has_launcher(command) or any(
        "_mpi" in os.path.basename(word) for word in words)
