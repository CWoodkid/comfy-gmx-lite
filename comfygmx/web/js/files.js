/* The file browser: the Files tab, the folder and file pickers, and the small
   text editor they share.

   The Files tab used to list one thing -- the outputs of the current run,
   grouped by node -- which is the right first answer and no answer at all to
   "where did that end up", "what else is in there", or "I need an index file
   in that folder". So it has two modes now: the same grouped run listing, and
   a browser you can walk anywhere with, drag files out of onto the canvas, and
   drop files into.

   The pickers are the same listing in a modal. Choosing where a run goes was a
   text box you typed a path into, which meant knowing the path, and making a
   folder first meant leaving for a terminal. */
'use strict';

/* Files this can open in the editor. The cap is the server's: past it the text
   endpoint truncates, and saving a truncated file would throw the rest of it
   away. */
const EDITABLE_BYTES = 512 * 1024;

/* Shown with a pencil. Everything else is still editable if it is small
   enough -- this only decides what the button appears on by default. */
const TEXTISH = /\.(mdp|top|itp|ndx|dat|txt|csv|tsv|xvg|json|sh|py|log|out|err|str|inp|in|conf|cfg|yaml|yml|md|rtp|atp|itpx|fasta|seq)$/i;

function baseName(path) {
  return String(path || '').replace(/\/+$/, '').split('/').pop() || path;
}

/* One directory listing, rendered the same way wherever it appears.
   `options` says what the rows do: `onEnter(dir)`, `onFile(entry)`, plus
   `dirsOnly`, `draggable` and `actions(entry)` for the row buttons. */
function renderListing(host, data, options = {}) {
  host.innerHTML = '';
  // Anything to say above the rows goes in here rather than being appended by
  // the caller beforehand: this function starts by emptying the host, so a
  // note put there first was wiped before anyone saw it. That is why the
  // match count and the way back out of a search never appeared.
  if (options.note) host.appendChild(options.note);
  const up = UI.el('div', {
    class: 'fb-row dir up', onclick: () => options.onEnter(data.parent),
  }, [UI.el('span', { text: '↑ ..' }), UI.el('span', { class: 'fb-size', text: '' })]);
  if (data.parent && data.parent !== data.path) host.appendChild(up);

  let files = 0;
  for (const entry of data.entries) {
    if (!entry.dir) {
      files += 1;
      if (options.dirsOnly) continue;
    }
    const row = UI.el('div', {
      class: `fb-row${entry.dir ? ' dir' : ''}`,
      title: entry.path,
      onclick: () => (entry.dir ? options.onEnter(entry.path)
        : (options.onFile ? options.onFile(entry) : null)),
    }, [
      UI.el('span', { class: 'fb-name', text: (entry.dir ? '📁 ' : '📄 ') + entry.name }),
    ]);
    // A tick box rather than click-to-select: clicking a row already means
    // "go in" for a folder and "open" for a file, and one gesture cannot
    // sensibly mean both. The box also survives the list being redrawn, which
    // a highlight would not.
    if (options.pick) {
      const box = UI.el('input', { type: 'checkbox', class: 'fb-tick',
                                   title: 'Choose this one' });
      box.checked = options.pick.has(entry.path);
      box.addEventListener('click', (event) => event.stopPropagation());
      box.addEventListener('change', () => options.onPick(entry, box.checked));
      row.insertBefore(box, row.firstChild);
    }
    if (options.draggable && !entry.dir) {
      // Dragging a file onto the canvas is the same gesture as dragging one in
      // from the desktop, and lands the same node -- except that this one
      // already knows the path, so nothing is copied anywhere.
      row.setAttribute('draggable', 'true');
      row.addEventListener('dragstart', (event) => {
        event.dataTransfer.setData('text/comfygmx-file', entry.path);
        event.dataTransfer.setData('text/plain', entry.path);
        event.dataTransfer.effectAllowed = 'copy';
      });
    }
    if (entry.where && entry.where !== '.') {
      row.appendChild(UI.el('span', { class: 'fb-where', text: entry.where,
                                      title: entry.path }));
    }
    const actions = options.actions ? options.actions(entry) : [];
    for (const action of actions) if (action) row.appendChild(action);
    row.appendChild(UI.el('span', {
      class: 'fb-size', text: entry.dir ? '' : UI.bytes(entry.size),
    }));
    host.appendChild(row);
  }
  if (options.dirsOnly && files) {
    host.appendChild(UI.el('div', {
      class: 'fb-note',
      text: `${files} file${files === 1 ? '' : 's'} here, not shown — this is a `
          + 'folder chooser',
    }));
  }
  // "This folder is empty" is only true when nothing was hidden. With a filter
  // on it contradicted the line right under it, which said what had been
  // filtered out and offered to look deeper.
  if (!data.entries.length && !options.filtered) {
    host.appendChild(UI.el('div', { class: 'fb-note', text: 'this folder is empty' }));
  }
}

/* ------------------------------------------------------------ the pickers */

