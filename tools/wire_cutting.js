/* Can you hit a wire, and can you cut one in a single gesture?

   A wire is drawn two pixels wide. Asking somebody to land a right-click
   inside two pixels is asking for three tries, and it is worse on a trackpad
   and worse again when the canvas is zoomed out and the wire is a hair. So
   every wire is now drawn twice: once visibly, and once in a wide invisible
   stroke that catches the pointer. And holding Ctrl while right-clicking cuts
   the wire outright rather than offering a one-item menu to click next.

   What has to stay true:

     * every wire is a pair -- an invisible band and the line you see
     * the band is wide, and it stays the same width under the pointer
       whatever the zoom is, because it is divided by the zoom
     * the dashed wire that follows the cursor while you drag one stays
       untouchable, or letting go would find that wire instead of the socket
     * a plain right-click still offers the menu, and the menu says which key
       does the same thing in one go
     * Ctrl and right-click cuts it there and then, with no menu
     * on a Mac it is Cmd, because there Ctrl and click is how you ask for a
       menu in the first place, and cutting a wire instead would be a nasty
       surprise
     * whichever way it goes, the cut is one Ctrl+Z away from coming back

   Run:  node tools/wire_cutting.js
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

/* The smallest stand-in for an element that graph.js will accept. */
function makeElement(tag) {
  return {
    tagName: tag,
    attrs: {},
    style: { setProperty(name, value) { this[name] = value; } },
    children: [],
    listeners: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute(name, value) { this.attrs[name] = String(value); },
    getAttribute(name) { return this.attrs[name]; },
    appendChild(child) { this.children.push(child); return child; },
    remove() {},
    addEventListener(kind, fn) { (this.listeners[kind] = this.listeners[kind] || []).push(fn); },
    querySelectorAll: () => [],
    set innerHTML(_) { this.children = []; },
    get innerHTML() { return ''; },
  };
}

function loadEditor(platform) {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
  const made = [];
  const doc = {
    addEventListener() {},
    getElementById: () => null,
    createElement: () => makeElement('div'),
    createElementNS: (_ns, tag) => { const el = makeElement(tag); made.push(el); return el; },
  };
  const sandbox = {
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: doc,
    window: { addEventListener() {} },
    navigator: { platform, userAgent: platform },
    console,
    UI: { el: () => makeElement('div'), toast() {}, bytes: () => '',
          contextMenu() {} },
    API: {}, App: {}, Sessions: {}, requestAnimationFrame: (fn) => fn(),
    setTimeout, clearTimeout, Math, JSON, Set, Map, Date,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source + '\n;globalThis.__Editor = Editor;', sandbox,
                  { filename: 'graph.js' });
  return { Editor: sandbox.__Editor, sandbox, made };
}

/* Two blocks and one wire, with the page parts graph.js would otherwise go
   looking for replaced by fixed answers. */
function twoBlocksOneWire(Editor) {
  const svg = makeElement('svg');
  const world = makeElement('div');
  Editor.dom = { wires: svg, world, canvas: makeElement('div'),
                 zoom: makeElement('span'), nodes: makeElement('div') };
  Editor.nodes = new Map([
    ['run', { id: 'run', type: 'gmx.mdrun', title: 'Run MD (mdrun)', params: {} }],
    ['fix', { id: 'fix', type: 'gmx.trjconv', title: 'Process trajectory (trjconv)', params: {} }],
  ]);
  Editor.defs = {
    'gmx.mdrun': { outputs: [{ name: 'traj', type: 'traj' }], inputs: [] },
    'gmx.trjconv': { outputs: [], inputs: [{ name: 'traj', type: 'traj' }] },
  };
  Editor.links = [{ from_node: 'run', from_port: 'traj', to_node: 'fix', to_port: 'traj' }];
  Editor.portCenter = (id) => (id === 'run' ? { x: 0, y: 0 } : { x: 200, y: 40 });
  Editor.refreshPortStates = () => {};
  Editor.changed = () => {};
  Editor.mark = () => {};
  return svg;
}

console.log('how a wire is drawn');
let { Editor, sandbox } = loadEditor('Linux x86_64');
let svg = twoBlocksOneWire(Editor);
Editor.drawWires();
const group = svg.children[0];
check(group && group.tagName === 'g' && group.getAttribute('class') === 'wire-line',
      'a wire is not drawn as a group, so there is nowhere to put the band');
const parts = (group ? group.children : []).map((c) => c.getAttribute('class'));
check(parts[0] === 'wire-grab',
      'THE POINT OF THIS: there is no invisible band to catch the pointer, so '
      + `a wire is still a two pixel target (found ${JSON.stringify(parts)})`);
check(parts[1] === 'wire',
      'the visible wire is not drawn on top of the band');
check(group.children.length === 2
      && group.children[0].getAttribute('d') === group.children[1].getAttribute('d'),
      'the band does not follow the same curve as the wire, so it catches the '
      + 'pointer somewhere the wire is not');

console.log('the band keeps its width on screen at any zoom');
for (const scale of [0.25, 1, 2]) {
  Editor.view = { x: 0, y: 0, scale };
  Editor.applyView();
  const set = svg.style['--wire-grab'];
  check(set === `${14 / scale}px`,
        `at ${Math.round(scale * 100)}% zoom the band is set to ${set}, which is `
        + 'not the width that keeps it the same size under the pointer');
}

