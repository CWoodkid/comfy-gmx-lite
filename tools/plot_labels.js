/* Every number written beside a graph fits on the graph.

   A graph keeps a strip on its left for the numbers up its side. It used to
   be a fixed width: 40 pixels for the small graphs inside a block, 58 in the
   Plot tab. A potential energy of -623975.94 is ten characters, about 50
   pixels, so its first digits were drawn off the edge and the reader saw
   "3975.94". The strip is now as wide as the longest number needs. The
   numbers along the bottom are centred under their lines, so the last one
   used to hang half over the right edge ("100" under the secondary-structure
   map lost its last digit); now it stays inside.

   What has to stay true, for small graphs and big ones:

     * no number up the side starts left of the graph's own left edge
     * in the Plot tab, the numbers leave room for the axis title beside them
     * no number along the bottom sticks out on either side

   Run:  node tools/plot_labels.js
   It loads plots.js with a stand-in for the page that measures text the way
   a browser does in spirit (a fixed width per character), so it needs
   neither a browser nor a running server. */
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

/* A drawing surface that remembers every piece of text written on it, where,
   and how it was aligned. Text is measured at 0.6 of the font size per
   character: a little wider than real digits, so a margin that fits here
   fits in a browser too. */
function surface(width, height) {
  const written = [];
  let font = '10px system-ui';
  let align = 'start';
  let shifted = false;
  const size = () => Number((/(\d+)px/.exec(font) || [0, 10])[1]);
  const ctx = new Proxy({
    measureText: (text) => ({ width: String(text).length * size() * 0.6 }),
    fillText: (text, x) => {
      if (!shifted) written.push({ text: String(text), x, align, width: String(text).length * size() * 0.6 });
    },
    save: () => {}, restore: () => { shifted = false; },
    translate: () => { shifted = true; }, rotate: () => {},
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
  }, {
    get: (target, key) => (key in target ? target[key] : () => {}),
    set: (target, key, value) => {
      if (key === 'font') font = value;
      if (key === 'textAlign') align = value;
      target[key] = value;
      return true;
    },
  });
  return { canvas: { clientWidth: width, clientHeight: height, getContext: () => ctx }, written };
}

const sandbox = {
  window: { devicePixelRatio: 1, addEventListener() {} },
  document: {
    getElementById: () => ({ textContent: '', innerHTML: '', appendChild() {}, addEventListener() {},
      getContext: () => ({}) }),
    createElement: () => ({ getContext: () => ({ putImageData() {} }) }),
  },
  UI: { el: () => ({}) },
  console,
  Math, Number, String, Array, Object, Uint8ClampedArray, isFinite, parseInt,
};
vm.createContext(sandbox);
const source = fs.readFileSync(path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'plots.js'), 'utf8');
vm.runInContext(`${source}\nthis.drawPlot = drawPlot; this.drawDssp = drawDssp;`, sandbox);

const range = (n, from, to) => Array.from({ length: n }, (_, i) => from + (i / (n - 1)) * (to - from));

/* Graphs shaped like the real ones in the tutorials. */
const graphs = [
  { what: 'the minimisation energy in a block', compact: true, width: 280, height: 150,
    data: { x: range(388, 0, 489), series: [{ label: 'Potential', y: range(388, -456119, -623975.94) }] } },
  { what: 'the ice temperature in a block', compact: true, width: 280, height: 150,
    data: { x: range(201, 0, 200), series: [{ label: 'Temperature', y: range(201, 151.12, 1034.35) }] } },
  { what: 'a small RMSD in a block', compact: true, width: 280, height: 150,
    data: { x: range(101, 0, 10), series: [{ label: 'RMSD', y: range(101, -0.0037, 0.0749) }] } },
  { what: 'ten nanoseconds in picoseconds, in a block', compact: true, width: 280, height: 150,
    data: { x: range(1001, 0, 10000), series: [{ label: 'Rg', y: range(1001, 1.408, 1.427) }] } },
  { what: 'the minimisation energy in the Plot tab', compact: false, width: 379, height: 300,
    data: { x: range(388, 0, 489), xlabel: 'Energy Minimization Step', ylabel: '(kJ/mol)',
            series: [{ label: 'Potential', y: range(388, -456119, -623975.94) }] } },
];

for (const graph of graphs) {
  const { canvas, written } = surface(graph.width, graph.height);
  sandbox.drawPlot(canvas, graph.data, { compact: graph.compact });
  const side = written.filter((t) => t.align === 'right');
  const bottom = written.filter((t) => t.align === 'center');
  check(side.length >= 4, `${graph.what}: expected the numbers up the side, found ${side.length}`);
  check(bottom.length >= 4, `${graph.what}: expected the numbers along the bottom, found ${bottom.length}`);
  const titleRoom = !graph.compact && graph.data.ylabel ? 22 : 0;
  for (const t of side) {
    check(t.x - t.width >= titleRoom,
      `${graph.what}: "${t.text}" starts at ${(t.x - t.width).toFixed(1)} px, left of ${titleRoom}`);
  }
  for (const t of bottom) {
    check(t.x - t.width / 2 >= 0 && t.x + t.width / 2 <= graph.width,
      `${graph.what}: "${t.text}" runs from ${(t.x - t.width / 2).toFixed(1)} to `
      + `${(t.x + t.width / 2).toFixed(1)} px on a graph ${graph.width} px wide`);
  }
}

/* The secondary-structure map: residues up the side, pictures along the
   bottom, as the Lysozyme analysis draws it inside its block. */
{
  const frames = Array.from({ length: 101 }, () => 'H'.repeat(129));
  const { canvas, written } = surface(230, 220);
  sandbox.drawDssp(canvas, { frames, n_frames: 101, n_residues: 129, codes: ['H'],
    legend: [{ code: 'H', label: 'alpha helix' }] }, { compact: true });
  const side = written.filter((t) => t.align === 'right');
  const bottom = written.filter((t) => t.align === 'center');
  check(side.length >= 3 && bottom.length >= 3, 'the secondary-structure map: expected its numbers');
  for (const t of side) {
    check(t.x - t.width >= 0, `the secondary-structure map: "${t.text}" starts left of the edge`);
  }
  for (const t of bottom) {
    check(t.x - t.width / 2 >= 0 && t.x + t.width / 2 <= 230,
      `the secondary-structure map: "${t.text}" runs from ${(t.x - t.width / 2).toFixed(1)} `
      + `to ${(t.x + t.width / 2).toFixed(1)} px on a map 230 px wide`);
  }
}

if (failures) {
  console.log(`${failures} problem(s)`);
  process.exit(1);
}
console.log(`plot labels: every number fits, on ${graphs.length} graphs and the secondary-structure map`);
