/* Take the pictures for the tutorial website (website/), from a running page.

   It drives a Chrome without a window through its remote-control port, the
   way a person would use the page: it loads a tutorial with "Load as new
   graph", zooms the canvas to one box at a time, puts on every block the
   number the website gives it, and saves a picture of the canvas. The
   numbers come from website/_generated/<tutorial>/boxes.json, which
   tools/website.py writes, so a picture and its page always agree.

   usage:
     node tools/website_pictures.js DEBUG_PORT PAGE_URL TUTORIAL OUT_FOLDER [results|screen]

   DEBUG_PORT  the port of a Chrome started with --remote-debugging-port
   PAGE_URL    the editor's address (a test page), or @FILE to read it from a
               file (an online copy: its address carries its key)
   TUTORIAL    ice_melting or lysozyme
   OUT_FOLDER  where the pictures go: box-1.webp, box-2.webp, ..., whole.webp
   results     instead of the boxes as built: switch every box on, press Run,
               wait until everything has finished, and then take the boxes
               with their results in them (box-1-results.webp, ...), and each
               preview block on its own (<block>.webp)
   screen      instead: the whole editor, both side panels out, a number on
               each of its four parts, the first box on the canvas and the
               command of its first block on the right (screen.webp, for
               website/basics.md). Take it from an online copy: the Command
               tab shows the run folder, which on a test page is a path on
               your own computer.

   A run happens only with "results", and only where the page runs it. For
   the online copy that is mybinder.org, not this computer. */
'use strict';
const fs = require('fs');
const path = require('path');

const [port, where, tutorial, out, mode] = process.argv.slice(2);
// @FILE reads the address from a file: an online copy's address carries its
// key, and a command line can be seen by anybody on the computer.
const url = where.startsWith('@') ? fs.readFileSync(where.slice(1), 'utf8').trim() : where;
const results = mode === 'results';
const screen = mode === 'screen';
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const t0 = Date.now();
const stamp = () => `${((Date.now() - t0) / 1000).toFixed(0).padStart(5)} s`;
const boxes = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'website', '_generated',
  tutorial, 'boxes.json'), 'utf8'));

