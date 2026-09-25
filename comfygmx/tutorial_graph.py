"""Shared helpers for laying out a packaged tutorial's graph.

Positions are given in grid units -- one column is a node's width plus a gutter,
one row is a node's height plus a gutter -- so a tutorial reads as a table of
(column, row) rather than as a list of pixel coordinates.
"""

from __future__ import annotations

import math

from typing import Any, Dict

COL, ROW = 300, 175


def node(node_id: str, node_type: str, col: float, row: float, **params: Any) -> Dict[str, Any]:
    return as_current({
        "id": node_id,
        "type": node_type,
        "pos": [round(col * COL), round(row * ROW)],
        "params": params,
    })


def as_current(node: Dict[str, Any]) -> Dict[str, Any]:
    """The node as the palette offers it today.

    A tutorial written when RMSD was a block of its own still says gmx.rms;
    the block a person will actually see is "Measure something, frame by
    frame" with RMSD picked. Converting here, at creation, means the layout
    measures the block that will be drawn, and the exported JSON says what
    the editor would have shown anyway.
    """
    from .nodes.merged import convert_node
    from .registry import REGISTRY
    convert_node(node, REGISTRY)
    return node


def link(a: str, ap: str, b: str, bp: str) -> Dict[str, str]:
    return {"from_node": a, "from_port": ap, "to_node": b, "to_port": bp}


def note(node_id: str, col: float, row: float, text: str) -> Dict[str, Any]:
    return node(node_id, "util.note", col, row, text=text)


def group(title: str, color: str, *node_ids: str) -> Dict[str, Any]:
    """A coloured box around named nodes.

    No bounds: how tall a node renders depends on its widgets, which only the
    browser knows, so the group names its members and the editor measures them
    once they are on the canvas.  Colours come from ``chunks.COLOR`` so a blue
    box means the same thing in a tutorial as it does in a chunk.
    """
    return {"title": title, "color": color, "nodes": list(node_ids)}


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

#: How tall each node type renders, in pixels, measured in the editor.
#:
#: A graph written as a table of (column, row) has no idea how tall its nodes
#: are -- that depends on how many widgets each one has -- so placing rows a
#: fixed distance apart puts a 546 px mdp node straight through the row below.
#: Every shipped layout used to do exactly that; it only became visible once
#: groups drew a box around each stage.
#:
#: Every one of these is the height with the checker's complaint showing, which
#: is the state a freshly dropped graph is in: nothing is filled in yet, so
#: every node carries a red line saying so, and that line is 28 px the node did
#: not have a moment earlier.  Laying out against the quiet height leaves the
#: rows exactly one error line too close together, which is what they were.
#:
#: Regenerate with tools/measure_node_heights.js when the node bodies change,
#: and keep whichever number is larger.  The same node measures a few pixels
#: shorter or taller on different machines -- font, zoom and screen density all
#: move it -- and a height that is too small is the one that hurts, because it
#: is what lets two nodes overlap.  Too large only leaves a gap.
NODE_H = {
    "analysis.ice_count": 235,
    "build.ice": 284,
    "gmx.clustsize": 290,
    "gmx.density": 350,
    "gmx.dssp": 471,
    "gmx.editconf": 413,
    "gmx.energy": 226,
    "gmx.forcefield": 277,
    "gmx.genion": 363,
    "gmx.grompp": 314,
    "gmx.gyrate": 208,
    "gmx.hbond": 247,
    "gmx.index": 243,
    "gmx.index_by_kind": 201,
    "gmx.insert_molecules": 179,
    "gmx.make_ndx": 286,
    "gmx.mdrun": 372,
    "gmx.measure": 293,
    "gmx.mindist": 268,
    "gmx.msd": 334,
    "gmx.pdb2gmx": 355,
    "gmx.polystat": 250,
    "gmx.principal": 250,
    "gmx.rms": 250,
    "gmx.rmsf": 268,
    "gmx.sasa": 223,
    "gmx.select": 237,
    "gmx.solvate": 196,
    "gmx.trjconv": 492,
    "io.fetch_url": 284,
    "io.file": 212,
    "io.structure": 219,
    "prep.clean": 313,
    "util.edit_text": 297,
    "util.mdp": 701,
    "util.note": 166,
    "view.plot": 386,
    "view.structure": 386,
    "view.trajectory": 616,
}

