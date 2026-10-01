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

Six results make it visible:

| block | what it draws | what the class should see |
| --- | --- | --- |
| **Energy terms** (Temperature) | the temperature through the run | a gentle slope for 100 ps, then a steep one |
| **Count the ice** | how many molecules still sit in the crystal pattern, frame by frame | a slow fall from about 30 ps, then to zero by about 70 ps |
| **Radius of gyration** | roughly how far the molecules are from the middle, on average | shrinks a little as the cube becomes a drop, shoots up as the drop boils away, and levels off when the gas fills the box |
| **Energy terms** (Potential) | how tightly the molecules hold on to each other | climbs the whole way, fastest while the drop boils away |
| **Water in the drop** | the share of the water still in the liquid drop, frame by frame | near 100 % until the drop starts to boil, then down to nothing |
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

I added *Water in the drop* later, and ran it on a workstation with 4
processors. The drop held over 90 % of its water until 125 ps, was half gone at
147 ps, and was empty from 180 ps on. The thermostat's target at those moments
was 550 K, 682 K and 880 K. On one processor the block takes 13 seconds.

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

## Extra: the same with salt

A colleague asked whether this simulation can show salt raising the boiling
point of water. It can show which way salt pushes, and why. It cannot show by
how much. The box **3. Extra: the same with salt**, to the right of the run,
does it. It starts switched off, so **Run** leaves it out: the class sees the
pure cube first, and the salty one when you are ready.

**Switching it on.** Right-click the box's title bar and choose **Switch this
chunk back on** (or hold Ctrl and Alt and click the title bar). Then press
**Run**. Only the new box runs, because everything the pure cube produced is
reused. It takes about as long as the first run: on one processor the salty
cube heated in 118 seconds, the same as the pure one. The same menu switches
it off again.

**What is in it.** The same cube, with 26 of its 768 water molecules swapped
for sodium ions (Na+) and 26 for chloride ions (Cl−). That is 2 moles of salt
per kilogram of water, more than three times as salty as the sea (about 0.6).
The box settles the cube and heats it exactly as boxes 1 and 2 do, with copies
of the same two *Run parameters (.mdp)* blocks. If you change the heating in
box 2, change the copy in box 3 too, or the comparison is not fair. Two
*Compare graphs* blocks set the pure and the salty cube side by side: the ice
count, and the water still in the drop. Its movie shows the ions too, sodium
in purple and chloride in green.

**What the class should see.** This is my run on a workstation. The
temperatures are the thermostat's target at that moment.

| | pure water | with salt |
| --- | --- | --- |
| pass the ice test at the start | 441 of 768 | 163 of 716 |
| after 1 ps | 285 | 21 |
| ice all but gone (2 % of the start left) | 61 ps (322 K) | 20.5 ps (241 K) |
| water in the drop: over 90 % until | 125 ps (550 K) | 128 ps (568 K) |
| half gone | 147 ps (682 K) | 150.5 ps (703 K) |
| 10 % left | 156 ps (736 K) | 179.5 ps (877 K) |
| at the end, 1000 K | none | 3.6 %, stuck to the ions |

- **The salty ice melts sooner.** Every ion breaks the honeycomb around it, so
  fewer molecules pass the ice test from the start, and the rest give way at a
  lower temperature.
- **The salty drop holds on to its water for longer.** It starts to lose water
  at nearly the same moment, and it is half gone only a few picoseconds later;
  how many changes from run to run. The difference is at the end: the last
  tenth of the water stays about 23 ps (140 degrees) longer, and a few per cent
  never leave at all.

**The science.** Salt in water falls apart into ions, and each ion holds on to
the water molecules around it. A molecule held by an ion is less free to fly
off, so salty water has to be hotter before it boils. The ions also get in the
way of the molecules locking into the pattern of ice, so salty water has to be
colder before it freezes. That is why roads are salted in winter, and why the
sea freezes at about −2 °C. The size of the effect depends on how many
particles are dissolved, not on what they are. For water, every mole of
dissolved particles in a kilogram raises the boiling point by about 0.51
degrees and lowers the freezing point by about 1.86. Salt gives two particles,
a sodium and a chloride, so at 2 moles per kilogram the boiling point goes up
by about 2 degrees and the freezing point down by about 7.

**Why the simulation overdoes it.** Here both shifts are tens of degrees. There
are three reasons, and they are worth telling the class.

- The heating is very fast. As with the pure cube, everything happens later
  than it would in a kitchen, and a difference between the two cubes is
  stretched out with it.
- The drop is tiny, and it gets saltier as it boils. By the time half the water
  has gone, the salt is twice as concentrated, and the last few dozen water
  molecules are all held by ions. A pan of salt water only gets there when it
  has nearly boiled dry.
- The salty crystal is not one that nature makes. Real ice pushes salt out as it
  freezes: sea ice is far less salty than the sea, with the salt left in small
  pockets of brine. A crystal with
  ions spread all through it is salty water frozen far too fast for the salt to
  get out, and it is weaker for it.

So the class sees the right direction for the right reason, but not the right
size. I would say so when I show it.

**How the salt is put in.** *Ice crystal* has a box *Salt: pairs of Na+ and
Cl-*. It swaps that many water molecules for sodium ions and as many again for
chloride ions, each ion where the molecule's oxygen was, and no two ions closer
than 0.5 nm. *Seed for the salt*, under advanced, chooses which molecules; the
hydrogens of the rest stay as they were. The block reports how much salt that
came to, in moles per kilogram of water. Left empty, the box gives the pure
crystal, exactly as before. The ions are the ones Joung and Cheatham made for
TIP4P-Ew water, a close relative of TIP4P/Ice, as GROMACS 2026.3 ships them in
its amber14sb.ff force field.

