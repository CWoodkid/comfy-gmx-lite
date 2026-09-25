"""An ice cube melting: a tutorial written for this version.

Not a translation of a published course, unlike the other two. A small cube
of ice floats in empty space and is simulated twice, at room temperature and
at a temperature colder than any freezer. In the warm run the crystal falls
apart within a few tens of picoseconds and pulls itself into a round drop; in
the cold one it holds. Three measurements say the same thing in numbers: how
many molecules are still part of the ice, how big the lump is, and what it
looks like.

The whole of it runs in a few minutes on one processor, which is the point:
it was made for a class, where there are fifteen minutes and one processor
each.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .chunks import COLOR
from .tutorial_graph import (
    group as _group, link as _l, node as _n, note as _note, relayout as _relayout,
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


def _melt_mdp(kelvin: int, what: str) -> str:
    celsius = kelvin - 273
    return f"""; The ice cube at {kelvin} K, which is {celsius} degrees C: {what}.
;
; To try another temperature, change ref_t and gen_temp below -- both of
; them, to the same number -- and press Run again.
integrator           = md
dt                   = 0.002     ; one step is 2 femtoseconds (0.002 ps)
nsteps               = 50000     ; 50,000 steps: 100 picoseconds

nstxout-compressed   = 250       ; save a picture every 250 steps (0.5 ps)
nstenergy            = 500       ; and the energies, every 1 ps
nstlog               = 5000

cutoff-scheme        = Verlet
coulombtype          = PME
rcoulomb             = 1.0
vdwtype              = cut-off
rvdw                 = 1.0
pbc                  = xyz

; The thermostat: it keeps the temperature at ref_t, by speeding the
; molecules up or slowing them down a little at every step.
tcoupl               = v-rescale
tc-grps              = System
tau_t                = 0.1       ; how quickly it corrects, in ps
ref_t                = {kelvin}

; Give every molecule a speed to start with, picked at random the way
; speeds are spread at this temperature.
gen_vel              = yes
gen_temp             = {kelvin}
gen_seed             = 2026

; No pressure control: around the cube there is nothing but empty space.
pcoupl               = no