#: Anything not in the table -- a node added since it was measured.  Generous
#: on purpose: too much air costs a scroll, too little costs an overlap.
DEFAULT_NODE_H = 420
#: Air between one row and the next.
# Vertical space left between one row of blocks and the next.
#
# Bigger than it looks like it needs to be, on purpose. The heights in NODE_H
# were measured on blocks with nothing wired into them, and a block that IS
# wired up is taller: once the check knows what it is connected to, it prints
# its remarks on the face of the block. Three extra lines is common and that is
# about 84 px, so a gap of 70 was not enough and rows ran into each other.
#
# The cost of being generous here is only blank space; the cost of being mean
# is two blocks drawn on top of each other.
GAP_Y = 160
#: Two y values closer than this were meant to be the same row.
ROW_TOLERANCE = 60

#: A note is as tall as what it says, so it is worked out rather than looked up.
#: All five numbers are measured in the browser, not guessed: the card around
#: the text box is 63 px, the box itself is 11 px fixed-width type on a 15.95 px
#: line, its usable width takes 75 characters now that the card is 536 px wide,
#: and it stops growing at 900 px and scrolls after that.  Checked against all
#: seven notes of the biphasic tutorial; the smoke test holds those seven as a
#: fixture.
NOTE_CHROME = 63
NOTE_WRAP = 75
NOTE_LINE = 15.95
NOTE_PAD = 10
#: The box stops growing here and scrolls the rest, so however long a note gets
#: the card stops. Kept in step with GROW_MAX_PX in comfygmx/web/js/graph.js.
NOTE_CAP = 900
#: And never smaller than the six rows the box asks for when it is empty.
NOTE_MIN = 106


def wrapped_lines(text: str, width: int = NOTE_WRAP) -> int:
    """How many lines the browser will break this into, at `width` characters.

    Words are kept whole, which is what the browser does, so a line of 31
    characters whose last word is long becomes two lines rather than one and a
    stub.
    """
    total = 0
    for line in text.split("\n"):
        if not line.strip():
            total += 1
            continue
        used = 0
        rows = 1
        for word in line.split(" "):
            extra = len(word) + (1 if used else 0)
            if used and used + extra > width:
                rows += 1
                used = len(word)
            else:
                used += extra
        total += rows
    return total


def note_height(text: str) -> int:
    body = (text or "").strip("\n")
    if not body.strip():
        return NOTE_CHROME + NOTE_MIN
    grown = NOTE_PAD + math.ceil(NOTE_LINE * wrapped_lines(body))
    return NOTE_CHROME + max(NOTE_MIN, min(NOTE_CAP, grown))


#: Nodes are 236 px wide unless they carry a picture, and then they are wider.
#: Only the exceptions are listed.
NODE_W = {
    "gmx.dssp": 300,
    # A note is drawn as a wide card (.note-card in style.css): two columns of
    # blocks wide, so a long note is a paragraph rather than a tower.
    "util.note": 536,
    "view.plot": 300,
    "view.structure": 300,
    "view.trajectory": 300,
}
DEFAULT_NODE_W = 236
#: The least gutter that still reads as two nodes rather than one wide one.
#: Deliberately small: this is a floor, not a pitch. Demanding the full 64 px
#: gutter of a 300 px column would find every 280 px column 20 px short and
#: push each one further right than the last, and a graph twenty columns wide
#: would come out four hundred pixels wider for no visible reason.
GAP_X = 24


def height_of(node: Dict[str, Any]) -> int:
    """How tall this node will render, by type and -- for a note -- by content."""
    if node.get("type") == "util.note":
        return note_height((node.get("params") or {}).get("text", ""))
    return NODE_H.get(node.get("type", ""), DEFAULT_NODE_H)


def width_of(node: Dict[str, Any]) -> int:
    return NODE_W.get(node.get("type", ""), DEFAULT_NODE_W)


def _boxes(nodes: list) -> list:
    return [(n, n["pos"][0], n["pos"][1],
             n["pos"][0] + width_of(n), n["pos"][1] + height_of(n)) for n in nodes]


