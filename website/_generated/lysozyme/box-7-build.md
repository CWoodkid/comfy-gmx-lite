<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

Pick the **Preset** first. The moment you type into one of its boxes, **Settings come from** turns to `manual` by itself, every box fills in with the preset's value, and **File name** becomes the preset's name with `_edited` added. Then change these:

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Settings come from** | `manual` | `preset` |
| **Preset** | `lysozyme_md` | `md_atomistic` |
| **Number of steps** | `5000` | `5000000` (from lysozyme_md) |
| **Frame every (steps)** | `50` | `5000` (from lysozyme_md) |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `md.mdp` | `run.mdp` |

### ② Preprocess (grompp)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** | `md_0_10.tpr` | `topol.tpr` |
| **Use conf as -r when unconnected** | not ticked | ticked |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
| ③ **Run MD (mdrun)** in box *7. NPT equilibration* | <span class="socket" style="background:#6fbf8b" title="structure"></span> final conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf |
| ③ **Run MD (mdrun)** in box *7. NPT equilibration* | <span class="socket" style="background:#8d97a5" title="file"></span> checkpoint | <span class="socket" style="background:#8d97a5" title="file"></span> checkpoint (-t) |
| ② **Add ions** in box *4. Add ions* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |

### ③ Run MD (mdrun)

In the list on the left, under **Run**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output prefix (-deffnm)** | `md_0_10` | `md` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Preprocess (grompp)** | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr | <span class="socket" style="background:#4f9dd8" title="tpr"></span> tpr |
