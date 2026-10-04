/* A block that makes a picture shows it inside itself (viewer.js, the
   "image" kind of preview, drawn by drawPicture in plots.js).

   "Grow a snowflake" writes a PNG, and before it the page could not show a
   picture file anywhere. What has to stay true:

     * the preview of a picture is a canvas with a caption under it, and the
       picture is drawn as large as fits, in the middle, never stretched
     * the caption names the file and its size in pixels, and says what went
       wrong when the file is not a picture after all
     * a picture has no "open it bigger" button, as there is nowhere bigger to
       put it, and it starts square, as a snowflake is
     * a block without a file box of its own says "run the node", not "run
       the node, or set a file"
     * the reload button on a curve keeps the curve. It used to describe the
       curve as if it were a structure, which threw, and the curve was wiped.
       On a picture it names the file once, not twice

   Run:  node tools/picture_preview.js
   It loads api.js, plots.js and viewer.js with a stand-in for the page, so it
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

/* A drawing surface that remembers the pictures drawn on it. */
function surface() {
  const drawn = [];
  const ctx = new Proxy({ drawImage: (...args) => drawn.push(args) }, {
    get: (target, key) => (key in target ? target[key] : () => ({ width: 0 })),
    set: (target, key, value) => { target[key] = value; return true; },
  });
  return { ctx, drawn };
}