def _collision(nodes: list):
    """The first pair of nodes whose rectangles intersect, in reading order."""
    boxes = sorted(_boxes(nodes), key=lambda b: (b[2], b[1]))
    for index, a in enumerate(boxes):
        for b in boxes[index + 1:]:
            if a[3] > b[1] and b[3] > a[1] and a[4] > b[2] and b[4] > a[2]:
                return a, b
    return None


def _cost(mover: Dict[str, Any], rest: list, axis: int, way: int,
          gap_x: int, gap_y: int, rounds: int = 40):
    """How far ``mover`` must travel along one axis to stand clear of everything.

    Walked rather than solved: each step moves past the nearest blocker, which
    may reveal the next one.  Returns None if it never comes free.
    """
    gap = gap_x if axis == 0 else gap_y
    span = (width_of, height_of)[axis]
    other_span = (height_of, width_of)[axis]
    origin = mover["pos"][axis]
    across = 1 - axis
    moved = 0
    for _ in range(rounds):
        need = 0
        low = mover["pos"][across]
        high = low + other_span(mover)
        for node in rest:
            other_low = node["pos"][across]
            if high <= other_low or other_low + other_span(node) <= low:
                continue
            start, end = mover["pos"][axis], mover["pos"][axis] + span(mover)
            edge, far = node["pos"][axis], node["pos"][axis] + span(node)
            if end <= edge or far <= start:
                continue
            need = max(need, (far + gap - start) if way > 0 else (end + gap - edge))
        if need <= 0:
            mover["pos"][axis] = origin
            return moved
        mover["pos"][axis] += way * need
        moved += need
    mover["pos"][axis] = origin
    return None


def _move_notes_clear(nodes: list, anchor: int, gap_x: int, gap_y: int,
                      rounds: int) -> None:
    """Get the captions out of the way of the work.

    Only a note moves. A note can sit anywhere that keeps it near what it
    describes, while a work node's position is the shape of the workflow, and
    shoving one out of its row to make room for a paragraph gets the priority
    backwards. Two work nodes standing on each other is a layout somebody has
    to look at, so it is left alone and reported rather than guessed at.
    """
    for _ in range(rounds):
        hit = _collision(nodes)
        if hit is None:
            return
        first, second = hit[0][0], hit[1][0]
        notes = [n for n in (first, second) if n.get("type") == "util.note"]
        if not notes:
            return
        mover = max(notes, key=lambda n: abs(n["pos"][1] - anchor))
        rest = [n for n in nodes if n is not mover]
        down = mover["pos"][1] >= anchor
        by_y = _cost(mover, rest, 1, 1 if down else -1, gap_x, gap_y)
        by_x = _cost(mover, rest, 0, 1, gap_x, gap_y)
        # Whole cost, not the cost of this one collision. Clearing the node in
        # front of you by 110 px four times running is worse than the one step
        # that clears everything, and only comparing totals can see that.
        if by_y is not None and (by_x is None or by_y <= by_x):
            mover["pos"][1] += by_y if down else -by_y
        elif by_x is not None:
            mover["pos"][0] += by_x
        else:
            return


