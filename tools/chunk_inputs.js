/* What does a chunk take in, and can it be pointed somewhere else from one
   window?

   A chunk is eight or nineteen blocks in a coloured box. Pointing one at a
   different structure meant opening the blocks inside it and finding the two
   or three that mention a file, which is a hunt through boxes that all look
   alike. Inputs, in the box's right-click menu, lists everything the chunk
   needs from outside, and every row does exactly what editing the block would
   have done.

   What has to stay true:

     * wires from one block in the chunk to another are left out: those are
       how the chunk works, not something coming into it
     * a socket fed from outside is listed, and says where it is fed from
     * a socket with nothing in it is listed
     * required and optional are told apart, because listing five optional
       index files beside the one trajectory that matters buries the
       trajectory
     * a file box on a block with no sockets at all is what the chunk reads
       from disk, and an empty one is still waiting, not optional
     * a file box on a block that also has sockets is an alternative to a
       wire, so an empty one is only the wire being used
     * two blocks of the same kind in one chunk are told apart
     * what can feed a socket is the same rule the canvas uses, and the ones
       carrying exactly what was asked for come first
     * the chunk's own sockets stand for the ones on the blocks inside it, so
       wiring one draws the ordinary block-to-block link and the saved graph
       knows nothing about chunk sockets
     * a chunk hands out what nothing inside it uses, and not the plumbing
       between its own blocks
     * a chunk knows which blocks it brought with it, so the sockets are
       right from the first moment rather than after the box has finished
       growing around its contents
     * renaming a chunk does not wipe its title bar
     * a wall is a patch panel: letting a wire go on the all-purpose dot parks
       what that wire carries on the wall and stops, and nothing inside the
       box is wired up for you
     * both walls do exactly the same thing, and the same cable let go on the
       other wall moves rather than doubles
     * only a source goes on a wall, because a socket waiting to be fed has
       nothing behind it to hang there
     * two cables carrying the same kind of file can be told apart, and any
       of them can be given a name of your own
     * a wall only grows a dot for a cable you put there, so wiring one
       block's output straight out of the chunk still draws straight
     * a cable is named as shortly as it can be and still be unique: what
       comes out of the socket, then the block, then both, then numbered,
       worked out for the whole box at once so a cable nothing clashes with
       keeps its short name
     * the names are written outside the box, and only go back inside where
       another box stands right against that wall
     * the left wall fills from the top and the right wall from the bottom,
       so names never pile onto the top right of the blocks inside
     * cutting the last wire through a wall dot takes the dot off the wall,
       and says so; a dot with other wires through it, or one not wired
       onward yet, is left alone
     * picking a wire up by its end leaves its dot until you let go
     * a cable not wired onward yet still shows a line to its block
     * a cable on two boxes' walls runs wall to wall while it waits, the same
       way the wire will run once something is connected
     * double-clicking an output puts it on the right-hand wall of its box,
       moves it there from the left, or takes it off if it is already there
     * a cable that doubles back at a wall makes a short U, not a long S, and
       ordinary block-to-block wires keep exactly the shape they had
     * cables on a wall are saved with the workflow, kept as copies, and left
       out of the file entirely when a wall is empty

   Run:  node tools/chunk_inputs.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failures = 0;
function check(ok, complaint) {
  if (ok) return;
  failures += 1;
  console.log(`  FAILED: ${complaint}`);
}

function stub() {
  return { style: { setProperty() {} }, classList: { add() {}, remove() {}, toggle() {} },
           addEventListener() {}, appendChild() {}, setAttribute() {},
           querySelectorAll: () => [], offsetWidth: 200, offsetHeight: 100 };
}

function loadEditor() {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
  const sandbox = {
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { addEventListener() {}, getElementById: () => null,
                createElement: () => stub(), createElementNS: () => stub() },
    window: { addEventListener() {} },
    navigator: { platform: 'Linux x86_64', userAgent: 'Linux' },
    console,
    UI: { el: () => stub(), toast() {}, bytes: () => '', contextMenu() {} },
    API: {}, App: {}, Sessions: {}, Panels: {}, requestAnimationFrame: (fn) => fn(),
    setTimeout, clearTimeout, Math, JSON, Set, Map, Date,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source + '\n;globalThis.__Editor = Editor;', sandbox,
                  { filename: 'graph.js' });
  return { Editor: sandbox.__Editor, sandbox };
}

/* A chunk shaped like the packaged analysis one: a loader with nothing but a
   file box, two of the same trajectory block, and one measuring block. One
   block is left outside the box, to stand for the run the chunk is joined to. */
