<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

Pick the **Preset** first. The moment you type into one of its boxes, **Settings come from** turns to `manual` by itself, every box fills in with the preset's value, and **File name** becomes the preset's name with `_edited` added. Then change these:

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Settings come from** | `manual` | `preset` |
| **Preset** | `lysozyme_npt` | `md_atomistic` |
| **Number of steps** | `2500` | `250000` (from lysozyme_npt) |
| **Thermostat time constant (ps)** (in the drawer **advanced**, under **Temperature**) | `0.1` | `1.0` (from lysozyme_npt) |
| **Energies every (steps)** (in the drawer **advanced**, under **Output**) | `50` | `500` (from lysozyme_npt) |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `npt.mdp` | `run.mdp` |
| **Extra mdp lines** (in the drawer **advanced**, under **File and extra lines**) | `tau-p = 1.0` | *empty* |

### ② Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `npt.tpr` | `topol.tpr` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ③ **Run MD (mdrun)** in box *6. NVT equilibration* | <span class="socket" style="background:#6fbf8b" title="structure"></span> final conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ③ **Run MD (mdrun)** in box *6. NVT equilibration* | <span class="socket" style="background:#6fbf8b" title="structure"></span> final conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> restraint (-r) |
| ③ **Run MD (mdrun)** in box *6. NVT equilibration* | <span class="socket" style="background:#8d97a5" title="file"></span> checkpoint | <span class="socket" style="background:#8d97a5" title="file"></span> checkpoint (-t) |
| ② **Add ions** in box *4. Add ions* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ③ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `npt` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ④ Energy terms

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Terms** | `Pressure` | `Potential`, `Temperature`, `Pressure` (one on each line) |
| **Output name** (in the drawer **advanced**) | `pressure.xvg` | `energy.xvg` |

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

### ⑥ Energy terms

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Terms** | `Density` | `Potential`, `Temperature`, `Pressure` (one on each line) |
| **Output name** (in the drawer **advanced**) | `density.xvg` | `energy.xvg` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** | <span class="socket" style="background:#8d97a5" title="file"></span> energy | <span class="socket" style="background:#8d97a5" title="file"></span> energy |

### ⑦ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑥ **Energy terms** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |
