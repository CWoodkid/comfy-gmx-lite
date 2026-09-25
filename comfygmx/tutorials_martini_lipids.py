"""The first Martini 3 tutorial, Lipids I, as a graph.

The tutorial is the Martini team's, at cgmartini.nl. What ships here is a
translation of its command sequence into a Comfy-gmx graph, not a copy of its
prose: each step carries a short summary of our own and a link to the page.
Read the tutorial; run this.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .chunks import COLOR
from .tutorial_graph import (
    group as _group, link as _l, node as _n, note as _note, relayout as _relayout,
)

SITE = "https://cgmartini.nl/docs/tutorials/Martini3/"
AUTHOR = "The Martini team, University of Groningen"
CITATION = (
    "Souza, P. C. T. et al. (2021) Martini 3: a general purpose force field for "
    "coarse-grained molecular dynamics. Nature Methods 18, 382-388. "
    "doi:10.1038/s41592-021-01098-3"
)
LIB = "https://cgmartini-library.s3.ca-central-1.amazonaws.com/"

#: One DSPC molecule, from the Martini 2 lipidome.  The tutorial takes the
#: DPPC structure and renames it: the Martini 3 lipid has the same beads in the
#: same places, only the bonded parameters tell C-16 and C-18 tails apart, and
#: those come from the topology rather than from this file.
LIPID_GRO = LIB + "1_Downloads/ff_parameters/martini2/lipidome/pc/dppc/DPPC-em.gro"
#: A box of equilibrated Martini water, for solvate to copy out of.
WATER_GRO = LIB + "1_Downloads/example_applications/solvent_systems/water.gro"
#: The Martini 3 release: bead definitions and the standard molecule sets.
FF_ZIP = LIB + "1_Downloads/ff_parameters/martini3/martini_v300.zip"
FF_MEMBERS = (
    "martini_v300/martini_v3.0.0.itp\n"
    "martini_v300/martini_v3.0.0_solvents_v1.itp\n"
)
#: The 2025 lipid update, which lives in its own repository rather than in the
#: release above.  Two files out of it are used here; the archive holds the
#: rest, so changing the lipid means changing a name, not fetching again.
LIPID_ZIP = ("https://github.com/Martini-Force-Field-Initiative/"
             "M3-Lipid-Parameters/archive/refs/heads/main.zip")
LIPID_MEMBERS = (
    "M3-Lipid-Parameters-main/ITPs/martini_v3.0.0_ffbonded_v2.itp\n"
    "M3-Lipid-Parameters-main/ITPs/martini_v3.0.0_phospholipids_PC_v2.itp\n"
)
TOP_INCLUDES = (
    "martini_v3.0.0.itp\n"
    "martini_v3.0.0_ffbonded_v2.itp\n"
    "martini_v3.0.0_phospholipids_PC_v2.itp\n"
    "martini_v3.0.0_solvents_v1.itp\n"
)

#: Everything below the run settings is the same in all three files, so it is
#: written once and pasted into each.  These are the tutorial's own numbers.
_COMMON = """
cutoff-scheme            = Verlet
nstlist                  = 20
nsttcouple               = 20
nstpcouple               = 20
rlist                    = 1.35
verlet-buffer-tolerance  = -1
pbc                      = xyz

coulombtype              = reaction-field
rcoulomb                 = 1.1
epsilon_r                = 15
epsilon_rf               = 0
vdw_type                 = cutoff
vdw-modifier             = Potential-shift-verlet
rvdw                     = 1.1

constraints              = none
constraint_algorithm     = Lincs
lincs_order              = 8
lincs_warnangle          = 90
lincs_iter               = 2
"""

_MIN_MDP = """; Minimisation, Martini 3.
; Walk downhill until nothing is pushing hard any more. No time passes.
integrator               = steep
nsteps                   = 10000

nstxout                  = 0
nstvout                  = 0
nstfout                  = 0
""" + _COMMON

_ASSEMBLY_MDP = """; Self-assembly, Martini 3. 30 ns at 20 fs a step.
;
; The pressure is the same in every direction (isotropic), which is right
; while there is no membrane yet -- the box has no special direction to
; treat differently. Once a bilayer has formed this becomes wrong, and the
; next run fixes it.
integrator               = md
dt                       = 0.02
nsteps                   = 1500000

