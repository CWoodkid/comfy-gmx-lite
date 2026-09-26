/* Fill-in-the-blanks forms: the boxes that want a small language, asked as
   questions instead.

   Several boxes in this program do not want a value, they want a sentence in
   somebody else's language. "r 1-40 & a CA" is exact and it is also
   unguessable, and a character in the wrong place is found by the program
   that reads it -- after it has started, sometimes minutes in.

   So a box can name a form. The form asks the same thing with dropdowns and
   numbers, shows the exact text it is about to write while you change it, and
   writes that text into the box. Three rules it follows everywhere:

     * The box stays editable. Somebody who knows the language types faster
       than they click, and a line the form cannot make must still be possible.
     * Opening a form on text that is already there reads it back in. Anything
       the form does not recognise is kept, word for word, in a box marked as
       such, so a form can never quietly throw a setting away.
     * The exact text is on screen the whole time. Nobody has to trust it.

   There is also a form for a whole node -- Forms.setup -- which asks about
   every one of its boxes in turn with the explanations visible, and shows the
   command that will run at the bottom. Every node has one; it is built from
   what the node says about itself, so a new node gets one for free. */
'use strict';

const Forms = {

  // ------------------------------------------------------------------
  // The registry
  // ------------------------------------------------------------------

  fields: new Map(),

  registerField(name, def) { this.fields.set(name, def); },

  hasField(name) { return !!name && this.fields.has(name); },

  /* Open the form for one box. The form gets the text that is in the box now
     and hands back the text to put there; a form may also fill in other boxes
     on the same node. */
  async openField(node, param, opts = {}) {
    const def = this.fields.get(param.form);
    if (!def) { UI.toast(`no form for ${param.form}`, 'warn'); return; }
    const reopen = () => this.openField(node, param, opts);
    const ctx = {
      node, param, reopen,
      value: node.params[param.name] === undefined || node.params[param.name] === null
        ? '' : String(node.params[param.name]),
    };
    // A form may have to ask the server something before it can draw
    // itself. Awaiting a plain object is harmless, so the sync ones are
    // unaffected.
    const made = await def.build(ctx);
    // Opened from the step-by-step panel, both buttons go back to it rather
    // than closing everything: filling in one box is rarely the whole job.
    const back = () => { if (!opts.after) return true; opts.after(); return false; };
    UI.modal(def.title || param.label, made.body, [
      { label: 'Leave it as it was', action: back },
      {
        label: 'Put this in the box',
        primary: true,
        action: () => {
          const result = made.read();
          const text = typeof result === 'string' ? result : result.text;
          const extra = typeof result === 'string' ? {} : (result.params || {});
          Forms.apply(node, Object.assign({ [param.name]: text }, extra));
          return back();
        },
      },
    ], { reopen: () => Forms.openField(node, param, opts) });
  },

  /* Write values into a node the way the editor does it itself: one undo step,
     the node redrawn, the graph marked as changed. */
  apply(node, values) {
    const names = Object.keys(values);
    if (!names.length) return;
    // The graph can have been rebuilt while the form was open -- an undo
    // replaces every node object, keeping the ids -- and it can have lost the
    // node altogether. Writing into the object the form captured would then
    // land nowhere, redraw nothing, and still say "filled in".
    const live = Editor.nodes.get(node.id);
    if (!live) {
      UI.toast('that node is not on the canvas any more, so there was nowhere '
        + 'to put this. Nothing was changed.', 'error', 9000);
      return;
    }
    node = live;
    for (const [name, value] of Object.entries(values)) node.params[name] = value;
    Editor.mark(`${names.length === 1 ? names[0] : 'settings'} on ${node.title}`,
                `form:${node.id}:${names.join(',')}`);
    Editor._refreshNodeElement(node);
    Editor.changed();
    UI.toast(names.length === 1 ? `${names[0]} filled in` : 'settings filled in', 'ok');
  },

  // ------------------------------------------------------------------
  // Small controls the forms are made of
  // ------------------------------------------------------------------

  ui: {
    /* One labelled thing, with an explanation under it. */
    field(label, control, hint) {
      const kids = [UI.el('label', { text: label }), control];
      if (hint) kids.push(UI.el('div', { class: 'hint', text: hint }));
      return UI.el('div', { class: 'field' }, kids);
    },

    /* A dropdown. Options are strings, or {value, label, title}. */
    select(options, value, onChange) {
      const el = UI.el('select');
      for (const option of options) {
        const opt = typeof option === 'string' ? { value: option, label: option } : option;
        el.appendChild(UI.el('option', {
          value: opt.value, text: opt.label === undefined ? opt.value : opt.label,
          title: opt.title || null,
        }));
      }
      el.value = value === null || value === undefined ? '' : String(value);
      // A value nothing in the list matches would silently show the first
      // entry, which is how a form quietly changes a setting it was only
      // supposed to display.
      if (el.value !== String(value === null || value === undefined ? '' : value)) {
        el.appendChild(UI.el('option', { value: String(value), text: `${value} (as typed)` }));
        el.value = String(value);
      }
      el.addEventListener('change', () => onChange(el.value));
      return el;
    },

    number(value, opts, onChange) {
      const el = UI.el('input', {
        type: 'number', step: opts.step === undefined ? 'any' : String(opts.step),
        placeholder: opts.placeholder || '',
      });
      if (opts.min !== undefined) el.min = String(opts.min);
      if (opts.max !== undefined) el.max = String(opts.max);
      el.value = value === null || value === undefined ? '' : String(value);
      el.addEventListener('input', () => onChange(el.value));
      return el;
    },

    input(value, onChange, opts = {}) {
      const el = UI.el('input', { type: 'text', placeholder: opts.placeholder || '' });
      if (opts.list) el.setAttribute('list', opts.list);
      if (opts.class) el.className = opts.class;
      el.value = value === null || value === undefined ? '' : String(value);
      el.addEventListener('input', () => onChange(el.value));
      return el;
    },

    check(label, checked, onChange) {
      const box = UI.el('input', { type: 'checkbox' });
      box.checked = !!checked;
      box.addEventListener('change', () => onChange(box.checked));
      const row = UI.el('label', { class: 'form-check' }, [box, UI.el('span', { text: label })]);
      return row;
    },

    button(label, onClick, opts = {}) {
      return UI.el('button', {
        class: `small${opts.primary ? ' primary' : ''}${opts.link ? ' link' : ''}`,
        text: label, title: opts.title || null, onclick: onClick,
      });
    },

    /* A file box with a Browse button beside it, that a file can also be
       dropped on.

       Without the drop handling the file is caught by the window instead --
       the whole page accepts dropped files and turns them into a Load node --
       so dropping one on a box in a dialog left the box empty and quietly put
       a node on the canvas behind it. Stopping the event here is what keeps it
       from reaching the window. */
    file(value, onChange, placeholder) {
      const box = UI.el('input', { type: 'text', class: 'file-box',
                                   placeholder: placeholder || '' });
      box.value = value || '';
      box.addEventListener('input', () => onChange(box.value));
      const browse = UI.el('button', {
        class: 'small', text: '…', title: 'browse',
        onclick: () => Panels.browseFile((path) => { box.value = path; onChange(path); }),
      });
      const fromOutside = (event) =>
        App.dragSource !== 'page' || App.dragCarriesFiles(event);
      box.addEventListener('dragover', (event) => {
        if (!fromOutside(event)) return;
        event.preventDefault();
        event.stopPropagation();
        box.classList.add('drop-target');
      });
      box.addEventListener('dragleave', () => box.classList.remove('drop-target'));
      box.addEventListener('drop', async (event) => {
        if (!fromOutside(event)) return;
        event.preventDefault();
        event.stopPropagation();
        box.classList.remove('drop-target');
        const path = await App.onePathFromDrop(event.dataTransfer);
        if (!path) return;
        box.value = path;
        onChange(path);
      });
      return UI.el('div', { class: 'row' }, [box, browse]);
    },

    /* A bordered block with a title and, if it can be removed, a × on it. */
    card(title, onRemove) {
      const head = UI.el('div', { class: 'form-card-head' }, [
        UI.el('strong', { text: title }),
      ]);
      if (onRemove) {
        head.appendChild(UI.el('span', { class: 'spacer' }));
        head.appendChild(UI.el('button', {
          class: 'small', text: '×', title: 'remove this one', onclick: onRemove,
        }));
      }
      const body = UI.el('div', { class: 'form-card-body' });
      return { el: UI.el('div', { class: 'form-card' }, [head, body]), body };
    },

    /* The exact text the form is about to write, kept up to date. */
    preview(label) {
      const pre = UI.el('pre', { class: 'form-preview' });
      const el = UI.el('div', { class: 'field' }, [
        UI.el('label', { text: label || 'What goes in the box' }), pre,
      ]);
      return { el, set: (text) => { pre.textContent = text || '(nothing)'; } };
    },

    hint(text, warned) {
      return UI.el('div', { class: `hint${warned ? ' warned' : ''}`, text });
    },
  },
};


