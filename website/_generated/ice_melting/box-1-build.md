<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

### ① Ice crystal

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

Leave its settings as they are.

### ② Define box (editconf)

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Box type** | `cubic` | `dodecahedron` |
| **Explicit box (nm)** | `5.5 5.5 5.5` | *empty* |
| **Output name** (in the drawer **advanced**) | `cube.gro` | `boxed.gro` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Ice crystal** | <span class="socket" style="background:#6fbf8b" title="structure"></span> ice | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |

### ③ Preview structure

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Define box (editconf)** | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |

### ④ Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Settings come from** | `raw` | `preset` |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `minimise.mdp` | `run.mdp` |

Into **The mdp text**, copy this (the button at its top right copies it):

```text
; Minimisation: let every molecule settle into place.
;
; A crystal built from a recipe is never quite right -- a hydrogen a little
; too close to a neighbour here, a molecule a little twisted there. This walks
; every molecule downhill in energy until nothing is pushing hard any more.
; No time passes, and nothing moves afterwards: the cube is standing
; perfectly still, which is what 0 K, absolute zero, means.
integrator      = steep
emtol           = 100       ; stop when no force is bigger than this
nsteps          = 5000      ; or after this many tries

cutoff-scheme   = Verlet
coulombtype     = PME       ; every charge feels every other charge
rcoulomb        = 1.0       ; nm
vdwtype         = cut-off   ; molecules further apart than rvdw ignore each other's size
rvdw            = 1.0       ; nm
pbc             = xyz       ; the box repeats in every direction
```

### ⑤ Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `em.tpr` | `topol.tpr` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ④ **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ② **Define box (editconf)** | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ① **Ice crystal** | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ⑥ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `em` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑤ **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
