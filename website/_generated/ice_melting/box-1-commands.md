<!-- Written by tools/website.py from the tutorial 'An ice cube melting'. Do not edit: run the script again instead. -->

**① Ice crystal**

```bash
# build the ice crystal
python make_ice.py --cells 6 4 4 --seed 1 --gro ice.gro --top ice.top --ndx ice.ndx
```

**② Define box (editconf)**

```bash
# gmx editconf
gmx editconf -f ice.gro -o cube.gro -c -box 5.5 5.5 5.5 -bt cubic
```

**③ Preview structure**

Draws its file inside the block. It runs no program.

**④ Run parameters (.mdp)**

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

**⑤ Preprocess (grompp)**

```bash
# gmx grompp
gmx grompp -f minimise.mdp -c cube.gro -p ice.top -o em.tpr -po mdout.mdp -r cube.gro
```

**⑥ Run MD (mdrun)**

```bash
# gmx mdrun
gmx mdrun -s em.tpr -deffnm em -v
```
