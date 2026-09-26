# An ice cube melting

I wrote this tutorial for Comfy-gmx lite. There is no published course behind
it, so this page holds my teacher's notes: what the simulation does, why I set
it up the way I did, what the class should see, and what to try next.

Open the **Tutorials** tab on the left, click **An ice cube melting** (under
*Made for Comfy-gmx lite*), press **Load as new graph**, then **Run**.

## What it shows

A tiny ice cube of 768 water molecules, about 3 nanometres across, floats in
empty space. One run of 200 picoseconds heats it from 200 K (−73 °C), colder
than any freezer, to 1000 K (727 °C). The thermostat's target climbs slowly to
400 K over the first 100 ps, then fast to 1000 K over the second 100 ps. On the
way the class sees ice, liquid and gas, one after the other:

- **Ice** for about the first 30 ps. The molecules shiver harder and harder,
  but the crystal holds.
- **Melting.** The corners go first, then the edges, then the faces. By about
  70 ps, near 340 K, the crystal is gone and the liquid has pulled itself into
  a round drop.
- **A drop of hot water** for about 40 ps, far above 100 °C.
- **Boiling.** Molecules fly off the drop, a few at first, then in a rush.
- **Gas** for the last 30 or 40 ps. The molecules fill the whole box.

Five results make it visible:

| block | what it draws | what the class should see |
| --- | --- | --- |
| **Energy terms** (Temperature) | the temperature through the run | a gentle slope for 100 ps, then a steep one |
| **Count the ice** | how many molecules still sit in the crystal pattern, frame by frame | a slow fall from about 30 ps, then to zero by about 70 ps |
| **Radius of gyration** | roughly how far the molecules are from the middle, on average | shrinks a little as the cube becomes a drop, shoots up as the drop boils away, and levels off when the gas fills the box |
| **Energy terms** (Potential) | how tightly the molecules hold on to each other | climbs the whole way, fastest while the drop boils away |
| **Preview trajectory** | a movie, one dot per molecule | a cube, then a ball, then a cloud |

This is what I got when I ran it in the online copy on one processor of my own
computer. It took 2 minutes 24 seconds from **Run** to the last block.

| time | temperature | counted as ice | radius of gyration | potential energy |
| --- | --- | --- | --- | --- |
| start | 202 K | 439 of 768 | 1.46 nm | −45,930 kJ/mol |
| 1 ps | 200 K | 274 | 1.44 nm | −42,589 kJ/mol |
| 20 ps | 236 K | 224 | 1.43 nm | −41,979 kJ/mol |
| 40 ps | 279 K | 135 | 1.43 nm | −40,511 kJ/mol |
| 60 ps | 323 K | 56 | 1.41 nm | −38,392 kJ/mol |
| 70 ps | 346 K | 0 | 1.39 nm | −36,748 kJ/mol |
| 100 ps | 412 K | 0 | 1.41 nm | −33,513 kJ/mol |
| 120 ps | 516 K | 0 | 1.55 nm | −27,029 kJ/mol |
| 140 ps | 654 K | 0 | 1.93 nm | −18,250 kJ/mol |
| 160 ps | 751 K | 0 | 2.66 nm | −10,329 kJ/mol |
| 200 ps | 1017 K | 0 | 2.73 nm | −6,800 kJ/mol |

The last molecule counted as ice went at 68.5 ps. The drop was smallest,
1.38 nm, at 73 ps. The thermometer reads a little above or below the target
from moment to moment, because the thermostat corrects it gently rather than
all at once.

On another computer the numbers will differ a little. Two machines round their
arithmetic in slightly different ways, those tiny differences grow over a run,
and so no two computers follow quite the same path.

## The science, for the teacher

**What ice is.** In liquid water every molecule tumbles past its neighbours.
In ice each molecule holds on to exactly four others with hydrogen bonds: it
points its two hydrogens at two of them, and the other two point a hydrogen at
it. Together they make a honeycomb of six-sided rings. Looking straight down
one axis of the crystal (z here), the rings line up into open channels. That
open structure is why ice is less dense than liquid water and floats.

**Why it melts from the surface.** A molecule at a corner or an edge has fewer
neighbours to hold on to than one inside, so it is the first to break free.
Melting spreads inwards from the surface. Even well below freezing, the
outermost layer of ice is loose and slightly wet, which is part of why ice is
slippery. That is the slow fall of the ice count before the crystal gives way.

**Why the drop is round, and smaller.** Surface tension pulls a liquid into the
shape with the least surface for its volume, which is a sphere. And liquid
water packs its molecules more closely than ice does. Both make the radius of
gyration go down as the cube melts.

**Why it melts and boils so late.** This model's ice melts at 272 K, and real
water boils at 373 K. Here the crystal is gone only near 340 K and the drop
starts to boil away somewhere above 400 K. The heat arrives far faster than in
any kitchen: the thermostat raises the temperature by 2 degrees every
picosecond, and later by 6. A crystal needs time to come apart, and at 373 K a
molecule escapes from the surface of a drop only now and then, far too rarely
to see in a few picoseconds. Heated this fast, the ice is briefly warmer than its melting
point and the drop warmer than its boiling point. The same can happen to real
water heated in a very clean cup in a microwave.

**Why boiling takes so much energy.** The potential energy measures how
tightly the molecules hold on to each other. Warming the ice and the drop only
makes the molecules shake harder. Boiling pulls them apart altogether, so the
energy climbs fastest then. Once everything is gas, the molecules have almost
nothing left to let go of, and it hardly climbs at all. That is why a pan of
boiling water stays at 100 °C until it is dry: the heat goes into pulling
molecules apart, not into making them hotter.

