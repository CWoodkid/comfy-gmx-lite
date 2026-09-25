"""Force fields you can fetch, and how they get into the folder GROMACS reads.

GROMACS ships about seventeen force fields. The ones a lot of people actually
want are not among them: CHARMM36 in particular has to be downloaded from the
group that maintains it and unpacked into a folder GROMACS is told to look in.
That is two chores before the topology block will even list it, and neither is
interesting.

So the list below is a small catalogue of force fields that can be fetched,
each with the address it comes from, and `install_script` writes the few lines
that download one and put it where it belongs. The Environments window shows
the catalogue and runs that script; the topology block then offers the name in
its list like any built-in one.

The addresses were read off the maintainers' own download pages rather than
guessed. If a newer build appears before this list catches up, the window also
takes an address you paste in.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ForceFieldSpec:
    """One force field somebody can fetch."""

    #: The folder name without its .ff ending. This is also what pdb2gmx is
    #: given as -ff, so it is the name that has to appear in the topology
    #: block's list.
    id: str
    #: The family, for grouping rows in the window.
    family: str
    #: Who maintains it and where the file comes from, said plainly.
    source: str
    #: What it is for, in a sentence.
    description: str
    #: The address of the archive.
    url: str
    #: Anything worth knowing before choosing this one over its neighbours.
    note: str = ""


_MACKERELL = ("MacKerell lab, University of Maryland "
              "(mackerell.umaryland.edu)")
_CHARMM_WHAT = (
    "CHARMM36 for proteins, nucleic acids, lipids and carbohydrates. This is "
    "the force field most membrane and protein work uses, and GROMACS does not "
    "ship it."
)


def _charmm(name: str, note: str = "") -> ForceFieldSpec:
    return ForceFieldSpec(
        id=name,
        family="CHARMM36",
        source=_MACKERELL,
        description=_CHARMM_WHAT,
        url=("http://mackerell.umaryland.edu/download.php"
             f"?filename=CHARMM_ff_params_files/{name}.ff.tgz"),
        note=note,
    )


#: What can be fetched, newest first within each family. Read off the
#: maintainers' download pages, not invented; every address here was fetched
#: once to check it answers.
CATALOG: List[ForceFieldSpec] = [
    _charmm("charmm36-feb2026_cgenff-5.0",
            "The newest build. CGenFF 5.0 covers more small molecules, so pick "
            "this one if you are parameterising a ligand with CGenFF 5."),
    _charmm("charmm36-feb2026_cgenff-4.6",
            "The newest build, paired with CGenFF 4.6 instead. Use it if your "
            "ligand parameters came from CGenFF 4."),
    _charmm("charmm36-feb2026_ljpme_cgenff-5.0",
            "As above, but set up for LJ-PME: long-range dispersion is treated "
            "the same way as electrostatics. Only use it if your run settings "
            "ask for LJ-PME as well."),
    _charmm("charmm36-feb2026_ljpme_cgenff-4.6",
            "The LJ-PME build with CGenFF 4.6."),
    _charmm("charmm36-jul2022",
            "A widely used older build, and the one most published protocols "
            "and tutorials were written against."),
    _charmm("charmm36_ljpme-jul2022", "The LJ-PME version of that build."),
    _charmm("charmm36-jul2021"),
    _charmm("charmm36_ljpme-jul2021", "The LJ-PME version of that build."),
    _charmm("charmm36-feb2021"),
    _charmm("charmm36-jul2020"),
    _charmm("charmm36-mar2019"),
    _charmm("charmm36-jul2017",
            "Old. Here for repeating work that used it, not for new work."),
]

BY_ID: Dict[str, ForceFieldSpec] = {spec.id: spec for spec in CATALOG}


#: A force field name is a folder name, and it becomes part of a path we write
#: to. Nothing outside this shape is accepted from the browser.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,80}$")


def clean_name(raw: str) -> str:
    """The folder name to use, or a complaint saying why it will not do."""
    name = (raw or "").strip().rstrip("/")
    if name.endswith(".ff"):
        name = name[:-3]
    if not name:
        raise ValueError("give the force field a name: it becomes the folder "
                         "name, and it is what the topology block will list")
    if not _SAFE_NAME.match(name):
        raise ValueError(
            f"'{name}' will not do as a folder name. Letters, digits, dots, "
            "dashes, plus signs and underscores only, starting with a letter "
            "or digit."
        )
    return name


def check_url(raw: str) -> str:
    """The address to fetch from, or a complaint."""
    url = (raw or "").strip()
    if not url:
        raise ValueError("give the address of the archive to fetch")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("the address has to start with http:// or https://")
    return url


def install_script(url: str, name: str, into: Path) -> str:
    """The lines that fetch one force field and put it where GROMACS reads it.

    Everything happens in a temporary folder beside the destination, and the
    unpacked folder is only moved into place once it is known to be a force
    field. A download that fails, or an archive with nothing in it, therefore
    leaves what was already installed exactly as it was.
    """
    where = shlex.quote(str(into))
    address = shlex.quote(url)
    folder = shlex.quote(name + ".ff")
    return f"""set -eu

