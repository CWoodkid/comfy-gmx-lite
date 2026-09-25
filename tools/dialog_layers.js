/* Does a dialog opened from inside a dialog leave the first one alone?

   This is a test for one reported bug and the class it belongs to. There is one
   dialog in the page, and opening a second in it used to empty the first: a
   form half filled in with a lipid's files was thrown away the moment somebody
   pressed the browse button next to one of them. Nothing in the form is saved
   anywhere until it is applied, so there was nothing to restore either.

   There is a second layer now. What has to stay true:

     * opening the second dialog leaves the first one's contents untouched
     * closing the second one leaves the first one on screen
     * Escape and a click beside it close the top one only
     * with no dialog open, a dialog still opens on the first layer as before
     * the back-arrow stack of the first layer is not disturbed by any of it

   Run:  node tools/dialog_layers.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

/* Just enough of a page: elements that remember their id, their classes, their
   text and their children, and nothing else. */
function makeElement(id) {
  const el = {
    id: id || '',
    tagName: 'DIV',
    children: [],
    _classes: new Set(),
    _listeners: {},
    textContent: '',
    value: '',
    style: {},
    get innerHTML() { return this.children.length ? '<children>' : ''; },
    set innerHTML(value) { if (!value) this.children = []; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild(child) { this.children = this.children.filter((c) => c !== child); },
    remove() {},
    setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, fn) { (this._listeners[name] = this._listeners[name] || []).push(fn); },
    fire(name, event) { for (const fn of this._listeners[name] || []) fn(event || { target: el }); },
    classList: {
      add(name) { el._classes.add(name); },
      remove(name) { el._classes.delete(name); },
      toggle(name, on) { if (on) el._classes.add(name); else el._classes.delete(name); },
      contains(name) { return el._classes.has(name); },
    },
  };
  return el;
}

const page = new Map();
for (const id of ['modal-backdrop', 'modal', 'modal-title', 'modal-body', 'modal-footer',
                  'modal-close', 'modal-back', 'submodal-backdrop', 'submodal',
                  'submodal-title', 'submodal-body', 'submodal-footer', 'submodal-close',
                  'toast-stack', 'context-menu', 'status-text']) {
  page.set(id, makeElement(id));
}
page.get('modal-backdrop').classList.add('hidden');
page.get('submodal-backdrop').classList.add('hidden');

const sandbox = {
  console,
  document: {
    getElementById: (id) => page.get(id) || makeElement(id),
    createElement: () => makeElement(''),
    createTextNode: (text) => ({ textContent: text }),
    addEventListener() {},
    body: makeElement('body'),
  },
  window: {},
  navigator: {},
  fetch: () => Promise.reject(new Error('no network in this test')),
  setTimeout, clearTimeout,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'api.js'), 'utf8')
  + '\n;globalThis.__UI = UI;', sandbox);
const UI = sandbox.__UI;

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };
const hidden = (id) => page.get(id).classList.contains('hidden');
const bodyOf = (id) => page.get(id).children.length;

console.log('one dialog on its own');
UI.modal('A form', makeElement('form-contents'), [{ label: 'Close' }]);
check(!hidden('modal-backdrop'), 'the first dialog did not open');
check(bodyOf('modal-body') === 1, 'the first dialog has no contents');
check(!UI._subOpen, 'the second layer opened when nothing asked it to');
check(UI.modalOpen(), 'modalOpen() says nothing is open while a dialog is open');

console.log('a second dialog on top of it');
const marker = page.get('modal-body').children[0];
UI.subModal('Choose a file', makeElement('browser'), [{ label: 'Cancel' }]);
check(!hidden('submodal-backdrop'), 'the second dialog did not open');
check(UI._subOpen, 'the second dialog does not know it is open');
check(!hidden('modal-backdrop'), 'the first dialog was hidden by the second');
check(page.get('modal-body').children[0] === marker,
      'THE BUG: the first dialog\'s contents were replaced by the second');
check(bodyOf('modal-body') === 1, 'the first dialog lost its contents');