function makeElement(tag) {
  const el = {
    tagName: String(tag).toUpperCase(), textContent: '', title: '', children: [], style: {},
    className: '', attributes: {},
    appendChild(child) { el.children.push(child); return child; },
    setAttribute(key, value) { el.attributes[key] = value; },
    addEventListener() {}, remove() {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  };
  if (el.tagName === 'CANVAS') {
    const { ctx, drawn } = surface();
    el.drawn = drawn;
    el.getContext = () => ctx;
    // As wide as the node, as high as the preview was told to be.
    Object.defineProperty(el, 'clientWidth', { get: () => 300 });
    Object.defineProperty(el, 'clientHeight', { get: () => parseInt(el.style.height, 10) || 150 });
  }
  return el;
}

const toasts = [];
const sandbox = {
  console, Math, JSON, Map, Set, Float32Array, Int32Array, Uint8Array, Array, Object, Number,
  String, Promise, Date, encodeURIComponent,
  document: {
    getElementById: () => makeElement('div'),
    createElement: makeElement,
    createTextNode: (text) => ({ textContent: text, children: [] }),
    addEventListener() {},
  },
  window: { addEventListener() {}, devicePixelRatio: 1 },
  requestAnimationFrame: (fn) => fn(),
  ResizeObserver: class { observe() {} unobserve() {} disconnect() {} },
  setTimeout, clearTimeout,
  fetch: () => Promise.reject(new Error('no network in this test')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const name of ['api.js', 'plots.js', 'viewer.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'comfygmx', 'web', 'js', name), 'utf8'),
                  sandbox, { filename: name });
}
vm.runInContext(`
  var Editor = { defs: {}, view: { scale: 1 }, mark() {}, changed() {} };
  var App = { normalisePath: (p) => p, activateTab() {} };
  var Panels = { saveFile() {} };
  globalThis.__parts = { API, UI, NodePreview, Editor };
`, sandbox);
const { API, UI, NodePreview, Editor } = sandbox.__parts;
UI.toast = (text) => toasts.push(text);

Editor.defs['model.snowflake'] = {
  type: 'model.snowflake', title: 'Grow a snowflake',
  params: [{ name: 'gather' }, { name: 'extra' }, { name: 'size' }, { name: 'output' }],
  preview: { kind: 'image', port: 'picture' },
};
Editor.defs['view.plot'] = {
  type: 'view.plot', title: 'Preview plot', params: [{ name: 'path' }],
  preview: { kind: 'plot', port: 'xvg' },
};

const buttons = (host) => host.children[0].children
  .filter((child) => child && child.tagName === 'BUTTON').map((child) => child.textContent);
const canvasOf = (host) => host.children.find((child) => child.tagName === 'CANVAS');
const captionOf = (host) => host.children.find((child) => child.className === 'preview-caption');
const lastDrawn = (canvas) => canvas.drawn[canvas.drawn.length - 1] || [];

(async () => {
  console.log('a picture, before the block has run');
  const snow = { id: 'snow', type: 'model.snowflake', params: {}, title: 'Grow a snowflake' };
  const host = NodePreview.build(snow, Editor.defs['model.snowflake']);
  const canvas = canvasOf(host);
  const caption = captionOf(host);
  check(Boolean(canvas), 'the preview of a picture has no canvas');
  check(JSON.stringify(buttons(host)) === JSON.stringify(['⟳', '⤓']),
        `the buttons over a picture are ${JSON.stringify(buttons(host))}, not reload and save`);
  check(caption && caption.textContent === 'run the node',
        `before a run the caption says "${caption && caption.textContent}"`);
  check(snow.display && snow.display.width === 300 && snow.display.height === 300,
        `a picture starts ${snow.display && snow.display.width} x ${snow.display && snow.display.height}, not square`);

  console.log('the picture a run made');
  const picture = { naturalWidth: 612, naturalHeight: 612 };
  API.image = () => Promise.resolve({ name: 'snowflake.png', image: picture, width: 612, height: 612 });
  snow.previewPath = '/run/snow/snowflake.png';
  await NodePreview.refresh(snow);
  check(caption.textContent === 'snowflake.png, 612 × 612 pixels',
        `the caption says "${caption.textContent}"`);
  let [what, x, y, w, h] = lastDrawn(canvas);
  check(what === picture && x === 0 && y === 0 && w === 300 && h === 300,
        `in a 300 x 300 preview the picture is drawn at ${x}, ${y}, ${w} x ${h}`);
  NodePreview.resize(snow, 300, 190);
  [what, x, y, w, h] = lastDrawn(canvas);
  check(what === picture && x === 55 && y === 0 && w === 190 && h === 190,
        `in a 300 x 190 preview the picture is drawn at ${x}, ${y}, ${w} x ${h}, `
        + 'not 190 x 190 in the middle');

  toasts.length = 0;
  await NodePreview.refresh(snow, true);
  check(toasts[0] === 'snowflake.png, 612 × 612 pixels',
        `reloading the picture said "${toasts[0]}"`);

  console.log('a file that is not a picture');
  API.image = () => Promise.resolve({ name: 'snowflake.png',
                                      error: 'this is not a picture the browser can read' });
  await NodePreview.refresh(snow);
  check(caption.textContent === 'snowflake.png: this is not a picture the browser can read',
        `the caption says "${caption.textContent}"`);
  check(snow.previewData === null, 'the old picture is still held after a failed read');

  console.log('reloading a curve');
  const plot = { id: 'plot', type: 'view.plot', params: { path: '/run/energy/energy.xvg' },
                 title: 'Preview plot' };
  API.xvg = () => Promise.resolve({ x: [0, 1, 2], series: [{ label: 'Potential', y: [3, 2, 1] }],
                                    n_rows: 3, stride: 1 });
  NodePreview.build(plot, Editor.defs['view.plot']);
  await NodePreview.refresh(plot);
  toasts.length = 0;
  await NodePreview.refresh(plot, true);
  check(plot.previewData !== null && !plot.previewError,
        `reloading a curve wiped it: "${plot.previewError}"`);
  check(toasts[0] === 'energy.xvg: 1 series, 3 rows', `the reload said "${toasts[0]}"`);

  if (failures) {
    console.log(`${failures} problem(s)`);
    process.exit(1);
  }
  console.log('picture preview: drawn as large as fits without stretching, a caption with its size, '
              + 'no button to nowhere, square to start; a curve survives its reload button');
})().catch((err) => {
  console.log(`  FAILED: ${err.stack || err}`);
  process.exit(1);
});
