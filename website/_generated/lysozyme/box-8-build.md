<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Process trajectory (trjconv)

In the list on the left, under **Trajectory tools**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **-ur** | `(default)` | `compact` |
| **Output name** | `md_0_10_noPBC.xtc` | `traj_proc.xtc` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ③ **Run MD (mdrun)** in box *8. Production MD* | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ② Measure something, frame by frame

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** (in the drawer **advanced**) | `rmsd.xvg` | *empty* |
| **Time unit** (in the drawer **advanced**) | `ps` | `ns` |

Into **Groups (stdin)**, copy this (the button at its top right copies it):

```text
Backbone
Backbone
```

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ③ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Measure something, frame by frame** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ④ Measure something, frame by frame

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** (in the drawer **advanced**) | `rmsd_xtal.xvg` | *empty* |
| **Time unit** (in the drawer **advanced**) | `ps` | `ns` |

Into **Groups (stdin)**, copy this (the button at its top right copies it):

```text
Backbone
Backbone
```

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *5. Energy minimisation* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑤ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ④ **Measure something, frame by frame** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑥ Measure something, frame by frame

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **What to measure** | `Radius of gyration: how spread out it is (gyrate)` | `RMSD: how far it moved from the start (rms)` |
| **Output name** (in the drawer **advanced**) | `gyrate.xvg` | *empty* |
| **Time unit** (in the drawer **advanced**) | `ps` | `ns` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑦ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑥ **Measure something, frame by frame** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑧ Secondary structure (dssp)

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Time unit** | `ps` | `ns` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑨ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑧ **Secondary structure (dssp)** | <span class="socket" style="background:#c88fd0" title="xvg"></span> counts | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑩ Measure something, frame by frame

In the list on the left, under **Analysis**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **What to measure** | `Hydrogen bonds between two groups (hbond)` | `RMSD: how far it moved from the start (rms)` |
| **Output name** (in the drawer **advanced**) | `hbnum.xvg` | *empty* |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |

### ⑪ Preview plot

In the list on the left, under **View**. Click it, or drag it onto the canvas.

Leave its settings as they are.

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ⑩ **Measure something, frame by frame** | <span class="socket" style="background:#c88fd0" title="xvg"></span> xvg | <span class="socket" style="background:#c88fd0" title="xvg"></span> data |

### ⑫ Preview trajectory

In the list on the left, under **View**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Take every** | `2` | `25` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Process trajectory (trjconv)** | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory | <span class="socket" style="background:#d9705f" title="traj"></span> trajectory |
| ② **Preprocess (grompp)** in box *8. Production MD* | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