console.log('closing the top one');
UI.closeModal();                       // what Escape calls
check(hidden('submodal-backdrop'), 'Escape did not close the second dialog');
check(!hidden('modal-backdrop'), 'Escape closed the first dialog as well as the second');
check(page.get('modal-body').children[0] === marker, 'the first dialog lost its contents');
UI.closeModal();
check(hidden('modal-backdrop'), 'the second Escape did not close the first dialog');

console.log('clicking beside a dialog');
UI.modal('A form', makeElement('form-contents'), []);
UI.subModal('Choose a file', makeElement('browser'), []);
// A click on the first dialog's backdrop while the second is open is aimed at
// neither, and must not take the form away underneath the browser.
page.get('modal-backdrop').fire('mousedown', { target: page.get('modal-backdrop') });
check(!hidden('modal-backdrop'), 'clicking beside closed the dialog under an open one');
page.get('submodal-backdrop').fire('mousedown', { target: page.get('submodal-backdrop') });
check(hidden('submodal-backdrop'), 'clicking beside the second dialog did not close it');
check(!hidden('modal-backdrop'), 'closing the second one closed the first');
UI.closeModal();

console.log('the back-arrow stack is not disturbed');
const first = () => UI.modal('First', makeElement('one'), [], { reopen: first });
const second = () => UI.modal('Second', makeElement('two'), [], { reopen: second });
first();
second();
check(UI._modalStack.length === 1, 'the stack did not remember the first page');
UI.subModal('On top', makeElement('sub'), []);
check(UI._modalStack.length === 1, 'the second layer pushed itself onto the first layer\'s stack');
UI.closeSubModal();
UI.modalBack();
check(page.get('modal-title').textContent === 'First',
      `going back landed on ${page.get('modal-title').textContent}`);
UI.closeModal();
check(UI._modalStack.length === 0, 'closing did not clear the stack');

console.log('a dialog\'s buttons close their own layer');
let ran = 0;
UI.modal('A form', makeElement('form'), []);
UI.subModal('Choose a file', makeElement('browser'),
            [{ label: 'Use this path', action: () => { ran += 1; } }]);
page.get('submodal-footer').children[0].fire('click');
check(ran === 1, 'the second dialog\'s button did not run its action');
check(hidden('submodal-backdrop'), 'the second dialog\'s button did not close it');
check(!hidden('modal-backdrop'), 'the second dialog\'s button closed the first dialog');
UI.closeModal();

console.log('a new first-layer dialog is never buried under the second');
UI.modal('A form', makeElement('form'), []);
UI.subModal('Choose a file', makeElement('browser'), []);
UI.modal('Somewhere else entirely', makeElement('other'), []);
check(hidden('submodal-backdrop'),
      'opening a new dialog left the old second one on top of it');
check(!UI._subOpen, 'the second layer still thinks it is open');
check(page.get('modal-title').textContent === 'Somewhere else entirely',
      'the new dialog did not open');
UI.closeModal();

console.log('what is underneath cannot be tabbed into or clicked');
UI.modal('A form', makeElement('form'), []);
UI.subModal('Choose a file', makeElement('browser'), []);
check(page.get('modal').inert === true,
      'the dialog underneath is still reachable by the Tab key');
UI.closeSubModal();
check(page.get('modal').inert === false,
      'the dialog underneath is still switched off after the second one closed');
UI.closeModal();

console.log('a late answer knows whether its dialog is still there');
UI.modal('Slow dialog', makeElement('slow'), [{ label: 'Build it', primary: true }]);
const slow = UI._generation;
check(UI.stillShowing(slow), 'a dialog does not recognise its own number');
UI.modal('Another dialog', makeElement('other'), [{ label: 'Set it up', primary: true }]);
check(!UI.stillShowing(slow),
      'THE RACE: a dialog that has been replaced still thinks it is on screen, '
      + 'so a late answer would relabel the new dialog\'s button');
UI.subModal('On top', makeElement('sub'), []);
check(!UI.stillShowing(slow), 'the number did not move when the second layer opened');
UI.closeSubModal();
UI.closeModal();
check(!UI.stillShowing(slow), 'the number did not move when the dialog closed');

if (failures) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
