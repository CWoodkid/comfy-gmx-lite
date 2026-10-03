<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Settings come from** | `raw` | `preset` |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `heat.mdp` | `run.mdp` |

Into **The mdp text**, copy this (the button at its top right copies it):

```text
; The ice cube heated in one run, from 200 K to 1000 K.
;
; 200 K is minus 73 degrees C, colder than any freezer. 1000 K is over 700
; degrees C. The thermostat's target climbs as the run goes: slowly to 400 K
; over the first 100 ps, so the ice has time to melt and the drop time to
; settle, then fast to 1000 K over the next 100 ps, where the drop boils away.
; To heat it differently, change the numbers on the annealing lines, and
; nsteps to match the last time on them.
integrator           = md
dt                   = 0.002     ; one step is 2 femtoseconds (0.002 ps)
nsteps               = 100000    ; 100,000 steps: 200 picoseconds

nstxout-compressed   = 250       ; save a picture every 250 steps (0.5 ps)
nstenergy            = 500       ; and the energies, every 1 ps
nstlog               = 5000

cutoff-scheme        = Verlet
coulombtype          = PME
rcoulomb             = 1.0
vdwtype              = cut-off
rvdw                 = 1.0
pbc                  = xyz

; The thermostat: it keeps the temperature at its target, by speeding the
; molecules up or slowing them down a little at every step.
tcoupl               = v-rescale
tc-grps              = System
tau_t                = 0.1       ; how quickly it corrects, in ps
ref_t                = 200       ; the target at the start

; Annealing: the target moves, in straight lines between these points.
; 200 K at 0 ps, 400 K at 100 ps, 1000 K at 200 ps.
annealing            = single
annealing-npoints    = 3
annealing-time       = 0 100 200
annealing-temp       = 200 400 1000

; Give every molecule a speed to start with, picked at random the way
; speeds are spread at 200 K.
gen_vel              = yes
gen_temp             = 200
gen_seed             = 2026

; No pressure control: around the cube there is nothing but empty space, and
; that is where the gas goes.
pcoupl               = no

; Take away any drift of the whole lot, so it does not wander off. Only the
; drift: molecules that boil off fly out through one side of the box and come
; back in through the opposite one, since the box repeats in every direction,
; and stopping any spin as well goes wrong once they do.
comm-mode            = linear
```

### ② Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `heat.tpr` | `topol.tpr` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ⑥ **Run MD (mdrun)** in box *1. An ice cube in empty space* | <span class="socket" style="background:#6fbf8b" title="structure"></span> final conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ① **Ice crystal** in box *1. An ice cube in empty space* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ③ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `heat` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ④ Energy terms

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Terms** | `Temperature` | `Potential`, `Temperature`, `Pressure` (one on each line) |
| **Output name** (in the drawer **advanced**) | `temperature.xvg` | `energy.xvg` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#8d97a5" title="file"></span> energy | <span class="socket" style="background:#8d97a5" title="file"></span> energy |

### ⑤ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ④ **Energy terms** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑥ Count the ice

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** (in the drawer **advanced**) | `ice.xvg` | `ice_count.xvg` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑦ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑥ **Count the ice** | <span class="socket" style="background:#c88fd0" title="xvg"></span> molecules in ice over time | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑧ Measure something, frame by frame

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **What to measure** | `Radius of gyration: how spread out it is (gyrate)` | `RMSD: how far it moved from the start (rms)` |
| **Output name** (in the drawer **advanced**) | `size.xvg` | *empty* |
| **Time unit** (in the drawer **advanced**) | `ps` | `ns` |
| **Selection (-sel)** | `Oxygens` | `Protein` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
| ① **Ice crystal** in box *1. An ice cube in empty space* | <span class="socket" style="background:#4fb8c8" title="index"></span> index | <span class="socket" style="background:#4fb8c8" title="index"></span> index |

### ⑨ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑧ **Measure something, frame by frame** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑩ Energy terms

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Terms** | `Potential` | `Potential`, `Temperature`, `Pressure` (one on each line) |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#8d97a5" title="file"></span> energy | <span class="socket" style="background:#8d97a5" title="file"></span> energy |

### ⑪ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑩ **Energy terms** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑫ Water in the drop

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑬ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑫ **Water in the drop** | <span class="socket" style="background:#c88fd0" title="xvg"></span> share of the water in the drop over time | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑭ Preview trajectory

In the list on the left, under **View**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Take every** | `2` | `25` |
| **Selection** | `Oxygens` | `Protein` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
| ① **Ice crystal** in box *1. An ice cube in empty space* | <span class="socket" style="background:#4fb8c8" title="index"></span> index | <span class="socket" style="background:#4fb8c8" title="index"></span> index |
