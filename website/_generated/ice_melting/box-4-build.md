<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Settings come from** | `raw` | `preset` |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `cool.mdp` | `run.mdp` |

Into **The mdp text**, copy this (the button at its top right copies it):

```text
; The hot gas cooled in one run, from 1000 K back down to 200 K.
;
; The heating run backwards: fast from 1000 K to 400 K over the first 100 ps,
; while the gas gathers back into a drop, then slowly to 200 K over the next
; 100 ps. It starts from the last picture of the heating run, and every
; molecule keeps the speed it had there, so the temperature carries on from
; where the heating left it.
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

; The same thermostat as in the heating run.
tcoupl               = v-rescale
tc-grps              = System
tau_t                = 0.1       ; how quickly it corrects, in ps
ref_t                = 1000      ; the target at the start

; Annealing: the target moves, in straight lines between these points.
; 1000 K at 0 ps, 400 K at 100 ps, 200 K at 200 ps.
annealing            = single
annealing-npoints    = 3
annealing-time       = 0 100 200
annealing-temp       = 1000 400 200

; No new speeds: every molecule keeps the one it had at the end of the
; heating. The structure file carries it, along with where the molecule was.
gen_vel              = no

pcoupl               = no
comm-mode            = linear
```

### ② Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `cool.tpr` | `topol.tpr` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ③ **Run MD (mdrun)** in box *2. Heat it: 200 K to 1000 K* | <span class="socket" style="background:#6fbf8b" title="structure"></span> final conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ① **Ice crystal** in box *1. An ice cube in empty space* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ③ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `cool` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ④ Count the ice

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** (in the drawer **advanced**) | `ice.xvg` | `ice_count.xvg` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑤ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ④ **Count the ice** | <span class="socket" style="background:#c88fd0" title="xvg"></span> molecules in ice over time | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑥ Water in the drop

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

Leave its settings as they are.

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
| ⑥ **Water in the drop** | <span class="socket" style="background:#c88fd0" title="xvg"></span> share of the water in the drop over time | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑧ Preview trajectory

In the list on the left, under **View**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Take every** | `2` | `25` |
| **Selection** | `Oxygens` | `Protein` |
| **Periodic boundary** | `lump` | `mol` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
| ① **Ice crystal** in box *1. An ice cube in empty space* | <span class="socket" style="background:#4fb8c8" title="index"></span> index | <span class="socket" style="background:#4fb8c8" title="index"></span> index |
