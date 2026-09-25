/* A small orthographic structure viewer: points plus a backbone trace.

   This exists to answer "did that actually work?" -- is the protein in the box,
   did the membrane form, is the complex still intact after 10 microseconds. It
   is not a replacement for VMD or PyMOL, and it does not pretend to be.

   Three things share this file: the renderer, the Viewer tab in the inspector,
   and the pictures drawn inside "Preview structure" nodes. They are the same
   code because they answer the same question at different sizes. */
'use strict';

/* A trace drawn when the colouring is by element: there is no element to draw
   it by, so it stays out of the way of the points that do have one. */
const TRACE_PLAIN = '#7f8894';

const CHAIN_COLORS = [
  '#4f9dd8', '#6fbf8b', '#d8a84f', '#d9705f', '#8a7fd0',
  '#4fb8c8', '#c88fd0', '#a8b84f', '#d0855f', '#7a95d0',
];

/* ------------------------------------------------------ turning the model */

/* The three directions of the screen -- right, up, and towards you -- written
   in the model's own coordinates, as nine numbers row by row. Multiplying a
   point by it says where on the screen the point goes.

   Angles would be shorter to write and are the reason this was wrong: two
   angles can only ever describe a turntable, and a turntable has one axis it
   cannot get away from. Nine numbers describe any orientation at all, and
   turning about the axis you can see is then one multiplication. */

/* The orientation the two old angles used to mean: a turn about the model's y
   axis, then a tilt about the screen's x. Kept so the view still opens at
   exactly the angle it always did. */
function eulerRotation(tilt, turn) {
  const cx = Math.cos(tilt); const sx = Math.sin(tilt);
  const cy = Math.cos(turn); const sy = Math.sin(turn);
  return [
    cy, 0, sy,
    sy * sx, cx, -cy * sx,
    -sy * cx, sx, cy * cx,
  ];
}

/* Turn a model by two angles measured on the screen: `side` about the line up
   the middle of the screen, `over` about the line across it.

   The order is: sideways first, then over the top. Both are turns about the
   screen's own axes, which is what makes them multiply on the left -- the new
   turn happens in front of everything already done, rather than being added
   to the model's own idea of which way is up. That is the whole difference
   between this and what it replaced.

   A drag straight sideways leaves the middle row -- the screen's up -- exactly
   as it was, so the structure spins about the line up the middle of the screen
   and nothing tips. A drag straight up or down leaves the top row alone in the
   same way. Only a diagonal drag mixes the two, and then it does what a hand
   turning a ball would do. */
function turnBy(start, side, over) {
  const cs = Math.cos(side); const ss = Math.sin(side);
  const co = Math.cos(over); const so = Math.sin(over);
  // About the screen's up axis, then about the screen's right axis.
  const spin = [cs, 0, ss, 0, 1, 0, -ss, 0, cs];
  const tip = [1, 0, 0, 0, co, -so, 0, so, co];
  return multiply(tip, multiply(spin, start));
}

/* Row-by-row, nine numbers each. */
function multiply(a, b) {
  const out = new Array(9);
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      out[row * 3 + col] = a[row * 3] * b[col]
        + a[row * 3 + 1] * b[3 + col]
        + a[row * 3 + 2] * b[6 + col];
    }
  }
  return out;
}

/* ------------------------------------------------------------- renderer */

/* One picture on one canvas. Pointer capture keeps every listener on the
   canvas element, so a view dies with its node instead of leaving handlers
   on window behind -- node bodies are rebuilt often. */
