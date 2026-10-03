# Comfy-gmx lite tutorials

Comfy-gmx lite runs molecular dynamics simulations in a web browser. You do
not type commands: you put **blocks** on a canvas and join them with
**wires**. Each block does one step, such as building a box of water,
running GROMACS or drawing a graph. Each wire carries a file from the block
that makes it to the block that needs it.

The editor comes with two tutorials, ready to load and run. This site takes
them apart, box by box, so that you can **build them yourself**: which blocks
to add, which settings to change, which wires to draw, what you should see at
the end, and the GROMACS commands behind every block.

<div class="grid cards" markdown>

-   :material-snowflake:{ .lg .middle } **[An ice cube melting](ice/index.md)**

    ---

    A tiny ice cube heated from colder than any freezer to hotter than any
    kettle: it melts into a drop, and the drop boils away. Made for a school
    workshop. About 3 minutes online.

-   :material-molecule:{ .lg .middle } **[Lysozyme in water](lysozyme/index.md)**

    ---

    The classic first GROMACS tutorial: a protein in a box of water,
    neutralised, minimised, equilibrated, run and analysed. Every run cut
    short so it fits a lesson. About 9 minutes online.

</div>

## Open Comfy-gmx lite

**Online**, with nothing to install: [![Open in Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/){ .binder-button }

The button opens it on mybinder.org; the same button is in the bar at the top
of every page. The first start takes a minute or two, longer just after the
program has changed. Each person gets a copy of their own. It closes after
10 minutes without activity, and nothing in it is kept. To keep a graph you
built, press **Export JSON**: it saves the graph as a file on your own
computer. **Import JSON** brings it back into a new copy later.

**On your own computer**: the
[README](https://github.com/CWoodkid/comfy-gmx-lite#running-on-a-local-computer)
says how to install it.

## Two ways to use a tutorial

1. **Load it ready-made.** Open **Tutorials** on the left, click the
   tutorial, press **Load as new graph**, then **Run**. Read the notes on the
   canvas while it works.
2. **Build it yourself**, with these pages. Start from an empty canvas and
   follow the boxes in order. Each page says what its box is for, shows it
   finished, and goes through its blocks one by one. Building it once by hand
   is the best way to see how the steps of a simulation hang together.

Both ways end with the same graph, so you can always load the ready-made one
next to yours and compare: **+** beside the tabs at the top gives a second,
empty tab to load it into.

## New to the mouse and keyboard?

The editor opens with a two-minute tour of clicking, dragging, wiring, moving
around and right-clicking. **?** at the top right, then **Show the basics**,
brings it back. [Before you start](basics.md) shows the parts of the screen
and the few things you do again and again in these tutorials.

## Where the tutorials come from

**Lysozyme in water** turns the first of Justin A. Lemkul's GROMACS
tutorials into blocks. The original explains far more than these pages, and
each page here links to the step it follows. Work that uses it should cite
it:

> Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
> Tutorials for the GROMACS-2018 Molecular Simulation Package. *Living J.
> Comput. Mol. Sci.* 1(1), 5068.
> [doi:10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068)

**An ice cube melting** was written for Comfy-gmx lite. Its science, and what
a class should see, are in the
[teacher's notes](https://github.com/CWoodkid/comfy-gmx-lite/blob/main/docs/ice-melting.md).