; Keep the cube in the middle of the picture: take away any drift and any
; spin it picks up. Safe only for a single lump that never touches the edge
; of the box -- which is what this is, and why grompp warns about it and is
; allowed one warning.
comm-mode            = angular
"""


_ICE_NODES: List[Dict[str, Any]] = [
    _note("note_what", 0, 0,
          "AN ICE CUBE MELTING\n"
          "\n"
          "Ice is water whose molecules have stopped tumbling past each other\n"
          "and locked into a pattern. Every molecule holds on to four\n"
          "neighbours, and together they make a honeycomb of six-sided rings.\n"
          "Melting is that pattern breaking up.\n"
          "\n"
          "Here you build a tiny ice cube -- 768 water molecules, 3 nanometres\n"
          "across; ten million of them side by side would make one cube for a\n"
          "drink -- let it float in empty space, and see what heat does to it.\n"
          "Twice: once at room temperature, once colder than any freezer.\n"
          "\n"
          "Press Run. Everything takes a few minutes; read the notes while it\n"
          "works."),

    # ---- 1. the cube --------------------------------------------------------
    _note("note_build", 0, 1,
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
          "be big enough that the cube never feels the copy of itself next door."),
    _n("ice", "build.ice", 1, 1, cells_x=6, cells_y=4, cells_z=4, seed=1),
    _n("box", "gmx.editconf", 2, 1, box_type="cubic", box="5.5 5.5 5.5",
       center=True, output="cube.gro"),
    _n("look", "view.structure", 3, 1),

    # ---- 2. settle ----------------------------------------------------------
    _n("em_mdp", "util.mdp", 1, 2, mode="raw", raw=_MIN_MDP,
       filename="minimise.mdp"),
    _n("em_pp", "gmx.grompp", 2, 2, output="em.tpr"),
    _n("em", "gmx.mdrun", 3, 2, deffnm="em"),

    # ---- 3. warm ------------------------------------------------------------
    _note("note_warm", 0, 3,
          "2. WARM: 300 K, 27 DEGREES C\n"
          "\n"
          "Every molecule is given a speed that matches 300 K, and a thermostat\n"
          "keeps it there. Then 100 picoseconds pass: 50,000 steps of 2\n"
          "femtoseconds each. A femtosecond is a millionth of a billionth of a\n"
          "second.\n"
          "\n"
          "What happens: the corners go first, then the edges, then the faces\n"
          "-- melting starts at the surface. Within about 30 ps the honeycomb\n"
          "is gone, and the liquid pulls itself into a round drop. Why round:\n"
          "surface tension. A ball is the shape with the least surface.\n"
          "\n"
          "grompp warns once about stopping the cube from spinning. That is\n"
          "expected, and allowed: see the last lines of the run settings."),
    _n("warm_mdp", "util.mdp", 1, 3, mode="raw",
       raw=_melt_mdp(300, "room temperature"), filename="warm.mdp"),
    _n("warm_pp", "gmx.grompp", 2, 3, maxwarn=1, output="warm.tpr"),
    _n("warm", "gmx.mdrun", 3, 3, deffnm="warm"),
    _n("warm_count", "analysis.ice_count", 4, 3, output="ice_warm.xvg"),
    _n("warm_count_plot", "view.plot", 5, 3),
    _n("warm_size", "gmx.gyrate", 4, 4, sel="Oxygens", tu="ps",
       output="size_warm.xvg"),
    _n("warm_size_plot", "view.plot", 5, 4),
    _n("warm_watch", "view.trajectory", 6, 3, mode="every Nth", skip=2,
       sel="Oxygens", pbc="mol", center=True),

    # ---- 4. cold ------------------------------------------------------------
    _note("note_cold", 0, 5,
          "3. COLD: 200 K, MINUS 73 DEGREES C\n"
          "\n"
          "The same cube and the same settings, except the temperature. 200 K\n"
          "is colder than any freezer: about as cold as the coldest nights in\n"
          "Antarctica. The molecules shiver in place, but the honeycomb holds.\n"
          "\n"
          "The outermost layer does loosen a little. The surface of ice is\n"
          "slightly wet even well below freezing, which is part of why ice is\n"
          "slippery.\n"
          "\n"
          "Try it: set ref_t and gen_temp in the cold run's settings to 250\n"
          "(minus 23 degrees C) and run it again. Tiny crystals melt at lower\n"
          "temperatures than big ones, so this cube starts to melt even there\n"
          "-- slowly."),
    _n("cold_mdp", "util.mdp", 1, 5, mode="raw",
       raw=_melt_mdp(200, "colder than any freezer"), filename="cold.mdp"),
    _n("cold_pp", "gmx.grompp", 2, 5, maxwarn=1, output="cold.tpr"),
    _n("cold", "gmx.mdrun", 3, 5, deffnm="cold"),
    _n("cold_count", "analysis.ice_count", 4, 5, output="ice_cold.xvg"),
    _n("cold_count_plot", "view.plot", 5, 5),
    _n("cold_size", "gmx.gyrate", 4, 6, sel="Oxygens", tu="ps",
       output="size_cold.xvg"),
    _n("cold_size_plot", "view.plot", 5, 6),
    _n("cold_watch", "view.trajectory", 6, 5, mode="every Nth", skip=2,
       sel="Oxygens", pbc="mol", center=True),

    # ---- 5. reading it ------------------------------------------------------
    _note("note_read", 7, 3,
          "4. WHAT THE THREE PICTURES SAY\n"
          "\n"
          "COUNT THE ICE: how many molecules still sit in the honeycomb, frame\n"
          "by frame. It starts well below 768, because a molecule on the\n"
          "surface has too few neighbours to pass the test. Within half a\n"
          "picosecond it drops in both runs: once the molecules shiver, some\n"
          "fail the strict test even though the crystal is still there. After\n"
          "that, the cold line stays nearly flat and the warm line falls to\n"
          "zero. That fall is the melting.\n"
          "\n"
          "SIZE: the radius of gyration, roughly how far the molecules are\n"
          "from the middle, on average. The warm one shrinks, for two reasons:\n"
          "a ball is more compact than a cube, and liquid water packs its\n"
          "molecules closer together than ice does. That is why ice floats,\n"
          "and why a full bottle of water bursts in a freezer.\n"
          "\n"
          "THE MOVIE: one dot per molecule, its oxygen. Press play; drag to\n"
          "turn it. Look straight down the z axis of the cold cube to see the\n"
          "six-sided channels running through the ice."),
]

_ICE_LINKS: List[Dict[str, str]] = [
    _l("ice", "structure", "box", "structure"),
    _l("box", "structure", "look", "structure"),

    _l("em_mdp", "mdp", "em_pp", "mdp"),
    _l("box", "structure", "em_pp", "structure"),
    _l("ice", "topology", "em_pp", "topology"),
    _l("em_pp", "tpr", "em", "tpr"),

    _l("warm_mdp", "mdp", "warm_pp", "mdp"),
    _l("em", "structure", "warm_pp", "structure"),
    _l("ice", "topology", "warm_pp", "topology"),
    _l("warm_pp", "tpr", "warm", "tpr"),
    _l("warm", "traj", "warm_count", "traj"),
    _l("warm_pp", "tpr", "warm_count", "tpr"),
    _l("warm_count", "xvg", "warm_count_plot", "xvg"),
    _l("warm", "traj", "warm_size", "traj"),
    _l("warm_pp", "tpr", "warm_size", "tpr"),
    _l("ice", "index", "warm_size", "index"),
    _l("warm_size", "xvg", "warm_size_plot", "xvg"),
    _l("warm", "traj", "warm_watch", "traj"),
    _l("warm_pp", "tpr", "warm_watch", "tpr"),
    _l("ice", "index", "warm_watch", "index"),

    _l("cold_mdp", "mdp", "cold_pp", "mdp"),
    _l("em", "structure", "cold_pp", "structure"),
    _l("ice", "topology", "cold_pp", "topology"),
    _l("cold_pp", "tpr", "cold", "tpr"),
    _l("cold", "traj", "cold_count", "traj"),
    _l("cold_pp", "tpr", "cold_count", "tpr"),
    _l("cold_count", "xvg", "cold_count_plot", "xvg"),
    _l("cold", "traj", "cold_size", "traj"),
    _l("cold_pp", "tpr", "cold_size", "tpr"),
    _l("ice", "index", "cold_size", "index"),
    _l("cold_size", "xvg", "cold_size_plot", "xvg"),
    _l("cold", "traj", "cold_watch", "traj"),
    _l("cold_pp", "tpr", "cold_watch", "tpr"),
    _l("ice", "index", "cold_watch", "index"),
]

_ICE_GROUPS = [
    _group("1. An ice cube in empty space", COLOR["build"], "ice", "box", "look"),
    _group("Let it settle", COLOR["minimise"], "em_mdp", "em_pp", "em"),
    _group("2. Warm: 300 K", COLOR["production"],
           "warm_mdp", "warm_pp", "warm", "warm_count", "warm_count_plot",
           "warm_size", "warm_size_plot", "warm_watch"),
    _group("3. Cold: 200 K", COLOR["equilibrate"],
           "cold_mdp", "cold_pp", "cold", "cold_count", "cold_count_plot",
           "cold_size", "cold_size_plot", "cold_watch"),
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
    {"title": "3. Warm it: 300 K", "page": "",
     "nodes": ["warm_mdp", "warm_pp", "warm", "warm_count", "warm_size",
               "warm_watch"],
     "summary": "100 ps at room temperature. The crystal falls apart from the "
                "surface inwards and becomes a round drop."},
    {"title": "4. Freeze it: 200 K", "page": "",
     "nodes": ["cold_mdp", "cold_pp", "cold", "cold_count", "cold_size",
               "cold_watch"],
     "summary": "The same, colder than any freezer. The honeycomb holds."},
]

TUTORIALS: List[Dict[str, Any]] = [
    {
        "id": "ice_melting",
        "collection": "workshop",
        "number": 1,
        "name": "An ice cube melting",
        "status": "packaged",
        "source": SITE,
        "summary": "A tiny ice cube floating in empty space, simulated twice: "
                   "at room temperature it melts into a round drop within a "
                   "few tens of picoseconds; colder than any freezer, it "
                   "holds. Count the ice molecule by molecule, measure the "
                   "size of the lump, and watch it happen.",
        "requires": [
            "GROMACS",
            "Python with numpy, for counting the ice",
            "nothing to download: the crystal is built by the first block",
        ],
        "runtime": "about 3 minutes on one processor: each of the two 100 ps "
                   "runs takes a little over a minute. Measured in the online "
                   "copy, limited to one processor",
        "measured": "Run here from start to finish in the online copy, on one "
                    "processor, in 2 minutes 48 seconds.\n"
                    "\n"
                    "The crystal: 768 molecules, 6 x 4 x 4 cells, 2.71 x 3.13 x "
                    "2.95 nm, with no overall dipole. 442 of them pass the ice "
                    "test at the start; the rest are on the surface.\n"
                    "\n"
                    "Warm, 300 K: 180 still ice after 1 ps, 105 at 10 ps, 15 at "
                    "30 ps and none from 40 ps on. The radius of gyration went "
                    "from 1.46 to 1.38 nm as the cube became a drop.\n"
                    "\n"
                    "Cold, 200 K: 270 still ice after 1 ps; then about 250 on "
                    "average over the first 50 ps and 240 over the second, going "
                    "up and down by 20 or 30 from frame to frame. The radius of gyration "
                    "went from 1.46 to 1.42 nm: the surface loosens a little, "
                    "the honeycomb holds.",
        "notes": "Written for this version: there is no published tutorial "
                 "behind it, so the notes on the canvas say everything it "
                 "has to say.",
        "steps": _ICE_STEPS,
        "graph": {"nodes": _relayout(_ICE_NODES), "links": _ICE_LINKS,
                  "groups": _ICE_GROUPS},
    },
]
