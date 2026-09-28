# The online copy

This folder lets Comfy-gmx lite run in a web browser, on any computer, with
nothing installed on it. A service such as mybinder.org, or a JupyterHub you
run yourself, reads this folder, builds a ready-made copy of the program with
everything it needs, and gives each person their own copy of it.

Each person's copy has its own processor, memory and files, so nobody can see
or disturb anybody else's runs. The page they use is the same editor as on a
desktop. Jupyter, which such services are built around, only passes it through.

## What each file does

| file | what it does |
|---|---|
| `environment.yml` | the software: GROMACS 2026.3 for processors only, Python 3.12, numpy, and jupyter-server-proxy, all from conda-forge |
| `apt.txt` | programs from Ubuntu: nano, a simple text editor for the Shell tab |
| `postBuild` | runs once, while the copy is built: installs the plug-in below, checks the two tutorials against the blocks this version has, and downloads what they need (the lysozyme structure and CHARMM36) |
| `jupyter-proxy/` | a small plug-in that tells Jupyter how to start the editor, and that it lives at `<session address>/comfygmx/` |
| `launch.py` | what Jupyter runs to start the editor: it works out how many processors this session may use, writes the settings, and starts it, telling the Shell tab that Jupyter is the only way in |
| `build-image.sh` | builds the same copy on your own machine with repo2docker, the program Binder uses |
| `try-image.sh` | starts that copy as one person's session would be: one processor and 2 GB of memory |

Because of `postBuild`, the download blocks of the tutorials finish at once in
the online copy. A class does not depend on those websites being up, or on
thirty people downloading at the same moment.

## How long the tutorials take

I measured these on 2026-09-26, from Run to the last block, with nobody
touching the page:

| tutorial | mybinder.org (2i2c) | mybinder.org (GESIS) | this copy on my workstation (AMD EPYC 9274F) |
|---|---|---|---|
| An ice cube melting | 2 min 50 s | 2 min 49 s | 2 min 26 s |
| Lysozyme in Water | 8 min 36 s | 8 min 50 s | 7 min 41 s |

I timed the ice tutorial after I changed it to one heating run. Before, with
its two runs at 300 K and 200 K, it took 3 min 12 s and 3 min 15 s there.

mybinder.org is several sites. Each start lands on one of them, and they run at
slightly different speeds. I limited the copy on my workstation to one
processor and 2 GB of memory, as a mybinder.org session is.
[../docs/tutorial-runs.md](../docs/tutorial-runs.md) has the time of every
part of every run and what each tutorial came out as.

## Try it on your own machine

```bash
binder/build-image.sh
binder/try-image.sh
```

The first command builds the copy. The first time takes a while, because it
downloads and installs the software; after that a rebuild takes two or three
minutes. The second command starts the copy and prints an address to open in a
browser, and the command that stops it. Only your computer can reach it, and
stopping it throws away everything done inside, as the end of a Binder session
does.

`build-image.sh` needs Docker. The first time, it sets up repo2docker, and
Docker's "buildx" add-on if your Docker lacks it, in
`~/.cache/comfy-gmx-lite-build` and nowhere else. The one exception: conda adds
that folder's buildx environment to its list, which `conda env list` shows.

`try-image.sh` gives the copy one processor, as mybinder.org does. `CPUS=2`
in front of it gives two; `CPUSET=5` keeps it on processor 5 of your machine,
out of the way of other work.

## Putting it online

### mybinder.org

mybinder.org is free and needs no server. It builds from this public
repository, and the address to hand out is

    https://mybinder.org/v2/gh/CWoodkid/comfy-gmx-lite/main?urlpath=comfygmx/

which opens straight into the editor. Its own rules, from its published
settings in September 2026:

- one processor and up to 2 GB of memory per person;
- a session closes after 10 minutes in which nothing reaches it, and after 6
  hours in any case;
- nothing is kept afterwards;
- at most 100 people on one repository at once.

The first start after each change I make to the repository takes as long as a
build. Later ones are quicker.

Ten quiet minutes means ten minutes in which no request reaches the copy.
While a run is going, the page asks the copy for news every few seconds, and
each question counts. Moving the mouse or typing on the page counts too; the
editor reports that at most once every two minutes. A tab left open with
nothing running and nobody at it sends nothing, and the session ends as the
site intends.

The page asks for news, rather than waiting to be told, because of how
mybinder.org's GESIS site behaves. The servers in front of it hold back a reply
that stays open until the reply is complete. I found this out when a run of the
Martini tutorial, which this project used to include, was cut off half way.
The page had followed that run through one such reply, so it saw nothing until
the run was over, and since nothing else reached the copy in the meantime,
mybinder.org closed it as unused. A test copy with nothing but one open reply
was gone within 16 minutes. I only tried the 2i2c site after the page had
started asking. With the page asking, a test block that ran for 25 minutes,
with nobody touching the page, kept its copy open to the end. A copy left with
its page open and nothing running had closed when I looked again, about 22
minutes later. I tested all of this on 2026-09-26.

### A JupyterHub of your own

A JupyterHub you run (on a university machine or a rented cloud server) serves
the same copy to every participant, with the processors and memory you choose
and no time limits you did not set. It can use the image `build-image.sh`
makes; each person then gets their own container from it. Do not mount a
storage volume over `/home/jovyan`: the program and its downloads live there,
and a volume on top would hide them. I have not tried this myself.