const Pick = {
  /* Choose a folder, and make one without leaving.

     `describe` is how the output-folder dialog keeps its free-space report:
     it is called with each folder as you walk into it, and whatever it
     answers appears under the listing. */
  folder({ start = '', title = 'Choose a folder', hint = '', label = 'Use this folder',
           extra = [], buttons = [], describe = null, onPick } = {}) {
    const pathInput = UI.el('input', { type: 'text', value: start, spellcheck: 'false' });
    const list = UI.el('div', { class: 'file-browser' });
    const note = UI.el('div', { class: 'hint' });
    let here = start;

    const say = async (path) => {
      if (!describe) return;
      note.textContent = 'checking…';
      const said = await describe(path);
      note.className = `hint${said && said.warn ? ' warn' : ''}`;
      note.textContent = (said && said.text) || '';
    };

    const load = async (path) => {
      let data;
      try {
        data = await API.files(path);
      } catch (err) {
        // A folder that is not there yet is a perfectly good answer here --
        // "create it under this name" -- so say so and keep the typed path.
        list.innerHTML = '';
        list.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
        say(path);
        return;
      }
      here = data.path;
      pathInput.value = data.path;
      // Rename and delete on the rows themselves. Choosing where to put
      // something is exactly when you notice last week's folder is misspelt
      // or was never wanted, and leaving for a terminal to fix that loses the
      // dialog you were in the middle of.
      renderListing(list, data, {
        dirsOnly: true,
        onEnter: load,
        actions: (entry) => (!entry.dir ? [] : [
          UI.el('button', {
            class: 'fb-act', text: '✎', title: `Rename ${entry.name}`,
            onclick: async (event) => {
              event.stopPropagation();
              const name = prompt(`New name for\n${entry.path}`, entry.name);
              if (name === null || name.trim() === entry.name) return;
              try {
                await API.renamePath(entry.path, name.trim());
                UI.toast(`renamed to ${name.trim()}`, 'ok');
              } catch (err) { UI.toast(err.message, 'error', 12000); }
              load(here);
            },
          }),
          UI.el('button', {
            class: 'fb-act', text: '🗑', title: `Move ${entry.name} to the trash`,
            onclick: async (event) => {
              event.stopPropagation();
              if (!confirm(`Move to the trash:\n\n${entry.path}\n\n`
                           + 'It keeps its name and can be carried back out of '
                           + 'the trash folder in the data directory.')) return;
              try {
                const result = await API.deletePaths([entry.path], false);
                if (result.other_disk && result.other_disk.length) {
                  UI.toast(`${entry.name} is on a different disk from the trash. `
                    + 'Use the Files panel, which can offer to delete it for good.',
                  'warn', 12000);
                } else {
                  UI.toast(`${entry.name} moved to the trash`, 'ok', 7000);
                }
              } catch (err) { UI.toast(err.message, 'error', 12000); }
              load(here);
            },
          }),
        ]),
      });
      say(data.path);
    };

    const create = async () => {
      const name = prompt(`New folder inside\n${here}`, '');
      if (name === null) return;
      try {
        const made = await API.mkdir(here, name.trim());
        UI.toast(`created ${made.path}`, 'ok');
        load(made.path);
      } catch (err) { UI.toast(err.message, 'error'); }
    };

    pathInput.addEventListener('change', () => load(pathInput.value.trim()));
    const body = UI.el('div', {}, [
      hint ? UI.el('p', { class: 'hint', text: hint }) : null,
      UI.el('div', { class: 'row' }, [
        pathInput,
        UI.el('button', { class: 'small', text: 'Go', onclick: () => load(pathInput.value.trim()) }),
        UI.el('button', { class: 'small', text: 'New folder…', onclick: create }),
        UI.el('button', {
          class: 'small', text: 'Copy path', title: "Copy this folder's path",
          onclick: () => UI.copy(pathInput.value.trim()),
        }),
      ]),
      extra.length ? UI.el('div', { class: 'row wrap fb-jump' }, extra.map((shortcut) =>
        UI.el('button', {
          class: 'small', text: shortcut.label, title: shortcut.path,
          onclick: () => load(shortcut.path),
        }))) : null,
      list,
      describe ? note : null,
    ].filter(Boolean));

    // Same rule as the file browser: opened from inside another dialog -- the
    // Settings page reaches for it -- this goes on the layer above and leaves
    // that dialog alone. Settings used to be re-drawn from a snapshot of its
    // boxes afterwards, which covered the ordinary path and lost everything
    // typed if the picker was cancelled instead.
    const footer = [
      { label: 'Cancel' },
      ...buttons,
      { label, primary: true, action: () => { onPick(pathInput.value.trim()); } },
    ];
    if (UI.modalOpen()) UI.subModal(title, body, footer);
    else UI.modal(title, body, footer);
    load(start);
  },

  /* Write a small text file: a new one in `directory`, or an existing `path`.
     Anything the text endpoint would truncate is refused rather than opened,
     because saving a truncated file deletes the rest of it. */
  async editText({ path = '', directory = '', name = '', text = null, onSaved } = {}) {
    if (text === null && path) {
      let data;
      try { data = await API.fileText(path); }
      catch (err) { UI.toast(err.message, 'error'); return; }
      if (data.truncated) {
        UI.toast(`${baseName(path)} is ${UI.bytes(data.size)}; this editor would only `
                 + 'show the start of it, and saving would throw the rest away. '
                 + 'Open it in a real editor.', 'error', 12000);
        return;
      }
      text = data.text;
    }
    if (text === null) text = '';
    const nameInput = UI.el('input', {
      type: 'text', value: name || baseName(path), spellcheck: 'false',
      placeholder: 'index.ndx',
    });
    if (path) nameInput.disabled = true;
    const area = UI.el('textarea', { rows: '18', spellcheck: 'false' });
    area.value = text;
    area.className = 'code';

    const body = UI.el('div', {}, [
      UI.el('p', { class: 'hint', text: path ? path : `New file in ${directory}` }),
      path ? null : UI.el('div', { class: 'field' }, [
        UI.el('label', { text: 'Name' }), nameInput]),
      area,
    ].filter(Boolean));

    UI.modal(path ? `Edit ${baseName(path)}` : 'New file', body, [
      { label: 'Cancel' },
      {
        label: 'Save',
        primary: true,
        action: async () => {
          const payload = path
            ? { path, text: area.value }
            : { path: directory, name: nameInput.value.trim(), text: area.value };
          try {
            const saved = await API.writeFile(payload);
            UI.toast(`wrote ${saved.name} (${UI.bytes(saved.size)})`, 'ok');
            if (onSaved) onSaved(saved);
          } catch (err) {
            // The modal closes on any answer a button gives, so handing the
            // typing back means opening it again with what was typed in it --
            // rather than losing a page of mdp to one bad file name.
            UI.toast(err.message, 'error', 9000);
            Pick.editText({ path, directory, name: nameInput.value,
                            text: area.value, onSaved });
          }
          return true;
        },
      },
    ]);
  },
};