/* ====================================================================
   Answers to a tool's questions: which group
   ==================================================================== */

const STANDARD_GROUPS = [
  ['System', 'everything in the file'],
  ['Protein', 'every protein chain, all of them together'],
  ['Backbone', 'the protein backbone only: N, C-alpha and C of every residue'],
  ['C-alpha', 'one atom per residue. All-atom files only'],
  ['MainChain', 'backbone plus the carbonyl oxygens'],
  ['SideChain', 'everything hanging off the backbone'],
  ['non-Protein', 'everything that is not protein: water, ions'],
  ['Water', 'water only'],
  ['SOL', 'water, by its residue name'],
  ['non-Water', 'everything except water. Usually what you want to keep'],
  ['Ion', 'the ions'],
  ['Other', 'everything that is neither protein nor water nor ions'],
];

Forms.registerField('gmx.groups', {
  title: 'What to answer the tool',
  build(ctx) {
    const F = Forms.ui;
    const lines = ctx.value.split('\n').map((l) => l.trim()).filter(Boolean);
    const rows = lines.length ? lines.slice() : [''];
    const listId = `groups-${Math.random().toString(36).slice(2)}`;
    const list = UI.el('datalist', { id: listId });
    for (const [name] of STANDARD_GROUPS) list.appendChild(UI.el('option', { value: name }));

    const body = UI.el('div', { class: 'form-body' });
    body.appendChild(list);
    body.appendChild(F.hint('These tools ask their questions on the keyboard and '
      + 'this box holds the answers, one per line, in the order they are asked. '
      + 'The node\'s own explanation says what each line is for:'));
    body.appendChild(UI.el('div', { class: 'form-quote', text: ctx.param.help || '' }));

    const cards = UI.el('div');
    const preview = F.preview('The exact text this writes');
    const redraw = () => preview.set(rows.filter((r) => r.trim()).join('\n') + '\n');

    const paint = () => {
      cards.innerHTML = '';
      rows.forEach((value, index) => {
        const box = F.input(value, (text) => { rows[index] = text; redraw(); },
          { list: listId, placeholder: 'a group name, or its number' });
        const known = STANDARD_GROUPS.find(([name]) => name === value.trim());
        const line = UI.el('div', { class: 'row' }, [
          UI.el('span', { class: 'form-index', text: `answer ${index + 1}` }),
          box,
          UI.el('button', { class: 'small', text: '×', title: 'remove this answer',
            onclick: () => { rows.splice(index, 1); paint(); } }),
        ]);
        const block = UI.el('div', {}, [line]);
        if (known) block.appendChild(F.hint(known[1]));
        cards.appendChild(block);
      });
      redraw();
    };
    body.appendChild(cards);
    body.appendChild(UI.el('div', { class: 'row form-actions' }, [
      F.button('Add another answer', () => { rows.push(''); paint(); }),
    ]));
    body.appendChild(F.hint('A number works too, and so does the name of a group '
      + 'an index node made. What the numbers are depends on the file, so a name '
      + 'is safer.'));
    body.appendChild(preview.el);
    paint();
    // An empty box means "the tool is not asked anything", so it stays empty
    // rather than becoming a blank line.
    return { body, read: () => {
      const kept = rows.filter((r) => r.trim());
      return kept.length ? `${kept.join('\n')}\n` : '';
    } };
  },
});


