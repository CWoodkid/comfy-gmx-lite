"""What is inside a trajectory, asked once and remembered.

Answering "how many frames is that" means reading the whole file: ``gmx check``
decompresses every frame to count them.  On a 46 GB trajectory on a share that
reads at 21 MB/s that is thirty-five minutes, and the trajectory preview node
was paying it again every time its parameters changed -- then throwing the
answer away.

So the answer is kept, keyed by the file's path, size and modification time. A
trajectory that has been rewritten looks different and is re-read; one that has
not is free forever after.

Nothing here ever scans on its own.  A scan is minutes of disk, so it happens
when somebody asks for it and not as a side effect of drawing a panel.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

#: Bumped when the shape of a stored record changes.
FACTS_VERSION = 1

_LOCK = threading.Lock()

#: ``Item        #frames Timestep (ps)`` then ``Step   60   10``.
_SUMMARY = re.compile(r"^Step\s+(\d+)\s+([\d.eE+-]+)?\s*$", re.M)
_ATOMS = re.compile(r"^# Atoms\s+(\d+)", re.M)
_PRECISION = re.compile(r"^Precision\s+([\d.eE+-]+)", re.M)


def _store_path(settings: Any) -> Path:
    return Path(settings.data_dir) / "cache" / "files.json"


def _load(settings: Any) -> Dict[str, Any]:
    try:
        data = json.loads(_store_path(settings).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(settings: Any, data: Dict[str, Any]) -> None:
    path = _store_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
    except OSError:
        pass  # a fact that cannot be written is not worth failing anything for


def _fingerprint(path: Path) -> Optional[Dict[str, float]]:
    try:
        info = path.stat()
    except OSError:
        return None
    return {"size": info.st_size, "mtime": info.st_mtime}


def known(settings: Any, path: str) -> Optional[Dict[str, Any]]:
    """What is already known about this file, or None if it has to be read."""
    target = Path(path)
    mark = _fingerprint(target)
    if mark is None:
        return None
    with _LOCK:
        entry = _load(settings).get(str(target.resolve()))
    if not entry or entry.get("version") != FACTS_VERSION:
        return None
    if entry.get("size") != mark["size"] or entry.get("mtime") != mark["mtime"]:
        return None  # rewritten since; what we knew was about a different file
    return entry


def parse_check(text: str) -> Dict[str, Any]:
    """Frames, timestep and atom count out of ``gmx check -f``."""
    facts: Dict[str, Any] = {}
    summary = _SUMMARY.search(text)
    if summary:
        facts["frames"] = int(summary.group(1))
        try:
            facts["dt"] = float(summary.group(2)) if summary.group(2) else 0.0
        except ValueError:
            facts["dt"] = 0.0
    atoms = _ATOMS.search(text)
    if atoms:
        facts["atoms"] = int(atoms.group(1))
    precision = _PRECISION.search(text)
    if precision:
        try:
            facts["precision"] = float(precision.group(1))
        except ValueError:
            pass
    if facts.get("frames") and facts.get("dt"):
        # The span, not frames x dt: sixty frames 10 ps apart cover 590 ps.
        facts["length"] = (facts["frames"] - 1) * facts["dt"]
    return facts


def scan(settings: Any, path: str, toolbox: Any, timeout: float = 3600.0) -> Dict[str, Any]:
    """Read the whole trajectory once and remember what is in it.

    Minutes, on a big file. Callers ask for this deliberately.
    """
    target = Path(path)
    mark = _fingerprint(target)
    if mark is None:
        return {"error": f"cannot read {path}"}
    resolved = toolbox.resolve("gmx")
    script = (f"{resolved.prelude}\n{resolved.command} check "
              f"-f {json.dumps(str(target))}")
    try:
        done = subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "gmx check did not finish in an hour"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    # gmx check writes its table to stderr; the streams are kept apart because
    # merging them lets its parting quotation land in the middle of the table.
    facts = parse_check((done.stdout or "") + "\n" + (done.stderr or ""))
    if not facts.get("frames"):
        first = ((done.stderr or done.stdout or "").strip().splitlines() or [""])[-1]
        return {"error": f"gmx check said nothing about frames ({first[:120]})"}
    entry = {"version": FACTS_VERSION, "path": str(target), **mark, **facts}
    with _LOCK:
        data = _load(settings)
        data[str(target.resolve())] = entry
        _save(settings, data)
    return entry


def forget(settings: Any, path: str = "") -> int:
    """Drop one file's facts, or all of them."""
    with _LOCK:
        data = _load(settings)
        if not path:
            count = len(data)
            _save(settings, {})
            return count
        key = str(Path(path).resolve())
        if key in data:
            del data[key]
            _save(settings, data)
            return 1
    return 0
