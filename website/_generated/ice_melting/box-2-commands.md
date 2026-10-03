<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

Some programs stop and ask a question, such as which group of atoms to use. The lines between `<<'COMFYGMX_STDIN'` and `COMFYGMX_STDIN` are the answers, given in advance. Typing a command by hand, you can leave them out and answer the questions yourself.

**① Run parameters (.mdp)**

It writes the run-parameter file `heat.mdp`, which later blocks read:

??? abstract "heat.mdp"

    ```ini
    ; The ice cube heated in one run, from 200 K to 1000 K.
    ;
    ; 200 K is minus 73 degrees C, colder than any freezer. 1000 K is over 700
    ; degrees C. The thermostat's target climbs as the run goes: slowly to 400 K
    ; over the first 100 ps, so the ice has time to melt and the drop time to
    ; settle, then fast to 1000 K over the next 100 ps, where the drop boils away.
    ; To heat it differently, change the numbers on the annealing lines, and
    ; nsteps to match the last time on them.
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

    ; The thermostat: it keeps the temperature at its target, by speeding the
    ; molecules up or slowing them down a little at every step.
    tcoupl               = v-rescale
    tc-grps              = System
    tau_t                = 0.1       ; how quickly it corrects, in ps
    ref_t                = 200       ; the target at the start

    ; Annealing: the target moves, in straight lines between these points.
    ; 200 K at 0 ps, 400 K at 100 ps, 1000 K at 200 ps.
    annealing            = single
    annealing-npoints    = 3
    annealing-time       = 0 100 200
    annealing-temp       = 200 400 1000

    ; Give every molecule a speed to start with, picked at random the way
    ; speeds are spread at 200 K.
    gen_vel              = yes
    gen_temp             = 200
    gen_seed             = 2026

    ; No pressure control: around the cube there is nothing but empty space, and
    ; that is where the gas goes.
    pcoupl               = no

    ; Take away any drift of the whole lot, so it does not wander off. Only the
    ; drift: molecules that boil off fly out through one side of the box and come
    ; back in through the opposite one, since the box repeats in every direction,
    ; and stopping any spin as well goes wrong once they do.
    comm-mode            = linear
    ```

**② Preprocess (grompp)**

```bash
# gmx grompp
gmx grompp -f heat.mdp -c em.gro -p ice.top -o heat.tpr -po mdout.mdp -r em.gro
```

**③ Run MD (mdrun)**

```bash
# gmx mdrun
gmx mdrun -s heat.tpr -deffnm heat -v
```

**④ Energy terms**

```bash
# gmx energy
gmx energy -f heat.edr -o temperature.xvg <<'COMFYGMX_STDIN'
Temperature
COMFYGMX_STDIN
```

**⑤ Preview plot**

Draws its file inside the block. It runs no program.

**⑥ Count the ice**

```bash
# find the water oxygens
gmx select -s heat.tpr -select 'name OW' -on oxygens.ndx

# take the oxygens out of every frame
gmx trjconv -s heat.tpr -f heat.xtc -n oxygens.ndx -o oxygens.gro <<'COMFYGMX_STDIN'
0
COMFYGMX_STDIN

# count the ice
python count_ice.py oxygens.gro ice.xvg --cutoff 0.35
```

**⑦ Preview plot**

Draws its file inside the block. It runs no program.

**⑧ Measure something, frame by frame**

```bash
# check the index file fits the structure
__s=$(python3 count_atoms.py heat.tpr 2>/dev/null); if [ -z "$__s" ]; then __s=$(timeout 120 gmx dump -s heat.tpr -quiet 2>/dev/null | grep -m1 -E '^[[:space:]]*#?n?atoms[[:space:]]*=' | tr -dc '0-9'); fi; python3 check_index.py ice.ndx "${__s:-0}"

# gmx gyrate
gmx gyrate -s heat.tpr -o size.xvg -f heat.xtc -n ice.ndx -sel Oxygens -tu ps -mode mass
```

**⑨ Preview plot**

Draws its file inside the block. It runs no program.

**⑩ Energy terms**

```bash
# gmx energy
gmx energy -f heat.edr -o energy.xvg <<'COMFYGMX_STDIN'
Potential
COMFYGMX_STDIN
```

**⑪ Preview plot**

Draws its file inside the block. It runs no program.

**⑫ Water in the drop**

```bash
# find the water oxygens and the ions
gmx select -s heat.tpr -select 'name OW NA CL' -on drop.ndx

# take them out of every frame
gmx trjconv -s heat.tpr -f heat.xtc -n drop.ndx -o drop_frames.gro <<'COMFYGMX_STDIN'
0
COMFYGMX_STDIN

# measure the drop
python count_drop.py drop_frames.gro drop.xvg --cutoff 0.35 --water OW
```

**⑬ Preview plot**

Draws its file inside the block. It runs no program.

**⑭ Preview trajectory**

```bash
# the system's own groups
printf 'q\n' | gmx make_ndx -f heat.tpr -o standard.ndx > /dev/null

# every group in one file
awk '/^\[/ { name = $0; gsub(/^\[ *| *\]$/, "", name); keep = !(name in seen); seen[name] = 1 } keep' ice.ndx standard.ndx > groups.ndx

# every 2nd frame of Oxygens
printf '%b' 'Oxygens\nOxygens\n' | gmx trjconv -s heat.tpr -f heat.xtc -o frames.pdb -pbc mol -n groups.ndx -center -skip 2
```
