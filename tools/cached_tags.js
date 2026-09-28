/* The dashed "cached" tag on a block, and when it is brought up to date.

   A block that the next Run would take from the store of earlier results,
   rather than work out again, carries a small dashed "cached" tag in its
   title bar. The page learns which blocks those are by asking the server
   the same question the Check button asks, and it asks after every edit.

   A run changes the answer: every block it finished is stored, and would be
   reused next time. A run also takes the tags off, because every status it
   sends redraws the block from scratch. So when a run ends the page has to
   ask again. It did not: the tags came back only after the next edit, such
   as dragging a box, and the line beside Run went on describing the graph
   as it was before the run.

   What has to stay true:

     * when a run ends, finished or failed, the tags come back by themselves
       on the blocks the server says it would reuse, and the line beside Run
       says the same
     * a run that ends in another tab does this too, because the graph on
       screen may share blocks with it -- unless the tab on screen is itself
       running, since its own end will ask, and tags on a run in progress
       would mix a forecast into what the borders say has happened

   Run:  node tools/cached_tags.js
   It loads the two browser files with a stand-in for the page and for the
   server, so it needs neither a browser nor a running server. */
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

/* A stand-in for a page element. Like a real one, setting its whole class
   attribute replaces every class it had: that is how a status arriving
   takes the tag off, so a stand-in without it would hide the fault. */
function stub() {
  const classes = new Set();
  const el = {
    style: { setProperty() {} },
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => {
        if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c);
        return classes.has(c);
      },
      contains: (c) => classes.has(c),
    },
    addEventListener() {}, appendChild() {}, setAttribute() {},
    querySelector: () => null, querySelectorAll: () => [],
    offsetWidth: 200, offsetHeight: 100, textContent: '', innerHTML: '', title: '',
  };
  Object.defineProperty(el, 'className', {
    get: () => [...classes].join(' '),
    set: (text) => {
      classes.clear();
      for (const c of String(text).split(/\s+/)) if (c) classes.add(c);
    },
  });
  return el;
}

// The page's own elements, one per id, so what the code writes can be read back.
const page = new Map();
const byId = (id) => {
  if (!page.has(id)) page.set(id, stub());
  return page.get(id);
};

// The server: which blocks it holds a stored result for, and how often it was asked.
let stored = new Set();
let asked = 0;
const API = {
  async plan() {
    asked += 1;
    const nodes = ['a', 'b', 'c'].map((id) => ({ node: id, type: 'util.mdp', cached: stored.has(id) }));
    const cached = nodes.filter((n) => n.cached).length;
    return {
      order: ['a', 'b', 'c'], plans: {}, problems: [], left_out: {},
      forecast: { nodes, total: 3, cached, will_run: 3 - cached, seconds: 0, unknown: 0 },
    };
  },
};

const Sessions = {
  activeId: 'here',
  list: [],
  active() { return this.list.find((s) => s.id === this.activeId); },
  noteStatus(session, status) { session.run.status = status; },
  noteNode(session, id, status, error) { session.run.statuses[id] = { status, error }; },
};

const sandbox = {
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  document: {
    addEventListener() {}, getElementById: byId,
    createElement: () => stub(), createElementNS: () => stub(),
    querySelector: () => null, querySelectorAll: () => [],
  },
  window: { addEventListener() {} },
  navigator: { platform: 'Linux x86_64', userAgent: 'Linux' },
  console,
  UI: { el: () => stub(), toast() {}, status() {}, bytes: () => '', duration: (s) => `${s} s`,
        contextMenu() {} },
  API, Sessions,
  Terminal: { status() {}, note() {} },
  Panels: {}, NodePreview: {},
  requestAnimationFrame: (fn) => fn(),
  setTimeout, clearTimeout, Math, JSON, Set, Map, Date, Promise,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const file of ['graph.js', 'app.js']) {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', file), 'utf8');
  vm.runInContext(source, sandbox, { filename: file });
}
const Editor = vm.runInContext('Editor', sandbox);
const App = vm.runInContext('App', sandbox);