/* ====================================================================
   Which groups to show: every group this system has, to tick
   ==================================================================== */

/* What the other groups GROMACS makes by itself are. The common ones are in
   STANDARD_GROUPS above; these turn up in the list of a real system too. */
const MORE_GROUPS = [
  ['Protein-H', 'the protein without its hydrogen atoms'],
  ['MainChain+Cb', 'the backbone and carbonyl oxygens, plus the first carbon '
    + 'of every side chain'],
  ['MainChain+H', 'the backbone and carbonyl oxygens, with their hydrogens'],
  ['SideChain-H', 'the side chains without their hydrogens'],
  ['Prot-Masses', 'the protein atoms that have a mass'],
  ['Water_and_ions', 'the water and the ions together'],
  ['NA', 'the sodium ions'],
  ['CL', 'the chloride ions'],
  ['Oxygens', 'the oxygen of every water molecule: one point per molecule. '
    + 'The Ice crystal block makes this group'],
];

Forms.registerField('gmx.pick_groups', {
  title: 'What to show',
  async build(ctx) {
    const F = Forms.ui;
    // In the order they were typed, so reading the box back changes nothing.
    const chosen = ctx.value.split(',').map((name) => name.trim()).filter(Boolean);

    // This system's own list exists once the run file feeding the block
    // does. Until then, the usual names, and the reason there is no more.
    let listed = null;
    let why = '';
    try {
      listed = (await API.graphGroups(Editor.toJSON(), ctx.node.id)).groups || [];
    } catch (err) {
      why = err && err.message ? err.message : String(err);
    }
    const meaning = new Map(STANDARD_GROUPS.concat(MORE_GROUPS));
    const groups = listed
      ? listed.map((group) => ({ name: group.name, atoms: group.atoms }))
      : STANDARD_GROUPS.map(([name]) => ({ name, atoms: null }));
    // A name already in the box that the list does not have stays, ticked:
    // a form never quietly throws a setting away.
    for (const name of chosen) {
      if (!groups.some((group) => group.name === name)) {
        groups.push({ name, atoms: null, unlisted: true });
      }
    }

    const body = UI.el('div', { class: 'form-body' });
    const preview = F.preview('The exact text this writes');
    const redraw = () => preview.set(chosen.join(', '));
    body.appendChild(F.hint(listed
      ? 'Every group this system has, with how many atoms are in each. Tick one '
        + 'to show just that part, or several to show them together.'
      : 'This system\'s own list is read from the run file that feeds this '
        + 'block, and that file is not there yet. These are the usual groups; '
        + 'run the blocks before this one, then open this again to see exactly '
        + 'which groups this system has.', !listed));
    if (why) body.appendChild(UI.el('div', { class: 'form-quote', text: why }));
    for (const group of groups) {
      const size = group.atoms === null || group.atoms === undefined
        ? '' : ` (${group.atoms} atoms)`;
      const label = `${group.name}${size}${group.unlisted ? ' (not in this list)' : ''}`;
      const row = UI.el('div', { class: 'group-pick' }, [
        F.check(label, chosen.includes(group.name), (checked) => {
          const at = chosen.indexOf(group.name);
          if (checked && at < 0) chosen.push(group.name);
          if (!checked && at >= 0) chosen.splice(at, 1);
          redraw();
        }),
      ]);
      if (meaning.has(group.name)) row.appendChild(F.hint(meaning.get(group.name)));
      body.appendChild(row);
    }
    body.appendChild(F.hint('Several ticked are shown as one: the block joins them '
      + 'into a single group before it takes the frames.'));
    body.appendChild(preview.el);
    redraw();
    return { body, read: () => chosen.join(', ') };
  },
});


