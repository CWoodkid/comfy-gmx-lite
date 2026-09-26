"""An ice cube heated until it boils away: a tutorial written for this version.

Not a translation of a published course, unlike Lysozyme in Water. A small cube
of ice floats in empty space and is heated in one run, from colder than any
freezer to far hotter than any kettle. On the way it melts into a round drop,
and the drop boils away into a gas that fills the box. Four measurements say
the same thing in numbers: the temperature, how many molecules are still part
of the ice, how big the lump is, and how tightly the molecules still hold on
to each other. A movie shows it.

The whole of it runs in a few minutes on one processor, which is the point:
it was made for a class, where there are fifteen minutes and one processor
each.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .chunks import COLOR
from .tutorial_graph import (
    group as _group, level_with as _level_with, link as _l, node as _n,
    note as _note, relayout as _relayout, wall as _wall,
)

#: Where the teacher's notes for this tutorial live.
SITE = "https://github.com/CWoodkid/comfy-gmx-lite/blob/main/docs/ice-melting.md"
AUTHOR = "Comfy-gmx lite"
CITATION = (
    "The water model: Abascal, J. L. F., Sanz, E., Garcia Fernandez, R. and "
    "Vega, C. (2005) A potential model for the study of ices and amorphous "
    "water: TIP4P/Ice. J. Chem. Phys. 122, 234511. doi:10.1063/1.1931662. "
    "The ice count: Nguyen, A. H. and Molinero, V. (2015) Identification of "
    "clathrate hydrates, hexagonal ice, cubic ice, and liquid water in "
    "simulations: the CHILL+ algorithm. J. Phys. Chem. B 119, 9369-9376. "
    "doi:10.1021/jp510289t"
)

_MIN_MDP = """; Minimisation: let every molecule settle into place.
;
; A crystal built from a recipe is never quite right -- a hydrogen a little
; too close to a neighbour here, a molecule a little twisted there. This walks
; every molecule downhill in energy until nothing is pushing hard any more.
; No time passes, and nothing moves afterwards: the cube is standing
; perfectly still, which is what 0 K, absolute zero, means.
integrator      = steep
emtol           = 100       ; stop when no force is bigger than this
nsteps          = 5000      ; or after this many tries

cutoff-scheme   = Verlet
coulombtype     = PME       ; every charge feels every other charge
rcoulomb        = 1.0       ; nm
vdwtype         = cut-off   ; molecules further apart than rvdw ignore each other's size
rvdw            = 1.0       ; nm
pbc             = xyz       ; the box repeats in every direction
"""

# The heating schedule was chosen by trying several on this very cube. Heated
# at one steady rate from 200 K to 1000 K, it melted within about 15 ps and
# was a drop for only about 30 ps before it started to boil. Climbing slowly to 400 K and
# fast after that gives every stage its share of the 200 ps: ice for about
# 30 ps, melting for about 40, a drop for about 40, boiling for about 60, gas
# for the rest.
_HEAT_MDP = """; The ice cube heated in one run, from 200 K to 1000 K.
;
; 200 K is minus 73 degrees C, colder than any freezer. 1000 K is over 700
; degrees C. The thermostat's target climbs as the run goes: slowly to 400 K
; over the first 100 ps, so the ice has time to melt and the drop time to
; settle, then fast to 1000 K over the next 100 ps, where the drop boils away.
; To heat it differently, change the numbers on the annealing lines, and
; nsteps to match the last time on them.
integrator           = md
dt                   = 0.002     ; one step is 2 femtoseconds (0.002 ps)
nsteps               = 100000    ; 100,000 steps: 200 picoseconds

nstxout-compressed   = 250       ; save a picture every 250 steps (0.5 ps)
nstenergy            = 500       ; and the energies, every 1 ps
nstlog               = 5000

cutoff-scheme        = Verlet
coulombtype          = PME
rcoulomb             = 1.0
vdwtype              = cut-off
rvdw                 = 1.0
pbc                  = xyz

; The thermostat: it keeps the temperature at its target, by speeding the
; molecules up or slowing them down a little at every step.
tcoupl               = v-rescale
tc-grps              = System
tau_t                = 0.1       ; how quickly it corrects, in ps
ref_t                = 200       ; the target at the start

; Annealing: the target moves, in straight lines between these points.
; 200 K at 0 ps, 400 K at 100 ps, 1000 K at 200 ps.
annealing            = single
annealing-npoints    = 3
annealing-time       = 0 100 200
annealing-temp       = 200 400 1000

; Give every molecule a speed to start with, picked at random the way
; speeds are spread at 200 K.
gen_vel              = yes
gen_temp             = 200
gen_seed             = 2026

