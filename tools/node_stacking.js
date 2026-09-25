/* Does clicking a node bring it in front of the ones drawn over it?

   Nodes are drawn in the order they were added, so a node added later covers
   one added earlier. Clicking the covered one did not change that, which left
   it unreachable: you could see a corner of it and not get at its boxes. On a
   graph loaded from a file the order is whatever the file happened to hold,
   so it was not even predictable which node would be the buried one.

   What has to stay true:

     * clicking a node puts it in front of every other node
     * clicking another one puts THAT in front, so the order follows you
       rather than settling
     * a node already selected still comes forward when clicked -- the click
       changes no selection, and that was the case that did nothing at all
     * re-drawing a node, which happens whenever one of its boxes changes,
       does not drop it back underneath
     * dragging a rubber band over the canvas does not restack everything it
       touches on every mouse move

   Run:  node tools/node_stacking.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeElement() {
  const el = {
    tagName: 'DIV',
    children: [],
    style: {},
    _classes: new Set(),
    dataset: {},
    appendChild(child) { el.children.push(child); return child; },
    remove() {},
    setAttribute() {},
    addEventListener() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { x: 0, y: 0, width: 236, height: 120 }; },
    classList: {
      add(name) { el._classes.add(name); },
      remove(name) { el._classes.delete(name); },
      toggle(name, on) { if (on) el._classes.add(name); else el._classes.delete(name); },
      contains(name) { return el._classes.has(name); },
    },
  };
  return el;
}

const sandbox = {
  console,
  document: {
    getElementById: () => makeElement(),
    createElement: () => makeElement(),
    createTextNode: (text) => ({ textContent: text }),
    addEventListener() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    body: makeElement(),
  },
  window: { addEventListener() {} },
  navigator: {},
  requestAnimationFrame: (fn) => fn(),
  ResizeObserver: function ResizeObserver() {
    return { observe() {}, unobserve() {}, disconnect() {} };
  },
  setTimeout,
  clearTimeout,
  fetch: () => Promise.reject(new Error('no network in this test')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const file = path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js');
vm.runInContext(fs.readFileSync(file, 'utf8') + '\n;globalThis.__Editor = Editor;', sandbox);
const Editor = sandbox.__Editor;

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };

/* Two nodes, the second one drawn over the first, as the editor would have
   them after adding one and then the other. */
const nodes = new Map();
for (const id of ['first', 'second']) {
  nodes.set(id, { id, type: 'gmx.editconf', params: {}, pos: [0, 0], _el: makeElement() });
}
Editor.nodes = nodes;
Editor.selection = new Set();
Editor.selectedGroups = new Set();
Editor.groups = [];
Editor.onSelect = null;
Editor.paintGroupSelection = () => {};

const zOf = (id) => Number(nodes.get(id)._el.style.zIndex || 0);
const inFront = (a, b) => zOf(a) > zOf(b);

console.log('before anything is clicked');
check(zOf('first') === 0 && zOf('second') === 0,
      'nodes start with a stacking order of their own');

console.log('clicking the covered one');
Editor.select(['first']);
check(inFront('first', 'second'),
      'THE BUG: selecting the node underneath did not bring it forward');

console.log('clicking the other one');
Editor.select(['second']);
check(inFront('second', 'first'), 'the second node did not come forward');

console.log('clicking a node that is already selected');
// select() will not fire -- nothing about the selection changes -- so this is
// the case that used to do nothing whatever. The editor calls raise() from
// the node's own mousedown for exactly this reason.
const before = zOf('first');
Editor.raise('first');
check(zOf('first') > before && inFront('first', 'second'),
      'THE BUG: clicking an already-selected node left it underneath');

console.log('re-drawing a node');
const held = zOf('first');
check(nodes.get('first')._z === held,
      'the stacking order is not kept on the node, so re-drawing it -- which '
      + 'happens whenever one of its boxes changes -- would lose it');

console.log('a rubber band over both of them');
Editor.selection = new Set();
Editor.select(['first', 'second']);
const settled = [zOf('first'), zOf('second')];
Editor.select(['first', 'second']);          // the band moves, same two inside
check(zOf('first') === settled[0] && zOf('second') === settled[1],
      'selecting the same nodes again restacked them, so dragging a rubber '
      + 'band would count upwards on every mouse move');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nnode stacking: the node you touched last is the one in front');