// Three blocks on the page, nothing wired.
Editor.defs = { 'util.mdp': { title: 'Run parameters', inputs: [], outputs: [], params: [] } };
const make = (id, x) => [id, { id, type: 'util.mdp', title: id.toUpperCase(), pos: [x, 0],
                               params: {}, status: 'idle', _el: stub() }];
Editor.nodes = new Map([make('a', 0), make('b', 300), make('c', 600)]);
Editor.links = [];
Editor.groups = [];
// Wires, box sizes and the Files tab are drawn elsewhere; this is about the tags.
Editor.drawWires = () => {};
Editor.settleGroups = () => {};
App.refreshFiles = () => {};

const tagged = () => [...Editor.nodes.keys()]
  .filter((id) => Editor.nodes.get(id)._el.classList.contains('will-cache')).join(',');
const line = () => byId('forecast-line').textContent;
// Longer than the half second the page waits after a change before it asks.
const settle = () => new Promise((done) => setTimeout(done, 900));

/* What a run does to the blocks on screen, through the editor's own code:
   every block starts again as idle, then each one it reaches is redrawn as
   running and then as done or failed. Whatever finished is now stored. */
function run(session, outcome) {
  Sessions.list = Sessions.list.filter((s) => s.id !== session.id).concat([session]);
  session.run = { id: session.id, status: 'running', statuses: {} };
  const onScreen = session.id === Sessions.activeId;
  if (onScreen) {
    App.setRunning(true);
    Editor.resetStatuses();
  }
  for (const [id, status] of Object.entries(outcome)) {
    session.run.statuses[id] = { status };
    if (status === 'done') stored.add(id);
    if (!onScreen) continue;
    Editor.setStatus(id, 'running');
    Editor.setStatus(id, status);
  }
}

(async () => {
  const here = { id: 'here', name: 'tab 1' };
  const there = { id: 'there', name: 'tab 2' };

  console.log('before any run');
  await App.check(false);
  check(tagged() === '', `blocks are tagged before anything was stored: ${tagged()}`);

  console.log('a run that finishes');
  run(here, { a: 'done', b: 'done', c: 'done' });
  let before = asked;
  App.onRunStatus(here, 'done');
  await settle();
  check(asked > before, 'the page did not ask the server again when the run ended');
  check(tagged() === 'a,b,c',
        `after the run the tagged blocks are [${tagged()}], not [a,b,c]: the tags `
        + 'only come back after the next edit');
  check(/nothing to do/.test(line()),
        `the line beside Run still describes the graph before the run: "${line()}"`);

  console.log('a run that fails');
  stored = new Set(['a']);
  run(here, { b: 'done', c: 'error' });
  App.onRunStatus(here, 'error');
  await settle();
  check(tagged() === 'a,b',
        `after a failed run the tagged blocks are [${tagged()}], not [a,b]`);
  check(/1 of 3 will run/.test(line()), `the line beside Run says "${line()}"`);

  console.log('a run in another tab');
  stored = new Set(['a']);
  App.setRunning(false);
  await App.check(false);
  run(there, { b: 'done', c: 'done' });
  App.onRunStatus(there, 'done');
  await settle();
  check(tagged() === 'a,b,c',
        `a run that ended in another tab left the tags on screen at [${tagged()}], `
        + 'though the server would now reuse all three');

  console.log('a run in another tab, while this one runs');
  stored = new Set();
  await App.check(false);
  run(here, { a: 'done' });
  run(there, { b: 'done' });
  before = asked;
  App.onRunStatus(there, 'done');
  await settle();
  check(asked === before && tagged() === '',
        'the tab on screen was still running, yet the other tab\'s end tagged its '
        + `blocks [${tagged()}] in the middle of its run`);
  App.onRunStatus(here, 'done');
  await settle();
  check(tagged() === 'a,b', `when this tab's run ended too the tags are [${tagged()}], not [a,b]`);

  if (failures) {
    console.log(`\n${failures} problem(s)`);
    process.exit(1);
  }
  console.log('\ncached tags: back by themselves when a run ends, finished or failed, and '
    + 'the line beside Run with them; a run ending in another tab counts too, but '
    + 'not while the tab on screen is still running');
})();
