# The online copy

This folder lets Comfy-gmx lite run in a web browser, on any computer, with
nothing installed on it. A service such as mybinder.org, or a JupyterHub you
run yourself, reads this folder, builds a ready-made copy of the program with
everything it needs, and gives each person their own copy of it.

Each person's copy has its own processor, memory and files, so nobody can see
or disturb anybody else's runs. The page they use is the same editor as on a
desktop; Jupyter, which such services are built around, only hands it through.

## What each file does

| file | what it does |
|---|---|
| `environment.yml` | the software: GROMACS 2026.3 for processors only, Python 3.12, numpy, and jupyter-server-proxy, all from conda-forge |
| `postBuild` | runs once, while the copy is built: installs the plug-in below, checks the three tutorials against the blocks this version has, and downloads what they need (the lysozyme structure, CHARMM36, the lipid, the water box, the Martini 3 files) |
| `jupyter-proxy/` | a small plug-in that tells Jupyter how to start the editor, and that it lives at `<session address>/comfygmx/` |
| `launch.py` | what Jupyter runs to start the editor: it works out how many processors this session may use, writes the settings, and starts it |
| `build-image.sh` | builds the same copy on your own machine, with repo2docker — the program Binder uses |
| `try-image.sh` | starts that copy as one person's session would be: one processor and 2 GB of memory |

Because of `postBuild`, the download blocks of the tutorials finish at once in
the online copy: a class does not depend on those websites being up, or on
thirty people downloading at the same moment.

## How long the tutorials take

Measured in this copy, in a container limited to one processor and 2 GB of
memory, as on mybinder.org, on an AMD EPYC 9274F:

| tutorial | from Run to the last block | of which, simulating |
|---|---|---|
| An ice cube melting | 2 min 48 s | 2 min 26 s |
| Lysozyme in Water | 7 min 41 s | 6 min 47 s |
| Lipids I: a bilayer that builds itself | 10 min 54 s | 10 min 44 s |

A cloud machine can be slower than this one. [../docs/tutorial-runs.md](../docs/tutorial-runs.md)
has the time of every run and what each tutorial came out as.

## Try it on your own machine

```bash
binder/build-image.sh
binder/try-image.sh
```

The first builds the copy; the first time takes a while (the software is
downloaded and installed), after that a rebuild takes two or three minutes. The
second starts it and prints an address to open in a browser, and the command
that stops it. Only this computer can reach it, and stopping it throws away
everything done inside, as the end of a Binder session does.

`build-image.sh` needs Docker. The first time, it sets up repo2docker, and
Docker's "buildx" add-on if this Docker lacks it, in
`~/.cache/comfy-gmx-lite-build`, and nowhere else — except that conda adds
that folder's buildx environment to its list, which `conda env list` shows.

`try-image.sh` gives the copy one processor, as mybinder.org does. `CPUS=2`
in front of it gives two; `CPUSET=5` keeps it on processor 5 of your machine,
out of the way of other work.

## Putting it online

**mybinder.org** is free and needs no server. It builds from this public
repository, and the address to hand out is

    https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/

which opens straight into the editor. Its own rules (from its published
settings, September 2026): one processor and up to 2 GB of memory per person;
a session closes after 10 minutes in which nothing reaches it, and after 6
hours in any case; nothing is kept afterwards; at most 100 people on one
repository at once. The first start after each change to the repository
takes as long as a build; later ones are quicker.

Ten quiet minutes means: no simulation running and nobody using the page. A
running simulation keeps the session alive, since its progress flows to the
page; so does moving the mouse or typing on the page, which the editor reports
at most once every two minutes. A tab left open with nobody at it goes quiet,
and the session ends as the site intends.

**A JupyterHub you run** (on a university machine or a rented cloud server)
serves the same copy to every participant, with the processors and memory you
choose and no time limits you did not set. It can use the image
`build-image.sh` makes; each person then gets their own container from it.
Do not mount a storage volume over `/home/jovyan`: the program and its
downloads live there, and a volume on top would hide them. *Not tried here.*