/* Which of these folders is the gigabyte, and is it safe to delete.

   Deleting a run is always safe -- every cache entry is re-checked when it is
   looked up, so a node whose files are gone simply runs again. The hard part
   is knowing *which* folder holds the data, and `du -sh` in a terminal was the
   only way to find out. Two things decide it: the size, and whether the folder
   is one a re-run left behind holding nothing but a workflow.json, its results
   still sitting in the older folder it reused. */
const RunFolders = {
  async show(root = '') {
    let data;
    try {
      data = await API.runFolders(root);
    } catch (err) {
      // A session can point at a folder that has since been deleted -- which
      // is exactly the sort of tidying this dialog is for -- so fall back to
      // the default rather than refusing to open.
      if (!root) { UI.toast(err.message, 'error'); return; }
      try { data = await API.runFolders(''); }
      catch (second) { UI.toast(second.message, 'error'); return; }
      UI.toast(`${root} is not there any more — showing the default run folder`,
               'warn', 6000);
    }
    this.render(data);
  },

  render(data) {
    const body = UI.el('div');
    const chosen = new Set();
    body.appendChild(UI.el('p', { class: 'hint' }, [
      `${data.runs.length} run${data.runs.length === 1 ? '' : 's'} in `,
      UI.el('code', { text: data.root }),
      ` — ${UI.bytes(data.bytes)}${data.partial ? '+ (still counting)' : ''} in total.`,
    ]));
    body.appendChild(UI.el('p', { class: 'hint', text:
      'Deleting one is safe: anything cached from it runs again next time rather '
      + 'than breaking. Watch the size rather than the date — a run that reused '
      + 'everything creates no node directories of its own, and its results are '
      + 'still in the older folder it reused.' }));

    const total = UI.el('div', { class: 'hint' });
    const paint = () => {
      const bytes = data.runs.filter((run) => chosen.has(run.path))
        .reduce((sum, run) => sum + run.bytes, 0);
      total.textContent = chosen.size
        ? `${chosen.size} selected — ${UI.bytes(bytes)}`
        : 'nothing selected';
      remove.disabled = !chosen.size;
      remove.textContent = chosen.size
        ? `Delete ${chosen.size} folder${chosen.size === 1 ? '' : 's'} (${UI.bytes(bytes)})`
        : 'Delete';
    };

    const table = UI.el('table', { class: 'runs-table' });
    for (const run of data.runs) {
      const tick = UI.el('input', { type: 'checkbox' });
      tick.addEventListener('change', () => {
        if (tick.checked) chosen.add(run.path); else chosen.delete(run.path);
        paint();
      });
      const when = new Date(run.modified * 1000);
      table.appendChild(UI.el('tr', {}, [
        UI.el('td', {}, [tick]),
        UI.el('td', {}, [
          UI.el('div', { text: run.name }),
          UI.el('div', { class: 'hint', text:
            `${run.nodes} node folder${run.nodes === 1 ? '' : 's'}, ${run.files} files`
            + (run.bookkeeping ? ' — reused everything; its results are elsewhere' : '')
            + (run.cached ? ` — ${run.cached} cached result${run.cached === 1 ? '' : 's'} still point here` : '') }),
        ]),
        UI.el('td', { class: 'num', text: UI.bytes(run.bytes) }),
        UI.el('td', { class: 'muted', text: Number.isFinite(when.getTime())
          ? when.toLocaleString() : '' }),
      ]));
    }
    body.appendChild(table);
    body.appendChild(total);

    const remove = UI.el('button', { class: 'danger', text: 'Delete' });
    remove.disabled = true;
    remove.addEventListener('click', async () => {
      const doomed = data.runs.filter((run) => chosen.has(run.path));
      const bytes = doomed.reduce((sum, run) => sum + run.bytes, 0);
      const holding = doomed.filter((run) => run.cached);
      if (!confirm(`Delete ${doomed.length} run folder`
        + `${doomed.length === 1 ? '' : 's'} — ${UI.bytes(bytes)}?\n\n`
        + (holding.length
          ? `${holding.length} of them still hold results the cache is reusing; `
            + 'those nodes will run again next time.\n\n' : '')
        + 'This cannot be undone.')) return;
      let freed = 0;
      for (const run of doomed) {
        try {
          await API.deleteRunFolder(run.path);
          freed += run.bytes;
        } catch (err) { UI.toast(`${run.name}: ${err.message}`, 'error', 10000); }
      }
      UI.toast(`freed ${UI.bytes(freed)}`, 'ok');
      this.show(data.root);
    });

    paint();
    UI.modal('Run folders', body, [{ label: 'Close' }, { label: remove.textContent,
      primary: false, action: () => { remove.click(); return false; } }]);
    // The footer button is a proxy for the real one, which carries the count.
    const footer = document.getElementById('modal-footer');
    footer.replaceChild(remove, footer.lastChild);
  },
};

