/* The node editor: DOM nodes inside a pan/zoom world, wires drawn on SVG.
   DOM rather than canvas because every node is a form, and native inputs beat
   re-implementing text fields on a 2D context. */
'use strict';

/* How far in and out the canvas may zoom.

   The lower number is what "Fit" is allowed to reach. It used to be 0.15, and
   a tall graph -- the packaged lysozyme tutorial is about 2400 by 7100 wide --
   needs 0.09 to fit a 970 by 760 canvas, so pressing Fit left a third of the
   graph off-screen while claiming to have fitted it. At this scale a node is
   only a coloured bar, which is the point: it is the map, not the reading
   view. */
const ZOOM_MIN = 0.05;
const ZOOM_MAX = 2.5;

/* How wide a band around a wire counts as being on the wire, in screen
   pixels. A wire is drawn 2 px wide. Asking somebody to land a right-click
   inside 2 px is asking for three tries, and it is worse on a trackpad and
   worse again when the canvas is zoomed out. So every wire is drawn twice:
   once visibly, and once in an invisible stroke this wide that catches the
   pointer. 14 leaves six pixels of slack on each side, which is a comfortable
   target without being so wide that two wires running side by side fight over
   the same click. */
const WIRE_GRAB_PX = 14;

const PORT_COLORS = {
  structure: '#6fbf8b',
  topology:  '#d8a84f',
  mdp:       '#8a7fd0',
  tpr:       '#4f9dd8',
  traj:      '#d9705f',
  index:     '#4fb8c8',
  xvg:       '#c88fd0',
  posre:     '#c0a060',
  file:      '#8d97a5',
  text:      '#7a8a99',
  any:       '#8d97a5',
};

/* Types that may be wired together even though they are not identical. */
const LOOSE = new Set(['any', 'file']);

/* What a file's name says it is. Filled from the server's own table when the
   catalogue loads, so there is exactly one copy of it. */
function kindOfFile(path) {
  // A URL carries its query string and fragment along, and "inputs.zip?v=3"
  // has no extension at all if they are left on.
  const clean = String(path || '').split('#')[0].split('?')[0];
  const name = clean.split(/[\\/]/).pop();
  const dot = name.lastIndexOf('.');
  if (dot < 1) return 'file';
  return (Editor.fileKinds || {})[name.slice(dot + 1).toLowerCase()] || 'file';
}

/* What a socket carries, in words: its name, then what kind of file that is
   and what is in it, from the server's FILE_GUIDE (comfygmx/nodes/io_nodes.py).
   A socket that only says "file" is looked up by its own name, the way the
   server does it: an mdrun's energies, checkpoint and log are all plain files
   as far as wiring goes, but they are nothing alike. */
function fileAbout(label, type, portName) {
  const guide = Editor.fileGuide || {};
  const loose = type === 'file' || type === 'any';
  const entry = (loose && guide[portName]) || guide[type] || (loose && guide.file);
  if (!entry) return `${label} (${type})`;
  // "checkpoint: checkpoint" says nothing twice.
  const kind = entry.name.toLowerCase();
  const head = String(label).toLowerCase() === kind
    ? `${entry.name} (${entry.endings})`
    : `${label}: ${kind} (${entry.endings})`;
  return `${head}\n${entry.what}`;
}

/* Parameters that hold the name of the file a port will carry, in the order
   they win. Most nodes are covered by this list; a node that decides it
   differently says so in FILE_NAME_FOR rather than putting its own rule inside
   portType. */
/* How tall a box that grows with its contents is allowed to get. Beyond
   this it scrolls again -- the layout has to be able to promise that no
   single card swallows the screen. Kept in step with NOTE_CAP in
   comfygmx/tutorial_graph.py, which is what the shipped layouts are
   spaced by; the smoke test compares the two. */
const GROW_MAX_PX = 900;
/* One line of the 11 px fixed-width type these boxes use, and the padding
   above and below it. Only used for the floor; the real height is read
   off the box once the browser has laid the text out. */
const GROW_LINE_PX = 16;
const GROW_PAD_PX = 10;
/* How many characters fit on one line of a box that grows -- measured, at the
   11 px fixed-width type these boxes use. Only the note has a box that grows,
   and the note card is 536 px wide (.note-card in style.css), which leaves the
   box itself 502 px of usable line. Kept in step with NOTE_WRAP in
   comfygmx/tutorial_graph.py. */
const GROW_WRAP = 75;

/* How many lines the browser will break this text into, breaking on spaces the
   way it does. Used as the opening guess for a box that grows, before the page
   has been laid out and there is a real height to read.

   It has to be a guess first and a measurement second, not a measurement only:
   reading the real height needs the browser to have drawn the page, and a tab
   sitting in the background is not drawing anything. A graph opened in a tab
   you are not looking at would come back with every note collapsed to six
   rows, and stay that way until something made it redraw. */
function growRows(text, floor) {
  let total = 0;
  for (const line of String(text || '').split('\n')) {
    if (!line.trim()) { total += 1; continue; }
    let used = 0, rows = 1;
    for (const word of line.split(' ')) {
      const extra = word.length + (used ? 1 : 0);
      if (used && used + extra > GROW_WRAP) { rows += 1; used = word.length; }
      else used += extra;
    }
    total += rows;
  }
  return Math.max(floor, Math.min(Math.floor(GROW_MAX_PX / GROW_LINE_PX), total));
}

/* The little grammar a box uses to say when it is shown.

     source=the Protein Data Bank        while that box holds that value
     measure=RMSD (rms)|RMSF (rmsf)      one of several values
     define!=                            while that box is NOT empty
     mode=manual & define!=              both, joined with " & "

   A name the node has no box for reads as empty, so "x!=" on a missing box
   is false and "x=" on one is true -- which is what an absent value means. */
function whenHolds(rule, params) {
  const text = String(rule || '').trim();
  if (!text) return true;
  return text.split(' & ').every((clause) => {
    const not = clause.indexOf('!=');
    const eq = clause.indexOf('=');
    if (eq < 0) return true;
    const negated = not >= 0 && not < eq;
    const name = clause.slice(0, negated ? not : eq);
    const listed = clause.slice(eq + 1).split('|');
    const value = params[name];
    const held = listed.includes(value === undefined || value === null ? '' : String(value));
    return negated ? !held : held;
  });
}

/* The boxes a rule looks at, so a change to one of them redraws the node. */
function whenNames(rule) {
  return String(rule || '').split(' & ').map((clause) => {
    const eq = clause.indexOf('=');
    if (eq < 0) return '';
    const not = clause.indexOf('!=');
    return clause.slice(0, not >= 0 && not < eq ? not : eq);
  }).filter(Boolean);
}

/* Boxes that get a button offering to work the answer out for you, keyed by
   node type and box name. */
const PARAM_HELPERS = {
  'gmx.editconf:distance': {
    label: 'Pick it by eye…',
    title: 'See the molecule, the box around it, and what each shape costs in water',
    open: (node) => App.pickBoxAround(node.id),
  },
};
const FILE_NAME_PARAMS = ['path', 'output', 'url'];
const FILE_NAME_FOR = {
  /* Downloading an archive and taking one file out of it: what leaves on the
     file port is that member, not the .zip that arrived. */
  'io.fetch_url'(params) {
    if (params.extract && String(params.member || '').trim()) {
      return String(params.member).split('\n').map((line) => line.trim())
        .filter(Boolean)[0] || '';
    }
    return '';
  },
};

/* The type a port actually carries. Usually the one the node declares; for a
   loader, or for a download, it is whatever the file turns out to be -- which
   is the difference between a grey wire that connects to anything and a wire
   that says what is on it. */
function portType(node, port) {
  if (!port.follows) return port.type;
  const params = node.params || {};
  const declared = String(params[port.follows] || '').trim();
  if (declared && declared !== 'auto') {
    // The parameter either names a type outright -- the loader's "kind" -- or
    // names a file, and then the file's name is what says the type.
    return PORT_COLORS[declared] ? declared : kindOfFile(declared);
  }
  const special = FILE_NAME_FOR[node.type];
  const named = special ? special(params) : '';
  if (named) return kindOfFile(named);
  for (const name of FILE_NAME_PARAMS) {
    const value = String(params[name] || '').trim();
    if (value) return kindOfFile(value);
  }
  return port.type;
}

/* Group colours, deliberately the ones ComfyUI uses: anyone who has coloured a
   graph before already knows what they mean, and the names are what they will
   look for in the menu. */
const GROUP_COLORS = [
  ['blue', '#3f789e'],
  ['teal', '#3f6d7d'],
  ['green', '#4a7a4a'],
  ['olive', '#b58b2a'],
  ['brown', '#b06634'],
  ['red', '#8a4a4a'],
  ['purple', '#a1309b'],
  ['indigo', '#6a6aa8'],
  ['grey', '#4a4a4a'],
];
const DEFAULT_GROUP_COLOR = GROUP_COLORS[0][1];

/* Room for the title bar, and how much air a new group leaves around the nodes
   it was built from. */
const GROUP_TITLE_H = 26;

/* Does this click mean "add to what is already selected"? Shift is this
   editor's convention, Ctrl and Cmd are the ones everybody arrives with. */
const additive = (event) => Boolean(event.shiftKey || event.ctrlKey || event.metaKey);

/* The preset a run-parameters node is showing, and what it sets. */
function mdpPreset(node) {
  const table = (Editor.mdp || {}).presets || {};
  return table[String((node.params || {}).preset || '')] || null;
}

/* Which mdp option a run-parameters box stands for. The table comes from the
   node itself (MdpNode._WIDGET_MAP); define is kept apart from it there
   because it is not filled in with the others, but it is still an option. */
function mdpKey(param) {
  if (param === 'define') return 'define';
  return ((Editor.mdp || {}).widgets || {})[param] || '';
}

/* An option name the way GROMACS compares them: case, dashes and underscores
   make no difference, so vdw-type, vdw_type and vdwtype are one option. A
   value is compared the same way (V-rescale and v_rescale are one
   thermostat), except a number, which is compared as a number: -1 and 1 are
   not the same seed. */
function mdpSquash(text) {
  return String(text === undefined || text === null ? '' : text)
    .trim().toLowerCase().replace(/[-_]/g, '');
}

function mdpSame(value, wanted) {
  const a = String(value === undefined || value === null ? '' : value).trim();
  const b = String(wanted === undefined || wanted === null ? '' : wanted).trim();
  if (a !== '' && b !== '' && Number.isFinite(Number(a)) && Number.isFinite(Number(b))) {
    return Number(a) === Number(b);
  }
  return mdpSquash(a) === mdpSquash(b);
}

/* The options a raw mdp text sets, by name as GROMACS compares them. */
function mdpRawOptions(text) {
  const found = {};
  for (const line of String(text || '').split('\n')) {
    const body = line.split(';')[0];
    const eq = body.indexOf('=');
    if (eq < 0) continue;
    const key = mdpSquash(body.slice(0, eq));
    if (key) found[key] = body.slice(eq + 1).trim();
  }
  return found;
}

/* The same raw text with one option given a new value. The line that sets it
   is changed where it stands, and its comment stays where it was; an option
   the text does not set yet gets a line of its own at the end. */
function mdpSetRaw(text, key, value) {
  const want = mdpSquash(key);
  const lines = String(text || '').split('\n');
  for (let i = 0; i < lines.length; i += 1) {
    const semi = lines[i].indexOf(';');
    const body = semi >= 0 ? lines[i].slice(0, semi) : lines[i];
    const eq = body.indexOf('=');
    if (eq < 0) continue;
    if (mdpSquash(body.slice(0, eq)) !== want) continue;
    const after = body.slice(eq + 1);
    const gap = (after.match(/^\s*/) || [''])[0] || ' ';
    let line = `${body.slice(0, eq + 1)}${gap}${value}`;
    if (semi >= 0) {
      // Keep the comment in its column, as long as the value still fits.
      const room = after.length - gap.length - String(value).length;
      line += `${' '.repeat(Math.max(1, room))}${lines[i].slice(semi)}`;
    }
    lines[i] = line;
    return lines.join('\n');
  }
  const kept = lines.join('\n').replace(/\s+$/, '');
  return `${kept}${kept ? '\n' : ''}${key} = ${value}\n`;
}

/* The .mdp files that file-mode blocks point at, read once each so the block
   can show what they say: the values in its boxes, which boxes matter, and
   the summary. A path typed again is read again, so a file changed on disk
   is picked up by retyping or re-picking it. */
const MdpFiles = {
  entries: new Map(),

  get(path) {
    const key = String(path || '').trim();
    if (!key) return null;
    let entry = this.entries.get(key);
    if (!entry) {
      entry = { state: 'reading' };
      this.entries.set(key, entry);
      this._read(key, entry);
    }
    return entry;
  },

  forget(path) {
    this.entries.delete(String(path || '').trim());
  },

  async _read(key, entry) {
    // Only in the page: the tests load this file without the server.
    if (typeof API === 'undefined') { entry.state = 'unread'; return; }
    try {
      const data = await API.fileText(key);
      entry.text = data.text || '';
      entry.options = mdpRawOptions(entry.text);
      entry.state = 'read';
    } catch (err) {
      entry.state = 'missing';
      entry.error = err.message;
    }
    Editor.refreshOpenNodes('util.mdp');
  },
};

/* Where each option's value comes from when its box is empty: the preset,
   the raw text or the file, keyed by name as GROMACS compares them, with the
   words an empty box uses to say so. Null while nobody can know: a file not
   read yet, or the preset table not arrived from the server. */
function mdpBase(node) {
  const params = node.params || {};
  if (params.mode === 'raw') {
    return { options: mdpRawOptions(params.raw), from: 'from the raw text',
             missing: 'not in the raw text' };
  }
  if (params.mode === 'file') {
    const file = MdpFiles.get(params.path);
    if (!file || !file.options) return null;
    return { options: file.options, from: 'from the file', missing: 'not in the file' };
  }
  const preset = mdpPreset(node);
  if (!preset) return null;
  const options = {};
  for (const [key, value] of Object.entries(preset)) options[mdpSquash(key)] = value;
  return { options, from: `from ${params.preset}`, missing: `not set by ${params.preset}` };
}

const mdpKnown = (value) => value !== undefined && value !== null && String(value).trim() !== '';

/* Every option the run will use, by name as GROMACS compares them: what a box
   holds, else what the preset, the text or the file says, else GROMACS's own
   default. In raw mode only the text counts: the run writes it exactly as it
   is and takes nothing from the boxes. `known` is false while the preset or
   the file is not at hand, and then nothing should be hidden or claimed on
   the strength of it. */
function mdpEffective(node) {
  const base = mdpBase(node);
  const options = {};
  for (const [key, value] of Object.entries((Editor.mdp || {}).gromacs_defaults || {})) {
    options[mdpSquash(key)] = String(value);
  }
  if (base) {
    for (const [key, value] of Object.entries(base.options)) {
      if (mdpKnown(value)) options[key] = String(value);
    }
  }
  const widgets = { ...((Editor.mdp || {}).widgets || {}), define: 'define' };
  if ((node.params || {}).mode !== 'raw') {
    for (const [param, key] of Object.entries(widgets)) {
      const value = (node.params || {})[param];
      if (mdpKnown(value)) options[mdpSquash(key)] = String(value);
    }
  }
  return { known: Boolean(base), options };
}

/* The four facts the boxes' rules lean on, worked out from the options:
   what kind of run it is, and whether a thermostat, a barostat and a
   temperature schedule are at work. See mdp_options.py for the rules. */
const MDP_MINIMISERS = ['steep', 'cg', 'lbfgs'];
const MDP_DYNAMICS = ['md', 'mdvv', 'mdvvavek', 'sd', 'bd'];

function mdpFacts(options) {
  const integrator = mdpSquash(options.integrator || 'md');
  let run = 'other';
  if (MDP_MINIMISERS.includes(integrator)) run = 'minimise';
  if (MDP_DYNAMICS.includes(integrator)) run = 'dynamics';
  const off = (value) => ['', 'no'].includes(mdpSquash(value));
  const friction = ['sd', 'bd'].includes(integrator);
  return {
    _run: run,
    _thermostat: run === 'dynamics' && (friction || !off(options.tcoupl)) ? 'on' : 'off',
    _barostat: run === 'dynamics' && !off(options.pcoupl) ? 'on' : 'off',
    _annealing: String(options.annealing || '').split(/\s+/)
      .some((word) => word && mdpSquash(word) !== 'no') ? 'on' : 'off',
  };
}

/* The boxes of the run-parameters block that are not mdp options. Their
   rules compare what the box itself holds; every other name in a rule is an
   mdp option, or one of the four facts, and is compared with the value the
   run will really use. */
const MDP_PLAIN = ['mode', 'preset', 'path', 'raw', 'saved', 'filename', 'extra_flags'];

function mdpShows(node, param) {
  const rule = String(param.when || '').trim();
  if (!rule) return true;
  const effective = mdpEffective(node);
  const facts = mdpFacts(effective.options);
  return rule.split(' & ').every((clause) => {
    const not = clause.indexOf('!=');
    const eq = clause.indexOf('=');
    if (eq < 0) return true;
    const negated = not >= 0 && not < eq;
    const name = clause.slice(0, negated ? not : eq).trim();
    const listed = clause.slice(eq + 1).split('|');
    let value;
    if (MDP_PLAIN.includes(name)) {
      value = (node.params || {})[name];
    } else {
      // Unknown until the preset or the file is at hand: show the box.
      if (!effective.known) return true;
      value = name in facts ? facts[name] : effective.options[mdpSquash(mdpKey(name) || name)];
    }
    const held = listed.some((wanted) => mdpSame(value, wanted));
    return negated ? !held : held;
  });
}

/* The name the block writes its file under: the same rule as MdpNode.plan. */
function mdpFileName(node) {
  const params = node.params || {};
  const fallback = (Editor.mdp || {}).default_name || 'run.mdp';
  let name = String(params.filename || '').trim() || fallback;
  if (params.mode === 'manual' && name === fallback) name = `${params.preset || 'run'}_edited.mdp`;
  return name.endsWith('.mdp') ? name : `${name}.mdp`;
}

/* A number of steps, a time step and a length of time, the way people say
   them: 50,000 steps, 2 fs, 100 ps, 1 µs. */
function mdpCount(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString('en-US') : String(value);
}

function mdpTime(ps) {
  const round = (x) => String(Number(x.toPrecision(3)));
  if (!Number.isFinite(ps)) return '';
  if (ps >= 1e6) return `${round(ps / 1e6)} µs`;
  if (ps >= 1e3) return `${round(ps / 1e3)} ns`;
  if (ps >= 1) return `${round(ps)} ps`;
  return `${round(ps * 1000)} fs`;
}

/* A value the way the box's own list writes it, so the card and the boxes
   agree: a preset's v-rescale reads V-rescale, cutoff reads Cut-off. A value
   the list does not have is shown as it is written. */
function mdpSpelled(param, value) {
  const defs = (((Editor.defs || {})['util.mdp'] || {}).params || []);
  const choices = ((defs.find((p) => p.name === param) || {}).choices || []).map(String);
  const text = String(value === undefined || value === null ? '' : value);
  return choices.find((c) => c && mdpSame(c, text)) || text;
}

/* A number as people write it: 1.0 bar is 1 bar. Anything else unchanged. */
function mdpNumber(value) {
  const text = String(value === undefined || value === null ? '' : value).trim();
  return text !== '' && Number.isFinite(Number(text)) ? String(Number(text)) : text;
}

/* What the settings add up to, in words: the card under the first boxes.
   Each line is one thing somebody checking a run wants to know, and the
   warnings are combinations GROMACS 2026.3 refuses or warns about, caught
   here instead of at grompp. */
function mdpSummary(node) {
  const params = node.params || {};
  const title = mdpFileName(node);
  const out = { title, source: '', lines: [], warnings: [] };
  const mode = params.mode || 'preset';
  if (mode === 'preset') out.source = `preset ${params.preset || ''}`;
  if (mode === 'manual') out.source = `${params.preset || 'preset'}, edited here`;
  if (mode === 'raw') out.source = 'your own text';
  if (mode === 'file') out.source = String(params.path || '').split('/').pop() || 'a file';

  if (mode === 'raw' && !String(params.raw || '').trim()) {
    out.warnings.push('The text is empty: paste an .mdp file into the box below.');
    return out;
  }
  if (mode === 'file') {
    const file = MdpFiles.get(params.path);
    if (!file) { out.warnings.push('No file chosen yet.'); return out; }
    if (file.state === 'missing') {
      out.warnings.push(`Cannot read ${params.path}: ${file.error || 'no such file'}.`);
      return out;
    }
    if (file.state !== 'read') { out.lines.push('Read from the file when the block runs.'); return out; }
  }
  const { known, options } = mdpEffective(node);
  if (!known) return out;
  const o = (key) => options[mdpSquash(key)];
  const facts = mdpFacts(options);
  const integrator = mdpSquash(o('integrator'));
  const words = (value) => String(value || '').trim().split(/\s+/).filter(Boolean);
  const refT = words(o('ref-t'));
  const groups = words(o('tc-grps'));

  if (facts._run === 'minimise') {
    const how = { steep: 'steepest descent', cg: 'conjugate gradients', lbfgs: 'L-BFGS' }[integrator];
    out.lines.push(`Energy minimisation (${how}): up to ${mdpCount(o('nsteps'))} steps, `
      + `until no force is above ${o('emtol')} kJ/mol/nm`);
  } else if (facts._run === 'dynamics') {
    const how = { md: 'Dynamics', mdvv: 'Dynamics (velocity Verlet)',
                  mdvvavek: 'Dynamics (velocity Verlet)', sd: 'Stochastic dynamics',
                  bd: 'Brownian dynamics' }[integrator];
    const steps = Number(o('nsteps'));
    const dt = Number(o('dt'));
    out.lines.push(steps < 0
      ? `${how}, ${mdpTime(dt)} steps, until it is stopped`
      : `${how}: ${mdpCount(steps)} steps of ${mdpTime(dt)} = ${mdpTime(steps * dt)}`);
    if (facts._thermostat === 'on') {
      const temps = [...new Set(refT.map(mdpNumber))];
      const holder = ['sd', 'bd'].includes(integrator) ? `held by the friction of ${integrator}`
        : mdpSpelled('tcoupl', o('tcoupl'));
      const several = groups.length > 1 ? `, ${groups.length} heat groups` : '';
      if (facts._annealing === 'on') {
        const points = words(o('annealing-temp'));
        const times = words(o('annealing-time'));
        out.lines.push(`Temperature follows a schedule: ${points.join(' → ')} K over `
          + `${times[times.length - 1] || '?'} ps (${holder}${several})`);
      } else {
        out.lines.push(`${temps.length ? temps.join(', ') : '?'} K (${holder}${several})`);
      }
    } else {
      out.lines.push('No thermostat: the temperature is free to drift');
    }
    if (facts._barostat === 'on') {
      const pressure = mdpNumber(words(o('ref-p'))[0]) || '?';
      out.lines.push(`${pressure} bar, ${mdpSpelled('pcoupltype', o('pcoupltype'))} `
        + `(${mdpSpelled('pcoupl', o('pcoupl'))})`);
    } else {
      out.lines.push('Fixed box size: no pressure control');
    }
    if (mdpSquash(o('gen-vel')) === 'yes') {
      const seed = Number(o('gen-seed'));
      out.lines.push(`New random velocities at ${mdpNumber(o('gen-temp'))} K`
        + `${Number.isFinite(seed) && seed !== -1 ? `, seed ${seed}` : ''}`);
    } else if (mdpSquash(o('continuation')) === 'yes') {
      out.lines.push('Continues from the run before it');
    }
  } else {
    out.lines.push(`${o('integrator')} run, ${mdpCount(o('nsteps'))} steps`);
  }

  const define = String(o('define') || '').trim();
  if (define) {
    out.lines.push(/-DPOSRES\b/.test(define)
      ? `Position restraints on (${define})` : `Topology switches: ${define}`);
  }
  const every = Number(o('nstxout-compressed'));
  if (every > 0) {
    out.lines.push(facts._run === 'dynamics'
      ? `A frame every ${mdpTime(every * Number(o('dt')))}`
      : `A frame every ${mdpCount(every)} steps`);
  }
  const coulomb = mdpSquash(o('coulombtype'));
  const cutoffs = [...new Set([o('rcoulomb'), o('rvdw')].map((v) => String(Number(v))))]
    .join(' and ');
  if (coulomb === 'pme') out.lines.push(`PME electrostatics, cut-offs ${cutoffs} nm`);
  else if (coulomb === 'reactionfield') {
    out.lines.push(`Reaction field, dielectric ${mdpNumber(o('epsilon-r'))}, cut-offs ${cutoffs} nm`);
  } else out.lines.push(`${mdpSpelled('coulombtype', o('coulombtype'))} electrostatics, cut-offs ${cutoffs} nm`);

  // What GROMACS 2026.3 refuses or warns about, said before grompp does.
  const w = out.warnings;
  if (facts._run === 'dynamics') {
    if (mdpSquash(o('gen-vel')) === 'yes' && mdpSquash(o('continuation')) === 'yes') {
      w.push('GROMACS refuses new velocities together with continuation = yes.');
    }
    if (facts._thermostat === 'on' && groups.length) {
      if (refT.length !== groups.length) {
        w.push(`ref-t needs one value per heat group: ${groups.length} groups, ${refT.length} values.`);
      }
      const tauT = words(o('tau-t'));
      if (tauT.length !== groups.length) {
        w.push(`tau-t needs one value per heat group: ${groups.length} groups, ${tauT.length} values.`);
      }
    }
    if (facts._barostat === 'on') {
      const need = { isotropic: 1, semiisotropic: 2, anisotropic: 6, surfacetension: 2 }[
        mdpSquash(o('pcoupltype'))];
      for (const key of ['ref-p', 'compressibility']) {
        if (need && words(o(key)).length !== need) {
          w.push(`${o('pcoupltype')} pressure needs ${need} value${need > 1 ? 's' : ''} `
            + `in ${key}, not ${words(o(key)).length}.`);
        }
      }
      if (/-DPOSRES\b/.test(define) && mdpSquash(o('refcoord-scaling')) === 'no') {
        w.push('With -DPOSRES and pressure control, set refcoord-scaling to com; '
          + 'GROMACS warns otherwise.');
      }
      if (mdpSquash(o('pcoupl')) === 'mttk' && !integrator.startsWith('mdvv')) {
        w.push('MTTK pressure control needs the md-vv integrator.');
      }
    }
    if (mdpSquash(o('tcoupl')).startsWith('andersen') && !integrator.startsWith('mdvv')) {
      w.push('The Andersen thermostat needs the md-vv integrator.');
    }
    if (mdpSquash(o('gen-vel')) === 'yes' && refT.length
        && !mdpSame(o('gen-temp'), refT[0])) {
      w.push(`New velocities are drawn at ${o('gen-temp')} K but the thermostat holds `
        + `${refT[0]} K; set gen-temp to match.`);
    }
  }
  if (Number(o('verlet-buffer-tolerance')) === -1
      && Number(o('rlist')) < Math.max(Number(o('rcoulomb')), Number(o('rvdw')))) {
    w.push('rlist is smaller than the cut-offs; GROMACS refuses that when '
      + 'verlet-buffer-tolerance is -1.');
  }
  return out;
}

