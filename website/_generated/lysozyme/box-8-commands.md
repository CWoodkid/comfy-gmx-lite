<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

Some programs stop and ask a question, such as which group of atoms to use. The lines between `<<'COMFYGMX_STDIN'` and `COMFYGMX_STDIN` are the answers, given in advance. Typing a command by hand, you can leave them out and answer the questions yourself.

**① Process trajectory (trjconv)**

```bash
# gmx trjconv
gmx trjconv -f md_0_10.xtc -s md_0_10.tpr -o md_0_10_noPBC.xtc -pbc mol -center <<'COMFYGMX_STDIN'
Protein
System
COMFYGMX_STDIN
```

**② Measure something, frame by frame**

```bash
# gmx rms
gmx rms -s md_0_10.tpr -o rmsd.xvg -f md_0_10_noPBC.xtc -tu ps <<'COMFYGMX_STDIN'
Backbone
Backbone
COMFYGMX_STDIN
```

**③ Preview plot**

Draws its file inside the block. It runs no program.

**④ Measure something, frame by frame**

```bash
# gmx rms
gmx rms -s em.tpr -o rmsd_xtal.xvg -f md_0_10_noPBC.xtc -tu ps <<'COMFYGMX_STDIN'
Backbone
Backbone
COMFYGMX_STDIN
```

**⑤ Preview plot**

Draws its file inside the block. It runs no program.

**⑥ Measure something, frame by frame**

```bash
# gmx gyrate
gmx gyrate -s md_0_10.tpr -o gyrate.xvg -f md_0_10_noPBC.xtc -sel Protein -tu ps -mode mass
```

**⑦ Preview plot**

Draws its file inside the block. It runs no program.

**⑧ Secondary structure (dssp)**

```bash
# gmx dssp
gmx dssp -s md_0_10.tpr -f md_0_10_noPBC.xtc -sel Protein -o dssp.dat -num dssp_num.xvg -tu ps
```

**⑨ Preview plot**

Draws its file inside the block. It runs no program.

**⑩ Measure something, frame by frame**

```bash
# gmx hbond
gmx hbond -s md_0_10.tpr -num hbnum.xvg -f md_0_10_noPBC.xtc -r Protein -t Protein -hbr 0.35 -hba 30.0
```

**⑪ Preview plot**

Draws its file inside the block. It runs no program.

**⑫ Preview trajectory**

```bash
# every 2nd frame of Protein
printf '%b' 'Protein\nProtein\n' | gmx trjconv -s md_0_10.tpr -f md_0_10_noPBC.xtc -o frames.pdb -pbc mol -center -skip 2
```
