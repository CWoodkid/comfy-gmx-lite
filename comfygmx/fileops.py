"""Copy, move, rename and delete, for the file panel.

A file panel that can only look is half a file panel: every tidy-up means
leaving for a terminal, and the one thing people do most between runs is move
results somewhere sensible. So this does the four things a file manager does.

Two rules run through all of it.

Nothing is overwritten. Where a name is already taken the whole operation stops
and says which name it was, before anything has been written. Silently
replacing somebody's file is a worse failure than refusing to start.

Nothing is destroyed on the first press. Delete moves things into a trash
folder inside the data directory, where they keep their own names and can be
carried back out. Getting rid of them for good is a second, separate act that
has to say so.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _resolved(raw: str) -> Path:
    return Path(raw).expanduser().resolve()


def too_important(path: Path, settings) -> str:
    """Why this must not be moved or deleted, or an empty string if it may be.

    Not a security boundary: the panel walks the whole filesystem on purpose,
    and anything the server can reach it could already overwrite. This is the
    guard rail on the stairs. It catches the handful of paths where a slip
    costs a day, and it costs nothing to have.
    """
    try:
        target = _resolved(str(path))
    except OSError as exc:
        return f"cannot work out where {path} is: {exc}"
    if target == Path(target.anchor):
        return "that is the root of the filesystem"
    if len(target.parts) <= 2:
        return (f"{target} is a top-level folder of this machine, which this "
                "will not touch")
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and target == home:
        return "that is your home directory itself"
    try:
        data = settings.data_dir.resolve()
    except OSError:
        data = None
    if data is not None:
        if target == data:
            return (f"{target} is the folder Comfy-gmx keeps everything in: its "
                    "settings, its saved graphs and its record of what has run")
        if target in data.parents:
            return (f"{target} has the Comfy-gmx data folder inside it, so "
                    "moving or deleting it would take that with it")
    return ""


def _same_disk(a: Path, b: Path) -> bool:
    """Is a rename between these two instant, or does it mean copying?"""
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def weigh(path: Path, deadline: float = 2.0) -> Tuple[int, int, bool]:
    """How many files and how many bytes, giving up politely if it is huge.

    Used to tell somebody what they are about to delete. A run directory can
    hold a 46 GB trajectory on a share that reads at 21 MB/s, so this stops
    counting rather than making the dialog take a minute; the third value says
    whether the count is the whole story.
    """
    if path.is_file() or path.is_symlink():
        try:
            return 1, path.stat().st_size, True
        except OSError:
            return 1, 0, True
    stop = time.monotonic() + deadline
    files = total = 0
    for root, _dirs, names in os.walk(path, onerror=lambda exc: None):
        for name in names:
            files += 1
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
        if time.monotonic() > stop:
            return files, total, False
    return files, total, True


def _free_name(directory: Path, name: str) -> str:
    """A name in this folder nobody is using: 'notes.txt' -> 'notes (2).txt'."""
    if not (directory / name).exists():
        return name
    stem, dot, suffix = name.partition(".")
    for number in range(2, 1000):
        candidate = f"{stem} ({number}){dot}{suffix}"
        if not (directory / candidate).exists():
            return candidate
    raise ValueError(f"there are already a thousand things called {name} here")


def _check_sources(raw_paths: List[str]) -> Tuple[List[Path], str]:
    if not raw_paths:
        return [], "nothing was chosen"
    out: List[Path] = []
    for raw in raw_paths:
        path = _resolved(str(raw))
        if not path.exists() and not path.is_symlink():
            return [], f"{path} is not there any more"
        out.append(path)
    return out, ""


def transfer(raw_paths: List[str], destination: str, settings,
             move: bool = False) -> Dict[str, Any]:
    """Copy or move things into a folder.

    Refuses before it starts rather than halfway through: a name already taken,
    a folder being put inside itself, a source that has since gone. Half a copy
    is harder to sort out than none.
    """
    sources, problem = _check_sources(raw_paths)
    if problem:
        return {"error": problem}
    try:
        target = _resolved(destination)
    except OSError as exc:
        return {"error": str(exc)}
    if not target.is_dir():
        return {"error": f"{target} is not a folder to put things in"}

    clashes = []
    for source in sources:
        if move:
            stop = too_important(source, settings)
            if stop:
                return {"error": f"{source.name or source} will not be moved: {stop}"}
        if source.parent == target and not move:
            continue          # copying beside itself gets a new name below
        if source == target:
            return {"error": f"{source.name} cannot be put inside itself"}
        if source.is_dir() and target == source or source in target.parents:
            return {"error": (f"{target} is inside {source.name}, so this "
                              "would put a folder inside itself")}
        if (target / source.name).exists():
            clashes.append(source.name)
    if clashes:
        shown = ", ".join(clashes[:5]) + (" ..." if len(clashes) > 5 else "")
        return {"error": (f"{target} already has {shown}. Nothing has been "
                          "changed: rename it, or choose another folder.")}

    done = []
    for source in sources:
        name = _free_name(target, source.name)
        landing = target / name
        try:
            if move:
                shutil.move(str(source), str(landing))
            elif source.is_dir():
                shutil.copytree(source, landing, symlinks=True)
            else:
                shutil.copy2(source, landing, follow_symlinks=False)
        except (OSError, shutil.Error) as exc:
            return {"error": (f"{'moving' if move else 'copying'} {source.name} "
                              f"failed: {getattr(exc, 'strerror', None) or exc}"),
                    "done": [str(p) for p in done]}
        done.append(landing)
    return {"moved" if move else "copied": [str(p) for p in done],
            "destination": str(target), "count": len(done)}


def trash_dir(settings) -> Path:
    return settings.data_dir / "trash"


def delete(raw_paths: List[str], settings,
           forever: bool = False) -> Dict[str, Any]:
    """Put things in the trash, or, asked plainly enough, get rid of them.

    The trash is a folder inside the data directory, so what went in keeps its
    name and can be dragged back out. Where that is on a different disk a
    rename is not possible and the trash would mean copying every byte first,
    which for a run directory is not a thing to do quietly: it says so and asks
    to be told to delete for good instead.
    """
    sources, problem = _check_sources(raw_paths)
    if problem:
        return {"error": problem}
    for source in sources:
        stop = too_important(source, settings)
        if stop:
            return {"error": f"{source.name or source} will not be deleted: {stop}"}

    if forever:
        gone = []
        for source in sources:
            try:
                if source.is_dir() and not source.is_symlink():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            except OSError as exc:
                return {"error": f"could not delete {source.name}: "
                                 f"{exc.strerror or exc}",
                        "deleted": gone}
            gone.append(str(source))
        return {"deleted": gone, "count": len(gone), "forever": True}

    room = trash_dir(settings)
    try:
        room.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"error": f"cannot make the trash folder {room}: "
                         f"{exc.strerror or exc}"}
    heavy = []
    for source in sources:
        if not _same_disk(source.parent, room):
            files, size, complete = weigh(source)
            heavy.append({"path": str(source), "name": source.name,
                          "files": files, "bytes": size, "counted_all": complete})
    if heavy:
        return {"error": "", "other_disk": heavy, "trash": str(room)}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    binned = []
    for source in sources:
        name = _free_name(room, f"{stamp}-{source.name}")
        try:
            os.rename(source, room / name)
        except OSError as exc:
            return {"error": f"could not move {source.name} to the trash: "
                             f"{exc.strerror or exc}",
                    "trashed": binned}
        binned.append({"was": str(source), "now": str(room / name)})
    return {"trashed": binned, "count": len(binned), "trash": str(room)}


def rename(raw_path: str, new_name: str, settings) -> Dict[str, Any]:
    """Give one thing a different name, in the folder it is already in."""
    sources, problem = _check_sources([raw_path])
    if problem:
        return {"error": problem}
    source = sources[0]
    stop = too_important(source, settings)
    if stop:
        return {"error": f"{source.name or source} will not be renamed: {stop}"}
    name = (new_name or "").strip()
    if not name or name in (".", ".."):
        return {"error": "give it a name"}
    if "/" in name or "\\" in name:
        return {"error": "a name cannot contain a slash: that would be a move, "
                         "not a rename"}
    landing = source.parent / name
    if landing == source:
        return {"renamed": str(source), "name": name}
    if landing.exists():
        return {"error": f"{source.parent} already has something called {name}"}
    try:
        source.rename(landing)
    except OSError as exc:
        return {"error": f"could not rename {source.name}: {exc.strerror or exc}"}
    return {"renamed": str(landing), "was": str(source), "name": name}
