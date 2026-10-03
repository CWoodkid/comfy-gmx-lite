# 6. NVT equilibration

!!! abstract "In this box"
    Give every atom a speed, warm the system to 298 K, and let the water
    settle around the protein while the protein is held in place. **5
    blocks.** About 2 minutes online.

Published tutorial:
[Step Six: Equilibration](http://www.mdtutorials.com/gmx/lysozyme/06_equil.html).

## What it does, and why

The minimised system is still: no atom moves. Before the real run, two
things must settle, the temperature and then the pressure. This box does the
temperature. *NVT* is short for what stays fixed: the Number of atoms, the
Volume of the box and the Temperature.

- At the start every atom gets a random speed, chosen so that all the
  speeds together match a temperature of 298 K. A *thermostat*, the part of
  the run that keeps the temperature at its target, then holds it at 298 K
  by speeding the atoms up or slowing them down a little at every step.
- The protein's heavy atoms, every atom but the hydrogens, are held in
  place by *position restraints*: springs that pull each atom back to where
  it was after the minimisation. The water was placed around a protein that
  did not move, so it needs time to arrange itself. Without the springs, the
  first rough moments could push the protein out of shape. Which atoms get
  a spring is the list that box 1 wrote; the line `define = -DPOSRES` in
  the preset's settings file switches the springs on.

The blocks:

- **Run parameters (.mdp)** starts from the preset `lysozyme_nvt`, the
  published `nvt.mdp`, and changes three values. The run is 2,500 steps of
  2 femtoseconds (a femtosecond is a thousandth of a picosecond), 5 ps in
  all, where the published run is 100 ps. The thermostat is given 0.1 ps
  instead of 1 ps to pull the temperature back: with the published value,
  the temperature was still at 278 K after 5 ps, short of the target. And
  the energies are saved every 50 steps instead of every 2,500, so that
  even this short run gives enough points for a curve.
- **Preprocess (grompp)** takes the minimised structure twice: once as the
  starting positions, and once, on its **restraint (-r)** dot, as the
  positions the springs pull towards.
- **Run MD (mdrun)** runs it.
- **Energy terms** takes the temperature out of the energy file, and
  **Preview plot** draws it.

## What you will build

[![The finished box: five blocks, each with its number](../pictures/lysozyme/box-5.webp){ .canvas }](../pictures/lysozyme/box-5.webp)

## Build it

--8<-- "_generated/lysozyme/box-5-build.md"

## Run it, and look

Press **Run**. The run takes almost 2 minutes online.

[![The box after the run, with its plot](../pictures/lysozyme/box-5-results.webp){ .canvas }](../pictures/lysozyme/box-5-results.webp)

[![The temperature over the 5 ps](../pictures/lysozyme/plot_temp.webp){ .canvas }](../pictures/lysozyme/plot_temp.webp)

The temperature starts at 300 K and falls at once, to 210 K after 0.1 ps in
our run. Then it climbs back. From 0.9 ps on it stays within 5 K of
298 K: over the second half of the run it averaged 298.5 K.

!!! question "Why does the temperature fall first?"
    Temperature measures how fast the atoms move. After the minimisation,
    every atom sits where the pulls on it balance. The speeds handed out at
    the start carry the atoms away from those places, and the pulls slow
    them down again. Part of the energy handed out as speed goes into
    stretching and squeezing the system instead. So the temperature drops,
    and the thermostat has to put the missing energy back in.

## Under the hood

The run's whole settings file, `nvt.mdp`, is folded away under ① below:
click its name to open it.

--8<-- "_generated/lysozyme/box-5-commands.md"
