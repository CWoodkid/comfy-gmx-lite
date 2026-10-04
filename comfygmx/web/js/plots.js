/* Line plots for .xvg data, drawn straight onto a canvas.
   No plotting library: the shapes here are axes, polylines and a crosshair. */
'use strict';

const SERIES_COLORS = [
  '#4f9dd8', '#6fbf8b', '#d8a84f', '#d9705f', '#8a7fd0',
  '#4fb8c8', '#c88fd0', '#a8b84f', '#d0855f', '#7a95d0',
];

const Plot = {
  data: null,
  hover: null,

  init() {
    this.canvas = document.getElementById('plot-canvas');
    this.ctx = this.canvas.getContext('2d');
    this.canvas.addEventListener('mousemove', (event) => {
      const rect = this.canvas.getBoundingClientRect();
      this.hover = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      this.draw();
    });
    this.canvas.addEventListener('mouseleave', () => { this.hover = null; this.draw(); });
    window.addEventListener('resize', () => this.draw());
  },

  show(data) {
    this.data = data;
    document.getElementById('plot-title').textContent =
      `${data.name}${data.stride > 1 ? ` (every ${data.stride}th row)` : ''}`;
    this._legend();
    this._stats();
    this.draw();
  },

  clear() {
    this.data = null;
    document.getElementById('plot-title').textContent = 'no data loaded';
    document.getElementById('plot-legend').innerHTML = '';
    document.getElementById('plot-stats').innerHTML = '';
    this.draw();
  },

  _legend() {
    const box = document.getElementById('plot-legend');
    box.innerHTML = '';
    this.data.series.forEach((series, index) => {
      const swatch = UI.el('span', { class: 'legend-swatch' });
      swatch.style.background = SERIES_COLORS[index % SERIES_COLORS.length];
      box.appendChild(UI.el('span', { class: 'legend-item' }, [swatch, series.label]));
    });
  },

  _stats() {
    const box = document.getElementById('plot-stats');
    box.innerHTML = '';
    if (!this.data.stats || !this.data.stats.length) return;
    const rows = this.data.stats.map((stat) =>
      `${stat.label.padEnd(22).slice(0, 22)}  mean ${fmt(stat.mean)}  sd ${fmt(stat.sd)}`
      + `  min ${fmt(stat.min)}  max ${fmt(stat.max)}`);
    box.textContent = rows.join('\n');
  },

  draw() {
    drawPlot(this.canvas, this.data, { hover: this.hover });
  },

  asCsv() {
    if (!this.data) return '';
    const header = ['x'].concat(this.data.series.map((s) => s.label)).join(',');
    const rows = this.data.x.map((value, index) =>
      [value].concat(this.data.series.map((s) => s.y[index])).join(','));
    return [header].concat(rows).join('\n');
  },
};

/* The same curve, on the inspector's canvas or inside a node.

   Compact drops what a 300 px wide canvas has no room for -- axis titles and
   half the ticks -- rather than drawing the full thing and letting it collide
   with itself. The strip on the left for the numbers up the side is as wide
   as the longest of them needs: a potential energy of -623975.94 is ten
   characters, and in a fixed strip its first digits were cut off. */
