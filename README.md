# Comfy-gmx lite

I made Comfy-gmx lite for a first lesson in molecular dynamics. You build a
simulation by wiring blocks together on a page in your web browser: download a
protein, put it in water, let it move, and measure what happened. GROMACS, the
simulation program, does the work underneath. Every block says what it does
and why, and you can look at every step: the files it wrote, the command it
ran, the numbers it produced.

It comes with two tutorials. Each one is short enough to run in a lesson on a
single processor:

| tutorial | what happens | time online |
| --- | --- | --- |
| **An ice cube melting** | a tiny ice cube, heated from 200 K to 1000 K in one run, melts into a drop, and the drop boils away into a gas | about 3 minutes |
| **Lysozyme in Water** | the classic first GROMACS tutorial: a protein in a box of water, from download to analysis | about 9 minutes |

I measured these times on mybinder.org, where each person gets one processor.
They run from pressing **Run** until the last block has finished.

Comfy-gmx lite is the teaching version of Comfy-gmx, a larger program I wrote.
I cut it down to what these tutorials need, plus a few everyday GROMACS tools,
so that a first-time user sees 25 blocks instead of hundreds.

## Try it online, with nothing to install

[![Open in Binder](https://mybinder.org/badge_logo.svg)](https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/)

The button opens your own copy of Comfy-gmx lite on
[mybinder.org](https://mybinder.org). It works in any web browser on any
computer: Windows, macOS, Linux or a Chromebook. Nothing gets installed on your
computer.

1. Press the button. The first start after I change this repository can take
   several minutes while mybinder.org prepares the copy. After that it takes
   under a minute.
2. The editor opens. Click **Tutorials** at the top of the list on the left,
   pick one, and press **Load as new graph**.
3. Press **Run**. Each block gets a green border when it has finished, and its
   results (plots, pictures of the molecules, movies) appear inside it.

A few things to know about mybinder.org, which is a free public service:

- Each person gets one processor and 2 GB of memory. The times above are for
  exactly that.
- mybinder.org closes a copy after about 10 minutes with nobody using it, and
  after 6 hours in any case. While a tutorial runs, the page keeps asking the
  copy how it is getting on, and that counts as using it. So does moving the
  mouse or typing on the page. A tab left open with nothing running and nobody
  at it closes after 10 minutes, as the site intends.
- Nothing is kept when a copy closes. To keep a result, download it from the
  **Files** tab first.
- Up to 100 people can use copies of this repository at the same time.

## For a class

Send everybody the link behind the button above. Each person gets a copy of
their own, so nobody can break anybody else's.

- Start the copies at the beginning of the lesson, not when you need them.
- Load the tutorial and press **Run** first, then read the notes on the canvas
  while it works. Every tutorial explains itself in its notes, step by step.
- Lysozyme in Water is a shortened version of a published tutorial. Its notes
  say where I shortened a run, and how long the original is.
- My teacher's notes for the ice tutorial are in
  [docs/ice-melting.md](docs/ice-melting.md). What each tutorial came out as
  when I ran it, and how long each part took, is in
  [docs/tutorial-runs.md](docs/tutorial-runs.md).

If mybinder.org is busy or down on the day, the same copy runs on any computer
with Docker, or on a JupyterHub of your own.
[binder/README.md](binder/README.md) explains how.

## Run it on your own computer

You need Python 3.9 or newer with numpy, and GROMACS. I tested it with GROMACS
2026.3. On Linux or macOS:

```bash
git clone https://github.com/CWoodkid/comfy-gmx-lite.git
cd comfy-gmx-lite
./start.sh
```

`./start.sh` checks what your machine has and opens <http://localhost:8189> in
your browser. If it cannot find GROMACS, it says so. Then point **Settings** at
the `GMXRC` file of the GROMACS you have, or build one with **Environments →
Build from source**. Your runs and settings are kept in `~/.comfy-gmx-lite`.
`./run.sh --help` lists the other ways to start it.

On Windows, use WSL (Linux inside Windows), or Docker with the files in
[binder/](binder/).

## What is in it

There are 25 blocks. They load and download files, prepare a protein, build a
system (box, water, ions, other molecules, an ice crystal), run GROMACS,
process a trajectory, measure things (energies, RMSD, radius of gyration,
secondary structure, density, counting ice) and show the results.
[docs/nodes.md](docs/nodes.md) lists every block and its settings.

There are two tutorials, described in [docs/tutorials.md](docs/tutorials.md),
and seven chunks: ready-made groups of blocks, such as a minimisation, an
equilibration or a standard analysis, to drop into a graph of your own.

I left out everything else the full Comfy-gmx does: coarse-grained (Martini)
simulations, membrane builders, ligands, and installing other programs.

## Where the tutorials come from

Lysozyme in Water turns a published tutorial into blocks. Read the original;
it explains far more than my notes do. If you use it, please cite it:

- Lemkul, J. A. (2018) From Proteins to Perturbed Hamiltonians: A Suite of
  Tutorials for the GROMACS-2018 Molecular Simulation Package. *Living J.
  Comput. Mol. Sci.* 1(1), 5068.
  [doi:10.33011/livecoms.1.1.5068](https://doi.org/10.33011/livecoms.1.1.5068).
  The tutorial itself is at <http://www.mdtutorials.com/gmx/lysozyme/>.

I wrote the ice tutorial for this version. Its references are in
[docs/ice-melting.md](docs/ice-melting.md).

## Licence

MIT. See [LICENSE](LICENSE).