function createStructureView(canvas, options = {}) {
  const opts = {
    empty: 'select a .pdb or .gro in the Files tab',
    minHeight: 260,
    /* The editor draws nodes inside a scaled world; a 10 px mouse move is
       10/scale px of node. Without this, rotation speed changes with zoom. */
    scale: () => 1,
    ...options,
  };

  const view = {
    canvas,
    ctx: canvas.getContext('2d'),
    data: null,
    message: '',
    /* How the model is turned, as three rows: the screen's own right, up and
       towards-you directions, written in the model's coordinates.

       It used to be two angles -- a turn about the model's y axis and a tilt
       about the screen's x. That is a turntable, and a turntable has one axis
       it can never get away from. Tilt far enough and the model's y ends up
       pointing at the camera, and then dragging sideways spins the picture in
       the plane of the screen like a pinwheel instead of turning the molecule.
       On a membrane box, which is four times taller than it is wide and has
       to be tilted right over to be seen upright, that is exactly where you
       end up -- and the ends of the box swing out in great arcs.

       Kept as a matrix, a drag turns the model about the screen's own axes
       instead: sideways always spins it about the line up the middle of the
       screen, whatever way up it happens to be. */
    rot: eulerRotation(-0.35, 0.6),
    zoom: 1,
    pan: { x: 0, y: 0 },
    /* What the view turns around, in model space. Zero is the centroid of
       everything loaded, which is the box centre for a solvated system -- so
       turning it swings the protein across the screen instead of spinning it
       where it stands. Double-click an atom to turn around that instead. */
    pivot: { x: 0, y: 0, z: 0 },
    style: 'auto',
    colorBy: 'element',
    _interacting: false,

    show(data) {
      this.data = data;
      this.message = '';
      this._prepare();
      this.reset();
      return data;
    },

    /* A stack of coordinate sets over the same atoms. The centre and the
       radius are worked out once over the whole stack, so the molecule neither
       jumps nor rescales as it plays. */
    setFrame(index) {
      const frames = this.data && this.data.frames;
      if (!frames || !frames.length) return;
      const clamped = Math.max(0, Math.min(frames.length - 1, Math.round(index)));
      this.frame = clamped;
      const frame = frames[clamped];
      const c = this._centre;
      for (let i = 0; i < this.px.length; i += 1) {
        this.px[i] = frame.x[i] - c.x;
        this.py[i] = frame.y[i] - c.y;
        this.pz[i] = frame.z[i] - c.z;
      }
      this.draw();
    },

    clear(message = '') {
      this.data = null;
      this.message = message;
      this.draw();
    },

    reset() {
      this.zoom = 1;
      this.pan = { x: 0, y: 0 };
      this.rot = eulerRotation(-0.35, 0.6);
      this.pivot = { x: 0, y: 0, z: 0 };
      this.draw();
    },

    /* Turn around this point from now on, and bring it to the middle. */
    setPivot(index) {
      if (index == null || !this.px) return;
      this.pivot = { x: this.px[index], y: this.py[index], z: this.pz[index] };
      this.pan = { x: 0, y: 0 };
      this.draw();
    },

    /* The atom nearest a point on the canvas, from the last frame drawn. */
    pick(cx, cy, within = 18) {
      if (!this._sx) return null;
      let best = null;
      let bestD = within * within;
      for (let i = 0; i < this._sx.length; i += 1) {
        const dx = this._sx[i] - cx;
        const dy = this._sy[i] - cy;
        const d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    },

    setStyle(style) { this.style = style; this.draw(); },
    setColor(colorBy) { this.colorBy = colorBy; this.draw(); },

    _prepare() {
      const data = this.data;
      const n = data.x.length;
      // One centre and one radius for the whole run, not per frame: recentring
      // each frame would hide the very drift you are looking for, and
      // rescaling each frame would make a breathing protein look still.
      const stack = data.frames && data.frames.length ? data.frames : [data];
      let cx = 0; let cy = 0; let cz = 0;
      for (const frame of stack) {
        for (let i = 0; i < n; i += 1) { cx += frame.x[i]; cy += frame.y[i]; cz += frame.z[i]; }
      }
      const total = n * stack.length;
      cx /= total; cy /= total; cz /= total;
      this._centre = { x: cx, y: cy, z: cz };
      this.frame = 0;

      this.px = new Float32Array(n);
      this.py = new Float32Array(n);
      this.pz = new Float32Array(n);
      let radius = 1;
      for (const frame of stack) {
        for (let i = 0; i < n; i += 1) {
          radius = Math.max(radius, Math.hypot(frame.x[i] - cx, frame.y[i] - cy,
                                               frame.z[i] - cz));
        }
      }
      for (let i = 0; i < n; i += 1) {
        this.px[i] = stack[0].x[i] - cx;
        this.py[i] = stack[0].y[i] - cy;
        this.pz[i] = stack[0].z[i] - cz;
      }
      this.radius = radius;

      // Per-atom colour, resolved once rather than per frame.
      const chainIndex = {};
      data.chains.forEach((chain, index) => { chainIndex[chain] = index; });
      this.colorElement = new Array(n);
      this.colorChain = new Array(n);
      this.colorBfactor = new Array(n);
      const bf = data.bfactor || [];
      // ConSurf's nine grades, 1 (variable, cyan) to 9 (conserved, maroon);
      // any other B-factor range is stretched onto the same nine colours.
      const grades = ['#10c8d1', '#8cffff', '#d7ffff', '#eaffff', '#ffffff',
                      '#fcedf1', '#faccd8', '#f27f9a', '#a0203c'];
      const values = bf.filter((v) => Number.isFinite(v) && v !== 0);
      const isGrades = values.length && values.every((v) => v >= 1 && v <= 9 && Math.abs(v - Math.round(v)) < 1e-6);
      const lo = values.length ? Math.min(...values) : 0;
      const hi = values.length ? Math.max(...values) : 1;
      for (let i = 0; i < n; i += 1) {
        this.colorElement[i] = data.colors[data.element[i]] || '#909090';
        this.colorChain[i] = CHAIN_COLORS[(chainIndex[data.chain[i]] || 0) % CHAIN_COLORS.length];
        const v = bf[i];
        if (!Number.isFinite(v) || v === 0) this.colorBfactor[i] = '#5c6672';
        else if (isGrades) this.colorBfactor[i] = grades[Math.max(0, Math.min(8, Math.round(v) - 1))];
        else this.colorBfactor[i] = grades[Math.max(0, Math.min(8, Math.floor(8.999 * (v - lo) / ((hi - lo) || 1))))];
      }
    },

    draw() {
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight || opts.minHeight;
      if (!width || !height) return;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const ctx = this.ctx;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.fillStyle = '#0d1014';
      ctx.fillRect(0, 0, width, height);

      if (!this.data) {
        ctx.fillStyle = '#626c7a';
        ctx.font = '12px system-ui';
        ctx.textAlign = 'center';
        ctx.fillText(this.message || opts.empty, width / 2, height / 2);
        return;
      }

      const n = this.px.length;
      const scale = (Math.min(width, height) * 0.45 / this.radius) * this.zoom;
      const ox = width / 2 + this.pan.x;
      const oy = height / 2 + this.pan.y;

      // Three rows: where the screen's right, up and towards-you directions
      // lie in the model. A point's place on screen is what it measures along
      // each of them.
      const r = this.rot;
      const r0 = r[0]; const r1 = r[1]; const r2 = r[2];
      const r3 = r[3]; const r4 = r[4]; const r5 = r[5];
      const r6 = r[6]; const r7 = r[7]; const r8 = r[8];

      const sx = new Float32Array(n);
      const sy = new Float32Array(n);
      const sz = new Float32Array(n);
      const vx = this.pivot.x; const vy = this.pivot.y; const vz = this.pivot.z;
      for (let i = 0; i < n; i += 1) {
        const x = this.px[i] - vx; const y = this.py[i] - vy; const z = this.pz[i] - vz;
        sx[i] = ox + (r0 * x + r1 * y + r2 * z) * scale;
        sy[i] = oy - (r3 * x + r4 * y + r5 * z) * scale;
        sz[i] = r6 * x + r7 * y + r8 * z;
      }
      this._sx = sx; this._sy = sy;

      const style = this.style === 'auto'
        ? (this.data.trace.length && n > 6000 ? 'both' : 'points')
        : this.style;

      if (style === 'points' || style === 'both') {
        // Thin out while the mouse is down so rotation stays interactive.
        const stride = this._interacting && n > 12000 ? Math.ceil(n / 12000) : 1;
        const indices = [];
        for (let i = 0; i < n; i += stride) indices.push(i);
        indices.sort((a, b) => sz[a] - sz[b]);

        const palette = this.colorBy === 'chain' ? this.colorChain
          : this.colorBy === 'bfactor' ? this.colorBfactor : this.colorElement;
        const size = Math.max(1.2, Math.min(5, scale * 0.55));
        const depthRange = this.radius * 2 || 1;
        for (const i of indices) {
          if (this.colorBy === 'depth') {
            const t = (sz[i] + this.radius) / depthRange;
            ctx.fillStyle = `hsl(${210 - t * 150}, 55%, ${28 + t * 42}%)`;
          } else {
            ctx.fillStyle = palette[i];
          }
          ctx.globalAlpha = style === 'both' ? 0.45 : 0.9;
          ctx.fillRect(sx[i] - size / 2, sy[i] - size / 2, size, size);
        }
        ctx.globalAlpha = 1;
      }

      if (style === 'trace' || style === 'both') {
        ctx.lineWidth = Math.max(1.2, Math.min(4, scale * 0.35));
        ctx.lineJoin = 'round';
        const depthRange = this.radius * 2 || 1;
        for (const run of this.data.trace) {
          if (this.colorBy === 'depth') {
            // Segment by segment, because the whole point of colouring by
            // depth is that the far end of a run is a different colour from
            // the near end, and one stroke can only be one colour.
            for (let k = 1; k < run.length; k += 1) {
              const a = run[k - 1];
              const b = run[k];
              const t = ((sz[a] + sz[b]) / 2 + this.radius) / depthRange;
              ctx.strokeStyle = `hsl(${210 - t * 150}, 55%, ${28 + t * 42}%)`;
              ctx.beginPath();
              ctx.moveTo(sx[a], sy[a]);
              ctx.lineTo(sx[b], sy[b]);
              ctx.stroke();
            }
            continue;
          }
          // A backbone trace has no element -- it is not atoms -- so 'element'
          // leaves it neutral and lets the points carry the colour. Colouring
          // it per run instead, which is what this used to do, made all three
          // settings paint the same picture whenever every run was a chain:
          // the control looked broken because it was.
          if (this.colorBy === 'bfactor') {
            // Segment by segment: the grade changes residue by residue along
            // the chain, which is the whole point of this colouring.
            for (let k = 1; k < run.length; k += 1) {
              const a = run[k - 1];
              const b = run[k];
              ctx.strokeStyle = this.colorBfactor[b] || TRACE_PLAIN;
              ctx.beginPath();
              ctx.moveTo(sx[a], sy[a]);
              ctx.lineTo(sx[b], sy[b]);
              ctx.stroke();
            }
            continue;
          }
          ctx.strokeStyle = this.colorBy === 'chain'
            ? (this.colorChain[run[0]] || '#4f9dd8')
            : TRACE_PLAIN;
          ctx.beginPath();
          run.forEach((atom, position) => {
            if (position === 0) ctx.moveTo(sx[atom], sy[atom]);
            else ctx.lineTo(sx[atom], sy[atom]);
          });
          ctx.stroke();
        }
      }

      // Scale bar: 1 nm in the current projection.
      const barPixels = scale * 10;
      if (barPixels > 12 && barPixels < width * 0.7) {
        ctx.strokeStyle = '#8d97a5';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(14, height - 16);
        ctx.lineTo(14 + barPixels, height - 16);
        ctx.stroke();
        ctx.fillStyle = '#8d97a5';
        ctx.font = '10px system-ui';
        ctx.textAlign = 'left';
        ctx.fillText('1 nm', 14, height - 21);
      }
    },
  };

  let dragging = null;
  /* Right-drag is a pan, so the context menu must not open on the canvas. */
  canvas.addEventListener('contextmenu', (event) => event.preventDefault());
  canvas.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 && event.button !== 1 && event.button !== 2) return;
    event.preventDefault();
    event.stopPropagation();
    canvas.setPointerCapture(event.pointerId);
    dragging = {
      x: event.clientX, y: event.clientY,
      rot: view.rot.slice(), px: view.pan.x, py: view.pan.y,
      /* Left turns it, anything else slides it. Shift is kept because it is
         what the caption used to say and fingers remember. */
      shift: event.shiftKey || event.button === 1 || event.button === 2,
    };
    view._interacting = true;
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const k = opts.scale() || 1;
    const dx = (event.clientX - dragging.x) / k;
    const dy = (event.clientY - dragging.y) / k;
    if (dragging.shift) {
      view.pan.x = dragging.px + dx;
      view.pan.y = dragging.py + dy;
    } else {
      // Both turns are about the screen's own axes, so sideways spins the
      // model about the line up the middle of the screen and up-and-down tips
      // it towards you. Worked out afresh from where the drag started rather
      // than added on each time, so a slow drag and a fast one over the same
      // distance land in the same place.
      view.rot = turnBy(dragging.rot, dx * 0.01, dy * 0.01);
    }
    view.draw();
  });
  const stop = (event) => {
    if (!dragging) return;
    dragging = null;
    view._interacting = false;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    view.draw();
  };
  canvas.addEventListener('dblclick', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = canvas.getBoundingClientRect();
    const k = opts.scale() || 1;
    const index = view.pick((event.clientX - rect.left) / k, (event.clientY - rect.top) / k);
    if (index === null) { view.reset(); return; }
    view.setPivot(index);
    if (opts.onPivot) opts.onPivot(index);
  });
  canvas.addEventListener('pointerup', stop);
  canvas.addEventListener('pointercancel', stop);

  canvas.addEventListener('wheel', (event) => {
    event.preventDefault();
    // Without this the graph canvas underneath zooms as well.
    event.stopPropagation();
    view.zoom *= event.deltaY < 0 ? 1.12 : 1 / 1.12;
    view.zoom = Math.max(0.1, Math.min(12, view.zoom));
    view.draw();
  }, { passive: false });

  canvas.addEventListener('dblclick', (event) => {
    event.stopPropagation();
    view.reset();
  });

  return view;
}

