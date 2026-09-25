# An ice cube melting

A tutorial written for Comfy-gmx lite. There is no published course behind it,
so this page is the teacher's notes: what the simulation does, why it is set up
the way it is, what the class should see, and what to try next.

Open the **Tutorials** tab on the left, click **An ice cube melting** (under
*Made for Comfy-gmx lite*), press **Load as new graph**, then **Run**.

## What it shows

A tiny ice cube — 768 water molecules, about 3 nanometres across — floats in
empty space. The same cube is simulated twice for 100 picoseconds:

- at **300 K** (27 °C), room temperature, it melts. The corners go first, then
  the edges, then the faces. Within a few tens of picoseconds the crystal is
  gone, and the liquid pulls itself into a round drop.
- at **200 K** (−73 °C), colder than any freezer, it holds. The molecules
  shiver in place, but the pattern of the crystal stays.

Three results make the difference visible:

| block | what it draws | warm run | cold run |
| --- | --- | --- | --- |
| **Count the ice** | how many molecules still sit in the crystal pattern, frame by frame | falls to zero | stays nearly flat |
| **Radius of gyration** | roughly how far the molecules are from the middle, on average | shrinks clearly as the cube becomes a drop | shrinks a little |
| **Preview trajectory** | a movie, one dot per molecule | a cube turning into a ball | a cube |

What it came out as when it was run here, in the online copy on one
processor (2 minutes 48 seconds from **Run** to the last block):

| | warm, 300 K | cold, 200 K |
| --- | --- | --- |
| counted as ice at the start | 442 of 768 | 442 of 768 |
| after 1 ps | 180 | 270 |
| after 10 ps | 105 | 258 |
| after 30 ps | 15 | 237 |
| from 40 ps to the end | 0 | about 240, give or take 20 |
| radius of gyration, start → end | 1.46 → 1.38 nm | 1.46 → 1.42 nm |

Each 100 ps run took a little over a minute. On another computer the numbers
will differ a little: the tiny differences in how two machines round their
arithmetic grow over a run, so no two computers follow quite the same path.

## The science, for the teacher

**What ice is.** In liquid water every molecule tumbles past its neighbours.
In ice each molecule holds on to exactly four others with hydrogen bonds: it
points its two hydrogens at two of them, and the other two point a hydrogen at
it. Together they make a honeycomb of six-sided rings. Looking straight down
one axis of the crystal (z here), the rings line up into open channels, and
that open structure is why ice is less dense than liquid water and floats.

**Why it melts from the surface.** A molecule at a corner or an edge has fewer
neighbours to hold on to than one inside, so it is the first to break free.
Melting spreads inwards from the surface. Even well below freezing the outermost
layer of ice is loose and slightly wet, which is part of why ice is slippery —
the cold run shows a little of this too.

**Why the drop is round, and smaller.** Surface tension pulls a liquid into the
shape with the least surface for its volume, which is a sphere. And liquid
water packs its molecules more closely than ice does. Both make the radius of
gyration of the warm run go down.

**Why a tiny cube melts below 0 °C.** A small crystal has a large share of its
molecules at the surface, where they are held less firmly, so it melts at a
lower temperature than a big one. This cube starts to melt, slowly, even at
250 K (−23 °C).

## How it is set up, and why

**The water model is TIP4P/Ice.** A model is the set of rules the computer uses
for how molecules push and pull on each other. TIP4P/Ice draws a water molecule
as four points: the oxygen, the two hydrogens, and an invisible point that
carries the oxygen's negative charge. Its numbers were fitted so that its ice
behaves like real ice: its authors put its melting point at 272.2 K, and real
ice melts at 273.15 K. Water models made for liquid water melt far lower —
146 K for TIP3P and 215 K for SPC/E, two of the most used. With TIP3P, even the
cold run here would be 54 degrees above the melting point.

**The crystal is built by the first block, *Ice crystal*.** It places the
oxygens where ordinary ice (ice Ih, the hexagonal kind) puts them, then chooses
which way each molecule points its hydrogens. That choice has rules — every
oxygen has exactly two hydrogens near it and every hydrogen bond has exactly one
hydrogen on it — and the block also makes sure the molecules' small electric
charges do not all line up in one direction across the crystal. Changing the
*Seed for the hydrogens* gives a different, equally valid arrangement of them.

**Empty space instead of water around it.** The cube floats in a 5.5 nm box of
nothing. That keeps the run small (fast enough for one processor in a lesson)
and the picture clear. The box repeats in every direction, as simulation boxes
do, so it is big enough that the cube never touches the copy of itself next
door. It also melts far faster than a real ice cube in a drink: it is tiny,
and the thermostat hands every molecule the heat it needs at once, where a real
cube has to wait for heat to flow in from the drink around it.

**Settle, then run.** A minimisation first nudges every molecule into place.
Then each run gives the molecules speeds that match its temperature and keeps
that temperature with a thermostat, for 50,000 steps of 2 femtoseconds. The
settings also stop the cube drifting or spinning, so it stays in the middle of
the picture; GROMACS warns about that once, and the run is allowed that one
warning.

**How the ice is counted.** The *Count the ice* block uses the CHILL+ method.
For each molecule it looks at the arrangement of its four nearest neighbours
(the oxygens within 0.35 nm) and asks whether they sit the way they do in a
crystal. A molecule counts as ice when it has exactly four neighbours and all
four bonds are arranged like hexagonal ice (three of one kind, one of another)
or cubic ice (all four the same kind). Molecules on the surface of the crystal
do not pass this test even in perfect ice, because they have fewer than four
neighbours, so the count starts well below 768. Within half a picosecond it
drops in both runs: once the molecules start to shiver, some of them fail the
strict test even though the crystal is still there. What tells the two runs
apart is what happens after that.

## Things to try

- **Another temperature.** In the *Run parameters (.mdp)* block of the cold
  run (in the box "3. Cold: 200 K"), change `ref_t` and `gen_temp` — both, to
  the same number — and press **Run**. At 250 K the cube melts, but slowly. Where is the line
  between melting and not melting in 100 ps?
- **A bigger cube.** Raise *Cells along x* (or y, or z) on *Ice crystal*. The
  time the runs take grows with the number of molecules, so double one
  direction at a time. Does a bigger cube take longer to melt?
- **Look down the channels.** In the cold run's movie, turn the cube until you
  look straight down the z axis. The six-sided rings line up into channels.
- **A different hydrogen arrangement.** Change *Seed for the hydrogens* on
  *Ice crystal*. The
  oxygens stay where they are; the hydrogens point differently. The melting
  should look the same — ask the class why that is a good sign.

## References

- Abascal, J. L. F., Sanz, E., García Fernández, R. and Vega, C. (2005). A
  potential model for the study of ices and amorphous water: TIP4P/Ice. *J.
  Chem. Phys.* 122, 234511. [doi:10.1063/1.1931662](https://doi.org/10.1063/1.1931662)
- Nguyen, A. H. and Molinero, V. (2015). Identification of clathrate hydrates,
  hexagonal ice, cubic ice, and liquid water in simulations: the CHILL+
  algorithm. *J. Phys. Chem. B* 119, 9369–9376.
  [doi:10.1021/jp510289t](https://doi.org/10.1021/jp510289t)
- Vega, C., Sanz, E. and Abascal, J. L. F. (2005). The melting temperature of
  the most common models of water. *J. Chem. Phys.* 122, 114507.
  [doi:10.1063/1.1862245](https://doi.org/10.1063/1.1862245)
