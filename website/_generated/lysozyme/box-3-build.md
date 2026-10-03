<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Run parameters (.mdp)

In the list on the left, under **Parameters & scripting**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Preset** | `lysozyme_ions` | `md_atomistic` |
| **File name** (in the drawer **advanced**, under **File and extra lines**) | `ions.mdp` | `run.mdp` |

### ② Add ions

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Salt concentration (M)** | `0.0` | `0.15` |
| **grompp -maxwarn** (in the drawer **advanced**) | `0` | `1` |
| **Output name** (in the drawer **advanced**) | `1AKI_solv_ions.gro` | `ions.gro` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Solvate** in box *3. Box and solvent* | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |
| ② **Solvate** in box *3. Box and solvent* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |
| ① **Run parameters (.mdp)** | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp | <span class="socket" style="background:#8a7fd0" title="mdp"></span> mdp |
