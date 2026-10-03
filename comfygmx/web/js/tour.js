/* The basics: a short tour of how to work this page with your hands.

   Pupils who grew up on phones and tablets know tapping and swiping, but not
   always what a mouse expects: that dragging means pressing, holding, moving
   and letting go, that the right button opens a menu, or that Ctrl+Z means
   holding one key while pressing another. A workshop found that out the hard
   way. So the page opens with ten slides, each with a small moving picture of
   one thing to do, drawn in the editor's own colours.

   The first slide asks whether a mouse or a touchpad is being used. The rest
   then show that device's moves, and the page takes the answer as its own
   setting (the same one as Settings > What you are pointing with), so a
   touchpad slides the canvas with two fingers from then on.

   When it opens by itself: the first time the page is opened in a browser
   tab, once that tab has nothing else to ask (the first-start setup window
   goes first). A reload in the same tab does not bring it back. "Don't show
   this at the start again" stops it for good in this browser. ? > Show the
   basics opens it at any time.

   The pictures are SVG, moved by SVG's own animation elements (<animate>,
   <animateTransform>, <animateMotion>). Every current browser plays them
   without any script running per frame, and a picture starts again from the
   beginning each time its slide is shown. Somebody who has asked the computer
   for less movement on screen (the "reduce motion" setting) sees each picture
   stopped at its most telling moment instead. */
'use strict';