/* Every widget filled in from the preset, so an edited node holds the whole
   parameter set instead of a diff against something invisible. A dropdown
   gets the preset's value in its own spelling, so V-rescale is picked for a
   preset that writes v-rescale. */
function mdpFill(node) {
  const preset = mdpPreset(node);
  const widgets = (Editor.mdp || {}).widgets || {};
  const filled = {};
  if (!preset) return filled;
  const presetOptions = {};
  for (const [key, value] of Object.entries(preset)) presetOptions[mdpSquash(key)] = value;
  for (const [param, key] of Object.entries(widgets)) {
    const value = presetOptions[mdpSquash(key)];
    if (value === undefined || value === null || String(value) === '') continue;
    filled[param] = mdpSpelled(param, value);
  }
  return filled;
}

const PARAM_FOLLOWS = {
  /* A preset is a claim: these are the published settings, untouched. Editing
     one of its values makes that claim false, so the node stops making it --
     it switches to manual, fills in every other value from the preset so what
     is on screen is the whole file rather than one changed line over thirty
     invisible ones, and names its output after the preset it grew out of. A
     tuned run should not be indistinguishable from a stock one six months
     later. */
  'util.mdp': (() => {
    const rules = {
      preset(node, raw) {
        // Changing which preset, while already editing one: refill from the
        // new one, or the node keeps the old preset's values under the new
        // preset's name. What is *not* refilled is anything that was really
        // edited -- a value that differs from the old preset was typed by
        // somebody, and swapping the baseline underneath it should not throw
        // it away.
        if (node.params.mode !== 'manual') return null;
        const was = mdpFill(node);
        const filled = mdpFill({ params: { ...node.params, preset: raw } });
        if (!Object.keys(filled).length) return null;
        for (const [param, value] of Object.entries(node.params)) {
          const typed = String(value || '');
          if (typed && param in filled && typed !== String(was[param] || '')) {
            filled[param] = typed;
          }
        }
        const named = /_edited\.mdp$/.test(String(node.params.filename || ''));
        return { ...filled, ...(named ? { filename: `${raw}_edited.mdp` } : {}) };
      },
      mode(node, raw) {
        if (raw !== 'preset' && raw !== 'raw') return null;
        // Back to the stock preset: the widgets go quiet again, since a blank
        // widget is what "whatever the preset says" looks like. On to raw
        // text, the same and the define box with them: the text is then the
        // whole file, and a value left in a box from an edited preset would
        // look set while the run ignored it.
        const widgets = Object.keys((Editor.mdp || {}).widgets || {});
        if (raw === 'raw') widgets.push('define');
        const cleared = {};
        for (const param of widgets) {
          if (String(node.params[param] || '')) cleared[param] = '';
        }
        if (/_edited\.mdp$/.test(String(node.params.filename || ''))) {
          cleared.filename = (Editor.mdp || {}).default_name || 'run.mdp';
        }
        return Object.keys(cleared).length ? cleared : null;
      },
    };
    /* In raw mode the text is the whole file, so a box is a way of changing
       one line of it: what is typed goes into the text, and the box empties
       again to show what the text now says. Otherwise raw mode would show the
       values in the boxes and then quietly ignore anything typed there. */
    const rawEdit = (node, raw, param) => {
      const key = mdpKey(param);
      const value = String(raw === undefined || raw === null ? '' : raw).trim();
      if (!key || !value) return null;
      return { raw: mdpSetRaw(node.params.raw, key, value), [param]: '' };
    };
    // One rule per value widget, all the same rule.
    const touched = (node, raw, param) => {
      if (node.params.mode === 'raw') return rawEdit(node, raw, param);
      if (node.params.mode !== 'preset' || !String(raw || '').trim()) return null;
      const changes = { ...mdpFill(node), mode: 'manual', [param]: raw };
      const fallback = (Editor.mdp || {}).default_name || 'run.mdp';
      if (!String(node.params.filename || '') || node.params.filename === fallback) {
        changes.filename = `${node.params.preset || 'run'}_edited.mdp`;
      }
      return changes;
    };
    // One rule for every value box, all the same rule. Looked up by name as
    // the boxes are used rather than listed here, because which boxes there
    // are comes from the server (MdpNode._WIDGET_MAP), and a hand-kept list
    // here missed every box added after it was written.
    rules.anyValue = (param) => (mdpKey(param)
      ? (node, raw) => touched(node, raw, param) : null);
    return rules;
  })(),
};
const GROUP_PAD = 16;

/* How wide a strip beside a box the names of its wall cables need. The same
   number caps how wide one name may be drawn, so what is checked for and what
   is written are the same thing. */
const NAME_STRIP = 150;

/* How much wider each cable of a bundle swings where the bundle turns back
   round the corner of a box (see _swingWider): this much more pull on the
   curve for every pixel its dot sits further from the corner than the dot
   nearest the corner does. Tried on the tutorials: with less than about 16,
   two cables side by side still touch where they turn; with 16 they stay a
   dot's width apart all the way round. */
const SWING_PER_PX = 16;

/* How long two edits of the same thing count as one undo step. Typing into a
   text field fires a change per keystroke, and forty keystrokes must not be
   forty presses of Ctrl+Z. */
const COALESCE_MS = 900;
const HISTORY_LIMIT = 80;

/* ------------------------------------------------- the flag reference

   Under the Extra flags box, the flags of the command that box is appended
   to: what each one does, in the command's own words, and which of them this
   node already sets. It is the difference between a free-text box you have to
   leave the program to use and one you can actually type into.

   The list arrives when it is opened, not when the node is built. A graph of
   forty nodes would otherwise carry forty flag lists nobody asked to see, and
   'gmx mdrun' alone has seventy-one. */
const FlagReference = {
  /* command -> the answer, so opening the same reference on ten nodes asks
     once. Node-specific marks come from the node passed with the request, so
     the cache is keyed by both. */
  _cache: new Map(),

  build(hint, def, textarea, commit) {
    const box = UI.el('details', { class: 'flagref' });
    const many = hint.available > 0;
    const summary = UI.el('summary', {
      text: many
        ? `${hint.available} more flag${hint.available === 1 ? '' : 's'} ${hint.command} takes`
        : `what ${hint.command} takes`,
    });
    box.appendChild(summary);
    const body = UI.el('div', { class: 'flagref-body' });
    box.appendChild(body);
    box.addEventListener('toggle', () => {
      if (box.open && !body.dataset.filled) {
        body.dataset.filled = '1';
        this._fill(body, hint, def, textarea, commit);
      }
    });
    // Opening the reference must not drag the node, and must not toggle the
    // advanced block it lives inside.
    box.addEventListener('mousedown', (event) => event.stopPropagation());
    return box;
  },

  async _fill(body, hint, def, textarea, commit) {
    body.textContent = 'asking…';
    const key = `${hint.command}\u0000${def.type}`;
    let data = this._cache.get(key);
    if (!data) {
      try {
        data = await API.flags(hint.command, def.type);
        this._cache.set(key, data);
      } catch (error) {
        body.textContent = `could not read the flag list: ${error.message}`;
        return;
      }
    }
    body.textContent = '';
    body.appendChild(this._head(hint, data, def));
    const flags = (data.flags || []).slice();
    if (!flags.length) {
      body.appendChild(UI.el('p', {
        class: 'flagref-none',
        text: `No flag list for ${hint.command} here -- it is a program `
            + 'Comfy-gmx could not ask on this machine. Anything you type is '
            + 'still passed to it.',
      }));
      return;
    }
    // Free flags first: those are the ones the box is for. The ones the node
    // sets itself stay in the list, greyed, because somebody hunting for a
    // flag should find out the node has a widget for it rather than conclude
    // the command has no such flag.
    flags.sort((a, b) => (a.used ? 1 : 0) - (b.used ? 1 : 0));
    const list = UI.el('div', { class: 'flagref-list' });
    for (const flag of flags) list.appendChild(this._row(flag, textarea, commit));
    if (flags.length > 10) body.appendChild(this._filter(list));
    body.appendChild(list);
    if (data.source) {
      body.appendChild(UI.el('div', { class: 'flagref-source', text: `from ${data.source}` }));
    }
  },

  _head(hint, data, def) {
    const head = UI.el('div', { class: 'flagref-head' });
    const taken = (hint.modelled || []).length;
    head.appendChild(UI.el('span', {
      class: 'flagref-what',
      text: taken
        ? `${hint.available} free, ${taken} already set by the boxes above`
        : `${hint.available} flag${hint.available === 1 ? '' : 's'}`,
    }));
    const docs = data.docs || def.docs;
    if (docs) {
      head.appendChild(UI.el('a', {
        class: 'flagref-docs', href: docs, target: '_blank', rel: 'noopener',
        text: 'documentation ↗',
      }));
    }
    return head;
  },

  _filter(list) {
    const box = UI.el('input', {
      type: 'search', class: 'flagref-filter', placeholder: 'filter flags…',
    });
    const apply = () => {
      const needle = box.value.trim().toLowerCase();
      for (const row of list.children) {
        row.classList.toggle('hidden', Boolean(needle)
          && !row.dataset.search.includes(needle));
      }
    };
    box.addEventListener('input', apply);
    // A search box inside a node must not reach the canvas: Delete would
    // delete the node out from under the cursor.
    box.addEventListener('keydown', (event) => event.stopPropagation());
    return box;
  },

  _row(flag, textarea, commit) {
    const takes = flag.takes ? ` ${flag.takes}` : '';
    const row = UI.el('div', {
      class: `flagref-row${flag.used ? ' used' : ''}`,
      title: flag.used
        ? `this node sets ${flag.flag} itself`
        : `add ${flag.flag} to the box above`,
    });
    row.dataset.search = `${flag.flag} ${flag.aliases || ''} ${flag.what || ''}`.toLowerCase();
    row.appendChild(UI.el('code', { text: flag.flag + takes }));
    const what = [flag.what || ''];
    if (flag.default) what.push(`(default ${flag.default})`);
    if (flag.used) what.push(flag.widget ? `-- set by "${flag.widget}"` : '-- set by this node');
    row.appendChild(UI.el('span', { class: 'flagref-def', text: what.join(' ').trim() || '—' }));
    row.addEventListener('click', () => {
      if (flag.used) {
        // Typing it again is not a way of overriding the widget -- GROMACS
        // refuses a flag given twice -- so say which box owns it instead.
        UI.toast(flag.widget
          ? `${flag.flag} is what the "${flag.widget}" box sets`
          : `this node sets ${flag.flag} itself`, 'info', 3000);
        return;
      }
      // A flag that takes a value is inserted without one, and the caret is
      // left where the value goes: guessing a value would be worse than
      // leaving the space.
      const current = textarea.value.trim();
      textarea.value = `${current}${current ? ' ' : ''}${flag.flag}${flag.takes ? ' ' : ''}`;
      commit(textarea.value);
      textarea.focus();
      textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    });
    return row;
  },
};