**How the drop is measured.** *Water in the drop* looks for the biggest group
of molecules that touch, closer than 0.35 nm (about the distance to a
molecule's nearest neighbours in liquid water), directly or through others.
That is the drop. It counts the water molecules in it, frame by frame, as a
share of all the water. The ions belong to the drop but are not counted. The
gas in this small box is crowded, and gas molecules brush past the drop all
the time, so a molecule counts only when it is in the drop in the frame
before and the frame after as well.

**Things to try with salt.**

- **Less salt.** Set the salt to 13 pairs, about 1 mole per kilogram. Is the
  difference still there?
- **More salt.** 40 pairs is about 3 moles per kilogram. Does the salty drop
  leave more water behind?
- **How much is chance?** Change *Seed for the salt*, or `gen_seed` in the heating
  run's *Run parameters (.mdp)* (in both boxes, to keep them alike), and run
  again. Which parts of the difference come back every time?

## Extra: cool it down again

Does the gas freeze back into ice when it is cooled again? Two more boxes
answer that: **4. Extra: cool it down again**, under the pure run, and **5.
Extra: cool the salty one down too**, under the salty cube. Both start
switched off, like the salt box. Their note stands to their left.

**Switching them on.** Right-click each box's title bar and choose **Switch
this chunk back on**, then press **Run**. Only the new boxes run, because the
heating runs are reused. Box 4 needs nothing but the heating above it. Box 5
needs the salt box switched on and run as well, and its two graphs, which set
pure and salty side by side, need box 4 too. Each cooling run takes as long
as a heating run: on one processor, 119 seconds for the pure gas and 117 for
the salty one.

**What is in them.** Each box starts from the last frame of the heating run
above it: the gas at 1000 K, with every molecule where it was and moving as
fast as it was. So nothing jumps: the pure gas ended the heating at 990 K and
started the cooling at 990 K. The *Run parameters (.mdp)* block cools it along
the heating schedule backwards: fast from 1000 K to 400 K over the first
100 ps, then slowly to 200 K over the second 100 ps. The ice count, the water
in the drop and a movie follow it, as in the heating. Box 5 has a copy of box
4's *Run parameters (.mdp)*. If you change one, change the other too.

The two movies have *Periodic boundary* set to **lump**. The drop forms
wherever the gas happens to gather, often across the edge of the box, and
the box repeats in every direction, so the usual setting draws it cut in
two, half at each side of the box. **lump** moves every frame so the drop
sits in the middle, in one piece. The heating movies do not need it: the
cube starts in the middle, and its drop stays there.

**What the class should see.** This is my run on a workstation. The
temperatures are the thermostat's target at that moment.

| | pure water | with salt |
| --- | --- | --- |
| water in the drop at the start, 1000 K | none | 8 %, the water that never left the ions |
| back in the drop: 10 % | 62.5 ps (625 K) | 35.5 ps (787 K) |
| half | 74.5 ps (553 K) | 70 ps (580 K) |
| 90 % | 83 ps (502 K) | 84 ps (496 K) |
| all of it | from 147.5 ps (305 K) on | from 173.5 ps (253 K) on |
| most molecules passing the ice test in one frame | 2 (5 in another run) | 1 |

- **The gas turns back into a drop.** As the molecules slow down, the ones
  that meet stick together again, and the drop gathers them up. It comes back
  at a lower temperature than it left: in the same run, the pure drop was half
  gone at 670 K on the way up, and half back at 553 K on the way down. Both
  lag behind a thermostat that moves this fast, as the melting did.
- **A ball, or a column through the box.** The water does not always end as a
  round drop. It can also settle into a thick column that runs out through one
  side of the box and back in through the opposite side, joined to itself: the
  box repeats in every direction, so the column has no ends. A liquid pulls
  itself into the shape with the least surface, and for 768 molecules in this
  box the two shapes come out almost equal: about 39 nm² for a ball 3.5 nm
  across, and about 40 nm² for the column. So either can form. In my two runs
  the pure water made a column once and a ball once, and so did the salty
  water. The movie shows a column as a band that touches two opposite faces of
  the box. It is one body of water, and the drop graph counts it as one.
- **The ice does not come back.** Now and then a few molecules pass the ice
  test by chance, as happens in any cold water. The pure cube had 439 at the
  start of the heating, and nothing like that returns, not even at 200 K.
- **Salt makes little difference here.** The salty drop starts from the water
  that never left its ions. In one of my runs it gathered the rest back a
  little sooner than the pure drop did, and in another a little later, so that
  part is chance.

**Why the ice does not come back.** Melting and freezing are not mirror images.
A crystal can start to melt anywhere on its surface, and this one comes apart
in picoseconds. Freezing has to start from a seed: a cluster of molecules that
happen to line up into the pattern of ice together, big enough to grow rather
than fall apart again. Small clusters like that form and fall apart all the
time. One big enough to grow is rare, and the less the water is cooled below
its freezing point, the bigger it has to be. So pure water can be cooled well
below 0 °C and stay liquid. This is supercooling, and it happens in nature:
the tiny droplets in clouds stay liquid down to about −38 °C. In a glass of
water, freezing starts from something a seed can grow on, such as dust or a
scratch in the glass. The drop in the simulation has nothing like that, and
200 ps is far too short for a seed to form on its own.

**What I tried before building it.** I cooled a drop to 230 K (−43 °C) and held
it there for 900 ps, over four times as long as the cooling run. No more than
5 molecules passed the ice test at any moment, pure or salty. I also started
from frames where the cube had not finished melting, and cooled them at once
to 230 K or to 200 K. The ice that was left did not grow back. At 230 K it
kept melting, from 195 molecules to 57 in a nanosecond. At 200 K it went down
from 256 to around 190 in 250 ps and stayed near that for the rest of the
500 ps run. A crystal this small melts at a lower temperature than a big one,
because so much of it is surface. With salt, the 37 molecules of ice that were
left melted away at both temperatures.

**Things to try with the cooling.**

- **Watch the drop gather.** Play the movie in box 4 between about 60 and
  85 ps, when most of the water comes back into the drop.
- **Cool it more slowly.** In box 4's *Run parameters (.mdp)*, set
  `annealing-time` to `0 100 1000`, `annealing-temp` to `1000 230 230` and
  `nsteps` to `500000`: down to 230 K in 100 ps, then held there for 900 ps.
  That is the run I tried. It takes five times as long, about ten minutes on
  one processor. Does any ice come back?

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
- Joung, I. S. and Cheatham, T. E. (2008). Determination of alkali and halide
  monovalent ion parameters for use in explicitly solvated biomolecular
  simulations. *J. Phys. Chem. B* 112, 9020-9041.
  [doi:10.1021/jp8001614](https://doi.org/10.1021/jp8001614)
- Nguyen, A. H. and Molinero, V. (2015). Identification of clathrate hydrates,
  hexagonal ice, cubic ice, and liquid water in simulations: the CHILL+
  algorithm. *J. Phys. Chem. B* 119, 9369-9376.
  [doi:10.1021/jp510289t](https://doi.org/10.1021/jp510289t)
- Vega, C., Sanz, E. and Abascal, J. L. F. (2005). The melting temperature of
  the most common models of water. *J. Chem. Phys.* 122, 114507.
  [doi:10.1063/1.1862245](https://doi.org/10.1063/1.1862245)
