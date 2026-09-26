/* Do the run-parameters boxes show the value the run will use?

   A "Run parameters (.mdp)" block has a box for each of the options people
   change most. Left empty, a box means "whatever the preset says" -- or, in
   raw mode, whatever the text says. What has to stay true:

     * an empty box shows that value from the moment the block appears: the
       preset's, the raw text's, or GROMACS's own default when neither sets
       it, and never the words "preset default"; a box nobody gives a value
       says that it is not set
     * changing the preset, the mode or the raw text redraws the block, or
       its boxes go on showing the old values
     * in raw mode, typing in a box changes that line of the text, keeping
       its comment, instead of being silently ignored
     * outside raw mode, editing a box still turns the preset into an edited
       copy of it, as before

   Run:  node tools/mdp_boxes.js
   It loads the editor with a stand-in for the page, so it needs neither a
   browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeElement() {
  const el = {
    tagName: 'DIV', children: [], style: {}, dataset: {},
    appendChild(child) { el.children.push(child); return child; },
    remove() {}, setAttribute() {}, addEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { x: 0, y: 0, width: 236, height: 120 }; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
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
const same = (got, want, what) =>
  check(got === want, `${what}\n        got:  ${JSON.stringify(got)}\n        want: ${JSON.stringify(want)}`);

// What the server sends (/api/mdp/presets), cut down to what is tested here.
Editor.mdp = {
  presets: {
    md_atomistic: { nsteps: 50000000, dt: 0.002, 'ref-t': '310 310', pcoupl: 'C-rescale' },
  },
  widgets: { nsteps: 'nsteps', dt: 'dt', ref_t: 'ref-t', tau_t: 'tau-t',
             pcoupl: 'pcoupl', nstlog: 'nstlog', gen_seed: 'gen-seed' },
  gromacs_defaults: { nsteps: '0', dt: '0.001', pcoupl: 'no', nstlog: '1000',
                      'gen-seed': '-1' },
  default_name: 'run.mdp',
};
const box = (name) => ({ name, placeholder: 'preset default' });
const shows = (node, name, bare) => Editor._placeholder(node, box(name), bare);

console.log('a preset: its values, and GROMACS\'s where it has none');
const preset = { id: 'm', type: 'util.mdp', params: { mode: 'preset', preset: 'md_atomistic' } };
same(shows(preset, 'dt'), '0.002  (from md_atomistic)', 'dt does not show the preset\'s value');
same(shows(preset, 'nstlog'), '1000  (GROMACS default)',
     'an option the preset does not set does not show GROMACS\'s own value');
same(shows(preset, 'pcoupl', true), 'C-rescale', 'a dropdown\'s empty entry lost the preset\'s value');
same(shows(preset, 'tau_t'), 'not set by md_atomistic',
     'an option nobody gives a value should say so, not "preset default"');
check(!Editor._mdpShown(preset, box('tau_t')), 'a box with no value is drawn as if it had one');
same(Editor._placeholder(preset, { name: 'define', placeholder: 'e.g. -DPOSRES' }), 'e.g. -DPOSRES',
     'define lost its example: leaving it out is the usual case');
check(Editor._mdpShown(preset, box('dt')), 'a known value is not marked to be drawn readable');
check(!Editor._mdpShown({ type: 'gmx.grompp', params: {} }, box('dt')),
      'a box on another block was treated as a run parameter');

console.log('raw mode: the values in the text');
const heat = [
  '; Heat the cube',
  'nsteps                   = 100000     ; 200 ps',
  'dt       = 0.002',
  'ref_t    = 200',
  '',
].join('\n');
const raw = { id: 'r', type: 'util.mdp',
              params: { mode: 'raw', preset: 'md_atomistic', raw: heat } };
same(shows(raw, 'nsteps'), '100000  (from the raw text)', 'raw mode does not show the text\'s nsteps');
same(shows(raw, 'ref_t'), '200  (from the raw text)',
     'an option written with an underscore was not read');
same(shows(raw, 'nstlog'), '1000  (GROMACS default)',
     'an option the text leaves out does not show GROMACS\'s own value');
same(shows(raw, 'tau_t'), 'not in the raw text',
     'an option the text leaves out, with no GROMACS default, should say so');
same(shows({ type: 'util.mdp', params: { mode: 'file' } }, 'dt'), 'as in the file',
     'file mode should not claim the preset\'s values: the file decides');

console.log('raw mode: typing in a box changes that line of the text');
raw.params.nsteps = '150000';
check(Editor.applyFollows(raw, 'nsteps', '150000'), 'typing in raw mode did nothing');
check(raw.params.raw.includes('nsteps                   = 150000     ; 200 ps'),
      `the nsteps line was not changed in place, comment kept:\n${raw.params.raw}`);
same(raw.params.nsteps, '', 'the box should empty again and show the text\'s value');
same(shows(raw, 'nsteps'), '150000  (from the raw text)', 'the box does not show the new value');
raw.params.ref_t = '250';
Editor.applyFollows(raw, 'ref_t', '250');
check(raw.params.raw.includes('ref_t    = 250'),
      `the line written with an underscore was not changed:\n${raw.params.raw}`);
raw.params.nstlog = '500';
Editor.applyFollows(raw, 'nstlog', '500');
check(raw.params.raw.endsWith('nstlog = 500\n'),
      `an option the text did not set was not added at the end:\n${raw.params.raw}`);
same(raw.params.mode, 'raw', 'typing in raw mode changed the mode');
same(raw.params.raw.split('\n')[0], '; Heat the cube', 'the text\'s own comments were lost');

console.log('a preset: editing a box still makes an edited copy');
preset.params.nsteps = '5000';
check(Editor.applyFollows(preset, 'nsteps', '5000'), 'editing a preset box did nothing');
same(preset.params.mode, 'manual', 'editing a preset box did not switch it to manual');
same(preset.params.filename, 'md_atomistic_edited.mdp', 'the edited copy was not renamed');

console.log('changing the preset, the mode or the raw text redraws the boxes');
// Just enough of the page's element maker to build one box and change it.
const made = [];
sandbox.UI = {
  el(tag, attrs = {}, children = []) {
    const el = makeElement();
    el.tagName = String(tag).toUpperCase();
    el.handlers = {};
    el.addEventListener = (type, fn) => { el.handlers[type] = fn; };
    el.insertBefore = () => {};
    Object.assign(el, attrs);
    for (const child of [].concat(children || [])) if (child) el.appendChild(child);
    made.push(el);
    return el;
  },
};
Editor.defs = { 'util.mdp': { params: [], inputs: [], outputs: [{ name: 'mdp', type: 'mdp' }] } };
Editor.mark = () => {};
Editor.changed = () => {};
const redrawn = [];
Editor._refreshNodeElement = (node) => { redrawn.push(node.id); };
for (const [name, type, choices, value] of [
  ['preset', 'choice', ['md_atomistic', 'em_atomistic'], 'em_atomistic'],
  ['mode', 'choice', ['preset', 'manual', 'file', 'raw'], 'raw'],
  ['raw', 'text', null, 'nsteps = 10\n'],
]) {
  const node = { id: name, type: 'util.mdp', title: 'Run parameters',
                 params: { mode: 'preset', preset: 'md_atomistic' } };
  made.length = 0;
  Editor._buildWidget(node, { name, type, label: name, choices });
  const box = made.find((el) => el.handlers.change);
  box.value = value;
  box.handlers.change();
  check(redrawn.includes(name),
        `changing ${name} did not redraw the block, so its boxes go on showing the old values`);
}

if (failures) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nrun-parameter boxes: every value on show from the start, and raw mode '
  + 'edits the text');
