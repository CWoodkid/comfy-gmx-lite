# How long each tutorial takes, and what it came out as

Every tutorial was run from start to finish in the online copy — the image
`binder/build-image.sh` builds, the same one mybinder.org builds — in a
container limited to one processor and 2 GB of memory, as a mybinder.org
session is. The processor was one core of an AMD EPYC 9274F; a cloud machine
may well be slower. GROMACS was 2026.3 from conda-forge.

The downloads (the protein and the force field) were already in the image, as
they are online, so they took no time.

| # | Tutorial | Blocks | From Run to the last block | of which, simulating |
|---|---|---|---|---|
| 1 | An ice cube melting | 27 | 2 min 48 s | 2 min 26 s |
| 1 | Lysozyme in Water | 50 | 7 min 41 s | 6 min 47 s |

## An ice cube melting

| run | length | time |
|---|---|---|
| minimisation | — | 1 s |
| warm, 300 K | 100 ps | 74 s |
| cold, 200 K | 100 ps | 71 s |
| counting the ice | 201 frames, each run | 7.5 s each |

What it came out as:

- The crystal: 768 molecules, 2.71 × 3.13 × 2.95 nm, with no overall dipole.
  442 of them pass the ice test at the start; the rest sit on the surface,
  with too few neighbours to pass.
- Warm: 180 still ice after 1 ps, 105 at 10 ps, 15 at 30 ps, none from 40 ps
  on. Radius of gyration 1.46 → 1.38 nm.
- Cold: 270 still ice after 1 ps, then about 250 on average over the first
  50 ps and 240 over the second, going up and down by 20 or 30 from frame to
  frame. Radius of gyration 1.46 → 1.42 nm.

More in [ice-melting.md](ice-melting.md).

## Lysozyme in Water

| run | length here (the tutorial's) | time |
|---|---|---|
| minimisation | 457 steps | 30 s |
| NVT equilibration | 5 ps (100 ps) | 93 s |
| NPT equilibration | 5 ps (500 ps) | 94 s |
| production | 10 ps (10 ns) | 190 s |

Each of the four `grompp` steps takes 8 to 9 seconds on one processor, and so
does *Add ions*, which runs one too. Everything else takes a second or two.

What it came out as, against the published tutorial where it gives a number:

| | here | the tutorial |
|---|---|---|
| waters and chloride ions | 12,589 and 8 | 12,588 and 8 |
| minimisation | 457 steps, largest force 889 kJ/mol/nm on atom 567 | 566 steps, 980 on atom 567 |
| temperature | about 210 K the moment the speeds are handed out, back near 298 K within 1.5 ps | 298 K |
| density | 985 → 1026 kg/m³ over 5 ps | 1025.3 averaged over 500 ps |
| RMSD after the production run | about 0.08 nm | — |
| radius of gyration | 1.40 – 1.42 nm over 10 ps | 1.409 over 10 ns |

The number of minimisation steps changes from run to run, because *Add ions*
picks the waters it replaces at random; the atom with the largest force does
not.
