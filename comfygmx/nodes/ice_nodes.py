"""Ice: a crystal to start from, and a way to see how much of it is left.

Two blocks for the ice-melting tutorial, and for anything else made of ice.
"Ice crystal" builds a block of ordinary ice (ice Ih, the kind in a freezer)
out of TIP4P/Ice water, with a topology to match. "Count the ice" goes
through a trajectory and counts, frame by frame, how many molecules are
still arranged as in a crystal.

Both do their work with small Python scripts that travel inside the block.
The ice builder needs nothing but Python; the counter needs numpy.
"""

from __future__ import annotations

from .base import Node, NodeError, Param, Plan, PlanContext, Port

BUILD = "Build system"
BUILD_COLOR = "#2b5d8a"
ANALYSIS = "Analysis"
ANALYSIS_COLOR = "#3f7a6d"

_MAKE_ICE = r'''"""Build a block of ice Ih out of TIP4P/Ice water molecules.

Writes three files:

* a structure (.gro): the crystal, in a box exactly the size of the crystal,
  so that it is a perfect periodic crystal as it stands;
* a topology (.top): what a TIP4P/Ice molecule is, and how many there are;
* an index (.ndx): the group "Oxygens", one atom per molecule, for looking at
  the crystal without the hydrogens in the way.

Where the oxygens go is fixed by the crystal. Where the hydrogens go is not:
each oxygen has four neighbours and points its two hydrogens at two of them,
and ice does not care which two, as long as every oxygen gives two hydrogens,
takes two, and every neighbouring pair shares exactly one ("the ice rules").
The choice is made at random here, then adjusted until the whole crystal has
no overall electric dipole, as real ice has none.

Standard library only, so it runs under any Python 3.
"""

import argparse
import math
import random
import sys

# Ice Ih. a is the distance between neighbouring hexagonal channels; c is the
# height of two layers. c/a is the ideal sqrt(8/3), which makes every O-O-O
# angle the tetrahedral 109.47 degrees and every O-O distance the same.
A = 0.4513                           # nm
C = A * math.sqrt(8.0 / 3.0)         # nm
CELL = (A, A * math.sqrt(3.0), C)    # a rectangular cell of 8 molecules

# TIP4P/Ice: Abascal, Sanz, Garcia Fernandez and Vega, J. Chem. Phys. 122,
# 234511 (2005), doi:10.1063/1.1931662
R_OH = 0.09572                       # nm
ANGLE_HOH = 104.52                   # degrees
D_OM = 0.01577                       # nm, the charge site M on the bisector
SIGMA = 0.31668                      # nm
EPSILON = 106.1 * 0.0083144626       # 106.1 K times the gas constant, kJ/mol
Q_H = 0.5897                         # e
Q_M = -2 * Q_H


def cell_oxygens():
    """The 8 oxygens of one rectangular cell (a, a*sqrt(3), c), in nm."""
    # The four oxygens of the hexagonal cell: space group P6_3/mmc, site 4f,
    # with z = 1/16, which is the ideal tetrahedral arrangement.
    z = 1.0 / 16.0
    frac = [(1 / 3, 2 / 3, z), (2 / 3, 1 / 3, z + 0.5),
            (2 / 3, 1 / 3, -z), (1 / 3, 2 / 3, 0.5 - z)]
    a1 = (A, 0.0)
    a2 = (-A / 2.0, A * math.sqrt(3.0) / 2.0)
    lx, ly, lz = CELL
    found = []
    for f1, f2, f3 in frac:
        for n1 in range(-3, 4):
            for n2 in range(-3, 4):
                x = (f1 + n1) * a1[0] + (f2 + n2) * a2[0]
                y = (f1 + n1) * a1[1] + (f2 + n2) * a2[1]
                if -1e-6 < x < lx - 1e-6 and -1e-6 < y < ly - 1e-6:
                    p = (round(x % lx, 6), round(y % ly, 6), round((f3 % 1.0) * lz, 6))
                    if p not in found:
                        found.append(p)
    if len(found) != 8:
        raise SystemExit(f"internal error: {len(found)} oxygens in a cell, expected 8")
    return found


def build_oxygens(nx, ny, nz):
    lx, ly, lz = CELL
    base = cell_oxygens()
    oxygens = []
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                for x, y, zz in base:
                    oxygens.append((x + ix * lx, y + iy * ly, zz + iz * lz))
    return oxygens, (nx * lx, ny * ly, nz * lz)


def minimum_image(d, box):
    return tuple(di - bi * round(di / bi) for di, bi in zip(d, box))


def neighbour_bonds(oxygens, box, cutoff=0.30):
    """Every O-O hydrogen bond of the crystal, as (i, j, vector from i to j)."""
    size = cutoff
    grid = {}
    shape = [max(1, int(b // size)) for b in box]
    for i, p in enumerate(oxygens):
        key = tuple(int(p[k] / box[k] * shape[k]) % shape[k] for k in range(3))
        grid.setdefault(key, []).append(i)
    bonds = []
    for i, p in enumerate(oxygens):
        key = tuple(int(p[k] / box[k] * shape[k]) % shape[k] for k in range(3))
        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    other = ((key[0] + dx) % shape[0], (key[1] + dy) % shape[1],
                             (key[2] + dz) % shape[2])
                    for j in grid.get(other, ()):
                        if j <= i or j in seen:
                            continue
                        seen.add(j)
                        d = minimum_image(tuple(oxygens[j][k] - p[k] for k in range(3)), box)
                        if math.sqrt(sum(c * c for c in d)) < cutoff:
                            bonds.append((i, j, d))
    count = [0] * len(oxygens)
    for i, j, _ in bonds:
        count[i] += 1
        count[j] += 1
    if any(c != 4 for c in count):
        raise SystemExit("the crystal is too small in some direction: use at least "
                         "2 cells along each direction")
    return bonds


class Orientation:
    """Which way each bond points: from the oxygen that gives the hydrogen to
    the one that takes it."""

    def __init__(self, n, bonds, rng):
        self.bonds = bonds
        self.rng = rng
        self.touching = [[] for _ in range(n)]
        for e, (i, j, _) in enumerate(bonds):
            self.touching[i].append(e)
            self.touching[j].append(e)
        self.forward = [True] * len(bonds)   # True: i gives to j
        self._walks_to_start()

    def giver(self, e):
        i, j, _ = self.bonds[e]
        return i if self.forward[e] else j

    def taker(self, e):
        i, j, _ = self.bonds[e]
        return j if self.forward[e] else i

    def vector(self, e):
        d = self.bonds[e][2]
        return d if self.forward[e] else tuple(-c for c in d)

    def _walks_to_start(self):
        # Every oxygen has four bonds, an even number, so a walk along unused
        # bonds can only get stuck where it began. Pointing every bond the way
        # the walk went through it gives each oxygen as many bonds out as in:
        # two and two, which is the ice rules.
        unused = [list(t) for t in self.touching]
        used = [False] * len(self.bonds)
        for start in range(len(unused)):
            while any(not used[e] for e in unused[start]):
                v = start
                while True:
                    choices = [e for e in unused[v] if not used[e]]
                    if not choices:
                        break
                    e = self.rng.choice(choices)
                    used[e] = True
                    i, j, _ = self.bonds[e]
                    self.forward[e] = (i == v)
                    v = j if i == v else i

    def loop(self, start):
        """Follow outgoing bonds at random until the walk meets itself; the
        bonds of the loop that closes, and how far it went around the box."""
        at = {start: 0}
        path = []
        v = start
        while True:
            e = self.rng.choice([e for e in self.touching[v] if self.giver(e) == v])
            path.append(e)
            v = self.taker(e)
            if v in at:
                return path[at[v]:]
            at[v] = len(path)

    def flip(self, edges):
        for e in edges:
            self.forward[e] = not self.forward[e]

    def dipole(self):
        return [sum(self.vector(e)[k] for e in range(len(self.bonds))) for k in range(3)]


def disorder(n, bonds, box, rng, shuffles):
    o = Orientation(n, bonds, rng)
    for _ in range(shuffles):
        edges = o.loop(rng.randrange(n))
        shift = [sum(o.vector(e)[k] for e in edges) for k in range(3)]
        if all(abs(s) < 1e-6 for s in shift):
            o.flip(edges)     # a loop that closes inside the box: free to turn round
    # What is left is how many times the bonds wind round the box, net, in
    # each direction -- a dipole across the whole crystal. Turn round loops
    # that wind the right way until nothing winds.
    for attempt in range(200000):
        wind = [round(o.dipole()[k] / box[k]) for k in range(3)]
        if not any(wind):
            return o
        edges = o.loop(rng.randrange(n))
        shift = [round(sum(o.vector(e)[k] for e in edges) / box[k]) for k in range(3)]
        after = [wind[k] - 2 * shift[k] for k in range(3)]
        if sum(abs(a) for a in after) < sum(abs(w) for w in wind):
            o.flip(edges)
    raise SystemExit("could not remove the dipole: try an even number of cells "
                     "in each direction")


def unit(v):
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v)


def write(prefix_gro, prefix_top, prefix_ndx, oxygens, box, o, seed):
    half = math.radians(ANGLE_HOH) / 2.0
    lines = []
    atom = 0
    gives = [[] for _ in oxygens]
    for e in range(len(o.bonds)):
        gives[o.giver(e)].append(o.vector(e))
    for m, p in enumerate(oxygens):
        u1, u2 = (unit(v) for v in gives[m])
        bis = unit(tuple(a + b for a, b in zip(u1, u2)))
        per = unit(tuple(a - b for a, b in zip(u1, u2)))
        h1 = tuple(p[k] + R_OH * (math.cos(half) * bis[k] + math.sin(half) * per[k]) for k in range(3))
        h2 = tuple(p[k] + R_OH * (math.cos(half) * bis[k] - math.sin(half) * per[k]) for k in range(3))
        msite = tuple(p[k] + D_OM * bis[k] for k in range(3))
        for name, xyz in (("OW", p), ("HW1", h1), ("HW2", h2), ("MW", msite)):
            atom += 1
            lines.append("%5d%-5s%5s%5d%8.3f%8.3f%8.3f\n" % (
                (m + 1) % 100000, "SOL", name, atom % 100000, xyz[0], xyz[1], xyz[2]))
    n = len(oxygens)
    with open(prefix_gro, "w") as fh:
        fh.write(f"Ice Ih, {n} TIP4P/Ice molecules, hydrogens from seed {seed}\n")
        fh.write(f"{atom:5d}\n")
        fh.writelines(lines)
        fh.write("%10.5f%10.5f%10.5f\n" % box)
    with open(prefix_top, "w") as fh:
        fh.write(TOPOLOGY.format(sigma=SIGMA, epsilon=EPSILON, q_h=Q_H, q_m=Q_M,
                                 r_oh=R_OH, r_hh=2 * R_OH * math.sin(half),
                                 a=D_OM / (2 * R_OH * math.cos(half)), n=n))
    with open(prefix_ndx, "w") as fh:
        fh.write("[ Oxygens ]\n")
        numbers = [str(4 * m + 1) for m in range(n)]
        for k in range(0, n, 15):
            fh.write(" ".join(numbers[k:k + 15]) + "\n")


TOPOLOGY = """\
; TIP4P/Ice water, as a crystal of ice Ih.
;
; Abascal, Sanz, Garcia Fernandez and Vega, "A potential model for the study
; of ices and amorphous water: TIP4P/Ice", J. Chem. Phys. 122, 234511 (2005),
; doi:10.1063/1.1931662. A water model made to melt at the right temperature:
; its ice melts at about 270 K, against 273 K for real ice.
;
; Four sites. The oxygen O carries no charge but is the only one that feels
; the others' size (the Lennard-Jones sigma and epsilon). The two hydrogens H
; carry the positive charge. M is not an atom at all: a point on the line
; between the two hydrogens, a little in front of the oxygen, that carries
; the negative charge. The molecule is rigid: SETTLE holds its shape.

[ defaults ]
; nbfunc  comb-rule  gen-pairs  fudgeLJ  fudgeQQ
  1       2          no         1.0      1.0

[ atomtypes ]
; name    at.num  mass     charge  ptype  sigma (nm)  epsilon (kJ/mol)
  OW_ice  8       15.9994  0.0     A      {sigma:.5f}     {epsilon:.6f}
  HW_ice  1       1.008    0.0     A      0.0         0.0
  MW_ice  0       0.0      0.0     D      0.0         0.0

[ moleculetype ]
; name  nrexcl
  SOL   2

[ atoms ]
; nr  type    resnr  residue  atom  cgnr  charge    mass
  1   OW_ice  1      SOL      OW    1      0.0      15.9994
  2   HW_ice  1      SOL      HW1   1      {q_h:.4f}    1.008
  3   HW_ice  1      SOL      HW2   1      {q_h:.4f}    1.008
  4   MW_ice  1      SOL      MW    1     {q_m:.4f}    0.0

[ settles ]
; oxygen  funct  O-H (nm)  H-H (nm)
  1       1      {r_oh:.5f}   {r_hh:.5f}

[ virtual_sites3 ]
; M is built from O, H1 and H2 at every step
; site  from    funct  a            b
  4     1 2 3   1      {a:.9f}  {a:.9f}

[ exclusions ]
1 2 3 4
2 1 3 4
3 1 2 4
4 1 2 3

[ system ]
Ice Ih, TIP4P/Ice

[ molecules ]
; name  number
  SOL   {n}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cells", type=int, nargs=3, default=[6, 4, 4],
                    metavar=("X", "Y", "Z"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gro", default="ice.gro")
    ap.add_argument("--top", default="ice.top")
    ap.add_argument("--ndx", default="ice.ndx")
    args = ap.parse_args(argv)
    if min(args.cells) < 2:
        raise SystemExit("use at least 2 cells in each direction")
    rng = random.Random(args.seed)
    oxygens, box = build_oxygens(*args.cells)
    bonds = neighbour_bonds(oxygens, box)
    o = disorder(len(oxygens), bonds, box, rng, shuffles=20 * len(oxygens))
    write(args.gro, args.top, args.ndx, oxygens, box, o, args.seed)
    dip = o.dipole()
    print(f"{len(oxygens)} water molecules in ice Ih, {args.cells[0]} x {args.cells[1]} x "
          f"{args.cells[2]} cells, {box[0]:.3f} x {box[1]:.3f} x {box[2]:.3f} nm")
    print(f"every oxygen gives two hydrogens and takes two; the bonds' overall "
          f"direction adds up to ({dip[0]:.3f}, {dip[1]:.3f}, {dip[2]:.3f}) nm, so the "
          f"crystal has no overall dipole")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_COUNT_ICE = r'''#!/usr/bin/env python3