/* --------------------------------------------------------------- pictures */
const TourArt = (() => {
  const INK = {
    bg: '#14171c', dot: '#262c36', body: '#1b1f26', edge: '#2c333d', title: '#eef2f6',
    text: '#d7dde5', dim: '#8d97a5', faint: '#626c7a', accent: '#4f9dd8', ok: '#6fbf8b',
    off: '#2a3039', rim: '#6a7584', key: '#262c36', panel: '#191d24', wheel: '#3a424d',
  };
  /* The title-bar colour of each kind of block, as the blocks themselves set
     it (`color` in comfygmx/nodes/*.py). */
  const KIND = {
    io: '#2f6b52', prep: '#3f6b8a', build: '#2b5d8a', run: '#8a4b2b', view: '#3f6d7d',
  };
  // The colour of a wire carrying this kind of file, from graph.js when it is there.
  const wire = (type) => (typeof PORT_COLORS !== 'undefined' && PORT_COLORS[type]) || INK.dim;

  /* -- timing. Every animation in one picture lasts the picture's length `d`
     and repeats, so they all stay in step. Moments are given as fractions of
     that length: 0.5 is halfway. */
  const T = (d, times) => `dur="${d}s" repeatCount="indefinite" keyTimes="${times.join(';')}"`;
  const ease = (n) => Array(n).fill('.45 0 .25 1').join(';');
  // A group travelling through points, slowing into each one.
  const travel = (d, points, times) => `<animateTransform attributeName="transform" type="translate" values="${points.map((p) => p.join(' ')).join(';')}" ${T(d, times)} calcMode="spline" keySplines="${ease(points.length - 1)}"/>`;
  // A value that jumps from one to the next at the given moments.
  const jumps = (attr, d, values, times) => `<animate attributeName="${attr}" values="${values.join(';')}" ${T(d, times)} calcMode="discrete"/>`;
  // A value that changes smoothly between the given moments.
  const glides = (attr, d, values, times) => `<animate attributeName="${attr}" values="${values.join(';')}" ${T(d, times)}/>`;
  // Seen only between two moments.
  const between = (d, from, to) => jumps('opacity', d, [0, 1, 0], [0, from, to]);
  // Fades in at the start of each round and out at its end, so that going
  // back to the beginning is not a jump.
  const rounds = (d, end = 0.9) => glides('opacity', d, [0, 1, 1, 0], [0, 0.05, end, 1]);

  /* -- the parts every picture is made of */
  const frame = (name, label, inner) => `<svg class="tour-art" viewBox="0 0 520 250" role="img" aria-label="${label}" xmlns="http://www.w3.org/2000/svg">
<defs><pattern id="tour-dots-${name}" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="${INK.dot}"/></pattern></defs>
<rect width="520" height="250" fill="${INK.bg}"/>
${inner}
</svg>`;
  const dots = (name, x = 0, y = 0, w = 520, h = 250) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#tour-dots-${name})"/>`;

  /* A block as the canvas draws it: a coloured title bar, two lines standing
     for its settings, and dots on its edges for what goes in (left) and what
     comes out (right). `anim` goes inside its group and moves it. */
  const block = ({ x, y, w = 150, h = 74, title, kind, ins = [], outs = [], anim = '', extra = '' }) => {
    const sockets = (list, cx) => list.map((type, i) => `<circle cx="${cx}" cy="${36 + i * 16}" r="5" fill="${wire(type)}" stroke="${INK.bg}" stroke-width="1.5"/>`).join('');
    return `<g transform="translate(${x},${y})">${anim}
<rect width="${w}" height="${h}" rx="7" fill="${INK.body}" stroke="${INK.edge}"/>
<path d="M0,22 V7 A7,7 0 0 1 7,0 H${w - 7} A7,7 0 0 1 ${w},7 V22 Z" fill="${KIND[kind]}"/>
<text x="9" y="15" font-size="11" fill="${INK.title}">${title}</text>
<rect x="14" y="${h - 30}" width="${Math.round(w * 0.55)}" height="5" rx="2.5" fill="${INK.edge}"/>
<rect x="14" y="${h - 18}" width="${Math.round(w * 0.35)}" height="5" rx="2.5" fill="${INK.edge}"/>
${sockets(ins, 0)}${sockets(outs, w)}${extra}</g>`;
  };
  // A rectangle hugging a block, for the blue outline of a selected one and
  // the glow of a running one.
  const hug = (x, y, w, h, colour, width, anim) => `<rect x="${x - 3}" y="${y - 3}" width="${w + 6}" height="${h + 6}" rx="9" fill="none" stroke="${colour}" stroke-width="${width}" opacity="0">${anim}</rect>`;

  // The mouse pointer, its tip at the group's origin.
  const ARROW = `<path d="M0,0 L0,18 L4.8,13.6 L8,21 L11,19.8 L7.9,12.6 L14,12.6 Z" fill="#ffffff" stroke="#111111" stroke-width="1.2" stroke-linejoin="round"/>`;
  const pointer = (anim, extra = '') => `<g transform="translate(-100,-100)">${anim}${extra}${ARROW}</g>`;
  // A ring spreading from the pointer's tip at the moment a button goes down.
  const ring = (d, at) => {
    const t = [0, at, at, Math.min(at + 0.12, 1), 1];
    return `<circle r="0" fill="none" stroke="${INK.accent}" stroke-width="2" opacity="0">${glides('r', d, [0, 0, 3, 15, 15], t)}${glides('opacity', d, [0, 0, 0.9, 0, 0], t)}</circle>`;
  };
  // A part that is lit blue while it is held down, at each pair of moments.
  const held = (d, spans, idle = INK.off) => {
    const values = [idle];
    const times = [0];
    for (const [from, to] of spans) {
      values.push(INK.accent, idle);
      times.push(from, to);
    }
    return jumps('fill', d, values, times);
  };

  /* The mouse in the corner, with whichever part is in use lit up. */
  const mouse = ({ left = '', right = '', wheel = '', say = '' } = {}) => `<g transform="translate(472,172)">
<rect width="34" height="54" rx="17" fill="#20252d" stroke="${INK.rim}" stroke-width="1.4"/>
<path d="M17,1.4 A15.6,15.6 0 0 0 1.4,17 V22 H17 Z" fill="${INK.off}">${left}</path>
<path d="M17,1.4 A15.6,15.6 0 0 1 32.6,17 V22 H17 Z" fill="${INK.off}">${right}</path>
<path d="M17,1.4 V22 M1.4,22 H32.6" stroke="${INK.rim}" stroke-width="1.2" fill="none"/>
<rect x="14.5" y="6" width="5" height="11" rx="2.5" fill="${INK.wheel}" stroke="${INK.rim}">${wheel}</rect>
${say}</g>`;
  /* The touchpad in the corner, with fingertips on it. */
  const pad = (tips, say = '') => `<g transform="translate(426,176)">
<rect width="80" height="52" rx="8" fill="#20252d" stroke="${INK.rim}" stroke-width="1.4"/>
${tips}${say}</g>`;
  // One fingertip: where it is over time, and the moments it touches the pad.
  const tip = (d, xs, ys, times, touching) => `<circle cx="${xs[0]}" cy="${ys[0]}" r="6" fill="${INK.text}" opacity="0">${glides('cx', d, xs, times)}${glides('cy', d, ys, times)}${jumps('opacity', d, [0, 0.9, 0], [0, touching[0], touching[1]])}</circle>`;
  // A few words beside the mouse or the touchpad, naming what is in use.
  const aside = (text, d, from, to, x = -8, y = 31) => `<text x="${x}" y="${y}" font-size="11" fill="${INK.dim}" stroke="${INK.bg}" stroke-width="4" paint-order="stroke" text-anchor="end" opacity="0">${text}${between(d, from, to)}</text>`;
  /* A key on the keyboard. `press` lights it while it is held. */
  const key = (label, x, y, w, press = '') => `<g transform="translate(${x},${y})">
<rect width="${w}" height="26" rx="5" fill="${INK.key}" stroke="${INK.rim}" stroke-width="1.2">${press}</rect>
<text x="${w / 2}" y="17.5" font-size="11.5" fill="${INK.text}" text-anchor="middle">${label}</text></g>`;
  // The numbered steps written across the top of a picture, one at a time.
  const step = (text, d, from, to, x = 260, y = 36) => `<text x="${x}" y="${y}" font-size="15" font-weight="600" fill="${INK.accent}" stroke="${INK.bg}" stroke-width="5" paint-order="stroke" text-anchor="middle" opacity="0">${text}${between(d, from, to)}</text>`;
  const arrowRight = (x1, x2, y) => `<path d="M${x1},${y} H${x2} M${x2 - 8},${y - 6} L${x2},${y} L${x2 - 8},${y + 6}" stroke="${INK.faint}" stroke-width="1.5" stroke-dasharray="4 5" fill="none"/>`;

  /* ------------------------------------------------------------- the slides */
  const pictures = {
    // Two small pictures for the first slide's two buttons.
    mouseChoice: () => `<svg class="tour-choice-art" viewBox="0 0 120 90" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
<path d="M60,18 C60,8 70,6 82,4" stroke="${INK.rim}" stroke-width="2" fill="none"/>
<rect x="43" y="18" width="34" height="58" rx="17" fill="#20252d" stroke="${INK.rim}" stroke-width="1.6"/>
<path d="M60,19.5 A15.5,15.5 0 0 0 44.5,35 V42 H60 Z" fill="${INK.accent}"/>
<path d="M60,19.5 A15.5,15.5 0 0 1 75.5,35 V42 H60 Z" fill="${INK.off}"/>
<path d="M60,19.5 V42 M44.5,42 H75.5" stroke="${INK.rim}" stroke-width="1.2" fill="none"/>
<rect x="57.5" y="24" width="5" height="11" rx="2.5" fill="${INK.wheel}" stroke="${INK.rim}"/></svg>`,
    padChoice: () => `<svg class="tour-choice-art" viewBox="0 0 120 90" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
<rect x="8" y="8" width="104" height="74" rx="8" fill="#20252d" stroke="${INK.rim}" stroke-width="1.6"/>
${[16, 25, 34].map((y) => `<rect x="16" y="${y}" width="88" height="6" rx="2" fill="${INK.off}"/>`).join('')}
<rect x="38" y="46" width="44" height="28" rx="4" fill="${INK.bg}" stroke="${INK.rim}"/>
<circle cx="54" cy="60" r="5" fill="${INK.text}"/><circle cx="66" cy="60" r="5" fill="${INK.text}"/></svg>`,

    click: (kind) => {
      const d = 4;
      const panel = `<g transform="translate(372,18)">
<rect width="132" height="146" rx="6" fill="${INK.panel}" stroke="${INK.edge}"/>
<text x="12" y="18" font-size="10" fill="${INK.accent}">Log</text>
<text x="42" y="18" font-size="10" fill="${INK.faint}">Files</text>
<text x="76" y="18" font-size="10" fill="${INK.faint}">Viewer</text>
<rect x="8" y="23" width="28" height="2" fill="${INK.accent}"/>
<path d="M0,30 H132" stroke="${INK.edge}"/>
<text x="12" y="48" font-size="10" fill="${INK.faint}" opacity="1">no block selected${jumps('opacity', d, [1, 0, 1], [0, 0.46, 0.94])}</text>
<g opacity="0">${between(d, 0.46, 0.94)}<text x="12" y="48" font-size="11" fill="${INK.text}">Solvate</text>
${[[60, 100], [72, 84], [84, 96], [96, 60], [108, 90], [120, 70]].map(([y, w]) => `<rect x="12" y="${y}" width="${w}" height="5" rx="2.5" fill="${INK.edge}"/>`).join('')}</g></g>`;
      const hand = kind === 'trackpad'
        ? pad(tip(d, [40, 40], [26, 26], [0, 1], [0.44, 0.52]), aside('tap once', d, 0.44, 0.62, -8, 30))
        : mouse({ left: held(d, [[0.44, 0.52]]), say: aside('left button', d, 0.44, 0.62) });
      return frame('click', 'The pointer clicks a block, the block gets a blue outline, and the panel on the right shows its log', `${dots('click')}
<text x="16" y="28" font-size="12" fill="${INK.dim}">click = press once and let go</text>
${block({ x: 120, y: 70, w: 176, h: 88, title: 'Solvate', kind: 'build', ins: ['structure', 'topology'], outs: ['structure', 'topology'] })}
${hug(120, 70, 176, 88, INK.accent, 2, between(d, 0.46, 0.94))}
${panel}${hand}
${pointer(travel(d, [[330, 214], [330, 214], [214, 120], [214, 120]], [0, 0.08, 0.38, 1]) + rounds(d), ring(d, 0.44))}`);
    },

    drag: (kind) => {
      const d = 5;
      const hand = kind === 'trackpad'
        ? pad(tip(d, [40, 40], [26, 26], [0, 1], [0.29, 0.74]), aside('press it down and keep pressing', d, 0.29, 0.74, -8, 30))
        : mouse({ left: held(d, [[0.29, 0.74]]), say: aside('keep the left button down', d, 0.29, 0.74) });
      return frame('drag', 'The pointer presses on the title bar of a block, holds, moves it to the right and lets go', `${dots('drag')}
${arrowRight(110, 330, 186)}
${block({ x: 56, y: 96, w: 160, h: 74, title: 'Run MD (mdrun)', kind: 'run', ins: ['tpr'], outs: ['traj', 'structure'], anim: travel(d, [[56, 96], [56, 96], [236, 96], [236, 96]], [0, 0.34, 0.7, 1]) + rounds(d) })}
${step('1  Press and hold', d, 0.29, 0.46)}${step('2  Move', d, 0.46, 0.72)}${step('3  Let go', d, 0.74, 0.92)}
${hand}
${pointer(travel(d, [[340, 214], [150, 107], [150, 107], [330, 107], [330, 107]], [0, 0.24, 0.34, 0.7, 1]) + rounds(d), ring(d, 0.29))}`);
    },

    connect: (kind) => {
      const d = 5;
      const path = 'M174,96 C237,96 237,136 300,136';
      const hand = kind === 'trackpad'
        ? pad(tip(d, [40, 40], [26, 26], [0, 1], [0.24, 0.68]), aside('press it down and keep pressing', d, 0.24, 0.68, -8, 30))
        : mouse({ left: held(d, [[0.24, 0.68]]), say: aside('keep the left button down', d, 0.24, 0.68) });
      return frame('connect', 'The pointer drags a wire from the dot on the right of one block to a dot of the same colour on the left of another', `${dots('connect')}
${block({ x: 24, y: 60, w: 150, h: 74, title: 'Load structure', kind: 'io', outs: ['structure'] })}
${block({ x: 300, y: 100, w: 150, h: 74, title: 'Clean structure', kind: 'prep', ins: ['structure'], outs: ['structure'] })}
<path d="${path}" pathLength="1" stroke="${wire('structure')}" stroke-width="2.5" fill="none" stroke-dasharray="1 1" stroke-dashoffset="1">${glides('stroke-dashoffset', d, [1, 1, 0, 0], [0, 0.26, 0.66, 1])}${glides('opacity', d, [1, 1, 0], [0, 0.9, 1])}</path>
<circle cx="300" cy="136" r="9" fill="none" stroke="${INK.accent}" stroke-width="2" opacity="0">${between(d, 0.26, 0.68)}</circle>
${step('1  Press on the dot', d, 0.22, 0.32)}${step('2  Move to a dot of the same colour', d, 0.32, 0.66)}${step('3  Let go', d, 0.68, 0.9)}
${hand}
<g>${travel(d, [[160, 120], [160, 120], [0, 0], [0, 0]], [0, 0.04, 0.22, 1])}${rounds(d)}<g><animateMotion path="${path}" keyPoints="0;0;1;1" keyTimes="0;0.26;0.66;1" calcMode="linear" dur="${d}s" repeatCount="indefinite"/>${ring(d, 0.24)}${ARROW}</g></g>`);
    },

    pan: (kind) => {
      const d = 6;
      const times = [0, 0.3, 0.52, 0.62, 0.86, 1];
      const world = `<g>${travel(d, [[0, 0], [0, 0], [-120, -26], [-120, -26], [0, 0], [0, 0]], times)}
${dots('pan', -320, -220, 1200, 700)}
${block({ x: 40, y: 64, w: 150, h: 74, title: 'Load structure', kind: 'io', outs: ['structure'] })}
<path d="M190,100 C220,100 220,132 250,132" stroke="${wire('structure')}" stroke-width="2.5" fill="none"/>
${block({ x: 250, y: 96, w: 150, h: 74, title: 'Solvate', kind: 'build', ins: ['structure', 'topology'], outs: ['structure'] })}
${block({ x: 470, y: 40, w: 150, h: 74, title: 'Add ions', kind: 'build', ins: ['structure'], outs: ['structure'] })}</g>`;
      if (kind === 'trackpad') {
        return frame('pan', 'Two fingers slide on the touchpad, and the whole canvas slides with them', `${world}
${step('Slide two fingers', d, 0.26, 0.9)}
${pad(tip(d, [30, 30, 16, 16, 30, 30], [26, 26, 20, 20, 26, 26], times, [0.26, 0.9]) + tip(d, [50, 50, 36, 36, 50, 50], [26, 26, 20, 20, 26, 26], times, [0.26, 0.9]), aside('two fingers', d, 0.26, 0.9, -8, 30))}
${pointer(travel(d, [[330, 200], [330, 200]], [0, 1]))}`);
      }
      return frame('pan', 'The Space bar is held down while the pointer drags, and the whole canvas moves with it', `${world}
${step('1  Hold down Space', d, 0.2, 0.3)}${step('2  Drag', d, 0.3, 0.88)}${step('3  Let go', d, 0.88, 0.96)}
${key('Space', 18, 212, 120, held(d, [[0.2, 0.92]], INK.key))}
${mouse({ left: held(d, [[0.3, 0.53], [0.62, 0.87]]), say: aside('left button', d, 0.3, 0.87) })}
${pointer(travel(d, [[330, 200], [330, 200], [210, 174], [210, 174], [330, 200], [330, 200]], times) + rounds(d, 0.92))}`);
    },

    zoom: (kind) => {
      const d = 6;
      const times = [0, 0.15, 0.42, 0.55, 0.82, 1];
      const world = `<g transform="translate(262,128)"><g><animateTransform attributeName="transform" type="scale" values="1;1;1.5;1.5;1;1" ${T(d, times)} calcMode="spline" keySplines="${ease(5)}"/><g transform="translate(-262,-128)">
${dots('zoom', -260, -260, 1040, 770)}
${block({ x: 70, y: 70, w: 150, h: 74, title: 'Load structure', kind: 'io', outs: ['structure'] })}
<path d="M220,106 C250,106 250,150 280,150" stroke="${wire('structure')}" stroke-width="2.5" fill="none"/>
${block({ x: 280, y: 114, w: 150, h: 74, title: 'Solvate', kind: 'build', ins: ['structure', 'topology'], outs: ['structure'] })}</g></g></g>`;
      if (kind === 'trackpad') {
        return frame('zoom', 'Two fingers move apart on the touchpad and the canvas grows, then they move together and it shrinks', `${world}
${step('Fingers apart: zoom in', d, 0.15, 0.45)}${step('Fingers together: zoom out', d, 0.55, 0.85)}
${pad(tip(d, [34, 34, 14, 14, 34, 34], [26, 26, 26, 26, 26, 26], times, [0.12, 0.86]) + tip(d, [46, 46, 66, 66, 46, 46], [26, 26, 26, 26, 26, 26], times, [0.12, 0.86]))}
${pointer(travel(d, [[262, 128], [262, 128]], [0, 1]))}`);
      }
      return frame('zoom', 'The mouse wheel rolls forward and the canvas grows around the pointer, then it rolls back and the canvas shrinks', `${world}
${step('Roll the wheel forward: zoom in', d, 0.15, 0.45)}${step('Roll it back: zoom out', d, 0.55, 0.85)}
${mouse({ wheel: held(d, [[0.15, 0.42], [0.55, 0.82]], INK.wheel), say: aside('▲ forward', d, 0.15, 0.42, -8, 14) + aside('▼ back', d, 0.55, 0.82, -8, 14) })}
${pointer(travel(d, [[262, 128], [262, 128]], [0, 1]))}`);
    },

    edit: (kind) => {
      const d = 8;
      const tap = kind === 'trackpad';
      const palette = `<g>
<rect x="10" y="12" width="140" height="176" rx="6" fill="${INK.panel}" stroke="${INK.edge}"/>
<text x="22" y="34" font-size="9" fill="${INK.dim}" letter-spacing="1">BUILD SYSTEM</text>
<rect x="14" y="71" width="132" height="22" rx="4" fill="#26303c" opacity="0">${between(d, 0.17, 0.3)}</rect>
${[['Define box', 58], ['Solvate', 86], ['Add ions', 114], ['Ice crystal', 142]].map(([name, y]) => `<rect x="16" y="${y - 12}" width="3" height="18" fill="${KIND.build}"/><text x="26" y="${y + 1}" font-size="11" fill="${INK.text}">${name}</text>`).join('')}</g>`;
      const hand = tap
        ? pad(tip(d, [40, 40], [26, 26], [0, 1], [0.17, 0.24]) + tip(d, [40, 40], [26, 26], [0, 1], [0.42, 0.49]), aside('tap', d, 0.17, 0.24, -8, 30) + aside('tap', d, 0.42, 0.49, -8, 30))
        : mouse({ left: held(d, [[0.17, 0.24], [0.42, 0.49]]) });
      return frame('edit', 'A name in the list is clicked and its block appears; the block is clicked, the Delete key removes it, and Ctrl and Z bring it back', `${dots('edit')}
${palette}
<g opacity="0">${glides('opacity', d, [0, 0, 1, 1, 0, 0, 1, 1, 0], [0, 0.19, 0.23, 0.555, 0.6, 0.735, 0.775, 0.94, 1])}
${block({ x: 250, y: 64, w: 170, h: 86, title: 'Solvate', kind: 'build', ins: ['structure', 'topology'], outs: ['structure', 'topology'] })}
${hug(250, 64, 170, 86, INK.accent, 2, jumps('opacity', d, [0, 1, 0, 1, 0], [0, 0.42, 0.58, 0.76, 0.94]))}</g>
${step('1  Click a name in the list', d, 0.15, 0.3, 335)}${step('2  Click the block', d, 0.4, 0.52, 335)}${step('3  Delete removes it', d, 0.54, 0.66, 335)}${step('4  Ctrl + Z brings it back', d, 0.68, 0.92, 335)}
<text x="209" y="205" font-size="10" fill="${INK.dim}" text-anchor="middle">remove</text>
<text x="325" y="205" font-size="10" fill="${INK.dim}" text-anchor="middle">undo</text>
${key('Delete', 176, 212, 66, held(d, [[0.54, 0.6]], INK.key))}
${key('Ctrl', 290, 212, 50, held(d, [[0.68, 0.8]], INK.key))}
<text x="350" y="230" font-size="13" fill="${INK.dim}" text-anchor="middle">+</text>
${key('Z', 360, 212, 30, held(d, [[0.72, 0.78]], INK.key))}
${hand}
${pointer(travel(d, [[340, 222], [64, 84], [64, 84], [330, 120], [330, 120]], [0, 0.14, 0.2, 0.38, 1]) + rounds(d, 0.92), ring(d, 0.17) + ring(d, 0.42))}`);
    },

    menu: (kind) => {
      const d = 6;
      const menu = `<g transform="translate(152,66)" opacity="0">${between(d, 0.34, 0.68)}
<rect width="196" height="104" rx="6" fill="${INK.body}" stroke="#3a434f"/>
<rect x="4" y="56" width="188" height="22" rx="4" fill="#2d6d9c" opacity="0">${between(d, 0.55, 0.68)}</rect>
${['Rename…', 'Inputs…', 'Switch this chunk back on', 'Select contents'].map((label, i) => `<text x="12" y="${22 + i * 24}" font-size="11" fill="${INK.text}">${label}</text>`).join('')}</g>`;
      const box = `<g>
<rect x="30" y="52" width="300" height="170" rx="8" fill="rgba(255,255,255,0.02)" stroke="${INK.rim}" stroke-dasharray="6 4">${jumps('opacity', d, [1, 0, 1], [0, 0.7, 0.95])}</rect>
<rect x="30" y="52" width="300" height="170" rx="8" fill="rgba(138,127,208,0.06)" stroke="#8a7fd0" opacity="0">${between(d, 0.7, 0.95)}</rect>
<path d="M30,76 V60 A8,8 0 0 1 38,52 H322 A8,8 0 0 1 330,60 V76 Z" fill="#3a3550"/>
<text x="40" y="68" font-size="11" fill="${INK.title}">3. Extra: the same with salt</text>
<g opacity="0.4">${jumps('opacity', d, [0.4, 1, 0.4], [0, 0.7, 0.95])}
${block({ x: 46, y: 96, w: 130, h: 64, title: 'Ice crystal', kind: 'build', outs: ['structure'] })}
${block({ x: 190, y: 134, w: 126, h: 64, title: 'Run MD (mdrun)', kind: 'run', ins: ['tpr'] })}</g></g>`;
      const hand = kind === 'trackpad'
        ? pad(tip(d, [32, 32], [26, 26], [0, 1], [0.32, 0.4]) + tip(d, [48, 48], [26, 26], [0, 1], [0.32, 0.4]) + tip(d, [40, 40], [26, 26], [0, 1], [0.62, 0.67]),
          aside('tap with two fingers', d, 0.32, 0.5, -8, 30) + aside('tap', d, 0.62, 0.76, -8, 30))
        : mouse({ right: held(d, [[0.32, 0.4]]), left: held(d, [[0.62, 0.67]]), say: aside('right button', d, 0.32, 0.5) + aside('left button', d, 0.62, 0.76) });
      return frame('menu', 'The right button on the title bar of a switched-off box opens a menu; choosing Switch this chunk back on switches the box on', `${dots('menu')}
${box}${menu}
${step('1  Right-click', d, 0.3, 0.46, 432, 60)}${step('2  Choose a line', d, 0.46, 0.7, 432, 60)}${step('Switched on', d, 0.7, 0.92, 432, 60)}
${hand}
${pointer(travel(d, [[360, 220], [150, 64], [150, 64], [226, 134], [226, 134]], [0, 0.26, 0.44, 0.56, 1]) + rounds(d, 0.92), ring(d, 0.32) + ring(d, 0.62))}`);
    },

    run: (kind) => {
      const d = 8;
      // Blue while a block works, then green once it is done.
      const states = (x, y, w, h, from, to) => hug(x, y, w, h, INK.accent, 3, between(d, from, to)) + hug(x, y, w, h, INK.ok, 2, between(d, to, 0.97));
      const atoms = [[-30, -10], [-14, -22], [4, -16], [18, -26], [30, -8], [16, 4], [26, 20], [6, 18], [-10, 8], [-26, 14], [-6, -4]];
      const bonds = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [5, 7], [7, 8], [8, 9], [8, 10], [10, 2], [10, 0]];
      const molecule = `<g opacity="0">${between(d, 0.6, 0.97)}<g transform="translate(428,116)"><animateTransform attributeName="transform" type="rotate" values="0;0;80;80" keyTimes="0;0.72;0.88;1" dur="${d}s" repeatCount="indefinite" additive="sum"/>
${bonds.map(([a, b]) => `<line x1="${atoms[a][0]}" y1="${atoms[a][1]}" x2="${atoms[b][0]}" y2="${atoms[b][1]}" stroke="${INK.dim}" stroke-width="2"/>`).join('')}
${atoms.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="5" fill="${['#d9705f', '#8d97a5', '#4f9dd8'][i % 3]}"/>`).join('')}</g></g>`;
      const hand = kind === 'trackpad'
        ? pad(tip(d, [40, 40], [26, 26], [0, 1], [0.11, 0.16]) + tip(d, [40, 40, 56, 56], [26, 26, 26, 26], [0, 0.7, 0.88, 1], [0.7, 0.88]))
        : mouse({ left: held(d, [[0.11, 0.16], [0.7, 0.88]]) });
      return frame('run', 'Run is pressed; each block glows blue while it works and gets a green border when it is done; then the picture in the last block is dragged to turn the molecule', `${dots('run')}
<rect width="520" height="30" fill="${INK.panel}"/><path d="M0,30 H520" stroke="${INK.edge}"/>
<rect x="12" y="5" width="44" height="20" rx="4" fill="#2d6d9c" stroke="${INK.accent}"/><text x="34" y="19" font-size="11" fill="#ffffff" text-anchor="middle">Run</text>
<rect x="62" y="5" width="80" height="20" rx="4" fill="${INK.body}" stroke="${INK.edge}"/><text x="102" y="19" font-size="10" fill="${INK.faint}" text-anchor="middle">Run selected</text>
<rect x="446" y="7" width="62" height="16" rx="8" fill="none" stroke="${INK.edge}"/>
<text x="477" y="19" font-size="10" fill="${INK.faint}" text-anchor="middle">idle${jumps('opacity', d, [1, 0, 1], [0, 0.12, 0.97])}</text>
<text x="477" y="19" font-size="10" fill="${INK.accent}" text-anchor="middle" opacity="0">running${between(d, 0.12, 0.6)}</text>
<text x="477" y="19" font-size="10" fill="${INK.ok}" text-anchor="middle" opacity="0">done${between(d, 0.6, 0.97)}</text>
<path d="M152,128 C166,128 166,128 180,128" stroke="${wire('structure')}" stroke-width="2.5" fill="none"/>
<path d="M316,128 C332,128 332,80 348,80" stroke="${wire('structure')}" stroke-width="2.5" fill="none"/>
${block({ x: 16, y: 92, w: 136, h: 72, title: 'Load structure', kind: 'io', outs: ['structure'] })}
${block({ x: 180, y: 92, w: 136, h: 72, title: 'Run MD (mdrun)', kind: 'run', ins: ['structure'], outs: ['structure'] })}
<g transform="translate(348,44)"><rect width="160" height="124" rx="7" fill="${INK.body}" stroke="${INK.edge}"/>
<path d="M0,22 V7 A7,7 0 0 1 7,0 H153 A7,7 0 0 1 160,7 V22 Z" fill="${KIND.view}"/><text x="9" y="15" font-size="11" fill="${INK.title}">Preview structure</text>
<rect x="10" y="30" width="140" height="84" rx="4" fill="#101318"/>
<circle cx="0" cy="36" r="5" fill="${wire('structure')}" stroke="${INK.bg}" stroke-width="1.5"/></g>
${molecule}
${states(16, 92, 136, 72, 0.14, 0.3)}${states(180, 92, 136, 72, 0.3, 0.5)}${states(348, 44, 160, 124, 0.5, 0.6)}
<circle cx="22" cy="234" r="5" fill="${INK.accent}"/><text x="32" y="238" font-size="11" fill="${INK.dim}">working</text>
<circle cx="102" cy="234" r="5" fill="${INK.ok}"/><text x="112" y="238" font-size="11" fill="${INK.dim}">done</text>
${hand}
${pointer(travel(d, [[300, 226], [34, 16], [34, 16], [400, 118], [400, 118], [460, 118], [460, 118]], [0, 0.08, 0.16, 0.62, 0.7, 0.88, 1]) + rounds(d, 0.93), ring(d, 0.11) + ring(d, 0.7))}`);
    },

    ready: (kind) => {
      const d = 8;
      const clicks = [0.12, 0.28, 0.48, 0.7];
      const mini = (x, y, colour) => `<g transform="translate(${x},${y})"><rect width="70" height="40" rx="5" fill="${INK.body}" stroke="${INK.edge}"/><path d="M0,12 V5 A5,5 0 0 1 5,0 H65 A5,5 0 0 1 70,5 V12 Z" fill="${colour}"/></g>`;
      const done = (x, y) => `<rect x="${x - 2}" y="${y - 2}" width="74" height="44" rx="6" fill="none" stroke="${INK.ok}" stroke-width="2" opacity="0">${between(d, 0.8, 0.97)}</rect>`;
      const hand = kind === 'trackpad'
        ? pad(clicks.map((at) => tip(d, [40, 40], [26, 26], [0, 1], [at, at + 0.05])).join(''))
        : mouse({ left: held(d, clicks.map((at) => [at, at + 0.05])) });
      return frame('ready', 'The Tutorials tab is opened, a tutorial is chosen and loaded with Load as new graph, and Run is pressed', `${dots('ready', 150, 30, 370, 220)}
<rect width="150" height="250" fill="${INK.panel}"/><path d="M150,0 V250" stroke="${INK.edge}"/>
<text x="12" y="22" font-size="10" fill="${INK.dim}">Nodes</text><text x="56" y="22" font-size="10" fill="${INK.dim}">Chunks</text><text x="102" y="22" font-size="10" fill="${INK.dim}">Tutorials</text>
<rect x="8" y="27" width="40" height="2" fill="${INK.accent}">${jumps('opacity', d, [1, 0, 1], [0, 0.12, 0.97])}</rect>
<rect x="98" y="27" width="46" height="2" fill="${INK.accent}" opacity="0">${between(d, 0.12, 0.97)}</rect>
<g>${jumps('opacity', d, [1, 0, 1], [0, 0.12, 0.97])}${[[48, 90], [66, 70], [84, 100], [102, 60], [120, 84]].map(([y, w]) => `<rect x="14" y="${y}" width="${w}" height="6" rx="3" fill="${INK.edge}"/>`).join('')}</g>
<g opacity="0">${between(d, 0.12, 0.97)}<rect x="8" y="74" width="136" height="22" rx="4" fill="#26303c" opacity="0">${between(d, 0.26, 0.34)}</rect>
<text x="14" y="58" font-size="11" fill="${INK.text}">Lysozyme in Water</text><text x="14" y="89" font-size="11" fill="${INK.text}">An ice cube melting</text></g>
<rect x="150" y="0" width="370" height="30" fill="${INK.panel}"/><path d="M150,30 H520" stroke="${INK.edge}"/>
<rect x="166" y="5" width="44" height="20" rx="4" fill="#2d6d9c" stroke="${INK.accent}"/><text x="188" y="19" font-size="11" fill="#ffffff" text-anchor="middle">Run</text>
<g opacity="0">${between(d, 0.5, 0.97)}
<path d="M248,90 H276 M346,90 C360,90 360,150 374,150 M444,150 H460" stroke="${wire('structure')}" stroke-width="2" fill="none"/>
${mini(178, 70, KIND.build)}${mini(276, 70, KIND.build)}${mini(374, 130, KIND.run)}${mini(178, 150, KIND.view)}
${done(178, 70)}${done(276, 70)}${done(374, 130)}${done(178, 150)}</g>
<g opacity="0">${between(d, 0.3, 0.5)}<rect x="176" y="44" width="280" height="140" rx="7" fill="${INK.panel}" stroke="#3a434f"/>
<text x="190" y="66" font-size="11" fill="${INK.text}">Tutorial 1: An ice cube melting</text>
${[84, 98, 112].map((y, i) => `<rect x="190" y="${y}" width="${[240, 200, 220][i]}" height="5" rx="2.5" fill="${INK.edge}"/>`).join('')}
<rect x="296" y="152" width="146" height="22" rx="4" fill="#2d6d9c" stroke="${INK.accent}"/><text x="369" y="167" font-size="11" fill="#ffffff" text-anchor="middle">Load as new graph</text></g>
${hand}
${pointer(travel(d, [[300, 226], [122, 22], [122, 22], [90, 86], [90, 86], [369, 163], [369, 163], [188, 16], [188, 16]], [0, 0.09, 0.14, 0.24, 0.3, 0.44, 0.52, 0.66, 1]) + rounds(d, 0.94), clicks.map((at) => ring(d, at)).join(''))}`);
    },
  };
  return pictures;
})();

/* ------------------------------------------------------------ the words */
const TourSlides = {
  /* Every slide, in order, for a mouse ('mouse') or a touchpad ('trackpad').
     A slide is its name, its title, its paragraphs (simple HTML: <b> for
     things on screen, <kbd> for keys), its picture, and the moment of the
     picture to show when the computer asks for less movement. */
  all(kind) {
    const pad = kind === 'trackpad';
    const art = (name) => TourArt[name](kind);
    return [
      { id: 'choose', title: 'Welcome! Mouse or touchpad?', choice: true,
        text: ['This short tour shows how to use this page with your hands. It takes about two minutes.',
          'First, what do you point with? The tour then shows the moves for that one, and the page uses them from now on. You can change it later in <b>Settings</b>.'] },
      { id: 'click', title: 'Click: press once and let go', art: art('click'), still: 2.4,
        text: [pad
          ? 'Point at a block with the arrow, then tap the touchpad once with one finger (or press it down until it clicks).'
          : 'Point at a block with the arrow, then press the left mouse button once and let it go.',
        'The block is now <b>selected</b>: it has a blue outline, and the <b>Log</b> tab on the right shows what this block printed.'] },
      { id: 'drag', title: 'Drag: press, hold, move, let go', art: art('drag'), still: 2.6,
        text: [pad
          ? 'To move a block, point at its coloured title bar. Press the touchpad down until it clicks, and keep it pressed. Slide that finger, or a second finger, to move the block. Lift to let go.'
          : 'To move a block, point at its coloured title bar. Press the left button and keep it pressed, move the mouse, then let go.'] },
      { id: 'connect', title: 'Wires: connect two blocks', art: art('connect'), still: 2.7,
        text: ['A wire carries a file from one block to the next. Drag from a dot on the right edge of a block to a dot of the <b>same colour</b> on the left edge of another block.',
          'To take a wire away again, double-click the dot it goes into.'] },
      { id: 'pan', title: 'Move around', art: art('pan'), still: 2.9,
        text: pad
          ? ['Slide two fingers across the touchpad: the whole canvas moves.',
            'Holding down the <kbd>Space</kbd> bar and dragging works too.']
          : ['Hold down the <kbd>Space</kbd> bar and drag with the left button: the whole canvas moves. Dragging with the wheel pressed down works too.',
            'Without <kbd>Space</kbd>, dragging on an empty spot draws a box instead, which selects the blocks inside it.'] },
      { id: 'zoom', title: 'Zoom in and out', art: art('zoom'), still: 2.5,
        text: [pad
          ? 'Move two fingers apart on the touchpad to zoom in, and together to zoom out.'
          : 'Roll the mouse wheel forward to zoom in, and back to zoom out. The page zooms in on the spot the arrow points at.',
        'Lost your blocks? Press <kbd>F</kbd>, or <b>Fit</b> at the bottom right of the canvas, to see them all again.'] },
      { id: 'edit', title: 'Add, remove, undo', art: art('edit'), still: 6.2,
        text: ['Click a name in the list on the left, and that block appears on the canvas. If another block is selected, the new one goes next to it, already wired up where the colours match.',
          'To remove a block, click it and press the <kbd>Delete</kbd> key.',
          'Made a mistake? <kbd>Ctrl</kbd> + <kbd>Z</kbd> undoes it: hold down <kbd>Ctrl</kbd>, press <kbd>Z</kbd>, then let go of both. (On a Mac, <kbd>Cmd</kbd> instead of <kbd>Ctrl</kbd>.)'] },
      { id: 'menu', title: 'Right-click for more', art: art('menu'), still: 3.5,
        text: [pad
          ? 'Tap the touchpad with two fingers at the same time (or press it down with two fingers until it clicks): that is a <b>right-click</b>. Do it on a block, on the title bar of a box, or on an empty spot.'
          : 'Press the <b>right</b> mouse button on a block, on the title bar of a box, or on an empty spot.',
        'A menu opens with what you can do there. Click a line to choose it. The ice tutorial\'s extra boxes are switched on this way.'] },
      { id: 'run', title: 'Run, then look', art: art('run'), still: 6.6,
        text: ['Press <b>Run</b> at the top left. A block glows blue while it works, and gets a green border when it is done.',
          pad
            ? 'Pictures and plots appear inside the blocks. Drag a picture of a molecule to turn it; slide two fingers up or down on it to zoom.'
            : 'Pictures and plots appear inside the blocks. Drag a picture of a molecule to turn it; roll the wheel over it to zoom.',
          'Click a block to read what it printed, in the <b>Log</b> tab on the right.'] },
      { id: 'ready', title: 'You are ready', art: art('ready'), still: 3.6,
        text: ['Open <b>Tutorials</b> on the left, click a tutorial, press <b>Load as new graph</b>, then <b>Run</b>.',
          'To see this tour again, press <b>?</b> at the top right, then <b>Show the basics</b>.'] },
    ];
  },
};

/* ------------------------------------------------------------ the window */
const Tour = {
  NEVER: 'comfygmx.tour.never',   // this browser, for good: no tour at the start
  SHOWN: 'comfygmx.tour.shown',   // this tab: the tour has opened once already
  index: 0,
  generation: -1,
  _keys: null,

  /* Called once the page has started. Opens the tour if this tab has not
     seen it and nobody said never, as soon as no other window is open. */
  atStart() {
    if (this._get(this._local(), this.NEVER) || this._get(this._session(), this.SHOWN)) return;
    const began = Date.now();
    const attempt = () => {
      if (UI.anyDialogOpen()) {
        // Something else is being asked first, such as setting up the
        // machine. Wait for it, but not for ever: after two minutes the
        // person is busy with other things, and ? still has the tour.
        if (Date.now() - began < 120000) setTimeout(attempt, 1000);
        return;
      }
      this._set(this._session(), this.SHOWN, true);
      this.open();
    };
    setTimeout(attempt, 400);
  },

  open(index = 0) {
    this.index = index;
    UI.modal('The basics', UI.el('div', { class: 'tour' }), [], { panelClass: 'tour-panel' });
    this.generation = UI._generation;
    this._listen();
    this.show();
  },

  showing() {
    return this.generation === UI._generation && UI.modalOpen();
  },

  slides() {
    return TourSlides.all(Editor.pointer());
  },

  show() {
    const slides = this.slides();
    this.index = Math.max(0, Math.min(this.index, slides.length - 1));
    const slide = slides[this.index];
    const last = this.index === slides.length - 1;
    document.getElementById('modal-title').textContent = `The basics · ${this.index + 1} of ${slides.length}`;

    const host = document.querySelector('#modal-body .tour');
    host.innerHTML = '';
    const words = UI.el('div', { class: 'tour-text' }, [UI.el('h2', { text: slide.title })]);
    for (const paragraph of slide.text) words.appendChild(UI.el('p', { html: paragraph }));
    if (slide.choice) {
      // The question first, then the two answers to it.
      host.appendChild(words);
      host.appendChild(this._choice());
    } else {
      // The picture first, then what it shows.
      const holder = UI.el('div', { class: 'tour-picture', html: slide.art });
      host.appendChild(holder);
      this._still(holder.querySelector('svg'), slide.still);
      host.appendChild(words);
    }
    host.appendChild(UI.el('div', { class: 'tour-dots' }, slides.map((s, i) => UI.el('button', {
      class: i === this.index ? 'current' : '',
      title: `${i + 1}. ${s.title}`,
      'aria-label': `Slide ${i + 1}: ${s.title}`,
      onclick: () => this.go(i),
    }))));

    // The buttons along the bottom, drawn here rather than by UI.modal,
    // because they change from slide to slide.
    const footer = document.getElementById('modal-footer');
    footer.innerHTML = '';
    const never = UI.el('input', { type: 'checkbox', id: 'tour-never' });
    never.checked = Boolean(this._get(this._local(), this.NEVER));
    never.addEventListener('change', () => this._set(this._local(), this.NEVER, never.checked));
    footer.appendChild(UI.el('label', { class: 'tour-never' }, [never, ' Don\'t show this at the start again']));
    const back = UI.el('button', { text: '← Back', onclick: () => this.go(this.index - 1) });
    back.disabled = this.index === 0;
    footer.appendChild(back);
    const forward = UI.el('button', {
      class: 'primary', id: 'tour-next',
      text: last ? 'Start' : 'Next →',
      onclick: () => (last ? UI.closeModal() : this.go(this.index + 1)),
    });
    footer.appendChild(forward);
    forward.focus();
  },

  go(index) {
    if (!this.showing()) return;
    const count = this.slides().length;
    if (index < 0 || index >= count) return;
    this.index = index;
    this.show();
  },

  /* The first slide's two big buttons. Choosing one sets the page's own
     setting, so the canvas behaves as the tour says from then on. */
  _choice() {
    const now = Editor.pointer();
    const option = (kind, label, art) => UI.el('button', {
      class: `tour-option${now === kind ? ' chosen' : ''}`,
      'data-kind': kind,
      onclick: () => {
        Editor.setPointer(kind);
        this.go(1);
      },
    }, [UI.el('span', { html: art }), UI.el('span', { class: 'tour-option-label', text: label })]);
    return UI.el('div', { class: 'tour-choice' }, [
      option('mouse', 'A mouse', TourArt.mouseChoice()),
      option('trackpad', 'A touchpad', TourArt.padChoice()),
    ]);
  },

  /* For somebody who asked for less movement: the picture stopped at the
     moment that shows the most. */
  _still(svg, at) {
    if (!svg || typeof window === 'undefined' || !window.matchMedia) return;
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (typeof svg.pauseAnimations !== 'function') return;
    svg.pauseAnimations();
    svg.setCurrentTime(at || 0);
  },

  /* The arrow keys move between slides while the tour is on screen. The
     listener takes itself away the first time it finds the tour gone. */
  _listen() {
    if (this._keys) return;
    this._keys = (event) => {
      if (!this.showing()) {
        document.removeEventListener('keydown', this._keys, true);
        this._keys = null;
        return;
      }
      if (UI._subOpen) return;
      if (event.key === 'ArrowRight') { event.preventDefault(); event.stopPropagation(); this.go(this.index + 1); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); event.stopPropagation(); this.go(this.index - 1); }
    };
    document.addEventListener('keydown', this._keys, true);
  },

  /* Remembering, in the browser. A browser that refuses (a private window
     with storage blocked) still gets the tour; it just cannot remember. */
  _local() {
    try { return window.localStorage; } catch (err) { return null; }
  },
  _session() {
    try { return window.sessionStorage; } catch (err) { return null; }
  },
  _get(store, name) {
    try { return Boolean(store && store.getItem(name)); } catch (err) { return false; }
  },
  _set(store, name, on) {
    try {
      if (!store) return;
      if (on) store.setItem(name, '1'); else store.removeItem(name);
    } catch (err) { /* nothing to be done: it simply is not remembered */ }
  },
};
