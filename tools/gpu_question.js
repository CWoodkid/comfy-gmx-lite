/* The question at Run: "another simulation holds the graphics card" (app.js).

   When Settings says to ask, pressing Run first asks the server whether this
   run would start a simulation while every graphics card it may use is held
   by another one (api/resources/check). Only then does the page ask: share
   the card, or use the processor only. The answer goes along with the run.

   What has to stay true:

     * no question from the server: no dialog, and the run starts as before,
       with nothing said about the card
     * "Use the processor only" and "Share the graphics card" each start the
       run with that answer; ticking "remember" also saves it in Settings
     * Cancel, or the dialog closing any other way (its x, Escape, another
       dialog in its place), starts nothing
     * the server failing to answer is no reason to stop: the run starts, and
       Settings decides
     * the graph asked about is the graph that is run
     * a session that is already running starts nothing and asks nothing

   Run:  node tools/gpu_question.js
   It loads app.js with a stand-in for the page and for the server, so it
   needs neither a browser nor a running server. */
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

function element() {
  return {
    textContent: '', innerHTML: '', style: {}, checked: false, value: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, appendChild(child) { return child; },
    querySelector: () => null, querySelectorAll: () => [],
  };
}

/* The page's dialogs: one at a time, and every opening and closing moves a
   number on, as UI.modal and UI.closeModal do. */
const dialogs = [];
const boxes = [];
const UI = {
  _generation: 0,
  el(tag, attrs = {}) {
    const node = element();
    if (tag === 'input' && attrs.type === 'checkbox') boxes.push(node);
    return node;
  },
  toast() {},
  modal(title, body, buttons) {
    UI._generation += 1;
    dialogs.push({ title, buttons, open: true });
    return body;
  },
  closeModal() {
    UI._generation += 1;
    for (const d of dialogs) d.open = false;
  },
};
function press(label) {
  const dialog = dialogs[dialogs.length - 1];
  const button = dialog && dialog.buttons.find((b) => b.label === label);
  if (!button) { check(false, `no button "${label}" in the dialog`); return; }
  if (!button.action || button.action() !== false) UI.closeModal();
}

/* The server. */
let answer = { ask: false };
let checkFails = false;
const asked = [];
const started = [];
const saved = [];
const API = {
  resourcesCheck(graph, opts) {
    asked.push({ graph, opts });
    return checkFails ? Promise.reject(new Error('server gone')) : Promise.resolve(answer);
  },
  run(graph, opts) {
    started.push({ graph, opts });
    return Promise.resolve({ run: 'r1', order: [], workdir: '/tmp/r1', reused: [] });
  },
  saveSettings(patch) { saved.push(patch); return Promise.resolve({}); },
};

let session = { id: 's1', name: 'test', run: null };
const graphObject = { nodes: [{ id: 'md' }], links: [] };
const sandbox = {
  document: { getElementById: () => element(), addEventListener() {} },
  window: { addEventListener() {} },
  console, UI, API,
  Sessions: { active: () => session, activeId: 's1', beginRun() {} },
  Editor: { nodes: { size: 1 }, resetStatuses() {}, setStatus() {},
            toJSON: () => graphObject },
  setTimeout, clearTimeout, setInterval, clearInterval, Promise, Math, JSON, Set, Map,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'app.js'), 'utf8'),
  sandbox, { filename: 'app.js' });
const App = vm.runInContext('App', sandbox);
App.watch = () => {};
App.setRunning = () => {};

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
function reset() {
  dialogs.length = 0; boxes.length = 0;
  asked.length = 0; started.length = 0; saved.length = 0;
  checkFails = false; session = { id: 's1', name: 'test', run: null };
}

(async () => {
  const busy = { ask: true, message: 'graphics card 0 (Test card) is in use by another '
    + 'simulation (process 4242: gmx mdrun -deffnm prod)' };

  // Nothing to ask: no dialog, and the run says nothing about the card.
  reset(); answer = { ask: false };
  await App.run(['md'], ['md'], { isolate: false });
  check(dialogs.length === 0, 'a dialog opened although the server had no question');
  check(started.length === 1 && started[0].opts.gpu_busy === '',
        `the run did not start plainly: ${JSON.stringify(started.map((s) => s.opts.gpu_busy))}`);
  check(asked.length === 1 && asked[0].graph === started[0].graph,
        'the graph asked about is not the graph that was run');
  check(asked[0] && JSON.stringify(asked[0].opts) === JSON.stringify(
    { only: ['md'], force: ['md'], isolate: false }),
        `the question did not carry what Run was asked to do: ${JSON.stringify(asked[0] && asked[0].opts)}`);

  // Processor only, not remembered.
  reset(); answer = busy;
  let going = App.run(null, null);
  await tick();
  check(dialogs.length === 1 && dialogs[0].title === 'The graphics card is busy',
        'no dialog about the busy card');
  press('Use the processor only');
  await going;
  check(started.length === 1 && started[0].opts.gpu_busy === 'processor',
        'the processor-only answer did not reach the run');
  check(saved.length === 0, 'an answer nobody asked to remember was saved');

  // Share, remembered.
  reset(); answer = busy;
  going = App.run(null, null);
  await tick();
  boxes[boxes.length - 1].checked = true;
  press('Share the graphics card');
  await going;
  check(started.length === 1 && started[0].opts.gpu_busy === 'share',
        'the share answer did not reach the run');
  check(saved.length === 1 && saved[0].resources && saved[0].resources.gpu_busy === 'share',
        `remember did not save the answer: ${JSON.stringify(saved)}`);

  // Cancel: nothing starts.
  reset(); answer = busy;
  going = App.run(null, null);
  await tick();
  press('Cancel');
  await going;
  check(started.length === 0, 'Cancel still started the run');

  // Closed some other way: nothing starts, and the run call finishes.
  reset(); answer = busy;
  let finished = false;
  going = App.run(null, null).then(() => { finished = true; });
  await tick();
  UI.closeModal();
  await tick(600);
  check(finished, 'closing the dialog without an answer left Run waiting for ever');
  check(started.length === 0, 'closing the dialog without an answer started the run');

  // A second dialog in its place answers the first with "nothing".
  reset(); answer = busy;
  finished = false;
  going = App.run(null, null).then(() => { finished = true; });
  await tick();
  UI.modal('Something else', element(), [{ label: 'OK' }]);
  await tick(600);
  check(finished && started.length === 0,
        'a dialog that took the question\'s place did not count as no answer');

  // The server failing to answer does not stop the run.
  reset(); checkFails = true;
  await App.run(null, null);
  check(started.length === 1 && started[0].opts.gpu_busy === '',
        'the run did not start when the question could not be asked');

  // Already running: nothing asked, nothing started.
  reset(); answer = busy;
  session.run = { status: 'running' };
  await App.run(null, null);
  check(asked.length === 0 && started.length === 0 && dialogs.length === 0,
        'a session already running asked or started something');

  if (failures) {
    console.log(`${failures} problem(s)`);
    process.exit(1);
  }
  console.log('the question at Run: asked only when the server says so; each answer '
              + 'reaches the run; Cancel and closing start nothing; remember saves');
})().catch((err) => {
  console.log(`  FAILED: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
