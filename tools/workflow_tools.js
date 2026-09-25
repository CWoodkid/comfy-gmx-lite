/* Does the "this workflow needs programs you have not got" dialog offer the
   right versions?

   A workflow built somewhere else names the programs it needs and, if it was
   saved by a recent Comfy-gmx, the version of each it was built against. Two
   versions of a coarse-graining tool do not produce the same model, so which
   one you install is a real choice, not a detail.

   What has to stay true:

     * the version the workflow used is offered, and is what is chosen unless
       you say otherwise
     * the newest is offered as well -- somebody starting their own work does
       not want a two-year-old build
     * a workflow that does not say which version it used offers only the
       newest, and says why
     * pressing Install passes the chosen version on, rather than quietly
       installing whatever is newest
     * each program says which nodes need it, so it is clear what is lost by
       not installing it

   Run:  node tools/workflow_tools.js
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
    style: {},
    textContent: '',
    value: '',
    disabled: false,
    get className() { return [...el._classes].join(' '); },
    set className(value) {
      el._classes = new Set(String(value).split(/\s+/).filter(Boolean));
    },
    get innerHTML() { return ''; },
    set innerHTML(value) { if (!value) el.children = []; },
    appendChild(child) { el.children.push(child); return child; },
    remove() {},
    setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, fn) { (el._listeners[name] = el._listeners[name] || []).push(fn); },
    fire(name) { for (const fn of el._listeners[name] || []) fn({ target: el, preventDefault() {} }); },
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
vm.runInContext(read('api.js') + '\n;globalThis.__UI = UI;', sandbox);
vm.runInContext(read('files.js'), sandbox);
vm.runInContext(read('panels.js') + '\n;globalThis.__Panels = Panels;', sandbox);
const UI = sandbox.__UI;
const Panels = sandbox.__Panels;

let opened = null;
UI.modal = (title, body, buttons) => { opened = { title, body, buttons }; };
UI.subModal = UI.modal;
UI.modalOpen = () => false;
UI.closeModal = () => { opened = null; };
UI.toast = () => {};

// What the install dialog was asked for, instead of opening it.
let asked = null;
Panels.install = (tool, options) => { asked = { tool: tool.id, options }; };

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };

const walk = (el, into = []) => {
  into.push(el);
  for (const child of el.children || []) walk(child, into);
  return into;
};
const textOf = (el) => walk(el).map((e) => e.textContent).filter(Boolean).join(' ');
const selects = () => walk(opened.body).filter((el) => el.tagName === 'SELECT');
const buttonNamed = (text) => walk(opened.body)
  .find((el) => el.tagName === 'BUTTON' && String(el.textContent).trim() === text);

const MISSING = [
  {
    id: 'martinize2', name: 'martinize2 (vermouth)',
    description: 'Turns an atomistic protein into a Martini model.',
    optional: true, present: false, where: '', version: '',
    wanted: '0.12.0', installable: true, licence_key: false, versions_from: 'pip',
    nodes: ['cg', 'cg2'], titles: ['Martinize (martinize2)'],
  },
  {
    id: 'insane', name: 'insane',
    description: 'Classic Martini bilayer builder.',
    optional: true, present: false, where: '', version: '',
    wanted: '', installable: true, licence_key: false, versions_from: 'pip',
    nodes: ['mem'], titles: ['Build membrane (insane)'],
  },
];

console.log('what the dialog offers');
Panels.workflowTools(MISSING);
check(!!opened, 'the dialog did not open');
const said = textOf(opened.body);
check(/Martinize \(martinize2\)/.test(said),
      'the dialog does not say which nodes need each program');

const [first, second] = selects();
check(!!first && !!second, `expected a version box per program, found ${selects().length}`);
const options = (box) => box.children.map((o) => String(o.textContent));
check(options(first).some((text) => text.includes('0.12.0')),
      `THE BUG: the version the workflow used is not offered: ${JSON.stringify(options(first))}`);
check(options(first).some((text) => /newest/i.test(text)),
      'the newest version is not offered');
check(first.value === '0.12.0',
      `THE BUG: the workflow's own version is not what is chosen: "${first.value}"`);

console.log('a workflow that does not say');
check(options(second).length === 1 && /newest/i.test(options(second)[0]),
      `a program with no recorded version should offer only the newest: ${JSON.stringify(options(second))}`);
check(/does not say which version/.test(said),
      'nothing explains why only the newest is on offer for that one');

console.log('pressing Install');
buttonNamed('Install…').click();
check(asked && asked.tool === 'martinize2',
      `Install opened the wrong thing: ${JSON.stringify(asked)}`);
check(asked && asked.options && asked.options.version === '0.12.0',
      `THE BUG: Install did not pass the chosen version on: ${JSON.stringify(asked && asked.options)}`);

console.log('choosing the newest instead');
first.value = '';
buttonNamed('Install…').click();
check(asked && asked.options.version === '',
      `choosing the newest still asked for ${JSON.stringify(asked && asked.options)}`);

console.log('one that cannot be installed from here');
Panels.workflowTools([Object.assign({}, MISSING[0], {
  id: 'gmx', name: 'GROMACS', installable: false, wanted: '2024.4',
  titles: ['Preprocess (grompp)'],
})]);
const stubborn = textOf(opened.body);
check(/not one this can install/.test(stubborn),
      'a program that cannot be installed here does not say so');
check(/2024\.4/.test(stubborn),
      'it does not say which version the workflow was built with');
check(!!buttonNamed('Open Environments'),
      'there is nowhere to go for a program this cannot install');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nworkflow tools: the version it was built with, or the newest, and '
            + 'the choice is passed on');