into={where}
mkdir -p "$into"
cd "$into"

# Somewhere to make a mess that is not the folder GROMACS reads.
work=$(mktemp -d "$into/.fetching-XXXXXX")
trap 'rm -rf "$work"' EXIT

echo "fetching {name} from {url}"
curl -fL --retry 3 --progress-bar -o "$work/archive" {address}
echo "downloaded $(du -h "$work/archive" | cut -f1)"

echo "unpacking"
if ! tar xzf "$work/archive" -C "$work" 2>/dev/null \\
   && ! tar xf "$work/archive" -C "$work" 2>/dev/null; then
  echo "that address did not give back an archive this can unpack. It is most"
  echo "often a web page rather than the file itself: open the address in a"
  echo "browser, find the actual download link, and use that. Nothing has been"
  echo "changed."
  head -c 200 "$work/archive" | tr -d '\\000' | sed 's/^/  got: /' | head -3
  exit 1
fi

# The folder inside the archive is not always named the way the file is.
inside=$(find "$work" -maxdepth 3 -type d -name '*.ff' | head -n 1)
if [ -z "$inside" ]; then
  echo "there is no folder ending in .ff inside that archive, so it is not a"
  echo "force field GROMACS can read. Nothing has been changed."
  exit 1
fi
if [ ! -f "$inside/forcefield.itp" ]; then
  echo "$(basename "$inside") has no forcefield.itp in it, so GROMACS would"
  echo "not offer it. Nothing has been changed."
  exit 1
fi

if [ -d "$into/{name}.ff" ]; then
  echo "replacing the {name}.ff that was already here"
  rm -rf "$into/{name}.ff"
fi
mv "$inside" "$into/{name}.ff"
echo "installed {name} into $into/{name}.ff"
echo "it came out of the archive as $(basename "$inside")" \\
  || true
echo
echo "the topology block now lists it as {name}"
"""


def installed(settings) -> List[Dict[str, str]]:
    """Every force field the topology block can offer, and where each is from."""
    found = settings.gromacs_forcefields()
    rows: List[Dict[str, str]] = []
    for name in found.get("user", []):
        spec = BY_ID.get(name)
        rows.append({
            "name": name,
            "where": "yours",
            "path": str(Path(found["dir"]) / f"{name}.ff"),
            "source": spec.source if spec else "",
            "family": spec.family if spec else "",
        })
    for name in found.get("builtin", []):
        if any(row["name"] == name for row in rows):
            continue
        rows.append({
            "name": name,
            "where": "GROMACS",
            "path": str(Path(found["gmx_top"]) / f"{name}.ff") if found.get("gmx_top") else "",
            "source": "installed with GROMACS",
            "family": "",
        })
    return rows


def catalog(settings) -> Dict[str, object]:
    """What is installed, and what can be fetched, for the Environments window."""
    found = settings.gromacs_forcefields()
    here = set(found.get("user", [])) | set(found.get("builtin", []))
    return {
        "dir": found["dir"],
        "dir_exists": found["dir_exists"],
        "gmx_top": found.get("gmx_top", ""),
        "installed": installed(settings),
        "available": [
            {
                "id": spec.id,
                "family": spec.family,
                "source": spec.source,
                "description": spec.description,
                "note": spec.note,
                "url": spec.url,
                "have": spec.id in here,
            }
            for spec in CATALOG
        ],
    }