/* ====================================================================
   Lists of files
   ==================================================================== */

Forms.registerField('files.list', {
  title: 'Which files',
  build(ctx) {
    const F = Forms.ui;
    const rows = ctx.value.split('\n').map((l) => l.trim()).filter(Boolean);
    if (!rows.length) rows.push('');
    const body = UI.el('div', { class: 'form-body' });
    body.appendChild(F.hint(ctx.param.help || 'One file per line.'));
    const cards = UI.el('div');
    const preview = F.preview('The exact text this writes');
    const redraw = () => preview.set(rows.filter((r) => r.trim()).join('\n'));
    const paint = () => {
      cards.innerHTML = '';
      rows.forEach((value, index) => {
        const box = F.file(value, (path) => { rows[index] = path; redraw(); },
          ctx.param.placeholder || 'a file');
        box.appendChild(UI.el('button', {
          class: 'small', text: '×', title: 'remove this one',
          onclick: () => { rows.splice(index, 1); paint(); },
        }));
        cards.appendChild(box);
      });
      redraw();
    };
    body.appendChild(cards);
    body.appendChild(UI.el('div', { class: 'row form-actions' }, [
      F.button('Add another file', () => { rows.push(''); paint(); }),
    ]));
    body.appendChild(preview.el);
    paint();
    return { body, read: () => rows.filter((r) => r.trim()).join('\n') };
  },
});


/* ====================================================================
   make_ndx: making a group of your own
   ==================================================================== */

const NDX_KINDS = [
  { value: 'a', label: 'atoms with these names', hint:
    'Wildcards work: H* takes every atom whose name starts with H, which in a '
    + 'protein is the hydrogens.', example: 'a H*' },
  { value: 'r', label: 'these residues', hint:
    'By name or by number: r SOL, or r 1-50.', example: 'r SOL' },
  { value: 'name', label: 'give a group a name', hint:
    'The number comes from the list the tool prints. New groups are added at '
    + 'the end, so the first one you make is one past the last of the standard '
    + 'ones.', example: 'name 20 PHOSPHATES' },
  { value: 'combine', label: 'join two groups together', hint:
    'Quotes around the names: "Protein" | "PHOSPHATES". Use & instead of | for '
    + 'the atoms in both.', example: '"Protein" | "PHOSPHATES"' },
  { value: 'del', label: 'delete a group', hint: 'By number.', example: 'del 19' },
  { value: 'raw', label: 'something else — type it myself', hint:
    'Anything make_ndx understands.', example: '' },
];