; No pressure control: around the cube there is nothing but empty space, and
; that is where the gas goes.
pcoupl               = no

; Take away any drift of the whole lot, so it does not wander off. Only the
; drift: molecules that boil off fly out through one side of the box and come
; back in through the opposite one, since the box repeats in every direction,
; and stopping any spin as well goes wrong once they do.
comm-mode            = linear
"""


_ICE_NODES: List[Dict[str, Any]] = [
    _note("note_what", 0, 0,
          "AN ICE CUBE, HEATED UNTIL IT BOILS AWAY\n"
          "\n"
          "Ice is water whose molecules have stopped tumbling past each other\n"
          "and locked into a pattern. Every molecule holds on to four\n"
          "neighbours, and together they make a honeycomb of six-sided rings.\n"
          "Melting is that pattern breaking up. Boiling is the molecules\n"
          "letting go of each other altogether.\n"
          "\n"
          "Here you build a tiny ice cube -- 768 water molecules, 3 nanometres\n"
          "across; ten million of them side by side would make one cube for a\n"
          "drink -- let it float in empty space, and heat it: from colder than\n"
          "any freezer to far hotter than any kettle, in one run.\n"
          "\n"
          "Press Run. Everything takes a few minutes; read the notes while it\n"
          "works. Point at any socket to see what kind of file goes through\n"
          "it; Help (the ? at the top) lists them all."),

    # ---- 1. the cube --------------------------------------------------------
    # The page reads in two columns. On the left, one box builds the cube and
    # lets it settle. On the right, the run that heats it, with its graphs.
    # The three files the run needs leave the left box through dots on its
    # right edge and enter the run through dots on its left edge, so they
    # cross the gap between the columns as a few tidy lines instead of a
    # tangle of long wires. The run's note sits inside its box, in the space
    # under the blocks, where no wire has to pass.
    _note("note_build", 2, 0,
          "1. BUILD THE CUBE\n"
          "\n"
          "'Ice crystal' puts every molecule where ice puts it. Each oxygen\n"
          "(red) points its two hydrogens (white) at two of its four\n"
          "neighbours. Those hydrogen bonds are what hold ice together.\n"
          "\n"
          "The water model is TIP4P/Ice: a water molecule drawn as four points\n"
          "-- an oxygen, two hydrogens, and one invisible point that carries the\n"
          "negative charge. Its numbers were chosen so that its ice melts at\n"
          "the right temperature: 272 K, where real ice melts at 273 K,\n"
          "0 degrees C.\n"
          "\n"
          "'Define box' puts the cube in the middle of a 5.5 nm box of empty\n"
          "space. Simulation boxes repeat in every direction, so the box has to\n"
          "be big enough that the cube never feels the copy of itself next door.\n"
          "\n"
          "The second row lets the cube settle: every molecule is nudged into\n"
          "place before the clock starts. No time passes in this step."),
    _n("ice", "build.ice", 0, 1, cells_x=6, cells_y=4, cells_z=4, seed=1),
    _n("box", "gmx.editconf", 1, 1, box_type="cubic", box="5.5 5.5 5.5",
       center=True, output="cube.gro"),
    _n("look", "view.structure", 2, 1),

    # ---- 2. settle ----------------------------------------------------------
    _n("em_mdp", "util.mdp", 0, 2, mode="raw", raw=_MIN_MDP,
       filename="minimise.mdp"),
    _n("em_pp", "gmx.grompp", 1, 2, output="em.tpr"),
    _n("em", "gmx.mdrun", 2, 2, deffnm="em"),

    # ---- 3. heat ------------------------------------------------------------
    _note("note_heat", 5.5, 2,
          "2. HEAT IT: 200 K TO 1000 K\n"
          "\n"
          "Every molecule is given a speed that matches 200 K, minus 73\n"
          "degrees C, and a thermostat keeps the temperature where it is told.\n"
          "Then it is told to climb: slowly to 400 K over the first 100\n"
          "picoseconds, then fast to 1000 K over the next 100. That is 100,000\n"
          "steps of 2 femtoseconds each; a femtosecond is a millionth of a\n"
          "billionth of a second.\n"
          "\n"
          "What happens, in order:\n"
          "- ice for about the first 30 ps: the molecules shiver harder and\n"
          "  harder, but the honeycomb holds;\n"
          "- then it melts, from the surface inwards, and by about 70 ps, near\n"
          "  340 K, it has pulled itself into a round drop;\n"
          "- a drop of hot water for about 40 ps, far above 100 degrees C;\n"
          "- then it boils away: molecules fly off, a few at first, then in a\n"
          "  rush;\n"
          "- gas for the last 30 or 40 ps: the molecules fill the whole box.\n"
          "\n"
          "Real ice melts at 273 K and real water boils at 373 K. Here both\n"
          "happen later, because everything has to happen within 200\n"
          "picoseconds: the heat arrives faster than a crystal can come apart,\n"
          "and at 373 K a molecule escapes from the drop only now and then."),
    _n("heat_mdp", "util.mdp", 4.5, 1, mode="raw", raw=_HEAT_MDP,
       filename="heat.mdp"),
    _n("heat_pp", "gmx.grompp", 5.5, 1, output="heat.tpr"),
    _n("heat", "gmx.mdrun", 6.5, 1, deffnm="heat"),
    _n("temp", "gmx.energy", 7.5, 1, terms="Temperature\n",
       output="temperature.xvg"),
    _n("temp_plot", "view.plot", 8.5, 1),
    _n("count", "analysis.ice_count", 7.5, 2, output="ice.xvg"),
    _n("count_plot", "view.plot", 8.5, 2),
    _n("size", "gmx.gyrate", 7.5, 3, sel="Oxygens", tu="ps", output="size.xvg"),
    _n("size_plot", "view.plot", 8.5, 3),
    _n("energy", "gmx.energy", 7.5, 4, terms="Potential\n", output="energy.xvg"),
    _n("energy_plot", "view.plot", 8.5, 4),
    _n("watch", "view.trajectory", 9.5, 1, mode="every Nth", skip=2,
       sel="Oxygens", pbc="mol", center=True),

    # ---- 4. reading it ------------------------------------------------------
    # Above the pictures it explains.
    _note("note_read", 7.5, 0,
          "3. WHAT THE PICTURES SAY\n"
          "\n"
          "TEMPERATURE: the thermometer. It follows the thermostat: a gentle\n"
          "slope for 100 ps, then a steep one. Use it to read off how hot it\n"
          "was at any moment in the other graphs.\n"
          "\n"
          "COUNT THE ICE: how many molecules still sit in the honeycomb, frame\n"
          "by frame. It starts well below 768, because a molecule on the\n"
          "surface has too few neighbours to pass the test, and drops within\n"
          "the first picosecond: once the molecules shiver, some fail the\n"
          "strict test even though the crystal is still there. Its fall to\n"
          "zero is the melting.\n"
          "\n"
          "SIZE: the radius of gyration, roughly how far the molecules are from\n"
          "the middle, on average. It shrinks a little as the cube melts: a\n"
          "ball is more compact than a cube, and liquid water packs its\n"
          "molecules closer together than ice does, which is why ice floats.\n"
          "Then it shoots up as the drop boils away, and levels off once the\n"
          "gas fills the box evenly.\n"
          "\n"
          "ENERGY: how tightly the molecules hold on to each other, the\n"
          "potential energy. The more negative, the tighter. It climbs the whole\n"
          "way, because the heat goes into pulling the molecules apart; fastest\n"
          "while the drop boils away, and hardly at all once it is all gas,\n"
          "when the molecules have almost nothing left to let go of.\n"
          "\n"
          "THE MOVIE: one dot per molecule, its oxygen. Press play; drag to\n"
          "turn it."),
]

_ICE_LINKS: List[Dict[str, str]] = [
    _l("ice", "structure", "box", "structure"),
    _l("box", "structure", "look", "structure"),

    _l("em_mdp", "mdp", "em_pp", "mdp"),
    _l("box", "structure", "em_pp", "structure"),
    _l("ice", "topology", "em_pp", "topology"),
    _l("em_pp", "tpr", "em", "tpr"),

    _l("heat_mdp", "mdp", "heat_pp", "mdp"),
    _l("em", "structure", "heat_pp", "structure"),
    _l("ice", "topology", "heat_pp", "topology"),
    _l("heat_pp", "tpr", "heat", "tpr"),
    _l("heat", "edr", "temp", "edr"),
    _l("temp", "xvg", "temp_plot", "xvg"),
    _l("heat", "traj", "count", "traj"),
    _l("heat_pp", "tpr", "count", "tpr"),
    _l("count", "xvg", "count_plot", "xvg"),
    _l("heat", "traj", "size", "traj"),
    _l("heat_pp", "tpr", "size", "tpr"),
    _l("ice", "index", "size", "index"),
    _l("size", "xvg", "size_plot", "xvg"),
    _l("heat", "edr", "energy", "edr"),
    _l("energy", "xvg", "energy_plot", "xvg"),
    _l("heat", "traj", "watch", "traj"),
    _l("heat_pp", "tpr", "watch", "tpr"),
    _l("ice", "index", "watch", "index"),
]

_ICE_GROUPS = [
    # Building the cube and letting it settle share one box. As two boxes, one
    # above the other, the topology would have had to leave the first box
    # through its right edge on its way to the run and then double back
    # across it to reach the settling step underneath.
    _group("1. An ice cube in empty space", COLOR["build"],
           "ice", "box", "look", "em_mdp", "em_pp", "em",
           # The right edge fills from the bottom up, so this is the reverse
           # of the order the run lists them in, and the lines run straight.
           walls=[_wall("em", "structure", "east", "settled cube"),
                  _wall("ice", "index", "east"),
                  _wall("ice", "topology", "east")]),
    _group("2. Heat it: 200 K to 1000 K", COLOR["production"],
           "heat_mdp", "heat_pp", "heat", "temp", "temp_plot", "count",
           "count_plot", "size", "size_plot", "energy", "energy_plot", "watch",
           "note_heat",
           walls=[_wall("ice", "topology", "west"),
                  _wall("ice", "index", "west"),
                  _wall("em", "structure", "west", "settled cube")]),
]

_ICE_STEPS = [
    {"title": "1. Build the cube", "page": "",
     "nodes": ["ice", "box", "look"],
     "summary": "768 water molecules in the pattern of ordinary ice, put in "
                "the middle of a box of empty space."},
    {"title": "2. Let it settle", "page": "",
     "nodes": ["em_mdp", "em_pp", "em"],
     "summary": "Minimisation: every molecule nudged into place. No time "
                "passes."},
    {"title": "3. Heat it: 200 K to 1000 K", "page": "",
     "nodes": ["heat_mdp", "heat_pp", "heat", "temp", "count", "size",
               "energy", "watch"],
     "summary": "200 ps in one run, the temperature climbing all the way. The "
                "ice melts into a round drop, and the drop boils away into a "
                "gas that fills the box."},
]

TUTORIALS: List[Dict[str, Any]] = [
    {
        "id": "ice_melting",
        "collection": "workshop",
        "number": 1,
        "name": "An ice cube melting",
        "status": "packaged",
        "source": SITE,
        "summary": "A tiny ice cube floating in empty space, heated in one run "
                   "from 200 K, colder than any freezer, to 1000 K: it melts "
                   "into a round drop, and the drop boils away into a gas that "
                   "fills the box. Follow the temperature, count the ice "
                   "molecule by molecule, measure the size of the lump and "
                   "how tightly its molecules hold on, and watch it happen.",
        "requires": [
            "GROMACS",
            "Python with numpy, for counting the ice",
            "nothing to download: the crystal is built by the first block",
        ],
        "runtime": "about 2 and a half minutes on one processor, most of it "
                   "the 200 ps run. Measured in the online copy, limited to "
                   "one processor",
        "measured": "Run here from start to finish in the online copy, on one "
                    "processor, in 2 minutes 24 seconds.\n"
                    "\n"
                    "The crystal: 768 molecules, 6 x 4 x 4 cells, 2.71 x 3.13 x "
                    "2.95 nm, with no overall dipole. 439 of them pass the ice "
                    "test at the start; the rest are on the surface.\n"
                    "\n"
                    "The temperature followed the thermostat: 202 K at the "
                    "start, 303 K at 50 ps, 412 K at 100 ps, 683 K at 150 ps "
                    "and 1017 K at the end.\n"
                    "\n"
                    "Ice: 274 still ice after 1 ps, 224 at 20 ps, 135 at 40 ps, "
                    "56 at 60 ps, and none from 68.5 ps on.\n"
                    "\n"
                    "Size: the radius of gyration went from 1.46 nm to 1.38 nm "
                    "at 73 ps as the cube became a drop, was back above 1.45 nm "
                    "at 105 ps as the drop began to boil away, passed 2.65 nm "
                    "at 160 ps and ended at 2.73 nm, the gas spread through "
                    "the box.\n"
                    "\n"
                    "Energy: the potential energy went from -45,930 to -6,800 "
                    "kJ/mol.",
        "notes": "Written for this version: there is no published tutorial "
                 "behind it, so the notes on the canvas say everything it "
                 "has to say.",
        "steps": _ICE_STEPS,
        # Two columns, each stacked on its own; the first box and the run
        # then stand level with each other.
        "graph": {"nodes": _level_with(_relayout(_ICE_NODES, bands=(4,)),
                                       "heat_mdp", "ice", 4),
                  "links": _ICE_LINKS, "groups": _ICE_GROUPS},
    },
]
