/* Do the run-parameters boxes show the value the run will use, and only the
   boxes that matter for it?

   A "Run parameters (.mdp)" block has a box for each of the options people
   change: a dozen on its face, the rest in drawers. Left empty, a box means
   "whatever the preset says", or in raw mode whatever the text says, or in
   file mode whatever the file says. What has to stay true:

     * an empty box shows that value from the moment the block appears: the
       preset's, the text's, or GROMACS's own default when neither sets it,
       and never the words "preset default"; a box nobody gives a value says
       that it is not set
     * changing the preset, the mode or the raw text redraws the block, or
       its boxes go on showing the old values
     * in raw mode, typing in a box changes that line of the text, keeping
       its comment, instead of being silently ignored
     * outside raw mode, editing a box still turns the preset into an edited
       copy of it, as before
     * in raw mode the face of the block is the text and a summary of it: no
       preset name, no file name, and the value boxes in the drawer
     * a box that does nothing for the run as it will be is hidden: no time
       step on a minimisation, no pressure boxes without pressure control;
       while the file is not read yet, nothing is hidden
     * the summary card says in words what the settings add up to, and warns
       about combinations GROMACS refuses; no preset of our own draws a
       warning
     * option names are one option however they are written (vdw_type,
       VDW-TYPE), and a value in a dropdown is picked in the list's own
       spelling (v-rescale is V-rescale)
     * a drawer that was opened stays open when the block is drawn again

   Run:  node tools/mdp_boxes.js
   It loads the editor with a stand-in for the page, so it needs neither a
   browser nor a running server. The real block definition and presets come
   from the Python side, through python3 (or the one named in
   COMFYGMX_PYTHON), run in this repository. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

const ROOT = path.join(__dirname, '..');

function makeElement() {
  const el = {
    tagName: 'DIV', children: [], style: {}, dataset: {},
    appendChild(child) { el.children.push(child); return child; },
    remove() {}, setAttribute() {}, addEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { x: 0, y: 0, width: 236, height: 120 }; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
  return el;
}

const sandbox = {
  console,
  document: {
    getElementById: () => makeElement(), createElement: () => makeElement(),
    createTextNode: (text) => ({ textContent: text }),
    addEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
    body: makeElement(),
  },
  window: { addEventListener() {} },
  navigator: {},
  requestAnimationFrame: (fn) => fn(),
  ResizeObserver: function ResizeObserver() {
    return { observe() {}, unobserve() {}, disconnect() {} };
  },
  setTimeout, clearTimeout,
  fetch: () => Promise.reject(new Error('no network in this test')),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(
  path.join(ROOT, 'comfygmx', 'web', 'js', 'graph.js'), 'utf8')
  + '\n;globalThis.__Editor = Editor;'
  + '\nglobalThis.__mdp = { MdpFiles, mdpSummary, mdpFill, mdpRawOptions, mdpSetRaw };',
  sandbox);
const Editor = sandbox.__Editor;
const { MdpFiles, mdpSummary, mdpFill, mdpRawOptions, mdpSetRaw } = sandbox.__mdp;

// Every block has a box for which installation to run with; there are none
// here.
sandbox.App = { installChoices: () => [] };

// Just enough of the page's element maker to build boxes and drawers, and
// to press them: every element keeps the handlers it was given.
const made = [];
sandbox.UI = {
  el(tag, attrs = {}, children = []) {
    const el = makeElement();
    el.tagName = String(tag).toUpperCase();
    el.handlers = {};
    el.addEventListener = (type, fn) => { el.handlers[type] = fn; };
    el.insertBefore = () => {};
    Object.assign(el, attrs);
    for (const child of [].concat(children || [])) if (child) el.appendChild(child);
    made.push(el);
    return el;
  },
};

let failures = 0;
const check = (ok, what) => { if (!ok) { failures += 1; console.log(`  FAIL  ${what}`); } };
const same = (got, want, what) =>
  check(JSON.stringify(got) === JSON.stringify(want),
        `${what}\n        got:  ${JSON.stringify(got)}\n        want: ${JSON.stringify(want)}`);

async function main() {
  // What the server sends (/api/mdp/presets), cut down to what is tested in
  // the first part.
  Editor.mdp = {
    presets: {
      md_atomistic: { nsteps: 50000000, dt: 0.002, 'ref-t': '310 310', pcoupl: 'C-rescale' },
    },
    widgets: { nsteps: 'nsteps', dt: 'dt', ref_t: 'ref-t', tau_t: 'tau-t',
               pcoupl: 'pcoupl', nstlog: 'nstlog', gen_seed: 'gen-seed' },
    gromacs_defaults: { nsteps: '0', dt: '0.001', pcoupl: 'no', nstlog: '1000',
                        'gen-seed': '-1' },
    default_name: 'run.mdp',
  };
  const box = (name) => ({ name, placeholder: 'preset default' });
  const shows = (node, name, bare) => Editor._placeholder(node, box(name), bare);

  console.log('a preset: its values, and GROMACS\'s where it has none');
  const preset = { id: 'm', type: 'util.mdp', params: { mode: 'preset', preset: 'md_atomistic' } };
  same(shows(preset, 'dt'), '0.002  (from md_atomistic)', 'dt does not show the preset\'s value');
  same(shows(preset, 'nstlog'), '1000  (GROMACS default)',
       'an option the preset does not set does not show GROMACS\'s own value');
  same(shows(preset, 'pcoupl', true), 'C-rescale', 'a dropdown\'s empty entry lost the preset\'s value');
  same(shows(preset, 'tau_t'), 'not set by md_atomistic',
       'an option nobody gives a value should say so, not "preset default"');
  check(!Editor._mdpShown(preset, box('tau_t')), 'a box with no value is drawn as if it had one');
  same(Editor._placeholder(preset, { name: 'define', placeholder: 'e.g. -DPOSRES' }), 'e.g. -DPOSRES',
       'define lost its example: leaving it out is the usual case');
  check(Editor._mdpShown(preset, box('dt')), 'a known value is not marked to be drawn readable');
  check(!Editor._mdpShown({ type: 'gmx.grompp', params: {} }, box('dt')),
        'a box on another block was treated as a run parameter');

  console.log('raw mode: the values in the text');
  const heat = [
    '; Heat the cube',
    'nsteps                   = 100000     ; 200 ps',
    'dt       = 0.002',
    'ref_t    = 200',
    '',
  ].join('\n');
  const raw = { id: 'r', type: 'util.mdp',
                params: { mode: 'raw', preset: 'md_atomistic', raw: heat } };
  same(shows(raw, 'nsteps'), '100000  (from the raw text)', 'raw mode does not show the text\'s nsteps');
  same(shows(raw, 'ref_t'), '200  (from the raw text)',
       'an option written with an underscore was not read');
  same(shows(raw, 'nstlog'), '1000  (GROMACS default)',
       'an option the text leaves out does not show GROMACS\'s own value');
  same(shows(raw, 'tau_t'), 'not in the raw text',
       'an option the text leaves out, with no GROMACS default, should say so');
  same(shows({ type: 'util.mdp', params: { mode: 'file' } }, 'dt'), 'as in the file',
       'file mode should not claim the preset\'s values: the file decides');

  console.log('raw mode: typing in a box changes that line of the text');
  raw.params.nsteps = '150000';
  check(Editor.applyFollows(raw, 'nsteps', '150000'), 'typing in raw mode did nothing');
  check(raw.params.raw.includes('nsteps                   = 150000     ; 200 ps'),
        `the nsteps line was not changed in place, comment kept:\n${raw.params.raw}`);
  same(raw.params.nsteps, '', 'the box should empty again and show the text\'s value');
  same(shows(raw, 'nsteps'), '150000  (from the raw text)', 'the box does not show the new value');
  raw.params.ref_t = '250';
  Editor.applyFollows(raw, 'ref_t', '250');
  check(raw.params.raw.includes('ref_t    = 250'),
        `the line written with an underscore was not changed:\n${raw.params.raw}`);
  raw.params.nstlog = '500';
  Editor.applyFollows(raw, 'nstlog', '500');
  check(raw.params.raw.endsWith('nstlog = 500\n'),
        `an option the text did not set was not added at the end:\n${raw.params.raw}`);
  same(raw.params.mode, 'raw', 'typing in raw mode changed the mode');
  same(raw.params.raw.split('\n')[0], '; Heat the cube', 'the text\'s own comments were lost');

  console.log('a preset: editing a box still makes an edited copy');
  preset.params.nsteps = '5000';
  check(Editor.applyFollows(preset, 'nsteps', '5000'), 'editing a preset box did nothing');
  same(preset.params.mode, 'manual', 'editing a preset box did not switch it to manual');
  same(preset.params.filename, 'md_atomistic_edited.mdp', 'the edited copy was not renamed');

  console.log('changing the preset, the mode or the raw text redraws the boxes');
  Editor.defs = { 'util.mdp': { params: [], inputs: [], outputs: [{ name: 'mdp', type: 'mdp' }] } };
  Editor.mark = () => {};
  Editor.changed = () => {};
  const redrawn = [];
  const realRefresh = Editor._refreshNodeElement;
  Editor._refreshNodeElement = (node) => { redrawn.push(node.id); };
  for (const [name, type, choices, value] of [
    ['preset', 'choice', ['md_atomistic', 'em_atomistic'], 'em_atomistic'],
    ['mode', 'choice', ['preset', 'manual', 'file', 'raw'], 'raw'],
    ['raw', 'text', null, 'nsteps = 10\n'],
  ]) {
    const node = { id: name, type: 'util.mdp', title: 'Run parameters',
                   params: { mode: 'preset', preset: 'md_atomistic' }, _el: makeElement() };
    Editor.nodes.set(node.id, node);
    made.length = 0;
    Editor._buildWidget(node, { name, type, label: name, choices });
    const input = made.find((el) => el.handlers.change);
    input.value = value;
    input.handlers.change();
    if (name === 'raw') {
      // A text box commits when you leave it, usually by clicking the next
      // box; redrawing there and then would rebuild that box under the
      // pointer, so the redraw waits until the click has landed.
      check(!redrawn.includes(name), 'the raw text redrew the block while the click that '
        + 'ended the edit was still landing');
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    check(redrawn.includes(name),
          `changing ${name} did not redraw the block, so its boxes go on showing the old values`);
    Editor.nodes.delete(node.id);
  }
  Editor._refreshNodeElement = realRefresh;

  // From here on, the real block and the real presets.
  const table = JSON.parse(execFileSync(process.env.COMFYGMX_PYTHON || 'python3', ['-c', [
    'import json',
    'from comfygmx.server import mdp_presets_table',
    'from comfygmx.nodes.util_nodes import MdpNode',
    'print(json.dumps({"mdp": mdp_presets_table(), "def": MdpNode.spec()}))',
  ].join('\n')], { cwd: ROOT, encoding: 'utf8' }));
  Editor.mdp = table.mdp;
  Editor.defs = { 'util.mdp': table.def };
  const params = table.def.params;
  const param = (name) => params.find((p) => p.name === name);
  const block = (values) => ({ id: 'b', type: 'util.mdp', title: 'Run parameters',
                               params: { mode: 'preset', preset: 'md_atomistic', ...values } });
  const face = (node) => params.filter((p) => Editor.paramShown(node, p)
    && !Editor._placement(node, p).advanced).map((p) => p.name);
  const visible = (node, name) => Editor.paramShown(node, param(name));

  console.log('raw mode: the text and its summary on the face, the boxes in the drawer');
  const ice = [
    '; Minimise the ice',
    'integrator = steep',
    'nsteps     = 5000',
    'emtol      = 100',
    'coulombtype = PME',
    '',
  ].join('\n');
  const rawBlock = block({ mode: 'raw', raw: ice });
  same(face(rawBlock), ['mode', 'raw'],
       'raw mode shows more than the text on the face of the block');
  for (const name of ['preset', 'path', 'saved', 'extra_flags']) {
    check(!visible(rawBlock, name), `raw mode still shows "${param(name).label}", which it does not use`);
  }
  same(Editor._placement(rawBlock, param('nsteps')), { advanced: true, section: 'Main settings' },
       'in raw mode the number of steps is not under "Main settings" in the drawer');
  same(Editor._placement(rawBlock, param('tcoupl')), { advanced: true, section: 'Temperature' },
       'in raw mode a box of a topic drawer moved out of its topic');
  same(Editor._placement(block({}), param('nsteps')), { advanced: false, section: '' },
       'outside raw mode the number of steps left the face of the block');
  const mains = params.filter((p) => Editor.paramShown(rawBlock, p)
    && Editor._placement(rawBlock, p).section === 'Main settings').map((p) => p.name);
  same(mains, ['integrator', 'nsteps', 'emtol', 'emstep', 'define', 'nstxout_compressed'],
       'the main settings of a raw minimisation are not the ones it uses');

  console.log('an edited preset switched to raw: the text decides, not the boxes');
  const switched = block({ nsteps: '1000' });
  Editor.applyFollows(switched, 'nsteps', '1000');
  same(switched.params.mode, 'manual', 'typing in a box of a preset did not make it manual');
  switched.params.mode = 'raw';
  Editor.applyFollows(switched, 'mode', 'raw');
  switched.params.raw = 'integrator = steep\nnsteps = 5000\nemtol = 100\n';
  same(Object.keys(table.mdp.widgets).concat('define').filter((p) => String(switched.params[p] || '')),
       [], 'boxes filled in from the edited preset stay set in raw mode, where the run ignores them');
  same(switched.params.filename, 'run.mdp', 'your own text is still named after the edited preset');
  same(mdpSummary(switched).lines[0],
       'Energy minimisation (steepest descent): up to 5,000 steps, until no force is above 100 kJ/mol/nm',
       'the card of your own text describes values left in the boxes');
  switched.params.nsteps = '7';
  same(mdpSummary(switched).lines[0].includes('up to 5,000 steps'), true,
       'in raw mode the card takes a value left in a box, which the run does not');

  console.log('a box that does nothing for the run is hidden');
  same(face(block({ preset: 'em_atomistic' })),
       ['mode', 'preset', 'integrator', 'nsteps', 'emtol', 'emstep', 'define',
        'nstxout_compressed', 'saved'],
       'a minimisation preset does not show its own boxes on the face');
  same(face(block({ preset: 'md_atomistic' })),
       ['mode', 'preset', 'integrator', 'nsteps', 'dt', 'ref_t', 'pcoupl', 'define',
        'nstxout_compressed', 'saved'],
       'a dynamics preset does not show its own boxes on the face');
  for (const name of ['dt', 'ref_t', 'pcoupl', 'tcoupl', 'gen_vel', 'comm_mode', 'ref_p']) {
    check(!visible(block({ preset: 'em_atomistic' }), name),
          `a minimisation shows "${param(name).label}", which only dynamics uses`);
  }
  check(visible(block({ preset: 'em_atomistic', integrator: 'cg' }), 'nstcgsteep'),
        'conjugate gradients typed in the box does not show its own setting');
  check(!visible(block({ preset: 'em_atomistic', integrator: 'cg' }), 'emstep'),
        'conjugate gradients still shows the steepest-descent step size');
  const sd = block({ integrator: 'sd' });
  check(visible(sd, 'ld_seed'), 'sd does not show its random seed');
  check(!visible(sd, 'tcoupl'), 'sd shows a thermostat box that GROMACS switches off for it');
  check(visible(sd, 'tau_t') && visible(sd, 'ref_t'), 'sd hides its temperature boxes');
  check(!visible(sd, 'nsttcouple'), 'sd shows how often a thermostat it does not use acts');
  check(visible(block({ integrator: 'bd' }), 'bd_fric'), 'Brownian dynamics hides its friction');
  check(!visible(block({}), 'bd_fric'), 'plain dynamics shows the Brownian friction');
  check(visible(block({}), 'ref_p'), 'pressure control on, but its pressure box is hidden');
  check(!visible(block({ pcoupl: 'no' }), 'ref_p'), 'pressure control off, but its boxes still show');
  check(!visible(block({ preset: 'nvt_atomistic' }), 'compressibility'),
        'a preset without pressure control shows the barostat boxes');
  check(visible(block({ preset: 'nvt_atomistic', pcoupl: 'C-rescale' }), 'compressibility'),
        'pressure control typed in the box does not show its boxes');
  check(!visible(block({ tcoupl: 'no' }), 'tau_t'), 'no thermostat, but its boxes still show');
  check(!visible(block({}), 'rlist'), 'rlist shows while GROMACS sets it itself');
  check(visible(block({ verlet_buffer_tolerance: '-1' }), 'rlist'),
        'rlist is hidden when it is the one that decides');
  check(visible(block({ coulombtype: 'Reaction-Field' }), 'epsilon_rf'),
        'reaction field typed in the box hides the reaction field\'s own setting');
  check(!visible(block({}), 'epsilon_rf'), 'PME shows the reaction field\'s setting');
  check(visible(block({}), 'fourierspacing')
        && !visible(block({ coulombtype: 'Reaction-Field' }), 'fourierspacing'),
        'the PME grid spacing shows without PME, or hides with it');
  check(!visible(block({}), 'gen_temp'), 'a run that continues shows the velocity temperature');
  check(visible(block({ preset: 'nvt_atomistic' }), 'gen_temp'),
        'new velocities, but their temperature is hidden');
  check(!visible(block({}), 'annealing_temp'), 'no schedule, but the schedule\'s boxes show');
  check(visible(block({ annealing: 'single single' }), 'annealing_temp'),
        'a schedule typed in the box does not show its temperatures');
  check(!visible(block({ vdw_modifier: 'Potential-shift' }), 'rvdw_switch')
        && visible(block({ vdw_modifier: 'Force-switch' }), 'rvdw_switch'),
        'the switch distance does not follow the van der Waals modifier');

  // Only the preset and the text are hidden: file mode uses neither.
  const unread = block({ mode: 'file', path: '/nowhere/not-read-yet.mdp' });
  same(params.filter((p) => !visible(unread, p.name)).map((p) => p.name), ['preset', 'raw'],
       'a file not read yet hides boxes on the strength of values nobody knows');
  const minFile = [
    'INTEGRATOR   = steep',
    'emtol        = 50   ; tighter',
    'nsteps       = 2000',
    'vdw_type     = cut-off',
    '',
  ].join('\n');
  MdpFiles.entries.set('/data/min.mdp',
    { state: 'read', text: minFile, options: mdpRawOptions(minFile) });
  const readFile = block({ mode: 'file', path: '/data/min.mdp' });
  check(!visible(readFile, 'dt'), 'a minimisation file still shows the time step');
  same(Editor._placeholder(readFile, param('emtol')), '50  (from the file)',
       'a box does not show the file\'s value');

  console.log('the summary card says what the settings add up to');
  const card = (values) => mdpSummary(block(values));
  const clean = Object.keys(table.mdp.presets).filter((name) => card({ preset: name }).warnings.length);
  same(clean, [], 'presets of our own draw warnings');
  same(card({ preset: 'md_atomistic' }), {
    title: 'run.mdp', source: 'preset md_atomistic',
    lines: ['Dynamics: 50,000,000 steps of 2 fs = 100 ns',
            '310 K (V-rescale, 2 heat groups)',
            '1 bar, isotropic (Parrinello-Rahman)',
            'Continues from the run before it',
            'A frame every 10 ps',
            'PME electrostatics, cut-offs 1.2 nm'],
    warnings: [] }, 'the card of md_atomistic');
  same(mdpSummary(block({ mode: 'raw', raw: 'integrator = md\ntcoupl = v-rescale\n'
                         + 'tc-grps = System\nref-t = 300.0\ntau-t = 0.1\n' })).lines[1],
       '300 K (V-rescale)', 'a text writing v-rescale is not shown in the list\'s spelling');
  same(mdpSummary(rawBlock).lines, [
    'Energy minimisation (steepest descent): up to 5,000 steps, until no force is above 100 kJ/mol/nm',
    'PME electrostatics, cut-offs 1 nm'], 'the card of a raw minimisation');
  same(mdpSummary(rawBlock).source, 'your own text', 'the card does not say the text is your own');
  same(mdpSummary(block({ mode: 'raw', raw: '  ' })).warnings,
       ['The text is empty: paste an .mdp file into the box below.'],
       'an empty text is not pointed out');
  same(card({ preset: 'nvt_atomistic', annealing: 'single single', annealing_npoints: '3 3',
              annealing_time: '0 100 200 0 100 200',
              annealing_temp: '200 400 1000 200 400 1000' }).lines[1],
       'Temperature follows a schedule: 200 → 400 → 1000 → 200 → 400 → 1000 K over 200 ps '
       + '(V-rescale, 2 heat groups)', 'a temperature schedule is not described');
  same(mdpSummary(readFile).lines[0],
       'Energy minimisation (steepest descent): up to 2,000 steps, until no force is above 50 kJ/mol/nm',
       'the card of a file does not describe the file');
  same(mdpSummary(unread).lines, ['Read from the file when the block runs.'],
       'the card claims to know a file it has not read');
  MdpFiles.entries.set('/data/gone.mdp', { state: 'missing', error: 'no such file' });
  same(mdpSummary(block({ mode: 'file', path: '/data/gone.mdp' })).warnings,
       ['Cannot read /data/gone.mdp: no such file.'], 'a file that cannot be read is not pointed out');
  const warns = (values, part, what) => check(card(values).warnings.some((w) => w.includes(part)),
    `${what}\n        warnings: ${JSON.stringify(card(values).warnings)}`);
  warns({ gen_vel: 'yes' }, 'continuation = yes', 'new velocities in a run that continues');
  warns({ ref_t: '300' }, 'ref-t needs one value per heat group', 'one temperature for two groups');
  warns({ pcoupltype: 'semiisotropic' }, 'semiisotropic pressure needs 2 values',
        'one pressure for semi-isotropic coupling');
  warns({ pcoupl: 'MTTK' }, 'MTTK pressure control needs the md-vv integrator', 'MTTK with md');
  warns({ tcoupl: 'Andersen' }, 'Andersen thermostat needs the md-vv', 'Andersen with md');
  warns({ preset: 'nvt_atomistic', gen_temp: '300' }, 'set gen-temp to match',
        'velocities drawn at another temperature than the thermostat holds');
  warns({ verlet_buffer_tolerance: '-1', rlist: '1.0' }, 'rlist is smaller than the cut-offs',
        'a pair list shorter than the cut-offs');
  warns({ preset: 'npt_atomistic', refcoord_scaling: 'no' }, 'set refcoord-scaling to com',
        'restraints with pressure control and fixed restraint points');

  console.log('option names written any way are one option, and values in the list\'s spelling');
  const odd = block({ mode: 'raw', raw: 'Integrator = SD\nLD-SEED = 5\nref_t = 300\ntc-grps = System\n' });
  check(visible(odd, 'ld_seed') && !visible(odd, 'tcoupl'), 'Integrator = SD was not read as sd');
  same(Editor._placeholder(odd, param('ld_seed')), '5  (from the raw text)', 'LD-SEED was not read');
  same(mdpSetRaw(odd.params.raw, 'ld-seed', '7').split('\n')[1], 'LD-SEED = 7',
       'a line written in capitals was not changed in place');
  // No preset here writes its values in lower case; one made up for the test does.
  Editor.mdp.presets.lower_case = { integrator: 'md', tcoupl: 'v-rescale',
                                    pcoupl: 'parrinello-rahman' };
  same(mdpFill(block({ preset: 'lower_case' })).tcoupl, 'V-rescale',
       'filling the boxes from a preset writing v-rescale did not pick the list\'s V-rescale');
  same(mdpFill(block({ preset: 'lower_case' })).pcoupl, 'Parrinello-Rahman',
       'filling the boxes from a preset writing parrinello-rahman did not pick the list\'s entry');
  delete Editor.mdp.presets.lower_case;
  made.length = 0;
  Editor._buildWidget(block({ tcoupl: 'v-rescale' }), param('tcoupl'));
  const select = made.find((el) => el.tagName === 'SELECT');
  same(select.value, 'V-rescale', 'a dropdown holding v-rescale does not pick V-rescale');
  same(select.children.map((o) => o.value), param('tcoupl').choices,
       'a dropdown holding v-rescale added it as a second entry');
  made.length = 0;
  Editor._buildWidget(block({ coulombtype: 'User' }), param('coulombtype'));
  const other = made.find((el) => el.tagName === 'SELECT').children.find((o) => o.value === 'User');
  same(other && other.text, 'User', 'a GROMACS value the list lacks is not shown plainly');

  console.log('a drawer that was opened stays open');
  const kept = block({});
  let drawer = Editor._drawer(kept, 'section:Temperature', 'section', 'Temperature (6)', '');
  check(!drawer.open, 'a drawer nobody opened is open');
  drawer.open = true;
  drawer.handlers.toggle();
  drawer = Editor._drawer(kept, 'section:Temperature', 'section', 'Temperature (6)', '');
  check(drawer.open === true, 'an opened drawer is closed again when the block is redrawn');
  drawer.open = false;
  drawer.handlers.toggle();
  drawer = Editor._drawer(kept, 'section:Temperature', 'section', 'Temperature (6)', '');
  check(!drawer.open, 'a closed drawer opens again when the block is redrawn');
  made.length = 0;
  const advanced = params.filter((p) => Editor.paramShown(rawBlock, p))
    .map((p) => ({ param: p, ...Editor._placement(rawBlock, p) }))
    .filter((x) => x.advanced);
  const outer = Editor._buildAdvanced(rawBlock, advanced);
  const heads = outer.children.filter((el) => el.tagName === 'DETAILS')
    .map((el) => el.children[0].text);
  // A minimisation: no temperature, pressure, velocities or drift drawers.
  same(heads, ['Main settings (6)', 'Output (8)', 'Cut-offs and pair lists (2)',
               'Electrostatics (7)', 'Van der Waals (4)', 'Bonds and constraints (6)',
               'Frozen atoms (2)', 'File and extra lines (1)'],
       'the drawers of a raw minimisation, main settings first');

  if (failures) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
  }
  console.log('\nrun-parameter boxes: every value on show from the start, only the boxes '
    + 'the run uses, a true summary, and raw mode edits the text');
}

main().catch((err) => { console.log(`  FAIL  the test itself broke: ${err.stack}`); process.exit(1); });
