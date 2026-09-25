/* Does dragging sideways spin the structure about the middle of the screen?

   Reported: "once user hold left mouse button and tries to turn the structure
   moving the mouse directly to right or left, I expect for structure to move
   like a cylinder and rotate within self but it rotates like a roller
   coaster."

   It did. The view was turned by two angles: a turn about the MODEL's y axis,
   then a tilt about the screen's x. That is a turntable, and a turntable has
   one axis it can never get away from. Tilt far enough -- and a membrane box
   four times taller than it is wide has to be tilted right over before it can
   be seen upright -- and the model's y ends up pointing at the camera. Turning
   about an axis that points at you spins the picture in the plane of the
   screen like a pinwheel, and the ends of a long box swing out in great arcs.

   The system this was reported on: 24,272 atoms, 176 x 150 x 480 angstroms,
   sitting at a tilt of 84 degrees. Two degrees from the corner where a
   turntable gives up entirely.

   What has to stay true:

     * a drag straight sideways leaves the screen's up direction alone, so the
       structure spins about the line up the middle of the screen -- whatever
       way up it happens to be, tilted 84 degrees included
     * a drag straight up or down leaves the screen's right alone
     * the view opens at exactly the angle it always did
     * turning never squashes or stretches anything: the three directions stay
       at right angles and stay one unit long, however long you drag

   Run:  node tools/viewer_turn.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const sandbox = {
  console,
  document: {
    getElementById: () => null, createElement: () => ({ style: {}, getContext: () => null }),
    addEventListener() {}, querySelector: () => null,
  },
  window: {}, navigator: {}, setTimeout, clearTimeout,
  requestAnimationFrame: (fn) => fn(),
  fetch: () => Promise.reject(new Error('no network in this test')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'viewer.js'), 'utf8')
  + '\n;globalThis.__turn = { eulerRotation, turnBy, multiply };', sandbox);
const { eulerRotation, turnBy, multiply } = sandbox.__turn;

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };
const close = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;
const sameRow = (m, n, row) => [0, 1, 2].every((i) => close(m[row * 3 + i], n[row * 3 + i], 1e-12));

/* Where the screen's right, up and towards-you directions lie in the model. */
const RIGHT = 0; const UP = 1; const DEPTH = 2;

console.log('the view opens where it always did');
const start = eulerRotation(-0.35, 0.6);
// The old code worked these out inline; the same numbers, from the same angles.
const cx = Math.cos(-0.35); const sx = Math.sin(-0.35);
const cy = Math.cos(0.6); const sy = Math.sin(0.6);
const point = [3, -2, 5];
const oldX = point[0] * cy + point[2] * sy;
const oldZ1 = -point[0] * sy + point[2] * cy;
const oldY = point[1] * cx - oldZ1 * sx;
const put = (m, p, row) => m[row * 3] * p[0] + m[row * 3 + 1] * p[1] + m[row * 3 + 2] * p[2];
check(close(put(start, point, RIGHT), oldX, 1e-12)
      && close(put(start, point, UP), oldY, 1e-12),
      'the opening view is not where it used to be');

console.log('a drag straight sideways');
// The tilt this was reported at: 84 degrees over, which is where the old way
// gave up.
const steep = eulerRotation(-1.462, 0.04);
for (const [what, from] of [['at the opening angle', start], ['tilted 84 degrees', steep]]) {
  const spun = turnBy(from, 0.4, 0);
  check(sameRow(spun, from, UP),
        `THE BUG: dragging sideways ${what} moved the screen's up direction, so `
        + 'the structure rolls instead of spinning about the middle of the screen');
  check(!sameRow(spun, from, RIGHT),
        `dragging sideways ${what} did not turn the structure at all`);
}

console.log('a drag straight up or down');
const tipped = turnBy(steep, 0, 0.3);
check(sameRow(tipped, steep, RIGHT),
      'dragging up and down moved the screen\'s right direction, so it rolls');

console.log('a long drag does not squash it');
let m = start;
for (let i = 0; i < 400; i += 1) m = turnBy(m, 0.05, 0.03);
for (const row of [RIGHT, UP, DEPTH]) {
  const length = Math.hypot(m[row * 3], m[row * 3 + 1], m[row * 3 + 2]);
  check(close(length, 1, 1e-9),
        `after 400 turns one of the directions is ${length.toFixed(6)} long, not 1 -- `
        + 'the picture would be stretched');
}
const dot = (a, b) => [0, 1, 2].reduce((s, i) => s + m[a * 3 + i] * m[b * 3 + i], 0);
check(close(dot(RIGHT, UP), 0, 1e-9) && close(dot(RIGHT, DEPTH), 0, 1e-9)
      && close(dot(UP, DEPTH), 0, 1e-9),
      'after 400 turns the three directions are no longer at right angles');

console.log('the same drag lands in the same place, however it is cut up');
const once = turnBy(start, 0.7, 0.2);
const twiceOver = turnBy(start, 0.7, 0.2);
check(once.every((v, i) => close(v, twiceOver[i], 1e-12)),
      'the same drag from the same start gave two different answers');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nviewer: sideways spins it about the middle of the screen, at any tilt');
