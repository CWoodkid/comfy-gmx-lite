"""The boxes on the "Run parameters (.mdp)" block, one per mdp option.

Each entry says which GROMACS option a box sets, what it is called on
screen, which values it offers, when it is shown, and what it means in
plain words: what it does, what each value means, and the value usually
used for each kind of run. The block (nodes/util_nodes.py, MdpNode) builds
its boxes from this table, and the browser gets the same table through
/api/mdp/presets, so the two cannot disagree about which box sets which
option.

Checked against GROMACS 2026.3 on 2026-09-29: every option below is one
gmx grompp 2026.3 accepts, every default is what it writes into mdout.mdp
for an empty .mdp file, and every choice is one it lists as allowed when it
is given a wrong one. The warnings and refusals the help texts mention are
ones grompp 2026.3 printed for a small box of water.

Where a box is shown ("when"): the rules are read by the browser against
the value the run will really use, whether a box, the preset, the raw text
or the file says it. Four of the names they use are not boxes but are
worked out from the others:

    _run         dynamics (md, md-vv, md-vv-avek, sd, bd) or
                 minimise (steep, cg, l-bfgs)
    _thermostat  on when a thermostat is at work: sd or bd, or tcoupl
                 anything but no, in a dynamics run
    _barostat    on when pcoupl is anything but no, in a dynamics run
    _annealing   on when annealing names single or periodic for a group

A box that does nothing for the run as it stands (a time step in a
minimisation, a barostat time with no barostat) is left out of sight, so
what is on screen is what matters.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Dict, List, Tuple


def _h(text: str) -> str:
    """Help written as an indented block: blank lines between paragraphs,
    and the usual values as a small table indented under them.

    A table starts a block of its own, with a blank line put before it where
    the line above introduces it ("Usual values:"). The page lays a block of
    indented lines out as a table in fixed-width type, but only when every
    line in the block is indented; with the heading in the same block, the
    whole table ran together into one sentence."""
    out: List[str] = []
    for line in textwrap.dedent(text).strip("\n").splitlines():
        indented = line.startswith("    ")
        if indented and out and out[-1].strip() and not out[-1].startswith("    "):
            out.append("")
        out.append(line)
    return "\n".join(out)


@dataclass(frozen=True)
class Box:
    """One box on the block."""

    param: str            # its name in the block, and in saved workflows
    key: str              # the mdp option it sets
    label: str            # what it is called on screen
    help: str
    kind: str = "str"     # "str" or "choice"
    choices: Tuple[str, ...] = ()
    section: str = ""     # "" is on the face of the block; else its drawer
    when: str = ""
    placeholder: str = ""


#: The drawers inside the block's advanced drawer, in the order they are listed.
SECTIONS: Tuple[str, ...] = (
    "Temperature",
    "Pressure",
    "Starting velocities",
    "Output",
    "Cut-offs and pair lists",
    "Electrostatics",
    "Van der Waals",
    "Bonds and constraints",
    "Drift of the whole system",
    "Heating and cooling",
    "Frozen atoms",
    "File and extra lines",
)


BOXES: List[Box] = [
    # ---- on the face of the block -------------------------------------
    Box("integrator", "integrator", "Kind of run", kind="choice",
        choices=("", "md", "sd", "steep", "cg", "l-bfgs", "md-vv",
                 "md-vv-avek", "bd"),
        help=_h("""
            What the run does with the forces between the atoms.

            md: molecular dynamics. The atoms move under their forces, one
            small step of time after another. The usual choice for every
            run in which time passes.

            sd: dynamics with friction and small random pushes on every
            atom (stochastic dynamics). Those hold the temperature by
            themselves, so no separate thermostat is used. Good for
            free-energy work and for small or sparse systems.

            steep: energy minimisation by steepest descent. No time passes:
            the atoms are moved downhill until the forces are small. The
            standard first step after building a system, to remove atoms
            that sit too close together.

            cg: minimisation by conjugate gradients. It gets closer to the
            true minimum than steep and is used after it when a very well
            minimised structure is needed.

            l-bfgs: another minimiser, often the quickest to finish, but it
            cannot share its work between several processes.

            md-vv, md-vv-avek: dynamics by the velocity Verlet method.
            Needed for the MTTK barostat and the Andersen thermostat;
            otherwise md does the same job faster.

            bd: Brownian dynamics, for particles in a very thick liquid.
            Rarely used.

            Usual values:
                minimisation, any model       steep
                warm-up and production        md
                alchemical free energy        sd
            """)),
    Box("nsteps", "nsteps", "Number of steps",
        help=_h("""
            How many steps the run takes.

            For dynamics, the run lasts this many steps times the time step
            (dt): 50,000 steps of 0.002 ps is 100 ps. -1 means no limit:
            the run goes on until it is stopped, or until the time given to
            mdrun with -maxh is up.

            For a minimisation it is the most steps allowed. The run usually
            stops sooner, once no force is above the stopping force (emtol).

            Usual values:
                minimisation                   5,000 to 50,000
                all-atom warm-up, 2 fs steps   50,000 (100 ps) to 500,000 (1 ns)
                all-atom production, 2 fs      5,000,000 (10 ns) and more
            """)),
    Box("dt", "dt", "Time step (ps)", when="_run=dynamics",
        help=_h("""
            How far time moves on between one calculation of the forces and
            the next, in picoseconds (1 ps is a millionth of a millionth of a
            second). The run lasts nsteps times dt.

            A longer step covers more time for the same computer time, but
            too long and the atoms move too far in one step and the run
            falls apart, usually with LINCS warnings or a message about
            particles moving too far.

            Usual values:
                atoms, all bonds free to vibrate       0.001 (1 fs)
                atoms, bonds to hydrogen held fixed    0.002 (2 fs, with constraints = h-bonds)
                atoms, with heavier hydrogens          0.004 (4 fs, with mass-repartition-factor = 3)
            """)),
    Box("emtol", "emtol", "Stopping force (kJ/mol/nm)", when="_run=minimise",
        help=_h("""
            A minimisation stops as soon as the largest force on any atom
            is below this, in kJ/mol/nm. It also stops after nsteps steps,
            or when it can improve no further; the log says which.

            Smaller is stricter and takes longer. GROMACS's own default, 10,
            is strict. Most setups use a looser value, because the warm-up
            that follows settles the rest.

            Usual values:
                all-atom, before a warm-up    1000
            """)),
    Box("emstep", "emstep", "First step size (nm)", when="integrator=steep",
        help=_h("""
            For steepest descent: how far, in nm, the atoms may move in the
            first step. The step then grows while the energy keeps falling
            and shrinks when it rises, so this only sets where it starts.

            Usual values:
                all-atom                        0.01 (the default)
            """)),
    Box("nstcgsteep", "nstcgsteep", "Steepest-descent step every",
        when="integrator=cg",
        help=_h("""
            For conjugate gradients: take one steepest-descent step every
            this many steps, which keeps the method from stalling. The
            default, 1000, is what almost everybody uses.
            """)),
    Box("ref_t", "ref-t", "Temperature (K)", when="_thermostat=on",
        help=_h("""
            The temperature the thermostat holds, in kelvin (degrees Celsius
            plus 273.15). One number for each heat group in tc-grps, in the
            same order and separated by spaces: '310 310' for two groups.

            Usual values:
                room temperature      298 or 300
                body temperature      310
                POPC membranes        303 to 310
                DPPC membranes        323, because DPPC is still solid at 310
            """)),
    Box("pcoupl", "pcoupl", "Pressure control", kind="choice",
        choices=("", "no", "C-rescale", "Parrinello-Rahman", "Berendsen", "MTTK"),
        when="_run=dynamics",
        help=_h("""
            Whether the box may change size to keep the pressure steady (a
            barostat).

            no: the box keeps its size and the pressure is whatever it turns
            out to be. This is a run at constant volume, often called NVT.

            C-rescale: stochastic cell rescaling. It settles quickly and gives
            the right fluctuations, so it suits warm-up and production alike.
            The usual choice today.

            Parrinello-Rahman: right fluctuations too, but the box can swing
            wildly when the pressure starts far from the target. Use it only
            after a warm-up with C-rescale.

            Berendsen: settles quickly but gives the wrong fluctuations;
            GROMACS 2026 warns against it. Only for old protocols.

            MTTK: only with the md-vv integrator and without constraints.

            Usual values:
                minimisation, first warm-up (NVT)   no
                second warm-up (NPT)                C-rescale
                production                          C-rescale or Parrinello-Rahman
            """)),
    Box("define", "define", "Topology switches", placeholder="e.g. -DPOSRES",
        help=_h("""
            Switches that turn on optional parts of the topology, each
            written as -D and a name, separated by spaces. The topology
            decides what a switch does; these are the common ones:

                -DPOSRES            hold atoms near their starting places
                -DFLEXIBLE          let water bend and stretch; for minimisation only

            -DPOSRES (position restraints) is used during warm-up, so a
            protein keeps its shape while the water settles around it.

            Usual values:
                minimisation          empty, or -DFLEXIBLE
                warm-up (NVT, NPT)    -DPOSRES
                production            empty

            Give only switches the topology uses. GROMACS warns about any it
            does not find, which catches a misspelt name, and a warning stops
            grompp unless it is allowed.

            Type NONE to remove a define line that the preset has.
            """)),
    Box("nstxout_compressed", "nstxout-compressed", "Frame every (steps)",
        help=_h("""
            How often, in steps, the positions are saved to the compressed
            trajectory (.xtc), the file you watch and analyse. 0 saves none.
            The time between frames is this times dt: 5000 steps of 2 fs is
            one frame every 10 ps.

            More frames make smoother films and more data, and a bigger
            file. Most analyses are fine with a frame every 10 to 100 ps.

            Usual values:
                warm-up, all-atom 2 fs       500 to 5000 (1 to 10 ps)
                production, all-atom 2 fs    5000 (10 ps)
            """)),

    # ---- Temperature --------------------------------------------------
    Box("tcoupl", "tcoupl", "Thermostat", kind="choice", section="Temperature",
        choices=("", "no", "V-rescale", "Nose-Hoover", "Berendsen", "Andersen",
                 "Andersen-massive"),
        when="_run=dynamics & integrator!=sd|bd",
        help=_h("""
            How the temperature is kept steady (the thermostat).

            no: none. The total energy stays constant and the temperature
            wanders; only for special tests.

            V-rescale: nudges the speeds towards the target, with a small
            random part (the Bussi thermostat). It gives the right
            fluctuations, is robust, and is fine from warm-up to production.
            The usual choice.

            Nose-Hoover: right fluctuations too, but the temperature swings
            slowly around the target, so it is for production after a
            warm-up. With the md integrator it uses a single link instead of
            a chain; GROMACS notes this.

            Berendsen: settles fast but gives the wrong spread of speeds;
            GROMACS 2026 warns against it.

            Andersen, Andersen-massive: redraw speeds at random now and
            then. Only with md-vv, and with nstcomm = 1.

            With integrator = sd or bd no thermostat is used: the friction
            does the job, and GROMACS switches this off by itself.

            Usual value: V-rescale, for everything.
            """)),
    Box("tc_grps", "tc-grps", "Heat groups", section="Temperature",
        when="_thermostat=on",
        help=_h("""
            Which parts of the system get a thermostat of their own, as names
            of index groups separated by spaces. Each group needs its own
            value in ref-t and tau-t, in the same order.

            Giving a protein and its water separate groups stops the
            fast-moving water from heating or cooling the protein unevenly.
            A name has to exist: GROMACS makes standard groups by itself
            (System, Protein, Non-Protein, Water, SOL, Water_and_ions), and
            anything else, such as a membrane group, comes from an index file
            wired into grompp (a Make index block).

            Usual values:
                small, or one component       System
                protein in water, all-atom    Protein Non-Protein
                membrane protein              Protein Membrane Solvent (from an index file)
            """)),
    Box("tau_t", "tau-t", "Thermostat time constant (ps)", section="Temperature",
        when="_thermostat=on",
        help=_h("""
            How quickly the thermostat pulls the temperature back, in ps. A
            larger number is gentler. One value per heat group.

            Usual values:
                V-rescale, all-atom     0.1
                Nose-Hoover             0.5 to 2, often 1.0
                sd integrator           2 (here it sets the friction)
            """)),
    Box("nsttcouple", "nsttcouple", "Thermostat every (steps)", section="Temperature",
        when="_thermostat=on & integrator!=sd|bd",
        help=_h("""
            How often, in steps, the thermostat acts. -1, the default, lets
            GROMACS choose: 100 steps, or fewer when tau-t needs it (with
            tau-t = 0.1 and 2 fs steps it picks 10). Leave it at -1 unless a
            published protocol gives a number.
            """)),
    Box("ld_seed", "ld-seed", "Random seed", section="Temperature",
        when="integrator=sd|bd",
        help=_h("""
            The seed for the random pushes of the sd and bd integrators. -1,
            the default, picks a new seed every time, so the run cannot be
            repeated exactly. Give a fixed number to make it repeatable.

            A run that continues another should not reuse that run's seed,
            or it repeats the same pushes; GROMACS notes this. -1 avoids it.
            """)),
    Box("bd_fric", "bd-fric", "Friction (amu/ps)", section="Temperature",
        when="integrator=bd",
        help=_h("""
            For Brownian dynamics: the friction, in amu/ps. 0, the default,
            works it out from each particle's mass and tau-t instead.
            """)),

    # ---- Pressure -----------------------------------------------------
    Box("ref_p", "ref-p", "Pressure (bar)", section="Pressure",
        when="_barostat=on",
        help=_h("""
            The pressure to hold, in bar (1 bar is about 1 atmosphere). One
            value for isotropic coupling, two for semiisotropic (first the
            membrane plane, then across it), six for anisotropic. GROMACS
            refuses a run with the wrong number of values.

            Usual values:
                everything             1.0
                membrane, semiiso      1.0 1.0
            """)),
    Box("pcoupltype", "pcoupltype", "Directions", kind="choice", section="Pressure",
        choices=("", "isotropic", "semiisotropic", "anisotropic", "surface-tension"),
        when="_barostat=on",
        help=_h("""
            Which ways the box may change shape.

            isotropic: all three directions scale together. For proteins in
            water and anything else without a preferred direction.

            semiisotropic: the two directions in the membrane plane (x and y)
            scale together, and the direction across it (z) on its own. The
            standard for membranes. Needs two values in compressibility and
            in ref-p.

            anisotropic: every direction, and the box angles, on its own, with
            six values. Rarely needed; it can let the box deform.

            surface-tension: holds a surface tension in the membrane plane
            instead; the first ref-p value is then the tension.

            Usual values:
                solutions      isotropic
                membranes      semiisotropic
            """)),
    Box("tau_p", "tau-p", "Barostat time constant (ps)", section="Pressure",
        when="_barostat=on",
        help=_h("""
            How quickly the box responds to a pressure difference, in ps. A
            larger number is gentler. GROMACS's default is 5.

            Usual values:
                C-rescale                   1 to 5
                Parrinello-Rahman, atoms    2 to 5
            """)),
    Box("compressibility", "compressibility", "Compressibility (1/bar)",
        section="Pressure", when="_barostat=on",
        help=_h("""
            How easily the system squeezes, in 1/bar. It sets how far the box
            moves for a given pressure difference. One value per direction
            group, like ref-p.

            Usual values:
                water, all-atom          4.5e-5
                membrane, semiiso        4.5e-5 4.5e-5
            """)),
    Box("nstpcouple", "nstpcouple", "Barostat every (steps)", section="Pressure",
        when="_barostat=on",
        help=_h("""
            How often, in steps, the barostat acts. -1, the default, lets
            GROMACS choose: 100 steps, or fewer when tau-p needs it. Leave it
            at -1 unless a published protocol gives a number.
            """)),
    Box("refcoord_scaling", "refcoord-scaling", "Move restraint points",
        kind="choice", choices=("", "no", "com", "all"), section="Pressure",
        when="_barostat=on",
        help=_h("""
            Only matters with position restraints (-DPOSRES) and a barostat
            together. When the box changes size, do the points the atoms are
            held to move with it?

            no: they stay where they are. GROMACS warns, because this gives
            wrong results.

            com: the restraint pattern moves with the box as a whole (its
            centre of mass is scaled). The usual choice.

            all: every restraint point is scaled with the box.

            Usual value: com, whenever -DPOSRES and a barostat are both on.
            """)),

    # ---- Starting velocities -----------------------------------------
    Box("gen_vel", "gen-vel", "New random velocities", kind="choice",
        choices=("", "yes", "no"), section="Starting velocities",
        when="_run=dynamics",
        help=_h("""
            yes: give every atom a random speed to match gen-temp at the
            start. For the first dynamics run after a minimisation, which has
            no speeds to start from, and for replicas that should differ.

            no: keep the speeds the run starts with, from the structure or
            checkpoint file handed to grompp.

            GROMACS refuses gen-vel = yes together with continuation = yes.

            Usual values:
                first warm-up after minimising    yes
                every run after that              no
            """)),
    Box("gen_temp", "gen-temp", "Velocity temperature (K)",
        section="Starting velocities", when="_run=dynamics & gen_vel=yes",
        help=_h("""
            The temperature, in kelvin, the random speeds are drawn for. Make
            it the same as ref-t. GROMACS's default is 300 K, which is wrong
            for a run held at 310 K.
            """)),
    Box("gen_seed", "gen-seed", "Velocity seed", section="Starting velocities",
        when="_run=dynamics & gen_vel=yes",
        help=_h("""
            The random seed for the new speeds. Give each replica its own
            number and they differ from the first step, repeatably. -1, the
            default, picks a new seed every time, and that cannot be
            repeated.
            """)),
    Box("continuation", "continuation", "Continues a previous run", kind="choice",
        choices=("", "no", "yes"), section="Starting velocities",
        when="_run=dynamics",
        help=_h("""
            yes: this run carries straight on from the one before, so the
            bond lengths of the starting structure are not corrected again.
            For every run that starts where another ended.

            no: a fresh start. Bonds held at a fixed length are set to it at
            the first step.

            Usual values:
                first warm-up after minimising     no
                later warm-ups and production      yes
            """)),

    # ---- Output ---------------------------------------------------------
    Box("nstlog", "nstlog", "Log every (steps)", section="Output",
        help=_h("""
            How often, in steps, energies and progress are written to the
            .log file. 0 writes them only at the end. The default is 1000;
            every 5000 to 10000 steps is plenty for a long run.
            """)),
    Box("nstenergy", "nstenergy", "Energies every (steps)", section="Output",
        help=_h("""
            How often, in steps, the energies, temperature, pressure and box
            size are saved to the .edr file that gmx energy reads. It has to
            be a multiple of nstcalcenergy; GROMACS changes it and warns if it
            is not. The default is 1000. Matching it to the trajectory frames
            (nstxout-compressed) lines the two up.
            """)),
    Box("nstcalcenergy", "nstcalcenergy", "Compute energies every (steps)",
        section="Output",
        help=_h("""
            How often, in steps, the energies are worked out at all; that
            costs time. The default, 100, is right for nearly every run.
            nstenergy and nstlog should be multiples of it.
            """)),
    Box("nstxout", "nstxout", "Full-precision frame every (steps)", section="Output",
        help=_h("""
            How often, in steps, positions are written at full precision to
            the .trr file. These files are big, so most runs write none (0,
            the default) and use the compressed trajectory instead. The final
            positions are saved to the .gro file whatever this says.
            """)),
    Box("nstvout", "nstvout", "Velocities every (steps)", section="Output",
        help=_h("""
            How often velocities are written to the .trr file. 0, the default,
            writes none. The checkpoint file keeps the velocities a run needs
            to continue, so this is only for studying the speeds themselves.
            """)),
    Box("nstfout", "nstfout", "Forces every (steps)", section="Output",
        help=_h("""
            How often forces are written to the .trr file. 0, the default,
            writes none. Only for studying the forces themselves, for example
            the force a pulled molecule feels; a force file of a long run is
            as big as a full-precision trajectory.
            """)),
    Box("compressed_x_precision", "compressed-x-precision", "Frame precision",
        section="Output",
        help=_h("""
            How finely positions are stored in the compressed trajectory.
            1000, the default, keeps them to 0.001 nm, and is what nearly
            every run uses. A smaller number makes a smaller file and a
            coarser record of where the atoms were.
            """)),
    Box("energygrps", "energygrps", "Energy groups", section="Output",
        help=_h("""
            Groups to split the energies between, so gmx energy can report
            for example the interaction between a protein and its ligand.
            Group names separated by spaces; anything but a standard name
            needs an index file.

            More than one group slows the run, and a run on a graphics card
            then works out the short-range forces on the processor instead.
            So the usual way is to leave this empty and get group energies
            afterwards, with gmx mdrun -rerun on the finished trajectory.
            """)),

    # ---- Cut-offs and pair lists -----------------------------------------
    Box("nstlist", "nstlist", "Pair list every (steps)",
        section="Cut-offs and pair lists",
        help=_h("""
            How often, in steps, the list of atom pairs close enough to
            interact is rebuilt. It does not change the accuracy, only the
            speed, and mdrun raises it by itself when that is faster. The
            default is 10.
            """)),
    Box("verlet_buffer_tolerance", "verlet-buffer-tolerance", "Allowed energy drift",
        section="Cut-offs and pair lists",
        help=_h("""
            How much energy error per atom is allowed from pairs that come
            into range between two rebuilds of the pair list, in kJ/mol/ps.
            GROMACS then works out the pair list distance (rlist) by itself.
            The default, 0.005, is right for almost everything.

            -1 switches this off, and rlist is used exactly as given. Only a
            few published protocols do that.
            """)),
    Box("rlist", "rlist", "Pair list distance (nm)", section="Cut-offs and pair lists",
        when="verlet_buffer_tolerance=-1",
        help=_h("""
            The distance, in nm, within which pairs are listed. Only used when
            verlet-buffer-tolerance is -1. It has to be at least as large as
            rcoulomb and rvdw, or GROMACS refuses the run.
            """)),

    # ---- Electrostatics ---------------------------------------------------
    Box("coulombtype", "coulombtype", "Method", kind="choice", section="Electrostatics",
        choices=("", "PME", "Reaction-Field", "Cut-off", "Ewald"),
        help=_h("""
            How charges act on each other.

            PME: every charge feels every other, however far away, worked out
            quickly on a grid (particle mesh Ewald). The standard for
            all-atom force fields.

            Reaction-Field: charges interact directly up to the cut-off, and
            everything beyond it is treated as an even medium. Only for force
            fields that were made with it.

            Cut-off: charges stop interacting at rcoulomb. Crude; for quick
            tests, or for a run input that will not be run (the one genion
            needs).

            Ewald: exact but slow; only for very small systems.

            Usual values:
                all-atom (CHARMM, AMBER, OPLS-AA)    PME
            """)),
    Box("coulomb_modifier", "coulomb-modifier", "Edge at the cut-off", kind="choice",
        section="Electrostatics",
        choices=("", "Potential-shift", "Potential-shift-Verlet", "None"),
        help=_h("""
            How the electrostatic energy is brought to zero at the cut-off.
            Potential-shift, the default (older files write it
            Potential-shift-Verlet), shifts it so there is no jump at the
            edge. None leaves the jump. Leave it as it is unless a force
            field's instructions say otherwise.
            """)),
    Box("rcoulomb", "rcoulomb", "Cut-off (nm)", section="Electrostatics",
        help=_h("""
            The distance, in nm, up to which charges interact directly. With
            PME the rest comes from the grid, so this mostly decides how the
            work is split; with Reaction-Field and Cut-off, charges farther
            apart do not interact directly at all. It belongs to the force
            field: use the value it was made with.

            Usual values:
                CHARMM36              1.2
                AMBER, OPLS-AA        1.0 (0.9 to 1.2 are used)
            """)),
    Box("epsilon_r", "epsilon-r", "Dielectric constant", section="Electrostatics",
        help=_h("""
            Every electrostatic interaction is divided by this. 1, the
            default, for all-atom force fields, where the water itself does
            the screening. Change it only when a force field's instructions
            say so: changing it changes the model.
            """)),
    Box("epsilon_rf", "epsilon-rf", "Dielectric beyond the cut-off",
        section="Electrostatics", when="coulombtype=reaction-field",
        help=_h("""
            For Reaction-Field only: the dielectric constant of the even
            medium assumed beyond the cut-off. 0, the default, means
            infinitely large.
            """)),
    Box("fourierspacing", "fourierspacing", "PME grid spacing (nm)",
        section="Electrostatics", when="coulombtype=pme",
        help=_h("""
            For PME: the spacing of the grid that the far-away part is worked
            out on, in nm. Smaller is more accurate and slower. The default
            is 0.12; 0.16, as in the lysozyme tutorial, is common and fine.
            """)),
    Box("pme_order", "pme-order", "PME order", section="Electrostatics",
        when="coulombtype=pme",
        help=_h("""
            For PME: over how many grid points each charge is spread in each
            direction. 4, the default, is the standard. 6 with a coarser grid
            can be faster on some machines for the same accuracy.
            """)),
    Box("ewald_rtol", "ewald-rtol", "PME accuracy at the cut-off",
        section="Electrostatics", when="coulombtype=pme|ewald",
        help=_h("""
            For PME and Ewald: how much of the direct interaction is left at
            the cut-off, which sets how the work is split between the direct
            part and the grid. The default, 1e-5, is what nearly everybody
            uses.
            """)),

    # ---- Van der Waals ----------------------------------------------------
    Box("vdwtype", "vdwtype", "Method", kind="choice", section="Van der Waals",
        choices=("", "Cut-off", "PME"),
        help=_h("""
            How the attraction and repulsion between atoms that are not
            bonded to each other (the Lennard-Jones interaction) are handled.

            Cut-off: they stop at rvdw, smoothed at the edge as vdw-modifier
            says. The standard for nearly every force field.

            PME: the long-range part is added from a grid (LJ-PME). For the
            few force fields made with it; slower.
            """)),
    Box("vdw_modifier", "vdw-modifier", "Edge at the cut-off", kind="choice",
        section="Van der Waals",
        choices=("", "Potential-shift", "Potential-shift-Verlet", "Force-switch",
                 "Potential-switch", "None"),
        help=_h("""
            How the Lennard-Jones interaction is brought to zero at the
            cut-off.

            Potential-shift: shifts the energy so there is no jump at the
            edge. The default (older files write it Potential-shift-Verlet),
            and what AMBER and OPLS-AA use.

            Force-switch: turns the force off smoothly between rvdw-switch and
            rvdw. CHARMM36 requires it, with rvdw-switch = 1.0 and rvdw = 1.2.

            Potential-switch: turns the energy off smoothly over the same
            range.

            None: a plain cut, with a small jump.

            Usual values:
                CHARMM36                    Force-switch
                AMBER, OPLS-AA              Potential-shift
            """)),
    Box("rvdw", "rvdw", "Cut-off (nm)", section="Van der Waals",
        help=_h("""
            The distance, in nm, beyond which atoms no longer attract or repel
            each other. It belongs to the force field: use its own value.

            Usual values:
                CHARMM36              1.2
                AMBER, OPLS-AA        1.0
            """)),
    Box("rvdw_switch", "rvdw-switch", "Smoothing starts at (nm)",
        section="Van der Waals", when="vdw_modifier=force-switch|potential-switch",
        help=_h("""
            For Force-switch and Potential-switch: where the smoothing
            starts, in nm; it ends at rvdw. CHARMM36 uses 1.0 with rvdw = 1.2.
            """)),
    Box("dispcorr", "dispcorr", "Long-range correction", kind="choice",
        section="Van der Waals",
        choices=("", "no", "EnerPres", "Ener", "AllEnerPres", "AllEner"),
        help=_h("""
            Adds an estimate of the Lennard-Jones attraction beyond the
            cut-off, which the cut-off leaves out.

            no: nothing is added.

            EnerPres: correct both the energy and the pressure. Right for
            liquids with AMBER and OPLS-AA, where it makes the density come
            out right.

            Ener: correct the energy only.

            AllEnerPres, AllEner: the same, also counting pairs the topology
            excludes from each other.

            Usual values:
                AMBER, OPLS-AA                   EnerPres
                CHARMM36                         no
            """)),

    # ---- Bonds and constraints --------------------------------------------
    Box("constraints", "constraints", "Bonds held at a fixed length", kind="choice",
        section="Bonds and constraints",
        choices=("", "none", "h-bonds", "all-bonds", "h-angles", "all-angles"),
        help=_h("""
            Which bonds are held at a fixed length instead of vibrating.
            Holding the fastest vibrations, those of hydrogen atoms, is what
            makes a 2 fs time step possible.

            none: every bond vibrates. Bonds the topology itself marks as
            fixed stay fixed.

            h-bonds: bonds to hydrogen atoms are fixed. The standard for
            all-atom runs; CHARMM36 is made for it.

            all-bonds: every bond is fixed. From older protocols; modern force
            fields do not need it.

            h-angles, all-angles: angles too. Rarely used.

            Usual values:
                all-atom, 2 or 4 fs      h-bonds
                minimisation             none
            """)),
    Box("constraint_algorithm", "constraint-algorithm", "Method", kind="choice",
        section="Bonds and constraints", choices=("", "LINCS", "SHAKE"),
        help=_h("""
            How fixed bonds are kept at their length. LINCS, the default, is
            fast and works in parallel. SHAKE is older and slower, cannot be
            split over several processes, and is needed only for angle
            constraints (h-angles, all-angles), which LINCS should not be used
            with. Water is held rigid by its own method (SETTLE) either way.
            """)),
    Box("lincs_order", "lincs-order", "LINCS order", section="Bonds and constraints",
        help=_h("""
            How many terms LINCS uses to keep bonds at their length. The
            default, 4, suits ordinary runs. A minimisation that has to be
            very exact can need 8.
            """)),
    Box("lincs_iter", "lincs-iter", "LINCS passes", section="Bonds and constraints",
        help=_h("""
            How many correction passes LINCS makes each step. 1, the default,
            is enough for ordinary runs; 2 is more accurate, for a run without
            a thermostat that has to keep its total energy steady.
            """)),
    Box("lincs_warnangle", "lincs-warnangle", "LINCS warning angle (degrees)",
        section="Bonds and constraints",
        help=_h("""
            LINCS warns when a bond turns by more than this many degrees in
            one step, a sign that the time step is too long. The default is
            30.
            """)),
    Box("mass_repartition_factor", "mass-repartition-factor", "Heavier hydrogens (factor)",
        section="Bonds and constraints",
        help=_h("""
            Makes the lightest atoms, the hydrogens in an all-atom system,
            heavier by this factor, taking the extra mass from the atom each
            is bonded to so the total stays the same (hydrogen mass
            repartitioning). Heavier hydrogens vibrate more slowly, which
            allows a 4 fs time step. 1, the default, changes nothing.

            Usual values:
                ordinary run, 2 fs     1
                all-atom, 4 fs         3, with constraints = h-bonds and dt = 0.004
            """)),

    # ---- Drift of the whole system -----------------------------------------
    Box("comm_mode", "comm-mode", "Remove drift", kind="choice",
        section="Drift of the whole system", choices=("", "Linear", "Angular", "None"),
        when="_run=dynamics",
        help=_h("""
            Stops the whole system from slowly sliding through the box, which
            small numerical errors cause over a long run.

            Linear: remove any overall movement in a straight line. The
            default, and right for anything in a periodic box.

            Angular: also remove overall turning. Only for a single molecule
            with no periodic box around it.

            None: remove nothing.
            """)),
    Box("nstcomm", "nstcomm", "Every (steps)", section="Drift of the whole system",
        when="_run=dynamics",
        help=_h("""
            How often, in steps, the drift of the whole system is removed.
            The default, 100, is fine for nearly every run; removing it more
            often costs a little time and changes nothing you would see. The
            Andersen thermostat is the exception and needs 1.
            """)),
    Box("comm_grps", "comm-grps", "Groups", section="Drift of the whole system",
        when="_run=dynamics",
        help=_h("""
            Groups whose drift is removed separately, as index group names
            separated by spaces. Empty, the default, treats the whole system
            as one.

            For a membrane, giving the membrane and the water separate groups
            stops the two from sliding past each other.

            Usual values:
                most systems      empty
                membranes         Membrane Solvent (from an index file)
            """)),

    # ---- Heating and cooling ----------------------------------------------
    Box("annealing", "annealing", "Schedule per heat group", section="Heating and cooling",
        when="_thermostat=on",
        help=_h("""
            Changes the target temperature during the run: heating up slowly,
            or melting and then cooling (simulated annealing). One word per
            heat group in tc-grps:

                no          the temperature stays at ref-t
                single      follow the schedule once, then stay at its last temperature
                periodic    repeat the schedule for the whole run

            The schedule itself goes in the three boxes below.
            """)),
    Box("annealing_npoints", "annealing-npoints", "Points per group",
        section="Heating and cooling", when="_annealing=on",
        help=_h("""
            How many time and temperature pairs each group's schedule has, one
            number per heat group: 3 for a schedule with three points.
            """)),
    Box("annealing_time", "annealing-time", "Times (ps)", section="Heating and cooling",
        when="_annealing=on",
        help=_h("""
            The time of each point, in ps, starting at 0; the groups one after
            another. For one group heated from 200 K to 400 K over 100 ps and
            on to 1000 K by 200 ps: 0 100 200.
            """)),
    Box("annealing_temp", "annealing-temp", "Temperatures (K)",
        section="Heating and cooling", when="_annealing=on",
        help=_h("""
            The temperature at each point, in the same order as the times:
            200 400 1000. Between two points the temperature changes in a
            straight line.
            """)),

    # ---- Frozen atoms -------------------------------------------------------
    Box("freezegrps", "freezegrps", "Frozen groups", section="Frozen atoms",
        help=_h("""
            Groups whose atoms do not move at all, in the directions set
            below, as index group names separated by spaces. For special
            setups such as a fixed surface. Not for keeping a protein in
            shape: position restraints (-DPOSRES) do that better. Frozen
            atoms should not also be under pressure control.
            """)),
    Box("freezedim", "freezedim", "Frozen directions", section="Frozen atoms",
        help=_h("""
            For each frozen group, Y or N for x, y and z, in the same order as
            the groups: Y Y Y holds a group completely, N N Y only stops it
            moving up and down. Two frozen groups need six letters.
            """)),
]


#: GROMACS's own value for every box's option, used where neither the
#: preset, the raw text nor the file sets it, so an empty box shows the
#: number the run will really use. Read from the mdout.mdp that gmx grompp
#: 2026.3 writes for an empty .mdp. gen-seed and ld-seed are taken from the
#: manual: their default, -1, means a new random seed every time, so
#: mdout.mdp shows the seed that was drawn instead. ref-t, tc-grps, tau-t,
#: ref-p, compressibility and the annealing, freezing and group boxes have
#: none: they are empty until somebody fills them in.
GROMACS_DEFAULTS: Dict[str, str] = {
    "integrator": "md",
    "nsteps": "0",
    "dt": "0.001",
    "emtol": "10",
    "emstep": "0.01",
    "nstcgsteep": "1000",
    "pcoupl": "no",
    "tcoupl": "no",
    "nsttcouple": "-1",
    "ld-seed": "-1",
    "bd-fric": "0",
    "pcoupltype": "isotropic",
    "tau-p": "5",
    "nstpcouple": "-1",
    "refcoord-scaling": "no",
    "gen-vel": "no",
    "gen-temp": "300",
    "gen-seed": "-1",
    "continuation": "no",
    "nstlog": "1000",
    "nstenergy": "1000",
    "nstcalcenergy": "100",
    "nstxout": "0",
    "nstvout": "0",
    "nstfout": "0",
    "nstxout-compressed": "0",
    "compressed-x-precision": "1000",
    "nstlist": "10",
    "verlet-buffer-tolerance": "0.005",
    "rlist": "1",
    "coulombtype": "Cut-off",
    "coulomb-modifier": "Potential-shift-Verlet",
    "rcoulomb": "1",
    "epsilon-r": "1",
    "epsilon-rf": "0",
    "fourierspacing": "0.12",
    "pme-order": "4",
    "ewald-rtol": "1e-05",
    "vdwtype": "Cut-off",
    "vdw-modifier": "Potential-shift-Verlet",
    "rvdw": "1",
    "rvdw-switch": "0",
    "dispcorr": "no",
    "constraints": "none",
    "constraint-algorithm": "LINCS",
    "lincs-order": "4",
    "lincs-iter": "1",
    "lincs-warnangle": "30",
    "mass-repartition-factor": "1",
    "comm-mode": "Linear",
    "nstcomm": "100",
}


#: Every option name gmx grompp 2026.3 writes into mdout.mdp, squashed the
#: way GROMACS compares them (lower case, no dashes or underscores). The self
#: test holds every box to it, so a box can never set an option GROMACS
#: does not know.
GROMACS_OPTIONS = frozenset("""
include define integrator tinit dt nsteps initstep simulationpart mts
massrepartitionfactor commmode nstcomm commgrps bdfric ldseed emtol emstep
niter fcstep nstcgsteep nbfgscorr rtpi nstxout nstvout nstfout nstlog
nstcalcenergy nstenergy nstxoutcompressed compressedxprecision
compressedxgrps energygrps cutoffscheme nstlist pbc periodicmolecules
verletbuffertolerance verletbufferpressuretolerance rlist coulombtype
coulombmodifier rcoulombswitch rcoulomb epsilonr epsilonrf vdwtype
vdwmodifier rvdwswitch rvdw dispcorr tableextension energygrptable
fourierspacing fouriernx fourierny fouriernz pmeorder ewaldrtol ewaldrtollj
ljpmecombrule ewaldgeometry epsilonsurface implicitsolvent
ensembletemperaturesetting ensembletemperature tcoupl nsttcouple
nhchainlength printnosehooverchainvariables tcgrps taut reft pcoupl
pcoupltype nstpcouple taup compressibility refp refcoordscaling qmmm
qmmmgrps annealing annealingnpoints annealingtime annealingtemp genvel
gentemp genseed constraints constraintalgorithm continuation shakesor
shaketol lincsorder lincsiter lincswarnangle morse energygrpexcl nwall
walltype wallrlinpot wallatomtype walldensity wallewaldzfac pull awh
rotation imdgroup disre disreweighting disremixed disrefc disretau
nstdisreout orire orirefc oriretau orirefitgrp nstorireout freeenergy
couplemoltype couplelambda0 couplelambda1 coupleintramol initlambda
initlambdastate deltalambda nstdhdl feplambdas masslambdas coullambdas
vdwlambdas bondedlambdas restraintlambdas temperaturelambdas
calclambdaneighbors initlambdaweights initlambdacounts initwlhistogramcounts
dhdlprintenergy scfunction scalpha scpower scrpower scsigma sccoul
scgapsysscalelinpointlj scgapsysscalelinpointq scgapsyssigmalj
separatedhdlfile dhdlderivatives dhhistsize dhhistspacing accgrps accelerate
freezegrps freezedim cosacceleration deform deforminitflow
simulatedtempering simulatedtemperingscaling simtemplow simtemphigh
swapcoords adress user1grps user2grps userint1 userint2 userint3 userint4
userreal1 userreal2 userreal3 userreal4 electricfieldx electricfieldy
electricfieldz densityguidedsimulationactive qmmmcp2kactive colvarsactive
nnpotactive fmmbackend
""".split())


def squash(key: str) -> str:
    """An option name the way GROMACS compares them."""
    return key.strip().lower().replace("-", "").replace("_", "")


#: The values gmx grompp 2026.3 lists as allowed for each option a dropdown
#: sets, as it printed them when handed a wrong one. GROMACS compares them
#: without regard to case, and so does the self test that holds every
#: dropdown to this list.
GROMACS_CHOICES: Dict[str, Tuple[str, ...]] = {
    "integrator": ("md", "steep", "cg", "bd", "nm", "l-bfgs", "tpi", "tpic",
                   "sd", "md-vv", "md-vv-avek", "mimic"),
    "tcoupl": ("No", "Berendsen", "Nose-Hoover", "yes", "Andersen",
               "Andersen-massive", "V-rescale"),
    "pcoupl": ("No", "Berendsen", "Parrinello-Rahman", "Isotropic", "MTTK",
               "C-rescale"),
    "pcoupltype": ("Isotropic", "Semiisotropic", "Anisotropic", "Surface-Tension"),
    "refcoord-scaling": ("No", "All", "COM"),
    "gen-vel": ("no", "yes"),
    "continuation": ("no", "yes"),
    "coulombtype": ("Cut-off", "Reaction-Field", "PME", "Ewald", "P3M-AD",
                    "Poisson", "Switch", "Shift", "User", "Reaction-Field-nec"),
    "coulomb-modifier": ("Potential-shift-Verlet", "Potential-shift", "None",
                         "Potential-switch", "Exact-cutoff", "Force-switch"),
    "vdwtype": ("Cut-off", "Switch", "Shift", "User", "PME"),
    "vdw-modifier": ("Potential-shift-Verlet", "Potential-shift", "None",
                     "Potential-switch", "Exact-cutoff", "Force-switch"),
    "dispcorr": ("No", "EnerPres", "Ener", "AllEnerPres", "AllEner"),
    "constraints": ("none", "h-bonds", "all-bonds", "h-angles", "all-angles"),
    "constraint-algorithm": ("Lincs", "Shake"),
    "comm-mode": ("Linear", "Angular", "None", "Linear-acceleration-correction"),
}
