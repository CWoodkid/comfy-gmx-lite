"""A model snowflake: water vapour freezing on a grid of cells, not molecules.

The ice tutorial shows ice as molecules, a few nanometres across. A real
snowflake is a million times wider, holds about a billion billion molecules
and grows for many minutes: far beyond any simulation of molecules. Its arms
come from something a small model can show, and "Grow a snowflake" runs one:
C. Reiter's model of 2005, which keeps count of how much water each cell of
a flat grid holds. It needs numpy, which the ice blocks need too.

The block sits in a category of its own, "Models without molecules", so that
nobody mistakes it for a simulation like the others.
"""

from __future__ import annotations

from .base import Node, NodeError, Param, Plan, PlanContext, Port

CATEGORY = "Models without molecules"
COLOR = "#4f7fae"

#: The model, as a script that travels inside the block. It writes the picture
#: by hand (numpy and zlib), so it needs no drawing library: the online copy
#: of the lite has numpy and nothing more.
_SNOWFLAKE = r'''"""Grow a model snowflake and draw it as a picture.

This is a model of water vapour freezing, not a simulation of molecules: it
is C. Reiter's snowflake model (Chaos, Solitons & Fractals 23, 1111-1119,
2005, doi:10.1016/s0960-0779(04)00374-1). The flake is flat, and the plane it
grows in is cut into small six-sided cells. Each cell holds some water. A cell
holding as much as 1 is ice.

At every step:
  - every cell of ice, and every cell touching the ice, gains a little water
    (EXTRA): vapour reaching the flake from above and below;
  - the water in all the other cells spreads out to their neighbours, the way
    vapour spreads through air;
  - the air far from the flake is topped up, so it always holds 1 - GATHER.
A cell that reaches 1 freezes. GATHER is therefore how much more water the air
must collect before it turns to ice.

    python3 snowflake.py --gather 0.6 --extra 0.001 --size 100 --out snowflake.png
"""
import argparse
import struct
import sys
import time
import zlib

import numpy as np

SQRT3 = 3.0 ** 0.5
BACKGROUND = np.array([14, 26, 43], dtype=float)       # night sky
EARLY = np.array([29, 78, 145], dtype=float)           # ice that froze first
LATE = np.array([236, 245, 255], dtype=float)          # ice that froze last


def grow(gather, extra, size, max_steps):
    """Run the model. Returns the step at which each cell froze (-1 for
    cells that never did), the number of steps, and how far the flake got."""
    beta = 1.0 - gather
    n = 2 * size + 3
    q, r = np.meshgrid(np.arange(n) - n // 2, np.arange(n) - n // 2, indexing="ij")
    reach_of = np.maximum.reduce([abs(q), abs(r), abs(q + r)])   # cells from the middle
    outside = reach_of >= size

    water = np.full((n, n), beta)
    middle = n // 2
    water[middle, middle] = 1.0
    born = np.full((n, n), -1, dtype=np.int64)
    born[middle, middle] = 0
    reach = 0

    def around(a, edge):
        """The sum of each cell's six neighbours (a grid padded with edge)."""
        p = np.pad(a, 1, constant_values=edge)
        return (p[2:, 1:-1] + p[:-2, 1:-1] + p[1:-1, 2:] + p[1:-1, :-2]
                + p[2:, :-2] + p[:-2, 2:])

    step = 0
    while step < max_steps and reach < size - 6:
        step += 1
        ice = water >= 1.0
        near = ice | (around(ice.astype(np.int8), 0) > 0)
        moving = np.where(near, 0.0, water)
        held = np.where(near, water + extra, 0.0)
        moving = moving + (around(moving, beta) - 6.0 * moving) / 12.0
        water = moving + held
        water[outside] = beta
        new = (water >= 1.0) & (born < 0)
        if new.any():
            born[new] = step
            reach = max(reach, int(reach_of[new].max()))
    return born, step, reach


def picture(born, size, scale=3, fine=3):
    """Colour the ice by when it froze: deep blue first, white last.

    Each pixel is the average of fine x fine points spread over it, so every
    cell gets its true share of the picture. With one point per pixel, a row
    of cells, 2.6 pixels high, got two rows of pixels or three, and cells of
    the same size were drawn at different sizes."""
    n = born.shape[0]
    half = size + 2
    width = int(round(2 * half * scale))
    last = max(int(born.max()), 1)
    t = np.clip(born / last, 0.0, 1.0) ** 0.7
    colour = EARLY * (1 - t)[..., None] + LATE * t[..., None]
    colour[born < 0] = BACKGROUND
    # Points spread evenly over the pixels, in cells from the middle.
    points = (np.arange(width * fine) + 0.5) / (scale * fine) - half
    out = np.empty((width, width, 3), dtype=np.uint8)
    for top in range(0, width, 32):             # 32 rows of pixels at a time
        bottom = min(top + 32, width)
        x, y = np.meshgrid(points, -points[top * fine:bottom * fine])
        # The six-sided cell each point is in.
        rf = y * 2.0 / SQRT3
        qf = x - rf / 2.0
        sf = -qf - rf
        qi, ri, si = np.round(qf), np.round(rf), np.round(sf)
        dq, dr, ds = abs(qi - qf), abs(ri - rf), abs(si - sf)
        qi = np.where((dq > dr) & (dq > ds), -ri - si, qi)
        ri = np.where((dr >= dq) & (dr > ds), -qi - si, ri)
        col = (qi + n // 2).astype(int)
        row = (ri + n // 2).astype(int)
        inside = (col >= 0) & (col < n) & (row >= 0) & (row < n)
        rgb = np.empty(x.shape + (3,))
        rgb[...] = BACKGROUND
        rgb[inside] = colour[col[inside], row[inside]]
        rgb = rgb.reshape(bottom - top, fine, width, fine, 3).mean(axis=(1, 3))
        out[top:bottom] = np.round(rgb).astype(np.uint8)
    return out


def png(rgb, comment):
    """The picture as a PNG file, written by hand: no drawing library needed."""
    height, width, _ = rgb.shape
    raw = np.zeros((height, 1 + 3 * width), dtype=np.uint8)
    raw[:, 1:] = rgb.reshape(height, 3 * width)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"Comment\x00" + comment.encode("latin-1", "replace"))
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 9))
            + chunk(b"IEND", b""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gather", type=float, default=0.6)
    ap.add_argument("--extra", type=float, default=0.001)
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--max-steps", type=int, default=0,
                    help="stop here even if the flake is still small (default 100 x size)")
    ap.add_argument("--out", default="snowflake.png")
    args = ap.parse_args(argv)
    if not 0.0 < args.gather < 1.0:
        sys.exit("--gather must be more than 0 and less than 1")
    if args.extra < 0:
        sys.exit("--extra cannot be negative")
    max_steps = args.max_steps or 100 * args.size

    start = time.time()
    born, steps, reach = grow(args.gather, args.extra, args.size, max_steps)
    took = time.time() - start
    rgb = picture(born, args.size)
    comment = (f"Model snowflake (Reiter 2005): water to gather {args.gather}, "
               f"ice from above and below {args.extra}, {steps} steps")
    with open(args.out, "wb") as fh:
        fh.write(png(rgb, comment))

    print(f"A model snowflake: water to gather {args.gather}, "
          f"ice from above and below {args.extra}.")
    cells = int((born >= 0).sum())
    if reach >= args.size - 6:
        print(f"It grew {reach} cells from the middle in {steps} steps "
              f"({took:.1f} s); {cells:,} cells froze.")
    else:
        print(f"It stopped after {steps} steps, only {reach} cells from the middle "
              f"({took:.1f} s; {cells:,} cells froze): it grows very slowly with "
              "this much to gather and this little from above and below. "
              "Try more ice from above and below, or less water to gather.")
    print(f"Wrote {args.out}, {rgb.shape[1]} x {rgb.shape[0]} pixels.")


if __name__ == "__main__":
    main()
'''


