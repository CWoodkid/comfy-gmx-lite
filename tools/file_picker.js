/* Can you get back out of a folder in the file picker, and find things in it?

   Two reports, one dialog. "Load structure, choose file: there is no go back
   button on file explorer" -- there was a small "↑ .." row at the top of the
   listing and nothing else, no Up, no Back, easy to miss and easy to scroll
   away from. And "a search option would be great": the Files tab has one, the
   picker did not, so finding a file meant knowing where it was.

   What has to stay true:

     * there is an Up button, and it goes to the folder above
     * there is a Back button; it is dead until you have been somewhere, and
       then it retraces your steps. Back is not Up: walk in and out again and
       Up would take you somewhere you have never been
     * typing in the search box hides what does not match, at once
     * pressing Enter looks through the folders underneath as well, and says
       where each answer lives
     * choosing a file still hands its path back and closes the dialog

   Run:  node tools/file_picker.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeElement(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    children: [],
    _classes: new Set(),
    _listeners: {},
    _attrs: {},
    style: {},
    textContent: '',
    value: '',
    disabled: false,
    checked: false,
    files: [],
    get className() { return [...el._classes].join(' '); },
    set className(value) {
      el._classes = new Set(String(value).split(/\s+/).filter(Boolean));
    },
    get innerHTML() { return ''; },
    set innerHTML(value) { if (!value) el.children = []; },
    appendChild(child) { el.children.push(child); return child; },
    remove() {},
    setAttribute(name, value) { el._attrs[name] = value; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, fn) { (el._listeners[name] = el._listeners[name] || []).push(fn); },
    fire(name, event) {
      for (const fn of el._listeners[name] || []) fn(Object.assign({ target: el, preventDefault() {} }, event || {}));
    },
    click() { el.fire('click'); },
    getContext() { return { clearRect() {}, fillRect() {}, fillText() {}, strokeRect() {} }; },
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
    getElementById: () => makeElement('div'),
    createElement: (tag) => makeElement(tag),
    createTextNode: (text) => ({ textContent: text, _classes: new Set(), children: [] }),
    querySelector: () => null,
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

const read = (name) => fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', name), 'utf8');
vm.runInContext(read('api.js') + '\n;globalThis.__UI = UI; globalThis.__API = API;', sandbox);
vm.runInContext(read('files.js') + '\n;globalThis.__Pick = Pick;', sandbox);
vm.runInContext(read('panels.js') + '\n;globalThis.__Panels = Panels;', sandbox);
const UI = sandbox.__UI;
const API = sandbox.__API;
const Panels = sandbox.__Panels;

/* A small made-up filesystem, deep enough that getting back out matters. */
const TREE = {
  '/home/me': [
    { name: 'projects', dir: true }, { name: 'notes.txt', dir: false },
  ],
  '/home/me/projects': [
    { name: 'run1', dir: true }, { name: 'run2', dir: true },
  ],
  '/home/me/projects/run1': [
    { name: 'frame.gro', dir: false }, { name: 'topol.top', dir: false },
  ],
};

let asked = null;
API.files = (where) => {
  const at = where || '/home/me';
  if (!TREE[at]) return Promise.reject(new Error(`not a directory: ${at}`));
  const cut = at.lastIndexOf('/');
  return Promise.resolve({
    path: at,
    parent: cut > 0 ? at.slice(0, cut) : '/',
    entries: TREE[at].map((entry) => Object.assign({ size: 10, path: `${at}/${entry.name}` }, entry)),
  });
};
API.findFiles = (where, needle) => {
  asked = { where, needle };
  return Promise.resolve({
    path: where,
    entries: [{ name: 'frame.gro', path: '/home/me/projects/run1/frame.gro',
                dir: false, size: 10, where: 'run1' }],
    complete: true,
    searched: 3,
  });
};

let opened = null;
UI.modal = (title, body, buttons) => { opened = { title, body, buttons }; };
UI.subModal = UI.modal;
UI.modalOpen = () => false;
UI.closeModal = () => { opened = null; };
UI.toast = () => {};
UI.copy = () => {};

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };

