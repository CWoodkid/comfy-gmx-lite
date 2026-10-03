<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

**① Define box (editconf)**

```bash
# gmx editconf
gmx editconf -f 1AKI_processed.gro -o 1AKI_newbox.gro -c -d 1.2 -bt cubic
```

**② Solvate**

```bash
# gmx solvate
gmx solvate -cp 1AKI_newbox.gro -o 1AKI_solv.gro -cs spc216.gro -p topol.top
```