def deoverlap(nodes: list, gap_y: int = GAP_Y, gap_x: int = GAP_X,
              rounds: int = 60) -> list:
    """Pull apart whatever overlaps, and leave everything else alone.

    ``relayout`` is for a graph written as a table: it restacks every row.  This
    is for a graph somebody arranged by hand -- a shipped workflow -- where the
    arrangement is the point and only the collisions are wrong.

    The row most of the graph stands on holds still.  Things above it are
    pushed up, things below are pushed down, and a note hung beside the line of
    work moves rather than the work.  A collision is settled along whichever
    axis costs less, because a seven-pixel overlap should cost seven pixels and
    not shove the rest of the graph two hundred to the right.
    """
    if not nodes:
        return nodes
    counts: Dict[int, int] = {}
    for node in nodes:
        counts[node["pos"][1]] = counts.get(node["pos"][1], 0) + 1
    anchor = max(counts, key=lambda y: (counts[y], -abs(y)))

    # First the easy half: a column is a stack, and a stack is one dimension.
    columns: Dict[int, list] = {}
    for node in nodes:
        columns.setdefault(node["pos"][0], []).append(node)
    for column in columns.values():
        column.sort(key=lambda n: n["pos"][1])
        held = min(range(len(column)),
                   key=lambda i: abs(column[i]["pos"][1] - anchor))
        for i in range(held + 1, len(column)):
            floor = column[i - 1]["pos"][1] + height_of(column[i - 1]) + gap_y
            column[i]["pos"][1] = max(column[i]["pos"][1], floor)
        for i in range(held - 1, -1, -1):
            ceiling = column[i + 1]["pos"][1] - height_of(column[i]) - gap_y
            column[i]["pos"][1] = min(column[i]["pos"][1], ceiling)

    # Captions first, so a note lying across a column is settled by moving the
    # note, not by pushing the column and everything right of it sideways.
    _move_notes_clear(nodes, anchor, gap_x, gap_y, rounds)

    # A node with a picture in it is 300 px wide, not 236, so a column pitch
    # that fits the ordinary ones has it lapping over its neighbour. Whole
    # columns move, and everything to their right moves with them, because two
    # work nodes standing side by side are a row and a row should stay a row.
    #
    # Only a pair that overlaps on *both* axes counts. Columns 180 px apart are
    # fine when nothing in one stands beside anything in the other, and reading
    # the pitch itself as the fault would push every column right of the first
    # narrow gutter, over and over, for nothing anyone could see.
    order = sorted(columns)
    placed: list = []
    shift = 0
    for x in order:
        column = columns[x]
        for node in column:
            top, tall = node["pos"][1], height_of(node)
            for other in placed:
                other_top = other["pos"][1]
                if top >= other_top + height_of(other) or other_top >= top + tall:
                    continue
                shift = max(shift, other["pos"][0] + width_of(other) + gap_x - x)
        for node in column:
            node["pos"][0] += shift
        placed.extend(column)

    # And again: moving a column can put a note back in somebody's way.
    _move_notes_clear(nodes, anchor, gap_x, gap_y, rounds)
    return nodes


#: What the editor adds around a chunk's blocks when it draws the box: 16 px of
#: air on every side and a 26 px band for the title. Kept in step with
#: GROUP_PAD and GROUP_TITLE_H in comfygmx/web/js/graph.js.
GROUP_PAD = 16
GROUP_TITLE_H = 26


def _group_box(members: list):
    return (min(m["pos"][0] for m in members) - GROUP_PAD,
            min(m["pos"][1] for m in members) - GROUP_PAD - GROUP_TITLE_H,
            max(m["pos"][0] + width_of(m) for m in members) + GROUP_PAD,
            max(m["pos"][1] + height_of(m) for m in members) + GROUP_PAD)


