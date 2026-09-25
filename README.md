# Comfy-gmx lite

Molecular dynamics for a first lesson. You build a simulation by wiring blocks
together on a page in your web browser — download a protein, put it in water,
let it move, measure what happened — and GROMACS, the simulation program, does
the work underneath. Every block says what it does and why, and every step can
be looked at: the files it wrote, the command it ran, the numbers it produced.

It comes with two tutorials, each short enough to run in a lesson on a single
processor:

| tutorial | what happens | time on one processor |
| --- | --- | --- |
| **An ice cube melting** | a tiny ice cube at room temperature melts into a drop; the same cube in deep cold holds | about 3 minutes |
| **Lysozyme in Water** | the classic first GROMACS tutorial: a protein in a box of water, from download to analysis | about 8 minutes |

Comfy-gmx lite is the teaching version of Comfy-gmx, a larger program by the
same author, cut down to what these tutorials need and a few everyday GROMACS
tools, so that a first-time user sees 25 blocks instead of hundreds.

## Try it online — nothing to install

[![Open in Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/)

The button opens a copy of Comfy-gmx lite of your own, on
[mybinder.org](https://mybinder.org), in any web browser on any computer —
Windows, macOS, Linux or a Chromebook. Nothing is installed on your computer.

1. Press the button. The first start after a change to this repository can take
   several minutes while mybinder.org prepares the copy; after that it takes
   under a minute.
2. The editor opens. Click **Tutorials** at the top of the list on the left,
   pick one, and press **Load as new graph**.
3. Press **Run**. Each block gets a green border when it has finished, and its
   results — plots, pictures of the molecules, movies — appear inside it.

What to know about mybinder.org, a free public service:

- Each person gets **one processor and 2 GB of memory**. The times above are for
  exactly that.
- A copy is **closed after about 10 minutes with nobody using it**, and after 6
  hours in any case. While a tutorial is running, the page keeps asking the copy
  how it is getting on, and that counts as using it; so does moving the mouse or
  typing on the page. A tab left open with nothing running and nobody at it
  closes after 10 minutes, as the site intends.
- **Nothing is kept** when a copy closes. To keep a result, download it from the
  **Files** tab first.
- Up to 100 people can use copies of the same repository at the same time.

## For a class

Send everybody the link behind the button above. Each person gets a copy of
their own, so nobody can break anybody else's.

- Start the copies at the beginning of the lesson, not when they are needed.
- Load the tutorial and press **Run** first, then read the notes on the canvas
  while it works: every tutorial explains itself in its notes, step by step.
- The runs are short versions of the published tutorials. The notes say
  where a run was shortened, and how long the original is.
- The teacher's notes for the ice tutorial are in
  [docs/ice-melting.md](docs/ice-melting.md). What each tutorial came out as
  when it was run here, and how long each part took, is in
  [docs/tutorial-runs.md](docs/tutorial-runs.md).

If mybinder.org is busy or down on the day, the same copy can run on any
computer with Docker, or on a JupyterHub of your own:
[binder/README.md](binder/README.md) explains how.

## Run it on your own computer

It needs Python 3.9 or newer with numpy, and GROMACS (2026.3 is what it was
tested with). On Linux or macOS:

```bash
git clone https://github.com/CWoodkid/comfy-gmx-lite.git
cd comfy-gmx-lite
./start.sh
```

`./start.sh` checks what this machine has and opens <http://localhost:8189>
in your browser. If it cannot find GROMACS it says so: point **Settings** at the
`GMXRC` file of the GROMACS you have, or build one with **Environments → Build
from source**. Runs and settings are kept in `~/.comfy-gmx-lite`.
`./run.sh --help` lists the other ways to start it.

On Windows, use WSL (Linux inside Windows), or Docker with the files in
[binder/](binder/).

## What is in it

- **25 blocks**: loading and downloading files, preparing a protein, building
  a system (box, water, ions, other molecules, an ice crystal), running
  GROMACS, processing a trajectory, measuring (energies, RMSD, radius of
  gyration, secondary structure, density, counting ice), and seeing the
  results. [docs/nodes.md](docs/nodes.md) lists every block and its settings.
- **2 tutorials**, described in [docs/tutorials.md](docs/tutorials.md).
- **7 chunks**: ready-made groups of blocks — a minimisation, an equilibration,
  a standard analysis — to drop into a graph of your own.

Everything else that the full Comfy-gmx does — coarse-grained (Martini)
simulations, membrane builders, ligands, installing other programs — was left
out.

## Where the tutorials come from

Lysozyme in Water is a translation into blocks of a published tutorial. Read
the original; it explains far more than the notes here. If you use it, cite it:

- Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
  Tutorials for the GROMACS-2018 Molecular Simulation Package. *Living J.
  Comput. Mol. Sci.* 1(1), 5068.
  [doi:10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068) —
  the tutorial itself is at <http://www.mdtutorials.com/gmx/lysozyme/>.

The ice tutorial was written for this version; its references are in
[docs/ice-melting.md](docs/ice-melting.md).

## Licence

MIT — see [LICENSE](LICENSE).
