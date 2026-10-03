<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

Some programs stop and ask a question, such as which group of atoms to use. The lines between `<<'COMFYGMX_STDIN'` and `COMFYGMX_STDIN` are the answers, given in advance. Typing a command by hand, you can leave them out and answer the questions yourself.

**① Run parameters (.mdp)**

It writes the run-parameter file `cool.mdp`, which later blocks read:

??? abstract "cool.mdp"

    ```ini
    ; The hot gas cooled in one run, from 1000 K back down to 200 K.
    ;
    ; The heating run backwards: fast from 1000 K to 400 K over the first 100 ps,
    ; while the gas gathers back into a drop, then slowly to 200 K over the next
    ; 100 ps. It starts from the last picture of the heating run, and every
    ; molecule keeps the speed it had there, so the temperature carries on from
    ; where the heating left it.
    integrator           = md
    dt                   = 0.002     ; one step is 2 femtoseconds (0.002 ps)
    nsteps               = 100000    ; 100,000 steps: 200 picoseconds

    nstxout-compressed   = 250       ; save a picture every 250 steps (0.5 ps)
    nstenergy            = 500       ; and the energies, every 1 ps
    nstlog               = 5000

    cutoff-scheme        = Verlet
    coulombtype          = PME
    rcoulomb             = 1.0
    vdwtype              = cut-off
    rvdw                 = 1.0
    pbc                  = xyz

    ; The same thermostat as in the heating run.
    tcoupl               = v-rescale
    tc-grps              = System
    tau_t                = 0.1       ; how quickly it corrects, in ps
    ref_t                = 1000      ; the target at the start

    ; Annealing: the target moves, in straight lines between these points.
    ; 1000 K at 0 ps, 400 K at 100 ps, 200 K at 200 ps.
    annealing            = single
    annealing-npoints    = 3
    annealing-time       = 0 100 200
    annealing-temp       = 1000 400 200

    ; No new speeds: every molecule keeps the one it had at the end of the
    ; heating. The structure file carries it, along with where the molecule was.
    gen_vel              = no

    pcoupl               = no
    comm-mode            = linear
    ```

**② Preprocess (grompp)**

```bash
# gmx grompp
gmx grompp -f cool.mdp -c heat.gro -p ice.top -o cool.tpr -po mdout.mdp -r heat.gro
```

**③ Run MD (mdrun)**

```bash
# gmx mdrun
gmx mdrun -s cool.tpr -deffnm cool -v
```

**④ Count the ice**

```bash
# find the water oxygens
gmx select -s cool.tpr -select 'name OW' -on oxygens.ndx

# take the oxygens out of every frame
gmx trjconv -s cool.tpr -f cool.xtc -n oxygens.ndx -o oxygens.gro <<'COMFYGMX_STDIN'
0
COMFYGMX_STDIN

# count the ice
python count_ice.py oxygens.gro ice.xvg --cutoff 0.35
```

**⑤ Water in the drop**

```bash
# find the water oxygens and the ions
gmx select -s cool.tpr -select 'name OW NA CL' -on drop.ndx

# take them out of every frame
gmx trjconv -s cool.tpr -f cool.xtc -n drop.ndx -o drop_frames.gro <<'COMFYGMX_STDIN'
0
COMFYGMX_STDIN

# measure the drop
python count_drop.py drop_frames.gro drop.xvg --cutoff 0.35 --water OW
```

**⑥ Compare plots**

```bash
# put the plots together
python compare.py compare.xvg 'pure water' first_ice.xvg 'with salt' second_ice.xvg --column 1 --title 'Ice while cooling: pure water against salty'
```

**⑦ Compare plots**

```bash
# put the plots together
python compare.py compare.xvg 'pure water' first_drop.xvg 'with salt' second_drop.xvg --column 1 --title 'Water back in the drop while cooling: pure against salty'
```

**⑧ Preview trajectory**

```bash
# the system's own groups
printf 'q\n' | gmx make_ndx -f cool.tpr -o standard.ndx > /dev/null

# every group in one file
awk '/^\[/ { name = $0; gsub(/^\[ *| *\]$/, "", name); keep = !(name in seen); seen[name] = 1 } keep' ice.ndx standard.ndx > groups.ndx

# every 2nd frame of Oxygens_and_ions
printf '%b' 'Oxygens_and_ions\nOxygens_and_ions\n' | gmx trjconv -s cool.tpr -f cool.xtc -o frames.pdb -pbc mol -n groups.ndx -center -skip 2

# the lump moved to the middle of the box
python whole_lump.py frames.pdb
```