"""Count, frame by frame, how many water molecules are still part of the ice.

A molecule counts as ice when it has exactly four neighbours closer than
0.35 nm, arranged as they are in a crystal. The test is CHILL+ (Nguyen and
Molinero, J. Phys. Chem. B 119, 9369-9376 (2015), doi:10.1021/jp510289t):
for each pair of neighbours it asks whether, looking along the line between
them, the other neighbours of the two sit in between each other's
("staggered") or right behind each other's ("eclipsed"). Hexagonal ice, the
ice in a freezer, has three staggered and one eclipsed; cubic ice, a rarer
cousin, has four staggered. Liquid water has no such order and passes neither.

Molecules on the outside of a crystal never count: they have no neighbours on
the outside. So a small crystal starts well below its full number.

usage: count_ice.py oxygens.gro out.xvg [--cutoff 0.35]
"""

import argparse
import math
import sys

import numpy as np

C0 = 0.25 * math.sqrt(7 / math.pi)
C1 = 0.125 * math.sqrt(21 / math.pi)
C2 = 0.25 * math.sqrt(105 / (2 * math.pi))
C3 = 0.125 * math.sqrt(35 / math.pi)


def frames(path):
    """(time in ps, oxygen positions, box) for every frame of a .gro file."""
    with open(path) as fh:
        while True:
            title = fh.readline()
            if not title:
                return
            n = int(fh.readline())
            xyz = np.empty((n, 3))
            for i in range(n):
                line = fh.readline()
                xyz[i] = (float(line[20:28]), float(line[28:36]), float(line[36:44]))
            box = np.array([float(v) for v in fh.readline().split()[:3]])
            time = float(title.split("t=")[1].split()[0]) if "t=" in title else 0.0
            yield time, xyz, box


