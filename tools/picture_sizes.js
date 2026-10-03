/* The pictures in the right-hand panel are drawn at the size they are seen at.

   The Viewer tab's picture takes whatever height the tab has left, and the
   line of text under it (atoms, chains, box, how to turn it) is empty until
   the first structure arrives. That line used to be filled in after the
   picture was drawn, so the first structure was drawn for a space 39 pixels
   taller than the one it was then squeezed into (624 against 585 in a window
   800 pixels high, with a small box of water, on 2026-10-03), and it stayed
   squashed until something drew it again. Only a change in the window's size
   did.

   What has to stay true:

     * the line of text is in place before the picture is drawn, so the first
       structure is drawn for the room that is really left
     * the picture is drawn again whenever its space changes size, whatever
       the reason: the line of text growing, the panel coming back after
       being put away, the window
     * the Plot tab's picture keeps a height of its own, so the legend and
       the numbers written under it cannot squeeze it (from the style sheet)

   Run:  node tools/picture_sizes.js
   It loads viewer.js with a stand-in for the page, so it needs neither a
   browser nor a running server. */
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

/* The page. The picture's space is 585 pixels high once the line of text
   under it has words in it, and 624 while that line is empty, as measured in
   the browser. What the picture was last drawn at is its width and height. */
const info = { textContent: '' };
let extra = 0;
const canvas = {
  width: 300, height: 150, style: {},
  get clientWidth() { return 379; },
  get clientHeight() { return (info.textContent ? 585 : 624) - extra; },
  addEventListener() {},
  getBoundingClientRect() { return { left: 0, top: 0, width: 379, height: this.clientHeight }; },
  // Any drawing call is accepted and does nothing.
  getContext: () => new Proxy({}, { get: (target, key) => (key in target ? target[key] : () => ({ width: 0 })) }),
};
const others = new Map();
const byId = (id) => {
  if (id === 'viewer-canvas') return canvas;
  if (id === 'viewer-info') return info;
  if (!others.has(id)) others.set(id, { textContent: '', value: '', addEventListener() {} });
  return others.get(id);
};

/* A stand-in for the browser's size watcher: it remembers what it was asked
   to watch, and the test says when a size has changed. */
const watchers = [];
class ResizeObserver {
  constructor(callback) { this.callback = callback; }
  observe(element) { watchers.push({ element, callback: this.callback }); }
  unobserve() {}
  disconnect() {}
}

const sandbox = {
  console, Math, JSON, Map, Set, Float32Array, Int32Array, Uint8Array, Array, Object, Number, String,
  document: { getElementById: byId, addEventListener() {}, createElement: () => ({ style: {} }) },
  window: { addEventListener() {}, devicePixelRatio: 1 },
  UI: { toast() {}, el: () => ({ style: {} }) },
  ResizeObserver,
  setTimeout, clearTimeout,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'viewer.js'), 'utf8'), sandbox,
  { filename: 'viewer.js' });
const Viewer = vm.runInContext('Viewer', sandbox);

console.log('the first structure');
Viewer.init();
// The structure itself is not what is being checked, so the part that draws
// it stands in for itself and draws the way the real one does: at the size
// its space has at that moment.
const drawn = () => [canvas.width, canvas.height];
Viewer.view.show = function show(data) { this.data = data; this.draw(); };
Viewer.view.draw = () => { canvas.width = canvas.clientWidth; canvas.height = canvas.clientHeight; };
Viewer.show({ name: 'cube.gro', n_atoms: 3072, chains: [], box: [55, 55, 55] }, '/tmp/cube.gro');
check(info.textContent.includes('3,072 atoms'), `the line under the picture says "${info.textContent}"`);
check(canvas.height === 585,
      `the first structure was drawn ${canvas.height} pixels high into a space of `
      + `${canvas.clientHeight}: the line of text under it came after the picture`);

console.log('its space changing size');
const watched = watchers.find((w) => w.element === canvas);
check(Boolean(watched), 'nothing watches the size of the picture\'s space');
if (watched) {
  extra = 48;   // the line of text under it has grown by two lines
  watched.callback([{ target: canvas }]);
  check(canvas.height === canvas.clientHeight,
        `after its space shrank to ${canvas.clientHeight} the picture is still `
        + `${canvas.height} pixels high`);
  extra = 0;
  watched.callback([{ target: canvas }]);
  check(canvas.height === 585, `after its space grew back the picture is ${canvas.height} pixels high`);
}

console.log('the Plot tab');
const css = fs.readFileSync(path.join(__dirname, '..', 'comfygmx', 'web', 'css', 'style.css'), 'utf8');
const plotRule = (css.match(/^#plot-canvas\s*\{([^}]*)\}/m) || [])[1] || '';
check(/height:\s*\d+px/.test(plotRule) && /flex-shrink:\s*0/.test(plotRule),
      `the Plot tab's picture no longer keeps a height of its own ("${plotRule.trim()}"), so the `
      + 'legend and numbers under it could squeeze it after it is drawn');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log(`\npictures: the first structure drawn at the room really left for it (${drawn().join(' x ')}), `
  + 'drawn again whenever that room changes, and the plot keeps a height of its own');
