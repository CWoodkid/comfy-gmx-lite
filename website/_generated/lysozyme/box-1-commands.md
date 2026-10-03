<!-- Written by tools/website.py from the tutorial 'Lysozyme in Water'. Do not edit: run the script again instead. -->

**① Force field directory**

```bash
# download force field
curl -fsSL --retry 3 -o ff.tgz 'http://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-jul2022.ff.tgz'

# unpack
tar xzf ff.tgz

# report unpacked name
local=$(find . -maxdepth 1 -type d -name "*.ff" | head -n1); echo "unpacked ${local#./}"
```

**② Load structure**

```bash
# download 1aki.pdb
curl -fsSL --retry 3 -o 1aki.pdb https://files.rcsb.org/download/1aki.pdb
```

**③ Clean structure**

```bash
# clean structure
python3 clean_pdb.py 1aki.pdb 1AKI_clean.pdb --drop-water --first-model --first-altloc
```

**④ Topology (pdb2gmx)**

```bash
# check the structure is all-atom
python3 check_all_atom.py 1AKI_clean.pdb 1AKI_processed.gro

# gmx pdb2gmx
gmx pdb2gmx -f 1AKI_clean.pdb -o 1AKI_processed.gro -p topol.top -ff charmm36-jul2022 -water tip3p
```
