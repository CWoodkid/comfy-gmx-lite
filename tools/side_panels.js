/* Putting the side panels away, and bringing them back (sides.js).

   The panel on the left (Nodes, Chunks, Tutorials) and the one on the right
   (Log, Problems, Command, Files, Viewer, Plot) can each be hidden, the way
   the Terminal drawer under the canvas can, so the graph gets the whole
   width.

   What has to stay true:

     * both panels are out on a first visit
     * the small button on a panel hides it, and a tab appears on that edge
       of the canvas, named after the tab that was showing in the panel;
       clicking that tab brings the panel back
     * the graph stays where it is on screen: the view moves by as much as
       the canvas's left edge did, the other way
     * Ctrl+[ and Ctrl+] do the same from the keyboard, Cmd on a Mac, but not
       while something is being typed in a box; Ctrl+` opens and closes the
       Terminal drawer (it sat where it was never reached)
     * the right panel comes back by itself for something asked for in it
       (the problems Check found, Show command, a file or a picture), but not
       merely because a node was clicked
     * a reload puts the panels as they were, without moving the graph

   Run:  node tools/side_panels.js
   It loads sides.js and app.js with a stand-in for the page, so it needs
   neither a browser nor a running server. */
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

/* A stand-in for a page element: classes, text, and click handlers that can
   be set off, which is all the side panels use. */
function element(text = '') {
  const classes = new Set();
  const listeners = {};
  return {
    textContent: text, innerHTML: '', title: '', style: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => {
        if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c);
        return classes.has(c);
      },
      contains: (c) => classes.has(c),
    },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    click() { for (const fn of listeners.click || []) fn({ preventDefault() {}, stopPropagation() {} }); },
    appendChild(child) { return child; },
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
  };
}

/* The page. The canvas's left edge is where the layout puts it: 250 pixels
   in while the left panel is out, at the window's edge once it is away. */
let page;
let activeTab;
function newPage() {
  page = new Map();
  activeTab = { left: 'Nodes', right: 'Log' };
  const canvas = element();
  canvas.getBoundingClientRect = () => {
    const layout = byId('layout').classList;
    const left = layout.contains('left-hidden') ? 0 : 250;
    const right = layout.contains('right-hidden') ? 0 : 380;
    return { left, top: 72, width: 1280 - left - right, height: 600 };
  };
  page.set('canvas', canvas);
  // The handles start hidden, as in index.html.
  for (const id of ['palette-handle', 'inspector-handle']) {
    const handle = element(id === 'palette-handle' ? 'Nodes' : 'Log');
    handle.classList.add('hidden');
    page.set(id, handle);
  }
}
function byId(id) {
  if (!page.has(id)) page.set(id, element());
  return page.get(id);
}
/* The tab showing in each panel. The Problems tab carries its count after
   its name, as the real one does. */
function tabIn(selector) {
  const side = selector.startsWith('#palette-tabs') ? 'left'
    : selector.startsWith('#inspector-tabs') ? 'right' : '';
  if (!side) return null;
  const name = activeTab[side];
  const badge = name === 'Problems' ? '3' : '';
  return { firstChild: { textContent: name }, textContent: name + badge };
}

const stored = new Map();
let terminalToggles = 0;
const drawn = { viewer: 0, plot: 0 };
let viewMoves = 0;

const Editor = {
  view: { x: 100, y: 40, scale: 0.5 },
  applyView() { viewMoves += 1; },
  nodes: new Map([['a', { id: 'a', title: 'Ice crystal', type: 'build.ice' }]]),
  toJSON: () => ({ nodes: [], links: [] }),
};

const sandbox = {
  localStorage: {
    getItem: (key) => (stored.has(key) ? stored.get(key) : null),
    setItem: (key, value) => stored.set(key, String(value)),
    removeItem: (key) => stored.delete(key),
  },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: {
    addEventListener() {}, getElementById: (id) => byId(id),
    querySelector: (selector) => tabIn(selector), querySelectorAll: () => [],
    createElement: () => element(), activeElement: { tagName: 'BODY' },
  },
  window: { addEventListener() {} },
  navigator: { platform: 'Linux x86_64', userAgent: 'Linux' },
  console,
  UI: { el: () => element(), toast() {}, status() {}, anyDialogOpen: () => false,
        closeModal() {} },
  API: { preview: () => Promise.resolve({ notes: [], command: 'gmx editconf' }) },
  Sessions: { active: () => null, list: [] },
  Terminal: { toggle() { terminalToggles += 1; } },
  Viewer: { draw() { drawn.viewer += 1; } },
  Plot: { draw() { drawn.plot += 1; } },
  Editor,
  setTimeout, clearTimeout, Math, JSON, Set, Map, Date, Promise,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const file of ['sides.js', 'app.js']) {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', file), 'utf8');
  vm.runInContext(source, sandbox, { filename: file });
}
const SidePanels = vm.runInContext('SidePanels', sandbox);
const App = vm.runInContext('App', sandbox);

const hidden = (side) => byId('layout').classList.contains(`${side}-hidden`);
const handleShown = (side) => !byId(side === 'left' ? 'palette-handle' : 'inspector-handle')
  .classList.contains('hidden');