Forms.registerField('gmx.ndx', {
  title: 'Groups to make',
  build(ctx) {
    const F = Forms.ui;
    const rows = ctx.value.split('\n').map((l) => l.trim())
      .filter((l) => l && l.toLowerCase() !== 'q');
    if (!rows.length) rows.push('');
    const body = UI.el('div', { class: 'form-body' });
    body.appendChild(F.hint(
      'An index file is a list of named groups of atoms, so that later commands '
      + 'can say "the phosphates" instead of a list of numbers. Each line here is '
      + 'one instruction; the q that ends the session is added for you.'));
    body.appendChild(UI.el('div', { class: 'form-quote', text:
      'The usual pattern is three lines: make the group, give it a name, then '
      + 'combine it with another one.' }));

    const cards = UI.el('div');
    const preview = F.preview('The exact text this writes');
    const redraw = () => preview.set(rows.filter((r) => r.trim()).join('\n') + '\nq');
    const paint = () => {
      cards.innerHTML = '';
      rows.forEach((value, index) => {
        const kind = NDX_KINDS.find((k) => value.trim().startsWith(`${k.value} `))
          || (value.trim().startsWith('"') ? NDX_KINDS[3] : NDX_KINDS[5]);
        const box = F.input(value, (text) => { rows[index] = text; redraw(); },
          { placeholder: 'a P*' });
        const kindBox = F.select(NDX_KINDS.map((k) => ({ value: k.value, label: k.label })),
          kind.value, (chosen) => {
            const picked = NDX_KINDS.find((k) => k.value === chosen);
            if (picked && picked.example) { rows[index] = picked.example; }
            paint();
          });
        cards.appendChild(UI.el('div', {}, [
          UI.el('div', { class: 'row' }, [
            kindBox, box,
            UI.el('button', { class: 'small', text: '×', title: 'remove this line',
              onclick: () => { rows.splice(index, 1); paint(); } }),
          ]),
          F.hint(kind.hint),
        ]));
      });
      redraw();
    };
    body.appendChild(cards);
    body.appendChild(UI.el('div', { class: 'row form-actions' }, [
      F.button('Add another line', () => { rows.push(''); paint(); }),
    ]));
    body.appendChild(preview.el);
    paint();
    return { body, read: () => rows.filter((r) => r.trim()).join('\n') + '\nq\n' };
  },
});


/* ====================================================================
   The step-by-step panel for a whole node
   ==================================================================== */

/* Every node has one of these, and none of them is written by hand: it is
   built from what the node says about itself -- its boxes, their explanations,
   what it takes in and what it produces. A node body has to be small enough to
   sit on a canvas next to twenty others, so its explanations hide in tooltips
   and its less common settings hide behind a triangle. Here there is room, so
   nothing hides: every box has its explanation under it, and the command that
   will actually run is at the bottom, changing as you change the boxes. */
Forms.setup = function setup(node) {
  const F = Forms.ui;
  const def = Editor.defs[node.type];
  if (!def) { UI.toast('this node has no description to show', 'warn'); return; }
  const body = UI.el('div', { class: 'form-body node-setup' });

  if (def.description) {
    for (const part of UI.prose(def.description, 'form-lead')) body.appendChild(part);
  }

  // ---- what has to be plugged in ----------------------------------------
  if ((def.inputs || []).length) {
    const table = UI.el('table', { class: 'info-table' });
    table.appendChild(UI.el('tr', {}, [
      UI.el('th', { text: 'this node needs' }), UI.el('th', { text: 'comes from' }),
    ]));
    for (const port of def.inputs) {
      const link = Editor.links.find((l) => l.to_node === node.id && l.to_port === port.name);
      const from = link && Editor.nodes.get(link.from_node);
      table.appendChild(UI.el('tr', {}, [
        UI.el('td', { text: `${port.label || port.name}${port.optional ? ' (optional)' : ''}` }),
        UI.el('td', {
          class: from ? '' : 'warned',
          text: from ? `${from.title} → ${link.from_port}`
            : (port.optional ? 'nothing — that is allowed' : 'nothing connected yet'),
        }),
      ]));
    }
    body.appendChild(table);
  }

  // ---- every box, with its explanation under it -------------------------
  const paramBlock = (param) => {
    const block = UI.el('div', { class: 'setup-param' });
    const widget = Editor._buildWidget(node, param);
    // The widget brings its own way into the form, meant for the small copy of
    // it on the canvas. In here it would be a second identical button that
    // closes the whole panel when it is done, so it goes and the panel's own
    // -- which comes back here afterwards -- stays.
    const theirs = widget.querySelector('button.form-open');
    if (theirs) theirs.remove();
    block.appendChild(widget);
    if (param.help) block.appendChild(F.hint(param.help));
    if (Forms.hasField(param.form)) {
      block.appendChild(UI.el('div', { class: 'row form-actions' }, [
        F.button('Fill this in with a form…', () => {
          Forms.openField(node, param, { after: () => Forms.setup(node) });
        }, { primary: true }),
      ]));
    }
    return block;
  };

  const basic = (def.params || []).filter((p) => !p.advanced);
  const advanced = (def.params || []).filter((p) => p.advanced);
  for (const param of basic) body.appendChild(paramBlock(param));
  if (advanced.length) {
    const more = UI.el('details', { class: 'form-more' },
      [UI.el('summary', { text: `Less usual settings (${advanced.length})` })]);
    for (const param of advanced) more.appendChild(paramBlock(param));
    body.appendChild(more);
  }

  // ---- and what all of that adds up to ----------------------------------
  const command = UI.el('pre', { class: 'form-preview', text: 'working it out…' });
  body.appendChild(UI.el('div', { class: 'field' }, [
    UI.el('label', { text: 'The command this will run' }), command,
  ]));
  body.appendChild(F.hint('Exactly what runs, built from the boxes above. If it '
    + 'says something is missing, that is what to fix before pressing Run.'));

  let timer = null;
  const refresh = async () => {
    try {
      const preview = await API.preview(Editor.toJSON(), node.id);
      command.textContent = preview.error
        ? `not ready yet:\n\n${preview.error}`
        : [...(preview.notes || []).map((n) => `# ${n}`), preview.manual].join('\n');
    } catch (err) {
      command.textContent = err.message;
    }
  };
  // The boxes commit on change, so listening for it here catches every edit
  // without each widget having to know this panel exists.
  body.addEventListener('change', () => {
    clearTimeout(timer);
    timer = setTimeout(refresh, 250);
  });
  refresh();

  UI.modal(`${node.title} — step by step`, body, [
    { label: 'Close' },
    { label: 'Run just this node', action: () => { App.run([node.id], [node.id], { isolate: true }); } },
    { label: 'Run up to here', primary: true, action: () => { App.run([node.id]); } },
  ], { reopen: () => Forms.setup(node) });
};