comm-mode                = Linear
nstcomm                  = 100
comm-grps                = System

nstxout                  = 0
nstvout                  = 0
nstfout                  = 0
nstlog                   = 10000
nstenergy                = 1000
nstxout-compressed       = 1000
compressed-x-precision   = 100
""" + _COMMON + """
tcoupl                   = v-rescale
tc-grps                  = System
tau_t                    = 1.0
ref_t                    = 340

gen_vel                  = yes
gen_temp                 = 340
gen_seed                 = 20130607

Pcoupl                   = c-rescale
Pcoupltype               = isotropic
tau_p                    = 4.0
ref_p                    = 1.0
compressibility          = 3e-4
"""

_EQUIL_MDP = """; Equilibration of the bilayer, Martini 3. 10 ns at 20 fs a step: a
; third of the tutorial's 30 ns, so that both runs fit in a lesson. The area
; per lipid drops within the first nanosecond and then keeps drifting slowly
; downwards: 10 ns does not settle it, and the tutorial's 30 ns settles it
; further.
;
; Four things differ from the self-assembly settings, and they are the whole
; exercise on this page of the tutorial:
;
;   Pcoupltype = semi-isotropic. The box may now change its area and its
;     height independently. With one pressure for all three directions a
;     bilayer is squeezed or stretched sideways by whatever the height is
;     doing, and its area per lipid settles at the wrong value.
;
;   tc-grps = DSPC W, two thermostats instead of one. Heat crosses the
;     membrane-water boundary slowly, so with a single thermostat one side
;     can sit warm while the other sits cold and the average looks right.
;
;   comm-grps = DSPC W, likewise. The membrane can drift sideways against
;     the water; correcting the whole box as one hides that.
;
;   gen_vel = no, continuation = yes. The velocities come from the run
;     before -- through the structure file, which carries them -- rather
;     than being drawn fresh.
integrator               = md
dt                       = 0.02
nsteps                   = 500000

comm-mode                = Linear
nstcomm                  = 100
comm-grps                = DSPC W

nstxout                  = 0
nstvout                  = 0
nstfout                  = 0
nstlog                   = 10000
nstenergy                = 1000
nstxout-compressed       = 1000
compressed-x-precision   = 100
""" + _COMMON + """
tcoupl                   = v-rescale
tc-grps                  = DSPC W
tau_t                    = 1.0 1.0
ref_t                    = 340 340

gen_vel                  = no
continuation             = yes

