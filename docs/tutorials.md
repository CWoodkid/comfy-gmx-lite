# The three tutorials

Open the **Tutorials** tab in the list on the left, pick one, read what it
needs, and press **Load as new graph**. Then press **Run**. Every tutorial
explains itself in notes on the canvas, step by step, so the notes are the
thing to read while it runs.

| # | Tutorial | Blocks | Where it comes from |
|---|---|---|---|
| 1 | [Lysozyme in Water](http://www.mdtutorials.com/gmx/lysozyme/) | 50 | the first of Justin A. Lemkul's GROMACS tutorials |
| 1 | [Lipids I: a bilayer that builds itself](https://cgmartini.nl/docs/tutorials/Martini3/LipidsI/index.html) | 31 | the first Martini 3 tutorial, by the Martini team |
| 1 | [An ice cube melting](ice-melting.md) | 27 | written for this version |

The first two are *translations* of a published tutorial's commands into
blocks, with that tutorial's own settings files. The explanations on those
sites are the authors' and are not copied here: each step carries a short
summary of our own and a link to the page it came from. **Read the tutorial;
run this.** How long each one takes, and what it came out as, is in
[tutorial-runs.md](tutorial-runs.md).

## What was shortened, and why

A lesson has fifteen or twenty minutes for a run, and an online session has one
processor. The published tutorials are written for a workstation and an
afternoon, so the long runs are cut down. Everything else — the force field,
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

**Lipids I: a bilayer that builds itself**

| run | the published tutorial | here |
|---|---|---|
| self-assembly | 30 ns | 30 ns, as published |
| equilibration of the bilayer | 30 ns | 10 ns |

One block is added: **Turn the membrane flat**. The bilayer forms facing
whichever direction chance picks, and everything after it assumes it lies flat
in the x–y plane. The tutorial says to check and turn it by hand with
`gmx editconf -rotate`; the block does that check and that turn. In 8 test runs
of the self-assembly, 7 had formed a bilayer at 30 ns, and the eighth had by
60 ns. Only 3 of the 7 happened to lie flat; the block turned the other 4.

**An ice cube melting** was written to fit: two runs of 100 ps each. Its
teacher's notes are in [ice-melting.md](ice-melting.md).

## If you use them, cite them

> Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
> Tutorials for the GROMACS-2018 Molecular Simulation Package.
> *Living J. Comput. Mol. Sci.* **1**(1), 5068.
> doi:[10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068)

> Souza, P. C. T. *et al.* (2021) Martini 3: a general purpose force field for
> coarse-grained molecular dynamics. *Nature Methods* **18**, 382–388.
> doi:[10.1038/s41592-021-01098-3](https://doi.org/10.1038/s41592-021-01098-3)

The references for the ice tutorial are at the end of
[ice-melting.md](ice-melting.md).