/* --------------------------------------------------------- inspector tab */

const Viewer = {
  view: null,
  data: null,
  /* Where what is on screen came from, so it can be saved again. */
  path: '',

  init() {
    this.view = createStructureView(document.getElementById('viewer-canvas'), {
      empty: 'select a .pdb or .gro in the Files tab, or preview one in a node',
    });
    document.getElementById('viewer-style').addEventListener('change', (event) => {
      this.view.setStyle(event.target.value);
    });
    document.getElementById('viewer-color').addEventListener('change', (event) => {
      this.view.setColor(event.target.value);
    });
    document.getElementById('btn-viewer-save').addEventListener('click', () => {
      if (!this.path) { UI.toast('nothing loaded to save', 'warn'); return; }
      Panels.saveFile(this.path);
    });
    window.addEventListener('resize', () => this.draw());
  },

  show(data, path = '') {
    if (!data || data.error) { UI.toast((data && data.error) || 'nothing to show', 'error'); return; }
    this.data = data;
    this.path = path;
    this.view.show(data);
    document.getElementById('viewer-title').textContent = data.name;
    document.getElementById('viewer-info').textContent =
      `${describe(data)}  —  drag to turn, right-drag to slide, wheel to zoom, `
      + 'double-click an atom to turn around it';
  },

  clear() {
    this.data = null;
    this.path = '';
    this.view.clear();
    document.getElementById('viewer-title').textContent = 'no structure loaded';
    document.getElementById('viewer-info').textContent = '';
  },

  draw() { if (this.view) this.view.draw(); },
};

