# Comfy-gmx lite

Comfy-gmx lite is a visual editor for GROMACS, the molecular dynamics
program, made for teaching. A simulation is built in a web browser by
connecting blocks on a canvas. Each block carries out one step, such as
downloading a protein, placing it in water, running the simulation or
measuring the result. Each block also shows the command it runs, the files it
writes and the numbers it produces. GROMACS does the computing underneath.

[![Open in Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/)
[![Tutorials website](https://img.shields.io/badge/Tutorials-website-4f9dd8?logo=materialformkdocs&logoColor=white)](https://cwoodkid.github.io/comfy-gmx-lite/)
[![Made with love](https://img.shields.io/badge/Made%20with-%E2%99%A5-ff69b4)](https://www.linkedin.com/in/mehmet-can-karakurt-39756668/)

## Purpose

Comfy-gmx lite is designed for a first lesson in molecular dynamics. A class
can run a complete simulation, from a structure to plots and a movie, within
one lesson, on any computer with a web browser and nothing installed. Every
step stays open to inspection, so learners can follow what the simulation
does and why, instead of treating it as a black box.

It is the teaching edition of Comfy-gmx, a larger research tool. It keeps
what its two tutorials need, plus a few everyday GROMACS tools, so a
first-time user sees 28 blocks rather than hundreds.

## Capabilities

- Simulations are graphs of blocks joined by wires. The 28 blocks cover
  loading and downloading files, preparing a structure, building a system
  (box, water, ions, added molecules, an ice crystal), preparing and running
  GROMACS, processing trajectories, analysis (energies, RMSD, radius of
  gyration, secondary structure, hydrogen bonds, density, ice counting, the
  water left in a drop) and previews, including one that sets two or three
  graphs side by side. One more block grows a snowflake in a simple model of
  water vapour freezing, not of molecules, and shows it as a picture.
- Every block and every setting carries a plain-language explanation. Each
  tutorial also explains its steps in notes on the canvas.
- The first time the page opens in a browser tab, a two-minute tour shows how
  to work it with your hands: clicking, dragging, wires, moving around,
  zooming, right-click menus, undo and running. Each of its ten slides has a
  small moving picture, for a mouse or for a touchpad, whichever you say you
  use. **?** → **Show the basics** brings it back, and a tick box stops it
  opening by itself.
- **Check** lists missing connections and unusable settings before anything
  runs. Beside **Run**, a line says how many blocks will run, how many stored
  results will be reused, and roughly how long the run will take.
- Results appear inside the blocks: plots, three-dimensional views of the
  molecules, and movies of the trajectory.
- Finished results are stored. A block whose settings and inputs have not
  changed is not run again: it is marked **cached** and its stored result is
  reused. Changing one setting reruns only the blocks that depend on it.
- Run-parameter blocks have a box for each of 65 common GROMACS settings: the
  most used on the block, the rest in drawers by topic, each explained with
  the values usually used. Every box shows the value the setting will have in
  the run, including the GROMACS default for a setting left empty, and a
  summary on the block says in words what the settings add up to. An `.mdp`
  file of your own, or pasted text, works too.
- The **Terminal** drawer under the canvas has two tabs. **Run** follows a
  run as it happens, with every command and its output. **Shell** is a command
  line (Bash) on the computer that runs the simulations, for looking at files,
  editing them with `nano`, or running `gmx` by hand. Several can be open at
  once, each in a tab of its own.
- The panels on either side of the canvas can be put away, so the graph gets
  the whole width: **◂** on the left, **▸** on the right, or **Ctrl+[** and
  **Ctrl+]**. A slim tab left on the canvas's edge brings each one back.
- The **Command**, **Log** and **Files** tabs show each block's exact
  commands, its output, and every file it wrote, ready to download.
- Graphs are saved and shared as JSON files. **Export scripts** writes a graph
  out as a folder of shell scripts with the same GROMACS commands, to run
  elsewhere, for example on a computing cluster.
- Seven chunks, ready-made groups of blocks such as an energy minimisation, an
  equilibration or a standard analysis, can be dropped into any graph.

## Tutorials

| tutorial | what happens | time on mybinder.org |
| --- | --- | --- |
| **An ice cube melting** | a small ice cube is heated from 200 K to 1000 K in one run: it melts into a drop, and the drop then boils away into a gas. Extra parts, switched off at first, do the same with salt in the ice, and cool the pure and the salty gas back down: each gathers into a drop again, but the ice does not come back | about 3 minutes, and about as long again for each of the three extra boxes |
| **Lysozyme in Water** | the classic first GROMACS tutorial: a protein in a box of water, from download to analysis | about 9 minutes |

The times run from pressing **Run** until the last block finishes. They were
measured on mybinder.org in September 2026, where each copy had one
processor. The extra boxes of the ice tutorial were timed on one processor
of a workstation instead.

To build a tutorial yourself, box by box, follow the
[tutorial website](https://cwoodkid.github.io/comfy-gmx-lite/): which blocks
to add, which settings to change, which wires to draw, what comes out, and
the GROMACS commands behind every block.

## Running online

The button above starts a private copy of Comfy-gmx lite on
[mybinder.org](https://mybinder.org), a free public service. The copy works
in any web browser (Windows, macOS, Linux or ChromeOS) and installs nothing
on the computer.

1. Press the button. After a change to this repository, the first start can
   take several minutes while mybinder.org builds the copy. Later starts take
   under a minute.
2. When the editor opens, click **Tutorials** at the top of the list on the
   left, choose a tutorial, and press **Load as new graph**.
3. Press **Run**. Each block gets a green border when it finishes, and its
   results appear inside it.

Limits of mybinder.org:

- Each copy has at least 1 GB and at most 2 GB of memory. The copies that
  gave the times above had one processor each.
- A copy closes after 10 minutes without activity. A running tutorial counts
  as activity, because the page keeps asking the copy for news, and so does
  working on the page.
- A session lasts up to six hours, or up to one processor-hour when it
  computes heavily.
- Nothing is kept when a copy closes. Results should be downloaded from the
  **Files** tab first.
- At most 100 people can use copies of this repository at the same time.

## Use in a class

- Share the link behind the button. Each person gets a separate copy, so
  nobody can affect anybody else's work.
- Start the copies at the beginning of the lesson, not when they are needed.
- The page opens with a two-minute tour of the mouse, the touchpad and the
  keys. Let everyone go through it before loading a tutorial: dragging,
  right-clicking and Ctrl+Z are not obvious to somebody who mostly uses a
  phone. **?** → **Show the basics** opens it again.
- Load the tutorial and press **Run** first, then read the notes on the canvas
  while it works. Each tutorial explains itself step by step.
- Lysozyme in Water is a shortened version of a published tutorial. Its notes
  say where a run was shortened, and how long the original is.
- Teacher's notes for the ice tutorial are in
  [docs/ice-melting.md](docs/ice-melting.md). What each tutorial produced, and
  how long each part took, is in [docs/tutorial-runs.md](docs/tutorial-runs.md).
- If mybinder.org is busy or down on the day, the same copy runs on any
  computer with Docker, or on a JupyterHub. [binder/README.md](binder/README.md)
  explains how.

## Running on a local computer

Comfy-gmx lite needs Python 3.9 or newer with numpy, and GROMACS. It has been
tested with GROMACS 2026.3. On Linux or macOS:

```bash
git clone https://github.com/CWoodkid/comfy-gmx-lite.git
cd comfy-gmx-lite
./start.sh
```

`./start.sh` checks what the machine has and opens <http://localhost:8189> in
the browser. If it cannot find GROMACS, it says so. **Settings** can then
point to the `GMXRC` file of an installed GROMACS, or **Environments → Build
from source** can build one. Runs and settings are kept in
`~/.comfy-gmx-lite`. `./run.sh --help` lists other ways to start the editor.

A computer that is already running another simulation is shared rather than
fought over. Left to itself, GROMACS takes every core and the graphics card,
and two simulations on the same cores both become slow. So just before a
simulation starts, the editor looks at which cores and graphics cards other
programs are using. The simulation is kept to the free cores and starts that
many threads. When another simulation holds the graphics card, the new one
keeps off it or shares it, as **Settings → This computer** says; by default
the question comes when **Run** is pressed. When every core is held by
another simulation, the new one waits until some come free; its block says
*waiting for free cores*, and **Cancel** stops the wait. On a computer with
nothing else running nothing changes, and a block whose threads are set by
hand keeps them. The block's log says what was chosen and why.

On Windows, use WSL (Linux inside Windows), or Docker with the files in
[binder/](binder/).

## What is included

The editor has 28 blocks, two tutorials and seven chunks. Compared with the
full Comfy-gmx, this edition leaves out coarse-grained (Martini) simulations,
membrane builders, ligands, and installers for programs other than GROMACS.

## Documentation

| file | contents |
| --- | --- |
| [the tutorial website](https://cwoodkid.github.io/comfy-gmx-lite/) | both tutorials, box by box, to build by hand; its pages are in [website/](website), and [website/README.md](website/README.md) says how they are made |
| [docs/nodes.md](docs/nodes.md) | every block and its settings |
| [docs/tutorials.md](docs/tutorials.md) | the two tutorials, what was shortened in them and why, and how to cite them |
| [docs/ice-melting.md](docs/ice-melting.md) | the ice tutorial: what it shows, the science for the teacher, and how it was set up |
| [docs/tutorial-runs.md](docs/tutorial-runs.md) | what each tutorial produced, and how long each part took |
| [binder/README.md](binder/README.md) | how the online copy is built, and how to run it with Docker or on a JupyterHub |

## Sources

Lysozyme in Water turns a published tutorial into blocks. The original
explains far more than the notes in the editor, and work that uses it should
cite it:

- Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
  Tutorials for the GROMACS-2018 Molecular Simulation Package. *Living J.
  Comput. Mol. Sci.* 1(1), 5068.
  [doi:10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068).
  The tutorial itself is at <http://www.mdtutorials.com/gmx/lysozyme/>.

The ice tutorial was written for Comfy-gmx lite. Its references are in
[docs/ice-melting.md](docs/ice-melting.md).

## Licence

MIT. See [LICENSE](LICENSE).
