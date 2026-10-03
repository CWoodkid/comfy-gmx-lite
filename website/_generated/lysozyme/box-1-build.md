<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

### ① Force field directory

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Source** | `archive URL` | `directory` |
| **Force field name** (in the drawer **advanced**) | `charmm36-jul2022` | *empty* |

Into **Archive URL**, in the drawer **advanced**, copy this (the button at its top right copies it):

```text
http://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-jul2022.ff.tgz
```

### ② Load structure

In the list on the left, under **Input / Output**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Where from** | `the Protein Data Bank` | `a file on this machine` |
| **PDB code** | `1aki` | *empty* |

### ③ Clean structure

In the list on the left, under **Structure preparation**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Remove heteroatoms** | not ticked | ticked |
| **Output name** (in the drawer **advanced**) | `1AKI_clean.pdb` | `clean.pdb` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ② **Load structure** | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |

### ④ Topology (pdb2gmx)

In the list on the left, under **Build system**. Click it, or drag it onto the canvas.

| setting | set it to | a fresh block has |
| --- | --- | --- |
| **Ignore input hydrogens (-ignh)** | not ticked | ticked |
| **Output name** (in the drawer **advanced**) | `1AKI_processed.gro` | `processed.gro` |

Wires into it, each from a dot on the right of one block to the dot of the same colour on the left of this one:

| from | its dot | into this block's dot |
| --- | --- | --- |
| ① **Force field directory** | <span class="socket" style="background:#8d97a5" title="ffdir"></span> force field | <span class="socket" style="background:#8d97a5" title="ffdir"></span> force field |
| ③ **Clean structure** | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure | <span class="socket" style="background:#6fbf8b" title="structure"></span> structure |