(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((done) => ws.addEventListener('open', done));
  let id = 0;
  const waiting = new Map();
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id); }
  });
  const send = (method, params = {}) => new Promise((done) => {
    id += 1; waiting.set(id, done); ws.send(JSON.stringify({ id, method, params }));
  });
  const js = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) {
      throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400));
    }
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  const save = async (file, clip) => {
    const r = await send('Page.captureScreenshot', { format: 'webp', quality: 90, clip: { ...clip, scale: 1 } });
    fs.writeFileSync(path.join(out, file), Buffer.from(r.result.data, 'base64'));
    console.log(`${stamp()}  saved ${file} (${Math.round(clip.width)} x ${Math.round(clip.height)})`);
  };
  const escape = async () => {
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await sleep(400);
  };
  fs.mkdirSync(out, { recursive: true });

  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url });
  await sleep(6000);
  // No tour of the mouse and keyboard over the pictures, now or after a reload.
  await js(`localStorage.setItem('comfygmx.tour.never', '1'); true`);
  // Close whatever opened by itself: the tour, or the first-start setup.
  for (let i = 0; i < 5 && await js(`!document.getElementById('modal-backdrop').classList.contains('hidden')`); i += 1) {
    console.log(`${stamp()}  closed the window "${await js(`document.getElementById('modal-title').textContent`)}"`);
    await escape();
  }
  // The canvas gets the whole width: both side panels put away.
  await js(`SidePanels.toggle('left', false); SidePanels.toggle('right', false); true`);
  await sleep(500);

  console.log(`${stamp()}  open tutorial: ${await js(`App.openTutorial(${JSON.stringify(tutorial)}).then(() => 'opened')`)}`);
  await sleep(1500);
  await js(`(() => {
    window.confirm = () => true;   // "Replace the current graph?" -- yes
    const button = [...document.querySelectorAll('button')]
      .find((el) => (el.textContent || '').trim() === 'Load as new graph');
    button.click();
  })()`);
  await sleep(3000);
  console.log(`${stamp()}  blocks on the canvas: ${await js('Editor.nodes.size')}`);

  // The extra boxes ship switched off. Built by hand, a block starts
  // switched on, so the pictures show them on. This runs nothing by itself.
  const switched = await js(`(() => {
    const off = [...Editor.nodes.values()].filter((n) => n.off).map((n) => n.id);
    if (off.length) Editor.toggleOff(off);
    return off.length;
  })()`);
  console.log(`${stamp()}  switched on ${switched} blocks`);
  await sleep(2000);

  if (screen) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 860, deviceScaleFactor: 1, mobile: false });
    await js(`SidePanels.toggle('left', true); SidePanels.toggle('right', true); true`);
    await sleep(600);
    await js(`document.querySelector('#palette-tabs [data-tab="nodes"]').click(); true`);
    const first = boxes[0];
    await js(`(() => {
      const g = Editor.groups.find((g) => g.title === ${JSON.stringify(first.title)});
      const [x, y, w, h] = g.bounds;
      const r = document.getElementById('canvas').getBoundingClientRect();
      const scale = Math.min(0.75, (r.width - 80) / w, (r.height - 80) / h);
      Editor.view.scale = scale;
      Editor.view.x = (r.width - w * scale) / 2 - x * scale;
      Editor.view.y = (r.height - h * scale) / 2 - y * scale;
      Editor.applyView();
      Editor.select([${JSON.stringify(first.blocks[0])}]);
      return true;
    })()`);
    await sleep(800);
    await js(`document.querySelector('#inspector-tabs [data-tab="command"]').click(); true`);
    await sleep(1500);
    // The numbers 1 to 4 of the page, each where it covers nothing that
    // matters: the run forecast in the toolbar, the empty end of the first
    // heading in the list, the empty top left of the canvas, and the empty
    // bottom of the right-hand panel.
    console.log(`${stamp()}  numbered ${await js(`(() => {
      const style = document.createElement('style');
      style.textContent = '#toast-stack { visibility: hidden !important; }'
        + ' .picture-number { position: fixed; z-index: 9999; width: 30px; height: 30px; border-radius: 50%;'
        + ' background: #ffd166; color: #111; border: 2px solid #111; font: 700 16px/26px system-ui, sans-serif;'
        + ' text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.5); pointer-events: none; }';
      document.head.appendChild(style);
      const rect = (id) => document.getElementById(id).getBoundingClientRect();
      const bar = rect('topbar');
      const after = rect('btn-cancel');
      const list = rect('palette');
      const tabs = rect('palette-tabs');
      const canvas = rect('canvas');
      const panel = rect('inspector');
      const spots = [
        [after.right + 14, bar.top + (bar.height - 30) / 2],
        [list.right - 44, tabs.bottom + 10],
        [canvas.left + 16, canvas.top + 16],
        [panel.right - 46, panel.bottom - 46],
      ];
      spots.forEach(([x, y], i) => {
        const badge = document.createElement('div');
        badge.className = 'picture-number';
        badge.textContent = String(i + 1);
        badge.style.left = x + 'px';
        badge.style.top = y + 'px';
        document.body.appendChild(badge);
      });
      return spots.length;
    })()`)} parts`);
    await sleep(400);
    const shot = await send('Page.captureScreenshot', { format: 'webp', quality: 90 });
    fs.writeFileSync(path.join(out, 'screen.webp'), Buffer.from(shot.result.data, 'base64'));
    console.log(`${stamp()}  saved screen.webp (1400 x 860)`);
    process.exit(0);
  }

  if (results) {
    await js(`document.getElementById('btn-run').click(); true`);
    console.log(`${stamp()}  pressed Run`);
    let last = '';
    for (;;) {
      await sleep(10000);
      const state = await js(`(() => {
        const counts = {};
        for (const n of Editor.nodes.values()) counts[n.status || 'none'] = (counts[n.status || 'none'] || 0) + 1;
        return { pill: (document.getElementById('run-status') || {}).textContent || '',
                 busy: document.getElementById('btn-run').disabled, counts };
      })()`);
      const line = `${state.pill} ${JSON.stringify(state.counts)}`;
      if (line !== last) { console.log(`${stamp()}  ${line}`); last = line; }
      if (!state.busy && Date.now() - t0 > 60000) break;
      if (Date.now() - t0 > 45 * 60000) { console.log(`${stamp()}  STILL RUNNING AFTER 45 MINUTES`); process.exit(1); }
    }
    // Let the previews fetch and draw what the run produced.
    await sleep(8000);
  }

  // The bar of zoom buttons and the Terminal tab sit over the canvas.
  await js(`(() => {
    const style = document.createElement('style');
    style.id = 'pictures-style';
    style.textContent = '#minimap-info, #terminal-handle, #toast-stack, #palette-handle, #inspector-handle { visibility: hidden !important; }'
      + ' .picture-number { position: fixed; z-index: 9999; width: 30px; height: 30px; border-radius: 50%;'
      + ' background: #ffd166; color: #111; border: 2px solid #111; font: 700 16px/26px system-ui, sans-serif;'
      + ' text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,.5); pointer-events: none; }';
    document.head.appendChild(style);
    Editor.select([]);
    return true;
  })()`);

  const canvasRect = async () => js(`(() => { const r = document.getElementById('canvas').getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height }; })()`);
  // The view that shows a rectangle of the canvas (in its own units) as
  // large as fits, as the Fit button does for everything.
  const show = async (bounds, most = 1.2, pad = 30) => js(`(() => {
    const [x, y, w, h] = ${JSON.stringify(bounds)};
    const r = document.getElementById('canvas').getBoundingClientRect();
    const scale = Math.min(${most}, (r.width - ${pad} * 2) / w, (r.height - ${pad} * 2) / h);
    Editor.view.scale = scale;
    Editor.view.x = (r.width - w * scale) / 2 - x * scale;
    Editor.view.y = (r.height - h * scale) / 2 - y * scale;
    Editor.applyView();
    return scale;
  })()`);

  // Every box at the same zoom, so that text is the same size in every
  // picture on the site. The window is made just big enough for the box:
  // the canvas is the window less the toolbar and the status line.
  const ZOOM = 0.8;
  const PAD = 90;
  const frame = await js(`(() => { const r = document.getElementById('canvas').getBoundingClientRect();
    return [window.innerWidth - r.width, window.innerHeight - r.height]; })()`);
  for (const box of boxes) {
    const bounds = await js(`(() => {
      const g = Editor.groups.find((g) => g.title === ${JSON.stringify(box.title)});
      return g ? g.bounds : null;
    })()`);
    if (!bounds) { console.log(`${stamp()}  NO BOX CALLED "${box.title}"`); continue; }
    const width = Math.ceil(bounds[2] * ZOOM + PAD * 2 + frame[0]);
    const height = Math.ceil(bounds[3] * ZOOM + PAD * 2 + frame[1]);
    await send('Emulation.setDeviceMetricsOverride', { width: Math.max(width, 900), height: Math.max(height, 600),
      deviceScaleFactor: 1, mobile: false });
    await sleep(700);
    const scale = await show(bounds, ZOOM, PAD);
    await sleep(900);
    // The numbers, on the top left corner of each block, as on the page.
    const placed = await js(`(() => {
      document.querySelectorAll('.picture-number').forEach((el) => el.remove());
      let placed = 0;
      ${JSON.stringify(box.blocks)}.forEach((nodeId, i) => {
        const node = Editor.nodes.get(nodeId);
        if (!node || !node._el) return;
        const r = node._el.getBoundingClientRect();
        const badge = document.createElement('div');
        badge.className = 'picture-number';
        badge.textContent = String(i + 1);
        badge.style.left = (r.left - 13) + 'px';
        badge.style.top = (r.top - 13) + 'px';
        document.body.appendChild(badge);
        placed += 1;
      });
      return placed;
    })()`);
    // Only the part of the canvas the box covers, with a little room around:
    // the box itself and the names of the sockets on its walls, which stand
    // outside it.
    const area = await js(`(() => {
      const g = Editor.groups.find((g) => g.title === ${JSON.stringify(box.title)});
      const parts = [g._el, ...g._el.querySelectorAll('.group-wall, .group-wall *')];
      let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
      for (const el of parts) {
        const r = el.getBoundingClientRect();
        if (!r.width && !r.height) continue;
        left = Math.min(left, r.left); top = Math.min(top, r.top);
        right = Math.max(right, r.right); bottom = Math.max(bottom, r.bottom);
      }
      const c = document.getElementById('canvas').getBoundingClientRect();
      left = Math.max(c.left, left - 16); top = Math.max(c.top, top - 16);
      right = Math.min(c.right, right + 16); bottom = Math.min(c.bottom, bottom + 16);
      return { x: left, y: top, width: right - left, height: bottom - top };
    })()`);
    console.log(`${stamp()}  box ${box.n} "${box.title}": zoom ${scale.toFixed(2)}, ${placed} of ${box.blocks.length} numbered`);
    await save(`box-${box.n}${results ? '-results' : ''}.webp`, area);
    await js(`document.querySelectorAll('.picture-number').forEach((el) => el.remove()); true`);

    if (results) {
      await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
      await sleep(700);
      // Each preview block on its own, large enough to read.
      for (const nodeId of box.blocks) {
        const isPreview = await js(`(() => { const n = Editor.nodes.get(${JSON.stringify(nodeId)});
          return Boolean(n && n.type.startsWith('view.')); })()`);
        if (!isPreview) continue;
        const nodeBounds = await js(`(() => { const n = Editor.nodes.get(${JSON.stringify(nodeId)});
          return [n.pos[0], n.pos[1], n._el.offsetWidth, n._el.offsetHeight]; })()`);
        await show(nodeBounds, 1.6, 40);
        await sleep(1200);
        const rect = await js(`(() => { const r = Editor.nodes.get(${JSON.stringify(nodeId)})._el.getBoundingClientRect();
          return { x: r.left - 4, y: r.top - 4, width: r.width + 8, height: r.height + 8 }; })()`);
        await save(`${nodeId}.webp`, rect);
      }
    }
  }

  // The whole tutorial at once, for its overview page. Only as built: the
  // overview page has no use for the same picture after a run.
  if (!results) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1000, deviceScaleFactor: 1, mobile: false });
    await sleep(700);
    await js(`Editor.fit(); true`);
    await sleep(1200);
    await save('whole.webp', await canvasRect());
  }
  process.exit(0);
})().catch((err) => { console.error(`${stamp()}  FAILED: ${err.message}`); process.exit(1); });
