# 3. Box and solvent

!!! abstract "In this box"
    Put the protein in the middle of a box, and fill the box with water.
    **2 blocks.** It takes about a second.

Published tutorial:
[Step Three: Defining the Unit Cell & Adding Solvent](http://www.mdtutorials.com/gmx/lysozyme/03_solvate.html).

## What it does, and why

- **Define box (editconf)** puts the protein in the middle of a cube, with
  at least 1.2 nm between the protein and every side. A simulation box
  repeats in every direction, like tiles, and the protein in the next tile
  is a copy of this one. With 1.2 nm on every side, two copies are always at
  least 2.4 nm apart, twice the distance over which the force field counts
  how atoms act on each other. So the protein never feels its own copy.
- **Solvate** fills the box with water. It copies a small ready-made box of
  216 water molecules side by side until the big box is full, then removes
  every molecule that overlaps the protein. That small box was made for a
  slightly different three-point water model, but any three-point model
  can start from it, and the minimisation in box 5 settles the difference.
  Solvate also adds the water to the topology's `[ molecules ]` list, so the
  topology and the structure keep agreeing.

The block's own box shape is a *rhombic dodecahedron*, a shape with twelve
faces that needs about 30% less water for the same distance. The published
tutorial uses a cube, which is easier to picture, so the list below changes
it.

## What you will build

[![The finished box: two blocks, each with its number](../pictures/lysozyme/box-2.webp){ .canvas }](../pictures/lysozyme/box-2.webp)

## Build it

Both blocks take wires from the topology block of box *1. Topology
(pdb2gmx)*: the tables say *in box 1. Topology (pdb2gmx)* beside them.

--8<-- "_generated/lysozyme/box-2-build.md"

## Run it, and look

Press **Run**. Box 1 is marked **cached**, since nothing in it changed, and
this box takes about a second.

[![The box after the run](../pictures/lysozyme/box-2-results.webp){ .canvas }](../pictures/lysozyme/box-2-results.webp)

Click each block and read the end of its **Log** on the right:

- **Define box (editconf)**: the protein measures 5.01 nm across at its
  widest (`diameter`), so the cube is 5.01 + 2 × 1.2 = 7.41 nm wide
  (`new box vectors`).
- **Solvate**: `Number of solvent molecules: 12597`. The box now holds
  39,751 atoms, and almost all of them are water: the protein is 1960.

## Under the hood

--8<-- "_generated/lysozyme/box-2-commands.md"
