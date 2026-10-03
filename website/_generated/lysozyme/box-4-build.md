<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Preset** | `lysozyme_min` | `md_atomistic` |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `minim.mdp` | `run.mdp` |

### ② Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `em.tpr` | `topol.tpr` |
| **Use conf as -r when unconnected** | not ticked | ticked |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ② **Add ions** in box *4. Add ions* | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ② **Add ions** in box *4. Add ions* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ③ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `em` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ④ Energy terms

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Terms** | `Potential` | `Potential`, `Temperature`, `Pressure` (one on each line) |
| **Output name** (in the drawer **advanced**) | `potential.xvg` | `energy.xvg` |

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
