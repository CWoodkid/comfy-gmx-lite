<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

Some programs stop and ask a question, such as which group of atoms to use. The lines between `<<'COMFYGMX_STDIN'` and `COMFYGMX_STDIN` are the answers, given in advance. Typing a command by hand, you can leave them out and answer the questions yourself.

**① Ice crystal**

```bash
# build the ice crystal
python make_ice.py --cells 6 4 4 --seed 1 --gro ice.gro --top ice.top --ndx ice.ndx --salt 26 --salt-seed 1
```

**② Define box (editconf)**

```bash
# gmx editconf
gmx editconf -f ice.gro -o cube.gro -c -box 5.5 5.5 5.5 -bt cubic
```

**③ Run parameters (.mdp)**

It writes the run-parameter file `minimise.mdp`, which later blocks read:

??? abstract "minimise.mdp"

    ```ini
    ; Minimisation: let every molecule settle into place.
    ;
    ; A crystal built from a recipe is never quite right -- a hydrogen a little
    ; too close to a neighbour here, a molecule a little twisted there. This walks
    ; every molecule downhill in energy until nothing is pushing hard any more.
    ; No time passes, and nothing moves afterwards: the cube is standing
    ; perfectly still, which is what 0 K, absolute zero, means.
    integrator      = steep
    emtol           = 100       ; stop when no force is bigger than this
    nsteps          = 5000      ; or after this many tries

    cutoff-scheme   = Verlet
    coulombtype     = PME       ; every charge feels every other charge
    rcoulomb        = 1.0       ; nm
    vdwtype         = cut-off   ; molecules further apart than rvdw ignore each other's size
    rvdw            = 1.0       ; nm
    pbc             = xyz       ; the box repeats in every direction
    ```

**④ Preprocess (grompp)**

```bash
# gmx grompp
gmx grompp -f minimise.mdp -c cube.gro -p ice.top -o em.tpr -po mdout.mdp -r cube.gro
```

**⑤ Run MD (mdrun)**

```bash
# gmx mdrun
gmx mdrun -s em.tpr -deffnm em -v
```

**⑥ Run parameters (.mdp)**

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

**⑦ Preprocess (grompp)**

```bash
# gmx grompp
gmx grompp -f heat.mdp -c em.gro -p ice.top -o heat.tpr -po mdout.mdp -r em.gro
```

**⑧ Run MD (mdrun)**

```bash
# gmx mdrun
gmx mdrun -s heat.tpr -deffnm heat -v
```

**⑨ Count the ice**

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

**⑩ Water in the drop**

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

**⑪ Compare plots**

```bash
# put the plots together
python compare.py compare.xvg 'pure water' first_ice.xvg 'with salt' second_ice.xvg --column 1 --title 'Ice: pure water against salty'
```

**⑫ Compare plots**

```bash
# put the plots together
python compare.py compare.xvg 'pure water' first_drop.xvg 'with salt' second_drop.xvg --column 1 --title 'Water still in the drop: pure against salty'
```

**⑬ Preview trajectory**

```bash
# the system's own groups
printf 'q\n' | gmx make_ndx -f heat.tpr -o standard.ndx > /dev/null

# every group in one file
awk '/^\[/ { name = $0; gsub(/^\[ *| *\]$/, "", name); keep = !(name in seen); seen[name] = 1 } keep' ice.ndx standard.ndx > groups.ndx

# every 2nd frame of Oxygens_and_ions
printf '%b' 'Oxygens_and_ions\nOxygens_and_ions\n' | gmx trjconv -s heat.tpr -f heat.xtc -o frames.pdb -pbc mol -n groups.ndx -center -skip 2
```