const walk = (el, into = []) => {
  into.push(el);
  for (const child of el.children || []) walk(child, into);
  return into;
};
// Whole label, not a fragment: "Upload…" contains "Up", and matching loosely
// meant the missing Up button looked present.
const buttonNamed = (text) => walk(opened.body)
  .find((el) => el.tagName === 'BUTTON' && String(el.textContent).trim() === text);
const inputs = () => walk(opened.body).filter((el) => el.tagName === 'INPUT');
const rowTexts = () => walk(opened.body)
  .filter((el) => el._classes && el._classes.has('fb-row'))
  .map((row) => walk(row).map((el) => el.textContent).join(' ').trim());
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

async function main() {
  let picked = null;
  Panels._lastBrowsed = '';
  Panels.browseFile((p) => { picked = p; }, '/home/me/projects');
  await settle();

  console.log('the buttons that were missing');
  const up = buttonNamed('↑ Up');
  const back = buttonNamed('← Back');
  check(!!up, 'THE BUG: there is no Up button in the file picker');
  check(!!back, 'THE BUG: there is no Back button in the file picker');
  check(back && back.disabled === true,
        'Back is live before you have been anywhere, so it can only disappoint');
  if (!up || !back) {
    // Nothing below can be tried without them; say so once rather than
    // crashing halfway through the list.
    console.log(`\n${failures} problem(s)`);
    process.exit(1);
  }

  console.log('walking in and out');
  const intoRun1 = () => {
    const row = walk(opened.body).find((el) => el._classes && el._classes.has('fb-row')
      && walk(el).some((c) => c.textContent === '📁 run1'));
    row.fire('click');
  };
  intoRun1();
  await settle();
  check(rowTexts().some((t) => t.includes('frame.gro')),
        'walking into run1 did not show what is in it');
  check(back.disabled === false, 'Back is still dead after walking into a folder');

  up.fire('click');
  await settle();
  check(rowTexts().some((t) => t.includes('run2')),
        'THE BUG: Up did not go to the folder above');

  // Back is not Up: from projects, Up goes to /home/me, Back goes to run1.
  back.fire('click');
  await settle();
  check(rowTexts().some((t) => t.includes('topol.top')),
        'THE BUG: Back did not retrace a step -- it went somewhere else');

  console.log('finding things');
  up.fire('click');                       // back to projects
  await settle();
  const search = inputs().find((el) => el._classes.has('fb-search'));
  check(!!search, 'THE BUG: there is no search box in the file picker');
  search.value = 'run2';
  search.fire('input');
  await settle();
  const shown = rowTexts().filter((t) => t.includes('run'));
  check(shown.some((t) => t.includes('run2')) && !shown.some((t) => t.includes('run1')),
        `typing did not hide what does not match -- rows are ${JSON.stringify(rowTexts())}`);

  search.value = 'frame';
  search.fire('input');
  search.fire('keydown', { key: 'Enter' });
  await settle();
  check(asked && asked.needle === 'frame' && asked.where === '/home/me/projects',
        `Enter did not search under this folder: ${JSON.stringify(asked)}`);
  check(rowTexts().some((t) => t.includes('frame.gro')),
        'the search found nothing to show');
  check(rowTexts().some((t) => t.includes('run1')),
        'the search results do not say which folder each answer is in');
  // The count and the way back out are drawn above the rows. They used to be
  // appended before the listing, which empties the panel first -- so they were
  // wiped before anybody saw them.
  const said = walk(opened.body)
    .filter((el) => el._classes && el._classes.has('fb-note'))
    .map((el) => walk(el).map((c) => c.textContent).join(' '))
    .join(' | ');
  check(/1 match in 3 folders/.test(said),
        `THE BUG: the search does not say what it found: "${said}"`);
  check(/back to the folder/.test(said),
        'THE BUG: there is no way back out of a search result');

  console.log('choosing one');
  const hit = walk(opened.body).find((el) => el._classes && el._classes.has('fb-row')
    && walk(el).some((c) => String(c.textContent).includes('frame.gro')));
  hit.fire('click');
  check(picked === '/home/me/projects/run1/frame.gro',
        `choosing a file handed back "${picked}"`);
  check(opened === null, 'choosing a file left the dialog open');

  if (failures) {
    console.log(`\n${failures} problem(s)`);
    process.exit(1);
  }
  console.log('\nfile picker: Up, Back, and a search that looks underneath');
}

main();