class SnowflakeNode(Node):
    type = "model.snowflake"
    title = "Grow a snowflake"
    category = CATEGORY
    color = COLOR
    tool = "python"
    preview_kind = "image"
    preview_port = "picture"
    description = (
        "Grows a snowflake out of water vapour, in a model, and draws it. It "
        "takes a few seconds.\n\n"
        "This is not a simulation of molecules. A real snowflake holds about a "
        "billion billion water molecules and grows for many minutes, far beyond "
        "any computer that simulates molecules. This block uses a much simpler "
        "model, published by C. Reiter in 2005. It cuts the flat flake and the "
        "air around it into small six-sided cells, and keeps count of how much "
        "water each cell holds. A cell that gathers enough turns to ice. In the "
        "other cells the vapour spreads out, the way vapour spreads through "
        "air.\n\n"
        "It shows one real idea. When the flake grows faster than vapour can "
        "reach it, the corners, which reach furthest into the air, get the most "
        "vapour and grow fastest. So the corners stretch out into arms, and the "
        "arms grow side branches. There are six arms because the cells have six "
        "sides: they stand for the six-sided rings that water molecules form in "
        "ice.\n\n"
        "Two numbers change the shape: how much water a bit of air must gather "
        "before it freezes, and how much ice reaches the flake from above and "
        "below. They are numbers of the model, not temperatures or amounts of "
        "moisture in a real cloud. Try 0.6 and 0.001 for a star with side "
        "branches, 0.7 and 0.0001 for a thin star, 0.35 and 0.001 for a fern, "
        "and 0.05 and 0 for a plate.\n\n"
        "Out comes a picture. The ice is coloured by when it froze: deep blue "
        "first, white last. Dark dots inside the flake are cells that never "
        "quite froze."
    )
    docs = "https://doi.org/10.1016/s0960-0779(04)00374-1"
    outputs = (Port("picture", "picture", "snowflake"),)
    params = (
        Param("gather", "float", "Water to gather before freezing", 0.6,
              min=0.05, max=0.95, step=0.05,
              help="How much more water a bit of air must gather before it turns "
                   "to ice, out of 1: the air far from the flake always holds 1 "
                   "minus this. Much to gather (0.6 or 0.7): the flake needs "
                   "vapour from further away, and the corners, which reach out "
                   "furthest, win, so it grows arms with side branches. Little to "
                   "gather (0.05): every edge freezes almost at once, and the "
                   "flake grows as a plate, a whole hexagon with ribs along the "
                   "six arms. With 0.9 or more it grows so "
                   "slowly that the block stops early, with a small star."),
        Param("extra", "float", "Ice from above and below", 0.001,
              min=0.0, max=0.01, step=0.0005,
              help="Water that reaches the flake from above and below at every "
                   "step, added to every cell of ice and every cell touching it. "
                   "The model is flat, so this stands for the third direction. "
                   "More makes fatter arms that fill in; 0 leaves only the vapour "
                   "that spreads across the flat flake."),
        Param("size", "int", "Size, in cells from the middle", 100,
              min=40, max=250, step=10, advanced=True,
              help="How far the flake may grow from the middle before it stops, "
                   "in cells. 100 takes a few seconds. A bigger flake is finer "
                   "but slower: it has more cells, and further to grow."),
        Param("output", "str", "Output name", "snowflake.png", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        gather = ctx.pfloat("gather", 0.6)
        extra = ctx.pfloat("extra", 0.001)
        size = ctx.pint("size", 100)
        if not 0.0 < gather < 1.0:
            raise NodeError("the water to gather is a share of 1: more than 0 and "
                            "less than 1")
        if not 0.0 <= extra <= 0.1:
            raise NodeError("the ice from above and below is between 0 and 0.1")
        if not 40 <= size <= 250:
            raise NodeError("the size is between 40 and 250 cells from the middle")
        out = ctx.pstr("output") or "snowflake.png"
        if not out.lower().endswith(".png"):
            raise NodeError("the picture is a PNG file: give its name the ending .png")
        plan.files["snowflake.py"] = _SNOWFLAKE
        plan.step(["python", "snowflake.py", "--gather", gather, "--extra", extra,
                   "--size", size, "--out", out],
                  tool="python", label="grow the snowflake")
        plan.outputs["picture"] = out
        return plan


NODES = [SnowflakeNode]
