/* The end of a cancelled run, as the page shows it (app.js, reconcile).

   After Cancel the page asks the server what became of the run, as well as
   following the run's stream. A run can end a moment after Cancel -- one
   whose simulation is waiting for free cores ends at once -- while its last
   lines are still on their way down the stream. If the page settled the run
   from the server's answer and stopped the stream there, the last lines never
   arrived: the block kept saying "waiting for free cores" and the log kept
   saying "running".

   What has to stay true:

     * the blocks are repainted from the server's answer, the line under each
       block included, so a cancelled wait no longer says it is waiting
     * a stream still attached is not stopped at once: it gets a moment to
       bring the last lines and settle the run itself, and the run is settled
       once, with one message
     * a stream that brings nothing in that moment does not leave the run
       "running": it is settled from the server's answer
     * with no stream attached the run is settled at once
     * a new run started in that moment is left alone

   Run:  node tools/cancel_end.js
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
    textContent: '', innerHTML: '', className: '', style: {}, checked: false, value: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener() {}, appendChild(child) { return child; },
    querySelector: () => null, querySelectorAll: () => [],
  };
}

/* What the page was told to show. */
const toasts = [];
const painted = [];
const UI = { el: () => element(), toast(text) { toasts.push(text); } };
let detail = null;
const API = { runDetail: () => Promise.resolve(detail) };

let session = null;
const sandbox = {
  document: { getElementById: () => element(), addEventListener() {} },
  window: { addEventListener() {} },
  console, UI, API,
  Sessions: {
    active: () => session, activeId: 's1',
    noteNode() {},
    noteStatus(s, status) { s.run.status = status; },
  },
  Editor: { setStatus(node, status, extra) { painted.push({ node, status, ...extra }); } },
  setTimeout, clearTimeout, setInterval, clearInterval, Promise, Math, JSON, Set, Map,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'app.js'), 'utf8'),
  sandbox, { filename: 'app.js' });
const App = vm.runInContext('App', sandbox);
App.setRunning = () => {};
App.refreshFiles = () => {};
App.schedulePlan = () => {};
App.streamGrace = 300;

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
let stopped = 0;
function start(runId, withStream) {
  toasts.length = 0; painted.length = 0; stopped = 0;
  session = {
    id: 's1', name: 'test',
    run: { id: runId, status: 'cancelling', statuses: { md: { status: 'running' } } },
    stop: withStream ? () => { stopped += 1; } : null,
  };
  detail = { status: 'cancelled',
             nodes: { md: { status: 'cancelled', error: '', progress: '' } } };
}

(async () => {
  // A stream still attached, which then brings the run's end itself.
  start('r1', true);
  App.reconcile(session, 8, 10);
  await tick(60);
  check(painted.some((p) => p.node === 'md' && p.status === 'cancelled' && p.progress === ''),
        `the block was not repainted from the server, line under it included: `
        + JSON.stringify(painted));
  check(stopped === 0 && session.run.status === 'cancelling',
        'the stream was stopped before it could bring the last lines');
  App.onRunStatus(session, 'cancelled');           // the stream's own "run" event
  check(stopped === 1 && session.run.status === 'cancelled',
        'the stream\'s own end did not settle the run');
  await tick(400);
  check(stopped === 1 && toasts.filter((t) => t === 'run cancelled').length === 1,
        `the run was settled twice: stopped ${stopped} time(s), messages ${JSON.stringify(toasts)}`);

  // A stream attached but silent: the run is settled anyway, after the moment.
  start('r2', true);
  App.reconcile(session, 8, 10);
  await tick(60);
  check(session.run.status === 'cancelling', 'settled before the stream had its moment');
  await tick(400);
  check(session.run.status === 'cancelled' && stopped === 1
        && toasts.filter((t) => t === 'run cancelled').length === 1,
        `a silent stream left the run '${session.run.status}' (stopped ${stopped} time(s))`);

  // No stream: settled at once.
  start('r3', false);
  App.reconcile(session, 8, 10);
  await tick(60);
  check(session.run.status === 'cancelled', `with no stream the run is '${session.run.status}'`);

  // A new run started in that moment is left alone.
  start('r4', true);
  App.reconcile(session, 8, 10);
  await tick(60);
  session.run = { id: 'r5', status: 'running', statuses: {} };
  await tick(400);
  check(session.run.id === 'r5' && session.run.status === 'running',
        `the new run was settled by the old one's check: ${session.run.status}`);

  if (failures) {
    console.log(`${failures} problem(s)`);
    process.exit(1);
  }
  console.log('the end of a cancelled run: blocks repainted with their last line, the stream '
              + 'given its moment, a silent stream settled anyway, a new run left alone');
})().catch((err) => {
  console.log(`  FAILED: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
