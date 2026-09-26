"""The tutorials this version ships, as runnable graphs.

One is a published course rebuilt as a graph: Lysozyme in Water, the first
of Justin A. Lemkul's GROMACS tutorials (http://www.mdtutorials.com/gmx/).
What is packaged is a *translation* of the tutorial's command sequence into a
Comfy-gmx graph, together with the parameter files the tutorial publishes.
The explanatory prose on that site is the author's and is not reproduced:
each step carries a short summary of our own plus a link to the page it came
from, so the tutorial stays the thing you read and this stays the thing you
run.

The other, an ice cube melting, was written for this version and has no
published page behind it; its notes say everything it has to say.

If you use one of these, cite the tutorial it came from -- see
:data:`COLLECTIONS`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .chunks import COLOR
from .tutorial_graph import (
    group as _group, level_with as _level_with, link as _l, node as _n,
    note as _note, relayout as _relayout, space_boxes as _space_boxes,
    untangle_groups as _untangle_groups, wall as _wall,
)
from .tutorials_ice import (
    AUTHOR as ICE_AUTHOR,
    CITATION as ICE_CITATION,
    SITE as ICE_SITE,
    TUTORIALS as _ICE_TUTORIALS,
)

AUTHOR = "Justin A. Lemkul, Ph.D. - Virginia Tech, Department of Biochemistry"
SITE = "http://www.mdtutorials.com/gmx/"
CITATION = (
    "Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of "
    "Tutorials for the GROMACS-2018 Molecular Simulation Package. "
    "Living J. Comput. Mol. Sci. 1(1), 5068. doi:10.33011/livecoms.1.1.5068"
)

#: Tutorial collection -> where it comes from and who to cite. A tutorial's
#: ``collection`` key selects one of these; the UI groups the palette by it.
COLLECTIONS: Dict[str, Dict[str, str]] = {
    "gmx": {
        "id": "gmx",
        "name": "GROMACS",
        "label": "mdtutorials.com/gmx",
        "site": SITE,
        "author": AUTHOR,
        "citation": CITATION,
    },
    "workshop": {
        "id": "workshop",
        "name": "Made for this workshop",
        "label": "made for Comfy-gmx lite",
        "site": ICE_SITE,
        "author": ICE_AUTHOR,
        "citation": ICE_CITATION,
    },
}

# --------------------------------------------------------------------------
# Tutorial 1 -- Lysozyme in Water
# --------------------------------------------------------------------------

_LYSOZYME_NODES: List[Dict[str, Any]] = [
    # The page reads in three columns. On the left, the protein is prepared:
    # topology, box and water, ions. In the middle, the four runs, one below
    # the other. On the right, the analysis, beside the production run it
    # reads.
    #
    # Every file that goes from one box to another leaves its box through a
    # dot on the right-hand wall and enters the next box through a dot on the
    # left-hand wall, with a short name written beside each dot. Between two
    # boxes stacked one above the other the wire swings round through the gap,
    # so the boxes in a column stand well apart (see space_boxes below). The
    # notes for the runs sit inside their boxes, under grompp and mdrun, where
    # no wire has to pass.

    # ---- steps 1-2: structure and topology -------------------------------
    _note("note_setup", 0, 0,
          "STEPS 1-2 - Topology\n"
          "1AKI is hen egg white lysozyme. The crystal waters are stripped before "
          "pdb2gmx; keeping them would be right only if one were functional.\n\n"
          "The tutorial uses CHARMM36, which GROMACS does not ship. Point the "
          "'Force field directory' node at your unpacked *.ff folder, or delete that "
          "node and pick a bundled force field on pdb2gmx instead.\n\n"
          "Point at any socket to see what kind of file goes through it; Help "
          "(the ? at the top) lists them all."),
    # Fetched rather than left blank. The tutorial does use CHARMM36 and does
    # tell you to get it from the MacKerell lab -- but shipping an empty path
    # meant the first node of the first tutorial failed with "no force field
    # directory given", which is a poor way to meet somebody. The node can
    # download and unpack an archive, and this is the archive.
    _n("ff", "gmx.forcefield", 0, 1, source="archive URL",
       url="http://mackerell.umaryland.edu/download.php"
           "?filename=CHARMM_ff_params_files/charmm36-jul2022.ff.tgz",
       name="charmm36-jul2022"),
    _n("fetch", "io.structure", 1, 1, source="the Protein Data Bank",
       pdb_id="1aki", format="pdb"),
    _n("clean", "prep.clean", 2, 1,
       drop_water=True, drop_hetero=False, first_model=True, first_altloc=True,
       renumber=False, output="1AKI_clean.pdb"),
    _n("top", "gmx.pdb2gmx", 3, 1,
       forcefield="charmm36-jul2022", water="tip3p", ignh=False,
       output="1AKI_processed.gro"),

    # ---- step 3: box and solvent -----------------------------------------
    _note("note_solv", 0, 3.5,
          "STEP 3 - Box and solvent\n"
          "A cubic box with 1.2 nm between the protein and every edge, then filled "
          "with SPC216 water (a generic 3-point box that relaxes into TIP3P).\n"
          "solvate updates [ molecules ] in the topology as it goes."),
    _n("box", "gmx.editconf", 2, 3,
       box_type="cubic", distance=1.2, center=True, output="1AKI_newbox.gro"),
    _n("solv", "gmx.solvate", 3, 3,
       solvent="spc216.gro", output="1AKI_solv.gro"),

    # ---- step 4: ions -----------------------------------------------------
    _note("note_ions", 0, 5.5,
          "STEP 4 - Ions\n"
          "Lysozyme carries +8e, so 8 Cl- replace 8 waters. genion needs a tpr, which "
          "means a throwaway grompp first - this node runs both, so the pair of "
          "commands the tutorial issues is one node here.\n"
          "'SOL' is the group to replace: you do not want ions substituted into the "
          "protein."),
    _n("mdp_ions", "util.mdp", 2, 5, preset="lysozyme_ions", filename="ions.mdp"),
    _n("ions", "gmx.genion", 3, 5,
       neutral=True, concentration=0.0, pname="NA", nname="CL",
       solvent_group="SOL", maxwarn=0, output="1AKI_solv_ions.gro"),

    # ---- step 5: energy minimisation --------------------------------------
    _note("note_em", 7.5, 2,
          "STEP 5 - Energy minimisation\n"
          "Steepest descent until Fmax < 1000 kJ/mol/nm. Two numbers in the log "
          "matter: Epot should be large and negative (order -1e6 here) and Fmax should "
          "be below the tolerance. If it is not, the geometry is bad and no amount of "
          "equilibration will rescue it."),
    _n("mdp_min", "util.mdp", 6.5, 1, preset="lysozyme_min", filename="minim.mdp"),
    _n("grompp_em", "gmx.grompp", 7.5, 1, output="em.tpr", restraint_from_conf=False),
    _n("mdrun_em", "gmx.mdrun", 8.5, 1, deffnm="em", v=True),
    _n("energy_pot", "gmx.energy", 9.5, 1, terms="Potential\n", output="potential.xvg"),
    _n("plot_pot", "view.plot", 10.5, 1),

    # ---- step 6: NVT ------------------------------------------------------
    _note("note_nvt", 7.5, 4,
          "STEP 6 - NVT equilibration\n"
          "5 ps here, with the protein position-restrained and velocities generated "
          "at 298 K. The tutorial runs 100 ps; on one processor that alone would take "
          "half an hour. The point is to let the solvent settle around a fixed "
          "solute.\n"
          "Watch the temperature. It drops at once, because about half of the energy "
          "handed out as speed goes straight into the molecules pulling on each "
          "other; then the thermostat brings it back to 298 K. The tutorial's "
          "thermostat corrects slowly (tau-t = 1 ps), which is fine over 100 ps but "
          "would not get there in 5, so here it corrects ten times faster "
          "(tau-t = 0.1 ps).\n"
          "grompp needs -r for the restraint reference: that is the second wire from "
          "the minimised structure, into the 'restraint' port."),
    _n("mdp_nvt", "util.mdp", 6.5, 3, preset="lysozyme_nvt", mode="manual",
       nsteps="2500", nstenergy="50", tau_t="0.1", filename="nvt.mdp"),
    _n("grompp_nvt", "gmx.grompp", 7.5, 3, output="nvt.tpr"),
    _n("mdrun_nvt", "gmx.mdrun", 8.5, 3, deffnm="nvt", v=True),
    _n("energy_temp", "gmx.energy", 9.5, 3, terms="Temperature\n",
       output="temperature.xvg"),
    _n("plot_temp", "view.plot", 10.5, 3),

    # ---- step 7: NPT ------------------------------------------------------
    _note("note_npt", 7.5, 6,
          "STEP 7 - NPT equilibration\n"
          "5 ps here (the tutorial: 500 ps) with the barostat on, restraints still "
          "applied, continuing from the NVT checkpoint so velocities carry over. The "
          "barostat corrects in 1 ps instead of the tutorial's 5 (tau-p), for the "
          "same reason as the thermostat before it: in 5 ps a 5 ps correction would "
          "only have started.\n"
          "Pressure fluctuates violently in a system this size - that is normal, not a "
          "problem. Density is the number to judge: it jumps from about 985 to over "
          "1010 kg/m3 in the first picosecond and ends near 1025 -- the average the "
          "tutorial reports over its 500 ps."),
    _n("mdp_npt", "util.mdp", 6.5, 5, preset="lysozyme_npt", mode="manual",
       nsteps="2500", nstenergy="50", tau_t="0.1", extra_flags="tau-p = 1.0",
       filename="npt.mdp"),
    _n("grompp_npt", "gmx.grompp", 7.5, 5, output="npt.tpr"),
    _n("mdrun_npt", "gmx.mdrun", 8.5, 5, deffnm="npt", v=True),
    _n("energy_press", "gmx.energy", 9.5, 5, terms="Pressure\n", output="pressure.xvg"),
    _n("plot_press", "view.plot", 10.5, 5),
    _n("energy_dens", "gmx.energy", 9.5, 6, terms="Density\n", output="density.xvg"),
    _n("plot_dens", "view.plot", 10.5, 6),

    # ---- step 8: production ----------------------------------------------
    _note("note_md", 7.5, 9,
          "STEP 8 - Production MD\n"
          "10 ps, no restraints, no velocity generation, a picture every 0.1 ps. The "
          "tutorial runs 10 ns, a thousand times longer: on one processor that "
          "takes about two days, where 10 ps takes about three minutes. Long enough "
          "to see the protein and the water move; far too short for the protein to "
          "change shape. Raise nsteps on the run-parameters node for a longer run."),
    _n("mdp_md", "util.mdp", 6.5, 8, preset="lysozyme_md", mode="manual",
       nsteps="5000", nstxout_compressed="50", filename="md.mdp"),
    _n("grompp_md", "gmx.grompp", 7.5, 8, output="md_0_10.tpr",
       restraint_from_conf=False),
    _n("mdrun_md", "gmx.mdrun", 8.5, 8, deffnm="md_0_10", v=True),

    # ---- steps 9-10: analysis --------------------------------------------
    _note("note_analysis", 14, 0,
          "STEPS 9-10 - Analysis\n"
          "Everything downstream runs on the reimaged trajectory: the protein diffuses "
          "and would otherwise appear to jump across the box.\n"
          "Two RMSD nodes - one against the equilibrated structure (md tpr) and one "
          "against the crystal structure (em tpr, whose coordinates are still the "
          "un-minimised PDB). In 10 ps both climb to about 0.08 nm. RMSD is not a "
          "convergence metric; it only says how far things moved.\n"
          "Rg near 1.4 nm and flat means the fold is holding.\n"
          "Each one ends in a Preview plot, so the answer is on the canvas rather "
          "than in a file you have to go and find. Hover for values; the arrow "
          "button opens the same curve full size in the Plot tab."),
    _note("note_dssp", 17, 0,
          "Reading the secondary structure\n"
          "The dssp node draws its own answer: residue up the side, time along the "
          "bottom, a colour per kind of structure. Warm colours are helices, cold "
          "ones are sheets, grey is loop.\n"
          "What to look for is bands, not values. A horizontal band that runs the "
          "whole width is an element that held for the entire run. A band that goes "
          "grey from one end is an element fraying, and the end it frays from tells "
          "you where. Grey creeping through the middle of a band is the interesting "
          "one: something opened up.\n"
          "Lysozyme should be almost all band. Its helices are around residues 5-15, "
          "25-36, 89-100 and 109-115, and the small beta sheet sits near 43-60; if "
          "those stay coloured for the whole run the fold is fine. The caption under the "
          "picture gives the run-average composition, which is the one number worth "
          "quoting - roughly 40% helix for this protein.\n"
          "The second output, 'counts', is the same thing summed per frame, and it "
          "goes to a Preview plot: a flat line is a fold that held, a line that "
          "slopes down is one that is melting."),
    _n("pbc", "gmx.trjconv", 14, 1,
       pbc="mol", ur="", center=True, output="md_0_10_noPBC.xtc",
       groups="Protein\nSystem\n"),
    _n("rms", "gmx.rms", 15, 1, groups="Backbone\nBackbone\n", tu="ps",
       output="rmsd.xvg"),
    _n("plot_rms", "view.plot", 16, 1),
    _n("rms_xtal", "gmx.rms", 17, 1,
       groups="Backbone\nBackbone\n", tu="ps", output="rmsd_xtal.xvg"),
    _n("plot_rms_xtal", "view.plot", 18, 1),
    _n("gyrate", "gmx.gyrate", 15, 2, sel="Protein", tu="ps", output="gyrate.xvg"),
    _n("plot_rg", "view.plot", 16, 2),
    _n("dssp", "gmx.dssp", 17, 2, sel="Protein", tu="ps",
       output="dssp.dat", output_num="dssp_num.xvg"),
    _n("plot_dssp", "view.plot", 18, 2),
    _n("hbond", "gmx.hbond", 15, 3, r="Protein", t="Protein", output="hbnum.xvg"),
    _n("plot_hb", "view.plot", 16, 3),

    # ---- and a look at the run itself -------------------------------------
    _note("note_watch", 17.1, 3,
          "Watch it, roughly\n"
          "The Preview trajectory node pulls every second frame of the protein "
          "out with trjconv and plays them inside the node. It is for the "
          "questions you answer by looking - did it stay folded, did it leave the "
          "box, is the terminus flapping - and not for anything you would put a "
          "number on. Press play, drag the slider, drag the picture to turn it.\n"
          "It writes the frames out as a multi-model PDB, so the same file opens in "
          "VMD or PyMOL when the rough look raises a real question."),
    _n("watch", "view.trajectory", 14, 2.5, mode="every Nth", skip=2,
       sel="Protein", pbc="mol", center=True),
]

_LYSOZYME_LINKS: List[Dict[str, str]] = [
    # Every analysis ends in a picture rather than in a loose end.
    _l("energy_pot", "xvg", "plot_pot", "xvg"),
    _l("energy_temp", "xvg", "plot_temp", "xvg"),
    _l("energy_press", "xvg", "plot_press", "xvg"),
    _l("energy_dens", "xvg", "plot_dens", "xvg"),
    _l("rms", "xvg", "plot_rms", "xvg"),
    _l("rms_xtal", "xvg", "plot_rms_xtal", "xvg"),
    _l("gyrate", "xvg", "plot_rg", "xvg"),
    _l("dssp", "xvg", "plot_dssp", "xvg"),
    _l("hbond", "xvg", "plot_hb", "xvg"),
    _l("pbc", "traj", "watch", "traj"),
    _l("grompp_md", "tpr", "watch", "tpr"),
    _l("ff", "ffdir", "top", "ffdir"),
    _l("fetch", "structure", "clean", "structure"),
    _l("clean", "structure", "top", "structure"),
    _l("top", "structure", "box", "structure"),
    _l("box", "structure", "solv", "structure"),
    _l("top", "topology", "solv", "topology"),
    _l("solv", "structure", "ions", "structure"),
    _l("solv", "topology", "ions", "topology"),
    _l("mdp_ions", "mdp", "ions", "mdp"),

    _l("mdp_min", "mdp", "grompp_em", "mdp"),
    _l("ions", "structure", "grompp_em", "structure"),
    _l("ions", "topology", "grompp_em", "topology"),
    _l("grompp_em", "tpr", "mdrun_em", "tpr"),
    _l("mdrun_em", "edr", "energy_pot", "edr"),

    _l("mdp_nvt", "mdp", "grompp_nvt", "mdp"),
    _l("mdrun_em", "structure", "grompp_nvt", "structure"),
    _l("mdrun_em", "structure", "grompp_nvt", "restraint"),
    _l("ions", "topology", "grompp_nvt", "topology"),
    _l("grompp_nvt", "tpr", "mdrun_nvt", "tpr"),
    _l("mdrun_nvt", "edr", "energy_temp", "edr"),

    _l("mdp_npt", "mdp", "grompp_npt", "mdp"),
    _l("mdrun_nvt", "structure", "grompp_npt", "structure"),
    _l("mdrun_nvt", "structure", "grompp_npt", "restraint"),
    _l("mdrun_nvt", "checkpoint", "grompp_npt", "checkpoint"),
    _l("ions", "topology", "grompp_npt", "topology"),
    _l("grompp_npt", "tpr", "mdrun_npt", "tpr"),
    _l("mdrun_npt", "edr", "energy_press", "edr"),
    _l("mdrun_npt", "edr", "energy_dens", "edr"),

    _l("mdp_md", "mdp", "grompp_md", "mdp"),
    _l("mdrun_npt", "structure", "grompp_md", "structure"),
    _l("mdrun_npt", "checkpoint", "grompp_md", "checkpoint"),
    _l("ions", "topology", "grompp_md", "topology"),
    _l("grompp_md", "tpr", "mdrun_md", "tpr"),

    _l("mdrun_md", "traj", "pbc", "traj"),
    _l("grompp_md", "tpr", "pbc", "tpr"),
    _l("pbc", "traj", "rms", "traj"),
    _l("grompp_md", "tpr", "rms", "tpr"),
    _l("pbc", "traj", "rms_xtal", "traj"),
    _l("grompp_em", "tpr", "rms_xtal", "tpr"),
    _l("pbc", "traj", "gyrate", "traj"),
    _l("grompp_md", "tpr", "gyrate", "tpr"),
    _l("pbc", "traj", "dssp", "traj"),
    _l("grompp_md", "tpr", "dssp", "tpr"),
    _l("pbc", "traj", "hbond", "traj"),
    _l("grompp_md", "tpr", "hbond", "tpr"),
]


def _in(node: str, port: str, name: str) -> Dict[str, str]:
    """A file coming into a box through a dot on its left-hand wall."""
    return _wall(node, port, "west", name)


def _out(node: str, port: str, name: str) -> Dict[str, str]:
    """A file leaving a box through a dot on its right-hand wall."""
    return _wall(node, port, "east", name)


#: The tutorial's own stages, as coloured boxes. Same palette as the chunks, so
#: a blue box means equilibration wherever you meet one. Each box holds its
#: own plots and its note as well, so a stage reads as one piece.
#:
#: Every file that goes from one box to another has a dot on the right-hand
#: wall of the box it leaves and one on the left-hand wall of the box it
#: enters, and each dot is given a short name of its own. Left to the editor,
#: a name is lengthened whenever the same word turns up twice on one box --
#: "topology" coming in on the left and the updated topology going out on the
#: right -- until it reads "Solvate · topology". The structure's name says
#: how far along it is instead: protein, protein in water, with ions,
#: minimised, after NVT, after NPT.
#:
#: The right wall lists its dots in the opposite order to the left wall they
#: run to: the left wall fills from the top down and the right wall from the
#: bottom up, and in this order the lines run side by side instead of
#: crossing. Where a box takes files from two places, the order of its left
#: wall is the one where the fewest wires cross, found by trying them: the
#: topology goes below the files from the box above when it comes in from
#: level or from below, and above them when it comes down from high up, as
#: into the production run.
_LYSOZYME_GROUPS = [
    _group("1. Topology (pdb2gmx)", COLOR["input"], "ff", "fetch", "clean", "top",
           walls=[_out("top", "structure", "protein"),
                  _out("top", "topology", "topology")]),
    _group("3. Box and solvent", COLOR["build"], "box", "solv",
           walls=[_in("top", "topology", "topology"),
                  _in("top", "structure", "protein"),
                  _out("solv", "structure", "protein in water"),
                  _out("solv", "topology", "topology")]),
    _group("4. Add ions", COLOR["build"], "mdp_ions", "ions",
           # The structure only goes up, to the minimisation, while the
           # topology goes to all four runs, down as well as up. So the
           # structure takes the upper dot, and the wires going down never
           # have to cross it.
           walls=[_in("solv", "topology", "topology"),
                  _in("solv", "structure", "protein in water"),
                  _out("ions", "topology", "topology"),
                  _out("ions", "structure", "with ions")]),
    _group("5. Energy minimisation", COLOR["minimise"],
           "mdp_min", "grompp_em", "mdrun_em", "energy_pot", "plot_pot", "note_em",
           # em.tpr goes on to the analysis: RMSD against the crystal
           # structure reads its coordinates. Named after the file, because
           # the analysis takes a second tpr as well. Its wire drops steeply
           # to the analysis, far below, while the minimised structure swings
           # round into the next run, so the two have to cross once. With
           # em.tpr on the lower dot that happens a little way out from the
           # wall, clear of the names; on the upper dot it would cut across
           # the other wire twice, right beside them.
           walls=[_in("ions", "structure", "with ions"),
                  _in("ions", "topology", "topology"),
                  _out("grompp_em", "tpr", "em.tpr"),
                  _out("mdrun_em", "structure", "minimised")]),
    _group("6. NVT equilibration", COLOR["equilibrate"],
           "mdp_nvt", "grompp_nvt", "mdrun_nvt", "energy_temp", "plot_temp",
           "note_nvt",
           walls=[_in("mdrun_em", "structure", "minimised"),
                  _in("ions", "topology", "topology"),
                  _out("mdrun_nvt", "checkpoint", "checkpoint"),
                  _out("mdrun_nvt", "structure", "after NVT")]),
    _group("7. NPT equilibration", COLOR["equilibrate"],
           "mdp_npt", "grompp_npt", "mdrun_npt", "energy_press", "plot_press",
           "energy_dens", "plot_dens", "note_npt",
           walls=[_in("mdrun_nvt", "structure", "after NVT"),
                  _in("mdrun_nvt", "checkpoint", "checkpoint"),
                  _in("ions", "topology", "topology"),
                  _out("mdrun_npt", "checkpoint", "checkpoint"),
                  _out("mdrun_npt", "structure", "after NPT")]),
    _group("8. Production MD", COLOR["production"],
           "mdp_md", "grompp_md", "mdrun_md", "note_md",
           # The topology comes steeply down from high up on the left. On the
           # bottom dot it would run through the curve of the two wires
           # coming round from the box above, crossing each of them twice;
           # on the top dot it crosses each of them once.
           walls=[_in("ions", "topology", "topology"),
                  _in("mdrun_npt", "structure", "after NPT"),
                  _in("mdrun_npt", "checkpoint", "checkpoint"),
                  _out("grompp_md", "tpr", "md_0_10.tpr"),
                  _out("mdrun_md", "traj", "trajectory")]),
    _group("9-10. Analysis", COLOR["analysis"],
           "pbc", "rms", "plot_rms", "rms_xtal", "plot_rms_xtal", "gyrate",
           "plot_rg", "dssp", "plot_dssp", "hbond", "plot_hb", "watch",
           "note_watch",
           # em.tpr comes down from above, the other two up from the
           # production run, so it takes the top dot and nothing crosses.
           walls=[_in("grompp_em", "tpr", "em.tpr"),
                  _in("mdrun_md", "traj", "trajectory"),
                  _in("grompp_md", "tpr", "md_0_10.tpr")]),
]

# Rows are written as indices; this spaces them by how tall the nodes in each
# one actually render. Each of the three columns is stacked on its own. Then
# the boxes in each column are pulled apart far enough for the wire from one
# to the next to swing round between them, and finally the runs are stood
# level with the first box on the left and the analysis level with the
# production run that feeds it.
_relayout(_LYSOZYME_NODES, bands=(5, 13))
_space_boxes(_LYSOZYME_NODES, _LYSOZYME_GROUPS,
             ["1. Topology (pdb2gmx)", "3. Box and solvent", "4. Add ions"], 360)
_space_boxes(_LYSOZYME_NODES, _LYSOZYME_GROUPS,
             ["5. Energy minimisation", "6. NVT equilibration",
              "7. NPT equilibration", "8. Production MD"], 360)
_level_with(_LYSOZYME_NODES, "mdp_min", "ff", 5)
_level_with(_LYSOZYME_NODES, "pbc", "mdp_md", 13)


_LYSOZYME_STEPS = [
    {"title": "1. Prepare the topology", "page": "01_pdb2gmx.html",
     "nodes": ["ff", "fetch", "clean", "top"],
     "summary": "Fetch 1AKI and CHARMM36, strip the crystal waters, and let pdb2gmx "
                "assign the force field "
                "and TIP3P. Produces the processed structure, the topology and the "
                "position-restraint file."},
    {"title": "2. Examine the topology", "page": "02_topology.html",
     "nodes": ["top"],
     "summary": "A reading exercise, no command. Open topol.top from the Files tab and "
                "look at [ moleculetype ], [ atoms ], the POSRES include and "
                "[ molecules ]."},
    {"title": "3. Define the box and solvate", "page": "03_solvate.html",
     "nodes": ["box", "solv"],
     "summary": "Cubic box, 1.2 nm to every edge, filled with SPC216 water."},
    {"title": "4. Add ions", "page": "04_ions.html",
     "nodes": ["mdp_ions", "ions"],
     "summary": "Neutralise the +8e protein by replacing SOL molecules with Cl-. The "
                "throwaway grompp that genion needs is part of the same node."},
    {"title": "5. Energy minimisation", "page": "05_EM.html",
     "nodes": ["mdp_min", "grompp_em", "mdrun_em", "energy_pot"],
     "summary": "Steepest descent to Fmax < 1000 kJ/mol/nm, then extract the potential "
                "energy trace."},
    {"title": "6. NVT equilibration", "page": "06_equil.html",
     "nodes": ["mdp_nvt", "grompp_nvt", "mdrun_nvt", "energy_temp"],
     "summary": "5 ps restrained NVT at 298 K with generated velocities (the "
                "tutorial: 100 ps); check that the temperature reaches and holds "
                "298 K."},
    {"title": "7. NPT equilibration", "page": "07_equil2.html",
     "nodes": ["mdp_npt", "grompp_npt", "mdrun_npt", "energy_press", "energy_dens"],
     "summary": "5 ps restrained NPT continuing from the NVT checkpoint (the "
                "tutorial: 500 ps); judge it on density, not on pressure."},
    {"title": "8. Production MD", "page": "08_MD.html",
     "nodes": ["mdp_md", "grompp_md", "mdrun_md"],
     "summary": "10 ps unrestrained (the tutorial: 10 ns). Raise nsteps on the "
                "run-parameters node for a longer run."},
    {"title": "9. Analysis: periodicity and RMSD", "page": "09_analysis.html",
     "nodes": ["pbc", "rms", "rms_xtal"],
     "summary": "Reimage the trajectory, then RMSD against the equilibrated structure "
                "and against the crystal structure."},
    {"title": "10. Analysis: Rg, secondary structure, hydrogen bonds",
     "page": "10_analysis2.html",
     "nodes": ["gyrate", "dssp", "hbond"],
     "summary": "Radius of gyration, per-residue secondary structure via the built-in "
                "DSSP, and hydrogen-bond counts."},
]


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

TUTORIALS: List[Dict[str, Any]] = [
    {
        "id": "lysozyme",
        "collection": "gmx",
        "number": 1,
        "name": "Lysozyme in Water",
        "status": "packaged",
        "source": SITE + "lysozyme/",
        "summary": "The canonical first GROMACS tutorial: hen egg white lysozyme "
                   "(1AKI) solvated, neutralised, minimised, equilibrated in NVT and "
                   "NPT, run and analysed -- every run cut short so that the whole of it "
                   "fits in a lesson.",
        "requires": [
            "GROMACS",
            "nothing you have to fetch by hand: CHARMM36 is not bundled with "
            "GROMACS, so the graph downloads charmm36-jul2022 from the MacKerell lab "
            "and unpacks it itself. Point the 'Force field directory' node at a local "
            "copy if you already have one, or delete it and name a bundled force "
            "field on pdb2gmx instead",
            "network access for the RCSB download, or swap in a 'Load structure' node",
        ],
        "runtime": "about 8 minutes on one processor: the four runs take half a "
                   "minute, a minute and a half, a minute and a half and three "
                   "minutes. Measured in the online copy, limited to one processor",
        "measured": "Run here from start to finish in the online copy, on one "
                    "processor, in 7 minutes 41 seconds.\n"
                    "\n"
                    "8 chloride ions and 12,589 waters, against the tutorial's 8 "
                    "and 12,588. Minimisation converged in 457 steps with a "
                    "maximum force of 889 kJ/mol/nm on atom 567 -- the same atom "
                    "the tutorial names (566 steps and 980 there), which is the "
                    "strongest single sign that this is the same system taking "
                    "the same path.\n"
                    "\n"
                    "The temperature fell to about 210 K the moment the speeds "
                    "were handed out and was back near 298 K within 1.5 ps. The "
                    "density rose from 985 to 1026 kg/m3 in the 5 ps, against "
                    "the 1025 the tutorial averages over 500 ps.\n"
                    "\n"
                    "In the 10 ps of production the RMSD climbed to about "
                    "0.08 nm, and the radius of gyration stayed between 1.40 "
                    "and 1.42 nm, against the tutorial's 1.409 over 10 ns.",
        "steps": _LYSOZYME_STEPS,
        "graph": {"nodes": _LYSOZYME_NODES, "links": _LYSOZYME_LINKS,
                  "groups": _LYSOZYME_GROUPS},
    },
]


TUTORIALS += _ICE_TUTORIALS

# Every packaged graph gets one last grooming here rather than in each module:
# where the boxes drawn round two stages would lie across each other, the lower
# stage is moved down until they read as separate blocks. Done centrally so a
# module never has to know how much padding the editor draws boxes with.
for _entry in TUTORIALS:
    _graph = _entry.get("graph")
    if _graph and _graph.get("groups"):
        _untangle_groups(_graph.get("nodes") or [], _graph["groups"])


def tutorial_list() -> List[Dict[str, Any]]:
    """Catalogue entries, with the graph stripped out of the listing."""
    out = []
    for tutorial in TUTORIALS:
        entry = {k: v for k, v in tutorial.items() if k != "graph"}
        entry["nodes"] = len(tutorial.get("graph", {}).get("nodes", []))
        entry["tools"] = tools_used(tutorial)["all"]
        out.append(entry)
    return out


def get(tutorial_id: str) -> Dict[str, Any]:
    for tutorial in TUTORIALS:
        if tutorial["id"] == tutorial_id:
            return tutorial
    raise KeyError(tutorial_id)


#: Which tool each kind of block drives -- "gmx.mdrun" -> "gromacs".
#:
#: Worked out once and kept, because the answer cannot change while the
#: program is running: it comes from the block classes, not from anything on
#: disk or in the settings.  Working it out afresh for every tutorial cost
#: about a tenth of a second each, and the page that lists the tutorials asks
#: once for every tutorial, one after another -- in the full program, with
#: dozens of tutorials, that was seconds of the browser sitting on an empty
#: canvas before a single node appeared.
_TOOL_OF_NODE: Dict[str, str] = {}


def _tool_of_node() -> Dict[str, str]:
    from .registry import REGISTRY               # circular at module level

    if not _TOOL_OF_NODE:
        for category in REGISTRY.categories():
            for spec in category["nodes"]:
                tool = (spec.get("tool") or "").strip()
                if tool and tool != "shell":
                    _TOOL_OF_NODE[spec["type"]] = tool
    return _TOOL_OF_NODE


def tools_used(tutorial: Dict[str, Any]) -> Dict[str, Any]:
    """Which external tools a tutorial's graph actually needs, and where.

    Derived from the nodes rather than written down beside them.  A hand-kept
    list is a list that drifts: swap a node and the prose still names the old
    tool.  Every node spec already declares the logical tool it drives, so the
    honest answer is a walk over the graph.

    Split by group as well as in total, because a tutorial can lay out
    alternative routes side by side, and somebody who only wants one route
    should not be told they need the tools of the others as well.
    """
    tool_of = _tool_of_node()

    graph = tutorial.get("graph") or {}
    nodes = graph.get("nodes") or []
    by_id = {node["id"]: tool_of.get(node.get("type", "")) for node in nodes}
    every = sorted({tool for tool in by_id.values() if tool})

    routes = []
    for group in graph.get("groups") or []:
        wanted = sorted({by_id.get(node_id) for node_id in group.get("nodes") or []}
                        - {None})
        if wanted:
            routes.append({"title": group.get("title", ""), "tools": wanted})
    return {"all": every, "groups": routes}


def collection_of(tutorial: Dict[str, Any]) -> Dict[str, str]:
    """The site, author and citation for the collection a tutorial came from."""
    return COLLECTIONS.get(tutorial.get("collection", "gmx"), COLLECTIONS["gmx"])


#: The order the palette shows the collections in. Anything in
#: :data:`COLLECTIONS` but missing from here is still shown, after these -- a
#: new collection that nobody remembered to list must not go invisible, which
#: is exactly what once happened to two sets.
COLLECTION_ORDER = ("gmx", "workshop")


def meta() -> Dict[str, Any]:
    """Collection metadata, in the order the palette should show them.

    Only collections that have a tutorial in them: a heading with nothing
    under it only raises a question.
    """
    present = {tutorial.get("collection", "gmx") for tutorial in TUTORIALS}
    keys = [key for key in COLLECTION_ORDER if key in COLLECTIONS]
    keys += [key for key in COLLECTIONS if key not in keys]
    keys = [key for key in keys if key in present]
    return {"collections": [COLLECTIONS[key] for key in keys]}