const ENERGY_TERMS = [
  ['Potential', 'the energy of the arrangement itself. Should settle and then '
    + 'wander about a steady value'],
  ['Kinetic En.', 'the energy of the motion. Follows the temperature'],
  ['Total Energy', 'the two above added together'],
  ['Temperature', 'the first thing to look at: it should sit at what you asked for'],
  ['Pressure', 'very noisy in a small box. Judge it over hundreds of frames, '
    + 'not frame by frame'],
  ['Volume', 'the size of the box. It shrinks over the first part of a run '
    + 'under pressure coupling and then settles'],
  ['Density', 'mass over volume. A settled density is the usual sign that '
    + 'equilibration is done'],
  ['Box-X', 'the box across'],
  ['Box-Y', 'the box along'],
  ['Box-Z', 'the box up'],
  ['LJ (SR)', 'how strongly things stick to and push off each other nearby'],
  ['Coulomb (SR)', 'the charges pushing and pulling nearby'],
  ['Bond', 'the springs holding pairs of beads together'],
  ['Angle', 'the springs holding three beads at an angle'],
  ['Constr. rmsd', 'how badly the constraints are being kept. Should be tiny; '
    + 'a growing one means the run is going wrong'],
  ['Pres. DC (bar)', 'the correction for what was cut off at the edge'],
];

Forms.registerField('gmx.terms', {
  title: 'Which numbers to pull out',
  build(ctx) {
    const F = Forms.ui;
    const chosen = ctx.value.split('\n').map((l) => l.trim()).filter(Boolean);
    const extra = chosen.filter((name) => !ENERGY_TERMS.some(([term]) => term === name));
    const state = new Set(chosen);
    const body = UI.el('div', { class: 'form-body' });
    const preview = F.preview('The exact text this writes');
    const list = () => ENERGY_TERMS.map(([term]) => term).filter((term) => state.has(term))
      .concat(extra.filter((term) => state.has(term)));
    const redraw = () => preview.set(list().join('\n') + '\n');

    body.appendChild(F.hint('Tick what you want written out. The names have to be '
      + 'ones this run actually recorded -- what is there depends on the settings '
      + 'it ran with, so a name that was not recorded is simply skipped.'));
    for (const [term, why] of ENERGY_TERMS) {
      const row = UI.el('div', {}, [
        F.check(term, state.has(term), (checked) => {
          if (checked) state.add(term); else state.delete(term);
          redraw();
        }),
        F.hint(why),
      ]);
      body.appendChild(row);
    }
    body.appendChild(F.field('Anything else, one per line',
      (() => {
        const area = UI.el('textarea', { rows: '2',
          placeholder: 'Surf*SurfTen\n#Surf*SurfTen' });
        area.value = extra.join('\n');
        area.addEventListener('input', () => {
          for (const name of extra) state.delete(name);
          extra.length = 0;
          for (const name of area.value.split('\n').map((l) => l.trim()).filter(Boolean)) {
            extra.push(name);
            state.add(name);
          }
          redraw();
        });
        return area;
      })(),
      'Exactly as gmx energy spells them. A number works too, but the numbers '
      + 'move between runs and the names do not.'));
    body.appendChild(preview.el);
    redraw();
    return { body, read: () => list().join('\n') + '\n' };
  },
});


