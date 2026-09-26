/* Do the forms read back exactly what they write?

   A form that loses a setting is worse than no form at all: the setting was
   there, somebody opened a dialog to change something else, and it went away
   quietly. So the rule is that opening a form on the text already in a box and
   pressing "Put this in the box" without touching anything has to give back
   that same text.

   Run:  node tools/forms_roundtrip.js
   It loads the browser file with stand-ins for the browser, so nothing here
   needs a browser or a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'forms.js'), 'utf8');

// Enough of a browser for the file to load and the forms to draw themselves
// into nothing. Every element is the same do-nothing object; what is under
// test is the text that comes back out.
function element() {
  const el = {
    style: {}, dataset: {}, children: [], value: '', textContent: '', innerHTML: '',
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(child) { el.children.push(child); return child; },
    append() {}, prepend() {}, remove() {}, replaceWith() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {}, setAttribute() {},
    getAttribute() { return null; }, querySelector() { return element(); },
    querySelectorAll() { return []; }, focus() {}, select() {}, click() {},
  };
  return el;
}
const sandbox = {
  console,
  document: { createElement: element, createTextNode: element,
              getElementById: element, querySelector: element, body: element() },
  window: {},
  UI: { el: element, toast() {}, modal() {}, prose: () => [] },
  // A stand-in server for the forms that ask it something before they draw:
  // this system has three groups.
  API: {
    graphGroups: async () => ({ groups: [
      { name: 'System', atoms: 2000 }, { name: 'Protein', atoms: 1960 },
      { name: 'Ion', atoms: 40 }] }),
  },
  Editor: { nodes: new Map(), toJSON: () => ({ nodes: [], links: [] }) },
  App: {}, Panels: {},
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source + '\n;globalThis.__test = { Forms };', sandbox);
const { Forms } = sandbox.__test;

let failures = 0;
function check(ok, what) {
  if (ok) return;
  failures += 1;
  console.log(`  FAIL  ${what}`);
}

/* One sample per form, written the way the box would hold it. */
const SAMPLES = {
  'gmx.groups': 'Protein\nSystem\n',
  'files.list': 'topol.top\nposre.itp',
  'gmx.ndx': 'a CA\nname 3 Calphas\nq\n',
  'gmx.terms': 'Potential\nTemperature\n',
  'gmx.select': 'name OW',
  'text.rules': 'replace: DPPC => DSPC',
  'text.globs': '*.itp',
  'gmx.pick_groups': 'Ion, Protein',
};

const words = (text) => String(text || '').split(/\s+/).filter(Boolean).join(' ');

/* Open one form on a text and close it again untouched: what it gives back.
   A form that asks the server first gets the stand-in above. */
async function roundTrip(name, sample) {
  const def = Forms.fields.get(name);
  const made = await def.build({ node: { id: 'n', params: {} },
                                 param: { name: 'x', label: name, help: '' },
                                 value: sample, reopen() {} });
  const result = made.read();
  return typeof result === 'string' ? result : result.text;
}

async function main() {
  console.log('each form, opened and closed without a change');
  for (const [name, sample] of Object.entries(SAMPLES)) {
    const def = Forms.fields.get(name);
    check(Boolean(def), `the ${name} form is not registered`);
    if (!def) continue;
    let text;
    try {
      text = await roundTrip(name, sample);
    } catch (err) {
      check(false, `${name}: the form could not be drawn: ${err.message}`);
      continue;
    }
    check(words(text) === words(sample),
          `${name}: reading it back changed it\n        in:  ${JSON.stringify(sample)}\n`
          + `        out: ${JSON.stringify(text)}`);
  }

  console.log('the groups form keeps what it cannot find, with or without the server');
  const kept = await roundTrip('gmx.pick_groups', 'Protein, Mystery');
  check(kept === 'Protein, Mystery',
        `a group this system has not got was dropped: ${JSON.stringify(kept)}`);
  sandbox.API.graphGroups = async () => { throw new Error('heat has not been run yet'); };
  const offline = await roundTrip('gmx.pick_groups', 'Oxygens, System');
  check(offline === 'Oxygens, System',
        `with no run file to read, the box changed: ${JSON.stringify(offline)}`);

  console.log('the forms that exist');
  const registered = [...Forms.fields.keys()].sort();
  console.log(`  ${registered.length} forms: ${registered.join(', ')}`);
  for (const name of registered) {
    check(name in SAMPLES, `${name} is registered but has no sample here to test it with`);
  }

  if (failures) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
  }
  console.log('\nall checks passed');
}

main().catch((err) => { console.log(`  FAIL  ${err.stack || err}`); process.exit(1); });