Pcoupl                   = c-rescale
Pcoupltype               = semi-isotropic
tau_p                    = 4.0
ref_p                    = 1.0 1.0
compressibility          = 3e-4 3e-4
"""

_LI_NODES: List[Dict[str, Any]] = [
    _note("note_what", 0, 0,
          "A bilayer that builds itself\n"
          "\n"
          "128 lipids are dropped into a box at random, water is poured in around\n"
          "them, and then nothing else is done. Over the next 30 nanoseconds they\n"
          "find each other, tails inward, heads out, and a membrane appears.\n"
          "\n"
          "That is worth watching once, because it is the clearest demonstration in\n"
          "the whole Martini set that the model is doing physics rather than being\n"
          "told the answer. Nobody says 'make a bilayer'. The tails dislike water,\n"
          "the heads like it, and a bilayer is what that adds up to.\n"
          "\n"
          "It is also not guaranteed. Sometimes you get a micelle that never opens\n"
          "out, or a bilayer with a water pore through it. Both are real\n"
          "intermediates and worth seeing. If it happens, run it again -- the\n"
          "starting arrangement is random. And the bilayer forms facing whichever\n"
          "way chance picks -- usually not flat. 'Turn the membrane flat' checks,\n"
          "and turns it, as the tutorial says to.\n"
          "\n"
          "After that comes a second run with three settings changed, and those\n"
          "three changes are the real lesson of the page. The note by the second\n"
          "set of run settings says what they are and why each one matters."),

    # ---- 1. a box of loose lipids ------------------------------------
    _n("lipid", "io.fetch_url", 1, 0, url=LIPID_GRO, output="DSPC-em.gro",
       extract=False),
    _n("rename", "util.edit_text", 2, -0.6, rules="replace: DPPC => DSPC",
       output="lipid.gro"),
    _note("note_scatter", 2, 0,
          "1. THROW THEM IN AND SEE\n"
          "\n"
          "One lipid, copied 128 times into a 7.5 nm box at random positions and\n"
          "random angles, each copy rejected and retried if it lands on top of one\n"
          "already there.\n"
          "\n"
          "'How close is too close' is 0.21 nm here, not the 0.105 nm GROMACS uses\n"
          "by default. That default is an atom's radius; a Martini bead stands for\n"
          "about four heavy atoms and is roughly twice as wide. Leave it at the\n"
          "default and the lipids are packed far too tightly to minimise.\n"
          "\n"
          "The structure is the Martini 2 DPPC one, saved under the name DSPC. The\n"
          "two have the same beads in the same places; what tells a C-16 tail from a\n"
          "C-18 tail in Martini 3 is in the topology, not in the coordinates."),
    _n("scatter", "gmx.insert_molecules", 3, 0, nmol=128, box="7.5 7.5 7.5",
       radius=0.21, try_count=500, output="128_noW.gro"),

    _n("water", "io.fetch_url", 1, 1, url=WATER_GRO, output="water.gro",
       extract=False),
    _note("note_water", 2, 1,
          "2. NOT VERY MUCH WATER\n"
          "\n"
          "768 water beads, which is six per lipid. One Martini water bead stands\n"
          "for four real ones, so that is 24 real waters a lipid -- thin. A real\n"
          "membrane simulation would use several times more.\n"
          "\n"
          "It is deliberate. With little water the lipids cannot get far from each\n"
          "other, and a bilayer forms more reliably and sooner. It also means part\n"
          "of the box starts out with no water in it at all, which is not realistic.\n"
          "\n"
          "Worth trying: raise 'Most solvent molecules' and see whether you still\n"
          "get a bilayer in 30 ns, or a micelle instead.\n"
          "\n"
          "The same 0.21 nm bead size is used again, so water is not poured into\n"
          "gaps a Martini bead could not actually fit into."),
    _n("wet", "gmx.solvate", 4, 1, maxsol=768, radius=0.21,
       output="waterbox.gro"),

    # ---- 2. the topology ---------------------------------------------
    _note("note_top", 0, 2,
          "3. WHAT THE MOLECULES ARE\n"
          "\n"
          "Four files, and the order they go in matters.\n"
          "\n"
          "  martini_v3.0.0.itp                    what every bead type is\n"
          "  martini_v3.0.0_ffbonded_v2.itp        how lipid bonds behave\n"
          "  martini_v3.0.0_phospholipids_PC_v2.itp  the lipids themselves\n"
          "  martini_v3.0.0_solvents_v1.itp        water\n"
          "\n"
          "Bead types first, because everything below refers to them. General bond\n"
          "behaviour before the specific lipids that use it.\n"
          "\n"
          "The lipid files come from a separate place from the rest: the 2025 lipid\n"
          "update lives in its own repository and is not in the Martini 3 release\n"
          "archive. Both are downloaded here.\n"
          "\n"
          "The counts -- 128 lipids, however many waters solvate managed to fit --\n"
          "are read off the structure rather than typed. The tutorial asks you to\n"
          "scroll back through the solvate output and find the number by eye."),
    _n("ff", "io.fetch_url", 1, 2, url=FF_ZIP, output="martini_v300.zip",
       extract=True, member=FF_MEMBERS),
    _n("lipid_itp", "io.fetch_url", 1, 3, url=LIPID_ZIP,
       output="m3-lipids.zip", extract=True, member=LIPID_MEMBERS),
    _n("top", "martini.merge_top", 3, 2, defines="", includes="",
       itp_files=TOP_INCLUDES, system_name="DSPC bilayer self-assembly",
       molecules="DSPC @DSPC\nW @W\n", output="dspc.top"),

    # ---- 3. minimise, then let it assemble ---------------------------
    _n("min_mdp", "util.mdp", 4, 3, mode="raw", raw=_MIN_MDP,
       filename="minimization.mdp"),
    _n("min_pp", "gmx.grompp", 5, 3, maxwarn=1, output="min.tpr"),
    _n("min", "gmx.mdrun", 6, 3, deffnm="minimized"),

    _n("sa_mdp", "util.mdp", 4, 4, mode="raw", raw=_ASSEMBLY_MDP,
       filename="martini_md.mdp"),
    _n("sa_pp", "gmx.grompp", 5, 4, maxwarn=1, output="dspc-md.tpr"),
    _n("sa", "gmx.mdrun", 6, 4, deffnm="dspc-md"),
    _n("flat", "build.lay_flat", 7, 4, beads="PO4", output="dspc-flat.gro"),

    # ---- 4. the same bilayer, allowed to find its own area -----------
    _note("note_equil", 0, 5,
          "4. THE THREE SETTINGS THAT MATTER\n"
          "\n"
          "The run above used one pressure for all three directions, which was right\n"
          "while there was no membrane. Now there is one, and a membrane has a\n"
          "direction: it is a sheet in the xy plane with water above and below --\n"
          "turned that way, if it formed standing up, by the block just before.\n"
          "\n"
          "SEMI-ISOTROPIC PRESSURE lets the area of the sheet and the height of the\n"
          "box change independently. Keep them tied together and the membrane is\n"
          "stretched or squeezed sideways by whatever the water column is doing, and\n"
          "the area per lipid -- the number everyone quotes -- comes out wrong.\n"
          "\n"
          "TWO THERMOSTATS, one for the lipids and one for the water. Heat crosses\n"
          "the boundary between them slowly. With a single thermostat the water can\n"
          "sit too warm and the membrane too cold while the average looks perfect.\n"
          "\n"
          "TWO DRIFT GROUPS, for the same reason: the membrane can slide sideways\n"
          "against the water, and correcting the box as a whole hides it.\n"
          "\n"
          "Read the settings on the node -- all three are near the bottom, and the\n"
          "comments in the file say the same as this note. Comparing it against the\n"
          "self-assembly settings above is the exercise the tutorial sets.\n"
          "\n"
          "This run is 10 ns, a third of the tutorial's 30, so that both runs fit\n"
          "in a lesson. The area per lipid drops within the first nanosecond and\n"
          "then keeps drifting slowly downwards: 10 ns does not settle it, which\n"
          "is worth saying whenever the number is quoted."),
    _n("eq_mdp", "util.mdp", 4, 5, mode="raw", raw=_EQUIL_MDP,
       filename="equilibration.mdp"),
    _n("eq_ndx", "gmx.make_ndx", 4, 6, commands="q\n", output="index.ndx"),
    _n("eq_pp", "gmx.grompp", 5, 5, maxwarn=2, output="equil.tpr"),
    _n("eq", "gmx.mdrun", 6, 5, deffnm="equil"),

    # ---- 5. is it a membrane, and what is it like ---------------------
    _note("note_read", 0, 7,
          "5. THREE THINGS TO MEASURE\n"
          "\n"
          "DENSITY ALONG Z is the check that it worked. A bilayer gives water high\n"
          "at both ends, a deep trough in the middle where the tails are, and the\n"
          "whole thing symmetric about the centre. One flat line means no membrane.\n"
          "Two humps and no trough means a micelle.\n"
          "\n"
          "AREA PER LIPID is the number to compare against experiment: the area of\n"
          "the box divided by half the lipids, since there are two leaflets. DSPC in\n"
          "the fluid phase is about 0.65 nm2. Look at the curve as well as the\n"
          "average -- the part at the start where it is still shrinking has not\n"
          "equilibrated and should be left out.\n"
          "\n"
          "HOW FAR A LIPID WANDERS, in the plane only. A lipid does not cross to the\n"
          "other leaflet on this timescale, so counting the z direction would halve\n"
          "the answer for no reason. The trajectory has to be unwrapped first, or a\n"
          "lipid that leaves one side of the box and comes back on the other looks\n"
          "as though it moved a whole box length in one step."),
    _n("centre", "gmx.trjconv", 7, 7, pbc="whole", ur="compact", center=False,
       groups="System\n", output="whole.xtc"),
    _n("dens", "gmx.density", 8, 7, d="Z", sl=100, center=True,
       groups="DSPC\nSystem\n", output="density.xvg"),

    _n("boxsize", "gmx.energy", 7, 8, terms="Box-X\nBox-Y\n",
       output="box-xy.xvg"),
    _n("area", "analysis.area_per_lipid", 8, 8, lipids=128, expected=0.65,
       expected_label="DSPC in the fluid phase, from experiment",
       output="area_per_lipid.xvg"),

    _n("nojump", "gmx.trjconv", 7, 9, pbc="nojump", ur="", center=False,
       groups="System\n", output="nojump.xtc"),
    _n("msd", "gmx.msd", 8, 9, lateral="z", trestart=200.0,
       groups="DSPC\n", output="msd.xvg"),
]

_LI_LINKS = [
    _l("lipid", "file", "rename", "file"),
    _l("rename", "out", "scatter", "insert"),
    _l("scatter", "structure", "wet", "structure"),
    _l("water", "file", "wet", "solvent_box"),

    _l("ff", "file", "top", "ff"),
    _l("lipid_itp", "file", "top", "itp"),
    _l("wet", "structure", "top", "structure"),

    _l("wet", "structure", "min_pp", "structure"),
    _l("top", "topology", "min_pp", "topology"),
    _l("min_mdp", "mdp", "min_pp", "mdp"),
    _l("min_pp", "tpr", "min", "tpr"),

    _l("min", "structure", "sa_pp", "structure"),
    _l("top", "topology", "sa_pp", "topology"),
    _l("sa_mdp", "mdp", "sa_pp", "mdp"),
    _l("sa_pp", "tpr", "sa", "tpr"),

    _l("sa", "structure", "flat", "structure"),
    _l("flat", "structure", "eq_ndx", "structure"),
    _l("flat", "structure", "eq_pp", "structure"),
    _l("top", "topology", "eq_pp", "topology"),
    _l("eq_mdp", "mdp", "eq_pp", "mdp"),
    _l("eq_ndx", "index", "eq_pp", "index"),
    _l("eq_pp", "tpr", "eq", "tpr"),

    _l("eq", "traj", "centre", "traj"),
    _l("eq_pp", "tpr", "centre", "tpr"),
    _l("centre", "traj", "dens", "traj"),
    _l("eq_pp", "tpr", "dens", "tpr"),
    _l("eq_ndx", "index", "dens", "index"),

    _l("eq", "edr", "boxsize", "edr"),
    _l("boxsize", "xvg", "area", "xvg"),

    _l("eq", "traj", "nojump", "traj"),
    _l("eq_pp", "tpr", "nojump", "tpr"),
    _l("nojump", "traj", "msd", "traj"),
    _l("eq_pp", "tpr", "msd", "tpr"),
    _l("eq_ndx", "index", "msd", "index"),
]

_LI_GROUPS = [
    _group("1. Lipids and water in a box", COLOR["build"],
           "lipid", "rename", "scatter", "water", "wet"),
    _group("2. What the molecules are", COLOR["params"],
           "ff", "lipid_itp", "top"),
    _group("3. Minimise, then let it assemble", COLOR["production"],
           "min_mdp", "min_pp", "min", "sa_mdp", "sa_pp", "sa", "flat"),
    _group("4. Let the membrane find its own area", COLOR["equilibrate"],
           "eq_mdp", "eq_ndx", "eq_pp", "eq"),
    _group("5. Is it a membrane, and what is it like", COLOR["analysis"],
           "centre", "dens", "boxsize", "area", "nojump", "msd"),
]

_LI_STEPS = [
    {"title": "1. 128 lipids, thrown in at random",
     "page": "LipidsI/index.html",
     "nodes": ["lipid", "rename", "scatter", "water", "wet"],
     "summary": "One lipid structure copied 128 times into a 7.5 nm box at "
                "random positions and angles, then water poured around it. "
                "Both steps use 0.21 nm as the bead size rather than the "
                "atomic default of 0.105, because a Martini bead stands for "
                "about four heavy atoms."},
    {"title": "2. The topology",
     "page": "LipidsI/index.html",
     "nodes": ["ff", "lipid_itp", "top"],
     "summary": "Four .itp files in a fixed order -- bead types, general "
                "lipid bonds, the lipid itself, water. The 2025 lipid update "
                "lives in a separate repository from the Martini 3 release, "
                "so both are downloaded. The molecule counts are read off the "
                "structure rather than typed in."},
    {"title": "3. Minimise, then 30 ns and see what happens",
     "page": "LipidsI/index.html",
     "nodes": ["min_mdp", "min_pp", "min", "sa_mdp", "sa_pp", "sa", "flat"],
     "summary": "Nothing tells the lipids to make a bilayer. The tails "
                "dislike water and the heads like it, and over 30 ns that is "
                "usually enough. It does not always work: a micelle or a "
                "membrane with a hole in it are both real outcomes, and both "
                "worth looking at. The bilayer faces whichever way chance "
                "picks; the tutorial says to turn it flat if it is not, and "
                "the last block here does that."},
    {"title": "4. The same bilayer, on the right settings, for 10 ns",
     "page": "LipidsI/index.html",
     "nodes": ["eq_mdp", "eq_ndx", "eq_pp", "eq"],
     "summary": "Three changes: pressure that treats the plane of the "
                "membrane separately from the direction across it, a "
                "thermostat each for lipids and water, and drift corrected "
                "for each of them separately. Comparing the two files is the "
                "exercise the page sets."},
    {"title": "5. Measure it",
     "page": "LipidsI/index.html",
     "nodes": ["centre", "dens", "boxsize", "area", "nojump", "msd"],
     "summary": "The density across the box says whether it is a membrane at "
                "all. The area per lipid is the number to compare against "
                "experiment. How far a lipid wanders in the plane is its "
                "diffusion, and needs an unwrapped trajectory or the answer "
                "is nonsense."},
]


TUTORIALS: List[Dict[str, Any]] = [
    {
        "id": "martini3_lipids_i",
        "collection": "martini",
        "number": 1,
        "name": "Lipids I: a bilayer that builds itself",
        "source": SITE + "LipidsI/index.html",
        "base": SITE,
        "summary": "Drop lipids into a box at random, add water, and watch a "
                   "bilayer form on its own -- then measure it: the density "
                   "across the membrane, the area each lipid takes up, and how "
                   "far a lipid wanders in the plane.",
        "status": "packaged",
        "requires": [
            "GROMACS",
            "network access: the graph downloads one lipid structure, a box of "
            "Martini water, the Martini 3 release and the 2025 lipid update",
            "Python with numpy, for the area per lipid",
            "no membrane builder at all -- the lipids are placed by "
            "gmx insert-molecules and find their own way",
        ],
        "runtime": "about 11 minutes on one processor: 8 minutes for the 30 ns "
                   "of self-assembly (about 5,400 ns a day) and under 3 for the "
                   "10 ns after it. Measured in the online copy, limited to one "
                   "processor",
        "measured": "Run here from start to finish in the online copy, on one "
                    "processor.\n"
                    "\n"
                    "128 lipids went in on the first try and 768 waters after "
                    "them, exactly the six per lipid asked for. Minimisation "
                    "reached -3.56e4 kJ/mol.\n"
                    "\n"
                    "A bilayer formed, facing along y, and 'Turn the membrane "
                    "flat' turned it into the xy plane before the second run. "
                    "The density profile, centred on the lipids, shows it as "
                    "two headgroup peaks at plus and minus 1.4 nm with a lower "
                    "middle between them.\n"
                    "\n"
                    "Area per lipid: 0.641 nm2 at the start of the second run, "
                    "0.602 on average over its 10 ns and 0.593 over the second "
                    "half, ending in a 6.09 nm square box. Lateral diffusion of "
                    "the lipids, 0.07 x 1e-5 cm2/s.\n"
                    "\n"
                    "Two cautions on those numbers. Martini runs faster than "
                    "reality by roughly a factor of four, so a diffusion "
                    "coefficient from it is not directly comparable to "
                    "experiment. And 10 ns is short for an area per lipid; the "
                    "curve is still drifting slowly downwards at the end.",
        "notes": "The one tutorial in the set that builds a membrane without a "
                 "builder. The self-assembly is the tutorial's own 1.5 million "
                 "steps at 20 fs; the second run is 10 ns, a third of the "
                 "tutorial's, so that both fit in a lesson.\n"
                 "\n"
                 "Self-assembly is not guaranteed in 30 ns: of 8 test runs here, "
                 "7 had formed a bilayer at 30 ns, and the eighth had by 60. If "
                 "what comes out is a micelle, or a bilayer with a water pore "
                 "through it, that is a real outcome and worth looking at -- "
                 "then run it again, since the starting arrangement is random. "
                 "A bilayer that formed standing up is turned flat by the block "
                 "before the second run. The tutorial provides a ready-made "
                 "bilayer for anyone who would rather not wait.",
        "steps": _LI_STEPS,
        "graph": {"nodes": _relayout(_LI_NODES), "links": _LI_LINKS,
                  "groups": _LI_GROUPS},
    },
]
