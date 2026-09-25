/* Do a node's boxes appear and disappear with the one that controls them?

   "Load structure" can take a file from this machine or a code from the
   Protein Data Bank. One box that quietly accepted either was not something
   anybody could see -- so there is a "Where from" box now, and the boxes under
   it change with it: a file chooser one way, a code box the other.

   What has to stay true:

     * a box with no condition is always shown
     * a box shows only while the box it names holds one of its values
     * a value that matches nothing the controlling box can hold means the box
       never appears, which is worse than showing it always -- so the
       conditions on the real node are checked against its real choices
     * changing the controlling box redraws the node, or the boxes it controls
       stay as they were

   Run:  node tools/param_when.js
   It loads the editor with a stand-in for the page, so it needs neither a
   browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeElement() {
  const el = {
    tagName: 'DIV', children: [], style: {}, dataset: {},
    _classes: new Set(),
    appendChild(child) { el.children.push(child); return child; },
    remove() {}, setAttribute() {}, addEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
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
    getElementById: () => makeElement(), createElement: () => makeElement(),
    createTextNode: (text) => ({ textContent: text }),
    addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    body: makeElement(),
  },
  window: { addEventListener() {} },
  navigator: {},
  requestAnimationFrame: (fn) => fn(),
  ResizeObserver: function ResizeObserver() {
    return { observe() {}, unobserve() {}, disconnect() {} };
  },
  setTimeout, clearTimeout,
  fetch: () => Promise.reject(new Error('no network in this test')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8')
  + '\n;globalThis.__Editor = Editor;', sandbox);
const Editor = sandbox.__Editor;

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };

const FROM_DISK = 'a file on this machine';
const FROM_PDB = 'the Protein Data Bank';
const node = { id: 'load', type: 'io.structure', params: { source: FROM_DISK } };

const shown = (when) => Editor.paramShown(node, { name: 'x', when });

console.log('a box with no condition');
check(shown('') && shown(undefined), 'a box with no condition was hidden');

console.log('a box that follows another');
check(shown(`source=${FROM_DISK}`), 'the file box is hidden while a file is what is wanted');
check(!shown(`source=${FROM_PDB}`), 'THE BUG: the code box is shown while a file is what is wanted');

node.params.source = FROM_PDB;
check(shown(`source=${FROM_PDB}`), 'THE BUG: the code box stays hidden after asking for a download');
check(!shown(`source=${FROM_DISK}`), 'the file box is still shown after asking for a download');

console.log('several values, and a value nothing holds');
check(Editor.paramShown({ params: { mode: 'raw' } }, { when: 'mode=preset|raw' }),
      'a box listing several values did not accept one of them');
check(!shown('source=somewhere else'),
      'a condition naming a value the box cannot hold showed the box anyway');

console.log('an unset box counts as empty');
check(Editor.paramShown({ params: {} }, { when: 'mode=' }),
      'a box that appears while another is empty did not appear');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nparameter boxes: they appear and disappear with the box that '
            + 'controls them');