/* ====================================================================
   gmx select: picking atoms by describing them
   ==================================================================== */

const SELECT_RECIPES = [
  ['name CA', 'the C-alpha atoms: one per amino acid, the usual way to follow '
    + 'the shape of a protein'],
  ['name OW', 'the oxygen of every water molecule: one point per water'],
  ['resname NA CL', 'every atom of the named residues: here, the ions'],
  ['resid 1 to 40', 'a stretch of residues by number'],
  ['resid 1 to 40 and name CA', 'the C-alphas of that stretch only'],
  ['name OW and within 0.5 of group "Protein"',
   'the water oxygens within 0.5 nm of the protein'],
  ['group "Protein" and z > 4', 'part of a group, cut at a height in nm'],
  ['resname SOL and same residue as within 0.35 of group "Protein"',
   'whole water molecules, any part of which touches the protein'],
];

Forms.registerField('gmx.select', {
  title: 'Which atoms to pick',
  build(ctx) {
    const F = Forms.ui;
    const state = { name: '', text: ctx.value || '' };
    const match = /^\s*"([^"]+)"\s*(.*)$/s.exec(state.text);
    if (match) { state.name = match[1]; state.text = match[2].trim(); }

    const body = UI.el('div', { class: 'form-body' });
    const preview = F.preview('The exact text this writes');
    const line = () => (state.name ? `"${state.name}" ${state.text}` : state.text);
    const redraw = () => preview.set(line());

    body.appendChild(F.hint('This tool picks atoms by describing them rather than '
      + 'by listing them, which is what you want for "everything within half a '
      + 'nanometre of the protein" -- a list like that would be different in '
      + 'every frame.'));
    body.appendChild(F.field('A name for the group it makes',
      F.input(state.name, (value) => { state.name = value; redraw(); },
        { placeholder: 'TM_backbone' }),
      'What later nodes will call it. Leave it blank and the description itself '
      + 'becomes the name, which is unreadable but works.'));

    const area = UI.el('textarea', { rows: '3', placeholder: 'name BB' });
    area.value = state.text;
    area.addEventListener('input', () => { state.text = area.value; redraw(); });
    body.appendChild(F.field('The description', area));

    body.appendChild(UI.el('h3', { text: 'ready-made ones' }));
    body.appendChild(F.hint('Press one to put it in the box, then change the names '
      + 'and numbers in it.'));
    for (const [text, why] of SELECT_RECIPES) {
      body.appendChild(UI.el('div', { class: 'row select-recipe' }, [
        UI.el('div', {}, [
          UI.el('div', { class: 'chooser-name', text }),
          F.hint(why),
        ]),
        F.button('use this', () => { state.text = text; area.value = text; redraw(); }),
      ]));
    }
    body.appendChild(UI.el('h3', { text: 'the words it understands' }));
    body.appendChild(UI.el('div', { class: 'form-quote', text:
      'name / resname / resid / atomnr    pick by what something is called or numbered\n'
      + 'and / or / not                    join two descriptions\n'
      + 'within N of ...                   within N nanometres of something else\n'
      + 'same residue as ...               widen a pick to whole molecules\n'
      + 'x / y / z                         a position in nm, as in z > 4\n'
      + 'group "NAME"                      a group from the index file on the input' }));
    body.appendChild(preview.el);
    redraw();
    return { body, read: line };
  },
});


/* ====================================================================
   Rules for "Edit a text file"
   ==================================================================== */

const TEXT_RULES = [
  { key: 'replace', label: 'replace', two: true,
    a: 'this text', b: 'with this', hint: 'every place it appears' },
  { key: 'delete lines containing', label: 'delete lines containing', a: 'text' },
  { key: 'delete lines starting with', label: 'delete lines starting with', a: 'text' },
  { key: 'uncomment lines starting with', label: 'uncomment lines starting with',
    a: 'text after the ; or #', hint: 'takes the ; or # off the front' },
  { key: 'comment out lines starting with', label: 'comment out lines starting with',
    a: 'text', hint: 'puts a ; in front' },
  { key: 'first line', label: 'set the first line to', a: 'text' },
  { key: 'append', label: 'add a line at the end', a: 'text' },
  { key: 'insert before line starting with', label: 'insert before the line starting with',
    a: 'text', hint: 'inserts the "Text to insert" box' },
  { key: 'insert after line starting with', label: 'insert after the line starting with',
    a: 'text', hint: 'inserts the "Text to insert" box' },
];