/* The one-line summary under a picture, shared by the tab and the nodes. */
function describe(data) {
  return [
    `${data.n_atoms.toLocaleString()} atoms`,
    data.decimated ? `showing ${data.n_shown.toLocaleString()}` : null,
    data.chains && data.chains.length ? `chains ${data.chains.join(' ')}` : null,
    data.box ? `box ${data.box.map((v) => (v / 10).toFixed(1)).join(' × ')} nm` : null,
  ].filter(Boolean).join(' · ');
}

/* --------------------------------------------------- previews in a node */

/* The picture a "Preview structure" node draws in its own body.

   What it draws comes from a run: when the node finishes, its output port
   carries an absolute path and that path is fetched here. A node that has not
   run yet falls back to its own file parameter, so the node is also useful on
   its own, before anything has been executed. */
/* The node preview has no room for a hint, so it goes in the tooltip. */
const HOW_TO_LOOK = 'drag to turn, right-drag to slide, wheel to zoom, '
  + 'double-click an atom to turn around it';

const NodePreview = {
  /* node id -> { view, caption, canvas } for the elements currently on screen. */
  views: new Map(),
  DEFAULT_SIZE: [300, 190],
  MIN_SIZE: [236, 110],
  MAX_SIZE: [900, 700],

  /* What this node draws. Four kinds now: a structure, a structure that
     moves, a curve, and dssp's residue-by-frame picture. They share the
     plumbing -- a path, a fetch, a canvas, a caption -- and differ only in
     which reader is called and what is drawn with the result. */
  kindOf(node) {
    const def = Editor.defs[node.type];
    return (def && def.preview && def.preview.kind) || 'structure';
  },

  /* Build the block that goes into the node body. */
  build(node, def) {
    // The body is being rebuilt, so whatever was here is going away.
    this.detach(node.id);
    const kind = (def.preview && def.preview.kind) || 'structure';
    if (kind === 'plot' || kind === 'dssp') return this.buildFlat(node, kind);
    return this.buildSpatial(node, def, kind);
  },

  /* A curve or a dssp map: a canvas, a caption, and nothing to turn. */
  buildFlat(node, kind) {
    const display = this.display(node);
    const host = UI.el('div', { class: 'node-preview' });
    const canvas = UI.el('canvas', { class: 'preview-canvas' });
    canvas.style.height = `${display.height}px`;
    const caption = UI.el('div', { class: 'preview-caption' });

    const bar = UI.el('div', { class: 'preview-bar' }, [
      UI.el('span', { class: 'spacer' }),
      UI.el('button', {
        class: 'mini', text: '⟳', title: 'Load the file again',
        onclick: (event) => { event.stopPropagation(); this.refresh(node, true); },
      }),
      UI.el('button', {
        class: 'mini', text: '⤢',
        title: kind === 'plot' ? 'Open in the Plot tab' : 'Open in the Plot tab',
        onclick: (event) => { event.stopPropagation(); this.expand(node); },
      }),
      UI.el('button', {
        class: 'mini', text: '⤓', title: 'Save or download this file',
        onclick: (event) => {
          event.stopPropagation();
          const source = this.source(node);
          if (!source) { UI.toast('nothing to save yet — run the node', 'warn'); return; }
          Panels.saveFile(source);
        },
      }),
    ]);
    host.appendChild(bar);
    host.appendChild(canvas);
    host.appendChild(caption);

    const entry = { canvas, caption, node, kind, hover: null };
    this.views.set(node.id, entry);
    if (kind === 'plot') {
      canvas.addEventListener('mousemove', (event) => {
        const rect = canvas.getBoundingClientRect();
        const k = Editor.view.scale || 1;
        entry.hover = { x: (event.clientX - rect.left) / k,
                        y: (event.clientY - rect.top) / k };
        this.paint(node);
      });
      canvas.addEventListener('mouseleave', () => { entry.hover = null; this.paint(node); });
    }
    canvas.addEventListener('mousedown', (event) => event.stopPropagation());

    if (node.previewData) {
      caption.textContent = this.describeFlat(kind, node.previewData);
    } else if (node.previewError) {
      caption.textContent = node.previewError;
    } else {
      const source = this.source(node);
      caption.textContent = source ? 'loading…' : 'run the node, or set a file';
      if (source) this.refresh(node);
    }
    requestAnimationFrame(() => this.paint(node));
    return host;
  },

  describeFlat(kind, data) {
    if (!data) return '';
    if (data.error) return data.error;
    if (kind === 'dssp') return dsspSummary(data);
    const rows = data.n_rows || 0;
    const shown = data.stride > 1 ? ` (every ${data.stride}th)` : '';
    return `${data.series.length} series, ${rows} rows${shown}`;
  },

  /* Draw whatever this node holds, without fetching anything. */
  paint(node) {
    const entry = this.views.get(node.id);
    if (!entry || !entry.canvas) return;
    if (entry.kind === 'dssp') {
      drawDssp(entry.canvas, node.previewData,
               { compact: true, empty: node.previewError || 'run the node' });
    } else if (entry.kind === 'plot') {
      drawPlot(entry.canvas, node.previewData,
               { compact: true, hover: entry.hover,
                 empty: node.previewError || 'run the node, or set a file' });
    }
  },

  buildSpatial(node, def, kind) {
    const display = this.display(node);
    const host = UI.el('div', { class: 'node-preview' });

    const styleSelect = UI.el('select', { class: 'mini' });
    for (const value of ['auto', 'points', 'trace', 'both']) {
      styleSelect.appendChild(UI.el('option', { value, text: value }));
    }
    styleSelect.value = display.style;
    styleSelect.addEventListener('change', () => {
      display.style = styleSelect.value;
      const entry = this.views.get(node.id);
      if (entry) entry.view.setStyle(display.style);
      Editor.mark(`draw ${node.title} as ${display.style}`, `display:${node.id}`);
      Editor.changed();
    });

    const colorSelect = UI.el('select', { class: 'mini' });
    for (const [value, text] of [['element', 'element'], ['chain', 'chain'], ['depth', 'depth'],
                                 ['bfactor', 'conservation / B-factor']]) {
      colorSelect.appendChild(UI.el('option', { value, text }));
    }
    colorSelect.value = display.color;
    colorSelect.addEventListener('change', () => {
      display.color = colorSelect.value;
      const entry = this.views.get(node.id);
      if (entry) entry.view.setColor(display.color);
      Editor.mark(`colour ${node.title} by ${display.color}`, `display:${node.id}`);
      Editor.changed();
    });

    const bar = UI.el('div', { class: 'preview-bar' }, [
      styleSelect,
      colorSelect,
      UI.el('span', { class: 'spacer' }),
      UI.el('button', {
        class: 'mini', text: '⟳', title: 'Load the file again',
        onclick: (event) => { event.stopPropagation(); this.refresh(node, true); },
      }),
      UI.el('button', {
        class: 'mini', text: '⤢', title: 'Open in the Viewer tab',
        onclick: (event) => { event.stopPropagation(); this.expand(node); },
      }),
      UI.el('button', {
        class: 'mini', text: '⤓', title: 'Save or download this structure',
        onclick: (event) => {
          event.stopPropagation();
          const source = this.source(node);
          if (!source) { UI.toast('nothing to save yet — run the node', 'warn'); return; }
          Panels.saveFile(source);
        },
      }),
    ]);
    for (const control of [styleSelect, colorSelect]) {
      control.addEventListener('mousedown', (event) => event.stopPropagation());
    }

    const canvas = UI.el('canvas', { class: 'preview-canvas' });
    canvas.style.height = `${display.height}px`;
    const caption = UI.el('div', { class: 'preview-caption' });

    host.appendChild(bar);
    host.appendChild(canvas);
    host.appendChild(caption);

    const view = createStructureView(canvas, {
      empty: 'not previewed yet',
      minHeight: display.height,
      scale: () => Editor.view.scale,
    });
    view.style = display.style;
    view.colorBy = display.color;
    const entry = { view, canvas, caption, node, kind };
    this.views.set(node.id, entry);

    if (kind === 'trajectory') {
      const slider = UI.el('input', { class: 'preview-frames', type: 'range',
                                      min: '0', max: '0', value: '0', step: '1' });
      const play = UI.el('button', { class: 'mini', text: '▶', title: 'Play' });
      const counter = UI.el('span', { class: 'preview-frame-no', text: '—' });
      const update = () => {
        counter.textContent = view.data && view.data.frames
          ? `${view.frame + 1}/${view.data.frames.length}` : '—';
        slider.value = String(view.frame || 0);
      };
      slider.addEventListener('input', () => {
        entry.stop();
        view.setFrame(Number(slider.value));
        update();
      });
      play.addEventListener('click', (event) => {
        event.stopPropagation();
        if (entry.timer) { entry.stop(); return; }
        const frames = view.data && view.data.frames;
        if (!frames || frames.length < 2) return;
        play.textContent = '❚❚';
        play.title = 'Pause';
        entry.timer = setInterval(() => {
          view.setFrame((view.frame + 1) % frames.length);
          update();
        }, 90);
      });
      // A node body is rebuilt often and a forgotten interval keeps drawing to
      // a canvas nobody can see, so stopping is a method rather than a closure.
      entry.stop = () => {
        if (entry.timer) clearInterval(entry.timer);
        entry.timer = null;
        play.textContent = '▶';
        play.title = 'Play';
      };
      entry.frameControls = { slider, counter, update };
      for (const control of [slider, play]) {
        control.addEventListener('mousedown', (event) => event.stopPropagation());
      }
      bar.insertBefore(play, bar.firstChild);
      bar.insertBefore(slider, play.nextSibling);
      bar.insertBefore(counter, slider.nextSibling);
    }

    // The element is built fresh every time the node body is rebuilt, so the
    // picture has to be put back from what the node already knows.
    if (node.previewData) {
      view.show(node.previewData);
      caption.textContent = describe(node.previewData);
      caption.title = HOW_TO_LOOK;
    } else if (node.previewError) {
      view.clear(node.previewError);
      caption.textContent = node.previewError;
    } else {
      const source = this.source(node);
      caption.textContent = source ? 'loading…' : 'run the node, or set a file';
      if (source) this.refresh(node);
    }
    // Lay out first, draw second: the canvas has no width until it is in the DOM.
    requestAnimationFrame(() => view.draw());
    return host;
  },

  /* Per-node display state. Lives on the node, not in its parameters: what a
     picture looks like must never invalidate the cache and re-run the graph. */
  display(node) {
    if (!node.display) {
      node.display = {
        style: 'auto', color: 'element',
        width: this.DEFAULT_SIZE[0], height: this.DEFAULT_SIZE[1],
      };
    }
    return node.display;
  },

  /* Where the picture comes from: a finished run first, the node's own file
     parameter second. */
  source(node) {
    return App.normalisePath(node.previewPath || (node.params && node.params.path) || '');
  },

  /* Point a node at a file and draw it. */
  setPath(nodeId, path) {
    const node = Editor.nodes.get(nodeId);
    if (!node || !path || node.previewPath === path) return;
    node.previewPath = path;
    node.previewData = null;
    node.previewError = '';
    this.refresh(node);
  },

  /* Pull the previewed file out of a node's run outputs. */
  fromOutputs(nodeId, outputs) {
    const node = Editor.nodes.get(nodeId);
    if (!node || !outputs) return;
    const def = Editor.defs[node.type];
    if (!def || !def.preview) return;
    const port = outputs[def.preview.port];
    if (port && port.path) this.setPath(nodeId, port.path);
  },

  /* The file parameter changed, so whatever a run put there is stale. */
  invalidate(node) {
    node.previewPath = '';
    node.previewData = null;
    node.previewError = '';
    this.refresh(node);
  },

  async refresh(node, announce = false) {
    const source = this.source(node);
    const entry = this.views.get(node.id);
    if (!source) {
      node.previewData = null;
      node.previewError = '';
      if (entry) {
        entry.caption.textContent = 'run the node, or set a file';
        if (entry.view) entry.view.clear('run the node, or set a file');
        else this.paint(node);
      }
      return;
    }
    if (entry) entry.caption.textContent = 'loading…';
    const kind = this.kindOf(node);
    const read = { plot: API.xvg, dssp: API.dssp,
                   trajectory: API.trajectory }[kind] || API.structure;
    try {
      const data = await read(source);
      if (data.error) throw new Error(data.error);
      node.previewData = data;
      node.previewError = '';
      const current = this.views.get(node.id);
      if (current && (kind === 'plot' || kind === 'dssp')) {
        current.caption.textContent = this.describeFlat(kind, data);
        current.caption.title = source;
        this.paint(node);
      } else if (current) {
        current.view.show(data);
        current.view.setStyle(this.display(node).style);
        current.view.setColor(this.display(node).color);
        current.caption.textContent = describe(data);
        current.caption.title = `${source}\n${HOW_TO_LOOK}`;
        if (current.frameControls) {
          const frames = (data.frames || []).length;
          current.frameControls.slider.max = String(Math.max(0, frames - 1));
          current.frameControls.update();
        }
      }
      if (announce) UI.toast(`${data.name}: ${describe(data)}`, 'ok');
    } catch (err) {
      // A remembered preview outlives the run directory it points at, and the
      // server's bare "not a file" does not explain which file, or why.
      const name = source.split('/').pop();
      const message = /^not a file$/i.test(err.message)
        ? `${name} is not there any more` : `${name}: ${err.message}`;
      node.previewData = null;
      node.previewError = message;
      const current = this.views.get(node.id);
      if (current && current.view) {
        current.view.clear(message);
        current.caption.textContent = message;
        current.caption.title = source;
      } else if (current) {
        current.caption.textContent = message;
        current.caption.title = source;
        this.paint(node);
      }
    }
  },

  expand(node) {
    if (!node.previewData) { this.refresh(node, true); return; }
    const kind = this.kindOf(node);
    if (kind === 'plot') {
      App.activateTab('plot');
      Plot.show(node.previewData);
      return;
    }
    if (kind === 'dssp') {
      // The Plot tab draws curves, and a dssp file is a picture; the counts
      // output is the curve, so send them there rather than showing nothing.
      App.activateTab('plot');
      Plot.show({ ...node.previewData, x: node.previewData.series.length
        ? node.previewData.series[0].y.map((_, i) => i) : [],
        xlabel: 'frame', ylabel: 'fraction of residues',
        stats: (node.previewData.summary || []).map((s) => ({
          label: s.label, mean: s.mean, sd: 0, min: 0, max: 1 })) });
      return;
    }
    App.activateTab('viewer');
    Viewer.show(node.previewData, this.source(node));
  },

  /* Called from the node's resize grip. */
  resize(node, width, height) {
    const display = this.display(node);
    display.width = Math.round(Math.max(this.MIN_SIZE[0], Math.min(this.MAX_SIZE[0], width)));
    display.height = Math.round(Math.max(this.MIN_SIZE[1], Math.min(this.MAX_SIZE[1], height)));
    const entry = this.views.get(node.id);
    if (!entry) return;
    entry.canvas.style.height = `${display.height}px`;
    // A curve and a dssp map have no view to turn; they are redrawn from the
    // node's own data instead.
    if (entry.view) entry.view.draw(); else this.paint(node);
  },

  /* A node body is rebuilt often, and a forgotten playback timer keeps drawing
     into a canvas nobody can see. */
  detach(nodeId) {
    const entry = this.views.get(nodeId);
    if (entry && entry.stop) entry.stop();
    this.views.delete(nodeId);
  },
  detachAll() {
    for (const entry of this.views.values()) if (entry.stop) entry.stop();
    this.views.clear();
  },
};