def untangle_groups(nodes: list, groups: list, gap: int = GAP_Y) -> list:
    """Where two chunk boxes would be drawn across each other, push one down.

    The editor draws each box around wherever its blocks ended up, so nothing
    in the layout itself keeps two boxes apart: rows from two different stages
    can interleave without any block touching any other, and the boxes drawn
    round them then lie across each other.  It reads as a mistake, and it is
    one -- a stage should read as a block.

    The box that starts higher on the page is treated as settled; every block
    of the other one moves together, so the stage keeps its internal shape.
    It moves whichever way is shorter: two stages standing side by side that
    cross by a sliver -- a wide note poking into the next column -- are
    nudged apart sideways rather than one being dropped a whole page down.
    Moving a box can push it into a third one, so the sweep repeats until
    nothing crosses.  Blocks outside every box are then pulled clear by
    ``deoverlap``.
    """
    by_id = {n["id"]: n for n in nodes}
    memberships = [[by_id[i] for i in (g.get("nodes") or []) if i in by_id]
                   for g in (groups or [])]
    memberships = [m for m in memberships if m]
    pushed_any = False
    for _ in range(len(memberships) + 2):
        boxes = [_group_box(m) for m in memberships]
        moved = False
        order = sorted(range(len(boxes)), key=lambda i: boxes[i][1])
        for upper_at, i in enumerate(order):
            a = boxes[i]
            for j in order[upper_at + 1:]:
                b = boxes[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    # Three ways to clear it: drop the lower box below the
                    # upper one, or nudge whichever box stands further right
                    # a little further right. The smallest move wins -- two
                    # columns crossed by a wide note are nudged a hundred
                    # pixels apart, not dropped a page down.
                    down = a[3] + gap + GROUP_TITLE_H - b[1]
                    ways = [(down, memberships[j], 1)]
                    if b[0] > a[0]:
                        ways.append((a[2] + GAP_X - b[0], memberships[j], 0))
                    elif a[0] > b[0]:
                        ways.append((b[2] + GAP_X - a[0], memberships[i], 0))
                    # A way that would move something backwards is not a
                    # way out; it only arises when the boxes already nest.
                    ways = [w for w in ways if w[0] > 0] or [(down, memberships[j], 1)]
                    amount, members, axis = min(ways, key=lambda w: w[0])
                    for member in members:
                        member["pos"][axis] += amount
                    boxes[i] = _group_box(memberships[i])
                    boxes[j] = _group_box(memberships[j])
                    moved = pushed_any = True
        if not moved:
            break
    # Moving a whole stage down can sit it on top of a block that belongs to
    # no stage at all -- a note, usually -- so those are pulled clear too.
    return deoverlap(nodes) if pushed_any else nodes


def make_room_for(nodes: list, column: float, ids) -> list:
    """Slide everything right of `column` one column over, and put `ids` there.

    A node is wider than the gap between two columns, so a block dropped
    halfway between two of them overlaps both.  When a graph turns out to need
    a column it was not written with -- a row of "Take one file out" blocks,
    say -- this makes a real one rather than squeezing them in.
    """
    wanted = set(ids)
    edge = round(column * COL)
    for node in nodes:
        if node["id"] in wanted:
            node["pos"][0] = edge
        elif node["pos"][0] >= edge:
            node["pos"][0] += COL
    return nodes


def relayout(nodes: list, gap: int = GAP_Y) -> list:
    """Push rows apart until no node overlaps the one below it.

    Columns are left alone and the order of the rows is kept, so a layout stays
    the table its author wrote.  Only the distance between rows changes.

    A row is only pushed down far enough to clear the blocks standing directly
    above it -- blocks that share its columns.  It used to be pushed down past
    the tallest block anywhere in the row above, which meant one long note card
    sitting off to the left shoved every later row -- and every chunk box drawn
    around them -- hundreds of pixels down the page for nothing that was in
    anybody's way.  The graphs came out scattered down a diagonal instead of
    reading as a tidy table.
    """
    if not nodes:
        return nodes
    ys = sorted({n["pos"][1] for n in nodes})
    rows: list = []
    for y in ys:
        if rows and y - rows[-1][-1] <= ROW_TOLERANCE:
            rows[-1].append(y)
        else:
            rows.append([y])

    def clearance(member, off, placed, floor):
        # A node deliberately nudged below its row stays nudged, and the
        # clearance has to hold for where it actually ends up.
        left = member["pos"][0]
        right = left + width_of(member)
        for above in placed:
            a_left = above["pos"][0]
            if a_left + width_of(above) > left and right > a_left:
                floor = max(floor, above["_y"] + height_of(above) + gap - off)
        return floor

    placed: list = []
    prev_base = None
    for row in rows:
        members = [n for n in nodes if n["pos"][1] in row]
        base = min(row)
        # Only the working blocks decide where the row sits.  A note is often
        # long, and a row dragged down to clear a tall note two columns away
        # left a band of blank canvas through the middle of its own chunk box.
        work = [n for n in members if n.get("type") != "util.note"]
        # Never higher than one gap below the row before it, so two rows stay
        # two rows even when nothing forces them apart.
        floor = ys[0] if prev_base is None else prev_base + gap
        for member in work:
            floor = clearance(member, member["pos"][1] - base, placed, floor)
        for member in work:
            member["_y"] = floor + (member["pos"][1] - base)
        placed.extend(work)
        # Each note starts level with its row and sinks on its own, only as
        # far as whatever actually stands in its way.
        for member in members:
            if member in work:
                continue
            off = member["pos"][1] - base
            member["_y"] = clearance(member, off, placed, floor) + off
            placed.append(member)
        prev_base = floor
    for node in nodes:
        node["pos"][1] = node.pop("_y")
    # Rows are only half the story. Two nodes can share a row and a column --
    # a caption written just above the node it describes, close enough that the
    # tolerance reads them as one row -- and restacking rows never pulls those
    # apart. deoverlap does, and does nothing at all where nothing overlaps.
    return deoverlap(nodes, gap_y=gap)


# --------------------------------------------------------------------------
# A columns layout: read left to right, one lane per line of work
# --------------------------------------------------------------------------

LANE_GAP = 120     # room between two lanes, enough for a chunk box's title bar
COLUMN_GAP = 90    # room between two columns, enough for two chunk boxes side by side


def _lane_name(title: str) -> str:
    """Groups whose titles share the part before ' · ' are one line of work.

    'Rep 1 · build' and 'Rep 1 · minimise' both belong to the lane 'Rep 1'; a
    title with no ' · ' is a lane of its own.
    """
    return title.split(" · ")[0].strip() if " · " in title else title.strip()


def columns_layout(nodes: list, links: list, groups: list,
                   gap_x: int = COLUMN_GAP, gap_y: int = GAP_Y // 4,
                   lane_gap: int = LANE_GAP) -> list:
    """Lay a graph out in columns so every link is short and runs rightwards.

    A block's column is how many steps it stands from the left edge: a block
    that only reads files stands in the first column, and everything else one
    column right of the furthest thing it depends on. A block nothing feeds
    into -- a file box, a settings box -- is pulled right instead, to stand
    just left of the first block that uses it, so a shared parameter file does
    not sit at the far left with a link running the whole width of the canvas.
    When that column is taken by another chunk box of the same lane, the
    blocks from the consumer onwards move one column right to make room, so
    no two chunk boxes are drawn across each other.

    Lanes run top to bottom, one per line of work: the chunk boxes whose
    titles share the part before ' · ' form one lane, in the order the boxes
    are listed. Inside a lane, blocks in the same column are stacked, ordered
    by where the blocks feeding them stand so the links do not cross. Notes
    make a row across the top, in the order they are listed in the file.

    Positions are changed in place and the list is returned.
    """
    if not nodes:
        return nodes
    by_id = {n["id"]: n for n in nodes}
    into: Dict[str, list] = {n["id"]: [] for n in nodes}
    out_of: Dict[str, list] = {n["id"]: [] for n in nodes}
    for lk in links or []:
        a, b = lk.get("from_node"), lk.get("to_node")
        if a in by_id and b in by_id and a != b:
            into[b].append(a)
            out_of[a].append(b)
    notes = [n for n in nodes if n.get("type") == "util.note"]
    blocks = [n for n in nodes if n not in notes]

    # Column: longest path from a source.
    col: Dict[str, int] = {}

    def depth(node_id: str, seen=()) -> int:
        if node_id in col:
            return col[node_id]
        if node_id in seen:          # a loop in the wiring; do not spin
            return 0
        best = 0
        for parent in into[node_id]:
            best = max(best, depth(parent, seen + (node_id,)) + 1)
        col[node_id] = best
        return best

    for node in blocks:
        depth(node["id"])

    # Lanes: from the groups, in order; ungrouped blocks join the lane of
    # what they feed (or are fed by), else a lane of their own at the end.
    lane_of: Dict[str, int] = {}
    group_of: Dict[str, int] = {}
    lane_names: list = []
    for gi, group in enumerate(groups or []):
        name = _lane_name(group.get("title", ""))
        if name not in lane_names:
            lane_names.append(name)
        for nid in group.get("nodes") or []:
            if nid in by_id and nid not in lane_of:
                lane_of[nid] = lane_names.index(name)
                group_of[nid] = gi
    loose = [n for n in blocks if n["id"] not in lane_of]
    for _ in range(len(loose) + 1):
        moved = False
        for node in loose:
            nid = node["id"]
            if nid in lane_of:
                continue
            neighbours = [lane_of[x] for x in out_of[nid] + into[nid] if x in lane_of]
            if neighbours:
                lane_of[nid] = min(neighbours)
                moved = True
        if not moved:
            break
    for node in loose:
        if node["id"] not in lane_of:
            if "other blocks" not in lane_names:
                lane_names.append("other blocks")
            lane_of[node["id"]] = lane_names.index("other blocks")

    # Sources are pulled right to stand just left of their first consumer.
    # If that column of the lane belongs to another chunk box, everything
    # from the consumer's column onwards in the lane moves right one column.
    sources = [n["id"] for n in blocks if not into[n["id"]] and out_of[n["id"]]]

    def cell_taken_by_other_box(nid: str, c: int) -> bool:
        for other in blocks:
            oid = other["id"]
            if oid != nid and lane_of[oid] == lane_of[nid] and col[oid] == c \
                    and group_of.get(oid, -1) != group_of.get(nid, -1):
                return True
        return False

    for _ in range(len(sources) + 1):
        for nid in sources:
            target = max(0, min(col[c] for c in out_of[nid]) - 1)
            if cell_taken_by_other_box(nid, target):
                for other in blocks:
                    oid = other["id"]
                    if lane_of[oid] == lane_of[nid] and col[oid] > target and oid != nid:
                        col[oid] += 1
                for other in blocks:
                    oid = other["id"]
                    if lane_of[oid] != lane_of[nid]:
                        col[oid] = max(col[oid], max([col[p] + 1 for p in into[oid]] or [0]))
                target = max(0, min(col[c] for c in out_of[nid]) - 1)
            col[nid] = target

    # Column widths, shared across lanes so the columns line up.
    ncols = max(col.values()) + 1 if col else 1
    col_w = [DEFAULT_NODE_W] * ncols
    for node in blocks:
        c = col[node["id"]]
        col_w[c] = max(col_w[c], width_of(node))
    col_x = [0] * ncols
    x = 0
    for c in range(ncols):
        col_x[c] = x
        x += col_w[c] + gap_x

    # Stack order inside a lane and column: by the average row of the
    # blocks feeding a block, so links come in straight.
    order: Dict[str, float] = {}
    lanes: Dict[int, Dict[int, list]] = {}
    for node in blocks:
        lanes.setdefault(lane_of[node["id"]], {}).setdefault(col[node["id"]], []).append(node)
    for lane in lanes.values():
        for c in sorted(lane):
            stack = lane[c]
            for i, node in enumerate(sorted(stack, key=lambda n: n["pos"][1])):
                order[node["id"]] = float(i)
            for _ in range(3):
                for node in stack:
                    parents = [order[p] for p in into[node["id"]] if p in order]
                    if parents:
                        order[node["id"]] = sum(parents) / len(parents)
                stack.sort(key=lambda n: (order[n["id"]], n["pos"][1]))
                for i, node in enumerate(stack):
                    order[node["id"]] = float(i)

    # Notes make a row across the top, in file order.
    y = 0
    if notes:
        x = 0
        for note in notes:
            note["pos"] = [x, 0]
            x += width_of(note) + gap_x
        y = max(height_of(n) for n in notes) + lane_gap

    # Then lane by lane. A file that feeds three or more blocks far to its
    # right -- a topology every grompp step reads, an index -- goes on a row
    # of its own under the line of work, so its links run through the clear
    # strip below the blocks instead of straight through them.
    shared = {n["id"] for n in blocks
              if len(out_of[n["id"]]) >= 3
              and max(col[c] for c in out_of[n["id"]]) - col[n["id"]] >= 4}
    for lane_idx in sorted(lanes):
        lane = lanes[lane_idx]
        top = y
        tallest = 0
        for c, stack in lane.items():
            yy = top
            for node in stack:
                if node["id"] in shared:
                    continue
                node["pos"] = [col_x[c], yy]
                yy += height_of(node) + gap_y
            tallest = max(tallest, yy - gap_y - top)
        under = top + tallest + gap_y * 2
        lowest = under
        for c, stack in lane.items():
            yy = under
            for node in stack:
                if node["id"] not in shared:
                    continue
                node["pos"] = [col_x[c], yy]
                yy += height_of(node) + gap_y
            lowest = max(lowest, yy - gap_y)
        y = max(top + tallest, lowest) + lane_gap
    return nodes