/* What is in a trajectory: frames, how far apart, how many atoms.

   Counting frames means decompressing every one of them -- half an hour for a
   46 GB file on a share that reads at 21 MB/s -- so this never scans by
   itself. Once it has been asked, the answer is kept against the file's size
   and modification time, and everything that needs it afterwards is instant:
   the preview node stops re-counting on every parameter change, and it can
   work out its own stride rather than shelling out to find one. */
const TrajectoryFacts = {
  async show(path) {
    let data;
    try { data = await API.trajFacts(path, false); }
    catch (err) { UI.toast(err.message, 'error'); return; }
    this.render(path, data);
  },

  render(path, data) {
    const body = UI.el('div');
    body.appendChild(UI.el('p', { class: 'hint', text: path }));
    if (data.known) {
      const table = UI.el('table');
      const rows = [
        ['frames', String(data.frames)],
        ['spacing', data.dt ? `${data.dt} ps` : 'not stated'],
        ['covers', data.length ? `${data.length} ps` : '—'],
        ['atoms', String(data.atoms || '—')],
        ['precision', data.precision ? `${data.precision} nm` : '—'],
        ['size', UI.bytes(data.size || 0)],
      ];
      for (const [key, value] of rows) {
        table.appendChild(UI.el('tr', {}, [
          UI.el('th', { text: key }), UI.el('td', { text: value })]));
      }
      body.appendChild(table);
      body.appendChild(UI.el('p', { class: 'hint', text:
        'Read once and remembered against this file\'s size and modification '
        + 'time. A trajectory still being written looks different next time and '
        + 'is read again.' }));
    } else {
      body.appendChild(UI.el('p', { text:
        `Nothing is known about this file yet. Counting the frames means `
        + `reading all ${UI.bytes(data.size || 0)} of it — GROMACS has to `
        + 'decompress every frame to count them, and on a network share that is '
        + 'minutes rather than seconds.' }));
      body.appendChild(UI.el('p', { class: 'hint', text:
        'Worth doing once: everything afterwards is instant, including the '
        + 'trajectory preview node, which otherwise counts the file again every '
        + 'time you change how many frames you want.' }));
    }

    const buttons = [{ label: 'Close' }];
    if (!data.known) {
      buttons.unshift({
        label: 'Count the frames',
        primary: true,
        action: () => {
          UI.toast('reading the trajectory — this can take a while', 'info', 8000);
          API.trajFacts(path, true)
            .then((fresh) => { UI.toast('read and remembered', 'ok'); this.render(path, fresh); })
            .catch((err) => UI.toast(err.message, 'error', 12000));
        },
      });
    }
    UI.modal(`What is in ${baseName(path)}`, body, buttons);
  },
};

/* -------------------------------------------------------- the Files tab */

