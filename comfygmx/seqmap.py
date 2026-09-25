"""What a structure file says its sequence is, versus what it actually holds.

Behind the sequence panel: which residues a structure file lists, and which of
them it has no coordinates for. Kept apart from :mod:`comfygmx.viz` and written
with nothing but Python's own standard library, so it needs nothing installed.

Readers for .pdb and .mmCIF; a .gro has nowhere to record a sequence that is not
there, so it is refused with an explanation rather than guessed at.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_int(text: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        return 0


# --------------------------------------------------------------------------

#: Residue names that make a chain a protein, a nucleic acid, water or salt.
#: Martini uses the standard amino-acid names, so one table serves both.
_PROTEIN_RES = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HID", "HIE", "HIP", "HSD", "HSE", "HSP", "CYX", "CYM", "ASH", "GLH",
    "LYN", "MSE", "SEC", "PYL", "ACE", "NME", "NMA", "TPO", "SEP", "PTR",
}
_NUCLEIC_RES = {
    "A", "C", "G", "U", "T", "I",
    "DA", "DC", "DG", "DT", "DI", "RA", "RC", "RG", "RU",
    "ADE", "CYT", "GUA", "THY", "URA",
}
_WATER_RES = {"HOH", "WAT", "SOL", "TIP", "TIP3", "TIP4", "SPC", "W", "WF", "PW"}
_ION_RES = {
    "NA", "CL", "K", "MG", "CA", "ZN", "FE", "MN", "CU", "CO", "NI", "BR",
    "IOD", "SOD", "CLA", "POT", "CES", "CAL", "MG2", "NA+", "CL-", "ION",
    "TNA", "TCL", "SO4", "PO4",
}


def _kind_of(resname: str) -> str:
    """What one residue is."""
    if resname in _PROTEIN_RES:
        return "protein"
    if resname in _NUCLEIC_RES:
        return "nucleic"
    if resname in _WATER_RES:
        return "water"
    if resname in _ION_RES:
        return "ion"
    return "other"


def _classify(counts: Dict[str, int]) -> str:
    """What a chain mostly is.

    By majority rather than by "contains one": a chain of four sugars attached
    to an ASN is not a protein chain, and calling it one is worse than useless
    when the answer is what you type into "keep chains".
    """
    if not counts:
        return "other"
    return max(counts.items(), key=lambda item: item[1])[0]


def _residue_stream(path: Path):
    """(chain, resid, resname) per *residue*, cheaply, for pdb/gro/ent.

    Deliberately not :func:`parse_structure`: composition needs no coordinates,
    and a 40 MB .gro should not be turned into 840,000 dictionaries to answer
    "which chains are in here".
    """
    suffix = path.suffix.lower()
    if suffix in (".cif", ".mmcif"):
        picks = None
        last = None
        for columns, values in _cif_rows(path, "_atom_site"):
            if picks is None:
                picks = (
                    _cif_pick(columns, "auth_asym_id", "label_asym_id"),
                    _cif_pick(columns, "auth_seq_id", "label_seq_id"),
                    _cif_pick(columns, "auth_comp_id", "label_comp_id"),
                    _cif_pick(columns, "pdbx_PDB_model_num"),
                )
            c_chain, c_num, c_name, c_model = picks
            if c_model >= 0 and values[c_model] not in ("1", ".", "?"):
                break
            key = (values[c_chain], values[c_num], values[c_name])
            if key == last:
                continue
            last = key
            yield (values[c_chain].strip() or "_", _safe_int(values[c_num]),
                   values[c_name].strip().upper())
        return

    if suffix in (".gro", ".g96"):
        with path.open(errors="replace") as handle:
            handle.readline()
            try:
                count = int(handle.readline().strip())
            except ValueError:
                return
            last = None
            for index, line in enumerate(handle):
                if index >= count or len(line) < 15:
                    break
                key = line[0:10]
                if key == last:
                    continue
                last = key
                yield "_", _safe_int(line[0:5]), line[5:10].strip().upper()
        return

    with path.open(errors="replace") as handle:
        last = None
        for line in handle:
            if line.startswith("ENDMDL"):
                break
            if not line.startswith(("ATOM", "HETATM")):
                continue
            key = line[17:27]
            if key == last:
                continue
            last = key
            chain = (line[21] if len(line) > 21 else " ").strip() or "_"
            yield chain, _safe_int(line[22:26]), line[17:20].strip().upper()


# --------------------------------------------------------------------------
# mmCIF
# --------------------------------------------------------------------------

def _cif_tokens(text: str) -> List[str]:
    """Split one mmCIF data line into values, honouring quoted ones.

    A quote only closes when whitespace follows it, which is what keeps atom
    names like ``O5'`` and residue names like ``5'-END`` in one piece.
    """
    out: List[str] = []
    index, end = 0, len(text)
    while index < end:
        char = text[index]
        if char in " \t":
            index += 1
            continue
        if char in "'\"":
            cursor = index + 1
            while cursor < end:
                if text[cursor] == char and (cursor + 1 >= end or text[cursor + 1] in " \t"):
                    break
                cursor += 1
            out.append(text[index + 1:cursor])
            index = cursor + 1
            continue
        cursor = index
        while cursor < end and text[cursor] not in " \t":
            cursor += 1
        out.append(text[index:cursor])
        index = cursor
    return out


def _cif_rows(path: Path, category: str):
    """``(columns, values)`` per row of one mmCIF ``loop_``.

    ``columns`` is the same dict on every row -- item name minus its category
    prefix, mapped to a position -- so pulling three fields out of ``_atom_site``
    costs no dictionary per atom.  Rows wrap across lines and values may be
    ``;`` blocks; real depositions use both.
    """
    prefix = (category if category.startswith("_") else "_" + category) + "."
    with path.open(errors="replace") as handle:
        columns: Dict[str, int] = {}
        state = "scan"
        values: List[str] = []
        block: Optional[List[str]] = None
        for line in handle:
            raw = line.rstrip("\n")

            if block is not None:
                if raw.startswith(";"):
                    values.append("\n".join(block))
                    block = None
                    while columns and len(values) >= len(columns):
                        yield columns, values[:len(columns)]
                        values = values[len(columns):]
                else:
                    block.append(raw)
                continue

            text = raw.strip()
            if state == "scan":
                if text == "loop_":
                    state, columns = "header", {}
                continue

            if state == "header":
                if text.startswith("_"):
                    name = text.split()[0]
                    if name.startswith(prefix):
                        columns[name[len(prefix):]] = len(columns)
                    else:
                        state = "scan"        # some other category's loop
                    continue
                if not columns:
                    state = "scan"
                    continue
                state, values = "rows", []
                # falls through: this line is already the first data row

            if state == "rows":
                if not text or text.startswith("#") or text == "loop_" \
                        or text.startswith(("data_", "_")):
                    return
                if raw.startswith(";"):
                    block = [raw[1:]]
                    continue
                values.extend(_cif_tokens(raw))
                while columns and len(values) >= len(columns):
                    yield columns, values[:len(columns)]
                    values = values[len(columns):]


def _cif_pick(columns: Dict[str, int], *names: str) -> int:
    """First of ``names`` that the loop actually carries, or -1."""
    for name in names:
        if name in columns:
            return columns[name]
    return -1


def _cif_value(path: Path, item: str) -> str:
    """One non-loop mmCIF item, e.g. ``_struct.title``."""
    with path.open(errors="replace") as handle:
        for line in handle:
            if not line.startswith(item):
                continue
            rest = line[len(item):]
            if not rest[:1].isspace():
                continue
            tokens = _cif_tokens(rest)
            if tokens:
                return "" if tokens[0] in ("?", ".") else tokens[0]
            # the value is on the following ``;`` block
            collected: List[str] = []
            started = False
            for follow in handle:
                if follow.startswith(";"):
                    if started:
                        break
                    started = True
                    collected.append(follow[1:].strip())
                    continue
                if started:
                    collected.append(follow.strip())
            return " ".join(collected).strip()
    return ""


# --------------------------------------------------------------------------
# what is missing
# --------------------------------------------------------------------------

#: Three-letter -> one-letter, including the names a crystallographer or a
#: force field substitutes.  Anything else becomes ``X``, the usual letter for
#: a residue with no standard one-letter code.
_ONE_LETTER = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V",
    "MSE": "M", "HSD": "H", "HSE": "H", "HSP": "H", "HID": "H", "HIE": "H",
    "HIP": "H", "CYX": "C", "CYM": "C", "ASH": "D", "GLH": "E", "LYN": "K",
    "SEC": "U", "PYL": "O", "TPO": "T", "SEP": "S", "PTR": "Y", "UNK": "X",
    "DA": "A", "DC": "C", "DG": "G", "DT": "T", "DI": "I",
    "A": "A", "C": "C", "G": "G", "U": "U", "T": "T", "I": "I",
}


def one_letter(resname: str) -> str:
    return _ONE_LETTER.get((resname or "").strip().upper(), "X")


def _split_resid(text: str) -> Tuple[Optional[int], str]:
    """``"  52A"`` -> ``(52, "A")`` -- the insertion code shares the field."""
    text = (text or "").strip()
    icode = ""
    if text and text[-1].isalpha():
        icode, text = text[-1], text[:-1]
    try:
        return int(text), icode
    except ValueError:
        return None, icode


def _runs_of_consecutive(entries):
    """Group ``(number, icode, resname)`` into stretches that number on."""
    out: List[List[Any]] = []
    for entry in entries:
        if out and not entry[1] and not out[-1][-1][1] and entry[0] == out[-1][-1][0] + 1:
            out[-1].append(entry)
        else:
            out.append([entry])
    return out


def _splice_missing(observed, missing):
    """Put unobserved residues back where their numbering says they belong.

    Sorting the two lists together would be shorter and wrong: 3EML numbers the
    T4 lysozyme it was fused to 1002-1161 and drops it into the middle of a
    receptor numbered -14 to 308, so ascending order is not chain order.
    Adjacency to a neighbouring residue is, and adjacency is local.

    Returns ``None`` when a stretch cannot be placed, so the caller can fall
    back to aligning against SEQRES.
    """
    if not observed:
        return [(n, i, r, False) for n, i, r in missing] or None
    by_number: Dict[Tuple[int, str], int] = {}
    for index, (number, icode, _name) in enumerate(observed):
        by_number.setdefault((number, icode), index)

    inserts: Dict[int, List[Any]] = {}
    for run in _runs_of_consecutive(missing):
        first, last = run[0][0], run[-1][0]
        at = by_number.get((first - 1, ""))
        if at is not None:
            place = at + 1
        elif by_number.get((last + 1, "")) is not None:
            place = by_number[(last + 1, "")]
        elif last < observed[0][0]:
            place = 0
        elif first > observed[-1][0]:
            place = len(observed)
        else:
            return None
        inserts.setdefault(place, []).extend(run)

    out = []
    for index in range(len(observed) + 1):
        for number, icode, name in inserts.get(index, ()):
            out.append((number, icode, name, False))
        if index < len(observed):
            number, icode, name = observed[index]
            out.append((number, icode, name, True))
    return out


def _find_run(seqres, names, start: int) -> Optional[int]:
    """Where a block of resolved residues sits in the deposited sequence."""
    span = len(names)
    for offset in range(start, len(seqres) - span + 1):
        if seqres[offset:offset + span] == names:
            return offset
    # One renamed residue -- MSE written as MET, a modified serine -- should
    # not make an otherwise exact 200-residue block unplaceable.
    allowed = max(0, span // 10)
    if not allowed:
        return None
    for offset in range(start, len(seqres) - span + 1):
        wrong = sum(1 for i in range(span) if seqres[offset + i] != names[i])
        if wrong <= allowed:
            return offset
    return None


def _align_to_seqres(seqres, observed):
    """Place the resolved residues into the deposited sequence.

    Used when a file has SEQRES but no REMARK 465 -- anything that has been
    through a pipeline rather than straight off the PDB.

    Runs of consecutively numbered residues move as blocks.  Nobody renumbers
    what is present, so a run has to sit in SEQRES as one exact stretch and the
    only question is where.  Walking SEQRES a residue at a time and taking
    whatever matches is what turns one 20-residue hole into three scattered
    ones: an unmatched position finds a later residue with the same name, and
    everything after it is off by one.
    """
    runs: List[List[Any]] = []
    for entry in observed:
        if runs and not entry[1] and not runs[-1][-1][1] \
                and entry[0] == runs[-1][-1][0] + 1:
            runs[-1].append(entry)
        else:
            runs.append([entry])

    placed, cursor = [], 0
    for run in runs:
        where = _find_run(seqres, [entry[2] for entry in run], cursor)
        if where is None:
            return None, len(observed)
        placed.append((where, run))
        cursor = where + len(run)

    out, position = [], 0
    for where, run in placed:
        while position < where:
            out.append((None, "", seqres[position], False))
            position += 1
        for number, icode, name in run:
            out.append((number, icode, name, True))
            position += 1
    while position < len(seqres):
        out.append((None, "", seqres[position], False))
        position += 1
    return out, 0


def _fill_numbers(residues):
    """Number the unobserved residues when the flanks leave no choice."""
    out = list(residues)
    index, total = 0, len(out)
    while index < total:
        if out[index][3] or out[index][0] is not None:
            index += 1
            continue
        start = index
        while index < total and not out[index][3] and out[index][0] is None:
            index += 1
        before = out[start - 1][0] if start else None
        after = out[index][0] if index < total else None
        length = index - start
        if before is not None and after is not None:
            base = before + 1 if after - before - 1 == length else None
        elif before is not None:
            base = before + 1
        elif after is not None:
            base = after - length
        else:
            base = None
        if base is None:
            continue
        for offset in range(length):
            number, icode, name, seen = out[start + offset]
            out[start + offset] = (base + offset, icode, name, seen)
    return out


def _pdb_sequence_sources(path: Path):
    """SEQRES, REMARK 465 and the resolved residues, in one pass.

    REMARK 465 is the deposition's own list of what was never located, with the
    author numbering on it -- far better than anything that can be inferred.
    """
    seqres: Dict[str, List[str]] = {}
    seqres_names: Dict[str, set] = {}
    missing: Dict[str, List[Any]] = {}
    observed: Dict[str, List[Any]] = {}
    order: List[str] = []
    armed = False
    seen_missing = set()
    last = None
    with path.open(errors="replace") as handle:
        for line in handle:
            if line.startswith("SEQRES"):
                chain = (line[11:12] or " ").strip() or "_"
                names = [name.upper() for name in line[19:].split()]
                seqres.setdefault(chain, []).extend(names)
                seqres_names.setdefault(chain, set()).update(names)
                if chain not in order:
                    order.append(chain)
            elif line.startswith("REMARK 465"):
                # Everything above the column header is prose about the entry.
                if "SSSEQI" in line:
                    armed = True
                elif armed and len(line) >= 27:
                    resname = line[15:18].strip().upper()
                    chain = (line[19:20] or " ").strip() or "_"
                    number, icode = _split_resid(line[20:27])
                    key = (chain, number, icode)
                    if resname and number is not None and key not in seen_missing:
                        seen_missing.add(key)
                        missing.setdefault(chain, []).append((number, icode, resname))
            elif line.startswith(("ATOM", "HETATM")):
                key = line[17:27]
                if key == last:
                    continue
                last = key
                chain = (line[21:22] or " ").strip() or "_"
                number, icode = _split_resid(line[22:27])
                if number is None:
                    continue
                resname = line[17:20].strip().upper()
                # Only what the chain is made of. 1AKI's 78 waters are HETATM on
                # chain A and would otherwise be counted as 78 residues that
                # "did not line up with SEQRES"; the His-tag at the end of 3EML
                # would stop looking like a C-terminal tail because a NAG and a
                # cholesterol sit after it in the file.
                if _kind_of(resname) not in ("protein", "nucleic") \
                        and resname not in seqres_names.get(chain, ()):
                    continue
                observed.setdefault(chain, []).append((number, icode, resname))
                if chain not in order:
                    order.append(chain)
            elif line.startswith("ENDMDL"):
                break
    return seqres, missing, observed, order


def _cif_sequence_chains(path: Path):
    """Chains from ``_pdbx_poly_seq_scheme``, which states outright which
    residues of the deposited sequence were never seen (``pdb_mon_id`` is
    ``?``).  When a file has it, nothing else needs guessing."""
    chains: Dict[str, List[Any]] = {}
    order: List[str] = []
    picks = None
    for columns, values in _cif_rows(path, "_pdbx_poly_seq_scheme"):
        if picks is None:
            picks = (
                _cif_pick(columns, "pdb_strand_id", "asym_id"),
                _cif_pick(columns, "mon_id"),
                _cif_pick(columns, "pdb_seq_num", "auth_seq_num", "seq_id"),
                _cif_pick(columns, "pdb_ins_code"),
                _cif_pick(columns, "pdb_mon_id", "auth_mon_id"),
            )
            if min(picks[:3]) < 0:
                return {}, []
        c_chain, c_name, c_num, c_ins, c_obs = picks
        chain = values[c_chain].strip() or "_"
        number, icode = _split_resid(values[c_num])
        if c_ins >= 0 and values[c_ins] not in ("?", ".", ""):
            icode = values[c_ins].strip()
        seen = c_obs < 0 or values[c_obs] not in ("?", ".")
        if chain not in chains:
            chains[chain] = []
            order.append(chain)
        chains[chain].append((number, icode, values[c_name].strip().upper(), seen))
    return chains, order


def _gaps_for(chain_id: str, residues) -> List[Dict[str, Any]]:
    """Every stretch of unobserved residues, labelled by which end it is on."""
    gaps: List[Dict[str, Any]] = []
    total = len(residues)
    index = 0
    while index < total:
        if residues[index][3]:
            index += 1
            continue
        start = index
        while index < total and not residues[index][3]:
            index += 1
        run = residues[start:index]
        first, last = run[0][0], run[-1][0]
        numbered = first is not None and last is not None
        gaps.append({
            "id": (f"{chain_id}:{first}..{last}" if numbered
                   else f"{chain_id}#{start + 1}..{index}"),
            "chain": chain_id,
            "kind": "n-term" if start == 0 else ("c-term" if index == total else "internal"),
            "numbered": numbered,
            "start": first,
            "end": last,
            "position": start + 1,
            "length": len(run),
            "sequence": "".join(one_letter(entry[2]) for entry in run),
            "before": residues[start - 1][0] if start else None,
            "after": residues[index][0] if index < total else None,
            "known": all(one_letter(entry[2]) != "X" for entry in run),
        })
    return gaps


def _sentence(text: str) -> str:
    """A depositor's SHOUTED molecule name, in the case RCSB shows it in.

    Lowercased word by word rather than wholesale, because the part worth
    reading is usually the part that must stay upright: HLA-A2, IgG1,
    SARS-CoV-2. A word carrying a digit, or a short all-capitals one, is a
    name rather than prose and is left alone.
    """
    words = []
    for word in text.split():
        keep = any(c.isdigit() for c in word) or (word.isupper() and len(word) <= 3)
        words.append(word if keep else word.lower())
    out = " ".join(words)
    return out[:1].upper() + out[1:] if out else ""


def _pdb_molecules(path: Path) -> Dict[str, str]:
    """chain id -> what the depositor called that molecule, from COMPND.

    COMPND is a specification list: ``MOL_ID`` opens an entry, ``MOLECULE``
    names it and ``CHAIN`` says which chains it covers, tokens separated by
    semicolons and wrapped across as many lines as it takes.  Read here rather
    than asked of a web service, because the file has already been fetched and
    a structure that never came from the PDB has the records too if whoever
    made it wrote them.
    """
    parts: List[str] = []
    with path.open(errors="replace") as handle:
        for line in handle:
            if line.startswith("COMPND"):
                parts.append(line[10:].rstrip())
            elif line.startswith(("ATOM", "HETATM", "MODEL")):
                break                      # the header is over; stop reading
    names: Dict[str, str] = {}
    molecule = ""
    for token in " ".join(part.strip() for part in parts).split(";"):
        key, _, value = token.partition(":")
        key = key.strip().upper()
        value = " ".join(value.split())
        if key == "MOL_ID":
            molecule = ""
        elif key == "MOLECULE":
            molecule = _sentence(value)
        elif key == "CHAIN" and molecule:
            for chain in value.split(","):
                chain = chain.strip()
                if chain and chain.upper() != "NULL":
                    names[chain] = molecule
    return names


def _cif_molecules(path: Path) -> Dict[str, str]:
    """The same from mmCIF: entity descriptions, and which strands carry them."""
    entities: Dict[str, str] = {}
    for columns, values in _cif_rows(path, "_entity"):
        key = _cif_pick(columns, "id")
        described = _cif_pick(columns, "pdbx_description")
        if key >= 0 and described >= 0:
            entities[values[key]] = values[described]

    names: Dict[str, str] = {}
    for columns, values in _cif_rows(path, "_entity_poly"):
        entity = _cif_pick(columns, "entity_id")
        strands = _cif_pick(columns, "pdbx_strand_id")
        if entity < 0 or strands < 0:
            continue
        description = entities.get(values[entity], "")
        for chain in values[strands].split(","):
            chain = chain.strip()
            if chain and description not in ("", "?", "."):
                names[chain] = _sentence(description)

    if not names:
        # One entity is written as plain items rather than a loop.
        description = _cif_value(path, "_entity.pdbx_description")
        strands = _cif_value(path, "_entity_poly.pdbx_strand_id")
        for chain in strands.split(","):
            chain = chain.strip()
            if chain and description:
                names[chain] = _sentence(description)
    return names


def _molecules(path: Path) -> Dict[str, str]:
    try:
        if path.suffix.lower() in (".cif", ".mmcif"):
            return _cif_molecules(path)
        return _pdb_molecules(path)
    except OSError:
        return {}


def parse_sequence(path: Path, max_positions: int = 60000) -> Dict[str, Any]:
    """The deposited sequence against what is actually in the coordinates.

    This is the thing you otherwise open the file in a text editor to work out:
    which residues a structure is missing, where they are, and whether they are
    a loop in the middle or a tail hanging off an end.  The distinction decides
    what is worth rebuilding -- an internal gap has two anchors and a defined
    answer, a disordered tail has one anchor and does not.
    """
    path = Path(path)
    if not path.is_file():
        return {"error": f"not a file: {path}"}

    suffix = path.suffix.lower()
    warnings: List[str] = []
    chains: Dict[str, List[Any]] = {}
    order: List[str] = []
    source = ""
    named = _molecules(path)

    if suffix in (".gro", ".g96", ".xyz"):
        return {
            "name": path.name, "path": str(path), "format": suffix.lstrip("."),
            "source": "", "chains": [], "total_missing": 0,
            "warnings": [f"a {suffix} file carries no deposited sequence, only the "
                         "coordinates that exist -- nothing can say what is absent. "
                         "Ask this of the .pdb or .cif it came from."],
        }

    if suffix in (".cif", ".mmcif"):
        chains, order = _cif_sequence_chains(path)
        if chains:
            source = "_pdbx_poly_seq_scheme"
        else:
            warnings.append("no _pdbx_poly_seq_scheme in this file; gaps are being "
                            "read from jumps in the residue numbering, so missing "
                            "tails cannot be seen")
            for chain, resid, resname in _residue_stream(path):
                chains.setdefault(chain, []).append((resid, "", resname, True))
                if chain not in order:
                    order.append(chain)
            source = "residue numbering"
    else:
        seqres, missing, observed, order = _pdb_sequence_sources(path)
        for chain in order:
            seen = observed.get(chain, [])
            gone = missing.get(chain, [])
            full = seqres.get(chain)
            spliced = _splice_missing(seen, gone) if gone else None
            # REMARK 465 is the deposition's own account of what was never
            # located -- but it describes the file as deposited.  Anything that
            # has since been through a pipeline can have holes the remark knows
            # nothing about, and it is SEQRES that catches those, so the two
            # have to agree before the remark is believed.
            if spliced is not None and (not full or len(spliced) == len(full)):
                chains[chain] = spliced
                continue
            if full:
                aligned, stranded = _align_to_seqres(full, seen)
                if aligned is not None:
                    chains[chain] = aligned
                    if spliced is not None:
                        warnings.append(
                            f"chain {chain}: REMARK 465 accounts for {len(spliced)} "
                            f"residues and SEQRES has {len(full)}, so this file has been "
                            "edited since it was deposited -- the gaps below come from "
                            "comparing the coordinates against SEQRES instead")
                    continue
                warnings.append(f"chain {chain}: {stranded} resolved residues could not "
                                "be placed in SEQRES, so only jumps in the numbering "
                                "are being reported -- missing tails will not show")
            elif spliced is not None:
                chains[chain] = spliced
                continue
            chains[chain] = [(n, i, r, True) for n, i, r in seen]
        if any(missing.values()):
            source = "REMARK 465"
            if seqres:
                source = "SEQRES and REMARK 465"
        elif seqres:
            source = "SEQRES"
        else:
            source = "residue numbering"
            warnings.append("no SEQRES and no REMARK 465 in this file: gaps are being "
                            "read from jumps in the residue numbering, so missing "
                            "tails cannot be seen")

    out_chains: List[Dict[str, Any]] = []
    total_missing = 0
    positions = 0
    for chain_id in order:
        residues = chains.get(chain_id) or []
        if not residues:
            continue
        kinds: Dict[str, int] = {}
        for entry in residues:
            kind = _kind_of(entry[2])
            kinds[kind] = kinds.get(kind, 0) + 1
        kind = _classify(kinds)
        # A membrane is not a sequence.  Nor are 758,669 waters.
        if kind not in ("protein", "nucleic"):
            continue
        residues = _fill_numbers(residues)
        if source == "residue numbering":
            residues = _expand_numbering_gaps(residues)
        positions += len(residues)
        if positions > max_positions:
            warnings.append(f"stopped after {max_positions:,} residues -- the rest of "
                            "the file is not shown")
            break
        gaps = _gaps_for(chain_id, residues)
        seen_numbers = [e[0] for e in residues if e[3] and e[0] is not None]
        missing_here = sum(1 for entry in residues if not entry[3])
        total_missing += missing_here
        out_chains.append({
            "id": chain_id,
            # What the depositor called it. Blank where the file never said --
            # a chain letter alone is not much to choose by when a receptor
            # complex arrives as sixteen of them.
            "molecule": named.get(chain_id, ""),
            "kind": kind,
            "length": len(residues),
            "observed": len(residues) - missing_here,
            "missing": missing_here,
            "letters": "".join(one_letter(entry[2]) for entry in residues),
            # '#' resolved, '.' absent -- one character per residue keeps a
            # 1,530-residue complex under 2 kB on the wire.
            "mask": "".join("#" if entry[3] else "." for entry in residues),
            "numbers": [entry[0] for entry in residues],
            "icodes": ("".join(entry[1] or " " for entry in residues)
                       if any(entry[1] for entry in residues) else ""),
            "first": seen_numbers[0] if seen_numbers else None,
            "last": seen_numbers[-1] if seen_numbers else None,
            "gaps": gaps,
        })

    return {
        "name": path.name,
        "path": str(path),
        "format": suffix.lstrip(".") or "pdb",
        "source": source,
        "chains": out_chains,
        "total_missing": total_missing,
        "warnings": warnings,
    }


def _expand_numbering_gaps(residues):
    """Turn jumps in the numbering into explicit unknown residues.

    Only for files with nothing else to go on.  The names are unknown, so they
    come out as X and nothing will agree to build them -- but the gap is at
    least visible, which is the difference between "there is a hole at 46-51"
    and silence.
    """
    out = []
    for entry in residues:
        if out and entry[0] is not None and out[-1][0] is not None:
            base = out[-1][0]
            step = entry[0] - base
            if 1 < step <= 400:
                for offset in range(1, step):
                    out.append((base + offset, "", "UNK", False))
        out.append(entry)
    return out
