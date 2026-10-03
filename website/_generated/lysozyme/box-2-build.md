<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Define box (editconf)

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Box type** | `cubic` | `dodecahedron` |
| **Output name** (in the drawer **advanced**) | `1AKI_newbox.gro` | `boxed.gro` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ④ **Topology (pdb2gmx)** in box *1. Topology (pdb2gmx)* | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |

### ② Solvate

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Output name** (in the drawer **advanced**) | `1AKI_solv.gro` | `solvated.gro` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Define box (editconf)** | <span class="socket" style="background:#6fbf8b" title="structure"></span> conf | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |
| ④ **Topology (pdb2gmx)** in box *1. Topology (pdb2gmx)* | <span class="socket" style="background:#d8a84f" title="topology"></span> topology | <span class="socket" style="background:#d8a84f" title="topology"></span> topology |