def y3(u):
    """The seven spherical harmonics of order 3 for unit vectors u (n x 3)."""
    x, y, z = u[:, 0], u[:, 1], u[:, 2]
    w = x + 1j * y
    m0 = C0 * (5 * z ** 3 - 3 * z)
    m1 = -C1 * w * (5 * z ** 2 - 1)
    m2 = C2 * w ** 2 * z
    m3 = -C3 * w ** 3
    return np.stack([-np.conj(m3), np.conj(m2), -np.conj(m1), m0, m1, m2, m3], axis=1)


def classify(o, box, cutoff):
    """How many molecules are hexagonal ice, and how many cubic ice."""
    n = len(o)
    ii, jj, dd = [], [], []
    for start in range(0, n, 256):
        d = o[None, :, :] - o[start:start + 256, None, :]
        d -= box * np.round(d / box)
        r = np.sqrt((d ** 2).sum(-1))
        a, b = np.nonzero((r < cutoff) & (r > 0))
        ii.append(a + start)
        jj.append(b)
        dd.append(d[a, b] / r[a, b][:, None])
    ii = np.concatenate(ii)
    jj = np.concatenate(jj)
    dd = np.concatenate(dd)
    count = np.bincount(ii, minlength=n)
    q = np.zeros((n, 7), complex)
    np.add.at(q, ii, y3(dd))
    norm = np.sqrt((np.abs(q) ** 2).sum(1))
    norm[norm == 0] = 1.0
    c = np.real((q[ii] * np.conj(q[jj])).sum(1)) / (norm[ii] * norm[jj])
    staggered = np.bincount(ii, weights=(c <= -0.8), minlength=n)
    eclipsed = np.bincount(ii, weights=(c >= -0.35) & (c <= 0.25), minlength=n)
    four = count == 4
    cubic = four & (staggered == 4)
    hexagonal = four & (staggered == 3) & (eclipsed == 1)
    return int(hexagonal.sum()), int(cubic.sum())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Count the molecules that are ice.")
    ap.add_argument("frames")
    ap.add_argument("out")
    ap.add_argument("--cutoff", type=float, default=0.35)
    args = ap.parse_args(argv)

    rows = []
    total = 0
    for time, xyz, box in frames(args.frames):
        hexagonal, cubic = classify(xyz, box, args.cutoff)
        rows.append((time, hexagonal + cubic, hexagonal, cubic))
        total = len(xyz)
    if not rows:
        sys.exit("no frames in " + args.frames)

    with open(args.out, "w") as fh:
        fh.write("# written by Comfy-gmx's 'Count the ice' block\n")
        fh.write("# columns: time (ps), molecules in ice, of which hexagonal, of which cubic\n")
        fh.write(f'@    title "How many of the {total} molecules are ice"\n')
        fh.write('@    xaxis  label "Time (ps)"\n')
        fh.write('@    yaxis  label "Molecules in ice"\n')
        fh.write("@TYPE xy\n")
        fh.write('@ s0 legend "in ice"\n')
        for time, ice, hexagonal, cubic in rows:
            fh.write(f"{time:10.3f} {ice:6d}\n")

    first, last = rows[0][1], rows[-1][1]
    print(f"{len(rows)} frames, {total} water molecules")
    print(f"in ice at the start: {first}; at the end ({rows[-1][0]:.1f} ps): {last}")
    if first and last <= 0.02 * first:
        gone = next(t for t, ice, _h, _c in rows if ice <= 0.02 * first)
        print(f"the ice was all but gone after {gone:.1f} ps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


class IceCrystalNode(Node):
    type = "build.ice"
    title = "Ice crystal"
    category = BUILD
    color = BUILD_COLOR
    tool = "python"
    description = (
        "Builds a block of ice: ordinary hexagonal ice, the kind in a freezer, "
        "made of TIP4P/Ice water molecules -- a water model designed to melt "
        "at the right temperature, about 270 K where real ice melts at 273 K.\n\n"
        "The block is made of small rectangular cells of 8 molecules each, "
        "0.45 x 0.78 x 0.74 nm. The oxygens sit where the crystal puts them. "
        "The hydrogens are placed at random, but by the rules real ice keeps: "
        "every oxygen holds two hydrogens and points them at two of its four "
        "neighbours, and every pair of neighbours shares exactly one. The "
        "crystal has no overall electric dipole, as real ice has none.\n\n"
        "Out come the crystal, a topology that says what a TIP4P/Ice molecule "
        "is, and an index file with one group, 'Oxygens': one atom per "
        "molecule, which is the clearest way to look at the crystal."
    )
    docs = "https://doi.org/10.1063/1.1931662"
    outputs = (
        Port("structure", "structure", "ice"),
        Port("topology", "topology", "topology"),
        Port("index", "index", "index"),
    )
    params = (
        Param("cells_x", "int", "Cells along x", 6, min=2, max=40,
              help="0.45 nm each. 6 cells make 2.7 nm."),
        Param("cells_y", "int", "Cells along y", 4, min=2, max=40,
              help="0.78 nm each. 4 cells make 3.1 nm."),
        Param("cells_z", "int", "Cells along z", 4, min=2, max=40,
              help="0.74 nm each, and the direction the hexagonal channels "
                   "run in: look down z to see the honeycomb. 4 cells make "
                   "2.9 nm."),
        Param("seed", "int", "Seed for the hydrogens", 1, min=1,
              help="Which random arrangement of hydrogens. Any number; the "
                   "same number gives the same crystal."),
        Param("output", "str", "Output name", "ice.gro", advanced=True),
        Param("topology_name", "str", "Topology name", "ice.top", advanced=True),
        Param("index_name", "str", "Index name", "ice.ndx", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        cells = [ctx.pint(name, 4) for name in ("cells_x", "cells_y", "cells_z")]
        if min(cells) < 2:
            raise NodeError("use at least 2 cells in each direction: with fewer, "
                            "a molecule would be its own neighbour across the box")
        out = ctx.pstr("output") or "ice.gro"
        top = ctx.pstr("topology_name") or "ice.top"
        ndx = ctx.pstr("index_name") or "ice.ndx"
        plan.files["make_ice.py"] = _MAKE_ICE
        plan.step(["python", "make_ice.py", "--cells", *cells,
                   "--seed", ctx.pint("seed", 1),
                   "--gro", out, "--top", top, "--ndx", ndx],
                  tool="python", label="build the ice crystal")
        plan.outputs["structure"] = out
        plan.outputs["topology"] = {"top": top, "glob": []}
        plan.outputs["index"] = ndx
        return plan


class IceCountNode(Node):
    type = "analysis.ice_count"
    title = "Count the ice"
    category = ANALYSIS
    color = ANALYSIS_COLOR
    tool = "gmx"
    description = (
        "Goes through a trajectory and counts, frame by frame, how many water "
        "molecules are still part of the ice. A falling line is ice melting; "
        "a flat one is ice that holds.\n\n"
        "A molecule counts as ice when its four nearest neighbours sit exactly "
        "as they do in a crystal (the CHILL+ test, Nguyen and Molinero 2015). "
        "Molecules on the outside of a crystal never count, because they have "
        "no neighbours on the outside, so a small crystal starts well below "
        "its full number of molecules."
    )
    docs = "https://doi.org/10.1021/jp510289t"
    inputs = (
        Port("traj", "traj", "trajectory"),
        Port("tpr", "tpr", "tpr"),
    )
    outputs = (Port("xvg", "xvg", "molecules in ice over time"),)
    params = (
        Param("sel", "str", "The water oxygens", "name OW",
              help="A GROMACS selection that picks one atom per water molecule: "
                   "its oxygen. 'name OW' for most water models."),
        Param("skip", "int", "Use every Nth frame", 1, min=1, max=10000),
        Param("cutoff", "float", "Neighbour distance (nm)", 0.35, min=0.2, max=0.6,
              advanced=True,
              help="Oxygens closer than this are neighbours. 0.35 nm is the "
                   "value the CHILL+ test was made with."),
        Param("output", "str", "Output name", "ice_count.xvg", advanced=True),
    )

    def plan(self, ctx: PlanContext) -> Plan:
        plan = Plan()
        tpr = ctx.require("tpr")
        traj = ctx.require("traj")
        out = ctx.pstr("output") or "ice_count.xvg"
        sel = ctx.pstr("sel") or "name OW"
        plan.step(["gmx", "select", "-s", tpr, "-select", sel, "-on", "oxygens.ndx"],
                  tool="gmx", label="find the water oxygens")
        argv = ["gmx", "trjconv", "-s", tpr, "-f", traj, "-n", "oxygens.ndx",
                "-o", "oxygens.gro"]
        if ctx.pint("skip", 1) > 1:
            argv += ["-skip", ctx.pint("skip", 1)]
        plan.step(argv, tool="gmx", label="take the oxygens out of every frame",
                  stdin="0\n")
        plan.files["count_ice.py"] = _COUNT_ICE
        plan.step(["python", "count_ice.py", "oxygens.gro", out,
                   "--cutoff", ctx.pfloat("cutoff", 0.35)],
                  tool="python", label="count the ice")
        plan.outputs["xvg"] = out
        return plan


NODES = [IceCrystalNode, IceCountNode]
