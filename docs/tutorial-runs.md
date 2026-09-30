# How long each tutorial takes, and what it came out as

I ran every tutorial from start to finish in the online copy: the image that
`binder/build-image.sh` builds, which is the same one mybinder.org builds. I
limited the container to one processor and 2 GB of memory, as a mybinder.org
session is. The processor was one core of an AMD EPYC 9274F, and a cloud
machine may well be slower. GROMACS was 2026.3 from conda-forge.

The downloads (the protein and the force field) were already in the image, as
they are online, so they took no time.

The ice tutorial has grown since it was timed, from 22 blocks to 38. It now
also measures how much water is left in the drop, which took 13 seconds on one
processor of my workstation. The other 14 new blocks are an extra box, and its
note, that do it all again with salt in the ice. That box starts switched off,
so **Run**
leaves it out. Switched on, it heats a second cube, which took 118 seconds on
one processor of my workstation, the same as the pure cube there.

| # | Tutorial | Blocks | From Run to the last block | of which, simulating |
|---|---|---|---|---|
| 1 | An ice cube melting | 22 then, 38 now | 2 min 26 s | 2 min 6 s |
| 1 | Lysozyme in Water | 50 | 7 min 41 s | 6 min 47 s |

## On mybinder.org

On 2026-09-26 I ran both tutorials on mybinder.org itself, on two of its
sites, with nobody touching the page:

| Tutorial | Blocks | 2i2c site | of which, simulating | GESIS site | of which, simulating |
|---|---|---|---|---|---|
| An ice cube melting | 22 then, 38 now | 2 min 50 s | 2 min 29 s | 2 min 49 s | 2 min 28 s |
| Lysozyme in Water | 50 | 8 min 36 s | 7 min 37 s | 8 min 50 s | 7 min 46 s |

That is between 12 and 16 per cent slower than the online copy on my
workstation. Each session stayed open for the whole run, and the page showed
every step as it happened.

I timed the ice tutorial after I changed it to one heating run, in a session
of its own on each site. Before the change, with two runs of 100 ps at 300 K
and 200 K and 27 blocks, it took 3 min 12 s on the 2i2c site and 3 min 15 s on
GESIS.

## An ice cube melting

| run | length | time |
|---|---|---|
| minimisation | n/a | 1 s |
| heating, 200 K to 1000 K | 200 ps | 125 s |
| counting the ice | 401 frames | 14 s |

I ran it twice. It took 2 min 24 s the first time and 2 min 26 s the second;
the times of each part above are from the second.

What it came out as, the first time:

- The crystal: 768 molecules, 2.71 × 3.13 × 2.95 nm, with no overall dipole.
  439 of them pass the ice test at the start. The rest sit on the surface,
  with too few neighbours to pass.
- The temperature followed the thermostat: 202 K at the start, 303 K at 50 ps,
  412 K at 100 ps, 683 K at 150 ps and 1017 K at the end.
- Ice: 274 still ice after 1 ps, 224 at 20 ps, 135 at 40 ps, 56 at 60 ps, and
  none from 68.5 ps on.
- Radius of gyration: 1.46 nm at the start, 1.38 nm at 73 ps as a drop, back
  above 1.45 nm at 105 ps as the drop began to boil away, 2.65 nm at 160 ps,
  and 2.73 nm at the end, with the gas spread through the box.
- Potential energy: −45,930 kJ/mol at the start, −6,800 kJ/mol at the end.

The second time, 442 passed the ice test at the start and the ice was all but
gone at 61 ps rather than 67. Two runs never follow quite the same path, and a
few picoseconds either way is the size of the difference to expect.

There is more in [ice-melting.md](ice-melting.md).

## Lysozyme in Water

| run | length here (the tutorial's) | time |
|---|---|---|
| minimisation | 457 steps | 30 s |
| NVT equilibration | 5 ps (100 ps) | 93 s |
| NPT equilibration | 5 ps (500 ps) | 94 s |
| production | 10 ps (10 ns) | 190 s |

Each of the four `grompp` steps takes 8 to 9 seconds on one processor, and so
does *Add ions*, which runs one too. Everything else takes a second or two.

Here is what it came out as, next to the published tutorial wherever it gives
a number:

| | here | the tutorial |
|---|---|---|
| waters and chloride ions | 12,589 and 8 | 12,588 and 8 |
| minimisation | 457 steps, largest force 889 kJ/mol/nm on atom 567 | 566 steps, 980 on atom 567 |
| temperature | about 210 K the moment the speeds are handed out, back near 298 K within 1.5 ps | 298 K |
| density | 985 → 1026 kg/m³ over 5 ps | 1025.3 averaged over 500 ps |
| RMSD after the production run | about 0.08 nm | not given |
| radius of gyration | 1.40 to 1.42 nm over 10 ps | 1.409 over 10 ns |

The number of minimisation steps changes from run to run, because *Add ions*
picks the waters it replaces at random. The atom with the largest force does
not change.