Forms.registerField('text.rules', {
  title: 'Rules',
  build(ctx) {
    const F = Forms.ui;
    const parse = (line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) return null;
      const colon = trimmed.indexOf(':');
      if (colon < 0) return { kind: 'replace', a: trimmed, b: '' };
      const head = trimmed.slice(0, colon).trim().toLowerCase().replace(/\s+/g, ' ');
      const rest = trimmed.slice(colon + 1).trim();
      const rule = TEXT_RULES.find((r) => r.key === head);
      if (!rule) return { kind: 'replace', a: trimmed, b: '' };
      if (rule.two) {
        const arrow = rest.indexOf('=>');
        if (arrow < 0) return { kind: rule.key, a: rest, b: '' };
        return { kind: rule.key, a: rest.slice(0, arrow).trim(), b: rest.slice(arrow + 2).trim() };
      }
      return { kind: rule.key, a: rest, b: '' };
    };
    const rows = (ctx.value || '').split('\n').map(parse).filter(Boolean);
    const body = UI.el('div', { class: 'form-body' });
    body.appendChild(F.hint('Each rule is one small change to the file, done in order. '
      + 'A rule that finds nothing to change stops the graph and says so, unless '
      + 'the file already looks the way the rule wants -- then it carries on.'));
    const cards = UI.el('div');
    const preview = F.preview('The rules, as the block reads them');
    const text = () => rows.filter((r) => r.a).map((r) => {
      const rule = TEXT_RULES.find((x) => x.key === r.kind) || TEXT_RULES[0];
      return rule.two ? `${r.kind}: ${r.a} => ${r.b}` : `${r.kind}: ${r.a}`;
    }).join('\n');
    const redraw = () => preview.set(text());
    const paint = () => {
      cards.innerHTML = '';
      rows.forEach((row, index) => {
        const rule = TEXT_RULES.find((x) => x.key === row.kind) || TEXT_RULES[0];
        const kids = [
          F.field('what to do', F.select(TEXT_RULES.map((r) => ({ value: r.key, label: r.label })),
            row.kind, (value) => { row.kind = value; paint(); }), rule.hint || ''),
          F.field(rule.a, F.input(row.a, (value) => { row.a = value; redraw(); })),
        ];
        if (rule.two) {
          kids.push(F.field(rule.b, F.input(row.b, (value) => { row.b = value; redraw(); })));
        }
        kids.push(UI.el('button', { class: 'small', text: '×', title: 'remove this rule',
          onclick: () => { rows.splice(index, 1); paint(); } }));
        cards.appendChild(UI.el('div', { class: 'row' }, kids));
      });
      redraw();
    };
    body.appendChild(cards);
    body.appendChild(UI.el('div', { class: 'row form-actions' }, [
      F.button('Add a rule', () => { rows.push({ kind: 'replace', a: '', b: '' }); paint(); }),
    ]));
    body.appendChild(preview.el);
    paint();
    return { body, read: text };
  },
});


Forms.registerField('text.globs', {
  title: 'Which files to take out',
  build(ctx) {
    const F = Forms.ui;
    const rows = (ctx.value || '').split('\n').map((l) => l.trim()).filter(Boolean);
    if (!rows.length) rows.push('');
    const body = UI.el('div', { class: 'form-body' });
    body.appendChild(F.hint('Patterns matched against the names inside the archive, '
      + 'one per line. * stands for any run of characters and ? for one, so '
      + '*/forcefield.itp finds that file whatever folder it is in.'));
    body.appendChild(UI.el('div', { class: 'form-quote', text:
      '*.pdb            every PDB file at the top\n'
      + '*/*.itp          every itp one folder down\n'
      + 'charmm*/*.itp    inside any folder whose name starts with charmm' }));
    const cards = UI.el('div');
    const preview = F.preview('The exact text this writes');
    const redraw = () => preview.set(rows.filter((r) => r.trim()).join('\n'));
    const paint = () => {
      cards.innerHTML = '';
      rows.forEach((value, index) => {
        cards.appendChild(UI.el('div', { class: 'row' }, [
          F.input(value, (v) => { rows[index] = v; redraw(); }, { placeholder: '*/*.pdb' }),
          UI.el('button', { class: 'small', text: '×', title: 'remove this pattern',
            onclick: () => { rows.splice(index, 1); paint(); } }),
        ]));
      });
      redraw();
    };
    body.appendChild(cards);
    body.appendChild(UI.el('div', { class: 'row form-actions' }, [
      F.button('Add a pattern', () => { rows.push(''); paint(); }),
      F.button('Take everything', () => { rows.length = 0; paint(); }),
    ]));
    body.appendChild(preview.el);
    paint();
    return { body, read: () => rows.filter((r) => r.trim()).join('\n') };
  },
});