**How much of a gas it is.** The box is small, so the gas is crowded. At the
end the 768 molecules share a box 5.5 nm across, about a seventh as dense as
liquid water. Steam at 100 °C and normal air pressure is about 1600 times less
dense than water. What the class sees is still the change that matters: the
molecules no longer stick together, and spread through all the space they
have.

## How I set it up, and why

**The water model is TIP4P/Ice.** A model is the set of rules the computer uses
for how molecules push and pull on each other. TIP4P/Ice draws a water molecule
as four points: the oxygen, the two hydrogens, and an invisible point that
carries the oxygen's negative charge. Its authors fitted its numbers so that
its ice behaves like real ice. They put its melting point at 272.2 K, and real
ice melts at 273.15 K. Water models made for liquid water melt far lower: 146 K
for TIP3P and 215 K for SPC/E, two of the most used. With TIP3P, this cube
would already be 54 degrees above its melting point at the very start.

**The first block, *Ice crystal*, builds the crystal.** It places the oxygens
where ordinary ice (ice Ih, the hexagonal kind) puts them, then chooses which
way each molecule points its hydrogens. That choice follows two rules: every
oxygen has exactly two hydrogens near it, and every hydrogen bond has exactly
one hydrogen on it. The block also makes sure the molecules' small electric
charges do not all line up in one direction across the crystal. Changing the
*Seed for the hydrogens* gives a different, equally valid arrangement of them.

**Empty space around it, not water.** The cube floats in a 5.5 nm box of
nothing. That keeps the run small, fast enough for one processor in a lesson,
and it keeps the picture clear. It is also where the gas goes when the drop
boils. The box repeats in every direction, as simulation boxes do, so I made it
big enough that the cube never touches the copy of itself next door. A
molecule that boils off and flies out through one side of the box comes back
in through the opposite side.

**Settle, then heat.** A minimisation first nudges every molecule into place.
Then the run gives the molecules speeds that match 200 K, and a thermostat
steers the temperature towards a target that climbs as the run goes (GROMACS
calls this annealing): 200 K at the start, 400 K at 100 ps, 1000 K at 200 ps,
in straight lines between them. That is 100,000 steps of 2 femtoseconds. I
tried several schedules on this cube. At one steady rate from 200 K to 1000 K,
it melted within about 15 ps and stayed a drop for only about 30 ps before it
began to boil. Slow first and fast after gives every stage its share of the
film. The settings
also stop the whole lot drifting across the box, but not spinning: once
molecules fly out through the sides of the box, stopping the spin as well goes
wrong.

**How the ice is counted.** The *Count the ice* block uses the CHILL+ method.
For each molecule it looks at the arrangement of its four nearest neighbours
(the oxygens within 0.35 nm) and asks whether they sit the way they do in a
crystal. A molecule counts as ice when it has exactly four neighbours and all
four bonds are arranged like hexagonal ice (three of one kind, one of another)
or cubic ice (all four the same kind). Molecules on the surface of the crystal
do not pass this test even in perfect ice, because they have fewer than four
neighbours, so the count starts well below 768. Within the first picosecond it
drops: once the molecules start to shiver, some of them fail the strict test
even though the crystal is still there. What matters is what happens after
that.

## Things to try

- **Heat it more slowly.** In the *Run parameters (.mdp)* block of the run (in
  the box "2. Heat it: 200 K to 1000 K"), change `annealing-time` to
  `0 200 300` and `nsteps` to `150000`, and press **Run**. The run takes half
  as long again. Does the ice melt at a lower temperature when it has more
  time?
- **Hold it at one temperature.** Set `annealing = no` and give `ref_t` and
  `gen_temp` the same number. At 300 K the cube melts within a few tens of
  picoseconds; at 200 K it holds. Where is the line between melting and not
  melting in 100 ps?
- **Make the cube bigger.** Raise *Cells along x* (or y, or z) on *Ice
  crystal*. The time the run takes grows with the number of molecules, so
  double one direction at a time. Does a bigger cube melt later?
- **Look down the channels.** In the first 20 ps of the movie, turn the cube
  until you look straight down the z axis. The six-sided rings line up into
  channels.
- **Change the hydrogens.** Set a different *Seed for the hydrogens* on *Ice
  crystal*. The oxygens stay where they are, and the hydrogens point
  differently. The melting and the boiling should look the same. Ask the class
  why that is a good sign.

## References

- Abascal, J. L. F., Sanz, E., García Fernández, R. and Vega, C. (2005). A
  potential model for the study of ices and amorphous water: TIP4P/Ice. *J.
  Chem. Phys.* 122, 234511. [doi:10.1063/1.1931662](https://doi.org/10.1063/1.1931662)
- Nguyen, A. H. and Molinero, V. (2015). Identification of clathrate hydrates,
  hexagonal ice, cubic ice, and liquid water in simulations: the CHILL+
  algorithm. *J. Phys. Chem. B* 119, 9369-9376.
  [doi:10.1021/jp510289t](https://doi.org/10.1021/jp510289t)
- Vega, C., Sanz, E. and Abascal, J. L. F. (2005). The melting temperature of
  the most common models of water. *J. Chem. Phys.* 122, 114507.
  [doi:10.1063/1.1862245](https://doi.org/10.1063/1.1862245)