const Editor = {
  defs: {},
  nodes: new Map(),
  links: [],
  /* Coloured boxes behind the nodes. Purely organisational: nothing about a
     group changes what runs, which is why membership is positional rather than
     stored -- drag a node out and it has left. */
  groups: [],
  groupCounter: 1,
  /* Groups are selected separately from nodes: selecting a group's contents is
     not the same as selecting the box, and Delete has to be able to mean both. */
  selectedGroups: new Set(),
  selection: new Set(),
  view: { x: 60, y: 40, scale: 1 },
  counter: 1,
  onChange: null,
  /* Called after undo/redo so the toolbar can update. */
  onHistory: null,
  /* Called after undo/redo has replaced the node objects. */
  onRestore: null,
  history: { past: [], future: [] },
  _baseline: '',
  _pending: { label: '', key: '' },
  _commitTimer: null,
  _restoring: false,
  _drag: null,
  _groupDrag: null,
  _linkDrag: null,
  //: Which box each block stands in, and where each chunk socket sits. Both
  //  are worked out when the graph changes and read while wires are drawn,
  //  which happens on every mouse move of a drag.
  _homeOf: new Map(),
  _groupDots: new Map(),
  _pan: null,
  /* Is the spacebar down? Holding it turns a plain drag into a drag of the
     canvas itself, which is the one way of moving around that works the same
     on a mouse, a trackpad and a tablet. The middle button does it too, but a
     laptop trackpad has no middle button to press: two fingers on a trackpad
     is a right-click on most machines and a scroll on the rest, never a middle
     click. Alt and drag was the other way out, and on Linux the desktop itself
     usually swallows Alt-drag to move the window, so it never reached here. */
  _spaceDown: false,
  _marquee: null,

  /* ------------------------------------------------------------- setup */
  init(defs) {
    this.defs = defs;
    this.dom = {
      canvas: document.getElementById('canvas'),
      world: document.getElementById('world'),
      groups: document.getElementById('groups'),
      wires: document.getElementById('wires'),
      nodes: document.getElementById('nodes'),
      marquee: document.getElementById('marquee'),
      zoom: document.getElementById('zoom-level'),
    };
    this._bindCanvas();
    this.applyView();
  },

  /* --------------------------------------------------- graph mutations */
  addNode(type, x, y, params = {}, id = null) {
    let def = this.defs[type];
    if (!def) { UI.toast(`unknown node type ${type}`, 'error'); return null; }
    // A block that has been folded into a bigger one: open as the bigger
    // one, with the choice that makes it behave like the old block, so a
    // graph saved before the merge never shows a block the palette lacks.
    if (def.replaced_by && this.defs[def.replaced_by.type]) {
      const swap = def.replaced_by;
      const moved = {};
      for (const [key, value] of Object.entries(params || {})) {
        moved[(swap.rename || {})[key] || key] = value;
      }
      params = Object.assign(moved, swap.params || {});
      type = swap.type;
      def = this.defs[type];
    }
    const nodeId = id || `n${this.counter++}`;
    const values = {};
    for (const param of def.params) values[param.name] = param.default;
    Object.assign(values, params);
    const node = {
      id: nodeId, type, pos: [Math.round(x), Math.round(y)],
      params: values, collapsed: false, title: def.title, pause: false, off: false,
      status: 'idle', notes: [], error: '', progress: '', problems: [], blocked: false,
      // Preview nodes only: how the picture is drawn and how big the node is.
      // Display state, never a parameter -- a parameter would change the cache
      // signature and re-run the graph because you switched to a trace.
      display: null, previewPath: '', previewData: null, previewError: '',
    };
    this.nodes.set(nodeId, node);
    this.dom.nodes.appendChild(this._buildNode(node));
    this.changed();
    return node;
  },

  removeNode(id) {
    this.mark('delete');
    const node = this.nodes.get(id);
    if (!node) return;
    const cut = this.links.filter((l) => l.from_node === id || l.to_node === id);
    this.links = this.links.filter((l) => l.from_node !== id && l.to_node !== id);
    if (node._el) { this._unwatchSize(node._el); node._el.remove(); }
    NodePreview.detach(id);
    this.nodes.delete(id);
    this.selection.delete(id);
    for (const group of this.groups) { if (group.own) group.own.delete(id); }
    this._dropSpentCables(cut);
    this.drawWires();
    this.changed();
  },

  connect(fromNode, fromPort, toNode, toPort) {
    this.mark('connect');
    if (fromNode === toNode) return false;
    // An input takes one wire; replacing is the common intent.
    const replaced = this.links.filter((l) => l.to_node === toNode && l.to_port === toPort);
    this.links = this.links.filter((l) => !(l.to_node === toNode && l.to_port === toPort));
    this.links.push({ from_node: fromNode, from_port: fromPort, to_node: toNode, to_port: toPort });
    // After the new wire is in, so a wire moved from one block to another
    // through the same wall keeps its dot there.
    this._dropSpentCables(replaced);
    this.refreshPortStates();
    this.drawWires();
    this.changed();
    return true;
  },

  /* Cut the wire into one input. Hands back the names of any wall cables
     that went with it, so whoever asked can say so.

     keepCables is for picking a wire up by its end to move it: the wire is
     off the graph while you carry it, but whether its dot on the wall is
     still wanted is only known once you let go. */
  disconnect(toNode, toPort, { keepCables = false } = {}) {
    this.mark('disconnect');
    const cut = this.links.filter((l) => l.to_node === toNode && l.to_port === toPort);
    if (!cut.length) return [];
    this.links = this.links.filter((l) => !(l.to_node === toNode && l.to_port === toPort));
    const gone = keepCables ? [] : this._dropSpentCables(cut);
    this.refreshPortStates();
    this.drawWires();
    this.changed();
    return gone;
  },

  /* The wall cables a wire is threaded through.

     The same test the wire drawing makes, kept in one place so the two can
     never disagree: a wire only touches a wall when its two ends stand in
     different boxes, and then only a wall carrying a cable for the block
     it comes out of. */
  _cablesUsedBy(link) {
    const homes = this._homeOf || new Map();
    const fromHome = homes.get(link.from_node);
    const toHome = homes.get(link.to_node);
    if (fromHome === toHome) return [];
    const found = [];
    for (const boxId of [fromHome, toHome]) {
      if (!boxId) continue;
      const group = this.groups.find((g) => g.id === boxId);
      const entry = group && (group.patch || []).find(
        (e) => e.node === link.from_node && e.port === link.from_port);
      if (entry) found.push({ group, entry });
    }
    return found;
  },

  /* After wires are cut, any wall cable that one of them went through and
     nothing goes through any more is taken off the wall. A dot on a wall
     stands for the wires going through it, so a dot with none left is a dot
     standing for nothing, and leaving it behind was the complaint.

     Only cables a cut wire actually used. One you have just put on a wall
     and not wired onward yet has no wires either, and it must not vanish
     because something unrelated was disconnected elsewhere. */
  _dropSpentCables(cut) {
    const touched = [];
    for (const link of cut) {
      for (const hit of this._cablesUsedBy(link)) {
        if (!touched.some((t) => t.entry === hit.entry)) touched.push(hit);
      }
    }
    const gone = [];
    for (const { group, entry } of touched) {
      const stillUsed = this.links.some(
        (l) => this._cablesUsedBy(l).some((hit) => hit.entry === entry));
      if (stillUsed) continue;
      gone.push(this._patchName(group, entry));
      group.patch = (group.patch || []).filter((e) => e !== entry);
    }
    // Straight away rather than on the next tidy-up: the wires are redrawn
    // next, and they would otherwise be drawn to a dot that is no longer
    // there for a moment.
    if (gone.length) this.rebuildGroupPorts();
    return gone;
  },

  clear() {
    NodePreview.detachAll();
    if (window.UI && UI.status) UI.status('ready');
    if (this._observer) { this._observer.disconnect(); this._sizes.clear(); }
    this.nodes.clear();
    this.links = [];
    this.groups = [];
    this.selection.clear();
    this.selectedGroups.clear();
    this.dom.nodes.innerHTML = '';
    this.dom.wires.innerHTML = '';
    this.dom.groups.innerHTML = '';
    this.counter = 1;
    this.groupCounter = 1;
    // Back to normal size. Whatever the last graph needed stays otherwise --
    // and after a big tutorial that is 7%, so the first block you add to the
    // empty canvas is a speck three pixels wide in the middle of nothing.
    this.view = { x: 60, y: 40, scale: 1 };
    this.applyView();
    this.changed();
  },

  toJSON() {
    return {
      version: 1,
      nodes: [...this.nodes.values()].map((n) => ({
        id: n.id, type: n.type, pos: n.pos, params: n.params,
        collapsed: n.collapsed, title: n.title,
        // Left out unless it is set, so no existing saved workflow changes.
        ...(n.pause ? { pause: true } : {}),
        // Switched off: left out of checking and running, and so is
        // everything that depends on it. Left out of the file unless set.
        ...(n.off ? { off: true } : {}),
        // Only preview nodes have one; leaving the key out keeps every other
        // node's JSON exactly as it was.
        ...(n.display ? { display: { ...n.display } } : {}),
      })),
      links: this.links.map((l) => ({ ...l })),
      groups: this.groups.map((g) => ({
        id: g.id, title: g.title, color: g.color, bounds: [...g.bounds],
        // Left out unless the box was built from a known set of nodes, so a
        // workflow saved before this existed still reads back identically.
        ...(g.own && g.own.size ? { own: [...g.own] } : {}),
        // The cables run through this box's walls. Left out when there are
        // none, so every workflow saved before this existed reads back
        // exactly as it did. A copy of each, not the objects themselves: two
        // boxes built from one chunk would otherwise share them, and editing
        // one would edit both.
        ...((g.patch || []).length ? { patch: g.patch.map((e) => ({ ...e })) } : {}),
      })),
      view: { ...this.view },
    };
  },

  fromJSON(data) {
    this.clear();
    let maxIndex = 0;
    for (const node of data.nodes || []) {
      const created = this.addNode(node.type, node.pos ? node.pos[0] : 0,
        node.pos ? node.pos[1] : 0, node.params || {}, node.id);
      if (created) {
        created.collapsed = !!node.collapsed;
        created.pause = !!node.pause;
        created.off = !!node.off;
        if (node.title) created.title = node.title;
        if (node.display) created.display = { ...node.display };
        this._refreshNodeElement(created);
      }
      const match = /^n(\d+)$/.exec(node.id || '');
      if (match) maxIndex = Math.max(maxIndex, parseInt(match[1], 10));
    }
    this.counter = maxIndex + 1;
    this.links = (data.links || []).filter(
      (l) => this.nodes.has(l.from_node) && this.nodes.has(l.to_node));
    let maxGroup = 0;
    for (const group of data.groups || []) {
      const members = (group.nodes || []).filter((id) => this.nodes.has(id));
      const bounds = this._groupBounds(group, members);
      if (!bounds) continue;
      const own = (group.own || group.nodes || []).filter((id) => this.nodes.has(id));
      const made = this.addGroup(group.title, bounds, group.color, group.id, own);
      // Same existence test the links get two lines up: a cable naming a
      // block that is not here would draw from nowhere.
      made.patch = (group.patch || [])
        .filter((e) => e && this.nodes.has(e.node))
        .map((e) => ({ node: e.node, port: e.port,
                       side: e.side === 'east' ? 'east' : 'west',
                       ...(e.label ? { label: e.label } : {}) }));
      const match = /^g(\d+)$/.exec(group.id || '');
      if (match) maxGroup = Math.max(maxGroup, parseInt(match[1], 10));
    }
    this.groupCounter = maxGroup + 1;
    if (data.view) { this.view = { ...data.view }; this.applyView(); }
    this.refreshPortStates();
    this.drawWires();
    this.changed();
    this.settleGroups();
  },

  /* Let every box grow to fit what it holds, once the drawing has settled.
     A box is measured the instant it is made, and at that moment the browser
     has not necessarily finished working out how tall each node is. So the
     box comes out a little small, the nodes never change size afterwards --
     they were already right -- and the watcher, which only fires on a CHANGE,
     never fires. Two drawing turns later everything is known, and this asks
     each box once. It was 108 px in the worst of the shipped layouts. */
  settleGroups() {
    if (!this.groups.length) return;
    const pass = () => {
      let moved = false;
      for (const group of this.groups) {
        const before = group.bounds.join();
        this._growGroup(group);
        if (group.bounds.join() !== before) moved = true;
      }
      if (moved) this.changed();
    };
    requestAnimationFrame(() => requestAnimationFrame(pass));
    // Plain timers as well, for two reasons. A tab that is not being looked
    // at runs no drawing callbacks at all, so the two lines above never fire
    // there. And the check that adds the "nothing wired in" line to a node
    // comes back from the server after a moment, which is later than any
    // drawing turn. Whichever pass arrives first does the work; the others
    // find nothing left to do and cost nothing.
    setTimeout(pass, 400);
    setTimeout(pass, 1500);
  },

  /* Insert a chunk, offset to a free spot, then select it.

     preserveIds keeps the fragment's own node ids where they are free, which
     matters for tutorials: the step list refers to nodes by name, and the graph
     then matches the JSON shipped in workflows/ exactly. */
  addChunk(chunk, originX, originY, preserveIds = false) {
    this.mark(`add ${chunk.name || 'chunk'}`);
    const mapping = {};
    const created = [];
    for (const node of chunk.graph.nodes) {
      const keep = preserveIds && node.id && !this.nodes.has(node.id) ? node.id : null;
      const made = this.addNode(node.type,
        originX + (node.pos ? node.pos[0] : 0),
        originY + (node.pos ? node.pos[1] : 0),
        node.params || {}, keep);
      if (!made) continue;
      // A block that arrives switched off stays off, as it does when a saved
      // workflow is opened. A tutorial can then ship a part that Run leaves
      // out until somebody switches it on.
      if (node.off) {
        made.off = true;
        this._refreshNodeElement(made);
      }
      mapping[node.id] = made.id;
      created.push(made.id);
    }
    for (const link of chunk.graph.links) {
      if (mapping[link.from_node] && mapping[link.to_node]) {
        this.connect(mapping[link.from_node], link.from_port,
          mapping[link.to_node], link.to_port);
      }
    }
    // A chunk that came with its own coloured box keeps it, offset to wherever
    // it was dropped. Ids are always fresh: two copies of a chunk are two
    // groups, not one shared between them.
    const fresh = [];
    for (const group of chunk.graph.groups || []) {
      const named = (group.nodes || []).map((local) => mapping[local]).filter(Boolean);
      const bounds = this._groupBounds(group, named, originX, originY);
      if (!bounds) continue;
      const box = this.addGroup(group.title, bounds, group.color, null,
        this._chunkMembers(chunk, group, mapping, named));
      // Through the same renaming table the blocks and wires went through.
      // Copied straight, both copies of a chunk dropped twice would have
      // their walls driving the first copy's blocks.
      box.patch = (group.patch || [])
        .map((e) => (mapping[e.node]
          ? { ...e, node: mapping[e.node] } : null))
        .filter(Boolean);
      fresh.push(box);
    }
    this.select(created);
    // How tall a node ends up is not settled the instant it is made: the check
    // that looks for missing inputs runs a moment later and can add a line of
    // its own to every node, which pushes the tallest one out of the bottom of
    // the box that was drawn round it. Wait two drawing turns, then let each
    // new box grow to whatever it is really holding.
    if (fresh.length) this.settleGroups();
    return created;
  },

  /* Which of a chunk's nodes belong to one of its boxes.

     Worked out in the chunk's own coordinates, before it lands. Asking the
     same question after the drop would give the wrong answer whenever the
     chunk came down on top of something: nodes that were already on the canvas
     are standing in the new box too, and there is then no way to tell them
     apart from the ones that arrived with it. */
  _chunkMembers(chunk, group, mapping, named) {
    if (Array.isArray(group.own) && group.own.length) {
      return group.own.map((local) => mapping[local]).filter(Boolean);
    }
    if (named.length) return named;
    if (!Array.isArray(group.bounds) || group.bounds.length !== 4) return [];
    const [gx, gy, gw, gh] = group.bounds;
    return chunk.graph.nodes.filter((node) => {
      const px = node.pos ? node.pos[0] : 0;
      const py = node.pos ? node.pos[1] : 0;
      return px >= gx && py >= gy && px <= gx + gw && py <= gy + gh;
    }).map((node) => mapping[node.id]).filter(Boolean);
  },

  changed() {
    document.getElementById('status-nodes').textContent =
      `${this.nodes.size} nodes · ${this.links.length} links`;
    // Every mutation ends up here, which is why the undo stack is driven from
    // it rather than from each call site: a batch like loading a workflow calls
    // addNode seventy times and must still be one step.
    if (!this._restoring) {
      clearTimeout(this._commitTimer);
      this._commitTimer = setTimeout(() => this.commit(), 120);
    }
    // The sockets on every chunk's title bar depend on the wires and on which
    // blocks are standing in which box, so both kinds of change land here.
    this.refreshAllGroupPorts();
    if (this.onChange) this.onChange();
  },

  /* --------------------------------------------------------- undo/redo */

  /* Name the edit that is about to happen. The label is what the Undo button
     shows; the key is what makes consecutive edits of the same thing merge. */
  mark(label, key = '') {
    // The first caller wins. Deleting five nodes marks "delete 5 nodes" and
    // then calls removeNode five times, each of which would otherwise relabel
    // the step "delete". The outermost intent is the one worth showing.
    if (this._pending.label) return;
    // The selection is captured here rather than at commit time: by then the
    // nodes this step is about may have been removed.
    this._pending = { label, key, sel: [...this.selection] };
  },

  /* The graph without the viewport: panning and zooming are not edits. */
  _snapshot() {
    const data = this.toJSON();
    delete data.view;
    return JSON.stringify(data);
  },

  commit() {
    clearTimeout(this._commitTimer);
    if (this._restoring) return;
    const state = this._snapshot();
    if (state === this._baseline) {
      // Nothing happened after all; do not let the label leak into the next edit.
      this._pending = { label: '', key: '' };
      return;
    }

    const now = performance.now();
    const { label, key, sel } = this._pending;
    const top = this.history.past[this.history.past.length - 1];
    if (key && top && top.key === key && now - top.at < COALESCE_MS) {
      // Same thing being edited again: extend the existing step rather than
      // adding one, so its stored "before" stays the state you want back.
      top.at = now;
    } else {
      this.history.past.push({
        label: label || 'edit', key, at: now,
        state: this._baseline, sel: sel || [...this.selection],
      });
      if (this.history.past.length > HISTORY_LIMIT) this.history.past.shift();
    }
    this.history.future.length = 0;
    this._baseline = state;
    this._pending = { label: '', key: '' };
    if (this.onHistory) this.onHistory();
  },

  canUndo() { return this.history.past.length > 0; },
  canRedo() { return this.history.future.length > 0; },
  undoLabel() {
    const top = this.history.past[this.history.past.length - 1];
    return top ? top.label : '';
  },
  redoLabel() {
    const top = this.history.future[this.history.future.length - 1];
    return top ? top.label : '';
  },

  undo() {
    this.commit();                       // a half-finished edit is still an edit
    const entry = this.history.past.pop();
    if (!entry) return false;
    this.history.future.push({
      label: entry.label, key: entry.key, at: performance.now(),
      state: this._baseline, sel: [...this.selection],
    });
    this._restore(entry.state, entry.sel);
    return true;
  },

  redo() {
    const entry = this.history.future.pop();
    if (!entry) return false;
    this.history.past.push({
      label: entry.label, key: entry.key, at: performance.now(),
      state: this._baseline, sel: [...this.selection],
    });
    this._restore(entry.state, entry.sel);
    return true;
  },

  _restore(state, selection) {
    const view = { ...this.view };       // stay where you are looking
    this._restoring = true;
    try {
      this.fromJSON(JSON.parse(state));
      this.view = view;
      this.applyView();
      this.select((selection || []).filter((id) => this.nodes.has(id)));
    } finally {
      this._restoring = false;
    }
    this._baseline = state;
    this._pending = { label: '', key: '' };
    this.changed();
    // Undo rebuilds every node object, so anything that lives beside the graph
    // rather than in it -- run statuses, previews -- has to be put back.
    if (this.onRestore) this.onRestore();
    if (this.onHistory) this.onHistory();
  },

  /* Start a fresh history from whatever is on the canvas now. Used when a
     session is opened, not when a graph is edited. */
  resetHistory() {
    this.history = { past: [], future: [] };
    this._baseline = this._snapshot();
    this._pending = { label: '', key: '' };
    if (this.onHistory) this.onHistory();
  },

  /* Sessions each keep their own stack; these move it in and out. */
  exportHistory() {
    return { history: this.history, baseline: this._baseline };
  },

  importHistory(saved) {
    if (saved && saved.history) {
      this.history = saved.history;
      this._baseline = saved.baseline;
    } else {
      this.history = { past: [], future: [] };
      this._baseline = this._snapshot();
    }
    this._pending = { label: '', key: '' };
    if (this.onHistory) this.onHistory();
  },

  /* ------------------------------------------------------- node element */
  _buildNode(node) {
    const def = this.defs[node.type];
    const el = UI.el('div', { class: 'node', 'data-id': node.id });
    // Notes are drawn as wide cards rather than towers -- see .note-card in
    // style.css for why.
    if (node.type === 'util.note') el.classList.add('note-card');
    node._el = el;
    this._watchSize(node);
    el.style.left = `${node.pos[0]}px`;
    el.style.top = `${node.pos[1]}px`;
    if (def.preview) {
      el.classList.add('has-preview');
      el.style.width = `${NodePreview.display(node).width}px`;
    }

    const header = UI.el('header', {}, [
      UI.el('span', { class: 'dot' }),
      UI.el('span', { class: 'title', text: node.title || def.title, title: def.description }),
      UI.el('button', {
        class: 'collapse setup', text: '⚙',
        title: 'Set this node up step by step, with everything explained',
        onclick: (event) => { event.stopPropagation(); Forms.setup(node); },
        // Without this the header's own handler starts dragging the node the
        // moment the button is pressed, so opening the panel nudges the node.
        onmousedown: (event) => event.stopPropagation(),
      }),
      UI.el('button', {
        class: 'collapse', text: node.collapsed ? '+' : '−', title: 'collapse',
        onclick: (event) => {
          event.stopPropagation();
          node.collapsed = !node.collapsed;
          this._refreshNodeElement(node);
          this.drawWires();
        },
      }),
    ]);
    header.style.background = this._headerColor(def.color);
    header.addEventListener('mousedown', (event) => this._startNodeDrag(event, node));
    header.addEventListener('dblclick', () => {
      const name = prompt('Node title', node.title || def.title);
      if (name !== null) {
        node.title = name.trim() || def.title;
        header.querySelector('.title').textContent = node.title;
      }
    });
    el.appendChild(header);

    const body = UI.el('div', { class: 'body' });

    const ports = UI.el('div', { class: 'ports' });
    const inputs = UI.el('div', { class: 'col inputs' });
    const outputs = UI.el('div', { class: 'col outputs' });
    for (const port of def.inputs) {
      if (this.portShown(node, port)) inputs.appendChild(this._buildPort(node, port, 'in'));
    }
    for (const port of def.outputs) {
      if (this.portShown(node, port)) outputs.appendChild(this._buildPort(node, port, 'out'));
    }
    ports.appendChild(inputs);
    ports.appendChild(outputs);
    body.appendChild(ports);

    const shown = def.params.filter((p) => this.paramShown(node, p));
    const placed = shown.map((p) => ({ param: p, ...this._placement(node, p) }));
    const basic = placed.filter((x) => !x.advanced).map((x) => x.param);
    const advanced = placed.filter((x) => x.advanced);
    if (node.type === 'util.mdp') {
      // Where the settings come from, then what they add up to in words, and
      // only then the boxes: the card is what somebody looking at a finished
      // graph wants first, and in raw mode it explains the text under it.
      const head = basic.filter((p) => ['mode', 'preset', 'path'].includes(p.name));
      const rest = basic.filter((p) => !head.includes(p));
      if (head.length) body.appendChild(this._buildWidgets(node, head));
      body.appendChild(this._buildMdpSummary(node));
      if (rest.length) body.appendChild(this._buildWidgets(node, rest));
    } else if (basic.length) {
      body.appendChild(this._buildWidgets(node, basic));
    }
    if (advanced.length) body.appendChild(this._buildAdvanced(node, advanced));

    // The picture goes under the parameters and above the status lines, so a
    // note or an error is never hidden behind it.
    if (def.preview) body.appendChild(NodePreview.build(node, def));

    body.appendChild(UI.el('div', { class: 'node-progress hidden' }));
    body.appendChild(UI.el('div', { class: 'node-notes hidden' }));
    body.appendChild(UI.el('div', { class: 'node-error hidden' }));

    el.appendChild(body);
    if (def.preview && !node.collapsed) el.appendChild(this._buildResizeGrip(node));
    if (node.collapsed) el.classList.add('collapsed');
    if (node.pause) el.classList.add('pauses');
    if (node.off) el.classList.add('off');
    if (node._z) el.style.zIndex = String(node._z);

    // Ctrl + Alt + click anywhere on the block switches it off or back on.
    // Caught on the way in, before the title bar starts dragging the block or
    // a box inside it takes the click.
    el.addEventListener('mousedown', (event) => {
      if (!this.offChordHeld(event)) return;
      event.preventDefault();
      event.stopPropagation();
      this.toggleOff(this.selection.has(node.id) ? this.selected() : [node.id]);
    }, true);

    el.addEventListener('mousedown', (event) => {
      if (event.target.closest('.port')) return;
      // Lifted whether or not this changes the selection: clicking a node
      // that is already selected is still you saying "this one".
      this.raise(node.id);
      if (!this.selection.has(node.id)) {
        this.select([node.id], additive(event));
      }
    });
    el.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      // Right-clicking inside a selection asks about the selection, not about
      // the one node under the pointer. Resetting it here meant every
      // multi-node menu entry -- group, save as chunk, duplicate -- silently
      // applied to one node.
      if (!this.selection.has(node.id)) this.select([node.id], additive(event));
      this._nodeMenu(event, node);
    });
    return el;
  },

  /* Whether a box goes on the face of the node or into its drawer, and under
     which heading there. In raw mode the run-parameters block shows its text
     and a summary of it; the value boxes, which only change lines of that
     text, move into the drawer under "Main settings" instead of repeating
     the text beside it. */
  _placement(node, param) {
    if (node.type === 'util.mdp' && (node.params || {}).mode === 'raw'
        && !param.advanced && mdpKey(param.name)) {
      return { advanced: true, section: 'Main settings' };
    }
    return { advanced: Boolean(param.advanced), section: param.section || '' };
  },

  /* The drawer of less usual boxes.

     It says how many of them have actually been filled in. A workflow
     somebody hands you can set half a dozen of them, and a closed drawer that
     says only "advanced (6)" looks the same whether they are all at their
     defaults or all changed, so the settings doing the work would be the
     ones you cannot see. The names go in the tooltip; the count goes on the
     line, where it costs no height.

     Boxes that name a section get a small drawer of their own inside it, so
     opening "advanced" on the run parameters shows a dozen headings rather
     than fifty boxes. */
  _buildAdvanced(node, advanced) {
    const params = advanced.map((x) => x.param);
    const changed = params.filter((p) => this.paramSet(node, p));
    const details = this._drawer(node, 'advanced', 'advanced',
      changed.length ? `advanced (${params.length}) · ${changed.length} set`
        : `advanced (${params.length})`,
      changed.length ? 'not at its default: ' + changed.map((p) => p.label).join(', ')
        : 'all at their defaults');
    const loose = advanced.filter((x) => !x.section).map((x) => x.param);
    if (loose.length) details.appendChild(this._buildWidgets(node, loose));
    const order = [];
    for (const x of advanced) if (x.section && !order.includes(x.section)) order.push(x.section);
    for (const section of order) {
      const inside = advanced.filter((x) => x.section === section).map((x) => x.param);
      const set = inside.filter((p) => this.paramSet(node, p));
      const drawer = this._drawer(node, `section:${section}`, 'section',
        `${section} (${inside.length})${set.length ? ` · ${set.length} set` : ''}`,
        set.length ? 'not at its default: ' + set.map((p) => p.label).join(', ') : '');
      drawer.appendChild(this._buildWidgets(node, inside));
      details.appendChild(drawer);
    }
    return details;
  },

  /* One drawer. Whether it is open is kept on the node, because every change
     to a box that shows or hides others builds the node again, and drawers
     that snapped shut each time would have to be reopened after every
     edit. */
  _drawer(node, key, cls, text, title) {
    const details = UI.el('details', { class: cls }, [UI.el('summary', { text, title })]);
    if (!node._drawers) node._drawers = new Set();
    if (node._drawers.has(key)) details.open = true;
    details.addEventListener('toggle', () => {
      if (details.open) node._drawers.add(key); else node._drawers.delete(key);
    });
    return details;
  },

  /* The card on the run-parameters block that says in words what its
     settings add up to (mdpSummary above), with anything GROMACS would
     refuse or warn about in red under it. */
  _buildMdpSummary(node) {
    const summary = mdpSummary(node);
    const card = UI.el('div', { class: 'mdp-summary' }, [
      UI.el('div', { class: 'mdp-summary-title' }, [
        UI.el('b', { text: summary.title }),
        UI.el('span', { class: 'mdp-summary-source',
                        text: summary.source ? ` · ${summary.source}` : '' }),
      ]),
    ]);
    for (const line of summary.lines) card.appendChild(UI.el('div', { text: line }));
    for (const line of summary.warnings) {
      card.appendChild(UI.el('div', { class: 'mdp-summary-warn', text: line }));
    }
    return card;
  },

  /* Redraw a node once the click that ended an edit has landed. A box you
     type in commits when you leave it, and redrawing there and then would
     rebuild the box you were moving to under the pointer, so the click that
     should have put you in it would go nowhere. */
  _refreshSoon(node) {
    clearTimeout(node._refreshTimer);
    node._refreshTimer = setTimeout(() => {
      if (node._el && this.nodes.get(node.id) === node) this._refreshNodeElement(node);
    }, 0);
  },

  /* Drag the corner of a preview node to make the picture bigger. Only
     preview nodes get one: every other node is as tall as its widgets. */
  _buildResizeGrip(node) {
    const grip = UI.el('div', { class: 'node-resize', title: 'Drag to resize' });
    grip.addEventListener('mousedown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const display = NodePreview.display(node);
      const start = { x: event.clientX, y: event.clientY, w: display.width, h: display.height };
      const scale = () => this.view.scale || 1;
      const move = (moveEvent) => {
        NodePreview.resize(node,
          start.w + (moveEvent.clientX - start.x) / scale(),
          start.h + (moveEvent.clientY - start.y) / scale());
        node._el.style.width = `${display.width}px`;
        this.drawWires();
      };
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        this.mark(`resize ${node.title}`, `resize:${node.id}`);
        this.changed();
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });
    return grip;
  },

  _headerColor(hex) {
    return `linear-gradient(180deg, ${hex}, ${hex}cc)`;
  },

  _buildPort(node, port, direction) {
    const type = portType(node, port);
    // Pointing at a socket, or at its name, says what kind of file goes
    // through it and what is in one: most people meeting a tpr for the first
    // time have no way to guess.
    const about = `${fileAbout(port.label, type, port.name)}\n\n`
      + (direction === 'in'
        ? 'Double-click to unplug it.'
        : 'Double-click to put it on the right-hand wall of its box.');
    const dot = UI.el('span', {
      class: 'port',
      'data-node': node.id, 'data-port': port.name,
      'data-dir': direction, 'data-type': type,
      title: about,
    });
    dot.style.background = PORT_COLORS[type] || PORT_COLORS.any;
    dot.addEventListener('mousedown', (event) => this._startLinkDrag(event, node, port, direction));
    dot.addEventListener('dblclick', (event) => {
      event.stopPropagation();
      if (direction === 'in') this.disconnect(node.id, port.name);
      else this.toggleOnRightWall(node, port);
    });

    const row = UI.el('div', {
      class: `port-row${port.optional ? ' optional' : ''}`,
    }, [dot, UI.el('span', { class: 'label', text: port.label, title: about })]);
    return row;
  },

  /* Whether one of a node's boxes is shown at all.

     A box can say `when: "source=the Protein Data Bank"`, and then it appears
     only while the box called `source` holds that value. Several values are
     separated by |. It is how one node offers a file chooser or a database
     code without showing both at once -- which is how somebody fills in the
     wrong one, or never notices the second is there. */
  /* Whether a box holds something other than what it was born with. Used to
     mark the hidden ones that are pulling their weight. */
  paramSet(node, param) {
    const value = (node.params || {})[param.name];
    if (value === undefined || value === null || value === '') return false;
    const fallback = param.default;
    if (fallback === undefined || fallback === null) return true;
    return String(value) !== String(fallback);
  },

  paramShown(node, param) {
    // The run-parameters block reads its rules against the value the run
    // will really use (from a box, the preset, the text or the file),
    // because most of its boxes are empty on purpose.
    if (node.type === 'util.mdp') return mdpShows(node, param);
    return whenHolds(String(param.when || ''), node.params || {});
  },

  /* Same rule for a port: a merged block draws the ports of the choice that
     is picked, not every port of every choice at once. */
  portShown(node, port) {
    return whenHolds(String(port.when || ''), node.params || {});
  },

  _buildWidgets(node, params) {
    const wrap = UI.el('div', { class: 'widgets' });
    for (const param of params) wrap.appendChild(this._buildWidget(node, param));
    return wrap;
  },

  /* Redraw every open node of one type. Used when something the nodes display
     arrives after they were built -- the mdp presets are fetched at boot and
     the nodes drawn before they land would show nothing. */
  refreshOpenNodes(type) {
    for (const node of this.nodes.values()) {
      if (node.type === type && node._el) this._refreshNodeElement(node);
    }
  },

  /* What this widget shows when it is empty. For the run-parameters node that
     is the value the run will actually use rather than the words "preset
     default": the widgets are deltas against a file nobody can see, and a
     delta against an invisible baseline is not something anybody can check. */
  _placeholder(node, param, bare = false) {
    const shown = this._mdpShown(node, param);
    if (!shown) return this._mdpNotSet(node, param) || param.placeholder || '';
    // A dropdown's empty entry is already inside brackets; saying where the
    // value came from a second time inside them reads as a typo.
    return bare || !shown.from ? shown.value : `${shown.value}  (${shown.from})`;
  },

  /* What an empty run-parameters box says when nobody gives it a value: the
     file then leaves the option out, and "preset default" would suggest a
     value that is not there. Only said when the preset's table is at hand to
     be sure of it. define keeps its example, because leaving it out is the
     usual case. */
  _mdpNotSet(node, param) {
    if (node.type !== 'util.mdp' || !mdpKey(param.name) || param.name === 'define') return '';
    const base = mdpBase(node);
    return base ? base.missing : '';
  },

  /* The value an empty run-parameters box stands for, and where it comes
     from: the raw text in raw mode, the preset otherwise, and GROMACS's own
     default where neither sets it. Shown from the moment the node appears, so
     nobody has to edit a box to find out what it holds. Null for every other
     box, and for a box whose value nobody knows. */
  _mdpShown(node, param) {
    if (node.type !== 'util.mdp') return null;
    const key = mdpKey(param.name);
    if (!key) return null;
    const base = mdpBase(node);
    // A file not read yet: it is read when the node runs, whatever this says.
    if (node.params.mode === 'file' && !base) return { value: 'as in the file', from: '' };
    if (base) {
      const value = base.options[mdpSquash(key)];
      if (mdpKnown(value)) return { value: String(value), from: base.from };
    }
    const fallback = ((Editor.mdp || {}).gromacs_defaults || {})[key];
    return mdpKnown(fallback) ? { value: String(fallback), from: 'GROMACS default' } : null;
  },

  _buildWidget(node, param) {
    const value = node.params[param.name];
    // On the run parameters, the option's own name beside the plain words:
    // it is what a published protocol, the manual and an .mdp file call it.
    const key = node.type === 'util.mdp' ? mdpKey(param.name) : '';
    const label = UI.el('label', {}, [
      UI.el('span', param.help ? { class: 'why', title: param.help, text: param.label }
        : { text: param.label }),
      key ? UI.el('span', { class: 'mdp-key', text: key }) : null,
    ]);

    let input;
    const def = this.defs[node.type];
    const commit = (raw) => {
      node.params[param.name] = raw;
      // Keyed so successive edits of this one field collapse into one step.
      this.mark(`${param.label} on ${node.title}`, `param:${node.id}:${param.name}`);
      const followed = this.applyFollows(node, param.name, raw);
      this.changed();
      // Typing a file into a preview node means that file, not whatever the
      // last run left pointed at.
      if (def && def.preview && param.name === 'path') NodePreview.invalidate(node);
      // Picking a file, or naming its type by hand, changes what the output
      // carries -- so the port has to change colour without waiting for a run.
      // Any parameter that could change what the port is carrying repaints
      // it, not only the one the port literally follows: a download typed by
      // its URL has to change colour when the URL does.
      const names = FILE_NAME_PARAMS.concat(['member', 'extract']);
      const carries = (def.outputs || []).some((p) => p.follows === param.name)
        || (names.includes(param.name)
            && (def.outputs || []).some((p) => p.follows));
      // A box other boxes appear and disappear with has to redraw the node,
      // or the ones it controls stay as they were.
      const controls = (def.params || []).some(
        (other) => whenNames(other.when).includes(param.name))
        || (def.inputs || []).concat(def.outputs || []).some(
          (port) => whenNames(port.when).includes(param.name));
      // The empty run-parameter boxes show what the preset, the mode, the raw
      // text or the file says, so a change to any of those has to redraw
      // them too. So does any other box there: the summary card says what
      // they all add up to, and one value can show or hide other boxes (a
      // thermostat's boxes go with the thermostat).
      const mdp = node.type === 'util.mdp';
      if (mdp && param.name === 'path') MdpFiles.forget(raw);
      const shows = mdp && ['preset', 'mode'].includes(param.name);
      if (shows || (!mdp && (followed || carries || controls))) this._refreshNodeElement(node);
      else if (mdp) this._refreshSoon(node);
      if (carries) this.drawWires();
    };

    // "Run this node against that installation" is only usable if you can see
    // what the installations are. The list is whatever actually holds this
    // node's tool, plus -- for GROMACS, whose versions are builds rather than
    // environments -- the builds that were found on disk.
    if (param.name === 'env_override') {
      const choices = App.installChoices(def && def.tool);
      if (choices.length) {
        const listId = `env-${node.id}`;
        input = UI.el('input', {
          type: 'text', list: listId, placeholder: param.placeholder || '',
        });
        input.value = value === null || value === undefined ? '' : String(value);
        input.addEventListener('change', () => commit(input.value));
        const datalist = UI.el('datalist', { id: listId });
        for (const choice of choices) {
          datalist.appendChild(UI.el('option', { value: choice.value, label: choice.label }));
        }
        return UI.el('div', { class: 'widget' }, [label, input, datalist]);
      }
    }

    switch (param.type) {
      case 'bool': {
        input = UI.el('input', { type: 'checkbox' });
        input.checked = !!value;
        input.addEventListener('change', () => commit(input.checked));
        const row = UI.el('div', { class: 'widget inline' }, [label, input]);
        row.insertBefore(input, label);
        return row;
      }
      case 'choice': {
        input = UI.el('select');
        // The blank option reads "(default)" everywhere else; on a preset it
        // can say which default, which is the whole question.
        const blank = this._placeholder(node, param, true);
        const choices = param.choices.map(String);
        // A saved graph can name something this machine has not got: a force
        // field installed on the machine it was built on, a version since
        // removed. Dropping it would leave the box blank and quietly change
        // what the graph does, so it is kept and marked instead.
        let now = value === null || value === undefined ? '' : String(value);
        // A run parameter written another way (v-rescale for V-rescale) is
        // the same value to GROMACS, and is picked as such rather than added
        // as a second entry. One the list does not have is still a value
        // GROMACS may know, not something missing from this machine.
        const mdp = node.type === 'util.mdp';
        if (mdp && now) now = choices.find((c) => c && mdpSame(c, now)) || now;
        if (now && !choices.includes(now)) choices.unshift(now);
        for (const choice of choices) {
          input.appendChild(UI.el('option', {
            value: choice,
            text: (choice && !param.choices.map(String).includes(choice))
              ? (mdp ? choice : `${choice} (not on this machine)`)
              : (choice || (blank ? `(${blank})` : '(default)')),
          }));
        }
        input.value = now;
        input.addEventListener('change', () => commit(input.value));
        break;
      }
      case 'combo': {
        const listId = `dl-${node.id}-${param.name}`;
        input = UI.el('input', { type: 'text', list: listId,
                                 placeholder: this._placeholder(node, param) });
        input.value = value === null || value === undefined ? '' : String(value);
        input.addEventListener('change', () => commit(input.value));
        const datalist = UI.el('datalist', { id: listId });
        for (const choice of param.choices) {
          datalist.appendChild(UI.el('option', { value: String(choice) }));
        }
        return this._wrapWidget(node, param, [label, input, datalist]);
      }
      case 'text': {
        const body = value === null || value === undefined ? '' : String(value);
        input = UI.el('textarea', { rows: String(param.rows || 4),
                                    placeholder: this._placeholder(node, param) });
        input.value = body;
        input.addEventListener('change', () => commit(input.value));
        /* A box marked "grow" takes the height of what is in it. Six rows and
           a scrollbar is right for something you fill in and wrong for a note
           somebody wrote for you to read: the reader gets the first four
           lines and finds the rest by accident.

           Measured rather than counted, because the number of lines you typed
           is not the number the box shows -- a 72-character line wraps into
           two in a 214 px column. Capped, so one very long note cannot push
           everything below it off the screen. */
        if (param.grow) {
          // Never smaller than the rows it asked for: an empty note you are
          // about to write in should not be one line high.
          input.rows = growRows(body, param.rows || 4);
          const floor = (param.rows || 4) * GROW_LINE_PX + GROW_PAD_PX;
          const fit = () => {
            // Nothing to read while the page is not being drawn, and reading
            // it anyway would collapse the box to nothing.
            if (!input.scrollHeight) return;
            input.style.height = 'auto';
            input.style.height = Math.min(GROW_MAX_PX,
              Math.max(floor, input.scrollHeight + 4)) + 'px';
          };
          input.addEventListener('input', fit);
          // Then the exact height, once the page has been laid out.
          requestAnimationFrame(fit);
        }
        // The Extra flags box is the one widget whose contents are a language
        // -- the flags of whatever command this node runs -- so it carries
        // that command's own list underneath it.
        if (param.name === 'extra_flags' && def && def.flag_hint) {
          return this._wrapWidget(node, param,
            [label, input, FlagReference.build(def.flag_hint, def, input, commit)]);
        }
        break;
      }
      case 'int':
      case 'float': {
        input = UI.el('input', {
          type: 'number',
          step: param.step !== null && param.step !== undefined ? String(param.step)
            : (param.type === 'int' ? '1' : 'any'),
          placeholder: this._placeholder(node, param),
        });
        if (param.min !== null && param.min !== undefined) input.min = String(param.min);
        if (param.max !== null && param.max !== undefined) input.max = String(param.max);
        input.value = value === null || value === undefined ? '' : String(value);
        input.addEventListener('change', () => {
          if (input.value === '') { commit(''); return; }
          commit(param.type === 'int' ? parseInt(input.value, 10) : parseFloat(input.value));
        });
        break;
      }
      case 'file': {
        // The class is how the drop handling tells a box meant for a path from
        // a box meant for typing in.
        input = UI.el('input', {
          type: 'text', class: 'file-box', placeholder: param.placeholder || '',
        });
        input.value = value === null || value === undefined ? '' : String(value);
        input.addEventListener('change', () => {
          // A file:// URL is what a browser writes when it inserts a dragged
          // file as text, and what you get from copying an address. It is a
          // path with a scheme on the front; treat it as one.
          input.value = App.normalisePath(input.value);
          commit(input.value);
        });
        const browse = UI.el('button', {
          class: 'small', text: '…', title: 'browse',
          onclick: (event) => {
            event.stopPropagation();
            // Opened at whatever the box already holds, so a file three
            // folders deep is one click away rather than four.
            Panels.browseFile((path) => { input.value = path; commit(path); },
                              App.normalisePath(input.value || ''));
          },
        });
        // A file dropped straight onto the box fills it in -- the shortest
        // path from "that one, there" to a node that reads it. Anything from
        // outside the browser counts, whatever the browser admits to carrying;
        // without preventDefault here Firefox writes the file:// URL in as
        // text and the node is handed something it cannot open.
        const fromOutside = (event) =>
          App.dragSource !== 'page' || App.dragCarriesFiles(event);
        input.addEventListener('dragover', (event) => {
          if (!fromOutside(event)) return;
          event.preventDefault();
          event.stopPropagation();
          input.classList.add('drop-target');
        });
        input.addEventListener('dragleave', () => input.classList.remove('drop-target'));
        input.addEventListener('drop', async (event) => {
          if (!fromOutside(event)) return;
          event.preventDefault();
          event.stopPropagation();
          input.classList.remove('drop-target');
          const path = await App.onePathFromDrop(event.dataTransfer);
          if (!path) return;
          input.value = path;
          commit(path);
        });
        const row = UI.el('div', { class: 'row' }, [input, browse]);
        return this._wrapWidget(node, param, [label, row]);
      }
      default: {
        input = UI.el('input', { type: 'text',
                                 placeholder: this._placeholder(node, param) });
        // A value the run will really use, not an example of what to type:
        // drawn to be read, not to fade into the box.
        if (this._mdpShown(node, param)) input.classList.add('known-value');
        input.value = value === null || value === undefined ? '' : String(value);
        input.addEventListener('change', () => commit(input.value));
      }
    }
    input.addEventListener('mousedown', (event) => event.stopPropagation());
    return this._wrapWidget(node, param, [label, input]);
  },

  /* The finished widget, with a way into its form if it has one.

     A box that wants a small language -- a membrane description, a list of
     lipids, the answers a tool reads from the keyboard -- says so in its
     description, and gets a button that opens a form asking the same thing in
     questions. The box itself stays exactly as it was: typing is still faster
     for anybody who knows the words. */
  _wrapWidget(node, param, parts) {
    const widget = UI.el('div', { class: 'widget', 'data-param': param.name }, parts);

    /* A helper button under one particular box, for the boxes where a picture
       answers the question better than a number does. Right-clicking the node
       offers the same thing, but a menu you have to know is there is a menu
       most people never open. */
    const helper = PARAM_HELPERS[`${node.type}:${param.name}`];
    if (helper) {
      const open = UI.el('button', {
        class: 'small form-open', text: helper.label, title: helper.title,
        onclick: (event) => { event.stopPropagation(); helper.open(node); },
      });
      open.addEventListener('mousedown', (event) => event.stopPropagation());
      widget.appendChild(open);
    }

    // `const Forms` in another file is a global name, not a property of
    // window, so this is how you ask whether that file loaded.
    if (typeof Forms === 'undefined' || !Forms.hasField(param.form)) return widget;
    const button = UI.el('button', {
      class: 'small form-open', text: 'Fill this in with a form…',
      title: 'Answer some questions instead of typing this',
      onclick: (event) => {
        event.stopPropagation();
        Forms.openField(node, param);
      },
    });
    button.addEventListener('mousedown', (event) => event.stopPropagation());
    widget.appendChild(button);
    return widget;
  },

  _refreshNodeElement(node) {
    const old = node._el;
    // The box being typed in, by name, so it can have the focus back.
    const active = typeof document !== 'undefined' ? document.activeElement : null;
    const holder = old && active && old.contains && old.contains(active) && active.closest
      ? active.closest('[data-param]') : null;
    const focused = holder ? holder.getAttribute('data-param') : '';
    this._unwatchSize(old);
    const fresh = this._buildNode(node);
    // Watch the new one. Without this line a node stopped being measured the
    // first time it was redrawn -- which is every node of every workflow that
    // is loaded rather than built by hand -- so the box around it never grew
    // when the check added an error line and the tallest node hung out of the
    // bottom. It was 60 px in the worst shipped layout.
    this._watchSize(node);
    if (old) old.replaceWith(fresh); else this.dom.nodes.appendChild(fresh);
    if (this.selection.has(node.id)) fresh.classList.add('selected');
    this.applyNodeStatus(node);
    this.refreshPortStates();
    if (focused && fresh.querySelector) {
      const again = fresh.querySelector(`[data-param="${focused}"] input, `
        + `[data-param="${focused}"] select, [data-param="${focused}"] textarea`);
      if (again) again.focus();
    }
  },

  /* One parameter changing another. Returns true when something else moved,
     so the caller knows the node has to be redrawn. */
  applyFollows(node, name, raw) {
    const table = PARAM_FOLLOWS[node.type] || {};
    const rule = table[name] || (table.anyValue && table.anyValue(name));
    const changes = rule ? rule(node, raw) : null;
    if (!changes) return false;
    Object.assign(node.params, changes);
    return true;
  },

  /* ------------------------------------------------- what a chunk takes in */
  /* Everything a group needs from outside itself, so it can be shown and
     changed in one place instead of by opening each block in turn.

     Two kinds, and they are changed in different ways. A file box names a
     place on disk: you change it by picking another file. A socket is fed by
     a wire from a block outside the group, or by nothing at all: you change
     it by pointing it at a different block.

     Wires from one block in the group to another are left out on purpose.
     Those are how the chunk works, not something coming into it, and listing
     them would bury the two or three that matter under twenty that do not.

     Read in the order the blocks sit on the canvas, left to right and then
     down, because that is the order somebody reads the chunk itself. */
  /* Which blocks a chunk's sockets and its Inputs window are worked out from.

     nodesInGroup asks whether a block sits wholly inside the box, which is
     the right question for "delete this group and its blocks": a rule you can
     see the edge of. It is the wrong question for one moment. A chunk just
     dropped on the canvas lays out over a second or two -- boxes grow as
     their contents arrive -- and while that is happening a block can be
     taller than the box that is about to grow around it, so it counts as
     outside and its sockets show up as things the chunk needs from elsewhere.
     Two seconds of a wrong answer on screen.

     A chunk remembers which blocks it brought with it, so ask that as well
     and the answer is right from the first moment. Dragging a block out of a
     box still takes it out: that list is torn up the moment a block is
     dragged clear. */
  chunkMembers(group) {
    const ids = new Set(this.nodesInGroup(group));
    if (group.own) {
      for (const id of group.own) if (this.nodes.has(id)) ids.add(id);
    }
    return [...ids];
  },

  chunkInputs(group) {
    const inside = new Set(this.chunkMembers(group));
    const order = [...inside].map((id) => this.nodes.get(id)).filter(Boolean)
      .sort((a, b) => (a.pos[0] - b.pos[0]) || (a.pos[1] - b.pos[1]));
    // Two blocks of the same kind in one chunk -- and there usually are, an
    // analysis chunk has three of the same measuring block -- are told apart
    // by where they sit, counted the way they are read.
    const seen = new Map();
    for (const node of order) seen.set(node.title, (seen.get(node.title) || 0) + 1);
    const nth = new Map();
    const ordinal = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th'];
    const whichOne = (node) => {
      if ((seen.get(node.title) || 0) < 2) return '';
      const n = (nth.get(node.title) || 0) + 1;
      nth.set(node.title, n);
      return ` (${ordinal[n - 1] || `${n}th`} of ${seen.get(node.title)})`;
    };

    const files = [];
    const sockets = [];
    for (const node of order) {
      const def = this.defs[node.type];
      if (!def) continue;
      const which = whichOne(node);
      // A block with no sockets at all reads its file from disk and nothing
      // else: that box IS what the chunk takes in, and an empty one is the
      // thing still to be filled in. A block that also has sockets offers its
      // file box as an alternative to a wire -- "Or a file" on the preview
      // blocks -- and an empty one there is simply the wire being used, which
      // is not something anybody needs reminding of.
      const readsOnly = (def.inputs || []).length === 0;
      for (const param of def.params || []) {
        if (param.type !== 'file' || !this.paramShown(node, param)) continue;
        const held = (node.params || {})[param.name];
        const value = held === null || held === undefined ? '' : String(held);
        files.push({ node, param, value, which,
                     kind: value ? 'named' : (readsOnly ? 'missing' : 'spare') });
      }
      for (const port of def.inputs || []) {
        if (!this.portShown(node, port)) continue;
        const link = this.links.find(
          (l) => l.to_node === node.id && l.to_port === port.name);
        if (link && inside.has(link.from_node)) continue;
        sockets.push({
          node, port, which, link: link || null,
          kind: link ? 'fed' : (port.optional ? 'spare' : 'missing'),
        });
      }
    }
    return { files, sockets };
  },

  /* What a chunk hands out: an output socket of a block inside it that
     nothing inside it uses.

     A block feeding another block in the same chunk is plumbing, so its
     socket is not on offer -- grompp's run file goes to mdrun and stays
     there. What is left is what a chunk is for: the trajectory and the run
     file at the end of a production chunk, the structure at the end of a
     preparation one. A socket already wired to something outside stays on
     the list whatever else is true of it, because it is plainly in use and
     you have to be able to see it and move it. */
  chunkOutputs(group) {
    const inside = new Set(this.chunkMembers(group));
    const order = [...inside].map((id) => this.nodes.get(id)).filter(Boolean)
      .sort((a, b) => (a.pos[0] - b.pos[0]) || (a.pos[1] - b.pos[1]));
    const out = [];
    for (const node of order) {
      const def = this.defs[node.type];
      if (!def) continue;
      for (const port of def.outputs || []) {
        if (!this.portShown(node, port)) continue;
        const going = this.links.filter(
          (l) => l.from_node === node.id && l.from_port === port.name);
        if (going.some((l) => inside.has(l.to_node))) continue;
        out.push({ node, port, used: going.length > 0 });
      }
    }
    return out;
  },

  /* Every socket outside the group that could feed this one. Same rule the
     canvas uses when it marks the sockets while you drag a wire, so the list
     and the highlighting can never disagree.

     That rule is deliberately loose: a socket that says only "a file" will
     take anything, so a log file is offered for an index. On the canvas that
     is fine, because you are already pointing at the one you meant. In a list
     it is noise, so each one says whether it is the kind that was asked for
     or merely something the socket would not refuse, and the exact ones come
     first. */
  chunkSourcesFor(group, port) {
    const inside = new Set(this.chunkMembers(group));
    const wanted = port.type;
    const found = [];
    for (const node of this.nodes.values()) {
      if (inside.has(node.id)) continue;
      const def = this.defs[node.type];
      if (!def) continue;
      for (const out of def.outputs || []) {
        if (!this.portShown(node, out)) continue;
        const carries = portType(node, out);
        if (!typesCompatible(carries, wanted)) continue;
        found.push({ node, port: out, carries, exact: carries === wanted });
      }
    }
    return found.sort((a, b) => (Number(b.exact) - Number(a.exact))
                             || (a.node.pos[0] - b.node.pos[0])
                             || (a.node.pos[1] - b.node.pos[1]));
  },

  /* Set a parameter from outside the widget that owns it -- a dialog, a menu --
     with the same follow-on rules and the same redraw. */
  setParam(node, name, value, label = '') {
    node.params[name] = value;
    this.mark(label || `${name} on ${node.title}`);
    this.applyFollows(node, name, value);
    this._refreshNodeElement(node);
    this.changed();
  },

  /* --------------------------------------------------------- selection */

  /* Shift is the editor\'s own convention; Ctrl and Cmd are everyone else\'s,
     and a file manager teaches Ctrl-click long before a node editor does. */
  /* Nodes are drawn in the order they were added, so one added later covers
     one added earlier -- and clicking the covered one did not change that.
     A node underneath another was unreachable: you could see a corner of it
     and not get at its boxes.

     Clicking or selecting now lifts it. The counter only ever goes up;
     nothing has to be put back down, because the whole rule is "the one you
     touched last is on top". It is kept on the node rather than only on the
     element, so re-drawing the node -- which happens whenever one of its
     boxes changes -- does not drop it back underneath. */
  _stackTop: 10,

  raise(ids) {
    for (const id of [].concat(ids)) {
      const node = this.nodes.get(id);
      if (!node) continue;
      node._z = ++this._stackTop;
      if (node._el) node._el.style.zIndex = String(node._z);
    }
  },

  select(ids, additive = false) {
    // Only the ones that were not already selected, so dragging a rubber band
    // over the canvas does not restack everything it touches on every mouse
    // move.
    const fresh = [].concat(ids).filter((id) => !this.selection.has(id));
    if (!additive) {
      this.selection.clear();
      this.selectedGroups.clear();
    }
    for (const id of [].concat(ids)) this.selection.add(id);
    this.raise(fresh);
    for (const node of this.nodes.values()) {
      if (node._el) node._el.classList.toggle('selected', this.selection.has(node.id));
    }
    this.paintGroupSelection();
    if (this.onSelect) this.onSelect([...this.selection]);
  },

  /* Select the box itself. Its contents come too, because that is what you
     meant by clicking it, but the box is now something Delete can see. */
  selectGroup(id, additive = false) {
    const group = this.groups.find((g) => g.id === id);
    if (!group) return;
    this.select(this.nodesInGroup(group), additive);
    this.selectedGroups.add(id);
    this.paintGroupSelection();
  },

  paintGroupSelection() {
    for (const group of this.groups) {
      if (group._el) group._el.classList.toggle('selected', this.selectedGroups.has(group.id));
    }
  },

  selected() { return [...this.selection]; },
  selectedGroupIds() { return [...this.selectedGroups]; },

  duplicateSelection() {
    this.mark('duplicate');
    const mapping = {};
    const made = [];
    for (const id of this.selection) {
      const node = this.nodes.get(id);
      if (!node) continue;
      const copy = this.addNode(node.type, node.pos[0] + 30, node.pos[1] + 30,
        JSON.parse(JSON.stringify(node.params)));
      if (copy) { mapping[id] = copy.id; made.push(copy.id); }
    }
    for (const link of [...this.links]) {
      if (mapping[link.from_node] && mapping[link.to_node]) {
        this.connect(mapping[link.from_node], link.from_port,
          mapping[link.to_node], link.to_port);
      }
    }
    this.select(made);
  },


  /* The file a node is ultimately looking at, following the wires back.

     A cleaning node is where you type chain letters and it has no file of its
     own -- the file is one or two nodes upstream. Walking back is what makes
     "what is in it?" answerable from the node that needs the answer. */
  /* A PDB code typed where a file name goes -- "1AKI" -- means the deposited
     structure, not a file. The same rule the node itself uses: a name with a
     slash or a dot in it is a path, and only the shape of a real code counts,
     so a short file name is not mistaken for one. */
  pdbCode(raw) {
    const text = String(raw || '').trim();
    const bare = /^pdb:/i.test(text) ? text.slice(4).trim() : text;
    if (!bare || /[\\/.]/.test(bare)) return '';
    return (/^[1-9][A-Za-z0-9]{3}$/.test(bare)
            || /^pdb_[0-9]{4}[A-Za-z0-9]{4}$/.test(bare)) ? bare : '';
  },

  structureSource(nodeId, seen = new Set()) {
    const node = this.nodes.get(nodeId);
    if (!node || seen.has(nodeId)) return null;
    seen.add(nodeId);
    const params = node.params || {};
    const id = String(params.pdb_id || '').trim()
      || Editor.pdbCode(params.path || '');
    if (id) {
      return { pdb: id, format: params.format || 'pdb',
               label: `${id.toUpperCase()} from RCSB`, node: nodeId };
    }
    const path = App.normalisePath(params.path || '');
    if (path) {
      return { path, label: path.split('/').pop(), node: nodeId };
    }
    // Follow the inputs, structure ports first: a grompp node has an mdp and a
    // topology wired in too, and neither of those is what was being asked about.
    const def = this.defs[node.type] || {};
    const ports = [...(def.inputs || [])].sort((a, b) => {
      const rank = (port) => (port.type === 'structure' ? 0
        : (port.type === 'traj' ? 1 : (port.type === 'any' || port.type === 'file' ? 2 : 3)));
      return rank(a) - rank(b);
    });
    for (const port of ports) {
      const link = this.links.find((l) => l.to_node === nodeId && l.to_port === port.name);
      if (!link) continue;
      const found = this.structureSource(link.from_node, seen);
      if (found) return found;
    }
    return null;
  },

  /* ------------------------------------------------------------- groups */

  /* A coloured box with a name on it. It owns no nodes: what is inside is
     whatever is standing inside its bounds when you ask, so dragging a node
     into one puts it in and dragging it out takes it out, with nothing to
     keep in step. */
  addGroup(title, bounds, color = DEFAULT_GROUP_COLOR, id = null, own = null) {
    const group = {
      id: id && !this.groups.some((g) => g.id === id) ? id : `g${this.groupCounter++}`,
      title: title || 'group',
      color: color || DEFAULT_GROUP_COLOR,
      bounds: bounds.map((v) => Math.round(v)),
      /* The nodes that arrived with this box, if anybody said so.
         Empty is the normal case and means "whatever is standing inside".
         See ownerOf for why some boxes need to remember. */
      own: new Set(own || []),
    };
    this.groups.push(group);
    this.dom.groups.appendChild(this._buildGroup(group));
    this.changed();
    return group;
  },

  removeGroup(id) {
    const group = this.groups.find((g) => g.id === id);
    if (!group) return;
    this.mark(`ungroup ${group.title}`);
    if (group._el) group._el.remove();
    this.groups = this.groups.filter((g) => g.id !== id);
    this.selectedGroups.delete(id);
    // The box is gone, so its nodes belong to nobody; whichever box they are
    // standing in now takes them, which is what "remove group, keep nodes"
    // has always meant.
    if (group.own) group.own.clear();
    this.changed();
  },

  /* Wrap the selection in a new group. */
  groupSelection(title) {
    const ids = [...this.selection];
    if (!ids.length) { UI.toast('select some nodes first', 'warn'); return null; }
    const box = this._boundsOf(ids);
    if (!box) return null;
    this.mark('group selection');
    const group = this.addGroup(title || 'group', [
      box.minX - GROUP_PAD,
      box.minY - GROUP_PAD - GROUP_TITLE_H,
      box.maxX - box.minX + GROUP_PAD * 2,
      box.maxY - box.minY + GROUP_PAD * 2 + GROUP_TITLE_H,
    ], GROUP_COLORS[(this.groups.length) % GROUP_COLORS.length][1], null, ids);
    return group;
  },

  /* Where a group's box goes.

     A graph written by hand -- a chunk, a shipped workflow -- cannot know how
     tall a node renders, because that depends on its widgets. Such a group
     names its members instead and the editor measures them once they are on
     the canvas. Groups saved from the editor carry real bounds and are used
     as they are. */
  _groupBounds(group, ids, originX = 0, originY = 0) {
    if (ids && ids.length) {
      const box = this._boundsOf(ids);
      if (box) {
        return [
          box.minX - GROUP_PAD,
          box.minY - GROUP_PAD - GROUP_TITLE_H,
          box.maxX - box.minX + GROUP_PAD * 2,
          box.maxY - box.minY + GROUP_PAD * 2 + GROUP_TITLE_H,
        ];
      }
    }
    if (Array.isArray(group.bounds) && group.bounds.length === 4) {
      return [originX + group.bounds[0], originY + group.bounds[1],
              group.bounds[2], group.bounds[3]];
    }
    return null;
  },

  /* Somewhere this box fits without landing on what is already there.

     Dropping a recipe at the middle of the view is right on an empty canvas
     and wrong on a full one: five nodes appear on top of five others and the
     only clue is that the wires look wrong. This walks down the canvas from
     the preferred spot until nothing overlaps. Down rather than right because
     a graph grows left to right, so the space below is the space nobody is
     using yet. */
  freeSpot(width, height, x, y, gap = 60) {
    const boxes = [];
    for (const node of this.nodes.values()) {
      if (!node._el) continue;
      boxes.push([node.pos[0], node.pos[1],
                  node._el.offsetWidth, node._el.offsetHeight]);
    }
    if (!boxes.length) return { x, y };
    const clear = (ox, oy) => !boxes.some(([bx, by, bw, bh]) =>
      ox < bx + bw + gap && ox + width + gap > bx
      && oy < by + bh + gap && oy + height + gap > by);
    if (clear(x, y)) return { x, y };
    // Bounded: a canvas with a node every 100px for 200 tries is not a canvas
    // anyone is working on, and an unbounded loop would hang the editor.
    for (let step = 1; step <= 200; step += 1) {
      const oy = y + step * (height + gap);
      if (clear(x, oy)) return { x, y: oy };
    }
    return { x, y };
  },

  _boundsOf(ids) {
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    let found = false;
    for (const id of ids) {
      const node = this.nodes.get(id);
      if (!node || !node._el) continue;
      found = true;
      minX = Math.min(minX, node.pos[0]);
      minY = Math.min(minY, node.pos[1]);
      maxX = Math.max(maxX, node.pos[0] + node._el.offsetWidth);
      maxY = Math.max(maxY, node.pos[1] + node._el.offsetHeight);
    }
    return found ? { minX, minY, maxX, maxY } : null;
  },

  /* Which box does this node belong to, if it was told rather than guessed?

     Boxes normally work out what is theirs by looking: whatever is standing
     inside is inside. That is friendly and it is enough as long as boxes do
     not sit on top of each other. Drop one chunk on top of another and it
     stops being enough -- the newcomer's box is drawn across nodes that came
     with the older one, and from then on both boxes claim them, so dragging
     the new box walks off with somebody else's nodes.

     So a box that was built from a known set of nodes -- a chunk being
     dropped, or "group the selection" -- writes that set down. A node with a
     box of its own is never taken by a second one. A node nobody wrote down
     behaves exactly as before. Drag a node out of its box by hand and the
     note is torn up, so "drag it out and it has left" still holds. */
  ownerOf(node) {
    for (const group of this.groups) {
      if (group.own && group.own.has(node.id)) return group;
    }
    return null;
  },

  /* Dragged clear of the box it came with, so tear up the note. Without this
     a node could still be carried off by a box it is no longer anywhere near,
     and "drag it out and it has left" would stop being true. */
  _releaseIfOutside(id) {
    const node = this.nodes.get(id);
    if (!node) return;
    for (const group of this.groups) {
      if (!group.own || !group.own.has(id)) continue;
      const [x, y, w, h] = group.bounds;
      if (node.pos[0] < x || node.pos[0] > x + w
        || node.pos[1] < y || node.pos[1] > y + h) group.own.delete(id);
    }
  },

  /* Does this node fit wholly inside some group? Then that group owns it.

     Group boxes overlap in real graphs -- a tall narrow one beside a wide flat
     one, and a node standing in the overlap. Without this, a node that plainly
     belongs to the group it fits in would also be dragged by the box it merely
     pokes through. */
  _fitsSomeGroup(node) {
    for (const group of this.groups) {
      const [x, y, w, h] = group.bounds;
      if (node.pos[0] >= x && node.pos[1] >= y
        && node.pos[0] + node._el.offsetWidth <= x + w
        && node.pos[1] + node._el.offsetHeight <= y + h) return true;
    }
    return false;
  },

  /* What a group takes with it: everything standing wholly inside, plus
     anything anchored by its top-left corner that fits in no group at all.

     Nodes change size after they are placed. A chunk is measured the instant
     it is dropped and the check that runs a moment later adds an error line to
     every node in it, 28 px each, so the tallest ends up hanging out of the
     bottom of a box that was drawn round the smaller ones. Strict containment
     then leaves that node standing where it was when the group is dragged --
     which is the bug this fixes, and it affected 31 of the 32 groups in the
     shipped chunks.

     The corner is the right anchor because a node grows right and down: where
     it starts does not move when it gets bigger. And "fits in no group at all"
     is what keeps a box from stealing a node that has a home of its own. */
  nodesAnchoredIn(group) {
    const [x, y, w, h] = group.bounds;
    const inside = [];
    for (const node of this.nodes.values()) {
      if (!node._el) continue;
      // A node this box was built from comes with it wherever it has got to,
      // and a node another box was built from is never taken.
      const owner = this.ownerOf(node);
      if (owner) { if (owner === group) inside.push(node.id); continue; }
      // Judged by its middle, not its corner. A wide card -- a note, say --
      // standing beside a box used to be adopted the moment its corner
      // crossed the edge, and the box then grew around it and over the next
      // box along. The middle being inside is what "in the box" looks like.
      const cx = node.pos[0] + node._el.offsetWidth / 2;
      const cy = node.pos[1] + node._el.offsetHeight / 2;
      if (!(cx >= x && cx <= x + w && cy >= y && cy <= y + h)) continue;
      const fits = node.pos[0] >= x && node.pos[1] >= y
        && node.pos[0] + node._el.offsetWidth <= x + w
        && node.pos[1] + node._el.offsetHeight <= y + h;
      if (fits || !this._fitsSomeGroup(node)) inside.push(node.id);
    }
    return inside;
  },

  /* Grow a group until nothing it holds is hanging out of it.

     A loop because growing can bring another node inside the box, and only
     grows: a group somebody made small on purpose holds nothing it is not
     already big enough for, and "Fit to contents" is there for tidying up. */
  _growGroup(group) {
    let grew = false;
    for (let pass = 0; pass < 8; pass += 1) {
      const box = this._boundsOf(this.nodesAnchoredIn(group));
      if (!box) break;
      const [x, y, w, h] = group.bounds;
      const width = Math.max(w, Math.round(box.maxX - x + GROUP_PAD));
      const height = Math.max(h, Math.round(box.maxY - y + GROUP_PAD));
      if (width === w && height === h) break;
      group.bounds[2] = width;
      group.bounds[3] = height;
      this._applyGroup(group);
      grew = true;
    }
    // A box that has just grown may have taken in a block that was hanging
    // out of it, and which blocks are inside is what decides the sockets on
    // its title bar. This is the only place membership changes without
    // anybody editing anything, so without this the sockets stayed as they
    // were measured a moment too early -- which is exactly when a chunk is
    // dropped on the canvas and its blocks have not finished laying out.
    if (grew) this.refreshAllGroupPorts();
  },

  /* One observer for every node, rather than a call at each place a node is
     re-rendered. A node changes size for more reasons than there are render
     paths -- an error line, a note, a preview being resized, a parameter
     widget opening -- and the observer catches all of them including the ones
     not thought of. Growing a group does not resize a node, so this cannot
     feed itself. */
  _watchSize(node) {
    if (!node._el) return;
    if (!this._sizes) {
      this._sizes = new Map();
      this._observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const watched = this._sizes.get(entry.target);
          if (watched) this._growGroupsAround(watched);
        }
      });
    }
    this._sizes.set(node._el, node);
    this._observer.observe(node._el);
  },

  _unwatchSize(el) {
    if (!el || !this._sizes) return;
    this._sizes.delete(el);
    if (this._observer) this._observer.unobserve(el);
  },

  /* Fires once per node whenever anything re-renders, so the cheap test comes
     first: only a node that is both taken by a group and hanging out of it is
     worth a full rescan. */
  _growGroupsAround(node) {
    if (!node || !node._el) return;
    const right = node.pos[0] + node._el.offsetWidth;
    const bottom = node.pos[1] + node._el.offsetHeight;
    const owner = this.ownerOf(node);
    if (owner) {
      // Its own box grows for it, full stop. This is what was missing when a
      // chunk landed on top of another: the node had grown past its own box,
      // but it also happened to fit inside the older box underneath, and the
      // test below read that as "it has a home already" and left the new box
      // at the size it was measured at.
      const [x, y, w, h] = owner.bounds;
      if (right > x + w || bottom > y + h) this._growGroup(owner);
      return;
    }
    for (const group of this.groups) {
      const [x, y, w, h] = group.bounds;
      if (!(node.pos[0] >= x && node.pos[0] <= x + w
        && node.pos[1] >= y && node.pos[1] <= y + h)) continue;
      if (right <= x + w && bottom <= y + h) continue;
      if (this._fitsSomeGroup(node)) continue;
      this._growGroup(group);
    }
  },

  /* Nodes standing inside a group -- the whole node, not most of it.

     This used to go by the node's centre, which is friendlier when you are
     dragging things in and out and dangerous everywhere else: "delete this
     group and its nodes" then took anything that happened to be lying half
     across the box, including nodes that had nothing to do with it. A rule
     you can see the edge of is worth more than a forgiving one.

     Dragging uses nodesAnchoredIn instead: moving the wrong node is one
     Ctrl+Z, deleting it is not. */
  /* The smallest group a point falls inside, or null.

     Groups nest, so the innermost is the one meant: right-clicking inside a
     stage that sits inside a whole pipeline is about the stage. */
  groupAt(x, y) {
    let found = null;
    for (const group of this.groups) {
      const [gx, gy, w, h] = group.bounds;
      if (x < gx || y < gy || x > gx + w || y > gy + h) continue;
      if (!found || w * h < found.bounds[2] * found.bounds[3]) found = group;
    }
    return found;
  },

  nodesInGroup(group) {
    const [x, y, w, h] = group.bounds;
    const inside = [];
    for (const node of this.nodes.values()) {
      if (!node._el) continue;
      // Same rule as nodesAnchoredIn: a node that came with another box is
      // that box's, however squarely it happens to be sitting in this one.
      const owner = this.ownerOf(node);
      if (owner && owner !== group) continue;
      const right = node.pos[0] + node._el.offsetWidth;
      const bottom = node.pos[1] + node._el.offsetHeight;
      if (node.pos[0] >= x && right <= x + w
        && node.pos[1] >= y && bottom <= y + h) inside.push(node.id);
    }
    return inside;
  },

  /* Groups wholly inside another one, so a group can be dragged with its
     contents when someone has nested them. */
  groupsInGroup(group) {
    const [x, y, w, h] = group.bounds;
    return this.groups.filter((other) => {
      if (other.id === group.id) return false;
      const [ox, oy, ow, oh] = other.bounds;
      return ox >= x && oy >= y && ox + ow <= x + w && oy + oh <= y + h;
    });
  },

  /* Shrink or grow a group to just contain what is standing in it.

     Anchored, like dragging: what the box moves is what the box should be big
     enough for, and "fit" that leaves a node hanging out would be a strange
     thing to call fit. */
  fitGroup(group) {
    const box = this._boundsOf(this.nodesAnchoredIn(group));
    if (!box) { UI.toast('nothing inside that group', 'warn'); return; }
    this.mark(`fit ${group.title}`);
    group.bounds = [
      Math.round(box.minX - GROUP_PAD),
      Math.round(box.minY - GROUP_PAD - GROUP_TITLE_H),
      Math.round(box.maxX - box.minX + GROUP_PAD * 2),
      Math.round(box.maxY - box.minY + GROUP_PAD * 2 + GROUP_TITLE_H),
    ];
    this._applyGroup(group);
    this.changed();
  },

  _buildGroup(group) {
    const el = UI.el('div', { class: 'group', 'data-id': group.id });
    group._el = el;
    /* The title bar carries three things now, so the name is a span of its
       own rather than loose text in the bar. That is not tidiness: renaming a
       group wrote the new name straight into the bar, which wiped everything
       else standing in it. The sockets and the button vanished the moment
       anybody renamed a chunk, and only came back when the graph was
       rebuilt. */
    const title = UI.el('div', { class: 'group-title' });
    const shown = UI.el('span', { class: 'group-name', text: group.title });

    /* The two walls. What the chunk takes in hangs on the left wall, what it
       hands out on the right, both starting just under the title bar. On the
       wall rather than on the title bar because that is where the wires
       arrive: a wire that ran past the edge of the box to a block buried in
       the middle of it was the thing that made a chunk hard to join up.

       The dots sit just inside the wall rather than straddling it. Two boxes
       in the shipped library stand with their walls touching -- the Minimise
       and Settle pair in the membrane tutorial, 0 px apart -- and dots that
       straddled would land on top of each other there. */
    const west = UI.el('div', { class: 'group-wall west' });
    const east = UI.el('div', { class: 'group-wall east' });

    // The title bar carries the name and nothing else. Everything the chunk
    // takes in from outside is still one window away, under Inputs in the
    // box's right-click menu.
    title.appendChild(shown);
    el.appendChild(title);
    el.appendChild(west);
    el.appendChild(east);
    el.appendChild(UI.el('div', { class: 'group-resize', title: 'Drag to resize' }));
    // A box built now gets its dots straight away rather than waiting for the
    // next edit. drawGroups() is never called from anywhere, so this is the
    // only place a box comes into being.
    this.refreshAllGroupPorts();

    title.addEventListener('mousedown', (event) => this._startGroupDrag(event, group));
    title.addEventListener('dblclick', (event) => {
      event.stopPropagation();
      const name = prompt('Group name', group.title);
      if (name === null) return;
      this.mark(`rename ${group.title}`);
      group.title = name.trim() || 'group';
      shown.textContent = group.title;
      this.changed();
    });
    title.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this._groupMenu(event, group);
    });

    el.querySelector('.group-resize').addEventListener('mousedown', (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const start = { x: event.clientX, y: event.clientY,
                      w: group.bounds[2], h: group.bounds[3] };
      const move = (moveEvent) => {
        const scale = this.view.scale || 1;
        group.bounds[2] = Math.max(120, start.w + (moveEvent.clientX - start.x) / scale);
        group.bounds[3] = Math.max(GROUP_TITLE_H + 40,
          start.h + (moveEvent.clientY - start.y) / scale);
        this._applyGroup(group);
        // The walls move with the box, and the wires end on them.
        this.drawWires();
      };
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        group.bounds = group.bounds.map((v) => Math.round(v));
        this._applyGroup(group);
        this.mark(`resize ${group.title}`, `group:${group.id}`);
        this.changed();
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });

    this._applyGroup(group);
    return el;
  },

  /* The cable dots on a chunk's two walls.

     They are not a new kind of link. Each one stands for a socket on a block
     inside, and wiring one draws the same link to that block that you would
     have drawn by hand -- which is why the saved graph, the run order and
     everything else know nothing about them. They carry the class the node
     ports carry and the same four pieces of information, so dragging, drop
     detection and the marking of what fits all work on them already.

     Each wall carries the cables you put on it and an empty dot at the
     bottom that takes anything. The two walls do exactly the same thing: it
     is your choice which side a cable comes out of, not the program's.

     Rebuilt rather than patched. It is a dozen dots, it is rebuilt only when
     the graph actually changes, and working out which of them moved costs
     more than making them again. */
  refreshGroupPorts(group) {
    if (!group._el) return;
    // Rides along with the walls because both are about what the box holds,
    // and this is rebuilt after every change to the graph.
    const inside = this._everythingIn(group).map((id) => this.nodes.get(id)).filter(Boolean);
    group._el.classList.toggle('all-off', inside.length > 0 && inside.every((n) => n.off));
    const west = group._el.querySelector('.group-wall.west');
    const east = group._el.querySelector('.group-wall.east');
    if (!west || !east) return;
    west.innerHTML = '';
    east.innerHTML = '';

    /* A wall holds what you have put on it, and nothing else.

       It started out showing every socket the chunk needed or produced, which
       meant every wire crossing the box was dragged through a dot whether you
       wanted that or not. A wire from one block straight to another is often
       exactly what you want to see. So the wall is a patch panel now: empty
       until you run a cable through it, and wires you have not routed are
       drawn block to block as they always were.

       What is stored is only which cables you routed and which wall you put
       them on. That is a note about how to draw, not a connection: if it ever
       goes stale the wire simply draws straight again. The connections
       themselves stay ordinary block-to-block links, which is why nothing
       downstream -- the run order, the problems list, the saved scripts --
       knows any of this exists. */
    /* Which side of the wall the names are written on.

       Outside the box wherever there is room, which is nearly always. A name
       written inside sits on top of whatever block happens to be nearest the
       wall, and on a small box that is every block. Outside it can cover
       nothing of the chunk at all, and it is where your eye already is: the
       wire leaves the dot outward, and the name goes with it.

       The one case with no room outside is another box right up against this
       one, and two in the shipped library stand exactly that way. There the
       name goes back inside, where at least it only covers this chunk's own
       contents rather than somebody else's. */
    for (const [side, wall] of [['west', west], ['east', east]]) {
      wall.classList.toggle('names-out', this._roomBeside(group, side));
    }

    // The dot that takes anything goes first, so it is always in the same
    // place: the top of the left wall and the bottom of the right one, which
    // the stylesheet fills upwards. Put it after the cables and it would
    // slide along the wall with every one you added.
    const cables = this._patchOf(group);
    west.appendChild(this._wallCatch(group, 'west',
      !cables.some((e) => e.side === 'west')));
    east.appendChild(this._wallCatch(group, 'east',
      !cables.some((e) => e.side === 'east')));
    for (const entry of cables) {
      const wall = entry.side === 'west' ? west : east;
      wall.appendChild(this._wallPort(group, entry));
    }
  },

  /* Is the strip just outside one of a box's walls clear of other boxes?

     Only boxes are looked at, not loose blocks. A block standing outside the
     wall is usually the very thing feeding the cable, and a name written
     across the corner of it is a small untidiness. A whole other chunk is
     not: its own contents and its own names are already there, and writing
     over them makes two boxes unreadable instead of one. */
  _roomBeside(group, side, want = NAME_STRIP) {
    const [x, y, w, h] = group.bounds;
    const from = side === 'west' ? x - want : x + w;
    const to = from + want;
    return !this.groups.some((other) => {
      if (other === group || !other.bounds) return false;
      const [ox, oy, ow, oh] = other.bounds;
      return ox < to && ox + ow > from && oy < y + h && oy + oh > y;
    });
  },

  /* The cables on a chunk's walls, with the ones whose block has gone left
     out. Pruning here rather than when a block is deleted means there is one
     place it can be got wrong instead of several, and a stale note costs
     nothing in the meantime: it only ever means a wire is drawn straight. */
  _patchOf(group) {
    const kept = (group.patch || []).filter((e) => {
      const node = this.nodes.get(e.node);
      if (!node) return false;
      const def = this.defs[node.type];
      return !!(def && (def.outputs || []).some((p) => p.name === e.port));
    });
    if (kept.length !== (group.patch || []).length) group.patch = kept;
    return kept;
  },

  /* What a cable is called on the wall.

     As short as it can be and still say which cable is which, because the
     name is written out beside the dot and a long one is a long strip of
     text laid across the picture.

     Three tries, shortest first, and each cable takes the first one that
     nothing else on the box shares:

       what comes out of the socket    "trajectory", "tpr"
       the block it comes from         "Run MD (mdrun)"
       both                            "Process trajectory (trjconv) · tpr"

     If even the third repeats, which takes two copies of the same block
     handing out the same thing, they are numbered. Cables can end up with
     names of different shapes on one wall, and that is the point: "tpr" says
     everything a longer name would, so a longer name is only clutter. A name
     you typed yourself always wins and never pushes the others longer. */
  _patchName(group, entry) {
    if (entry.label) return entry.label;
    const node = this.nodes.get(entry.node);
    if (!node) return entry.port;
    return this._patchNames(group).get(entry) || this._portLabel(node, entry.port);
  },

  /* All of a box's cable names worked out together, because one cable's name
     depends on the others.

     Everything starts on the shortest form. Then, as long as any two read the
     same, every cable caught in a tie moves up one form. Nothing else moves.
     That is why they have to be worked out as a set: judging one cable against
     every form the others could have taken lengthens names for clashes that
     were never going to happen. Three cables carrying a trajectory, a tpr and
     another trajectory come out as "Run MD", "tpr" and "Process trajectory" --
     the tpr keeps its short name because nothing is ever going to collide with
     it, even though it comes from the same block as the first. */
  _patchNames(group) {
    const of = (e) => this.nodes.get(e.node);
    const forms = [
      (e) => this._portLabel(of(e), e.port),
      (e) => of(e).title,
      (e) => `${of(e).title} · ${this._portLabel(of(e), e.port)}`,
    ];
    // Ones you named yourself are left out: you chose that name, so it is not
    // the program's business to lengthen the others around it.
    const rest = this._patchOf(group).filter((e) => !e.label && of(e));
    const step = new Map(rest.map((e) => [e, 0]));
    const nameOf = (e) => forms[step.get(e)](e);
    const counted = () => {
      const tally = new Map();
      for (const e of rest) tally.set(nameOf(e), (tally.get(nameOf(e)) || 0) + 1);
      return tally;
    };
    for (let round = 0; round < forms.length; round += 1) {
      const tally = counted();
      const tied = rest.filter(
        (e) => tally.get(nameOf(e)) > 1 && step.get(e) < forms.length - 1);
      if (!tied.length) break;
      for (const e of tied) step.set(e, step.get(e) + 1);
    }
    // Anything still sharing a name is two copies of one block handing out the
    // same thing. There is nothing left to say about them, so they are
    // numbered in the order they went on the wall.
    const total = counted();
    const sofar = new Map();
    const names = new Map();
    for (const e of rest) {
      const name = nameOf(e);
      if (total.get(name) < 2) { names.set(e, name); continue; }
      const nth = (sofar.get(name) || 0) + 1;
      sofar.set(name, nth);
      names.set(e, `${name} ${nth}`);
    }
    return names;
  },

  _portLabel(node, portName) {
    const def = this.defs[node.type] || {};
    const port = (def.outputs || []).find((p) => p.name === portName);
    return port ? port.label : portName;
  },

  /* One cable on a wall: a dot you can pull as many wires from as you like,
     and the name of what it carries. A node shows a name beside every socket,
     and a wall that is meant to be joined up like a node needs the same. */
  _wallPort(group, entry) {
    const node = this.nodes.get(entry.node);
    const def = this.defs[node.type];
    const port = (def.outputs || []).find((p) => p.name === entry.port);
    const type = portType(node, port);
    // Waiting means no wire goes through this dot. Whether the block's output
    // is wired to something elsewhere, not through this wall, is beside the
    // point.
    const used = this.links.some(
      (l) => this._cablesUsedBy(l).some((hit) => hit.entry === entry));
    const name = this._patchName(group, entry);
    const dot = UI.el('span', {
      class: `port wall-port${used ? ' connected' : ' pending'}`,
      'data-node': node.id, 'data-port': port.name,
      'data-dir': 'out', 'data-type': type,
      'data-group': group.id, 'data-patch': '1', 'data-wall': entry.side,
      title: `${fileAbout(name, type, port.name)}\n\n`
        + (used
          ? 'Drag from here to wire it somewhere else too.'
          : 'Nothing is wired from it yet. Drag from here to whatever needs it.'),
    });
    dot.style.background = PORT_COLORS[type] || PORT_COLORS.any;
    this._groupDots.set(`${group.id}|${node.id}|${port.name}|out`, dot);
    // The wall belongs to the box, and pressing the box drags it. The dot has
    // to take the press first or starting a wire would move the whole chunk.
    dot.addEventListener('mousedown', (event) => {
      event.stopPropagation();
      this._startLinkDrag(event, node, port, 'out', dot);
    });
    dot.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this._patchMenu(event, group, entry, name);
    });
    return UI.el('div', { class: `wall-row ${entry.side}` },
                 [dot, UI.el('span', { class: 'wall-name', text: name,
                                       title: fileAbout(name, type, port.name) })]);
  },

  _patchMenu(event, group, entry, name) {
    UI.contextMenu(event.clientX, event.clientY, [
      { label: 'Rename this cable…', action: () => {
        const given = prompt('What to call this cable on the wall', name);
        if (given === null) return;
        this.mark(`rename ${name}`);
        entry.label = given.trim();
        this.changed();
      } },
      { label: 'Take it off the wall', hint: 'wires stay', action: () => {
        this.mark(`take ${name} off the wall`);
        group.patch = (group.patch || []).filter((e) => e !== entry);
        this.changed();
        UI.toast(`${name} is off the wall. Anything it was feeding is still `
          + 'wired, drawn straight now', 'info', 5000);
      } },
      { label: 'Take it off and cut its wires', action: () => {
        this.mark(`cut ${name}`);
        group.patch = (group.patch || []).filter((e) => e !== entry);
        this.links = this.links.filter(
          (l) => !(l.from_node === entry.node && l.from_port === entry.port));
        this.refreshPortStates();
        this.drawWires();
        this.changed();
      } },
    ]);
  },

  /* The all-purpose dot at the top of each wall.

     Where you bring a cable to put it on the wall. It takes anything, both
     walls have one, and it is always in the same place whatever else is on
     the wall, so there is nothing to aim at and nothing to remember.

     The word beside it says so the first time. After that it fades out and
     comes back when the pointer is over that wall, or when you pick up a
     wire -- which is the moment it matters. Two boxes with the word written
     permanently beside four dots is four words too many. */
  _wallCatch(group, side, alone) {
    const dot = UI.el('span', {
      class: `port wall-catch ${side}`,
      'data-dir': 'any', 'data-type': 'any',
      'data-group': group.id, 'data-wall': side,
      title: 'Let go of a wire here and what it carries gets its own named '
        + `dot on ${group.title}'s wall. Then drag from that dot to whatever `
        + 'needs it',
    });
    // Nothing is dragged out of a catch-all: it is a place to let go of a
    // wire, not a place to start one. Without this the press would fall
    // through to the box and drag the whole chunk.
    dot.addEventListener('mousedown', (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    // The word is there while the wall is empty, because that is when you do
    // not yet know what the dashed circle is for. Once a cable is on the wall
    // you do, and two boxes with the word written beside four dots for ever
    // after is four words of clutter. It comes back whenever a wire is picked
    // up, which is the moment the circle matters again.
    return UI.el('div', { class: `wall-row ${side} catch${alone ? '' : ' quiet'}` },
                 [dot, UI.el('span', { class: 'wall-name faint', text: 'anything' })]);
  },

  /* Where a wire should meet a chunk's socket, in the same coordinates
     portCenter answers in: the box's own corner plus where the dot sits
     inside it. */
  groupPortCenter(dot) {
    const group = this.groups.find((g) => g.id === dot.dataset.group);
    if (!group || !group._el) return null;
    let x = 0;
    let y = 0;
    let cursor = dot;
    while (cursor && cursor !== group._el) {
      x += cursor.offsetLeft;
      y += cursor.offsetTop;
      cursor = cursor.offsetParent;
    }
    return {
      x: group.bounds[0] + x + dot.offsetWidth / 2,
      y: group.bounds[1] + y + dot.offsetHeight / 2,
    };
  },

  /* A wire let go on a chunk's all-purpose dot.

     A wall works like the patch panel behind a rack: you bring a cable to it,
     it gets a labelled socket, and from that socket you run short leads to
     wherever they are needed. So letting a wire go here does one thing and
     stops. It gives what that wire carries its own named dot on the wall, and
     waits. It does not pick a block inside the box to join it to. Guessing was
     the first way this worked and it was wrong twice over: it decided for you,
     and it made a wall the only way out of a box.

     Nothing about the graph changes. The cable on the wall is a note about
     where you would like wires drawn, kept with the box; the wires themselves
     are the same plain block-to-block links they have always been, and a
     workflow saved with cables on its walls runs on a copy of the program
     that has never heard of them. */
  _dropOnWall(dot, drag, event) {
    const group = this.groups.find((g) => g.id === dot.dataset.group);
    if (!group) return;
    const side = dot.dataset.wall;

    // Only a source goes on a wall. A wire dragged backwards out of a socket
    // that wants feeding has no output behind it to hang there.
    if (drag.direction !== 'out') {
      UI.toast('a wall holds what something makes. Drag from the socket a '
        + 'file comes out of and let go here', 'warn', 6000);
      return;
    }

    this.putOnWall(group, drag.node, drag.port, side);
  },

  /* Put what one output carries on one of a box's walls: a new dot if it is
     not on either wall yet, moved across if it is on the other one. The drop
     on the dashed circle and the double-click on an output both end here. */
  putOnWall(group, node, port, side) {
    group.patch = group.patch || [];
    const already = group.patch.find(
      (e) => e.node === node.id && e.port === port.name);
    if (already) {
      if (already.side !== side) {
        this.mark('move a cable to the other wall');
        already.side = side;
        this.rebuildGroupPorts();
        this.changed();
        UI.toast(`${this._patchName(group, already)} moved to the `
          + `${side === 'west' ? 'left' : 'right'} wall`, 'ok', 3000);
        return;
      }
      UI.toast(`${this._patchName(group, already)} is already on that wall`,
               'info', 3000);
      return;
    }

    this.mark(`put ${node.title} on ${group.title}'s wall`);
    const entry = { node: node.id, port: port.name, side };
    group.patch.push(entry);
    // Straight away, not on the next tidy-up, so the dot and its dashed line
    // are there the moment you let go or finish the double-click.
    this.rebuildGroupPorts();
    this.changed();
    UI.toast(`${this._patchName(group, entry)} is on the wall. Drag from that `
      + 'dot to whatever needs it, as many times as you like', 'ok', 7000);
  },

  /* Double-clicking an output: onto the right-hand wall of the box its block
     stands in, which is the way out of a chunk, without dragging a wire to
     the dashed circle. On the left wall already, it moves across. On the
     right wall already, the same double-click takes it off again, and any
     wires through it stay, drawn straight -- the same as "Take it off the
     wall" in the dot's own menu.

     It mirrors what double-clicking does to an input, which is unplug it:
     the quick thing you most often want to do with that socket. */
  toggleOnRightWall(node, port) {
    const boxId = this._homeOf && this._homeOf.get(node.id);
    const group = boxId && this.groups.find((g) => g.id === boxId);
    if (!group) {
      UI.toast(`${node.title} is not in a box, so there is no wall to put `
        + `${port.label} on. Select it and press Ctrl+G to make one.`, 'info', 5000);
      return;
    }
    const already = (group.patch || []).find(
      (e) => e.node === node.id && e.port === port.name);
    if (already && already.side === 'east') {
      const name = this._patchName(group, already);
      this.mark(`take ${name} off the wall`);
      group.patch = group.patch.filter((e) => e !== already);
      this.rebuildGroupPorts();
      this.changed();
      UI.toast(`${name} is off the wall. Double-click the socket again to put `
        + 'it back', 'info', 4000);
      return;
    }
    this.putOnWall(group, node, port, 'east');
  },

  /* Every chunk's sockets, after something changed. Put off by a moment
     because loading a workflow calls changed() once per block, and doing this
     seventy times in a row would be seventy times the work for one answer. */
  refreshAllGroupPorts() {
    clearTimeout(this._portTimer);
    this._portTimer = setTimeout(() => this.rebuildGroupPorts(), 60);
  },

  rebuildGroupPorts() {
    // Which box each block stands in, worked out once. Wires are redrawn on
    // every mouse move while something is being dragged, and asking each box
    // which blocks are in it every one of those times would make dragging a
    // big graph feel like wading.
    this._homeOf = new Map();
    this._groupDots = new Map();
    for (const group of this.groups) {
      for (const id of this.chunkMembers(group)) this._homeOf.set(id, group.id);
    }
    for (const group of this.groups) this.refreshGroupPorts(group);
    this.drawWires();
  },

  _applyGroup(group) {
    const el = group._el;
    if (!el) return;
    const [x, y, w, h] = group.bounds;
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.style.width = `${w}px`;
    el.style.height = `${h}px`;
    // Two alphas of one colour: a solid bar you can grab, a wash you can see
    // the grid through.
    el.style.borderColor = group.color;
    el.style.background = `${group.color}22`;
    const title = el.querySelector('.group-title');
    if (title) {
      title.style.background = group.color;
      title.style.height = `${GROUP_TITLE_H}px`;
    }
  },

  /* Dragging the title bar takes the contents along -- nodes and any nested
     groups. Membership is read once, at the start, so a node does not fall out
     of the group half way through the drag.

     Anchored rather than wholly contained, so a node hanging over an edge --
     because it grew, or because the box was pulled in around it -- still comes
     with the group instead of being left standing where it was. */
  _startGroupDrag(event, group) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    if (this.offChordHeld(event)) {
      this.toggleOff(this._everythingIn(group));
      return;
    }
    const world = this.screenToWorld(event.clientX, event.clientY);
    const members = this.nodesAnchoredIn(group).map((id) => {
      const node = this.nodes.get(id);
      return { id, x: node.pos[0], y: node.pos[1] };
    });
    this.selectGroup(group.id, additive(event));
    const nested = this.groupsInGroup(group).map((g) => ({ g, x: g.bounds[0], y: g.bounds[1] }));
    this._groupDrag = {
      group, members, nested,
      startX: world.x, startY: world.y,
      ox: group.bounds[0], oy: group.bounds[1],
    };
  },

  _groupMenu(event, group) {
    const swatches = {
      swatches: GROUP_COLORS.map(([name, hex]) => ({
        label: name,
        color: hex,
        action: () => {
          this.mark(`colour ${group.title}`);
          group.color = hex;
          this._applyGroup(group);
          this.changed();
        },
      })),
    };
    UI.contextMenu(event.clientX, event.clientY, [
      { label: 'Rename…', action: () => {
        const name = prompt('Group name', group.title);
        if (name === null) return;
        this.mark(`rename ${group.title}`);
        group.title = name.trim() || 'group';
        group._el.querySelector('.group-name').textContent = group.title;
        this.changed();
      } },
      { label: 'Inputs\u2026', action: () => Panels.chunkInputs(group) },
      (() => {
        const inside = this._everythingIn(group).map((id) => this.nodes.get(id));
        const allOff = inside.length && inside.every((node) => node.off);
        return {
          label: allOff ? 'Switch this chunk back on' : 'Switch this chunk off',
          hint: `${this.offChordName()} the title`,
          action: () => this.toggleOff(inside.map((node) => node.id)),
        };
      })(),
      { label: 'Select contents', action: () => this.select(this.nodesInGroup(group)) },
      { label: 'Fit to contents', action: () => this.fitGroup(group) },
      // Two ways to run a group, the same two a single node has.
      { label: `Run ${group.title} and everything before it`, action: () => {
        const members = this.nodesInGroup(group);
        if (!members.length) { UI.toast('nothing in that group', 'warn'); return; }
        App.run(members);
      } },
      { label: `Run just ${group.title}`, action: () => {
        const members = this.nodesInGroup(group);
        if (!members.length) { UI.toast('nothing in that group', 'warn'); return; }
        App.run(members, members, { isolate: true });
      } },
      '-',
      swatches,
      '-',
      { label: 'Save as chunk…', action: () => App.saveChunk(this.nodesInGroup(group), group) },
      { label: 'Remove group (keep nodes)', action: () => this.removeGroup(group.id) },
      { label: 'Delete group and nodes', action: () => {
        this.mark(`delete ${group.title}`);
        for (const id of this.nodesInGroup(group)) this.removeNode(id);
        this.removeGroup(group.id);
      } },
    ]);
  },

  /* The selection as a portable fragment: the nodes, the links that run
     between them, and any group whose contents are entirely in the selection.
     Positions are measured from the top-left of the selection, so the result
     can be dropped anywhere -- which is what makes it a chunk. */
  subgraph(ids) {
    const set = new Set(ids);
    const box = this._boundsOf(ids);
    if (!box) return null;
    const nodes = [];
    for (const id of ids) {
      const node = this.nodes.get(id);
      if (!node) continue;
      const def = this.defs[node.type] || {};
      nodes.push({
        id: node.id,
        type: node.type,
        pos: [Math.round(node.pos[0] - box.minX), Math.round(node.pos[1] - box.minY)],
        params: JSON.parse(JSON.stringify(node.params)),
        ...(node.collapsed ? { collapsed: true } : {}),
        ...(node.title && node.title !== def.title ? { title: node.title } : {}),
        ...(node.display ? { display: { ...node.display } } : {}),
      });
    }
    const links = this.links
      .filter((l) => set.has(l.from_node) && set.has(l.to_node))
      .map((l) => ({ ...l }));
    const groups = [];
    for (const group of this.groups) {
      const inside = this.nodesInGroup(group);
      // A group that also holds nodes you did not select would come back
      // wrong, so it is left behind rather than half saved.
      if (!inside.length || !inside.every((id) => set.has(id))) continue;
      groups.push({
        title: group.title,
        color: group.color,
        // Written down so the box knows what is its own when it is dropped
        // again, even if it lands on top of something.
        own: [...inside],
        // Only cables whose block is coming too. One naming a block outside
        // the selection could never be found again when the chunk is dropped.
        ...((group.patch || []).some((e) => set.has(e.node))
          ? { patch: group.patch.filter((e) => set.has(e.node))
                .map((e) => ({ ...e })) }
          : {}),
        bounds: [
          Math.round(group.bounds[0] - box.minX), Math.round(group.bounds[1] - box.minY),
          group.bounds[2], group.bounds[3],
        ],
      });
    }
    return { nodes, links, groups };
  },

  drawGroups() {
    this.dom.groups.innerHTML = '';
    for (const group of this.groups) this.dom.groups.appendChild(this._buildGroup(group));
    // Rebuilt boxes are empty bars until this runs, and the wires want the
    // sockets to be there before they are drawn.
    this.rebuildGroupPorts();
  },

  /* ------------------------------------------------------------- status */
  setStatus(nodeId, status, extra = {}) {
    const node = this.nodes.get(nodeId);
    if (!node) return;
    node.status = status;
    if (extra.error !== undefined) node.error = extra.error;
    if (extra.notes !== undefined) node.notes = extra.notes;
    if (extra.progress !== undefined) node.progress = extra.progress;
    this.applyNodeStatus(node);
  },

  /* Progress alone: the one line of text, and nothing else redrawn.

     A status change rebuilds the node's whole class list, which makes the
     browser restyle the node. Fine a few times a run; not fine for every
     step of a minimisation. */
  setProgress(nodeId, text) {
    const node = this.nodes.get(nodeId);
    if (!node) return;
    node.progress = text || '';
    const el = node._el && node._el.querySelector('.node-progress');
    if (!el) return;
    el.textContent = node.progress;
    el.classList.toggle('hidden', !node.progress);
  },

  applyNodeStatus(node) {
    const el = node._el;
    if (!el) return;
    // Every marker has to be rebuilt here. This assignment replaces the whole
    // class attribute, so anything set from outside -- as the problem
    // highlight used to be -- is wiped the next time a status arrives.
    const problems = node.problems || [];
    const worst = node.blocked ? ' blocked'
      : (problems.some((p) => p.level === 'error') ? ' invalid'
        : (problems.length ? ' warned' : ''));
    el.className = `node status-${node.status}${this.selection.has(node.id) ? ' selected' : ''}`
      + (node.collapsed ? ' collapsed' : '')
      // Rebuilt here too, or the next status event wipes the mark that says
      // the run stops at this node.
      + (node.pause ? ' pauses' : '') + worst
      // Switched off, or left out because something it needs is. Both are
      // rebuilt here for the same reason the pause mark is.
      + (node.off ? ' off' : (node.leftOut ? ' left-out' : ''))
      // And the note's wide-card shape, for the same reason.
      + (node.type === 'util.note' ? ' note-card' : '')
      + (el.classList.contains('has-preview') ? ' has-preview' : '');
    const progress = el.querySelector('.node-progress');
    if (progress) {
      progress.textContent = node.progress || '';
      progress.classList.toggle('hidden', !node.progress);
    }
    const notes = el.querySelector('.node-notes');
    if (notes) {
      const text = (node.notes || []).filter(Boolean).join('\n');
      notes.textContent = text;
      notes.classList.toggle('hidden', !text);
    }
    const error = el.querySelector('.node-error');
    if (error) {
      const lines = problems.map((p) => p.message);
      if (node.error && !lines.includes(node.error)) lines.unshift(node.error);
      error.textContent = lines.join('\n');
      error.classList.toggle('hidden', !lines.length);
    }
  },

  resetStatuses() {
    for (const node of this.nodes.values()) {
      node.status = 'idle';
      node.error = '';
      node.progress = '';
      this.applyNodeStatus(node);
    }
  },

  /* Attach the checker's findings to the nodes they belong to. Warnings count:
     a link into a port that no longer exists is not fatal, but it is why the
     node is not doing what you think. */
  markProblems(problems, causes) {
    for (const node of this.nodes.values()) {
      node.problems = [];
      node.blocked = false;
    }
    for (const problem of problems || []) {
      const node = this.nodes.get(problem.node);
      if (!node) continue;
      node.problems.push({ level: problem.level, message: problem.message });
      // Not a cause: broken only because something upstream is.
      if (causes && !causes.has(problem.node)) node.blocked = true;
    }
    for (const node of this.nodes.values()) this.applyNodeStatus(node);
    // This is the moment nodes change height: the check has just added, or
    // taken away, the lines a node prints about itself. A box drawn round a
    // node before those lines arrived is now too small for it.
    //
    // The watcher that normally notices a node changing size does not fire in
    // a browser tab nobody is looking at, and loading a workflow into a hidden
    // tab is exactly when this happens. So ask every box here as well.
    this.settleGroups();
  },

  /* ----------------------------------------------------------- geometry */
  portCenter(nodeId, portName, direction) {
    const node = this.nodes.get(nodeId);
    if (!node || !node._el) return null;
    if (node.collapsed) {
      const header = node._el.querySelector('header');
      const y = node.pos[1] + header.offsetHeight / 2;
      return { x: node.pos[0] + (direction === 'out' ? node._el.offsetWidth : 0), y };
    }
    const dot = node._el.querySelector(
      `.port[data-port="${CSS.escape(portName)}"][data-dir="${direction}"]`);
    if (!dot) return null;
    let x = 0;
    let y = 0;
    let cursor = dot;
    while (cursor && cursor !== node._el) {
      x += cursor.offsetLeft;
      y += cursor.offsetTop;
      cursor = cursor.offsetParent;
    }
    return {
      x: node.pos[0] + x + dot.offsetWidth / 2,
      y: node.pos[1] + y + dot.offsetHeight / 2,
    };
  },

  /* Does a wire pass through this wall dot from left to right, the way it
     passes through a block?

     Yes for the two ordinary uses of a wall: a file leaving its box through
     a dot on the box's right-hand wall, and a file arriving through a dot on
     the left-hand wall of the box it is going into. Those dots then behave
     like a block's own sockets -- the wire comes in from the left and goes
     on to the right, whatever the next stop is. So a file going from one box
     to another box underneath it leaves to the right, runs round through the
     gap between the two boxes and comes in from the left, just as a wire
     between two blocks stacked one above the other does. Leaning towards the
     other end instead would turn it straight back across the box it had
     just left.

     No for a file put on the other wall -- leaving through the left wall, or
     arriving through the right one. Such a dot has no natural side, so the
     wire leans towards the other end of that stretch. */
  _wallGoesRight(dot, role) {
    const side = dot && dot.dataset ? dot.dataset.wall : '';
    return side === (role === 'out' ? 'east' : 'west');
  },

  /* The highest and the lowest dot on each wall, keyed by box and side. */
  _measureWalls() {
    const spans = new Map();
    for (const dot of this._groupDots.values()) {
      const at = dot && dot.dataset && this.groupPortCenter(dot);
      if (!at) continue;
      const key = `${dot.dataset.group}|${dot.dataset.wall}`;
      const span = spans.get(key);
      if (span) {
        span.top = Math.min(span.top, at.y);
        span.bottom = Math.max(span.bottom, at.y);
      } else {
        spans.set(key, { top: at.y, bottom: at.y });
      }
    }
    return spans;
  },

  /* How much wider than usual each end of a stretch swings, when a cable
     has to turn back round the corner of a box.

     That happens to a cable that leaves its box through the right-hand wall
     for a left-hand wall further left -- usually that of the box underneath.
     It goes out to the right, round the corner, back along the gap and in
     from the left. A box often sends two or three such cables to the same
     box, and drawn with the same curve, each one dot lower than the last,
     they cut across each other where they turn. So they wrap round the
     corners the way the cables in a real bundle do: the one whose dot is
     nearest the corner turns tightest, and each dot further from it swings a
     little wider. Any other stretch gets nothing extra and is drawn as it
     always was. */
  _swingWider(from, to) {
    if (!from.dot || !to.dot || !from.onward || !to.onward || to.at.x >= from.at.x) {
      return [0, 0];
    }
    const spans = this._spans || this._measureWalls();
    const wall = (dot) => spans.get(`${dot.dataset.group}|${dot.dataset.wall}`);
    const out = wall(from.dot);
    const into = wall(to.dot);
    if (!out || !into) return [0, 0];
    // Going down, the cable turns round the bottom corner of the box it
    // leaves and the top corner of the box it enters; going up, the other
    // two.
    const down = to.at.y >= from.at.y;
    return [
      SWING_PER_PX * (down ? out.bottom - from.at.y : from.at.y - out.top),
      SWING_PER_PX * (down ? to.at.y - into.top : into.bottom - to.at.y),
    ];
  },

  drawWires() {
    const svg = this.dom.wires;
    svg.innerHTML = '';
    // Where the dots on each wall reach, for _swingWider. Measured once here
    // rather than for every wire.
    this._spans = this._measureWalls();
    // Wall dots some wire goes through. The rest get a line of their own
    // after the loop.
    const used = new Set();
    for (const link of this.links) {
      // Which walls this wire is threaded through. A wire only touches a
      // wall when you put it there yourself. Everything else runs straight
      // from one block to the other, exactly as it always did -- wiring a
      // single block's output straight out of a chunk still works.
      const fromHome = this._homeOf.get(link.from_node);
      const toHome = this._homeOf.get(link.to_node);
      // Keyed by the box as well as the block, because one block can sit on
      // two boxes' walls at once and each of those needs its own dot.
      const onWall = (boxId) => (boxId && fromHome !== toHome
        ? this._groupDots.get(`${boxId}|${link.from_node}|${link.from_port}|out`)
        : null);
      // On the way out: the wall of the box the block itself sits in.
      // On the way in: the wall of the box the wire is heading into.
      const outDot = onWall(fromHome);
      const inDot = onWall(toHome);
      if (outDot) used.add(outDot);
      if (inDot) used.add(inDot);

      const atBlockOut = this.portCenter(link.from_node, link.from_port, 'out');
      const atBlockIn = this.portCenter(link.to_node, link.to_port, 'in');
      if (!atBlockOut || !atBlockIn) continue;
      const source = this.nodes.get(link.from_node);
      const def = this.defs[source.type];
      const port = def.outputs.find((p) => p.name === link.from_port);
      const color = PORT_COLORS[port ? portType(source, port) : 'any']
        || PORT_COLORS.any;

      // Every place the wire touches, in order: the block that makes the
      // thing, then any walls, then the block that takes it. Each stop
      // remembers whether the wire has to pass through it from left to
      // right, the way it passes through a block.
      const stops = [{ at: atBlockOut, onward: true }];
      for (const [dot, role] of [[outDot, 'out'], [inDot, 'in']]) {
        const at = dot && this.groupPortCenter(dot);
        if (at) stops.push({ at, dot, onward: this._wallGoesRight(dot, role) });
      }
      stops.push({ at: atBlockIn, onward: true });

      const target = this.nodes.get(link.to_node);
      const naming = `${source.title} to ${target ? target.title : link.to_node}`;

      // Which way a wire sets off and which way it arrives. A block's output
      // is on its right and its input on its left, so those two ends never
      // change, and neither do the wall dots that work the same way (see
      // _wallGoesRight). Any other wall dot leans towards wherever the other
      // end of that stretch happens to be. That is what stops a cable that
      // doubles back at such a wall from swinging out in a long S before
      // coming back -- it makes a short, neat U instead.
      const lean = (a, b) => (b.x >= a.x ? 1 : -1);
      for (let i = 0; i + 1 < stops.length; i += 1) {
        const a = stops[i].at;
        const b = stops[i + 1].at;
        const shape = this._bezier(a, b,
          stops[i].onward ? 1 : lean(a, b),
          stops[i + 1].onward ? -1 : lean(b, a),
          this._swingWider(stops[i], stops[i + 1]));

        // Each stretch is a pair: an invisible fat stroke that catches the
        // pointer, and the thin one you actually see drawn on top of it.
        // Grouping them means one set of listeners, and it lets the visible
        // wire thicken when the pointer is anywhere in the band rather than
        // only dead on the line.
        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        // Faint when either end will not run: that file is not going to be
        // made or used this time, whatever the wire says.
        group.setAttribute('class', [source, target].some(
          (n) => n && (n.off || n.leftOut)) ? 'wire-line off' : 'wire-line');

        const grab = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        grab.setAttribute('d', shape);
        grab.setAttribute('class', 'wire-grab');
        group.appendChild(grab);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', shape);
        path.setAttribute('class', 'wire');
        path.setAttribute('stroke', color);
        group.appendChild(path);

        // Right-clicking any stretch of a wire cuts the whole wire. They are
        // one connection wearing several segments, and cutting half of one
        // would mean nothing.
        group.addEventListener('contextmenu', (event) => {
          event.preventDefault();
          event.stopPropagation();
          // Holding the cut key skips the menu. One wire, one gesture: you
          // were already pointing at the thing you wanted gone.
          if (this.cutKeyHeld(event)) {
            const gone = this.disconnect(link.to_node, link.to_port);
            UI.toast(`cut the wire from ${naming}`
              + (gone.length ? `, and ${gone.join(' and ')} came off the wall with it` : '')
              + ' -- Ctrl+Z puts it back', 'info', gone.length ? 4000 : 2600);
            return;
          }
          UI.contextMenu(event.clientX, event.clientY, [{
            label: 'Remove link',
            hint: `${this.cutKeyName()} + right-click`,
            action: () => this.disconnect(link.to_node, link.to_port),
          }]);
        });
        svg.appendChild(group);
      }
    }
    for (const dot of this._groupDots.values()) {
      if (!used.has(dot)) this._drawWaitingCable(svg, dot);
    }
    this._spans = null;
    if (this._linkDrag && this._linkDrag.temp) svg.appendChild(this._linkDrag.temp);
  },

  /* The line from a block to a cable on a wall that nothing is wired onward
     from yet.

     Without it the dot sat on the wall with no line to it at all, and there
     was no telling where it came from until you wired it to something. It is
     dashed, because it is not a wire -- nothing uses the file yet. Once a
     wire runs through the dot, that wire draws this stretch itself and this
     line is not needed.

     Right-clicking it takes the cable off the wall, and holding Ctrl (Cmd on
     a Mac) does it without asking, the same as cutting any other wire. */
  _drawWaitingCable(svg, dot) {
    if (!dot.isConnected) return;
    const group = this.groups.find((g) => g.id === dot.dataset.group);
    const entry = group && (group.patch || []).find(
      (e) => e.node === dot.dataset.node && e.port === dot.dataset.port);
    if (!entry) return;
    const to = this.groupPortCenter(dot);
    // Where the line starts. If the block's own box has this cable on its
    // wall as well, from there: the cable leaves one box through its wall
    // and arrives at the next through its wall, and a line from the block
    // itself would cut across as though the first wall were not there. It is
    // the same way the wire will run once something is wired to this dot.
    const home = this._homeOf && this._homeOf.get(dot.dataset.node);
    const exit = home && home !== dot.dataset.group
      ? this._groupDots.get(`${home}|${dot.dataset.node}|${dot.dataset.port}|out`)
      : null;
    const fromWall = exit && exit.isConnected ? this.groupPortCenter(exit) : null;
    const from = fromWall
      || this.portCenter(dot.dataset.node, dot.dataset.port, 'out');
    if (!from || !to) return;
    // A block's output always sets off to the right, and so does a wall dot
    // the file leaves its box through on the right-hand wall. Any other wall
    // dot leans towards whichever side the other end is on. The same rule
    // the wires follow (see _wallGoesRight).
    const role = home && home !== dot.dataset.group ? 'in' : 'out';
    const leaves = !fromWall || this._wallGoesRight(exit, 'out');
    const arrives = this._wallGoesRight(dot, role);
    const shape = this._bezier(from, to,
      leaves ? 1 : (to.x >= from.x ? 1 : -1),
      arrives ? -1 : (from.x >= to.x ? 1 : -1),
      this._swingWider({ at: from, dot: fromWall ? exit : null, onward: leaves },
                       { at: to, dot, onward: arrives }));
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    line.setAttribute('class', 'wire-line');
    const grab = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    grab.setAttribute('d', shape);
    grab.setAttribute('class', 'wire-grab');
    line.appendChild(grab);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', shape);
    path.setAttribute('class', 'wire wire-waiting');
    path.setAttribute('stroke', PORT_COLORS[dot.dataset.type] || PORT_COLORS.any);
    line.appendChild(path);

    const name = this._patchName(group, entry);
    const takeOff = () => {
      this.mark(`take ${name} off the wall`);
      group.patch = (group.patch || []).filter((e) => e !== entry);
      this.rebuildGroupPorts();
      this.changed();
    };
    line.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (this.cutKeyHeld(event)) {
        takeOff();
        UI.toast(`${name} is off the wall -- Ctrl+Z puts it back`, 'info', 2600);
        return;
      }
      UI.contextMenu(event.clientX, event.clientY, [{
        label: 'Take it off the wall',
        hint: `${this.cutKeyName()} + right-click`,
        action: takeOff,
      }]);
    });
    svg.appendChild(line);
  },

  /* The key you hold to cut a wire outright instead of being offered a menu.

     Ctrl on a PC. On a Mac it is Cmd instead, because there holding Ctrl and
     clicking is how you ask for a menu in the first place -- binding the cut
     to Ctrl would mean a Mac user asking for the menu silently lost a wire. */
  onAMac() {
    const said = (navigator.userAgentData && navigator.userAgentData.platform)
      || navigator.platform || navigator.userAgent || '';
    return /mac/i.test(said);
  },

  cutKeyHeld(event) {
    return this.onAMac() ? !!event.metaKey : !!event.ctrlKey;
  },

  cutKeyName() {
    return this.onAMac() ? 'Cmd' : 'Ctrl';
  },

  /* Ctrl + Alt + click switches a block off or back on; Cmd + Option on a
     Mac, where Ctrl + click is how you ask for a menu. */
  offChordHeld(event) {
    return event.button === 0 && event.altKey && this.cutKeyHeld(event);
  },

  offChordName() {
    return this.onAMac() ? 'Cmd + Option + click' : 'Ctrl + Alt + click';
  },

  /* Switch blocks off, or back on.

     A switched-off block stays exactly where it is, wired as it was, and is
     simply left out when the workflow is checked or run -- and so is anything
     that depends on it, because that cannot run without it. It is for the
     block you dropped in to try something and have not wired up yet, which
     used to stop the whole workflow from running until it was deleted.

     One switch for any mix: if anything given is still on, everything is
     switched off; if all of it is already off, it all comes back on. So the
     same key both ways, on one block or on a whole chunk. */
  toggleOff(ids) {
    const nodes = [...new Set(ids)].map((id) => this.nodes.get(id)).filter(Boolean);
    if (!nodes.length) {
      UI.toast('select a block, or click a box\'s title bar, first', 'info');
      return;
    }
    const off = nodes.some((node) => !node.off);
    const what = nodes.length === 1 ? nodes[0].title : `${nodes.length} blocks`;
    this.mark(off ? `switch off ${what}` : `switch on ${what}`);
    for (const node of nodes) {
      node.off = off;
      // Until the next check says otherwise. A block switched back on may
      // still be left out because something before it is off, and the check
      // that follows every edit works that out in half a second.
      node.leftOut = '';
      this.applyNodeStatus(node);
    }
    this.drawWires();
    this.changed();
    const [it, runs] = nodes.length === 1 ? ['it', 'It will'] : ['them', 'They will'];
    UI.toast(off
      ? `switched off ${what}. ${runs} not run, and nor will anything that `
        + `depends on ${it}. ${this.offChordName()} or Ctrl+M switches ${it} back on.`
      : `switched ${what} back on`, 'info', off ? 7000 : 3000);
  },

  /* Every block a box holds, including the ones in boxes inside it. What
     switching a chunk off means is everything you see in it. */
  _everythingIn(group) {
    const ids = new Set(this.chunkMembers(group));
    for (const inner of this.groupsInGroup(group)) {
      for (const id of this.chunkMembers(inner)) ids.add(id);
    }
    return [...ids];
  },

  /* Which blocks were left out by the last check because something they
     depend on is switched off, and why. The rule lives on the server, where
     the run is decided, so what is shown here can never disagree with what
     is run. */
  markLeftOut(leftOut) {
    for (const node of this.nodes.values()) {
      const entry = leftOut[node.id];
      node.leftOut = entry && !node.off ? entry.message : '';
      if (entry) {
        // Nothing about it was checked, so whatever the last check said
        // about it no longer stands.
        node.error = '';
        node.notes = node.leftOut ? [node.leftOut] : [];
      }
    }
    this.drawWires();
  },

  /* The curve between two points. The next two numbers say which way the
     wire sets off and which way it arrives: 1 for rightwards, -1 for
     leftwards. Left out, they give the ordinary case of a wire leaving the
     right-hand side of one block and arriving at the left-hand side of the
     next. The last one, also optional, makes the curve swing wider at its
     start and at its end by that much (see _swingWider). */
  _bezier(from, to, fromDir = 1, toDir = -1, wider = [0, 0]) {
    const dx = Math.max(50, Math.abs(to.x - from.x) * 0.55);
    return `M ${from.x} ${from.y} `
      + `C ${from.x + (dx + wider[0]) * fromDir} ${from.y} `
      + `${to.x + (dx + wider[1]) * toDir} ${to.y} ${to.x} ${to.y}`;
  },

  refreshPortStates() {
    const connected = new Set();
    for (const link of this.links) {
      connected.add(`${link.to_node}|${link.to_port}|in`);
      connected.add(`${link.from_node}|${link.from_port}|out`);
    }
    for (const dot of this.dom.nodes.querySelectorAll('.port')) {
      const key = `${dot.dataset.node}|${dot.dataset.port}|${dot.dataset.dir}`;
      dot.classList.toggle('connected', connected.has(key));
    }
  },

  /* ------------------------------------------------------------ view */
  applyView() {
    const { x, y, scale } = this.view;
    this.dom.world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    // The wires live inside the zoomed world, so a band of a fixed width
    // there shrinks with everything else and the wire gets harder to hit at
    // exactly the zoom where it is already thinnest. Dividing by the zoom
    // keeps the band the same size under the pointer whatever the zoom is.
    this.dom.wires.style.setProperty('--wire-grab', `${WIRE_GRAB_PX / scale}px`);
    this.dom.zoom.textContent = `${Math.round(scale * 100)}%`;
    this.dom.canvas.style.backgroundSize = `${24 * scale}px ${24 * scale}px`;
    this.dom.canvas.style.backgroundPosition = `${x}px ${y}px`;
  },

  /* Put a node in the middle of the view without changing the zoom.

     Used by the search and by "show this step's nodes". Jumping the zoom as
     well would answer "where is it" by rearranging everything around it. */
  centreOn(node) {
    const element = node._el;
    const rect = this.dom.canvas.getBoundingClientRect();
    const width = element ? element.offsetWidth : 240;
    const height = element ? element.offsetHeight : 120;
    this.view.x = rect.width / 2 - (node.pos[0] + width / 2) * this.view.scale;
    this.view.y = rect.height / 2 - (node.pos[1] + height / 2) * this.view.scale;
    this.applyView();
    this.drawWires();
  },

  /* Which nodes match a search: title, type, and the parameter values.

     The values matter as much as the titles. "Which node was pointing at that
     tpr" and "where did I set 310" are the questions a fifty-node graph makes
     unanswerable by eye, and they are questions about values. */
  search(query) {
    const needle = String(query || '').trim().toLowerCase();
    if (!needle) return [];
    const hits = [];
    for (const node of this.nodes.values()) {
      const def = this.defs[node.type] || {};
      const haystack = [node.title, def.title, node.type];
      for (const [name, value] of Object.entries(node.params || {})) {
        if (value === null || value === undefined || value === '') continue;
        haystack.push(name, String(value));
      }
      const where = haystack.filter(Boolean).map((part) => String(part).toLowerCase());
      if (where.some((part) => part.includes(needle))) hits.push(node);
    }
    // In reading order, so "next" walks the graph the way it is laid out
    // rather than the order the nodes happen to have been created in.
    hits.sort((a, b) => (a.pos[1] - b.pos[1]) || (a.pos[0] - b.pos[0]));
    return hits;
  },

  /* Nodes a run would take from the cache rather than compute. Drawn on the
     node itself: a list in a panel says the same thing, but not next to the
     thing it is about. Cleared the moment a run starts, since from then on
     the border tells the truth about what actually happened. */
  markCached(ids) {
    const wanted = new Set(ids);
    for (const [id, node] of this.nodes) {
      if (node._el) node._el.classList.toggle('will-cache', wanted.has(id));
    }
  },

  markFound(ids) {
    for (const node of this.nodes.values()) {
      if (node._el) node._el.classList.toggle('found', ids.includes(node.id));
    }
  },

  screenToWorld(clientX, clientY) {
    const rect = this.dom.canvas.getBoundingClientRect();
    return {
      x: (clientX - rect.left - this.view.x) / this.view.scale,
      y: (clientY - rect.top - this.view.y) / this.view.scale,
    };
  },

  viewCenter() {
    const rect = this.dom.canvas.getBoundingClientRect();
    return this.screenToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
  },

  /* Push apart any nodes that sit on top of each other.

     Column by column, top to bottom: a node that overlaps one already placed
     is moved straight down until it clears it. Nothing moves sideways, so
     the shape of the graph -- what feeds what, left to right -- is kept, and
     a graph that already has room stays exactly as it is. Real sizes are
     used, so a node that grew taller after it was placed is what gets the
     room made for it. Returns how many nodes moved. */
  tidy(gap = 40) {
    const boxes = [];
    for (const node of this.nodes.values()) {
      if (!node._el) continue;
      boxes.push({ node, x: node.pos[0], y: node.pos[1],
                   w: node._el.offsetWidth, h: node._el.offsetHeight });
    }
    boxes.sort((a, b) => (a.x - b.x) || (a.y - b.y));
    const placed = [];
    let moved = 0;
    for (const box of boxes) {
      let y = box.y;
      for (let guard = 0; guard < 500; guard += 1) {
        const hit = placed.find((other) =>
          box.x < other.x + other.w + gap && box.x + box.w + gap > other.x
          && y < other.y + other.h + gap && y + box.h + gap > other.y);
        if (!hit) break;
        y = hit.y + hit.h + gap;
      }
      if (Math.round(y) !== box.y) {
        if (!moved) this.mark('tidy');
        box.node.pos[1] = Math.round(y);
        box.node._el.style.top = `${box.node.pos[1]}px`;
        moved += 1;
      }
      box.y = y;
      placed.push(box);
    }
    if (moved) {
      this.drawWires();
      this.changed();
      this.settleGroups();
    }
    return moved;
  },

  /* Add a node beside another and wire the two together.

     The new node goes to the right of the source, in the first free spot,
     and every input of the new node that is plainly the same kind of file
     as an output of the source is connected -- structure to structure,
     topology to topology. The loose kinds ("any", "file") are not wired on a
     guess: a wire that says "some file" is the wire that fails three nodes
     later. Returns {node, wired: [[outputLabel, inputLabel], ...]}. */
  addAfter(sourceId, type) {
    const source = this.nodes.get(sourceId);
    if (!source || !source._el) return { node: this.addNode(type, 0, 0), wired: [] };
    const width = type === 'util.note' ? 536 : 236;
    const spot = this.freeSpot(width, 320,
      source.pos[0] + source._el.offsetWidth + 80, source.pos[1]);
    const node = this.addNode(type, spot.x, spot.y);
    if (!node) return null;
    const sdef = this.defs[source.type] || {};
    const tdef = this.defs[node.type] || {};
    const used = new Set();
    const wired = [];
    // Required inputs first: they are the ones the node cannot run without.
    const inputs = [...(tdef.inputs || [])].sort((a, b) => Number(!!a.optional) - Number(!!b.optional));
    for (const inp of inputs) {
      if (!this.portShown(node, inp)) continue;
      const want = portType(node, inp);
      if (LOOSE.has(want)) continue;
      for (const out of sdef.outputs || []) {
        if (used.has(out.name) || !this.portShown(source, out)) continue;
        if (portType(source, out) !== want) continue;
        if (this.connect(source.id, out.name, node.id, inp.name)) {
          used.add(out.name);
          wired.push([out.label || out.name, inp.label || inp.name]);
        }
        break;
      }
    }
    return { node, wired };
  },

  fit() {
    if (!this.nodes.size && !this.groups.length) return;
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    for (const group of this.groups) {
      minX = Math.min(minX, group.bounds[0]);
      minY = Math.min(minY, group.bounds[1]);
      maxX = Math.max(maxX, group.bounds[0] + group.bounds[2]);
      maxY = Math.max(maxY, group.bounds[1] + group.bounds[3]);
    }
    for (const node of this.nodes.values()) {
      const width = node._el ? node._el.offsetWidth : 240;
      const height = node._el ? node._el.offsetHeight : 120;
      minX = Math.min(minX, node.pos[0]);
      minY = Math.min(minY, node.pos[1]);
      maxX = Math.max(maxX, node.pos[0] + width);
      maxY = Math.max(maxY, node.pos[1] + height);
    }
    const rect = this.dom.canvas.getBoundingClientRect();
    const pad = 50;
    const scale = Math.min(1.2,
      Math.min((rect.width - pad * 2) / (maxX - minX), (rect.height - pad * 2) / (maxY - minY)));
    this.view.scale = Math.max(ZOOM_MIN, scale);
    this.view.x = pad - minX * this.view.scale
      + (rect.width - pad * 2 - (maxX - minX) * this.view.scale) / 2;
    this.view.y = pad - minY * this.view.scale
      + (rect.height - pad * 2 - (maxY - minY) * this.view.scale) / 2;
    this.applyView();
  },

  /* Which pointing device this browser is being used with.

     Kept in the browser rather than in the settings file on purpose: it
     describes the thing in front of you, not the machine doing the work. The
     same server opened from a desktop and from a laptop should answer
     differently, and it does. */
  pointer() {
    try {
      return localStorage.getItem('comfygmx.pointer') || 'mouse';
    } catch (err) {
      return 'mouse';          // a browser refusing storage still has to work
    }
  },

  setPointer(kind) {
    try { localStorage.setItem('comfygmx.pointer', kind); } catch (err) { /* fine */ }
  },

  /* Does this turn of the wheel mean zoom, or slide the canvas?

     One place, and a named one, because it is a rule rather than a detail:

       * A pinch on a trackpad reaches the browser as the wheel turning with
         Ctrl held. That is the only thing that tells a pinch apart from two
         fingers sliding, so Ctrl always means zoom, whatever is set.
       * With a mouse, the wheel turning means zoom, which is what it has
         always meant here.
       * With a trackpad, two fingers sliding means slide, which is what two
         fingers sliding means everywhere else on the machine.

     Cmd is here for Macs, where the browser sends that instead. */
  wheelMeans(event) {
    if (event.ctrlKey || event.metaKey) return 'zoom';
    return this.pointer() === 'trackpad' ? 'pan' : 'zoom';
  },

  /* ------------------------------------------------------ interactions */
  _bindCanvas() {
    const canvas = this.dom.canvas;

    // Space held down means the next drag moves the canvas. Watched on the
    // whole page, because the hand is on the canvas and the keyboard focus is
    // wherever it happens to be; but never while something is being typed, or
    // a space in the middle of a node's name would grab the canvas instead.
    const typing = () => {
      const el = document.activeElement;
      return !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
                      || el.isContentEditable);
    };
    document.addEventListener('keydown', (event) => {
      if (event.code !== 'Space' || event.repeat || typing()) return;
      this._spaceDown = true;
      canvas.classList.add('ready-to-pan');
      // Without this the page scrolls, and in a modal the button under the
      // pointer gets pressed.
      if (!event.target.closest('button')) event.preventDefault();
    });
    document.addEventListener('keyup', (event) => {
      if (event.code !== 'Space') return;
      this._spaceDown = false;
      canvas.classList.remove('ready-to-pan');
    });
    // Alt-tabbing away with space held would leave it stuck down for ever.
    window.addEventListener('blur', () => {
      this._spaceDown = false;
      canvas.classList.remove('ready-to-pan');
    });

    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      // What this turn of the wheel means is decided in one place: see
      // wheelMeans above.
      if (this.wheelMeans(event) === 'pan') {
        this.view.x -= event.deltaX;
        this.view.y -= event.deltaY;
        this.applyView();
        return;
      }
      const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
      const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, this.view.scale * factor));
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      this.view.x = px - (px - this.view.x) * (next / this.view.scale);
      this.view.y = py - (py - this.view.y) * (next / this.view.scale);
      this.view.scale = next;
      this.applyView();
    }, { passive: false });

    canvas.addEventListener('mousedown', (event) => {
      if (event.target.closest('.node')) return;
      if (event.button === 1 || this._spaceDown
          || (event.button === 0 && event.altKey)) {
        this._pan = { x: event.clientX, y: event.clientY, vx: this.view.x, vy: this.view.y };
        canvas.classList.add('panning');
        event.preventDefault();
        return;
      }
      if (event.button === 0) {
        if (!additive(event)) this.select([]);
        const start = { x: event.clientX, y: event.clientY };
        // Armed, not shown. Unhiding here paints the box at whatever size the
        // last drag left it in, so a plain click on empty canvas flashed the
        // previous selection rectangle back up and it stayed there until the
        // mouse moved. It is shown on the first move that is a drag.
        this._marquee = { start, additive: additive(event), live: false };
      }
    });

    canvas.addEventListener('contextmenu', (event) => {
      if (event.target.closest('.node') || event.target.closest('.wire')) return;
      event.preventDefault();
      const world = this.screenToWorld(event.clientX, event.clientY);
      const selected = this.selection.size;
      // The group menu hangs off the title bar, which is a small target and
      // not where the hand goes. Right-clicking anywhere inside the box gets
      // the one entry people come for.
      const here = this.groupAt(world.x, world.y);
      UI.contextMenu(event.clientX, event.clientY, [
        here ? { label: `Run ${here.title} and everything before it`, action: () => {
          const members = this.nodesInGroup(here);
          if (!members.length) { UI.toast('nothing in that group', 'warn'); return; }
          App.run(members);
        } } : null,
        here ? { label: `Run just ${here.title}`, action: () => {
          const members = this.nodesInGroup(here);
          if (!members.length) { UI.toast('nothing in that group', 'warn'); return; }
          App.run(members, members, { isolate: true });
        } } : null,
        here ? '-' : null,
        { label: 'Add node…', action: () => App.openNodeSearch(world) },
        { label: 'Add chunk…', action: () => App.openChunkPicker(world) },
        '-',
        selected
          ? { label: `Group ${selected} selected node${selected === 1 ? '' : 's'} (Ctrl+G)`,
              action: () => App.groupSelection() }
          : { label: 'New group here',
              action: () => {
                this.mark('new group');
                this.addGroup('group', [world.x, world.y, 420, 260],
                  GROUP_COLORS[this.groups.length % GROUP_COLORS.length][1]);
              } },
        selected
          ? { label: `Save ${selected} selected node${selected === 1 ? '' : 's'} as a chunk…`,
              action: () => App.saveChunk(this.selected()) }
          : null,
        '-',
        { label: 'Fit to view', action: () => this.fit() },
        { label: 'Paste', action: () => App.paste(world) },
      ].filter(Boolean));
    });

    window.addEventListener('mousemove', (event) => this._onMove(event));
    window.addEventListener('mouseup', (event) => this._onUp(event));
  },

  _startNodeDrag(event, node) {
    if (event.button !== 0) return;
    event.preventDefault();
    if (!this.selection.has(node.id)) this.select([node.id], additive(event));
    const world = this.screenToWorld(event.clientX, event.clientY);
    this._drag = {
      startX: world.x, startY: world.y,
      origins: [...this.selection].map((id) => {
        const target = this.nodes.get(id);
        return { id, x: target.pos[0], y: target.pos[1] };
      }),
      // Boxes that are part of the selection travel with it. Without this a
      // chunk you had selected came apart the moment you moved it: the nodes
      // went and the coloured rectangle stayed where it was.
      boxes: this.groups
        .filter((group) => this.selectedGroups.has(group.id))
        .map((group) => ({ group, x: group.bounds[0], y: group.bounds[1] })),
    };
  },

  _startLinkDrag(event, node, port, direction, wallDot) {
    event.preventDefault();
    event.stopPropagation();

    // Grabbing a connected input picks the wire up rather than starting a new one.
    if (direction === 'in') {
      const existing = this.links.find((l) => l.to_node === node.id && l.to_port === port.name);
      if (existing && !event.shiftKey) {
        const source = this.nodes.get(existing.from_node);
        const sourcePort = this.defs[source.type].outputs
          .find((p) => p.name === existing.from_port);
        // If the wire came through a wall, it is picked up from the last dot
        // it passed through: that is the stretch you were holding, and the
        // wire you carry should hang from where it did, not jump back to
        // the block on the far side of the box.
        const through = this._cablesUsedBy(existing);
        const last = through[through.length - 1];
        const fromDot = last && this._groupDots.get(
          `${last.group.id}|${existing.from_node}|${existing.from_port}|out`);
        const picked = { ...existing };
        this.disconnect(node.id, port.name, { keepCables: true });
        this._beginLink(source, sourcePort, 'out', event, fromDot);
        this._linkDrag.pickedUp = picked;
        return;
      }
    }
    this._beginLink(node, port, direction, event, wallDot);
  },

  _beginLink(node, port, direction, event, wallDot) {
    const temp = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    temp.setAttribute('class', 'wire dragging');
    temp.setAttribute('stroke',
      PORT_COLORS[portType(node, port)] || PORT_COLORS.any);
    this.dom.wires.appendChild(temp);
    this._linkDrag = { node, port, direction, temp, dot: wallDot || null };
    this._highlightCompatible(node, port, direction);
    this._onMove(event);
  },

  _highlightCompatible(node, port, direction) {
    const wanted = direction === 'out' ? 'in' : 'out';
    const dragged = portType(node, port);
    // A chunk's all-purpose dot takes anything, so marking it by type alone
    // would light up every box on the canvas the moment any wire was picked
    // up -- fourteen of them in the three-replicate workflow. It is marked
    // only when the chunk really does have somewhere for this wire to go,
    // which is the same question answered when the wire is let go.
    // A wall takes anything that comes out of something, so the only question
    // is which way round the wire is. Marking it by type would light up every
    // box on the canvas -- fourteen of them in the three-replicate workflow --
    // and say nothing.
    const wallsOpen = direction === 'out';
    for (const dot of this.dom.world.querySelectorAll('.port')) {
      if (dot.dataset.wall) {
        dot.classList.toggle('compatible', wallsOpen);
        dot.classList.toggle('incompatible', !wallsOpen);
        continue;
      }
      if (dot.dataset.dir !== wanted) continue;
      const fits = typesCompatible(dragged, dot.dataset.type);
      dot.classList.toggle('compatible', fits);
      dot.classList.toggle('incompatible', !fits);
    }
  },

  _onMove(event) {
    if (this._groupDrag) {
      const drag = this._groupDrag;
      const world = this.screenToWorld(event.clientX, event.clientY);
      const dx = world.x - drag.startX;
      const dy = world.y - drag.startY;
      const snap = event.ctrlKey ? 1 : 8;
      const round = (v) => Math.round(v / snap) * snap;
      drag.group.bounds[0] = round(drag.ox + dx);
      drag.group.bounds[1] = round(drag.oy + dy);
      this._applyGroup(drag.group);
      for (const member of drag.members) {
        const node = this.nodes.get(member.id);
        if (!node) continue;
        node.pos[0] = round(member.x + dx);
        node.pos[1] = round(member.y + dy);
        node._el.style.left = `${node.pos[0]}px`;
        node._el.style.top = `${node.pos[1]}px`;
      }
      for (const nest of drag.nested) {
        nest.g.bounds[0] = round(nest.x + dx);
        nest.g.bounds[1] = round(nest.y + dy);
        this._applyGroup(nest.g);
      }
      this.drawWires();
      return;
    }
    if (this._pan) {
      this.view.x = this._pan.vx + (event.clientX - this._pan.x);
      this.view.y = this._pan.vy + (event.clientY - this._pan.y);
      this.applyView();
      return;
    }
    if (this._drag) {
      const world = this.screenToWorld(event.clientX, event.clientY);
      const dx = world.x - this._drag.startX;
      const dy = world.y - this._drag.startY;
      const snap = event.ctrlKey ? 1 : 8;
      for (const origin of this._drag.origins) {
        const node = this.nodes.get(origin.id);
        if (!node) continue;
        node.pos[0] = Math.round((origin.x + dx) / snap) * snap;
        node.pos[1] = Math.round((origin.y + dy) / snap) * snap;
        node._el.style.left = `${node.pos[0]}px`;
        node._el.style.top = `${node.pos[1]}px`;
      }
      for (const origin of this._drag.boxes || []) {
        origin.group.bounds[0] = Math.round((origin.x + dx) / snap) * snap;
        origin.group.bounds[1] = Math.round((origin.y + dy) / snap) * snap;
        this._applyGroup(origin.group);
      }
      this.drawWires();
      return;
    }
    if (this._linkDrag) {
      const world = this.screenToWorld(event.clientX, event.clientY);
      // Started on a wall? Then the wire should come out from under the
      // pointer, at the dot you took hold of, not from the block on the far
      // side of the box. A dot that works like a block's socket sets off to
      // the right, as a block's output does; any other wall dot has no fixed
      // side, so the wire leans whichever way you are pulling it. The same
      // rule the finished wire follows (see _wallGoesRight).
      const dot = this._linkDrag.dot;
      const anchor = (dot && this.groupPortCenter(dot))
        || this.portCenter(this._linkDrag.node.id, this._linkDrag.port.name,
          this._linkDrag.direction);
      if (anchor) {
        const home = this._homeOf && this._homeOf.get(this._linkDrag.node.id);
        const role = dot && home !== dot.dataset.group ? 'in' : 'out';
        const lean = !dot || this._wallGoesRight(dot, role)
          ? 1 : (world.x >= anchor.x ? 1 : -1);
        const path = this._linkDrag.direction === 'out'
          ? this._bezier(anchor, world, lean, -lean)
          : this._bezier(world, anchor);
        this._linkDrag.temp.setAttribute('d', path);
      }
      return;
    }
    if (this._marquee) {
      const { start } = this._marquee;
      if (!this._marquee.live) {
        // The same 4px the mouseup uses to decide a click from a drag, so
        // what is drawn and what is selected agree.
        if (Math.abs(event.clientX - start.x) <= 4
            && Math.abs(event.clientY - start.y) <= 4) return;
        this._marquee.live = true;
        this.dom.marquee.classList.remove('hidden');
      }
      const box = this.dom.marquee;
      const rect = this.dom.canvas.getBoundingClientRect();
      const x1 = Math.min(start.x, event.clientX) - rect.left;
      const y1 = Math.min(start.y, event.clientY) - rect.top;
      box.style.left = `${x1}px`;
      box.style.top = `${y1}px`;
      box.style.width = `${Math.abs(event.clientX - start.x)}px`;
      box.style.height = `${Math.abs(event.clientY - start.y)}px`;
    }
  },

  _onUp(event) {
    if (this._groupDrag) {
      const label = this._groupDrag.group.title;
      this._groupDrag = null;
      this.mark(`move ${label}`);
      this.changed();
    }
    if (this._pan) {
      this._pan = null;
      this.dom.canvas.classList.remove('panning');
    }
    if (this._drag) {
      const moved = this._drag.origins.map((origin) => origin.id);
      // If boxes travelled with the selection then nothing moved relative to
      // anything else, so nothing has left anything.
      const carriedBoxes = (this._drag.boxes || []).length > 0;
      this._drag = null;
      if (!carriedBoxes) for (const id of moved) this._releaseIfOutside(id);
      this.mark('move');
      this.changed();
    }
    if (this._linkDrag) {
      const drag = this._linkDrag;
      drag.temp.remove();
      this._linkDrag = null;
      for (const dot of this.dom.world.querySelectorAll('.port')) {
        dot.classList.remove('compatible', 'incompatible');
      }
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const dot = target && target.closest ? target.closest('.port') : null;
      // A catch-all has no block and no socket behind it, so it must be dealt
      // with before the ordinary handling: that reads data-node and data-port
      // straight off the dot, and on a catch-all both are missing. The link
      // pushed on would name a block called "undefined", survive being saved,
      // and then be quietly dropped the next time the file was opened.
      if (dot && dot.dataset.wall) {
        this._dropOnWall(dot, drag, event);
      } else if (dot && dot.dataset.dir !== drag.direction) {
        if (!typesCompatible(drag.port.type, dot.dataset.type)) {
          UI.toast(`${drag.port.type} does not fit a ${dot.dataset.type} port`, 'warn');
        } else if (drag.direction === 'out') {
          this.connect(drag.node.id, drag.port.name, dot.dataset.node, dot.dataset.port);
        } else {
          this.connect(dot.dataset.node, dot.dataset.port, drag.node.id, drag.port.name);
        }
      }
      // A wire picked up by its end and carried: now it has landed (or been
      // dropped in empty space, which cuts it) it is known whether the dot it
      // hung from is still used. Not when it was let go on a wall -- that is
      // you asking for the cable to be on the wall, and it stays.
      if (drag.pickedUp && !(dot && dot.dataset.wall)) {
        this._dropSpentCables([drag.pickedUp]);
      }
      this.drawWires();
    }
    if (this._marquee) {
      const { start, additive } = this._marquee;
      this._marquee = null;
      this.dom.marquee.classList.add('hidden');
      const moved = Math.abs(event.clientX - start.x) > 4 || Math.abs(event.clientY - start.y) > 4;
      if (moved) {
        const a = this.screenToWorld(Math.min(start.x, event.clientX), Math.min(start.y, event.clientY));
        const b = this.screenToWorld(Math.max(start.x, event.clientX), Math.max(start.y, event.clientY));
        const hits = [];
        for (const node of this.nodes.values()) {
          const width = node._el.offsetWidth;
          const height = node._el.offsetHeight;
          if (node.pos[0] < b.x && node.pos[0] + width > a.x
            && node.pos[1] < b.y && node.pos[1] + height > a.y) hits.push(node.id);
        }
        this.select(hits, additive);
        // A box you drew right around a chunk means the chunk, not just the
        // nodes standing in it. Only boxes wholly inside count: touching the
        // edge of one is a selection that happens to overlap it, and taking
        // the whole thing then would be a surprise.
        for (const group of this.groups) {
          const [gx, gy, gw, gh] = group.bounds;
          if (gx >= a.x && gy >= a.y && gx + gw <= b.x && gy + gh <= b.y) {
            this.selectedGroups.add(group.id);
          }
        }
        this.paintGroupSelection();
      }
    }
  },

  _nodeMenu(event, node) {
    const source = this.structureSource(node.id);
    UI.contextMenu(event.clientX, event.clientY, [
      { label: 'Set this up step by step…', action: () => Forms.setup(node) },
      { label: 'Show command', action: () => App.showCommand(node.id) },
      ...(source ? [{ label: `What is in ${source.label}?`,
                      action: () => App.inspectStructure(node.id) },
                    { label: `What is missing from ${source.label}?`,
                      action: () => App.inspectMissing(node.id) }] : []),
      ...(node.type === 'gmx.editconf'
        ? [{ label: 'Pick the box by eye…',
             action: () => App.pickBoxAround(node.id) }]
        : []),
      // Two different things, so they are named for the difference.
      //   "up to here"  -- this node and everything feeding into it. Anything
      //                    whose answer is already on disk is reused, the rest
      //                    is worked out again.
      //   "just this"   -- this node and nothing else. What the nodes before
      //                    it produced last time is taken from disk as it
      //                    stands. If one of them has never run there is
      //                    nothing to take, and it says so instead of
      //                    quietly running half the graph.
      { label: 'Run up to here (this node and everything before it)',
        action: () => App.run([node.id]) },
      { label: 'Run just this node (reuse what came before)',
        action: () => App.run([node.id], [node.id], { isolate: true }) },
      '-',
      { label: 'Group selection (Ctrl+G)', action: () => App.groupSelection() },
      { label: 'Save selection as a chunk…', action: () => App.saveChunk(this.selected()) },
      '-',
      { label: 'Duplicate', action: () => this.duplicateSelection() },
      (() => {
        // The selection if this block is part of it, so switching off five
        // selected blocks is one right-click, the same as Duplicate.
        const ids = this.selection.has(node.id) ? this.selected() : [node.id];
        const on = ids.some((id) => !(this.nodes.get(id) || {}).off);
        const many = ids.length > 1 ? ` (${ids.length} blocks)` : '';
        return {
          label: on ? `Switch off: leave out of runs${many}` : `Switch back on${many}`,
          hint: 'Ctrl+M',
          action: () => this.toggleOff(ids),
        };
      })(),
      { label: node.pause ? 'Do not stop here any more'
                          : 'Stop the run here, before this node',
        action: () => {
          node.pause = !node.pause;
          this.mark(node.pause ? `stop at ${node.title}` : `do not stop at ${node.title}`);
          this._refreshNodeElement(node);
          this.drawWires();
          this.changed();
          UI.toast(node.pause
            ? 'the run will stop here and wait. Everything before it will have '
              + 'finished, so you can look at it and change this node before '
              + 'pressing Continue.'
            : 'the run will not stop here any more', 'info', 8000);
        } },
      { label: node.collapsed ? 'Expand' : 'Collapse', action: () => {
        node.collapsed = !node.collapsed;
        this.mark(node.collapsed ? 'collapse' : 'expand');
        this._refreshNodeElement(node);
        this.drawWires();
        this.changed();
      } },
      { label: 'Reset parameters', action: () => {
        const def = this.defs[node.type];
        node.params = {};
        for (const param of def.params) node.params[param.name] = param.default;
        this.mark(`reset ${node.title}`);
        this._refreshNodeElement(node);
        this.changed();
      } },
      '-',
      { label: 'Documentation', action: () => {
        const def = this.defs[node.type];
        if (def.docs) window.open(def.docs, '_blank', 'noopener');
        else UI.toast('no documentation link for this node', 'info');
      } },
      { label: 'Delete', action: () => {
        for (const id of [...this.selection]) this.removeNode(id);
      } },
    ]);
  },
};

function typesCompatible(a, b) {
  if (a === b) return true;
  // 'any' and 'file' are deliberate wildcards; the specific types are not
  // interchangeable -- a .top handed to a -f flag fails in a confusing way.
  return LOOSE.has(a) || LOOSE.has(b);
}