const FileBrowser = {
  /* 'run' lists what the current run produced, grouped by node. 'browse'
     walks the filesystem. The run view is the better answer to "what did that
     just make", so it stays the default whenever there is a run. */
  mode: 'run',
  cwd: '',
  /* What is typed in the search box. Filters what is on screen; the deep
     search below uses the same word but asks the server instead. */
  filter: '',
  /* Results of a search that went below this folder, or null when the panel is
     showing an ordinary listing. */
  found: null,

  init() {
    const on = (id, event, fn) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener(event, fn);
    };
    on('btn-files-mode', 'click', () => this.setMode(this.mode === 'run' ? 'browse' : 'run'));
    on('btn-refresh-files', 'click', () => this.refresh());
    on('btn-files-runs', 'click', () => RunFolders.show(
      (Sessions.active() || {}).outputDir || ''));
    on('btn-files-up', 'click', () => this.enter(this.parentOf(this.cwd)));
    on('btn-files-copy', 'click', () => {
      if (this.cwd) UI.copy(this.cwd);
    });
    on('btn-files-newdir', 'click', () => this.newFolder());
    on('btn-files-cut', 'click', () => this.hold(true));
    on('btn-files-copysel', 'click', () => this.hold(false));
    on('btn-files-paste', 'click', () => this.paste());
    on('btn-files-rename', 'click', () => this.renameChosen());
    on('btn-files-trash', 'click', () => this.trashChosen());
    on('btn-files-none', 'click', () => this.clearPicks());
    on('btn-files-newfile', 'click', () => Pick.editText({
      directory: this.cwd, onSaved: () => this.refresh(),
    }));
    on('files-path', 'change', (event) => this.enter(event.target.value.trim()));

    // Typing filters what is already on screen -- instant, and enough most of
    // the time. Enter, or the button, goes and looks underneath as well.
    on('files-filter', 'input', (event) => {
      this.filter = event.target.value.trim();
      this.found = null;
      const clear = document.getElementById('btn-files-clear');
      if (clear) clear.classList.toggle('hidden', !this.filter);
      this.repaint();
    });
    on('files-filter', 'keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); this.deepSearch(); }
      if (event.key === 'Escape') {
        event.preventDefault();
        event.target.value = '';
        this.filter = '';
        this.found = null;
        this.repaint();
      }
    });
    on('btn-files-deep', 'click', () => this.deepSearch());
    on('btn-files-clear', 'click', () => {
      const box = document.getElementById('files-filter');
      if (box) box.value = '';
      this.filter = '';
      this.found = null;
      document.getElementById('btn-files-clear').classList.add('hidden');
      this.repaint();
    });

    // Dropping a file on the panel means "put a copy here", which is the one
    // thing the canvas cannot do for you: a node points at a file, it does not
    // move it.
    const panel = document.getElementById('tab-files');
    if (!panel) return;
    panel.addEventListener('dragover', (event) => {
      if (this.mode !== 'browse' || !this.cwd) return;
      if (!App.dragCarriesFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      try { event.dataTransfer.dropEffect = 'copy'; } catch (err) { /* advisory */ }
      panel.classList.add('drop-target');
    });
    panel.addEventListener('dragleave', () => panel.classList.remove('drop-target'));
    panel.addEventListener('drop', (event) => {
      panel.classList.remove('drop-target');
      if (this.mode !== 'browse' || !this.cwd) return;
      if (!App.dragCarriesFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      this.take(event.dataTransfer);
    });
  },

  /* Redraw whatever the panel is showing, with the filter applied. Cheap: it
     re-asks the server for the folder, which is a directory listing. */
  repaint() {
    if (this.found) { this.showFound(); return; }
    this.refresh();
  },

  /* Does this name match what is typed? Plain "contains", not case sensitive:
     a filter box that needs a pattern language is a filter box nobody uses. */
  matches(name) {
    if (!this.filter) return true;
    return String(name || '').toLowerCase().includes(this.filter.toLowerCase());
  },

  /* Look in this folder and every folder under it. */
  async deepSearch() {
    if (!this.filter) { UI.toast('type something to look for first', 'warn'); return; }
    const where = this.mode === 'browse' ? this.cwd : (this.runDir() || this.cwd);
    if (!where) { UI.toast('nowhere to search — open a folder first', 'warn'); return; }
    const host = document.getElementById('files-list');
    host.innerHTML = '';
    host.appendChild(UI.el('div', { class: 'fb-note searching',
                                    text: `looking for "${this.filter}" under ${where}…` }));
    try {
      const data = await API.findFiles(where, this.filter);
      this.found = data;
      this.showFound();
    } catch (err) {
      host.innerHTML = '';
      host.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
    }
  },

  showFound() {
    const data = this.found;
    const host = document.getElementById('files-list');
    host.innerHTML = '';
    const title = document.getElementById('files-title');
    if (title) {
      title.textContent = `"${this.filter}" under ${baseName(data.path)}`;
      title.title = data.path;
    }
    const note = UI.el('div', { class: 'fb-note' }, [
      data.entries.length
        ? `${data.entries.length} match${data.entries.length === 1 ? '' : 'es'} in `
          + `${data.searched} folder${data.searched === 1 ? '' : 's'}`
          + (data.complete ? '' : ' — stopped early, so there may be more')
        : `nothing called "${this.filter}" under here`,
      ' ',
      UI.el('button', { class: 'small', text: 'back to the folder',
                        onclick: () => { this.found = null; this.repaint(); } }),
    ]);
    renderListing(host, { path: data.path, parent: data.path, entries: data.entries }, {
      note,
      draggable: true,
      // Ticking works here too. A search is where the scattered ones turn up,
      // and gathering them is exactly what somebody is doing at that moment.
      pick: this.chosen,
      onPick: (entry, wanted) => this.pick(entry, wanted),
      onEnter: (next) => { this.found = null; this.setMode('browse'); this.enter(next); },
      onFile: (entry) => App.openFile(entry.path),
    });
  },

  parentOf(path) {
    const trimmed = String(path || '').replace(/\/+$/, '');
    const cut = trimmed.lastIndexOf('/');
    return cut > 0 ? trimmed.slice(0, cut) : '/';
  },

  setMode(mode) {
    this.mode = mode;
    const browsing = mode === 'browse';
    const button = document.getElementById('btn-files-mode');
    if (button) {
      button.textContent = browsing ? 'By node' : 'Browse';
      button.title = browsing
        ? 'Back to the files this run produced, grouped by node'
        : 'Walk the filesystem: copy a path, make a folder, drag a file onto the canvas';
    }
    for (const id of ['files-bar', 'files-jump']) {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('hidden', !browsing);
    }
    // Leaving the browser drops the ticks. They are positions in a filesystem
    // and the run view is a different thing entirely, so carrying them across
    // would only mean deleting something you had forgotten was ticked.
    if (!browsing) this.chosen.clear();
    this.paintActions();
    if (browsing && !this.cwd) this.enter(this.startingPoint());
    else this.refresh();
  },

  /* Where "Browse" opens: whatever you are most likely to have meant. */
  startingPoint() {
    const session = Sessions.active ? Sessions.active() : null;
    return this.runDir() || (session && session.outputDir) || '';
  },

  /* Where this session's run put its node directories -- not the last run
     anywhere. A background session's run has its own. */
  runDir() {
    const session = Sessions.active ? Sessions.active() : null;
    return (session && session.run && session.run.workdir) || '';
  },

  refresh() {
    if (this.mode === 'browse') this.enter(this.cwd || this.startingPoint());
    else this.showRun();
  },

  /* Counts the listings asked for, so a slow one cannot land after a quick
     one and put the panel back in the folder you just left. Pressing Cut and
     then immediately clicking a folder does exactly that: Cut redraws where
     you are, the click asks for somewhere else, and whichever the server
     answers last used to win. Then Paste went to the wrong folder. */
  asked: 0,

  async enter(path) {
    const host = document.getElementById('files-list');
    const mine = (this.asked += 1);
    let data;
    try {
      data = await API.files(path || '');
    } catch (err) {
      if (mine !== this.asked) return;
      host.innerHTML = '';
      host.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
      return;
    }
    if (mine !== this.asked) return;
    this.cwd = data.path;
    this.mode = 'browse';
    this.paintActions();
    const input = document.getElementById('files-path');
    if (input) input.value = data.path;
    document.getElementById('files-title').textContent = baseName(data.path);
    document.getElementById('files-title').title = data.path;
    this.jumpRow();
    const shown = this.filter
      ? { ...data, entries: data.entries.filter((e) => this.matches(e.name)) }
      : data;
    if (this.filter && !shown.entries.length) {
      host.innerHTML = '';
      host.appendChild(UI.el('div', { class: 'fb-note' }, [
        `nothing here is called "${this.filter}". `,
        UI.el('button', { class: 'small', text: 'Look in sub-folders',
                          onclick: () => this.deepSearch() }),
      ]));
      return;
    }
    renderListing(host, shown, {
      draggable: true,
      pick: this.chosen,
      onPick: (entry, wanted) => this.pick(entry, wanted),
      onEnter: (next) => this.enter(next),
      onFile: (entry) => App.openFile(entry.path),
      actions: (entry) => (entry.dir ? [] : [
        entry.size <= EDITABLE_BYTES && TEXTISH.test(entry.name) ? UI.el('button', {
          class: 'fb-act', text: '✎', title: 'Edit this file',
          onclick: (event) => {
            event.stopPropagation();
            Pick.editText({ path: entry.path, onSaved: () => this.refresh() });
          },
        }) : null,
        UI.el('a', {
          class: 'fb-act', href: API.downloadUrl(entry.path), text: '↓',
          title: 'Download', onclick: (event) => event.stopPropagation(),
        }),
      ]),
    });
  },

  /* The two or three folders worth one click: where this run went, where this
     session puts its runs, and home. */
  jumpRow() {
    const host = document.getElementById('files-jump');
    if (!host) return;
    host.innerHTML = '';
    const session = Sessions.active ? Sessions.active() : null;
    const shortcuts = [
      { label: 'this run', path: this.runDir() },
      { label: 'output folder', path: (session && session.outputDir) || App.outputRoot },
      { label: 'uploads', path: App.uploadsDir },
      { label: 'home', path: App.homeDir },
    ].filter((shortcut) => shortcut.path && shortcut.path !== this.cwd);
    for (const shortcut of shortcuts) {
      host.appendChild(UI.el('button', {
        class: 'small', text: shortcut.label, title: shortcut.path,
        onclick: () => this.enter(shortcut.path),
      }));
    }
  },

  /* ------------------------------------------------------------- tidying */
  /* Which rows are ticked, and what is waiting to be pasted.

     The panel could always look; it could not tidy. Every "move these results
     somewhere sensible" meant leaving for a terminal, which is the commonest
     thing anybody does between runs. So: tick some rows, then Cut or Copy,
     walk to another folder, Paste.

     Paths rather than names, because the ticks have to survive walking into a
     folder and back out, and a search shows rows from several folders at
     once. */
  chosen: new Set(),
  clipboard: null,

  pick(entry, wanted) {
    if (wanted) this.chosen.add(entry.path);
    else this.chosen.delete(entry.path);
    this.paintActions();
  },

  clearPicks() {
    this.chosen.clear();
    this.paintActions();
    this.repaint();
  },

  /* What the row of buttons says and which of them can be pressed. */
  paintActions() {
    const bar = document.getElementById('files-actions');
    if (!bar) return;
    bar.classList.toggle('hidden', this.mode !== 'browse');
    const count = this.chosen.size;
    const held = this.clipboard ? this.clipboard.paths.length : 0;
    const label = document.getElementById('files-chosen');
    if (label) {
      label.textContent = count
        ? `${count} ticked`
        : (held ? `${held} waiting to be ${this.clipboard.move ? 'moved' : 'copied'}`
          : 'tick rows to move, copy or delete them');
    }
    const set = (id, on, title) => {
      const button = document.getElementById(id);
      if (!button) return;
      button.disabled = !on;
      if (title) button.title = title;
    };
    set('btn-files-cut', count > 0);
    set('btn-files-copysel', count > 0);
    set('btn-files-rename', count === 1,
      count === 1 ? 'Rename the one you ticked' : 'Tick exactly one to rename it');
    set('btn-files-trash', count > 0);
    set('btn-files-none', count > 0);
    set('btn-files-paste', held > 0 && !!this.cwd,
      held ? `Put ${held} thing(s) into this folder` : 'Nothing is waiting');
  },

  hold(move) {
    if (!this.chosen.size) return;
    this.clipboard = { paths: [...this.chosen], move };
    this.chosen.clear();
    UI.toast(`${this.clipboard.paths.length} thing(s) ready to be `
      + `${move ? 'moved' : 'copied'} — walk to a folder and press Paste`, 'info', 7000);
    this.paintActions();
    this.repaint();
  },

  async paste() {
    if (!this.clipboard || !this.cwd) return;
    const { paths, move } = this.clipboard;
    try {
      const result = move
        ? await API.movePaths(paths, this.cwd)
        : await API.copyPaths(paths, this.cwd);
      UI.toast(`${result.count} thing(s) ${move ? 'moved' : 'copied'} here`, 'ok', 6000);
      // A move is spent; a copy can be pasted again somewhere else, which is
      // what everybody expects of a copy.
      if (move) this.clipboard = null;
    } catch (err) {
      UI.toast(err.message, 'error', 12000);
    }
    this.paintActions();
    this.refresh();
  },

  async renameChosen() {
    if (this.chosen.size !== 1) return;
    const path = [...this.chosen][0];
    const was = baseName(path);
    const name = prompt(`New name for\n${path}`, was);
    if (name === null || name.trim() === was) return;
    try {
      await API.renamePath(path, name.trim());
      UI.toast(`renamed to ${name.trim()}`, 'ok');
      this.chosen.clear();
    } catch (err) { UI.toast(err.message, 'error', 12000); }
    this.paintActions();
    this.refresh();
  },

  /* Delete, which is the one that has to be careful.

     Nothing goes for good on the first press: things are moved into a trash
     folder inside the data directory, keeping their names, where they can be
     walked to and carried back. Only where the trash is on a different disk --
     when a rename is not possible and the trash would mean copying every byte
     first -- is there a second question, and that one says how much. */
  async trashChosen() {
    if (!this.chosen.size) return;
    const paths = [...this.chosen];
    const names = paths.map(baseName);
    const shown = names.slice(0, 6).join(', ') + (names.length > 6 ? ' ...' : '');
    if (!confirm(`Move to the trash:\n\n${shown}\n\n`
                 + 'They keep their names and can be carried back out of the '
                 + 'trash folder in the data directory.')) return;
    let result;
    try {
      result = await API.deletePaths(paths, false);
    } catch (err) { UI.toast(err.message, 'error', 12000); return; }

    if (result.other_disk && result.other_disk.length) {
      const lines = result.other_disk.map((item) =>
        `  ${item.name}: ${item.files} file(s), ${UI.bytes(item.bytes)}`
        + (item.counted_all ? '' : ' or more'));
      const ok = confirm(
        'These are on a different disk from the trash folder, so putting them '
        + 'there would mean copying every byte first:\n\n' + lines.join('\n')
        + `\n\nthe trash is ${result.trash}\n\n`
        + 'Delete them for good instead? This cannot be undone.');
      if (!ok) { UI.toast('nothing was deleted', 'info'); return; }
      try {
        const gone = await API.deletePaths(paths, true);
        UI.toast(`${gone.count} thing(s) deleted for good`, 'warn', 8000);
      } catch (err) { UI.toast(err.message, 'error', 12000); return; }
    } else {
      UI.toast(`${result.count} thing(s) moved to the trash — ${result.trash}`,
        'ok', 9000);
    }
    this.chosen.clear();
    this.paintActions();
    this.refresh();
  },

  async newFolder() {
    if (!this.cwd) return;
    const name = prompt(`New folder inside\n${this.cwd}`, '');
    if (name === null) return;
    try {
      const made = await API.mkdir(this.cwd, name.trim());
      UI.toast(`created ${made.name}`, 'ok');
      this.enter(made.path);
    } catch (err) { UI.toast(err.message, 'error'); }
  },

  /* Files dropped on the panel are copied into the folder being shown. */
  async take(dt) {
    const files = dt.files ? [...dt.files] : [];
    if (!files.length) {
      UI.toast('that drag carried no files', 'warn');
      return;
    }
    const target = this.cwd;
    let done = 0;
    for (const file of files) {
      try {
        await API.upload(file, target);
        done += 1;
      } catch (err) {
        UI.toast(`${file.name}: ${err.message}`, 'error', 10000);
      }
    }
    if (done) {
      UI.toast(`copied ${done} file${done === 1 ? '' : 's'} into ${baseName(target)}`, 'ok');
      this.refresh();
    }
  },

  /* The original view: what this run wrote, under the node that wrote it. */
  async showRun() {
    const host = document.getElementById('files-list');
    document.getElementById('files-title').textContent = App.runId
      ? `run ${App.runId}` : 'run files';
    if (!App.runId) {
      host.innerHTML = '';
      host.appendChild(UI.el('div', { class: 'fb-note' }, [
        'Nothing has run in this session yet. ',
        UI.el('button', { class: 'small', text: 'Browse the filesystem',
                          onclick: () => this.setMode('browse') }),
      ]));
      return;
    }
    let data;
    try { data = await API.runFiles(App.runId); }
    catch (err) {
      host.innerHTML = '';
      host.appendChild(UI.el('div', { class: 'fb-note', text: err.message }));
      return;
    }
    host.innerHTML = '';
    let shownFiles = 0;
    for (const group of data.nodes) {
      const node = Editor.nodes.get(group.node);
      const files = group.files.filter((file) => this.matches(file.name));
      // A node whose files all filtered out is not worth a heading.
      if (this.filter && !files.length) continue;
      shownFiles += files.length;
      host.appendChild(UI.el('div', { class: 'file-group' }, [
        UI.el('div', { class: 'head', title: group.workdir }, [
          UI.el('span', { text: `${node ? node.title : group.node} — ${group.workdir}` }),
          UI.el('button', {
            class: 'fb-act', text: '⧉', title: 'Copy this folder\'s path',
            onclick: (event) => { event.stopPropagation(); UI.copy(group.workdir); },
          }),
          UI.el('button', {
            class: 'fb-act', text: '→', title: 'Open this folder in the browser',
            onclick: (event) => { event.stopPropagation(); this.setMode('browse'); this.enter(group.workdir); },
          }),
        ]),
      ]));
      for (const file of files) {
        const row = UI.el('div', {
          class: 'file-row', draggable: 'true', title: file.path,
          onclick: () => App.openFile(file.path),
        }, [
          UI.el('span', { class: 'name', text: file.name }),
          UI.el('span', { class: 'size', text: UI.bytes(file.size) }),
          UI.el('a', {
            class: 'size', href: API.downloadUrl(file.path), text: '↓',
            title: 'download', onclick: (event) => event.stopPropagation(),
          }),
        ]);
        row.addEventListener('dragstart', (event) => {
          event.dataTransfer.setData('text/comfygmx-file', file.path);
          event.dataTransfer.setData('text/plain', file.path);
          event.dataTransfer.effectAllowed = 'copy';
        });
        host.appendChild(row);
      }
    }
    if (this.filter && !shownFiles) {
      host.appendChild(UI.el('div', { class: 'fb-note' }, [
        `nothing this run produced is called "${this.filter}". `,
        UI.el('button', { class: 'small', text: 'Look in the run folder',
                          onclick: () => this.deepSearch() }),
      ]));
    }
  },
};
