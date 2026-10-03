# Lysozyme in water

Lysozyme is a small protein, 129 amino acids long, found in egg white and in
tears. There it protects against bacteria by breaking open their walls. This
tutorial puts one lysozyme molecule in a box of water and takes it through
every step of a standard simulation: tell GROMACS what its atoms are and how
they are joined, surround it with water, cancel its electric charge, pull
apart atoms that sit too close, warm it up, let the box settle to the right
pressure, run it, and look at what it did.

It follows Justin A. Lemkul's tutorial
[Lysozyme in Water](http://www.mdtutorials.com/gmx/lysozyme/) step by step,
with the same commands and the same settings files. The one big difference:
every run is cut short, so the whole tutorial takes minutes instead of days.

[![The whole tutorial on the canvas: eight boxes](../pictures/lysozyme/whole.webp){ .canvas }](../pictures/lysozyme/whole.webp)

To build along, open Comfy-gmx lite in another tab: [![Open in Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/){ .binder-button }

## The boxes

The boxes carry the step numbers of the published tutorial, so that each
page here matches one page there. The published step 2 only reads a file and
runs nothing, so it shares a box with step 1.

| box | what it does | blocks |
| --- | --- | --- |
| [1–2. Topology](1-topology.md) | downloads the protein and the force field, removes the crystal water, and writes the topology: what every atom is, and how the atoms are joined | 4 |
| [3. Box and solvent](3-box.md) | puts the protein in a box and fills the box with water | 2 |
| [4. Add ions](4-ions.md) | swaps 8 water molecules for chloride ions, so the whole box has no net charge | 2 |
| [5. Energy minimisation](5-minimisation.md) | moves the atoms out of each other's way before anything is allowed to move freely | 5 |
| [6. NVT equilibration](6-nvt.md) | warms the water to 298 K while the protein is held in place | 5 |
| [7. NPT equilibration](7-npt.md) | lets the box shrink or grow until the pressure is right | 7 |
| [8. Production MD](8-production.md) | the run itself, with the protein free | 3 |
| [9–10. Analysis](9-analysis.md) | how far the protein moved, how compact it stayed, its helices and hydrogen bonds, and a movie | 12 |

## What is shortened, and why

A lesson has a quarter of an hour for a run, and a copy of the editor opened
online, on mybinder.org, has one processor. The published runs are made for
a workstation and an afternoon, so three of them are cut down:

| run | published | here |
| --- | --- | --- |
| NVT equilibration (temperature) | 100 ps | 5 ps |
| NPT equilibration (pressure) | 500 ps | 5 ps |
| production | 10 ns | 10 ps |

A picosecond (ps) is a millionth of a millionth of a second; a nanosecond
(ns) is a thousand picoseconds.

Two settings change along with the run lengths. The *thermostat*, the part
of the run that keeps the temperature at its target, is given 0.1 ps instead
of 1 ps to pull the temperature back. The *barostat*, which does the same
for the pressure, is given 1 ps instead of 5. The published values suit the
long runs. In a run of only 5 ps, neither would finish its job in time.

The short runs also save their energies and pictures more often: every
0.1 ps. The published runs save every 1, 5 or 10 ps. Saving that rarely
would leave these short runs only two to six points to draw a curve through.

Each page says where its box differs from the published step. To make a run
longer, raise **Number of steps** on the run's **Run parameters (.mdp)**
block.

Everything else follows the published tutorial: the protein, the water, the
box, the ions, the temperature, the pressure, and every other setting of
every run. The analysis differs in two small ways. The hydrogen bonds are
counted over the whole protein at once, where the published tutorial counts
the bonds between backbone atoms and the bonds between side chains
separately. And times are shown in picoseconds instead of nanoseconds,
because the runs are so short.

!!! note "A newer force field release"
    The tutorial downloads the July 2022 release of the CHARMM36 force field,
    the rules for how the atoms push and pull on each other. The published
    tutorial has since moved to a newer release. Expect small differences
    between the numbers here and the published ones.

## How long it takes

On mybinder.org, with one processor, the whole tutorial takes about
9 minutes from **Run** to the last block. The production run takes about
4 minutes of it, each of the two equilibration runs (boxes 6 and 7) about 2,
and the minimisation under 1. Everything else takes seconds.

At that speed, the published 10 ns production run alone would take about
2½ days.

## What you need to know first

The pages say in a few sentences what each box is for. The published
tutorial explains the reasons behind each step in far more depth, and each
page here links to the step it follows: read the two side by side. If
adding, wiring and running blocks are new to you, read
[Before you start](../basics.md) first.

## Credit

The steps and settings files are Justin A. Lemkul's. The explanations on
these pages are our own. Work that uses the tutorial should cite it:

> Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
> Tutorials for the GROMACS-2018 Molecular Simulation Package. *Living J.
> Comput. Mol. Sci.* 1(1), 5068.
> [doi:10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068)