function aChunk(Editor) {
  Editor.defs = {
    'io.structure': {
      title: 'Load structure', inputs: [],
      outputs: [{ name: 'structure', type: 'structure', label: 'structure' }],
      params: [{ name: 'path', type: 'file', label: 'File' }],
    },
    'gmx.trjconv': {
      title: 'Process trajectory', params: [],
      inputs: [{ name: 'traj', type: 'traj', label: 'trajectory' },
               { name: 'tpr', type: 'tpr', label: 'tpr' },
               { name: 'index', type: 'index', label: 'index', optional: true }],
      outputs: [{ name: 'traj', type: 'traj', label: 'trajectory' },
                { name: 'tpr', type: 'tpr', label: 'tpr' }],
    },
    'prep.clean': {
      title: 'Clean structure',
      inputs: [{ name: 'structure', type: 'structure', label: 'structure' }],
      outputs: [{ name: 'structure', type: 'structure', label: 'structure' }],
      params: [],
    },
    'view.plot': {
      title: 'Preview plot',
      inputs: [{ name: 'xvg', type: 'xvg', label: 'plot' }],
      outputs: [],
      params: [{ name: 'path', type: 'file', label: 'Or a file' }],
    },
    'gmx.mdrun': {
      title: 'Run MD', inputs: [], params: [],
      outputs: [{ name: 'traj', type: 'traj', label: 'trajectory' },
                { name: 'tpr', type: 'tpr', label: 'tpr' },
                { name: 'log', type: 'file', label: 'log' }],
    },
  };
  const make = (id, type, x) => [id, { id, type, title: Editor.defs[type].title,
                                       pos: [x, 0], params: {}, _el: stub() }];
  Editor.nodes = new Map([
    make('load', 'io.structure', 0),
    make('clean', 'prep.clean', 100),
    make('pbc', 'gmx.trjconv', 200),
    make('fit', 'gmx.trjconv', 400),
    make('plot', 'view.plot', 600),
    make('run', 'gmx.mdrun', -400),      // outside the box
  ]);
  Editor.links = [
    { from_node: 'load', from_port: 'structure', to_node: 'clean', to_port: 'structure' },
    { from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' },
    { from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' },
  ];
  const group = { id: 'g1', title: 'Standard analysis', bounds: [0, 0, 800, 400] };
  Editor.groups = [group];
  Editor.nodesInGroup = () => ['load', 'clean', 'pbc', 'fit', 'plot'];
  return group;
}

const { Editor, sandbox } = loadEditor();
// Kept aside before anything is stubbed out, because a later section replaces
// the real wire drawing with a do-nothing one and then needs it back.
const realDrawWires = Editor.drawWires;
const realConnect = Editor.connect;
const group = aChunk(Editor);
const { files, sockets } = Editor.chunkInputs(group);
const say = (row) => `${row.node.title}${row.which}::`
  + `${row.param ? row.param.label : row.port.label}::${row.kind}`;
const lines = [].concat(files, sockets).map(say);

console.log('what is left out');
check(!sockets.some((r) => r.node.id === 'fit' && r.port.name === 'traj'),
      'a wire from one block in the chunk to another is being listed as '
      + 'something the chunk takes in');

console.log('what is listed');
check(lines.includes('Load structure::File::missing'),
      'THE COMMON CASE: the empty file box on the block that reads the chunk\'s '
      + `structure is not listed as still waiting (got ${JSON.stringify(lines)})`);
check(lines.includes('Preview plot::Or a file::spare'),
      'the file box that is only an alternative to a wire is being treated as '
      + 'something still to fill in');
const pbc = sockets.filter((r) => r.node.id === 'pbc');
check(pbc.some((r) => r.port.name === 'traj' && r.kind === 'fed'),
      'a socket fed from outside the chunk is not marked as fed');
check(pbc.some((r) => r.port.name === 'tpr' && r.kind === 'missing'),
      'a needed socket with nothing in it is not marked as still waiting');
check(pbc.some((r) => r.port.name === 'index' && r.kind === 'spare'),
      'an optional socket is being mixed in with the ones that matter');

console.log('two of the same block');
check(lines.some((l) => l.startsWith('Process trajectory (1st of 2)')),
      'two blocks of the same kind in one chunk are not told apart, so the '
      + `rows cannot be matched to the blocks (${JSON.stringify(lines)})`);
check(lines.some((l) => l.startsWith('Process trajectory (2nd of 2)')),
      'only the first of two same-named blocks is numbered');

console.log('what may feed a socket');
const forTpr = Editor.chunkSourcesFor(group, { name: 'tpr', type: 'tpr' });
check(forTpr.length > 0, 'nothing is offered to feed a tpr socket');
check(forTpr[0].node.id === 'run' && forTpr[0].port.name === 'tpr' && forTpr[0].exact,
      'the one carrying exactly what was asked for is not first, so the list '
      + 'opens on a log file offered as a run input');
check(forTpr.some((s) => s.port.name === 'log' && !s.exact),
      'a plain file is no longer offered at all -- the canvas would still let '
      + 'you draw that wire, and the two must not disagree');
check(!forTpr.some((s) => s.node.id === 'pbc'),
      'a block inside the chunk is offered as a source, which would wire the '
      + 'chunk to itself');

console.log('what a chunk hands out');
const gives = Editor.chunkOutputs(group).map((r) => `${r.node.title}::${r.port.label}`);
check(gives.includes('Process trajectory::trajectory')
   || gives.includes('Process trajectory::tpr'),
      `the last block's sockets are not offered as the chunk's own (${JSON.stringify(gives)})`);
check(!gives.includes('Load structure::structure'),
      'a socket feeding another block in the same chunk is offered as something '
      + 'the chunk hands out, which is plumbing, not what the chunk is for');
check(gives.includes('Clean structure::structure'),
      'the last block in a line inside the chunk does not offer what it made');

console.log('which blocks a chunk counts as its own');
// The box is deliberately drawn too small, the way it is for the second or
// two after a chunk lands while its blocks are still laying out.
group.bounds = [0, 0, 10, 10];
Editor.nodesInGroup = () => [];
group.own = new Set(['load', 'clean', 'pbc', 'fit', 'plot']);
check(Editor.chunkMembers(group).length === 5,
      'a chunk that has not finished laying out forgets the blocks it brought '
      + 'with it, so its sockets show the wrong thing until the box has grown');
group.own = new Set();
check(Editor.chunkMembers(group).length === 0,
      'a chunk still claims blocks after they have been dragged out of it');

/* A wall is a patch panel, not a guess. Letting a wire go on the all-purpose
   dot gives what that wire carries its own named dot on that wall and stops
   there. Nothing inside the box is joined to anything: you take a fresh wire
   from the new dot to wherever you actually want it. */
console.log('letting go of a wire on the all-purpose dot');
Editor.nodesInGroup = () => ['load', 'clean', 'pbc', 'fit', 'plot'];
group.own = new Set();
group.patch = [];
let joined = [];
let toasts = [];
Editor.connect = (a, b, c, d) => { joined.push(`${a}.${b} -> ${c}.${d}`); };
Editor.drawWires = () => {};
Editor.changed = () => {};
Editor.mark = () => {};
Editor.refreshPortStates = () => {};
sandbox.UI.toast = (m) => toasts.push(m);
sandbox.App.check = () => {};
const catchAll = (side) => ({ dataset: { wall: side, group: group.id } });
const dragOf = (id, portName, type) => ({
  node: Editor.nodes.get(id),
  port: { name: portName, type, label: portName },
  direction: 'out',
});

Editor._dropOnWall(catchAll('west'), dragOf('run', 'traj', 'traj'), { clientX: 0, clientY: 0 });
check(group.patch.length === 1
   && group.patch[0].node === 'run' && group.patch[0].port === 'traj'
   && group.patch[0].side === 'west',
      'letting a wire go on the wall did not park what it carries there '
      + `(got ${JSON.stringify(group.patch)})`);
check(joined.length === 0,
      'THE POINT: dropping on a wall wired the thing to a block inside the box '
      + `by itself, instead of leaving the choice to you (${JSON.stringify(joined)})`);

// Both walls take anything, so the same cable let go on the other wall is the
// same cable, moved. Two dots for one thing would be two names for one thing.
Editor._dropOnWall(catchAll('east'), dragOf('run', 'traj', 'traj'), { clientX: 0, clientY: 0 });
check(group.patch.length === 1 && group.patch[0].side === 'east',
      `dropping a cable already on one wall onto the other made a second copy `
      + `instead of moving it (${JSON.stringify(group.patch)})`);

// Only a source goes on a wall: a wire dragged backwards out of a socket that
// wants feeding has nothing behind it to hang there.
toasts = [];
Editor._dropOnWall(catchAll('west'),
  { node: Editor.nodes.get('pbc'), port: { name: 'tpr', type: 'tpr', label: 'tpr' },
    direction: 'in' }, { clientX: 0, clientY: 0 });
check(group.patch.length === 1,
      'a wire dragged backwards out of a socket was parked on the wall, where '
      + 'there is nothing behind it to hang');
check(toasts.length === 1 && /makes/.test(toasts[0]),
      `and it did not say why (${JSON.stringify(toasts)})`);

/* The name is written out beside the dot, so a long one is a long strip of
   text laid across the picture. It has to be as short as it can be and still
   say which cable is which. */
console.log('a cable is named as shortly as it can be');
group.patch = [{ node: 'pbc', port: 'traj', side: 'west' }];
check(Editor._patchName(group, group.patch[0]) === 'trajectory',
      'THE POINT: the only cable on the box is named after its block as well '
      + 'as its socket, which is a long strip of text saying nothing the one '
      + `dot did not already say (${Editor._patchName(group, group.patch[0])})`);

console.log('telling two cables of the same kind apart');
group.patch = [
  { node: 'pbc', port: 'traj', side: 'west' },
  { node: 'fit', port: 'traj', side: 'west' },
];
let names = group.patch.map((e) => Editor._patchName(group, e));
check(names.every((n) => /Process trajectory/.test(n)),
      'two cables that would read the same are not lengthened to say which '
      + `block each comes from (${JSON.stringify(names)})`);

// Two cables from blocks with different names need only those names. Adding
// the socket on top says nothing and doubles the length of both.
group.patch = [
  { node: 'run', port: 'traj', side: 'west' },
  { node: 'pbc', port: 'traj', side: 'east' },
];
names = group.patch.map((e) => Editor._patchName(group, e));
check(names[0] === 'Run MD' && names[1] === 'Process trajectory',
      'THE POINT: two cables carrying the same kind of file from differently '
      + 'named blocks are given the block AND the socket, when the block on '
      + `its own already tells them apart (${JSON.stringify(names)})`);

// And a third cable that was never going to clash with either keeps its own
// short name, even though it comes out of the same block as the first.
group.patch = [
  { node: 'run', port: 'traj', side: 'west' },
  { node: 'run', port: 'tpr', side: 'west' },
  { node: 'pbc', port: 'traj', side: 'east' },
];
names = group.patch.map((e) => Editor._patchName(group, e));
check(names[1] === 'tpr',
      `a cable nothing else could be confused with was lengthened anyway (${JSON.stringify(names)})`);
check(names[0] === 'Run MD' && names[2] === 'Process trajectory',
      'THE POINT: the two cables that really do clash were lengthened past the '
      + 'block name, because each name was judged against every form the others '
      + `could have taken rather than the one each actually shows (${JSON.stringify(names)})`);
// A name you typed is left alone, and does not drag the others out longer.
group.patch = [
  { node: 'pbc', port: 'traj', side: 'west', label: 'before fitting' },
  { node: 'fit', port: 'traj', side: 'west' },
];
names = group.patch.map((e) => Editor._patchName(group, e));
check(names[0] === 'before fitting' && names[1] === 'trajectory',
      'naming one cable yourself made the other one longer for no reason '
      + `(${JSON.stringify(names)})`);
group.patch = [
  { node: 'pbc', port: 'traj', side: 'west' },
  { node: 'fit', port: 'traj', side: 'west' },
];
names = group.patch.map((e) => Editor._patchName(group, e));
check(new Set(names).size === 2,
      'THE POINT: two cables carrying the same kind of file end up with the '
      + `same name on the wall, so neither can be told from the other (${JSON.stringify(names)})`);
// Same block, same socket, on both walls: even then they must read apart.
group.patch = [
  { node: 'pbc', port: 'traj', side: 'west' },
  { node: 'pbc', port: 'traj', side: 'east' },
];
names = group.patch.map((e) => Editor._patchName(group, e));
check(new Set(names).size === 2,
      `one cable on each wall reads the same on both (${JSON.stringify(names)})`);
// And a name you typed yourself wins over the worked-out one.
group.patch = [{ node: 'pbc', port: 'traj', side: 'west', label: 'the fitted run' }];
check(Editor._patchName(group, group.patch[0]) === 'the fitted run',
      'renaming a cable does not stick');

/* A wall only grows a dot for a cable you put there. This is the step that
   keeps "I want to wire one output straight out of the chunk" working: no
   dot, no detour. */
console.log('a wall only grows dots for the cables you put on it');
group.patch = [{ node: 'run', port: 'traj', side: 'west' }];
const walls = { west: [], east: [] };
const namesOut = {};
const wallEl = (side) => ({
  innerHTML: '', appendChild: (kid) => walls[side].push(kid),
  classList: { toggle: (cls, on) => { namesOut[side] = on; } },
});
group._el = { querySelector: (sel) => (/west/.test(sel) ? wallEl('west') : wallEl('east')),
              classList: { toggle() {} } };
Editor._groupDots = new Map();
Editor.refreshGroupPorts(group);
const dotted = [...Editor._groupDots.keys()];
check(namesOut.west === true && namesOut.east === true,
      'the names are being written inside a box with nothing standing beside '
      + `it, straight across whatever block is nearest the wall (${JSON.stringify(namesOut)})`);
// A second box hard against the right-hand wall: there the name has to go
// back inside, because writing it over another chunk makes two unreadable.
Editor.groups = [group, { id: 'g2', title: 'Next', bounds: [group.bounds[0] + group.bounds[2],
                                                            0, 400, 400] }];
Editor.refreshGroupPorts(group);
check(namesOut.west === true && namesOut.east === false,
      'THE POINT: a box standing right against this one is written over '
      + `anyway (${JSON.stringify(namesOut)})`);
Editor.groups = [group];
Editor.refreshGroupPorts(group);
check(dotted.length === 1 && dotted[0] === 'g1|run|traj|out',
      'THE POINT: the wall grew dots for sockets nobody asked it to carry, so '
      + `wires that should run block to block are pulled through it (${JSON.stringify(dotted)})`);

/* And the drawing follows those dots exactly. */
console.log('only the cables you parked run through a wall');
group.bounds = [150, 0, 500, 400];
Editor.links = [
  { from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' },
  { from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' },
];
const wallDot = { dataset: { group: group.id, wall: 'west' } };
// Each stretch drawn, as: where it starts, where it ends, which way it sets
// off, which way it arrives, and the curve itself.
const drawn = [];
Editor.dom = { wires: { innerHTML: '', appendChild: () => {} } };
Editor.portCenter = (id) => ({ x: Editor.nodes.get(id).pos[0], y: 0 });
Editor.groupPortCenter = () => ({ x: 150, y: 40 });
const realBezier = Editor._bezier.bind(Editor);
Editor._bezier = (a, b, fromDir = 1, toDir = -1, wider = [0, 0]) => {
  const shape = realBezier(a, b, fromDir, toDir, wider);
  drawn.push([a.x, b.x, fromDir, toDir, shape]);
  return shape;
};
sandbox.document.createElementNS = () => stub();
Editor.drawWires = realDrawWires;          // the real one, back again
Editor._homeOf = new Map([['pbc', 'g1'], ['fit', 'g1']]);
const run = () => { drawn.length = 0; Editor.drawWires(); return drawn.slice(); };

Editor._groupDots = new Map();             // nothing parked
let legs = run();
check(legs.length === 2,
      'a wire with no cable on any wall was drawn as more than one stretch, so '
      + `it is being dragged through a wall nobody asked for (${JSON.stringify(legs)})`);

Editor._groupDots = new Map([['g1|run|traj|out', wallDot]]);
legs = run();
check(legs.length === 3,
      'the cable that was parked on the wall is not being taken through it '
      + `(${JSON.stringify(legs)})`);
check(legs.filter((l) => l[0] === 150 || l[1] === 150).length === 2,
      `the wall is not an end of two stretches (${JSON.stringify(legs)})`);
check(legs.some((l) => l[0] === 200 && l[1] === 400),
      'the wire between two blocks inside the box stopped being drawn straight '
      + `(${JSON.stringify(legs)})`);

console.log('a cable on a wall never doubles back the long way round');
// The block feeding the wall now sits inside the box at x 200, to the right
// of the left-hand wall at x 150, and what it feeds is outside to the left.
// The wire has to make a short U at the wall. Setting off right and swinging
// all the way back is the weird-looking thing this stops.
Editor.nodes.get('fit').pos[0] = -300;
Editor.links = [{ from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' }];
Editor._homeOf = new Map([['pbc', 'g1']]);
Editor._groupDots = new Map([['g1|pbc|traj|out', wallDot]]);
legs = run();
check(legs.length === 2, `expected two stretches (${JSON.stringify(legs)})`);
check(legs[0][3] === 1,
      'THE POINT: a cable arriving at a wall from a block inside the box is '
      + 'drawn as though it were arriving from outside, so it sails past the '
      + `wall and loops back (${JSON.stringify(legs[0])})`);
check(legs[1][2] === -1,
      'THE POINT: a cable leaving a wall towards something on the left sets '
      + `off rightwards first, making a long S (${JSON.stringify(legs[1])})`);

// ...and the curve really does use those two numbers rather than ignoring them.
const looped = realBezier({ x: 200, y: 0 }, { x: 150, y: 0 }, 1, 1);
const second = Number(looped.split('C')[1].trim().split(/\s+/)[2]);
check(second > 150,
      `the curve is ignoring which way it was told to arrive (${looped})`);

console.log('a cable from a right wall to a left wall runs round like a wire between blocks');
// Two boxes, one above the other: pbc in g1 hands its trajectory out through
// g1's right-hand wall at x 650, and fit in g2 underneath takes it in through
// g2's left-hand wall at x 150. The second wall is to the LEFT of the first,
// so leaning towards the other end would send the cable straight back across
// g1. It has to leave to the right and come in from the left instead, through
// the gap between the two boxes.
const outDotEast = { dataset: { group: 'g1', wall: 'east' } };
const inDotWest = { dataset: { group: 'g2', wall: 'west' } };
const whereWas = Editor.groupPortCenter;
Editor.groupPortCenter = (dot) => (dot === outDotEast ? { x: 650, y: 300 } : { x: 150, y: 700 });
Editor.nodes.get('fit').pos[0] = 300;
Editor._homeOf = new Map([['pbc', 'g1'], ['fit', 'g2']]);
Editor._groupDots = new Map([['g1|pbc|traj|out', outDotEast], ['g2|pbc|traj|out', inDotWest]]);
legs = run();
check(legs.length === 3, `expected three stretches (${JSON.stringify(legs)})`);
check(legs[1] && legs[1][0] === 650 && legs[1][1] === 150,
      `the middle stretch does not run wall to wall (${JSON.stringify(legs)})`);
check(legs[1] && legs[1][2] === 1 && legs[1][3] === -1,
      'THE POINT: a cable from a right-hand wall to a left-hand wall further left '
      + 'turns back across the box it came out of, instead of leaving to the right '
      + `and coming in from the left (${JSON.stringify(legs[1])})`);
check(legs[0][2] === 1 && legs[0][3] === -1 && legs[2][2] === 1 && legs[2][3] === -1,
      'the stretches inside the two boxes are no longer drawn like ordinary wires '
      + `(${JSON.stringify(legs)})`);
// A cable on the other wall of a box -- here the left wall, going out -- still
// leans, which is the short U checked just above.

console.log('cables side by side wrap round a corner without crossing');
// Two files go from g1's right-hand wall down to g2's left-hand wall, which
// is further left, so both cables turn back round g1's bottom corner and g2's
// top corner. Drawn with the same curve, each one dot lower than the other,
// they would cut across each other at both corners.
const dotsWere = Editor._groupDots;
const at = (group, wall, x, y) => ({ dataset: { group, wall }, spot: { x, y } });
Editor._groupDots = new Map([
  ['g1|pbc|traj|out', at('g1', 'east', 1650, 300)],
  ['g1|pbc|tpr|out', at('g1', 'east', 1650, 316)],
  ['g2|pbc|traj|out', at('g2', 'west', 150, 700)],
  ['g2|pbc|tpr|out', at('g2', 'west', 150, 716)],
]);
Editor.groupPortCenter = (dot) => dot.spot;
Editor.links = [
  { from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' },
  { from_node: 'pbc', from_port: 'tpr', to_node: 'fit', to_port: 'tpr' },
];
legs = run();
const between = legs.filter((l) => l[0] === 1650 && l[1] === 150).map((l) => l[4]);
// Points along a curve, read back from the path the editor drew.
const along = (d) => {
  const n = d.replace(/[MC]/g, ' ').trim().split(/\s+/).map(Number);
  const points = [];
  for (let i = 0; i <= 400; i += 1) {
    const t = i / 400;
    const u = 1 - t;
    const w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
    points.push([0, 1].map((k) => w[0] * n[k] + w[1] * n[2 + k] + w[2] * n[4 + k] + w[3] * n[6 + k]));
  }
  return points;
};
// Whether two curves cross anywhere.
const cross = (p, q) => {
  const side = (a, b, c) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]));
  for (let i = 0; i + 1 < p.length; i += 1) {
    for (let j = 0; j + 1 < q.length; j += 1) {
      if (side(p[i], p[i + 1], q[j]) * side(p[i], p[i + 1], q[j + 1]) < 0
          && side(q[j], q[j + 1], p[i]) * side(q[j], q[j + 1], p[i + 1]) < 0) return true;
    }
  }
  return false;
};
check(between.length === 2, `expected two cables from wall to wall (${JSON.stringify(legs)})`);
check(between.length === 2 && !cross(along(between[0]), along(between[1])),
      'THE POINT: two cables turning back round a box side by side cut across '
      + `each other where they turn (${JSON.stringify(between)})`);
// ...and drawn the old way, both with the same curve, they would have: the
// check above is not passing by luck.
const plain = [[300, 700], [316, 716]].map(([from, to]) => along(
  realBezier({ x: 1650, y: from }, { x: 150, y: to }, 1, -1)));
check(cross(plain[0], plain[1]),
      'the two cables would not have crossed even drawn the old way, so the check '
      + 'above proves nothing');

// Put the pieces back.
Editor._groupDots = dotsWere;
Editor.groupPortCenter = whereWas;
Editor.nodes.get('fit').pos[0] = -300;

/* A dot on a wall stands for the wires going through it. Cut the last of
   them and the dot goes too: leaving it behind was a dot standing for
   nothing. But only a dot a cut wire actually went through -- one you have
   just put on the wall and not wired onward yet must survive something
   unrelated being cut elsewhere. */
console.log('cutting the last wire through a dot takes the dot away');
const resetWalls = () => {
  Editor.nodes.get('run').pos[0] = -400;     // outside, to the left
  Editor.nodes.get('fit').pos[0] = 400;
  Editor._homeOf = new Map([['load', 'g1'], ['clean', 'g1'], ['pbc', 'g1'],
                            ['fit', 'g1'], ['plot', 'g1']]);
  group.patch = [{ node: 'run', port: 'traj', side: 'west' },
                 { node: 'run', port: 'tpr', side: 'west' }];
};
Editor.rebuildGroupPorts = () => {};
Editor.refreshPortStates = () => {};
Editor.drawWires = () => {};

resetWalls();
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' }];
let gone = Editor.disconnect('pbc', 'traj');
check(!group.patch.some((e) => e.port === 'traj'),
      'THE POINT: the last wire through a wall dot was cut and the dot stayed '
      + `on the wall, standing for nothing (${JSON.stringify(group.patch)})`);
check(gone.length === 1 && gone[0] === 'trajectory',
      `the cut does not say which cable came off with it (${JSON.stringify(gone)})`);
check(group.patch.some((e) => e.port === 'tpr'),
      'a cable nothing had been wired through yet was taken off the wall '
      + 'because a different wire was cut');

resetWalls();
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' },
                { from_node: 'run', from_port: 'traj', to_node: 'fit', to_port: 'traj' }];
Editor.disconnect('pbc', 'traj');
check(group.patch.some((e) => e.port === 'traj'),
      'a dot with another wire still going through it was taken off the wall');

// A wire between two blocks inside the box never went through the wall, so
// cutting it has nothing to do with the dot.
resetWalls();
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' },
                { from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' }];
Editor.disconnect('fit', 'traj');
check(group.patch.length === 2,
      'cutting a wire that never touched the wall took a cable off it');

// Picking a wire up by its end to move it: the dot has to wait.
resetWalls();
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' }];
Editor.disconnect('pbc', 'traj', { keepCables: true });
check(group.patch.length === 2,
      'picking a wire up by its end took its dot off the wall before you had '
      + 'even let go of it');

// Moving the wire to another block through the same wall keeps the dot;
// replacing it with a wire from somewhere else does not.
Editor.connect = realConnect;
resetWalls();
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' }];
Editor.connect('run', 'traj', 'pbc', 'traj');
check(group.patch.some((e) => e.port === 'traj'),
      'wiring the same thing into the same socket again took its dot away');
Editor.connect('load', 'structure', 'pbc', 'traj');
check(!group.patch.some((e) => e.port === 'traj'),
      'a wire replaced by one from somewhere else left its dot on the wall');

console.log('a cable waiting on the wall shows where it comes from');
// Put the real drawing back for this, with the stand-ins from above.
Editor.drawWires = realDrawWires;
const waitingDot = { isConnected: true,
  dataset: { group: 'g1', node: 'run', port: 'traj', type: 'traj', wall: 'west' } };
resetWalls();
group.patch = [{ node: 'run', port: 'traj', side: 'west' }];
Editor._groupDots = new Map([['g1|run|traj|out', waitingDot]]);
Editor.links = [];
legs = run();
check(legs.length === 1 && legs[0][0] === -400 && legs[0][1] === 150,
      'THE POINT: a cable on a wall with nothing wired onward has no line to '
      + `the block it comes from, so there is no telling where it came from (${JSON.stringify(legs)})`);
Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'pbc', to_port: 'traj' }];
legs = run();
check(legs.length === 2,
      'once a wire goes through the dot, the waiting line is drawn as well as '
      + `the wire, doubling the stretch up to the wall (${JSON.stringify(legs)})`);

/* One cable on two boxes: leaving the first by its right wall, arriving at the
   next by its left. Before anything inside the second box is wired to it, the
   line must still run wall to wall. Drawn from the block, it cut straight
   across to the second box as though the first wall were not there. */
console.log('a cable on two walls runs wall to wall before anything is wired');
const nextBox = { id: 'g2', title: 'Next', bounds: [900, 0, 300, 300],
                  patch: [{ node: 'pbc', port: 'traj', side: 'west' }] };
Editor.groups = [group, nextBox];
group.patch = [{ node: 'pbc', port: 'traj', side: 'east' }];
const leaving = { isConnected: true, at: { x: 650, y: 380 },
  dataset: { group: 'g1', node: 'pbc', port: 'traj', type: 'traj', wall: 'east' } };
const arriving = { isConnected: true, at: { x: 900, y: 40 },
  dataset: { group: 'g2', node: 'pbc', port: 'traj', type: 'traj', wall: 'west' } };
Editor._groupDots = new Map([['g1|pbc|traj|out', leaving], ['g2|pbc|traj|out', arriving]]);
const standInCenter = Editor.groupPortCenter;
Editor.groupPortCenter = (dot) => dot.at;
Editor._homeOf = new Map([['pbc', 'g1']]);
Editor.links = [];
legs = run().map((l) => `${l[0]}->${l[1]}`).sort();
check(JSON.stringify(legs) === JSON.stringify(['200->650', '650->900']),
      'THE POINT: the waiting line into the second box starts at the block '
      + 'rather than at the first box\'s wall, so the two walls do not look '
      + `connected (${JSON.stringify(legs)})`);
// And the same path the real wire takes once something inside is wired.
Editor._homeOf = new Map([['pbc', 'g1'], ['fit', 'g2']]);
Editor.links = [{ from_node: 'pbc', from_port: 'traj', to_node: 'fit', to_port: 'traj' }];
Editor.nodes.get('fit').pos[0] = 1000;
const wired = run().map((l) => `${l[0]}->${l[1]}`);
check(JSON.stringify(wired.slice(0, 2)) === JSON.stringify(['200->650', '650->900']),
      'the wire, once connected, runs a different way from the waiting line it '
      + `replaces (${JSON.stringify(wired)})`);
Editor.nodes.get('fit').pos[0] = 400;
Editor.groups = [group];
Editor.groupPortCenter = standInCenter;
Editor.drawWires = () => {};

/* The shortcut: double-click an output and it goes on the right-hand wall of
   its box, the way out of a chunk. Double-click it again and it comes off. */
console.log('double-clicking an output puts it on the right-hand wall');
const trajOut = { name: 'traj', label: 'trajectory', type: 'traj' };
Editor._homeOf = new Map([['pbc', 'g1'], ['fit', 'g1']]);
Editor.groups = [group];
group.patch = [];
Editor.toggleOnRightWall(Editor.nodes.get('pbc'), trajOut);
check(group.patch.length === 1 && group.patch[0].node === 'pbc'
   && group.patch[0].port === 'traj' && group.patch[0].side === 'east',
      'THE POINT: double-clicking an output did not put it on the right-hand '
      + `wall of its box (${JSON.stringify(group.patch)})`);
Editor.toggleOnRightWall(Editor.nodes.get('pbc'), trajOut);
check(group.patch.length === 0,
      `double-clicking it again did not take it off (${JSON.stringify(group.patch)})`);
group.patch = [{ node: 'pbc', port: 'traj', side: 'west' }];
Editor.toggleOnRightWall(Editor.nodes.get('pbc'), trajOut);
check(group.patch.length === 1 && group.patch[0].side === 'east',
      'an output already on the left wall was not moved across to the right, '
      + `or was doubled (${JSON.stringify(group.patch)})`);
// A block standing in no box has no wall. Say so, and change nothing.
toasts = [];
group.patch = [];
Editor.toggleOnRightWall(Editor.nodes.get('run'), trajOut);
check(group.patch.length === 0 && toasts.some((m) => /not in a box/.test(m)),
      'double-clicking an output of a block in no box put it on some wall, or '
      + `said nothing (${JSON.stringify(toasts)})`);
// And it is the output's double-click that does it, while an input's still
// unplugs.
check(/if \(direction === 'in'\) this\.disconnect\(node\.id, port\.name\);\s*else this\.toggleOnRightWall\(node, port\);/
  .test(fs.readFileSync(path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8')),
      'double-clicking an output socket is not what calls it, or double-clicking '
      + 'an input no longer unplugs it');

/* Cables on a wall have to be remembered. They are the one thing about a wall
   that is stored rather than worked out, so if saving drops them the walls go
   blank the next time the workflow is opened -- and undo, which saves and
   reloads the whole graph, would wipe them on every step. */
console.log('cables on a wall survive being saved');
group.patch = [{ node: 'pbc', port: 'traj', side: 'east', label: 'fitted run' }];
let saved = JSON.parse(JSON.stringify(Editor.toJSON()));
check(saved.groups[0].patch && saved.groups[0].patch.length === 1
   && saved.groups[0].patch[0].label === 'fitted run',
      `saving a box forgot the cables on its walls (${JSON.stringify(saved.groups[0])})`);
// A copy, not the same objects: two boxes made from one chunk would otherwise
// share their cables, and renaming one would rename both.
const live = Editor.toJSON();
check(live.groups[0].patch[0] !== group.patch[0],
      'the saved copy points at the very same cables the box is using, so a '
      + 'second box made from it would share them');
group.patch = [];
saved = JSON.parse(JSON.stringify(Editor.toJSON()));
check(!('patch' in saved.groups[0]),
      'a box with nothing on its walls writes an empty list into the saved '
      + 'file, which every workflow saved before walls existed would not have');

/* The right wall fills from the bottom. Its top runs down past the top right
   of the blocks inside, which is where their outputs and output names are,
   so cables stacked there cover the busiest part of the box. This is only
   the stylesheet, so it is read from there. */
console.log('the right wall fills from the bottom, the left from the top');
const css = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'css', 'style.css'), 'utf8');
const ruleFor = (sel) => {
  const at = css.indexOf(`${sel} {`);
  return at < 0 ? '' : css.slice(at, css.indexOf('}', at));
};
check(/flex-direction:\s*column-reverse/.test(ruleFor('.group-wall.east')),
      'THE POINT: the right wall stacks its cables from the top again, across '
      + 'the outputs of the blocks inside');
check(!/column-reverse/.test(ruleFor('.group-wall.west')),
      'the left wall was turned upside down too, which moves its cables away '
      + 'from where you asked for them');

console.log('renaming a chunk leaves its title bar alone');
const page = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
check(!/querySelector\('\.group-title'\)\.textContent =/.test(page),
      'THE BUG THIS FIXED: renaming a group writes the new name straight into '
      + 'the title bar, which wipes out everything else standing in it');
check(/\.group-name'\)\.textContent = group\.title/.test(page),
      'the rename no longer writes the name anywhere');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nchunk inputs: a chunk says what it takes in and what it hands '
  + 'out, tells its needed ones from its optional ones, numbers repeated '
  + 'blocks, and keeps its title bar through a rename');