function drawPlot(canvas, data, options = {}) {
  const { hover = null, compact = false,
          empty = 'select an .xvg in the Files tab' } = options;
  {
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#0d1014';
    ctx.fillRect(0, 0, width, height);

    if (!data || !data.series || !data.series.length) {
      ctx.fillStyle = '#626c7a';
      ctx.font = '12px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(data && data.error ? data.error : empty, width / 2, height / 2);
      return;
    }

    const pad = compact
      ? { left: 40, right: 8, top: 8, bottom: 18 }
      : { left: 58, right: 14, top: 12, bottom: 30 };
    const ticks = compact ? 3 : 5;
    const { x, series } = data;

    let yMin = Infinity;
    let yMax = -Infinity;
    for (const s of series) {
      for (const value of s.y) {
        if (value < yMin) yMin = value;
        if (value > yMax) yMax = value;
      }
    }
    if (!isFinite(yMin)) { yMin = 0; yMax = 1; }
    if (yMin === yMax) { yMin -= 0.5; yMax += 0.5; }
    const span = yMax - yMin;
    yMin -= span * 0.06;
    yMax += span * 0.06;
    const xMin = x[0];
    const xMax = x[x.length - 1] || 1;

    // The numbers up the side, measured in the font they are written in. The
    // axis title, in the Plot tab, stands to their left.
    ctx.font = compact ? '9px system-ui' : '10px system-ui';
    const yLabels = [];
    for (let i = 0; i <= ticks; i += 1) yLabels.push(fmt(yMin + (i / ticks) * (yMax - yMin)));
    const widest = Math.max(...yLabels.map((label) => ctx.measureText(label).width));
    const titleRoom = !compact && data.ylabel ? 22 : 2;
    pad.left = Math.max(pad.left, Math.ceil(widest) + 6 + titleRoom);
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    if (plotW < 20 || plotH < 20) return;

    const sx = (value) => pad.left + ((value - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (value) => pad.top + plotH - ((value - yMin) / (yMax - yMin || 1)) * plotH;

    // grid + ticks
    ctx.strokeStyle = '#21262f';
    ctx.fillStyle = '#8d97a5';
    ctx.font = compact ? '9px system-ui' : '10px system-ui';
    ctx.lineWidth = 1;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= ticks; i += 1) {
      const value = yMin + (i / ticks) * (yMax - yMin);
      const py = Math.round(sy(value)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(pad.left, py);
      ctx.lineTo(pad.left + plotW, py);
      ctx.stroke();
      ctx.fillText(yLabels[i], pad.left - 6, py);
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= ticks; i += 1) {
      const value = xMin + (i / ticks) * (xMax - xMin);
      const px = Math.round(sx(value)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(px, pad.top);
      ctx.lineTo(px, pad.top + plotH);
      ctx.stroke();
      const label = fmt(value);
      ctx.fillText(label, inside(px, ctx.measureText(label).width, width), pad.top + plotH + 6);
    }

    // axis labels
    ctx.fillStyle = '#626c7a';
    if (!compact && data.xlabel) {
      ctx.fillText(data.xlabel, pad.left + plotW / 2, height - 12);
    }
    if (!compact && data.ylabel) {
      ctx.save();
      ctx.translate(12, pad.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(data.ylabel, 0, 0);
      ctx.restore();
    }

    // series
    ctx.lineWidth = 1.4;
    series.forEach((s, index) => {
      ctx.strokeStyle = SERIES_COLORS[index % SERIES_COLORS.length];
      ctx.beginPath();
      for (let i = 0; i < s.y.length; i += 1) {
        const px = sx(x[i]);
        const py = sy(s.y[i]);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke();
    });

    // crosshair
    if (hover && hover.x > pad.left && hover.x < pad.left + plotW) {
      const fraction = (hover.x - pad.left) / plotW;
      const index = Math.max(0, Math.min(x.length - 1, Math.round(fraction * (x.length - 1))));
      const px = sx(x[index]);
      ctx.strokeStyle = '#3a434f';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(px, pad.top);
      ctx.lineTo(px, pad.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      const lines = [`x = ${fmt(x[index])}`];
      series.forEach((s, i) => {
        lines.push(`${s.label.slice(0, 20)} = ${fmt(s.y[index])}`);
        ctx.fillStyle = SERIES_COLORS[i % SERIES_COLORS.length];
        ctx.beginPath();
        ctx.arc(px, sy(s.y[index]), 3, 0, Math.PI * 2);
        ctx.fill();
      });

      ctx.font = '10px monospace';
      const boxW = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 12;
      const boxH = lines.length * 13 + 8;
      const bx = Math.min(px + 10, pad.left + plotW - boxW);
      const by = pad.top + 6;
      ctx.fillStyle = 'rgba(25,29,36,.94)';
      ctx.fillRect(bx, by, boxW, boxH);
      ctx.strokeStyle = '#2c333d';
      ctx.strokeRect(bx + 0.5, by + 0.5, boxW, boxH);
      ctx.fillStyle = '#d7dde5';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      lines.forEach((line, i) => ctx.fillText(line, bx + 6, by + 5 + i * 13));
    }
  }
}

/* Where to centre a number so that all of it is on the canvas: under its
   line, unless that would push it over an edge. */
function inside(centre, textWidth, canvasWidth) {
  const half = textWidth / 2;
  return Math.max(half, Math.min(canvasWidth - half, centre));
}

function fmt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return value.toExponential(2);
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(abs < 1 ? 4 : abs < 100 ? 3 : 2);
}


/* ------------------------------------------------------------------ dssp */

/* What gmx dssp assigns, and what each one looks like. Helices warm, sheets
   cold, everything loose grey -- so a fold that holds reads as bands of colour
   and one that comes apart reads as grey creeping in. */
const DSSP_COLORS = {
  H: '#d0567a',   // alpha helix
  G: '#e08bb0',   // 3-10 helix
  I: '#a3466a',   // pi helix
  P: '#c78fd0',   // polyproline
  E: '#4f9dd8',   // beta strand
  B: '#7fbde0',   // beta bridge
  T: '#6fbf8b',   // turn
  S: '#b58b2a',   // bend
  '~': '#2b313a', // loop
};

/* Residue up the side, time along the bottom, one pixel a residue-frame.

   Built as an ImageData at exactly matrix size and then scaled up, rather than
   as one fillRect per cell: a 600-frame run of a 300-residue protein is 180000
   cells, which is a slideshow drawn a rectangle at a time and instant drawn as
   a bitmap. */
function drawDssp(canvas, data, options = {}) {
  const { compact = false, empty = 'run the node to see the assignments' } = options;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.fillStyle = '#0d1014';
  ctx.fillRect(0, 0, width, height);

  if (!data || !data.frames || !data.frames.length) {
    ctx.fillStyle = '#626c7a';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(data && data.error ? data.error : empty, width / 2, height / 2);
    return;
  }

  const pad = compact
    ? { left: 30, right: 6, top: 6, bottom: 26 }
    : { left: 52, right: 16, top: 14, bottom: 48 };
  ctx.font = compact ? '9px system-ui' : '10px system-ui';
  const widest = ctx.measureText(String(data.n_residues)).width;
  pad.left = Math.max(pad.left, Math.ceil(widest) + 5 + 2);
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  if (plotW < 20 || plotH < 20) return;

  const frames = data.frames;
  const cols = frames.length;
  const rows = frames[0].length;
  const image = ctx.createImageData(cols, rows);
  const pixels = image.data;
  const rgb = {};
  for (const [code, hex] of Object.entries(DSSP_COLORS)) {
    rgb[code] = [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16),
                 parseInt(hex.slice(5, 7), 16)];
  }
  for (let c = 0; c < cols; c += 1) {
    const column = frames[c];
    for (let r = 0; r < rows; r += 1) {
      // Residue 1 at the bottom, the way a sequence is read up a plot.
      const colour = rgb[column[r]] || rgb['~'];
      const at = ((rows - 1 - r) * cols + c) * 4;
      pixels[at] = colour[0]; pixels[at + 1] = colour[1];
      pixels[at + 2] = colour[2]; pixels[at + 3] = 255;
    }
  }
  const tile = document.createElement('canvas');
  tile.width = cols; tile.height = rows;
  tile.getContext('2d').putImageData(image, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(tile, pad.left, pad.top, plotW, plotH);

  ctx.strokeStyle = '#2c333d';
  ctx.strokeRect(pad.left + 0.5, pad.top + 0.5, plotW - 1, plotH - 1);

  ctx.fillStyle = '#8d97a5';
  ctx.font = compact ? '9px system-ui' : '10px system-ui';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const ticks = compact ? 2 : 4;
  for (let i = 0; i <= ticks; i += 1) {
    const residue = Math.round(1 + (i / ticks) * (data.n_residues - 1));
    ctx.fillText(String(residue), pad.left - 5, pad.top + plotH - (i / ticks) * plotH);
  }
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i <= ticks; i += 1) {
    const frame = String(Math.round((i / ticks) * (data.n_frames - 1)));
    ctx.fillText(frame, inside(pad.left + (i / ticks) * plotW, ctx.measureText(frame).width, width),
                 pad.top + plotH + 4);
  }

  // The legend is the whole point -- a band of colour means nothing until you
  // know which colour is a helix.
  const swatchY = pad.top + plotH + (compact ? 14 : 22);
  let cursor = pad.left;
  ctx.textAlign = 'left';
  ctx.font = compact ? '9px system-ui' : '10px system-ui';
  for (const entry of (data.legend || [])) {
    if (entry.code === '~' && compact) continue;
    const label = compact ? entry.code : `${entry.code}  ${entry.label}`;
    const w = ctx.measureText(label).width + (compact ? 12 : 16);
    if (cursor + w > pad.left + plotW) break;
    ctx.fillStyle = DSSP_COLORS[entry.code] || '#8d97a5';
    ctx.fillRect(cursor, swatchY + 1, 8, 8);
    ctx.fillStyle = '#8d97a5';
    ctx.fillText(label, cursor + 11, swatchY);
    cursor += w;
  }
}

function dsspSummary(data) {
  if (!data || !data.summary) return '';
  const parts = data.summary
    .filter((s) => s.mean >= 0.005 && s.code !== '~')
    .sort((a, b) => b.mean - a.mean)
    .map((s) => `${s.label} ${(s.mean * 100).toFixed(0)}%`);
  return `${data.n_residues} residues, ${data.n_frames} frames — ${parts.join(', ')}`;
}


/* --------------------------------------------------------------- picture */

/* A picture file inside a node: as large as fits, in the middle, on the same
   dark ground as the plots. Its shape is kept, so nothing is cut off and
   nothing is stretched; a snowflake drawn squashed is not a snowflake. */
function drawPicture(canvas, data, options = {}) {
  const { empty = 'run the node' } = options;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#0d1014';
  ctx.fillRect(0, 0, width, height);
  if (!data || !data.image || !data.width || !data.height) {
    ctx.fillStyle = '#626c7a';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(data && data.error ? data.error : empty, width / 2, height / 2);
    return;
  }
  const scale = Math.min(width / data.width, height / data.height);
  const w = data.width * scale;
  const h = data.height * scale;
  ctx.drawImage(data.image, (width - w) / 2, (height - h) / 2, w, h);
}