const handleText = (side) => byId(side === 'left' ? 'palette-handle' : 'inspector-handle').textContent;
const savedState = () => JSON.parse(stored.get('comfygmx.sides') || 'null');
let prevented = 0;
const key = (name, extra = {}) => App.onKey({
  key: name, ctrlKey: true, metaKey: false, shiftKey: false, altKey: false,
  preventDefault() { prevented += 1; }, ...extra,
});

(async () => {
  newPage();

  console.log('the first visit');
  SidePanels.init();
  check(!hidden('left') && !hidden('right'),
        'a first visit starts with a panel put away');
  check(!handleShown('left') && !handleShown('right'),
        'a first visit shows a handle for a panel that is out');
  check(Editor.view.x === 100 && viewMoves === 0, 'starting up moved the graph');

  console.log('the left panel put away with its button');
  activeTab.left = 'Tutorials';
  byId('palette-hide').click();
  check(hidden('left'), 'the button beside the search box did not hide the left panel');
  check(handleShown('left') && handleText('left') === 'Tutorials',
        `the handle on the left edge is ${handleShown('left') ? '' : 'not '}showing and `
        + `says "${handleText('left')}", not "Tutorials", the tab that was open`);
  check(Editor.view.x === 350,
        `the graph jumped: the canvas's edge moved 250 pixels left and the view by `
        + `${Editor.view.x - 100}, not 250 to the right`);
  check(savedState() && savedState().left === false && savedState().right === true,
        `what is remembered is ${stored.get('comfygmx.sides')}`);

  console.log('and brought back with its handle');
  byId('palette-handle').click();
  check(!hidden('left') && !handleShown('left'), 'the handle did not bring the left panel back');
  check(Editor.view.x === 100, `the graph did not go back to where it was (view at ${Editor.view.x})`);

  console.log('the right panel');
  activeTab.right = 'Problems';
  byId('inspector-hide').click();
  check(hidden('right') && handleShown('right'), 'the button at the end of the tabs did not hide the right panel');
  check(handleText('right') === 'Problems',
        `the handle says "${handleText('right')}": the count on the Problems tab belongs off it`);
  check(Editor.view.x === 100, 'hiding the right panel moved the graph, though the canvas\'s left edge stayed');
  byId('inspector-handle').click();
  check(!hidden('right') && drawn.viewer === 1 && drawn.plot === 1,
        'bringing the right panel back did not draw its structure and plot again '
        + `(viewer ${drawn.viewer}, plot ${drawn.plot})`);

  console.log('the keys');
  key('[');
  check(hidden('left'), 'Ctrl+[ did not hide the left panel');
  key('[');
  check(!hidden('left'), 'Ctrl+[ did not bring the left panel back');
  key(']', { ctrlKey: false, metaKey: true });
  check(hidden('right'), 'Cmd+] did not hide the right panel on a Mac');
  key(']');
  check(!hidden('right'), 'Ctrl+] did not bring the right panel back');
  key('`');
  check(terminalToggles === 1, 'Ctrl+` did not open the Terminal drawer from the canvas');
  check(prevented === 5, `${prevented} of 5 keys were kept from the browser`);
  sandbox.document.activeElement = { tagName: 'INPUT' };
  key('[');
  sandbox.document.activeElement = { tagName: 'BODY' };
  check(!hidden('left'), 'Ctrl+[ typed in a text box hid the left panel');

  console.log('asking for something in the right panel');
  SidePanels.toggle('right', false);
  App.showTab('problems');
  check(!hidden('right'), 'the problems Check found were put in a panel that stayed away');
  SidePanels.toggle('right', false);
  App.activateTab('viewer');
  check(!hidden('right'), 'a structure asked for was put in a panel that stayed away');
  SidePanels.toggle('right', false);
  await App.showCommand('a');
  check(!hidden('right'), 'Show command did not bring the right panel back');
  SidePanels.toggle('right', false);
  byId('tab-command').classList.remove('hidden');
  App.onSelect(['a']);
  await new Promise((done) => setTimeout(done, 20));
  check(hidden('right'), 'clicking a node brought back a right panel that was put away');

  console.log('a reload');
  SidePanels.toggle('left', false);
  const before = Editor.view.x;
  const movesBefore = viewMoves;
  newPage();
  SidePanels.open = { left: true, right: true };
  SidePanels.init();
  check(hidden('left') && hidden('right') && handleShown('left') && handleShown('right'),
        'after a reload the panels are not as they were left (both put away)');
  check(Editor.view.x === before && viewMoves === movesBefore,
        'a reload moved the graph, though its saved view already fits the canvas');

  if (failures) {
    console.log(`\n${failures} problem(s)`);
    process.exit(1);
  }
  console.log('\nside panels: each put away with its button or Ctrl+[ and Ctrl+], back with the '
    + 'tab on its edge, the graph staying put; the right one comes back for what is asked '
    + 'of it but not for a click on a node; remembered through a reload; Ctrl+` reaches '
    + 'the Terminal drawer');
})();
