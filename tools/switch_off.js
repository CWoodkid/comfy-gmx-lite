/* Switching a block off, or a whole chunk, from the editor.

   The run itself is decided on the server (tools/smoke_test.py,
   check_switched_off). This is the editor's half: the switch, what it saves,
   the two shortcuts, and how a block that will not run is shown.

   What has to stay true:

     * one switch for any mix: anything still on and it all goes off, all off
       and it all comes back on
     * the flag is saved only when it is set, so no existing workflow changes,
       and it comes back when the workflow is opened again and after undo
     * switching a chunk off means every block you can see in it, including
       blocks in a box inside it
     * Ctrl + Alt + click (Cmd + Option on a Mac) is the mouse shortcut, and
       Ctrl alone or Alt alone is not
     * Ctrl+M does it from the keyboard
     * a block left out because something before it is switched off says so,
       and drops whatever the last check said about it
     * a switched-off block is drawn as one, and so is the box when every
       block in it is off

   Run:  node tools/switch_off.js
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
  const classes = new Set();
  return {
    style: { setProperty() {} },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
      contains: (c) => classes.has(c),
    },
    addEventListener() {}, appendChild() {}, setAttribute() {},
    querySelector: () => null, querySelectorAll: () => [],
    offsetWidth: 200, offsetHeight: 100, className: '',
  };
}

function loadEditor(platform) {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
  const toasts = [];
  const sandbox = {
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { addEventListener() {}, getElementById: () => null,
                createElement: () => stub(), createElementNS: () => stub() },
    window: { addEventListener() {} },
    navigator: { platform, userAgent: platform },
    console,
    UI: { el: () => stub(), toast: (m) => toasts.push(m), bytes: () => '', contextMenu() {} },
    API: {}, App: {}, Sessions: {}, Panels: {}, requestAnimationFrame: (fn) => fn(),
    setTimeout, clearTimeout, Math, JSON, Set, Map, Date,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source + '\n;globalThis.__Editor = Editor;', sandbox,
                  { filename: 'graph.js' });
  const Editor = sandbox.__Editor;
  Editor.defs = {
    'util.shell': { title: 'Shell', inputs: [], outputs: [], params: [] },
  };
  const make = (id, x) => [id, { id, type: 'util.shell', title: id.toUpperCase(),
                                 pos: [x, 0], params: {}, off: false, _el: stub() }];
  Editor.nodes = new Map([make('a', 0), make('b', 100), make('c', 200), make('d', 300)]);
  Editor.links = [];
  Editor.groups = [];
  Editor.selection = new Set();
  // The parts of the page these tests do not look at.
  let marks = [];
  Editor.mark = (label) => marks.push(label);
  Editor.changed = () => {};
  Editor.drawWires = () => {};
  return { Editor, toasts, marks: () => marks };
}

const { Editor, toasts, marks } = loadEditor('Linux x86_64');
const off = () => [...Editor.nodes.values()].filter((n) => n.off).map((n) => n.id).sort();

console.log('one switch, both ways');
Editor.toggleOff(['a']);
check(JSON.stringify(off()) === '["a"]', `switching one block off did not (${off()})`);
check(marks().some((m) => /switch off A/.test(m)),
      `switching off cannot be undone: nothing was marked for undo (${marks()})`);
// A mix: one already off, one on. Anything still on means "switch off".
Editor.toggleOff(['a', 'b']);
check(JSON.stringify(off()) === '["a","b"]',
      'THE POINT: a mix of on and off blocks came out as a mix -- the one that '
      + `was off got switched back on instead of the lot going off (${off()})`);
Editor.toggleOff(['a', 'b']);
check(off().length === 0, `with everything off, the switch did not bring it all back (${off()})`);
check(toasts.some((m) => /switched off/.test(m)) && toasts.some((m) => /back on/.test(m)),
      `nothing was said either way (${JSON.stringify(toasts)})`);
// Nothing chosen: say how to choose, and change nothing.
toasts.length = 0;
Editor.toggleOff([]);
check(toasts.length === 1 && off().length === 0,
      'pressing the switch with nothing selected did something, or said nothing');

console.log('saved only when set, and read back');
Editor.toggleOff(['c']);
let saved = JSON.parse(JSON.stringify(Editor.toJSON()));
const byId = (id) => saved.nodes.find((n) => n.id === id);
check(byId('c').off === true, 'a switched-off block is saved as if it were on');
check(!('off' in byId('a')),
      'a block that is on writes "off": false into the file, which changes every '
      + 'workflow saved before this existed');
// Opened again. fromJSON builds real blocks, which this stand-in cannot, so the
// one line that reads the flag is exercised directly on the saved copy.
const graphSource = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
check(/created\.off = !!node\.off;/.test(graphSource),
      'opening a workflow does not read the switch back, so a switched-off block '
      + 'comes back on -- and so does every undo, which reopens the graph');
// A tutorial or a chunk arrives through addChunk, not fromJSON. The ice
// tutorial ships its salt box switched off, and it came in switched on.
check(/addChunk\([\s\S]{0,900}if \(node\.off\) \{\s*made\.off = true;/.test(graphSource),
      'a tutorial or chunk that arrives with blocks switched off has them switched '
      + 'on, so Run runs the part it was meant to leave out');
Editor.toggleOff(['c']);

console.log('a chunk means everything you can see in it');
const outer = { id: 'g1', bounds: [0, 0, 1000, 500] };
const inner = { id: 'g2', bounds: [150, 50, 200, 200] };
Editor.groups = [outer, inner];
Editor.chunkMembers = (g) => (g === outer ? ['a', 'd'] : ['b']);
Editor.groupsInGroup = (g) => (g === outer ? [inner] : []);
const inside = Editor._everythingIn(outer).sort();
check(JSON.stringify(inside) === '["a","b","d"]',
      'switching a chunk off leaves out the blocks in a box inside it, which '
      + `you can plainly see are part of it (${JSON.stringify(inside)})`);

console.log('the mouse shortcut');
const click = (extra) => ({ button: 0, ctrlKey: false, altKey: false, metaKey: false, ...extra });
check(Editor.offChordHeld(click({ ctrlKey: true, altKey: true })),
      'Ctrl + Alt + click does not switch a block off');
check(!Editor.offChordHeld(click({ ctrlKey: true })),
      'Ctrl + click alone switches a block off, and it already means something else');
check(!Editor.offChordHeld(click({ altKey: true })), 'Alt + click alone switches a block off');
check(!Editor.offChordHeld(click({ ctrlKey: true, altKey: true, button: 2 })),
      'Ctrl + Alt + right-click switches a block off');
const mac = loadEditor('MacIntel').Editor;
check(mac.offChordHeld(click({ metaKey: true, altKey: true }))
      && !mac.offChordHeld(click({ ctrlKey: true, altKey: true })),
      'on a Mac the shortcut is not Cmd + Option, where Ctrl + click is how you ask for a menu');
check(/Ctrl \+ Alt \+ click/.test(Editor.offChordName())
      && /Cmd \+ Option \+ click/.test(mac.offChordName()),
      'the shortcut is not named the way it is pressed on each kind of machine');

console.log('the keyboard shortcut');
const appSource = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'app.js'), 'utf8');
check(/case 'm':[\s\S]{0,400}Editor\.toggleOff\(Editor\.selected\(\)\)/.test(appSource),
      'Ctrl+M does not switch the selection off');

console.log('what the last check said');
Editor.nodes.get('b').off = true;
for (const id of ['c', 'd']) {
  Editor.nodes.get(id).error = 'required input is not connected';
  Editor.nodes.get(id).notes = ['something old'];
}
Editor.markLeftOut({
  b: { because: '', message: "'B' is switched off" },
  c: { because: 'b', message: "'C' is left out: it depends on 'B', which is switched off" },
});
const c = Editor.nodes.get('c');
check(/depends on 'B'/.test(c.leftOut) && c.notes.length === 1 && /depends on 'B'/.test(c.notes[0]),
      `a block left out because of another does not say why (${JSON.stringify(c.notes)})`);
check(c.error === '',
      'a left-out block keeps the error from before it was left out, so it looks '
      + 'broken when it simply will not run');
check(Editor.nodes.get('b').leftOut === '',
      'the switched-off block itself is also marked as left out because of something');
check(Editor.nodes.get('d').leftOut === '' && Editor.nodes.get('d').error !== '',
      'a block the check did not leave out was cleared as well');

console.log('how it is drawn');
Editor.nodes.get('d').off = false;
Editor.applyNodeStatus(Editor.nodes.get('b'));
Editor.applyNodeStatus(c);
check(/\boff\b/.test(Editor.nodes.get('b')._el.className),
      'a switched-off block is drawn like any other');
check(/\bleft-out\b/.test(c._el.className) && !/\boff\b/.test(c._el.className),
      'a block left out because of another is not drawn as left out, or is drawn '
      + 'as switched off itself');
Editor.groups = [outer];
Editor.groupsInGroup = () => [];
Editor.chunkMembers = () => ['a', 'b'];
outer._el = stub();
outer._el.querySelector = () => null;
for (const n of Editor.nodes.values()) n.off = false;
Editor.refreshGroupPorts(outer);
check(!outer._el.classList.contains('all-off'), 'a box with blocks still on is drawn as off');
Editor.nodes.get('a').off = true;
Editor.nodes.get('b').off = true;
Editor.refreshGroupPorts(outer);
check(outer._el.classList.contains('all-off'),
      'a box whose every block is switched off does not show it on its title bar');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nswitch off: one switch both ways, saved only when set, whole chunks '
  + 'including boxes inside them, Ctrl + Alt + click and Ctrl+M, and the '
  + 'reason shown on blocks left out because of it');