console.log('the dashed wire you are dragging stays untouchable');
const css = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'css', 'style.css'), 'utf8');
check(/\.wire-line > \.wire \{[^}]*pointer-events: stroke/.test(css),
      'the visible wire only takes the pointer when it is one of a pair; if '
      + 'the rule were on .wire alone the dragged wire would take it too and '
      + 'letting go would find the wire in your hand, not the socket under it');
check(/\.wire-grab \{[^}]*stroke: transparent/.test(css),
      'the band is not transparent, so it is drawn over the graph');
check(/\.wire-line:hover > \.wire \{[^}]*stroke-width/.test(css),
      'the wire does not thicken when the pointer is in its band, so where two '
      + 'wires run close together you cannot see which one you are about to cut');

console.log('right-clicking a wire');
let menus = [];
let cut = [];
sandbox.UI.contextMenu = (x, y, items) => menus.push(items);
Editor.disconnect = (node, port) => cut.push(`${node}.${port}`);
const fire = (extra) => {
  const handler = svg.children[0].listeners.contextmenu[0];
  handler(Object.assign({ preventDefault() {}, stopPropagation() {}, clientX: 5, clientY: 5 }, extra));
};
fire({});
check(menus.length === 1 && cut.length === 0,
      'a plain right-click no longer offers the menu');
check(menus[0][0].label === 'Remove link',
      'the menu no longer says Remove link');
check(menus[0][0].hint === 'Ctrl + right-click',
      'the menu does not say which key does the same thing in one go, so the '
      + `shortcut can only be found by reading the help (${menus[0][0].hint})`);

fire({ ctrlKey: true });
check(cut.length === 1 && cut[0] === 'fix.traj',
      'THE SHORTCUT: Ctrl and right-click did not cut the wire');
check(menus.length === 1,
      'Ctrl and right-click cut the wire AND opened the menu, so the menu is '
      + 'left over a wire that has gone');

console.log('on a Mac it is Cmd, not Ctrl');
({ Editor, sandbox } = loadEditor('MacIntel'));
svg = twoBlocksOneWire(Editor);
Editor.drawWires();
menus = []; cut = [];
sandbox.UI.contextMenu = (x, y, items) => menus.push(items);
Editor.disconnect = (node, port) => cut.push(`${node}.${port}`);
const fireMac = (extra) => {
  const handler = svg.children[0].listeners.contextmenu[0];
  handler(Object.assign({ preventDefault() {}, stopPropagation() {}, clientX: 5, clientY: 5 }, extra));
};
check(Editor.cutKeyName() === 'Cmd', 'a Mac is still told to hold Ctrl');
fireMac({ ctrlKey: true });
check(cut.length === 0 && menus.length === 1,
      'on a Mac, holding Ctrl and clicking -- which is how you ask for a menu '
      + 'there -- cut the wire instead of offering one');
fireMac({ metaKey: true });
check(cut.length === 1, 'on a Mac, Cmd and right-click does not cut the wire');

/* While you drag a wire, every socket it could land on is marked, and every
   one it could not is marked the other way. That stopped working on
   2026-08-26 and nobody noticed, because the fault threw inside an event
   handler: the drag still worked, so the only sign was that nothing lit up.
   The block the wire comes from has to be handed to the marking, because what
   a socket carries can depend on what is typed into its block. */
console.log('starting to draw a wire says which sockets fit');
({ Editor } = loadEditor('Linux x86_64'));
twoBlocksOneWire(Editor);
const dots = [
  { dataset: { node: 'fix', port: 'traj', dir: 'in', type: 'traj' }, marks: {} },
  { dataset: { node: 'fix', port: 'tpr', dir: 'in', type: 'tpr' }, marks: {} },
  { dataset: { node: 'fix', port: 'anything', dir: 'in', type: 'file' }, marks: {} },
  { dataset: { node: 'run', port: 'traj', dir: 'out', type: 'traj' }, marks: {} },
];
for (const dot of dots) {
  dot.classList = { toggle(name, on) { dot.marks[name] = !!on; },
                    add() {}, remove() {}, contains: () => false };
}
Editor.dom.world = { querySelectorAll: () => dots };
let blewUp = null;
try {
  Editor._highlightCompatible(Editor.nodes.get('run'),
    { name: 'traj', type: 'traj' }, 'out');
} catch (err) { blewUp = err.message; }
check(blewUp === null,
      `marking the sockets threw: ${blewUp}. It throws before the first mouse `
      + 'move is handled, so nothing lights up while you drag a wire');
check(dots[0].marks.compatible === true,
      'a trajectory socket is not marked as fitting a trajectory');
check(dots[1].marks.incompatible === true,
      'a tpr socket is not marked as not fitting a trajectory');
check(dots[2].marks.compatible === true,
      'a socket that takes any file is not marked as fitting');
check(dots[3].marks.compatible === undefined && dots[3].marks.incompatible === undefined,
      'sockets on the wrong side of a block are being marked too');

console.log('the cut can be taken back');
({ Editor } = loadEditor('Linux x86_64'));
svg = twoBlocksOneWire(Editor);
let marked = [];
Editor.mark = (what) => marked.push(what);
Editor.disconnect('fix', 'traj');
check(marked.length === 1,
      'cutting a wire is not written into the undo list, so Ctrl+Z cannot put '
      + 'it back');
check(Editor.links.length === 0, 'the wire was not actually removed');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nwire cutting: a wire is a 14 px target at every zoom, a plain '
  + 'right-click still offers the menu, Ctrl and right-click cuts it outright '
  + '-- Cmd on a Mac -- and dragging a wire marks the sockets it fits');
