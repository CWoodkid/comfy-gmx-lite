# The two tutorials

Open the **Tutorials** tab in the list on the left, pick one, read what it
needs, and press **Load as new graph**. Then press **Run**. Every tutorial
explains itself in notes on the canvas, step by step, so the notes are the
thing to read while it runs.

| # | Tutorial | Blocks | Where it comes from |
|---|---|---|---|
| 1 | [Lysozyme in Water](http://www.mdtutorials.com/gmx/lysozyme/) | 50 | the first of Justin A. Lemkul's GROMACS tutorials |
| 1 | [An ice cube melting](ice-melting.md) | 27 | written for this version |

Lysozyme in Water is a *translation* of a published tutorial's commands into
blocks, with that tutorial's own settings files. The explanations on its site
are the author's and are not copied here: each step carries a short summary of
our own and a link to the page it came from. **Read the tutorial; run this.**
How long each one takes, and what it came out as, is in
[tutorial-runs.md](tutorial-runs.md).

## What was shortened, and why

A lesson has fifteen or twenty minutes for a run, and an online session has one
processor. The published tutorial is written for a workstation and an
afternoon, so its long runs are cut down. Everything else — the force field,
the water, the box, the settings of each run — is as published. The notes on
the canvas say where a run was shortened, and to make one longer, raise
`nsteps` in its *Run parameters (.mdp)* block.

**Lysozyme in Water**

| run | the published tutorial | here |
|---|---|---|
| NVT equilibration (temperature) | 100 ps | 5 ps |
| NPT equilibration (pressure) | 500 ps | 5 ps |
| production | 10 ns | 10 ps |

Two settings change with the lengths, because the published ones are made for
the long runs. The thermostat corrects the temperature in 0.1 ps instead of 1 ps
(`tau-t`), and in the pressure run the barostat corrects in 1 ps instead of 5
(`tau-p`). With the published values, 5 ps is not long enough for either to
finish its job: the temperature, which drops sharply the moment the speeds are
handed out, was still at 278 K after 5 ps instead of 298 K, and the density was
still rising in a straight line. With the faster values the temperature is back
at 298 K within 1.5 ps, and the density reaches about 1025 kg/m³, the value the
tutorial reports.

Ten picoseconds of a protein is enough to see every step of the workflow and
every analysis working, but not enough for the numbers to mean much: the
protein has barely started to move. The tutorial's own 10 ns would take about
two days on one processor.

**An ice cube melting** was written to fit: two runs of 100 ps each. Its
teacher's notes are in [ice-melting.md](ice-melting.md).

## If you use Lysozyme in Water, cite it

> Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
> Tutorials for the GROMACS-2018 Molecular Simulation Package.
> *Living J. Comput. Mol. Sci.* **1**(1), 5068.
> doi:[10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068)

The references for the ice tutorial are at the end of
[ice-melting.md](ice-melting.md).
