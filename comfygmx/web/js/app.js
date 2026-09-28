/* Application wiring: palette, run control, live logs and the inspector tabs. */
'use strict';

/* Mirrors MAX_BODY in server.py: past this the upload is refused, so say so
   before spending minutes pushing bytes at it. */
const MAX_UPLOAD = 64 * 1024 * 1024;

/* What a dropped file becomes. A structure gets its own loader and an .mdp
   gets the run-parameters node; everything else becomes a Load file, which
   works its own type out from the name -- so there is no list of extensions
   here to fall behind the one the server keeps. */
const DROP_NODES = [
  { ext: ['pdb', 'gro', 'g96', 'cif', 'pdbx', 'ent', 'mmcif'], type: 'io.structure' },
  { ext: ['mdp'], type: 'util.mdp', params: { mode: 'file' } },
];

/* One colour per tutorial collection: blue for the published GROMACS set, and
   the analysis green for the one made for this workshop. */
const TUTORIAL_COLOURS = {
  gmx: '#2b5d8a',
  workshop: '#3f7a6d',
};

const App = {
  defs: {},
  /* 'palette' | 'page' | null -- where the drag in flight started. */
  dragSource: null,
  /* What the last drop said it was carrying, so a drag this cannot use can
     say why rather than just failing. */
  lastDropTypes: [],
  chunks: [],
  tutorials: [],
  tutorialMeta: {},
  selectedNode: null,
  clipboard: null,
  logNode: null,
  _planTimer: null,

  /* The active session owns the graph, the output folder and the run. These
     read through to it so the rest of the app does not have to care. */
  get session() { return Sessions.active(); },
  get workflowName() {
    const session = Sessions.active();
    return session ? session.name : '';
  },
  set workflowName(name) {
    const session = Sessions.active();
    if (session) Sessions.rename(session.id, name);
  },
  get runId() {
    const session = Sessions.active();
    return session && session.run ? session.run.id : null;
  },

  async boot() {
    Viewer.init();
    Plot.init();

    // All four at once rather than one after another. None of them needs an
    // answer from any of the others, and waiting in turn meant the canvas sat
    // empty for the sum of the four instead of the longest one.
    let info; let catalogue; let chunkList; let tutorialCatalogue;
    try {
      [info, catalogue, chunkList, tutorialCatalogue] = await Promise.all([
        API.info(),
        API.nodes(),
        API.chunks(),
        // The tutorial list is allowed to be missing -- an older server has no
        // such page -- so it answers with an empty one rather than stopping
        // the whole start-up.
        API.tutorials().catch(() => ({ tutorials: [], meta: {} })),
      ]);
    } catch (err) {
      UI.toast(`cannot reach the server: ${err.message}`, 'error', 20000);
      return;
    }

    Editor.fileKinds = catalogue.file_kinds || {};
    Editor.fileGuide = catalogue.file_guide || {};
    for (const category of catalogue.categories) {
      for (const spec of category.nodes) this.defs[spec.type] = spec;
    }
    this.chunks = chunkList.chunks;
    this.tutorials = tutorialCatalogue.tutorials || [];
    this.tutorialMeta = tutorialCatalogue.meta;

    // What each run-parameters preset actually contains, so the node can show
    // it rather than leaving thirteen blank boxes labelled "preset default".
    API.mdpPresets()
      .then((data) => { Editor.mdp = data; Editor.refreshOpenNodes('util.mdp'); })
      .catch(() => { Editor.mdp = null; });

    this.homeDir = info.home || '';
    this.uploadsDir = info.uploads_dir || '';
    this.outputRoot = info.output_dir || '';

    Editor.init(this.defs);
    Terminal.init();
    FileBrowser.init();
    // Cheap: no probing, just what is on disk. Enough to offer a node the
    // installations it could be pointed at.
    API.environment(false)
      .then((info) => { this.envInfo = info; })
      .catch(() => { this.envInfo = null; });
    Editor.onChange = () => this.schedulePlan();
    Editor.onHistory = () => this.refreshHistoryButtons();
    Editor.onSelect = (ids) => this.onSelect(ids);

    this.buildPalette(catalogue.categories);
    this.buildChunkPalette();
    this.buildTutorialPalette();
    this.bindUI();
    this.bindFind();
    this.restore();

    UI.status(`Comfy-gmx ${info.version} · ${info.nodes} node types · data in ${info.data_dir}`);
    this.offerSetup();
  },

  /* On a machine that is not ready, say so once and offer to fix it.

     Opened by itself only on a genuine first run. After that it is a button in
     the top bar, which appears only while something is actually missing -- a
     dialog that reappears every morning is one people learn to dismiss without
     reading. */
  async offerSetup() {
    let state;
    try {
      state = await API.setup();
    } catch (err) {
      return;
    }
    this.setupState = state;
    const button = document.getElementById('btn-setup');
    button.classList.toggle('hidden', Boolean(state.ready));
    if (!state.ready) {
      const named = (state.blocking || []).map((id) => {
        const tool = (state.tools || []).find((entry) => entry.id === id);
        return tool ? tool.name : id;
      });
      button.title = named.length
        ? `${named.join(', ')} missing — click to sort it out`
        : 'Install what this machine is missing';
    }
    // GROMACS first, when it is the thing missing: it is the one nothing works
    // without, and it is the one first-run setup deliberately does not install.
    const gmx = (state.tools || []).find((tool) => tool.id === 'gmx');
    if (gmx && !gmx.present) {
      Panels.needGromacs(false, state.first_run ? () => Panels.setup(true) : null,
                         gmx.found || []);
    } else if (state.first_run) {
      Panels.setup(true);
    }
  },

  /* Re-read what is installed, after something has just installed it.

     The node inspector offers these as choices, so a tool that arrived while
     the editor was open should be offered without a page reload. */
  refreshEnvInfo() {
    return API.environment(false)
      .then((info) => { this.envInfo = info; })
      .catch(() => { this.envInfo = null; });
  },

  /* Which installations a node could be pointed at.

     Conda environments that actually hold the tool, and for GROMACS the builds
     found on disk -- those are not environments, so the override takes a
     version or a GMXRC path instead and the toolbox resolves either. */
  installChoices(tool) {
    if (!tool || !this.envInfo) return [];
    if (tool === 'gmx') {
      const builds = this.envInfo.gmxrc_candidates || [];
      // The short form where it is unambiguous, the path where it is not: two
      // 2024.4 builds -- one MPI, one double precision -- are a real thing to
      // have, and "2024.4" would then quietly mean whichever came first.
      const counts = new Map();
      for (const c of builds) counts.set(c.version, (counts.get(c.version) || 0) + 1);
      return builds.map((c) => ({
        value: c.version && counts.get(c.version) === 1 ? c.version : c.prefix,
        label: `${c.version || 'version ?'} · ${(c.binaries || []).join(', ')} · ${c.prefix}`,
      }));
    }
    return ((this.envInfo.installs || {})[tool] || []).map((i) => ({
      value: i.env,
      label: i.version || i.guess || '',
    }));
  },

  /* ------------------------------------------------------------ palette */

  /* Every node already has a colour -- it is the one it wears on the canvas.
     Carrying it into the palette means the list you pick from and the graph you
     drop into read as the same thing, and a heading takes the colour of what is
     under it rather than being one more line of grey. */
  tint(el, colour) {
    if (colour) el.style.setProperty('--item-color', colour);
    return el;
  },

  /* What colour a heading takes: whatever most of its contents are. */
  dominant(colours) {
    const counts = new Map();
    for (const colour of colours.filter(Boolean)) {
      counts.set(colour, (counts.get(colour) || 0) + 1);
    }
    let best = '';
    let most = 0;
    for (const [colour, n] of counts) if (n > most) { best = colour; most = n; }
    return best;
  },

  buildPalette(categories) {
    const host = document.getElementById('palette-nodes');
    host.innerHTML = '';
    for (const category of categories) {
      // A hidden node is one something else does the job of now. It stays in
      // the catalogue -- a workflow that already uses it has to go on loading
      // and running -- but it is not offered here, and a category with nothing
      // left in it does not get a heading.
      const offered = category.nodes.filter((spec) => !spec.hidden);
      if (!offered.length) continue;
      host.appendChild(this.tint(
        UI.el('div', { class: 'cat-title', text: category.name }),
        this.dominant(offered.map((n) => n.color))));
      for (const spec of offered) {
        // Words the search box should find this block by, beyond its title:
        // the choices in its choice boxes ("RMSD" lives inside "Measure
        // something, frame by frame" now) and the names of the blocks that
        // were folded into it, so a name remembered from an older version
        // still lands on the right block. Kept out of sight; the search
        // reads the text of the whole item.
        const terms = [];
        for (const param of spec.params || []) {
          if (param.type === 'choice') terms.push(...(param.choices || []).map(String));
        }
        for (const other of category.nodes) {
          if (other.replaced_by && other.replaced_by.type === spec.type) {
            terms.push(other.title, other.type);
          }
        }
        const item = this.tint(UI.el('div', {
          class: 'palette-item', draggable: 'true',
          'data-type': spec.type, title: spec.description,
        }, [
          UI.el('span', { text: spec.title }),
          UI.el('span', { class: 'sub', text: spec.type }),
          UI.el('span', { class: 'search-terms hidden', text: terms.join(' ') }),
        ]), spec.color);
        item.addEventListener('click', () => {
          Editor.mark(`add ${spec.title}`);
          // With one node selected, the new one goes next to it and is wired
          // to it wherever an output and an input are plainly the same kind
          // of file. That is how a chain gets built: click a node, click the
          // next block. With nothing selected it lands in the middle of the
          // view as before.
          if (this.selectedNode && Editor.nodes.has(this.selectedNode)) {
            const placed = Editor.addAfter(this.selectedNode, spec.type);
            if (placed && placed.node) {
              Editor.select([placed.node.id]);
              if (placed.wired.length) {
                UI.toast('wired ' + placed.wired.map(
                  ([out, inp]) => `${out} \u2192 ${inp}`).join(', '), 'ok');
              }
            }
            return;
          }
          const centre = Editor.viewCenter();
          Editor.addNode(spec.type, centre.x - 118, centre.y - 40);
        });
        item.addEventListener('dragstart', (event) => {
          event.dataTransfer.setData('text/comfygmx-node', spec.type);
          event.dataTransfer.effectAllowed = 'copy';
        });
        host.appendChild(item);
      }
    }
  },

  buildChunkPalette() {
    const host = document.getElementById('palette-chunks');
    host.innerHTML = '';

    const builtin = this.chunks.filter((c) => !c.custom);
    const custom = this.chunks.filter((c) => c.custom);

    const byCategory = {};
    for (const chunk of builtin) {
      (byCategory[chunk.category] = byCategory[chunk.category] || []).push(chunk);
    }
    for (const [category, chunks] of Object.entries(byCategory)) {
      host.appendChild(this.tint(
        UI.el('div', { class: 'cat-title', text: category }),
        this.dominant(chunks.map((c) => this.chunkColour(c)))));
      for (const chunk of chunks) host.appendChild(this.chunkItem(chunk));
    }

    // The user's own chunks live under one heading of their own, with whatever
    // sub-headings they gave them. An empty section still says where they will
    // appear, which is the only way to discover the feature.
    host.appendChild(this.tint(
      UI.el('div', { class: 'cat-title section', text: 'Custom chunks' }),
      this.dominant(custom.map((c) => this.chunkColour(c))) || 'var(--ok)'));
    if (!custom.length) {
      host.appendChild(UI.el('div', {
        class: 'palette-hint inline',
        text: 'Select nodes, right-click, "Save selection as a chunk…".',
      }));
      return;
    }
    const bySection = {};
    for (const chunk of custom) {
      (bySection[chunk.category || ''] = bySection[chunk.category || ''] || []).push(chunk);
    }
    for (const section of Object.keys(bySection).sort()) {
      if (section) {
        host.appendChild(this.tint(
          UI.el('div', { class: 'cat-title sub', text: section }),
          this.dominant(bySection[section].map((c) => this.chunkColour(c)))));
      }
      for (const chunk of bySection[section]) host.appendChild(this.chunkItem(chunk));
    }
  },

  /* A chunk arrives inside coloured boxes; the palette shows the same colour,
     so what you picked and what landed match. */
  chunkColour(chunk) {
    const groups = (chunk.graph && chunk.graph.groups) || [];
    return this.dominant(groups.map((g) => g.color)) || '';
  },

  chunkItem(chunk) {
    const item = this.tint(UI.el('div', {
      class: `palette-item chunk${chunk.custom ? ' custom' : ''}`,
      draggable: 'true', 'data-chunk': chunk.id,
      title: chunk.custom ? `${chunk.description || chunk.name}\n\n${chunk.path}`
        : chunk.description,
    }, [
      UI.el('span', { text: chunk.name }),
      UI.el('span', { class: 'sub', text: chunk.description || `${chunk.graph.nodes.length} nodes` }),
    ]), this.chunkColour(chunk));
    item.addEventListener('click', () => {
      const centre = Editor.viewCenter();
      Editor.addChunk(chunk, centre.x - 200, centre.y - 100);
      UI.toast(`added "${chunk.name}"`, 'ok', 2500);
    });
    item.addEventListener('dragstart', (event) => {
      event.dataTransfer.setData('text/comfygmx-chunk', chunk.id);
      event.dataTransfer.effectAllowed = 'copy';
    });
    if (chunk.custom) {
      item.appendChild(UI.el('button', {
        class: 'chunk-delete', text: '×', title: 'Delete this chunk',
        onclick: async (event) => {
          event.stopPropagation();
          if (!confirm(`Delete the chunk "${chunk.name}"?`)) return;
          try {
            await API.deleteChunk(chunk.id);
            UI.toast(`deleted "${chunk.name}"`, 'ok');
            this.refreshChunks();
          } catch (err) { UI.toast(err.message, 'error', 9000); }
        },
      }));
    }
    return item;
  },

  async refreshChunks() {
    try {
      this.chunks = (await API.chunks()).chunks;
      this.buildChunkPalette();
    } catch (err) { UI.toast(err.message, 'error'); }
  },

  /* Wrap the selection in a coloured box. */
  groupSelection() {
    if (!Editor.selection.size) { UI.toast('select some nodes first', 'warn'); return; }
    const name = prompt('Group name', 'group');
    if (name === null) return;
    Editor.groupSelection(name.trim() || 'group');
  },

  /* Save a selection, or a group's contents, as a chunk of your own. */
  saveChunk(ids, group = null) {
    const graph = Editor.subgraph(ids || Editor.selected());
    if (!graph || !graph.nodes.length) {
      UI.toast('select some nodes first', 'warn');
      return;
    }
    Panels.saveChunk(graph, group ? { name: group.title } : {});
  },

  buildTutorialPalette() {
    const host = document.getElementById('palette-tutorials');
    host.innerHTML = '';
    if (!this.tutorials.length) {
      host.appendChild(UI.el('div', { class: 'palette-hint', text: 'no tutorials available' }));
      return;
    }
    // Grouped by collection: the published GROMACS set and the one made here
    // have different authors and different papers to cite, so they are never
    // one list.
    const collections = (this.tutorialMeta.collections
      || [{ id: 'gmx', label: 'mdtutorials.com/gmx' }]).slice();
    // A tutorial whose collection the server did not describe still has to be
    // reachable. Give it a heading of its own rather than dropping it on the
    // floor, which is how two finished tutorials once went missing from here.
    const described = new Set(collections.map((c) => c.id));
    for (const tutorial of this.tutorials) {
      const id = tutorial.collection || 'gmx';
      if (described.has(id)) continue;
      described.add(id);
      collections.push({ id, label: id });
    }
    for (const collection of collections) {
      const mine = this.tutorials.filter(
        (t) => (t.collection || 'gmx') === collection.id);
      if (!mine.length) continue;
      const colour = TUTORIAL_COLOURS[collection.id] || 'var(--accent)';
      host.appendChild(this.tint(
        UI.el('div', { class: 'cat-title', text: collection.label }), colour));
      for (const tutorial of mine) {
        const packaged = tutorial.status === 'packaged';
        const item = this.tint(UI.el('div', {
          class: `palette-item chunk${packaged ? '' : ' unpackaged'}`,
          title: tutorial.summary,
        }, [
          UI.el('span', {}, [
            `${tutorial.number}. ${tutorial.name} `,
            UI.el('span', {
              class: `badge ${packaged ? 'ok' : ''}`,
              text: packaged ? `${tutorial.nodes} nodes` : 'not packaged',
            }),
          ]),
          UI.el('span', { class: 'sub', text: tutorial.summary }),
        ]), packaged ? colour : 'var(--text-faint)');
        item.addEventListener('click', () => this.openTutorial(tutorial.id));
        // Draggable like a chunk, and for the same reason: the panel is worth
        // reading, but not every time you want the graph.
        if (packaged) {
          item.setAttribute('draggable', 'true');
          item.addEventListener('dragstart', (event) => {
            event.dataTransfer.setData('text/comfygmx-tutorial', tutorial.id);
            event.dataTransfer.effectAllowed = 'copy';
          });
        }
        host.appendChild(item);
      }
    }
    host.appendChild(UI.el('div', {
      class: 'palette-hint',
      text: 'Graphs are a translation of the published commands; read the tutorial '
          + 'itself for the reasoning. Each one names its author and its citation.',
    }));
  },

  async openTutorial(id) {
    let tutorial;
    try { tutorial = await API.tutorial(id); }
    catch (err) { UI.toast(err.message, 'error'); return; }

    const body = UI.el('div');
    body.appendChild(UI.el('p', { text: tutorial.summary }));
    body.appendChild(UI.el('p', { class: 'hint' }, [
      'Source: ',
      UI.el('a', { href: tutorial.source, target: '_blank', rel: 'noopener',
                   text: tutorial.source }),
      ` — ${tutorial.meta.author}`,
    ]));

    if (tutorial.requires && tutorial.requires.length) {
      body.appendChild(UI.el('h3', { text: 'What you need' }));
      const list = UI.el('ul');
      for (const item of tutorial.requires) list.appendChild(UI.el('li', { text: item }));
      body.appendChild(list);
    }

    /* Which tools it needs and whether they are here, read off the graph
       rather than off the prose beside it -- a hand-kept list drifts, and the
       node specs already say which tool each node drives.

       Broken down by group as well, because a tutorial can lay out
       alternative routes side by side, and somebody who wants one route
       should not be told to install the tools of the others. */
    if (tutorial.needs && (tutorial.needs.all || []).length) {
      const missing = tutorial.needs.all.filter((tool) => !tool.present);
      const head = UI.el('div', { class: 'row' }, [
        UI.el('h3', { text: 'Tools this graph drives' }),
        UI.el('span', { class: 'spacer' }),
        missing.length ? UI.el('button', {
          class: 'small primary',
          text: `Install the ${missing.length} missing`,
          title: missing.map((tool) => tool.name).join(', '),
          onclick: () => Panels.setup(false, missing.map((tool) => tool.id)),
        }) : null,
      ].filter(Boolean));
      body.appendChild(head);

      const pill = (tool) => UI.el('span', {
        class: `badge ${tool.present ? 'ok' : 'warn'}`,
        text: tool.name,
        title: tool.present ? `found: ${tool.where}` : 'not installed',
      });

      const all = UI.el('div', { class: 'row wrap' });
      for (const tool of tutorial.needs.all) all.appendChild(pill(tool));
      body.appendChild(all);

      // Only worth splitting up when the routes actually differ.
      const routes = (tutorial.needs.groups || []).filter((group) =>
        group.tools.some((tool) => !tool.present));
      const varied = new Set((tutorial.needs.groups || [])
        .map((group) => group.tools.map((tool) => tool.id).join(','))).size > 1;
      if (routes.length && varied) {
        const table = UI.el('table');
        for (const group of tutorial.needs.groups) {
          const row = UI.el('div', { class: 'row wrap' });
          for (const tool of group.tools) row.appendChild(pill(tool));
          table.appendChild(UI.el('tr', {}, [
            UI.el('td', { text: group.title }),
            UI.el('td', {}, [row]),
          ]));
        }
        body.appendChild(UI.el('p', { class: 'hint', text:
          'Each row is independent: a tool you have not got costs you that row, '
          + 'not the tutorial.' }));
        body.appendChild(table);
      }
    }
    if (tutorial.runtime) {
      body.appendChild(UI.el('p', { class: 'hint', text: `Runtime: ${tutorial.runtime}` }));
    }
    if (tutorial.notes) {
      body.appendChild(UI.el('h3', {
        text: tutorial.status === 'packaged' ? 'Worth knowing' : 'Why it is not packaged yet',
      }));
      for (const part of UI.prose(tutorial.notes)) body.appendChild(part);
    }

    /* What the graph produced when somebody sat and ran it. Written down for
       every packaged tutorial and, until now, shown nowhere -- which is a
       waste, because the first thing you want when your own run finishes is
       something to compare it against. If your ion count or your density is
       nowhere near these, something went differently and it is worth finding
       out what before carrying on. */
    if (tutorial.measured) {
      body.appendChild(UI.el('h3', { text: 'What it came out as here' }));
      for (const part of UI.prose(tutorial.measured)) body.appendChild(part);
      body.appendChild(UI.el('p', { class: 'hint', text:
        'One computer, one run each. Your numbers will not match to the last '
        + 'digit — no two computers do the arithmetic in quite the same way, and '
        + 'some steps pick things at random — but they should land close.' }));
    }

    if (tutorial.steps && tutorial.steps.length) {
      body.appendChild(UI.el('h3', { text: 'Steps' }));
      const table = UI.el('table');
      for (const step of tutorial.steps) {
        const focus = UI.el('button', {
          class: 'small', text: 'show',
          title: 'select the nodes for this step on the canvas',
          onclick: () => this.focusNodes(step.nodes),
        });
        table.appendChild(UI.el('tr', {}, [
          UI.el('th', {}, [
            UI.el('a', {
              href: (tutorial.base || tutorial.source) + (step.page || ''),
              target: '_blank', rel: 'noopener',
              text: step.title,
            }),
          ]),
          UI.el('td', { class: 'muted', text: step.summary }),
          UI.el('td', {}, [focus]),
        ]));
      }
      body.appendChild(table);
      body.appendChild(UI.el('p', {
        class: 'hint',
        text: '"show" selects that step\'s nodes on the canvas — it works once the '
            + 'tutorial has been loaded.',
      }));
    }

    body.appendChild(UI.el('h3', { text: 'Citation' }));
    body.appendChild(UI.el('p', { class: 'hint', text: tutorial.meta.citation }));

    const buttons = [{ label: 'Close' }];
    if (tutorial.graph) {
      buttons.unshift({
        label: 'Add to canvas',
        action: () => {
          const centre = Editor.viewCenter();
          Editor.mark(`add ${tutorial.name}`);
          Editor.addChunk(tutorial, centre.x - 300, centre.y - 200);
          UI.toast(`added "${tutorial.name}"`, 'ok');
        },
      });
      buttons.unshift({
        label: 'Load as new graph',
        primary: true,
        action: () => {
          if (Editor.nodes.size && !confirm('Replace the current graph?')) return false;
          Editor.mark(`load ${tutorial.name}`);
          Editor.clear();
          Editor.addChunk(tutorial, 0, 0, true);
          Editor.select([]);
          setTimeout(() => Editor.fit(), 60);
          this.workflowName = `tutorial-${tutorial.id}`;
          UI.toast(`loaded "${tutorial.name}" — read the note nodes as you go`, 'ok', 7000);
        },
      });
    }
    UI.modal(`Tutorial ${tutorial.number}: ${tutorial.name}`, body, buttons);
  },

  filterPalette(query) {
    const needle = query.trim().toLowerCase();
    const TABS = { 'palette-nodes': 'Nodes', 'palette-chunks': 'Chunks',
                   'palette-tutorials': 'Tutorials' };
    const found = {};
    for (const host of Object.keys(TABS)) {
      const container = document.getElementById(host);
      let visibleInCategory = 0;
      let lastTitle = null;
      let total = 0;
      for (const child of container.children) {
        if (child.classList.contains('palette-empty')) continue;
        if (child.classList.contains('cat-title')) {
          if (lastTitle) lastTitle.classList.toggle('hidden', visibleInCategory === 0);
          lastTitle = child;
          visibleInCategory = 0;
          continue;
        }
        const text = child.textContent.toLowerCase();
        const match = !needle || text.includes(needle);
        child.classList.toggle('hidden', !match);
        if (match) { visibleInCategory += 1; total += 1; }
      }
      if (lastTitle) lastTitle.classList.toggle('hidden', visibleInCategory === 0);
      found[host] = total;
    }
    // Say so when a tab has gone blank, and say where the matches did land.
    // Searching from the Tutorials tab used to empty the list with no word of
    // explanation, which reads as "there is nothing called that anywhere".
    for (const [host, label] of Object.entries(TABS)) {
      const container = document.getElementById(host);
      let note = container.querySelector('.palette-empty');
      if (needle && found[host] === 0) {
        if (!note) {
          note = document.createElement('div');
          note.className = 'palette-empty';
          container.appendChild(note);
        }
        const elsewhere = Object.entries(TABS)
          .filter(([other]) => other !== host && found[other] > 0)
          .map(([other, name]) => `${found[other]} under ${name}`);
        note.textContent = `Nothing under ${label} matches "${query.trim()}".`
          + (elsewhere.length ? ` There is ${elsewhere.join(', ')}.` : '');
      } else if (note) {
        note.remove();
      }
    }
  },

  /* ---------------------------------------------------------- UI events */
  bindUI() {
    document.getElementById('palette-search').addEventListener('input', (event) => {
      this.filterPalette(event.target.value);
    });

    for (const tabs of ['palette-tabs', 'inspector-tabs']) {
      document.getElementById(tabs).addEventListener('click', (event) => {
        const tab = event.target.closest('.tab');
        if (!tab) return;
        const container = document.getElementById(tabs);
        for (const other of container.querySelectorAll('.tab')) {
          other.classList.toggle('active', other === tab);
        }
        if (tabs === 'palette-tabs') {
          for (const name of ['nodes', 'chunks', 'tutorials']) {
            document.getElementById(`palette-${name}`)
              .classList.toggle('hidden', tab.dataset.tab !== name);
          }
        } else {
          for (const name of ['log', 'problems', 'command', 'files', 'viewer', 'plot']) {
            document.getElementById(`tab-${name}`).classList.toggle('hidden', name !== tab.dataset.tab);
          }
          if (tab.dataset.tab === 'command') this.showCommand(this.selectedNode);
          if (tab.dataset.tab === 'viewer') this.viewSelectedPreview();
          if (tab.dataset.tab === 'files') this.refreshFiles();
          if (tab.dataset.tab === 'viewer') Viewer.draw();
          if (tab.dataset.tab === 'plot') Plot.draw();
        }
      });
    }

    document.getElementById('btn-run').addEventListener('click', () => this.run());
    document.getElementById('btn-run-selected').addEventListener('click', () => {
      const selected = Editor.selected();
      if (!selected.length) { UI.toast('nothing selected', 'warn'); return; }
      this.run(selected);
    });
    document.getElementById('btn-cancel').addEventListener('click', () => this.cancel());
    document.getElementById('btn-continue').addEventListener('click', () => this.resume());
    document.getElementById('btn-undo').addEventListener('click', () => this.undo());
    document.getElementById('btn-redo').addEventListener('click', () => this.redo());
    document.getElementById('btn-validate').addEventListener('click', () => this.check(true));
    document.getElementById('btn-save').addEventListener('click', async () =>
      Panels.saveWorkflow(this.workflowName, await this.stamped()));
    document.getElementById('btn-load').addEventListener('click', () =>
      Panels.openWorkflow((name, graph) => {
        this.adoptWorkflow(name, graph);
        UI.toast(`opened ${name}`, 'ok');
      }));
    document.getElementById('btn-export').addEventListener('click', () => this.exportJson());
    document.getElementById('btn-export-scripts')
      .addEventListener('click', () => Panels.exportScripts());
    document.getElementById('btn-import').addEventListener('click', () => this.importJson());
    document.getElementById('btn-clear').addEventListener('click', () => {
      if (Editor.nodes.size && !confirm('Discard the graph in this session?')) return;
      Editor.mark('new graph');
      Editor.clear();
      this.workflowName = 'untitled';
    });
    document.getElementById('btn-session-new').addEventListener('click',
      () => Sessions.add('untitled'));
    document.getElementById('session-output').addEventListener('click',
      () => this.chooseOutputDir());
    document.getElementById('btn-open-folder').addEventListener('click',
      () => this.openWorkFolder());
    document.getElementById('btn-setup').addEventListener('click', () => Panels.setup(false));
    document.getElementById('btn-env').addEventListener('click', () => Panels.environments());
    document.getElementById('btn-settings').addEventListener('click', () => Panels.settings());
    document.getElementById('btn-help').addEventListener('click', () => Panels.help());
    document.getElementById('btn-fit').addEventListener('click', () => Editor.fit());
    document.getElementById('btn-tidy').addEventListener('click', () => {
      const moved = Editor.tidy();
      UI.toast(moved ? `moved ${moved} node(s) apart` : 'nothing overlaps', 'ok');
    });
    document.getElementById('btn-reset-zoom').addEventListener('click', () => {
      Editor.view.scale = 1;
      Editor.applyView();
    });
    document.getElementById('btn-copy-command').addEventListener('click', () => {
      UI.copy(document.getElementById('command-output').textContent);
    });
    document.getElementById('btn-recheck').addEventListener('click', () => this.check(true));
    document.getElementById('status-problems').addEventListener('click', () => this.showTab('problems'));
    document.getElementById('btn-plot-csv').addEventListener('click', () => UI.copy(Plot.asCsv()));

    this.bindDrops();

    document.addEventListener('keydown', (event) => this.onKey(event));
    window.addEventListener('beforeunload', (event) => {
      this.persist();
      // Runs survive the page; the warning is so a reload is deliberate. The
      // same for a program running in the Shell tab: it outlives the page
      // for a minute, but Ctrl+W, which closes a browser tab, is also nano's
      // key for searching.
      if (Sessions.running().length || ShellTab.busy()) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
    setInterval(() => this.persist(), 15000);

    // Online (mybinder.org and the like), a session is shut down after ten
    // minutes in which the server hears nothing -- and reading the notes on
    // the canvas asks it for nothing. So while somebody is using the page --
    // moving the mouse, typing, scrolling -- the page says so, at most once
    // every two minutes. A tab left open with nobody at it goes quiet, and the
    // session still ends when the site means it to.
    let heardFrom = 0;
    const stillHere = () => {
      const now = Date.now();
      if (now - heardFrom < 120000) return;
      heardFrom = now;
      API.info().catch(() => {});
    };
    for (const kind of ['pointermove', 'keydown', 'wheel', 'touchstart']) {
      window.addEventListener(kind, stillHere, { passive: true });
    }

    // Coming back to the window is the moment to check rather than assume.
    // A tab left alone for hours can miss the end of a run entirely: the
    // machine slept, or the connection went and nobody was watching. Asking
    // here costs one small request and is the difference between seeing what
    // happened and staring at a block that stopped working overnight.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState !== 'visible') return;
      for (const session of Sessions.list) {
        if (!session.run) continue;
        if (['done', 'error', 'cancelled'].includes(session.run.status)) continue;
        this.reconcile(session, 3, 400);
      }
    });
  },

  onKey(event) {
    const inField = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);
    if (event.key === 'Escape') {
      UI.closeModal();
      const finding = !document.getElementById('canvas-find').classList.contains('hidden');
      if (finding) { this.find.close(); return; }
      if (!inField) Editor.select([]);
      return;
    }
    // A dialog is in front of the graph, so the keys belong to it. The guard
    // below only asks whether the cursor is in a text box, which is false the
    // moment somebody clicks a button or a line of explanation inside a
    // dialog -- and then Ctrl+Z rebuilt the graph under an open form, Delete
    // removed the node the form was filling in, and Ctrl+O replaced the form
    // with the open-workflow dialog. In every case the typing was lost with no
    // way back, because a form is not saved anywhere until it is applied.
    // Escape above is the one key that still means something here.
    if (UI.anyDialogOpen()) return;
    if (inField) return;

    if (event.ctrlKey || event.metaKey) {
      if (event.key === 'Tab') {
        event.preventDefault();
        const index = Sessions.list.findIndex((s) => s.id === Sessions.activeId);
        const step = event.shiftKey ? -1 : 1;
        const next = (index + step + Sessions.list.length) % Sessions.list.length;
        Sessions.switchTo(Sessions.list[next].id);
        return;
      }
      switch (event.key.toLowerCase()) {
        case 'f':
          event.preventDefault();
          this.find.open();
          return;
        case 'z':
          event.preventDefault();
          if (event.shiftKey) this.redo(); else this.undo();
          return;
        case 'y':
          event.preventDefault();
          this.redo();
          return;
        case 'n':
          if (!event.shiftKey) return;
          event.preventDefault();
          Sessions.add('untitled');
          return;
        case 'enter':
          event.preventDefault();
          if (event.shiftKey) this.run(Editor.selected()); else this.run();
          return;
        case 's':
          event.preventDefault();
          this.stamped().then((graph) => Panels.saveWorkflow(this.workflowName, graph));
          return;
        case 'o':
          event.preventDefault();
          Panels.openWorkflow((name, graph) => this.adoptWorkflow(name, graph));
          return;
        case 'd':
          event.preventDefault();
          Editor.duplicateSelection();
          return;
        case 'g':
          event.preventDefault();
          this.groupSelection();
          return;
        case 'm':
          // Switch the selection off, or back on. Clicking a box's title bar
          // selects everything in it, so this does whole chunks too. M for
          // mute, as in ComfyUI.
          event.preventDefault();
          Editor.toggleOff(Editor.selected());
          return;
        case 'c':
          this.clipboard = Editor.selected().map((id) => {
            const node = Editor.nodes.get(id);
            return { type: node.type, pos: node.pos, params: node.params };
          });
          return;
        case 'v':
          this.paste(Editor.viewCenter());
          return;
        case 'a':
          event.preventDefault();
          Editor.select([...Editor.nodes.keys()]);
          return;
        default:
          return;
      }
    }
    if ((event.ctrlKey || event.metaKey) && (event.key === '`' || event.key === '~')) {
      event.preventDefault();
      Terminal.toggle();
      return;
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      const doomed = Editor.selected();
      // Clicking a group's title bar selects the box as well as its contents,
      // so Delete takes the box with them. Removing only the nodes left an
      // empty coloured rectangle that could only be got rid of by menu.
      const boxes = Editor.selectedGroupIds();
      if (!doomed.length && !boxes.length) return;
      const what = [
        doomed.length ? `${doomed.length} node${doomed.length === 1 ? '' : 's'}` : '',
        boxes.length ? `${boxes.length} group${boxes.length === 1 ? '' : 's'}` : '',
      ].filter(Boolean).join(' and ');
      Editor.mark(`delete ${what}`);
      for (const id of doomed) Editor.removeNode(id);
      for (const id of boxes) Editor.removeGroup(id);
    } else if (event.key === 't' || event.key === 'T') {
      const moved = Editor.tidy();
      UI.toast(moved ? `moved ${moved} node(s) apart` : 'nothing overlaps', 'ok');
    } else if (event.key === 'f' || event.key === 'F') {
      Editor.fit();
    }
  },

  /* ------------------------------------------------------------- finding */
  /* Ctrl+F over the graph. The palette search finds node *types*; this finds
     the nodes you actually have, including by the values in them -- "which
     node points at that tpr" is not a question you can answer by eye at fifty
     nodes and it is not a question about titles. */
  find: {
    hits: [],
    at: -1,

    open() {
      const box = document.getElementById('canvas-find');
      box.classList.remove('hidden');
      const input = document.getElementById('find-input');
      input.focus();
      input.select();
      this.run(input.value);
    },

    close() {
      document.getElementById('canvas-find').classList.add('hidden');
      Editor.markFound([]);
      this.hits = [];
      this.at = -1;
    },

    run(query) {
      this.hits = Editor.search(query);
      this.at = this.hits.length ? 0 : -1;
      Editor.markFound(this.hits.map((node) => node.id));
      this.paint();
      if (this.hits.length) this.show();
    },

    step(delta) {
      if (!this.hits.length) return;
      this.at = (this.at + delta + this.hits.length) % this.hits.length;
      this.paint();
      this.show();
    },

    /* Centre it and select it, so the inspector follows along -- finding a
       node is nearly always the first half of doing something to it. */
    show() {
      const node = this.hits[this.at];
      if (!node || !Editor.nodes.has(node.id)) return;
      Editor.centreOn(node);
      Editor.select([node.id]);
    },

    paint() {
      document.getElementById('find-count').textContent = this.hits.length
        ? `${this.at + 1}/${this.hits.length}` : '0';
    },
  },

  bindFind() {
    const input = document.getElementById('find-input');
    input.addEventListener('input', () => this.find.run(input.value));
    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') {
        event.preventDefault();
        this.find.step(event.shiftKey ? -1 : 1);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        this.find.close();
      }
    });
    document.getElementById('find-next').addEventListener('click', () => this.find.step(1));
    document.getElementById('find-prev').addEventListener('click', () => this.find.step(-1));
    document.getElementById('find-close').addEventListener('click', () => this.find.close());
  },

  paste(origin) {
    if (!this.clipboard || !this.clipboard.length) return;
    Editor.mark(`paste ${this.clipboard.length} node(s)`);
    const minX = Math.min(...this.clipboard.map((n) => n.pos[0]));
    const minY = Math.min(...this.clipboard.map((n) => n.pos[1]));
    const made = [];
    for (const node of this.clipboard) {
      const created = Editor.addNode(node.type,
        origin.x + node.pos[0] - minX, origin.y + node.pos[1] - minY,
        JSON.parse(JSON.stringify(node.params)));
      if (created) made.push(created.id);
    }
    Editor.select(made);
  },

  /* -------------------------------------------------------- persistence */
  persist() {
    Sessions.persist();
  },

  restore() {
    Sessions.onSwitch = (session) => this.onSessionSwitch(session);
    Editor.onRestore = () => Sessions.repaint(Sessions.active());
    const { migrated } = Sessions.restore();
    const active = Sessions.active();
    Editor.fromJSON(active.graph);
    Editor.resetHistory();
    Sessions.repaint(active);
    Sessions.render();
    if (Editor.nodes.size) {
      UI.toast(migrated ? 'restored your last graph' : 'restored your sessions',
               'info', 2600);
    } else if (Sessions.list.length === 1) {
      this.starterGraph();
    }
    this.onSessionSwitch(active);
    // A run that was still going when the page was closed is still going now.
    for (const session of Sessions.list) {
      if (session.pendingRun) this.reattach(session, session.pendingRun);
      session.pendingRun = null;
    }
  },

  /* Re-read the block catalogue and redraw the blocks that changed.

     Most of what the catalogue holds is fixed, but not all of it: the
     Topology block's list of force fields is read off the disk when the
     catalogue is asked for. Fetch one and the browser's copy is a moment out
     of date, and the box would go on offering the old set until a reload. */
  async refreshNodeDefs() {
    let catalogue;
    try {
      catalogue = await API.nodes();
    } catch (err) {
      return;
    }
    const changed = [];
    for (const category of catalogue.categories || []) {
      for (const spec of category.nodes) {
        const before = JSON.stringify((this.defs[spec.type] || {}).params || []);
        this.defs[spec.type] = spec;
        if (JSON.stringify(spec.params || []) !== before) changed.push(spec.type);
      }
    }
    Editor.defs = this.defs;
    for (const type of changed) Editor.refreshOpenNodes(type);
    return changed;
  },

  /* Repaint everything the active session owns. */
  onSessionSwitch(session) {
    if (!session) return;
    const running = !!(session.run && session.run.status === 'running');
    this.setRunning(running);
    const pill = document.getElementById('run-status');
    pill.textContent = session.run ? session.run.status : 'idle';
    pill.className = `status-pill ${session.run
      ? (session.run.status === 'running' ? 'running' : session.run.status) : ''}`;
    document.getElementById('status-run').textContent =
      session.run ? `run ${session.run.id}` : '';

    const output = document.getElementById('log-output');
    output.innerHTML = '';
    if (session.run && session.run.lines.length) {
      for (const line of session.run.lines) this.appendLog(output, line);
      output.scrollTop = output.scrollHeight;
    }
    Terminal.repaint(session);
    Terminal.status(this._terminalStatus(session), running);
    this.logNode = session.run ? session.run.logNode : null;
    this.logPinned = session.run ? session.run.logPinned : false;
    document.getElementById('log-title').textContent = this.logNode
      ? `${(Editor.nodes.get(this.logNode) || {}).title || this.logNode}`
      : 'no node selected';
    this.refreshFiles();
    this.schedulePlan();
  },

  /* Reconnect to a run that outlived the page. */
  async reattach(session, runId) {
    let detail;
    try {
      detail = await API.runDetail(runId, false);
    } catch (err) {
      // The session was saved mid-run and the server has been restarted since,
      // so that run no longer exists. Leaving the tab as it was saved means a
      // spinner that never stops on a run that ended when the process did.
      if (session.run) this.onRunStatus(session, 'error');
      else { session.pendingRun = null; Sessions.render(); }
      return;
    }
    Sessions.beginRun(session, runId, detail.order || [], detail.workdir || '');
    session.run.status = detail.status;
    for (const [nodeId, state] of Object.entries(detail.nodes || {})) {
      session.run.statuses[nodeId] = { status: state.status, error: state.error || '' };
      const shown = this.previewPathFor(session, nodeId, state.outputs || {});
      if (shown) Sessions.notePreview(session, nodeId, shown);
    }
    if (session.id === Sessions.activeId) this.onSessionSwitch(session);
    Sessions.render();
    if (detail.status === 'running') this.watch(session);
    UI.toast(`reattached to run ${runId} (${session.name})`, 'info', 6000);
  },

  starterGraph() {
    const chunk = this.chunks.find((c) => c.id === 'prep_clean');
    if (chunk) Editor.addChunk(chunk, 80, 120);
  },

  /* The graph, plus a note of which version of each program it was built
     against. Somebody opening it on another machine can then be offered the
     same versions rather than whatever is newest today -- which is not the
     same simulation. Written only on the way out; it costs a version check per
     tool, and that is a second or two each. */
  async stamped() {
    const graph = Editor.toJSON();
    try {
      const report = await API.graphTools(graph, {}, true);
      if (report && report.stamp && Object.keys(report.stamp).length) {
        graph.tools = report.stamp;
      }
    } catch (err) {
      // A workflow without the note is still a workflow. Saving must not fail
      // because a version check did.
    }
    return graph;
  },

  /* A workflow arriving from somewhere: a file, or one saved earlier. Puts it
     in the editor and then asks whether this machine can actually run it. */
  adoptWorkflow(name, data, said) {
    Editor.mark(said || `open ${name}`);
    Editor.fromJSON(data);
    this.workflowName = name;
    this.checkWorkflowTools(data.tools || {});
  },

  /* Does this machine have what the workflow needs? Asked once, when one
     arrives, because the alternative is finding out halfway through a run. */
  async checkWorkflowTools(recorded) {
    let report;
    try {
      report = await API.graphTools(Editor.toJSON(), recorded || {}, false);
    } catch (err) {
      return;
    }
    const missing = (report.tools || []).filter((tool) => !tool.present);
    if (!missing.length) return;
    Panels.workflowTools(missing);
  },

  async exportJson() {
    const blob = new Blob([JSON.stringify(await this.stamped(), null, 2)],
                          { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = UI.el('a', { href: url, download: `${this.workflowName || 'workflow'}.json` });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  importJson() {
    const input = UI.el('input', { type: 'file', accept: '.json' });
    input.addEventListener('change', () => {
      const file = input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const data = JSON.parse(reader.result);
          this.adoptWorkflow(file.name.replace(/\.json$/, ''), data,
                             `import ${file.name}`);
          UI.toast(`imported ${file.name}`, 'ok');
        } catch (err) { UI.toast(`not a valid workflow: ${err.message}`, 'error'); }
      };
      reader.readAsText(file);
    });
    input.click();
  },

  /* ------------------------------------------------------------ planning */
  schedulePlan() {
    clearTimeout(this._planTimer);
    this._planTimer = setTimeout(() => this.check(false), 500);
  },

  async check(verbose) {
    if (!Editor.nodes.size) {
      Editor.markProblems([]);
      this.renderProblems([], 0);
      // An empty graph has no forecast, and leaving the last one up is a line
      // describing a graph that is not there any more.
      this.applyForecast(null);
      if (verbose) UI.toast('the graph is empty', 'info');
      return;
    }
    try {
      const result = await API.plan(Editor.toJSON());

      // Two sources say something is wrong and they used to be handled
      // separately: the structural check (a required port with nothing in it)
      // and the node's own planner (a parameter it cannot use). Both belong in
      // one list, or half the failures never get highlighted.
      const problems = [...(result.problems || [])];
      for (const [nodeId, entry] of Object.entries(result.plans || {})) {
        const node = Editor.nodes.get(nodeId);
        if (node) {
          node.notes = entry.notes || [];
          node.error = '';
        }
        if (entry.error) {
          // The structural check has already reported every required input this
          // node is missing, and it names the port by its label where the
          // planner names it by its id -- "conf" against "structure" for the
          // same wire. Comparing the text cannot match those, so drop the
          // planner's version whenever the node is already known to be missing
          // an input.
          const missing = /^input '.*' is not connected$/.test(entry.error);
          const known = problems.some(
            (p) => p.node === nodeId && / is not connected$/.test(p.message));
          if (!(missing && known)) {
            problems.push({ node: nodeId, level: 'error', message: entry.error });
          }
        }
      }
      this.lastProblems = problems;
      // Before the problems are marked: marking redraws every block, and a
      // block left out because something before it is switched off should be
      // drawn that way in the same pass.
      Editor.markLeftOut(result.left_out || {});
      // Causes get the red border; nodes broken only because something
      // upstream is broken get the softer one, so the picture on the canvas
      // says the same thing the list does.
      Editor.markProblems(problems, this.problemCauses(problems));

      const errors = problems.filter((p) => p.level === 'error');
      this.renderProblems(problems, (result.order || []).length);
      if (verbose) {
        if (errors.length) {
          const count = document.getElementById('problems-badge').textContent;
          UI.toast(`${count} node(s) to fix — listed in the Problems tab, `
                   + 'click one to jump to it', 'warn', 8000);
          this.showTab('problems');
        } else if (problems.length) {
          UI.toast(`runnable, with ${problems.length} warning(s)`, 'ok', 5000);
          this.showTab('problems');
        } else {
          UI.toast(`graph is runnable: ${result.order.length} nodes`, 'ok');
        }
      }
      this.applyForecast(result.forecast, result.left_out || {});
      UI.status(errors.length
        ? `${errors.length} problem(s)`
        : `${result.order.length} nodes ready`);
      if (this.selectedNode) this.showCommand(this.selectedNode, true);
    } catch (err) {
      UI.status(err.message);
      if (verbose) UI.toast(err.message, 'error');
    }
  },

  /* What Run would actually do, said before it is pressed.

     Check answers "is it broken". It has never answered "is it expensive",
     and a fifty-node graph where three nodes will run looks exactly like one
     where fifty will. The difference is an afternoon. */
  applyForecast(forecast, leftOut = {}) {
    this.forecast = forecast || null;
    const line = document.getElementById('forecast-line');
    // Said on the same line as what will run, because it is the other half of
    // the same answer: a switched-off block left in and forgotten about is a
    // result missing at the end of the day.
    const ids = Object.keys(leftOut);
    const off = ids.filter((id) => !leftOut[id].because).length;
    const needing = ids.length - off;
    const leftOutText = [
      off ? `${off} switched off` : '',
      needing ? `${needing} more left out that depend on ${off === 1 ? 'it' : 'them'}` : '',
    ].filter(Boolean).join(', ');
    if (!forecast || forecast.error || !forecast.total) {
      Editor.markCached([]);
      line.textContent = leftOutText ? `nothing will run · ${leftOutText}` : '';
      line.classList.toggle('hidden', !leftOutText);
      return;
    }
    Editor.markCached(forecast.nodes.filter((n) => n.cached).map((n) => n.node));
    line.classList.remove('hidden');
    if (!forecast.will_run) {
      line.textContent = `nothing to do — all ${forecast.total} nodes are cached`;
    } else {
      const parts = [`${forecast.will_run} of ${forecast.total} will run`];
      if (forecast.cached) parts.push(`${forecast.cached} reused`);
      // An estimate is only offered where there is something to base it on,
      // and it says how much of the graph it could not account for rather
      // than quietly leaving it out of the total.
      if (forecast.seconds >= 1) {
        parts.push(`about ${UI.duration(forecast.seconds)}`
          + (forecast.unknown ? ` plus ${forecast.unknown} never timed here` : ''));
      } else if (forecast.unknown) {
        parts.push(`${forecast.unknown} never run here, so no estimate`);
      }
      line.textContent = parts.join(' · ');
    }
    if (leftOutText) line.textContent += ` · ${leftOutText}`;
    const run = document.getElementById('btn-run');
    run.title = forecast.will_run
      ? `Run — ${line.textContent}`
      : 'Run — every node is cached; nothing would be recomputed';
  },

  /* Switch the inspector to a tab from code, keeping the tab strip in step. */
  showTab(name) {
    const strip = document.getElementById('inspector-tabs');
    for (const tab of strip.querySelectorAll('.tab')) {
      tab.classList.toggle('active', tab.dataset.tab === name);
    }
    for (const other of ['log', 'problems', 'command', 'files', 'viewer', 'plot']) {
      document.getElementById(`tab-${other}`).classList.toggle('hidden', other !== name);
    }
  },

  /* The findings, as a list you can click. A highlighted border is no help in
     a graph of seventy nodes at half zoom -- you have to be able to get to the
     node that is complaining. */
  renderProblems(problems, ready) {
    const host = document.getElementById('problems-list');
    const title = document.getElementById('problems-title');
    const badge = document.getElementById('problems-badge');
    const pill = document.getElementById('status-problems');
    host.innerHTML = '';

    const errors = problems.filter((p) => p.level === 'error');
    const setCount = (n, bad) => {
      badge.textContent = String(n);
      badge.classList.toggle('hidden', !n);
      badge.classList.toggle('bad', bad);
      pill.textContent = n ? (bad ? `${n} node(s) to fix` : `${n} warning(s)`) : '';
      pill.classList.toggle('hidden', !n);
      pill.classList.toggle('bad', bad);
    };

    if (!problems.length) {
      setCount(0, false);
      title.textContent = ready ? `${ready} nodes ready` : 'nothing to check';
      host.appendChild(UI.el('div', {
        class: 'problem-none',
        text: ready ? 'No problems. Every node can plan its commands.'
                    : 'Add some nodes, then press Check.',
      }));
      return;
    }
    const warnings = problems.length - errors.length;

    // Group by node so a node missing three inputs is one row, not three.
    const byNode = new Map();
    for (const problem of problems) {
      const key = problem.node || '';
      if (!byNode.has(key)) byNode.set(key, []);
      byNode.get(key).push(problem);
    }

    const causes = this.problemCauses(problems);
    const keys = [...byNode.keys()]
      .filter((key) => causes.has(key))
      // Graph-level findings first -- a cycle belongs to no single node.
      .sort((a, b) => (a ? 1 : 0) - (b ? 1 : 0));

    setCount(keys.length, !!errors.length);
    title.textContent = keys.length === 1
      ? '1 node to fix'
      : `${keys.length} nodes to fix`;
    if (warnings) title.textContent += `, ${warnings} warning(s)`;

    for (const key of keys) {
      const entries = byNode.get(key);
      const node = key ? Editor.nodes.get(key) : null;
      const worst = entries.some((p) => p.level === 'error') ? 'error' : 'warning';
      const rows = entries.map((p) => UI.el('div', {
        class: `problem-msg ${p.level}`, text: p.message,
      }));
      const row = UI.el('div', { class: `problem ${worst}` }, [
        UI.el('div', { class: 'problem-head' }, [
          UI.el('span', { class: 'problem-node',
                          text: node ? node.title : (key || 'the graph') }),
          node ? UI.el('span', { class: 'problem-type', text: `${key} · ${node.type}` }) : null,
          node ? UI.el('button', {
            class: 'small', text: 'show',
            title: 'select it and bring it into view',
            onclick: (event) => { event.stopPropagation(); this.focusNodes([key]); },
          }) : null,
        ]),
        ...rows,
      ]);
      if (node) row.addEventListener('click', () => this.focusNodes([key]));
      host.appendChild(row);
    }

    // Everything downstream of a cause -- including the consequences that were
    // just filtered out of the list -- is waiting on a fix rather than broken
    // itself. Saying how many there are keeps "3 problems" from reading as
    // "three nodes will not run".
    const blocked = this.blockedBy(keys.filter(Boolean));
    if (blocked.length) {
      const summary = UI.el('div', { class: 'problem-blocked' }, [
        UI.el('span', {
          text: `${blocked.length} more node(s) downstream cannot run until `
              + 'these are fixed.',
        }),
        UI.el('button', {
          class: 'small', text: 'show',
          onclick: () => this.focusNodes(blocked),
        }),
      ]);
      host.appendChild(summary);
    }
  },

  /* Which of the complaining nodes are worth showing.

     A node fed by a node that is already broken is a consequence, not a
     finding: it says "input 'tpr' is not connected" only because the grompp
     above it could not produce one. Listing both is how three untied wires
     become nine rows and you cannot tell which three to fix. */
  problemCauses(problems) {
    const broken = new Set((problems || []).map((p) => p.node).filter(Boolean));
    const causes = new Set();
    for (const problem of problems || []) {
      const id = problem.node || '';
      if (!id) { causes.add(''); continue; }   // a cycle belongs to no node
      const fedByBroken = Editor.links.some(
        (l) => l.to_node === id && broken.has(l.from_node));
      if (!fedByBroken) causes.add(id);
    }
    return causes;
  },

  /* Everything reachable from the given nodes, excluding themselves. */
  blockedBy(roots) {
    const out = new Set();
    const queue = [...roots];
    while (queue.length) {
      const current = queue.shift();
      for (const link of Editor.links) {
        if (link.from_node !== current || out.has(link.to_node)) continue;
        if (roots.includes(link.to_node)) continue;
        out.add(link.to_node);
        queue.push(link.to_node);
      }
    }
    return [...out];
  },

  /* The Viewer tab shows what the selected node is already drawing.

     A preview node draws its structure inside itself, and the Viewer tab
     used to say "no structure loaded" beside it -- true in a narrow sense
     and unhelpful. Opening the tab with such a node selected puts the same
     structure in the big view, which is what somebody clicking it wants. */
  viewSelectedPreview() {
    const node = Editor.nodes.get(this.selectedNode);
    if (!node || !node.previewData) return;
    const kind = ((Editor.defs[node.type] || {}).preview || {}).kind;
    if (kind !== 'structure') return;
    Viewer.show(node.previewData, NodePreview.source(node));
  },

  /* -------------------------------------------------------- undo/redo */
  undo() {
    const label = Editor.undoLabel();
    if (!Editor.undo()) { UI.toast('nothing to undo', 'info', 2000); return; }
    UI.toast(`undid ${label}`, 'info', 2500);
  },

  redo() {
    const label = Editor.redoLabel();
    if (!Editor.redo()) { UI.toast('nothing to redo', 'info', 2000); return; }
    UI.toast(`redid ${label}`, 'info', 2500);
  },

  refreshHistoryButtons() {
    const undo = document.getElementById('btn-undo');
    const redo = document.getElementById('btn-redo');
    if (!undo || !redo) return;
    undo.disabled = !Editor.canUndo();
    redo.disabled = !Editor.canRedo();
    undo.title = Editor.canUndo() ? `Undo ${Editor.undoLabel()} (Ctrl+Z)` : 'Nothing to undo';
    redo.title = Editor.canRedo() ? `Redo ${Editor.redoLabel()} (Ctrl+Shift+Z)` : 'Nothing to redo';
  },

  /* --------------------------------------------------------- selection */
  onSelect(ids) {
    this.selectedNode = ids.length === 1 ? ids[0] : null;
    if (this.selectedNode) {
      this.logNode = this.selectedNode;
      this.logPinned = true;
      // Pin on the session too, so switching away and back keeps this node.
      const session = Sessions.active();
      if (session && session.run) {
        session.run.logNode = this.selectedNode;
        session.run.logPinned = true;
      }
      this.showLog(this.selectedNode);
      if (!document.getElementById('tab-command').classList.contains('hidden')) {
        this.showCommand(this.selectedNode);
      }
    }
  },

  /* ------------------------------------------------------------ command */
  async showCommand(nodeId, quiet) {
    const title = document.getElementById('command-title');
    const output = document.getElementById('command-output');
    const notes = document.getElementById('command-notes');
    if (!nodeId) {
      title.textContent = 'no node selected';
      output.textContent = '';
      notes.innerHTML = '';
      return;
    }
    const node = Editor.nodes.get(nodeId);
    if (!node) {
      // The selection outlived its node -- a tutorial was loaded over a
      // graph with a node selected -- so there is nothing to show.
      this.selectedNode = null;
      title.textContent = 'no node selected';
      output.textContent = '';
      notes.innerHTML = '';
      return;
    }
    if (!quiet) this.activateTab('command');
    title.textContent = `${node.title} (${node.type})`;
    try {
      const preview = await API.preview(Editor.toJSON(), nodeId);
      notes.innerHTML = '';
      if (preview.error) {
        output.textContent = `cannot build a command yet:\n\n${preview.error}`;
        return;
      }
      for (const note of preview.notes || []) {
        notes.appendChild(UI.el('div', { class: 'note', text: note }));
      }
      let text = preview.manual;
      if (Object.keys(preview.files || {}).length) {
        const written = Object.entries(preview.files)
          .map(([name, content]) => `# ---- ${name} ----\n${content}`).join('\n');
        text = `# Comfy-gmx also writes these files into the work directory:\n`
          + `${written}\n# ---- commands ----\n${text}`;
      }
      output.textContent = text;
    } catch (err) {
      output.textContent = err.message;
    }
  },

  activateTab(name) {
    const container = document.getElementById('inspector-tabs');
    for (const tab of container.querySelectorAll('.tab')) {
      tab.classList.toggle('active', tab.dataset.tab === name);
    }
    for (const other of ['log', 'command', 'files', 'viewer', 'plot']) {
      document.getElementById(`tab-${other}`).classList.toggle('hidden', other !== name);
    }
  },

  /* ---------------------------------------------------------------- log */
  showLog(nodeId) {
    const node = Editor.nodes.get(nodeId);
    document.getElementById('log-title').textContent = node
      ? `${node.title} — ${node.status}` : 'no node selected';
    const output = document.getElementById('log-output');
    output.innerHTML = '';
    if (!this.runId || !node) return;
    API.nodeLog(this.runId, nodeId).then((data) => {
      output.innerHTML = '';
      for (const line of data.log) this.appendLog(output, line);
      output.scrollTop = output.scrollHeight;
      const session = Sessions.active();
      if (session && session.run) session.run.lines = data.log.slice(-2000);
    }).catch(() => { /* the node has not run in this run */ });
  },

  logClass(line) {
    if (/error|fatal|traceback/i.test(line)) return 'err';
    if (/warning|warn/i.test(line)) return 'warn';
    return '';
  },

  appendLog(output, line) {
    const cls = this.logClass(line);
    output.appendChild(UI.el('div', { class: cls, text: line }));
    while (output.childElementCount > 3000) output.removeChild(output.firstChild);
  },

  /* ---------------------------------------------------------------- run */
  /* `only`     which nodes to run.
     `force`    which of them to redo even if the answer is already stored.
     `isolate`  true means "these and nothing else": what the nodes before them
                produced last time is fetched from store instead of being
                worked out again. False -- the default -- also runs everything
                they depend on. */
  async run(only, force, { isolate = false } = {}) {
    const session = Sessions.active();
    if (!session) return;
    if (session.run && session.run.status === 'running') {
      UI.toast('this session is already running — cancel it, or open a new session', 'warn');
      return;
    }
    if (!Editor.nodes.size) { UI.toast('nothing to run', 'warn'); return; }

    Editor.resetStatuses();
    document.getElementById('log-output').innerHTML = '';
    // A run starts unpinned so the log pane tracks the active node; clicking a
    // node pins it there.
    this.logPinned = false;

    let started;
    try {
      started = await API.run(Editor.toJSON(), {
        only: only || null,
        force: force || null,
        isolate: Boolean(isolate),
        label: session.name,
        output_dir: session.outputDir || '',
        session: session.id,
      });
    } catch (err) {
      UI.toast(err.message, 'error', 9000);
      return;
    }

    Sessions.beginRun(session, started.run, started.order, started.workdir);
    // Nodes whose answer is already on disk are painted as reused straight
    // away. Announcing them as pending and letting them flash through reads
    // as "it started again from the beginning" -- which is what "Run from
    // here" looked like it was doing, though it recomputed nothing.
    const reused = new Set(started.reused || []);
    if (session.id === Sessions.activeId) {
      this.setRunning(true);
      document.getElementById('status-run').textContent = `run ${started.run}`;
      for (const id of started.order) {
        Editor.setStatus(id, reused.has(id) ? 'cached' : 'pending');
      }
    }
    const toRun = started.order.length - reused.size;
    const borrowed = isolate
      ? ' — everything before it is taken from the last run, not redone' : '';
    UI.toast(`run ${started.run} started — ${toRun} node${toRun === 1 ? '' : 's'} to run`
             + (reused.size ? `, ${reused.size} reused from cache` : '')
             + borrowed
             + ` — in ${started.workdir}`, 'info', 6000);
    this.watch(session);
  },

  /* Follow one session's run. The stream stays open whether or not that
     session is on screen, so a run you switched away from still finishes and
     still reports. Everything that touches the DOM is guarded on the session
     being the active one. */
  watch(session) {
    if (session.stop) { session.stop(); session.stop = null; }
    const runId = session.run.id;
    const isLive = () => session.id === Sessions.activeId;
    const output = document.getElementById('log-output');
    const follow = document.getElementById('log-follow');

    // Lines and progress arrive faster than the page can draw them -- a
    // minimisation with -v prints one line per step -- and adding each line
    // to the page as it came, scrolling after each one, froze the tab. So
    // they are collected and drawn once per screen refresh: one batch of
    // lines, one scroll, and for progress only the latest value per node.
    const pending = [];
    const pendingProgress = new Map();
    let flushScheduled = false;
    const flush = () => {
      flushScheduled = false;
      if (pending.length) {
        const batch = pending.splice(0, pending.length);
        if (isLive()) {
          const frag = document.createDocumentFragment();
          for (const [cls, text] of batch) frag.appendChild(UI.el('div', { class: cls, text }));
          output.appendChild(frag);
          while (output.childElementCount > 3000) output.removeChild(output.firstChild);
          if (follow.checked) output.scrollTop = output.scrollHeight;
        }
      }
      if (pendingProgress.size && isLive()) {
        for (const [node, text] of pendingProgress) Editor.setProgress(node, text);
      }
      pendingProgress.clear();
    };
    const schedule = () => {
      if (flushScheduled) return;
      flushScheduled = true;
      // A tab in the background gets no animation frames; the timer keeps
      // the log moving there too.
      requestAnimationFrame(flush);
      setTimeout(() => { if (flushScheduled) flush(); }, 250);
    };

    if (session.stop) { session.stop(); session.stop = null; }
    // Carry on from the last event we actually saw. Without this, coming back
    // after a break replays the run from the beginning, and every line the
    // drawer already holds is written into it a second time.
    session.stop = API.stream(
      `api/runs/${runId}/events`
      + (session.run.seen ? `?since=${session.run.seen}` : ''), (event) => {
      if (event.seq) session.run.seen = Math.max(session.run.seen || 0, event.seq);
      // The drawer gets everything, in order, for every node -- that is what
      // makes it a transcript rather than a second copy of the Log tab.
      const named = Editor.nodes.get(event.node);
      Terminal.note(session, event, named ? named.title : event.node);
      switch (event.type) {
        case 'node': {
          Sessions.noteNode(session, event.node, event.status, event.error);
          // A finished preview node carries the path of what it looked at.
          // Both statuses matter: a cached node produces no output of its own
          // but still reports where the file it stands for is.
          if (event.outputs && (event.status === 'done' || event.status === 'cached')) {
            const shown = this.previewPathFor(session, event.node, event.outputs);
            if (shown) {
              Sessions.notePreview(session, event.node, shown);
              if (isLive()) NodePreview.setPath(event.node, shown);
            }
          }
          if (event.status === 'running' && !session.run.logPinned) {
            // Nothing pinned: follow whatever is currently running.
            session.run.logNode = event.node;
            session.run.lines = [];
          }
          if (!isLive()) {
            if (event.status === 'error') {
              UI.toast(`${session.name}: ${event.node} failed — `
                       + `${event.error || 'see the log'}`, 'error', 12000);
            }
            break;
          }
          Terminal.status(this._terminalStatus(session), session.run.status === 'running');
          this.logPinned = session.run.logPinned;
          this.logNode = session.run.logNode;
          Editor.setStatus(event.node, event.status, {
            error: event.error || '',
            notes: event.notes,
          });
          const node = Editor.nodes.get(event.node);
          if (event.status === 'running' && !this.logPinned) {
            pending.length = 0;
            output.innerHTML = '';
            document.getElementById('log-title').textContent =
              `${node ? node.title : event.node} — running`;
          }
          if (event.node === this.logNode) {
            document.getElementById('log-title').textContent =
              `${node ? node.title : event.node} — ${event.status}`;
          }
          if (event.status === 'error') {
            UI.toast(`${event.node} failed: ${event.error || 'see the log'}`, 'error', 12000);
            this.logNode = session.run.logNode = event.node;
            Editor.select([event.node]);
          }
          break;
        }
        case 'progress':
          pendingProgress.set(event.node, event.progress);
          schedule();
          break;
        case 'step':
          if (event.node !== session.run.logNode) break;
          Sessions.noteLine(session, `» ${event.label}`);
          pending.push(['step', `» ${event.label}`]);
          schedule();
          break;
        case 'log':
          if (event.node !== session.run.logNode) break;
          Sessions.noteLine(session, event.line);
          pending.push([this.logClass(event.line), event.line]);
          schedule();
          break;
        case 'waiting':
          Terminal.setWaiting(session, event.node, event.waiting);
          break;
        case 'run':
          if (event.status === 'paused') {
            Sessions.noteStatus(session, 'paused');
            if (session.id === Sessions.activeId) {
              const pill = document.getElementById('run-status');
              pill.textContent = 'waiting';
              pill.className = 'status-pill paused';
              this.setPaused(true, event.node);
            }
            break;
          }
          if (event.status === 'running' && session.run.status === 'paused') {
            Sessions.noteStatus(session, 'running');
            if (session.id === Sessions.activeId) this.setPaused(false);
            break;
          }
          if (event.status === 'cancelling') {
            // Not a finished state: the run is still winding down, and Cancel
            // has to stay pressable so a second press can insist.
            Sessions.noteStatus(session, 'cancelling');
            if (session.id === Sessions.activeId) {
              const pill = document.getElementById('run-status');
              pill.textContent = 'cancelling';
              pill.className = 'status-pill running';
            }
            break;
          }
          this.onRunStatus(session, event.status);
          break;
        default:
          break;
      }
    }, (clean) => {
      session.stop = null;
      // The server said the work is over: believe it. It only went quiet:
      // ask what actually happened rather than guessing that it finished.
      if (clean) this.onRunStatus(session, 'done');
      else this.reconcile(session);
    });
  },

  onRunStatus(session, status) {
    if (!session.run) return;
    const settled = ['done', 'error', 'cancelled'].includes(status);
    // The stream's onEnd fires "done" after a real terminal status has already
    // arrived; do not let it overwrite an error with a success.
    if (settled && ['done', 'error', 'cancelled'].includes(session.run.status)) return;
    Sessions.noteStatus(session, status);

    if (session.id === Sessions.activeId) {
      const pill = document.getElementById('run-status');
      pill.textContent = status;
      pill.className = `status-pill ${status === 'running' ? 'running' : status}`;
    }
    if (!settled) return;

    // Nothing may be left spinning over a run that has stopped. A block only
    // ever changed on word from the stream, so if the stream went away while
    // one was working, its spinner stayed on for ever over a job no machine
    // was doing any more. Whatever became of the run became of that block.
    for (const [nodeId, state] of Object.entries(session.run.statuses || {})) {
      if (!state || state.status !== 'running') continue;
      Sessions.noteNode(session, nodeId, status, state.error || '');
      if (session.id === Sessions.activeId) {
        Editor.setStatus(nodeId, status, { error: state.error || '' });
      }
    }

    if (session.stop) { session.stop(); session.stop = null; }
    if (session.id === Sessions.activeId) {
      this.setRunning(false);
      UI.toast(`run ${status}`, status === 'done' ? 'ok' : 'error', 8000);
      this.refreshFiles();
    } else {
      UI.toast(`${session.name}: run ${status}`, status === 'done' ? 'ok' : 'error', 9000);
    }
    // The run has just stored what it made, so which blocks the next Run
    // would reuse has changed, and every status the run sent redrew its
    // block without the dashed "cached" tag. Ask again, as an edit does, or
    // the tags stay off and the line beside Run keeps describing the graph
    // as it was before the run. A run in another tab counts too: the graph
    // on screen may share blocks with it. Not while the tab on screen is
    // running, though: its own end asks, and a forecast has no place on a
    // run that is still going.
    if (!this._running) this.schedulePlan();
  },

  /* The Continue button appears only while something is actually waiting, so
     it is never a button that does nothing. */
  setPaused(paused, nodeId) {
    const button = document.getElementById('btn-continue');
    if (button) {
      button.classList.toggle('hidden', !paused);
      const node = nodeId && Editor.nodes.get(nodeId);
      button.textContent = node ? `Continue past ${node.title}` : 'Continue';
    }
    this._paused = paused;
    if (paused && nodeId) {
      UI.toast('the run is waiting before this node. Change what it should do, '
               + 'then press Continue.', 'warn', 12000);
    }
  },

  setRunning(running) {
    document.getElementById('btn-run').disabled = running;
    document.getElementById('btn-run-selected').disabled = running;
    document.getElementById('btn-cancel').disabled = !running;
    if (!running) this.setPaused(false);
    const stop = document.getElementById('terminal-stop');
    if (stop) stop.disabled = !running;
    const pill = document.getElementById('run-status');
    if (running) {
      pill.textContent = 'running';
      pill.className = 'status-pill running';
    }
    this._running = running;
    Terminal.status(this._terminalStatus(Sessions.active()), running);
  },

  /* What the drawer says about itself when it is not scrolling. */
  _terminalStatus(session) {
    if (!session || !session.run) return 'idle';
    const statuses = Object.values(session.run.statuses || {});
    const settled = statuses.filter((s) => ['done', 'cached', 'skipped'].includes(s.status));
    const failed = statuses.filter((s) => s.status === 'error').length;
    return [
      `run ${session.run.id}`,
      statuses.length ? `${settled.length}/${statuses.length} nodes` : '',
      failed ? `${failed} failed` : '',
      session.run.status,
    ].filter(Boolean).join(' · ');
  },

  /* Let a run that is being held at a node carry on.

     The graph goes with it, so anything changed while it waited -- a box size
     picked by eye, a flag corrected after looking at what came out -- is what
     the rest of the run uses. */
  async resume() {
    const session = Sessions.active();
    if (!session || !session.run) { UI.toast('nothing is waiting', 'warn'); return; }
    let result;
    try {
      result = await API.resume(session.run.id, Editor.toJSON());
    } catch (err) { UI.toast(err.message, 'error', 9000); return; }
    if (!result.resumed) { UI.toast(result.error || 'it would not go on', 'error', 9000); return; }
    UI.toast(result.note || 'carrying on', 'ok', 6000);
  },

  /* Stop the run. The first press asks the commands to stop and gives them a
     few seconds -- mdrun uses them to write a checkpoint, so the run can be
     picked up later. Press it again while it is still stopping and everything
     is killed outright, including anything a finished node left behind. */
  async cancel(hard) {
    const session = Sessions.active();
    if (!session || !session.run) { UI.toast('nothing is running', 'warn'); return; }
    const insist = hard === undefined ? session.run.status === 'cancelling' : Boolean(hard);
    let result;
    try {
      result = await API.cancel(session.run.id, insist);
    } catch (err) { UI.toast(err.message, 'error', 8000); return; }
    if (!result.cancelled) {
      // Never let a press of Cancel do nothing in silence.
      UI.toast(result.error || 'that run could not be stopped', 'error', 9000);
      this.onRunStatus(session, 'error');
      return;
    }
    UI.toast(result.hard
      ? 'killing everything this run started'
      : 'stopping — press Cancel again to kill it outright', 'warn', 7000);
    this.reconcile(session);
  },

  /* Ask the server what became of a run, rather than waiting to be told.

     The status arrives while the page follows the run (API.stream), and
     that is enough right up to the moment it is not: following that stopped
     while nothing was happening, or an event emitted between the last poll
     and the reconnect, leaves the tab saying "running" over a run that
     finished minutes ago. Cancel is
     where it shows, because a cancel is exactly when somebody is watching.

     Backs off rather than polling hard, and stops as soon as the run settles
     or the answer stops being interesting. */
  reconcile(session, tries = 8, delay = 700) {
    const runId = session.run && session.run.id;
    if (!runId) return;
    const settled = (what) => ['done', 'error', 'cancelled'].includes(what);
    const look = async (left, wait) => {
      if (!session.run || session.run.id !== runId) return;
      if (settled(session.run.status)) return;
      let detail;
      try {
        detail = await API.runDetail(runId, false);
      } catch (err) {
        // The run is not there at all -- a server restarted under a session
        // restored from the last visit. Saying so beats "running" for ever.
        this.onRunStatus(session, 'error');
        return;
      }
      if (!session.run || session.run.id !== runId) return;
      // Repaint every block from what the server holds, finished or not. The
      // blocks are the only place a stale "running" is visible once the pill
      // at the top has moved on, and a block left spinning over a job nothing
      // is working on is the most confusing thing this window can show.
      for (const [nodeId, state] of Object.entries(detail.nodes || {})) {
        Sessions.noteNode(session, nodeId, state.status, state.error || '');
        if (session.id === Sessions.activeId) {
          Editor.setStatus(nodeId, state.status, { error: state.error || '' });
        }
      }
      if (settled(detail.status)) {
        this.onRunStatus(session, detail.status);
        return;
      }
      // Still going. Get the live output back rather than polling it to death,
      // unless something has already reconnected while we were asking.
      if (!session.stop) { this.watch(session); return; }
      if (left > 0) setTimeout(() => look(left - 1, Math.min(wait * 1.6, 8000)), wait);
    };
    setTimeout(() => look(tries, delay), delay);
  },

  /* ------------------------------------------------------- output folder */
  /* Show this tab's folder in the desktop's own file manager.

     The Files tab can already walk it, but a file manager is where you drag
     things out to a mail message, open a structure in the viewer you like, or
     just look. Which folder counts as "this tab's" is whichever is the most
     use at that moment: the one this tab's last run wrote into if there has
     been a run, otherwise the folder its runs will be created under. The
     button says which one it means before you press it. */
  workFolder() {
    const session = Sessions.active ? Sessions.active() : null;
    if (!session) return { path: '', what: 'the default run folder' };
    const run = session.run && session.run.workdir;
    if (run) return { path: run, what: `the files from this tab's last run` };
    if (session.outputDir) return { path: session.outputDir, what: `this tab's run folder` };
    return { path: '', what: 'the default run folder' };
  },

  async openWorkFolder() {
    const want = this.workFolder();
    let answer;
    try {
      answer = await API.openFolder(want.path);
    } catch (err) {
      UI.toast(`could not open the folder: ${err.message}`, 'warn');
      return;
    }
    if (answer.opened) {
      UI.toast(`opened ${answer.path}`, 'ok', 2600);
      return;
    }
    // No desktop to open it in -- the server may be on another machine, or
    // running without a screen. The path itself is still the useful answer.
    UI.copy(answer.path);
    UI.toast(`${answer.why || 'nothing to open it with'} -- copied ${answer.path}`,
             'warn', 6000);
  },

  /* Where this session's runs go. It used to be a box you typed a path into,
     which meant knowing the path by heart and leaving for a terminal to make
     the folder -- so it browses now, and makes folders. The free-space report
     it always had follows you from folder to folder as you walk. */
  async chooseOutputDir() {
    const session = Sessions.active();
    if (!session) return;
    Pick.folder({
      title: `Output folder — ${session.name}`,
      start: session.outputDir || this.outputRoot || this.homeDir,
      hint: 'Where this session creates its run directories. Every node\'s working '
          + 'files live there, so put it on the disk with room for trajectories '
          + 'rather than in a home directory.',
      extra: [
        { label: 'default', path: this.outputRoot },
        { label: 'home', path: this.homeDir },
      ].filter((shortcut) => shortcut.path),
      describe: async (path) => {
        let data;
        try { data = await API.outputDir(path); }
        catch (err) { return { text: err.message, warn: true }; }
        if (data.problem) return { text: data.problem, warn: true };
        return {
          text: `${data.exists ? 'Exists' : 'Will be created'}: ${data.path} — `
              + `${(data.free_bytes / 1e9).toFixed(1)} GB free. `
              + 'Each run gets a timestamped subfolder.',
        };
      },
      buttons: [{
        label: 'Use default',
        action: () => {
          session.outputDir = '';
          Sessions.render();
          UI.toast('runs will go to the default folder', 'ok');
        },
      }],
      onPick: (path) => {
        session.outputDir = path;
        Sessions.render();
        UI.toast(path ? `runs will go under ${path}` : 'runs will go to the default folder', 'ok');
      },
    });
  },

  /* -------------------------------------------------------------- files */
  /* The panel itself lives in files.js; this is the tab asking it to redraw. */
  refreshFiles() {
    FileBrowser.refresh();
  },

  async openFile(path) {
    const lower = path.toLowerCase();
    try {
      // A trajectory is not text and never was. Opening one used to decode a
      // few hundred kB of compressed binary into the log pane; it now answers
      // the question somebody clicking a trajectory actually has.
      if (/\.(xtc|trr|tng)$/i.test(lower)) {
        TrajectoryFacts.show(path);
        return;
      }
      if (/\.(tpr|edr|cpt|npz|gsd|dcd|h5|bin)$/i.test(lower)) {
        UI.toast(`${path.split('/').pop()} is a binary file — download it or `
                 + 'point a node at it', 'info', 6000);
        return;
      }
      if (lower.endsWith('.pdb') || lower.endsWith('.gro') || lower.endsWith('.g96')) {
        this.activateTab('viewer');
        Viewer.show(await API.structure(path), path);
      } else if (lower.endsWith('.xvg') || lower.endsWith('.dat') || lower.endsWith('.csv')) {
        this.activateTab('plot');
        Plot.show(await API.xvg(path));
      } else {
        const data = await API.fileText(path, true);
        this.activateTab('log');
        const output = document.getElementById('log-output');
        output.innerHTML = '';
        document.getElementById('log-title').textContent =
          `${path}${data.truncated ? ' (tail)' : ''}`;
        for (const line of data.text.split('\n')) this.appendLog(output, line);
      }
    } catch (err) {
      UI.toast(err.message, 'error');
    }
  },

  /* Which file a finished node wants shown in its body, or '' for the great
     majority of nodes that show nothing. The node type has to be looked up in
     the session's own graph: a run in a background session has no nodes in the
     editor at all. */
  previewPathFor(session, nodeId, outputs) {
    let type = '';
    if (session.id === Sessions.activeId) {
      const node = Editor.nodes.get(nodeId);
      type = node ? node.type : '';
    }
    if (!type) {
      const raw = ((session.graph || {}).nodes || []).find((n) => n.id === nodeId);
      type = raw ? raw.type : '';
    }
    const def = this.defs[type];
    if (!def || !def.preview) return '';
    const port = (outputs || {})[def.preview.port];
    return port && port.path ? port.path : '';
  },

  /* What is in the structure this node is looking at, before anything runs. */
  async inspectStructure(nodeId) {
    const node = Editor.nodes.get(nodeId);
    const source = Editor.structureSource(nodeId);
    if (!source) { UI.toast('no structure to look at from here', 'warn'); return; }
    UI.toast(source.pdb ? `fetching ${source.pdb.toUpperCase()}…` : 'reading…', 'info', 2000);
    try {
      const data = await API.composition(source);
      if (data.error) throw new Error(data.error);
      if (!data.n_atoms) throw new Error(`${source.label} holds no atoms`);
      Panels.structureInfo(data, node);
    } catch (err) {
      UI.toast(err.message, 'error', 12000);
    }
  },

  /* "How big a box does this need?", answered by looking at it. Asked when
     there is no box at all yet and a number has to be invented. */
  async pickBoxAround(nodeId) {
    const node = Editor.nodes.get(nodeId);
    if (!node) return;
    UI.toast('measuring the molecule…', 'info', 2000);
    try {
      let what = null;
      try {
        what = { path: (await API.inputFile(Editor.toJSON(), nodeId, 'structure')).path };
      } catch (err) {
        // Nothing upstream has run yet. A box is chosen before anything runs,
        // so that is the normal case rather than the exception: fall back to
        // whatever file, or PDB code, the chain leads to.
        const source = Editor.structureSource(nodeId);
        if (!source || !(source.path || source.pdb)) throw err;
        what = source.pdb ? { pdb: source.pdb } : { path: source.path };
      }
      const data = await API.boxAround(what);
      if (data.error) throw new Error(data.error);
      Panels.boxAround(data, node);
    } catch (err) {
      UI.toast(err.message, 'error', 14000);
    }
  },

  /* What the structure this node is looking at does *not* contain.

     A different question from "what is in it", and the one that decides whether
     a rebuild is worth attempting: the coordinates cannot tell you about a
     residue that is not in them, only the deposited sequence can. */
  async inspectMissing(nodeId) {
    const node = Editor.nodes.get(nodeId);
    const source = Editor.structureSource(nodeId);
    if (!source) { UI.toast('no structure to look at from here', 'warn'); return; }
    UI.toast(source.pdb ? `fetching ${source.pdb.toUpperCase()}…` : 'reading…', 'info', 2000);
    try {
      const data = await API.sequence(source);
      if (data.error) throw new Error(data.error);
      Panels.missingResidues(data, node);
    } catch (err) {
      UI.toast(err.message, 'error', 12000);
    }
  },

  /* ------------------------------------------------------------- drops */

  /* Everything is bound to the window rather than to the canvas.

     The canvas is a strip between two panels and it is easy to miss, and a file
     dropped on a page that does not accept it makes the browser navigate to
     that file -- so a near miss looks like "nothing happened" and takes the
     graph with it.

     What gets claimed is decided by where the drag came from, not by what
     dataTransfer.types says it holds. During dragover a browser is allowed to
     hide almost everything about a drag, and Firefox hides enough that a file
     drag can look like nothing at all; deciding on that means refusing real
     files. A drag that began inside this page fired dragstart here, and
     anything else came from outside the browser -- which, for a page with no
     links to drag, means a file. */
  bindDrops() {
    const overlay = document.getElementById('drop-overlay');
    const message = document.getElementById('drop-message');
    let depth = 0;
    const hide = () => { depth = 0; overlay.classList.add('hidden'); };

    // Bound to window rather than document so nothing can be missed on its
    // way up: window is the last stop for everything the page dispatches.
    let beat = 0;
    const forget = () => { this.dragSource = null; };
    window.addEventListener('dragstart', (event) => {
      this.dragSource = this.dragCarriesOwn(event) ? 'palette' : 'page';
      beat = performance.now();
    });
    window.addEventListener('dragend', () => { forget(); hide(); });
    window.addEventListener('mousedown', forget);

    // Capture phase, so nothing downstream can stop this from running. A drop
    // onto a node's file box is handled there and stopped from bubbling, and
    // the overlay would otherwise never learn that the drag was over: it stayed
    // on screen until you dropped something else on it.
    window.addEventListener('drop', hide, true);

    /* A drag in progress fires dragover continuously, so a gap means the drag
       that set the flag has ended -- however its dragend went missing. Letting
       a stale 'page' flag survive would silently refuse every file dropped
       afterwards, which is the failure this whole path exists to prevent. */
    const freshen = () => {
      const now = performance.now();
      if (now - beat > 800) forget();
      beat = now;
    };

    /* Should this drag become a node? Text being dragged about inside the page
       should not, and neither should text dragged in from elsewhere and aimed
       at a box meant for typing in. Everything else should: a browser is free
       to say almost nothing about a drag in flight, and refusing what it will
       not describe means refusing real files. */
    const claim = (event) => {
      if (this.dragSource === 'palette') return true;
      const carries = this.dragCarriesFiles(event);
      if (this.dragSource === 'page' && !carries) return false;
      if (this.isTextField(event.target) && !carries) return false;
      return true;
    };

    /* Entering a child fires dragenter on it and dragleave on its parent, so
       the two only cancel out if every one of them is counted. Counting just
       the ones worth showing the overlay for made the total drift, which shows
       up as an overlay that hides while the drag is still in the window. */
    window.addEventListener('dragenter', (event) => {
      freshen();
      depth += 1;
      if (!claim(event) || this.dragSource === 'palette') return;
      event.preventDefault();
      message.textContent = this.pointInCanvas(event.clientX, event.clientY)
        ? 'Drop to add it here'
        : 'Drop anywhere — it lands in the middle of the view';
      overlay.classList.remove('hidden');
    });
    window.addEventListener('dragleave', () => {
      depth = Math.max(0, depth - 1);
      if (!depth) overlay.classList.add('hidden');
    });
    window.addEventListener('dragover', (event) => {
      freshen();
      if (!claim(event)) return;
      // Claim it before anything else can go wrong: if this handler throws
      // first, the browser is left free to navigate away from the editor.
      event.preventDefault();
      try { event.dataTransfer.dropEffect = 'copy'; } catch (err) { /* advisory */ }
    });
    window.addEventListener('drop', (event) => {
      const ours = this.dragSource === 'palette';
      if (!claim(event)) { forget(); return; }
      event.preventDefault();
      forget();
      hide();
      const dt = event.dataTransfer;
      if (!dt) return;
      this.lastDropTypes = this.dragTypes(event);

      const inCanvas = this.pointInCanvas(event.clientX, event.clientY);
      const world = inCanvas
        ? Editor.screenToWorld(event.clientX, event.clientY)
        : Editor.viewCenter();

      if (ours || this.dragCarriesOwn(event)) {
        // Our own drags only count over the canvas: letting go of a palette
        // item on the inspector means "never mind", not "put it somewhere".
        if (!inCanvas) return;
        const nodeType = dt.getData('text/comfygmx-node');
        if (nodeType) {
          Editor.mark(`add ${(this.defs[nodeType] || {}).title || nodeType}`);
          Editor.addNode(nodeType, world.x, world.y);
          return;
        }
        const chunk = this.chunks.find((c) => c.id === dt.getData('text/comfygmx-chunk'));
        if (chunk) { Editor.addChunk(chunk, world.x, world.y); return; }
        const tutorial = dt.getData('text/comfygmx-tutorial');
        if (tutorial) { this.dropTutorial(tutorial, world); return; }
        // A file dragged out of the Files tab. It is already on this machine,
        // so it takes the same path as a file dragged in from the desktop --
        // minus the part where the bytes have to be copied anywhere.
        const path = dt.getData('text/comfygmx-file');
        if (path) this.addDroppedPath(path, world);
        return;
      }
      this.dropFiles(dt, world);
    });
  },

  /* Dropping a tutorial is the "Add to canvas" button of its panel, at the
     point you let go. The palette only carries the tutorial's summary, so the
     graph is fetched here; the panel is still where the steps, the citation
     and the list of tools it needs live. */
  async dropTutorial(id, world) {
    let tutorial;
    try { tutorial = await API.tutorial(id); }
    catch (err) { UI.toast(err.message, 'error'); return; }
    if (!tutorial.graph) {
      UI.toast(`"${tutorial.name}" is not packaged as a graph yet`, 'warn');
      return;
    }
    Editor.mark(`add ${tutorial.name}`);
    Editor.addChunk(tutorial, world.x, world.y);
    UI.toast(`added "${tutorial.name}" — open it in the Tutorials tab for the `
             + 'steps and the citation', 'ok', 6000);
  },

  /* dataTransfer.types is an Array in some browsers and a DOMStringList in
     others, and reading it during a drag can throw outright. Nothing here is
     load-bearing -- it refines a decision that already has a safe default. */
  dragTypes(event) {
    try {
      const raw = event.dataTransfer && event.dataTransfer.types;
      return raw ? Array.prototype.slice.call(raw) : [];
    } catch (err) {
      return [];
    }
  },

  isTextField(target) {
    if (!target || !target.tagName) return false;
    if (target.isContentEditable) return true;
    if (target.tagName === 'TEXTAREA') return true;
    // A file box is a text input, but a file dropped on it is the whole point.
    if (target.classList && target.classList.contains('file-box')) return false;
    return target.tagName === 'INPUT'
      && ['text', 'search', 'url', 'email', 'password', 'number', ''].includes(
        (target.getAttribute('type') || '').toLowerCase());
  },

  dragCarriesOwn(event) {
    const types = this.dragTypes(event);
    return types.includes('text/comfygmx-node') || types.includes('text/comfygmx-chunk')
      || types.includes('text/comfygmx-tutorial')
      || types.includes('text/comfygmx-file');
  },

  dragCarriesFiles(event) {
    if (this.dragCarriesOwn(event)) return false;
    const types = this.dragTypes(event);
    return types.includes('Files') || types.includes('text/uri-list')
      || types.includes('application/x-moz-file');
  },

  pointInCanvas(x, y) {
    const rect = document.getElementById('canvas').getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  },

  /* Every URI the drag carries, in the order the source listed them.

     File managers hand over a text/uri-list; a browser hands over the address
     of whatever was dragged. Chrome deliberately withholds local paths from
     both, which is why the file bytes are a fallback and not the first choice. */
  urisFromDrop(dt) {
    const out = [];
    const seen = new Set();
    for (const type of ['text/uri-list', 'text/plain']) {
      let raw = '';
      try { raw = dt.getData(type) || ''; } catch (err) { raw = ''; }
      for (let line of raw.split(/[\r\n]+/)) {
        line = line.trim();
        // uri-list comments start with '#', and a bare '#' line is not a path.
        if (!line || line.startsWith('#')) continue;
        if (!seen.has(line)) { seen.add(line); out.push(line); }
      }
      if (out.length) break;
    }
    return out;
  },

  /* A URI this machine can open as a file, or '' if it is not one. */
  localPath(uri) {
    if (/^file:\/\//i.test(uri)) {
      try {
        const url = new URL(uri);
        // file://host/path is somebody else's disk unless the host is ours.
        if (url.hostname && url.hostname !== 'localhost') return '';
        return decodeURIComponent(url.pathname);
      } catch (err) { return ''; }
    }
    if (uri.startsWith('/') || uri.startsWith('~/')) return uri;
    return '';
  },

  /* A path with a scheme on the front is still a path. Anything else is
     returned untouched, so this is safe on whatever a user types. */
  normalisePath(text) {
    const value = String(text === null || text === undefined ? '' : text).trim();
    if (!/^file:\/\//i.test(value)) return value;
    return this.localPath(value) || value;
  },

  /* One path for a drop onto a file box: the dragged path if there is one,
     otherwise the uploaded copy of the dragged bytes. */
  async onePathFromDrop(dt) {
    const files = dt.files ? [...dt.files] : [];
    for (const uri of this.urisFromDrop(dt)) {
      const path = this.localPath(uri);
      if (path) return path;
    }
    if (!files.length) { UI.toast('that drag carried no file path', 'warn'); return ''; }
    if (files[0].size > MAX_UPLOAD) {
      UI.toast(`${files[0].name} is ${UI.bytes(files[0].size)} — too big to copy in. `
               + 'Use the … button to point at it where it already is.', 'error', 14000);
      return '';
    }
    try {
      const result = await API.upload(files[0]);
      UI.toast(`copied ${result.name} into the uploads folder`, 'ok');
      return result.path;
    } catch (err) {
      UI.toast(err.message, 'error', 9000);
      return '';
    }
  },

  async dropFiles(dt, world) {
    // A DataTransfer is emptied the moment the handler returns, so read
    // everything out of it before the first await. File objects survive.
    const uris = this.urisFromDrop(dt);
    const files = dt.files ? [...dt.files] : [];
    const paths = uris.map((uri) => this.localPath(uri)).filter(Boolean);
    const urls = uris.filter((uri) => /^https?:\/\//i.test(uri));

    let index = 0;
    const spot = () => { const at = { x: world.x + index * 28, y: world.y + index * 28 }; index += 1; return at; };

    // A path beats the bytes every time: the node then points at the original
    // file. That is the difference between referring to a 15 GB trajectory and
    // trying to push it through the browser.
    let handled = 0;
    for (const path of paths) {
      if (await this.addDroppedPath(path, spot())) handled += 1;
    }
    // Every path was one this machine cannot open -- a share that is not
    // mounted here, say. If the drag also carried the bytes, use those.
    if (handled || (paths.length && !files.length)) return;
    if (urls.length) {
      for (const url of urls) {
        const at = spot();
        Editor.mark('add Download file');
        Editor.addNode('io.fetch_url', at.x, at.y, { url });
      }
      UI.toast(`added ${urls.length} download node${urls.length === 1 ? '' : 's'}`, 'ok');
      return;
    }
    if (!files.length) {
      const seen = this.lastDropTypes.length ? this.lastDropTypes.join(', ') : 'nothing at all';
      UI.toast(`that drag carried nothing this can use — it offered ${seen}`, 'warn', 12000);
      return;
    }
    // No path anywhere -- Chrome hides it. Copy the bytes into the uploads
    // folder and point the node at the copy.
    for (const file of files) {
      if (file.size > MAX_UPLOAD) {
        UI.toast(`${file.name} is ${UI.bytes(file.size)} — too big to copy in. Add a `
                 + 'Load node and use its … button to point at the file where it is.',
                 'error', 14000);
        continue;
      }
      try {
        const result = await API.upload(file);
        await this.addDroppedPath(result.path, spot(), true);
      } catch (err) {
        UI.toast(`${file.name}: ${err.message}`, 'error', 12000);
      }
    }
  },

  /* Turn one path into the node that reads that kind of file. */
  async addDroppedPath(path, at, uploaded = false) {
    let info = null;
    try { info = await API.stat(path); } catch (err) { info = null; }
    if (info && !info.exists) {
      UI.toast(`this machine cannot see ${path}`, 'error', 12000);
      return false;
    }
    if (info && info.dir) {
      UI.toast(`${path} is a folder. Drop one of the files inside it instead.`, 'warn', 9000);
      return false;
    }
    const resolved = info && info.path ? info.path : path;
    const name = resolved.split('/').pop();

    // A dropped workflow is a workflow, not an input file. It opens in a new
    // session so nothing you were working on is replaced.
    if (/\.json$/i.test(name)) {
      const graph = await this.workflowFromFile(resolved);
      if (graph) {
        Sessions.add(name.replace(/\.json$/i, ''), graph);
        UI.toast(`opened ${name} in a new session`, 'ok', 6000);
        return true;
      }
    }

    const kind = this.dropKind(name);
    const def = this.defs[kind.type] || {};
    Editor.mark(`add ${def.title || kind.type}`);
    Editor.addNode(kind.type, at.x, at.y, { ...kind.params, path: resolved });
    UI.toast(`${name} → ${def.title || kind.type}`
             + (uploaded ? ' (copied into the uploads folder)' : ''), 'ok');
    return true;
  },

  /* Extension -> the node that reads it. Anything unrecognised still lands as
     a Load file node, which is better than refusing the drop. */
  dropKind(name) {
    const ext = (name.split('.').pop() || '').toLowerCase();
    for (const entry of DROP_NODES) {
      if (entry.ext.includes(ext)) return { type: entry.type, params: entry.params || {} };
    }
    // 'auto', so the loader reads the type off the name it was given
    // rather than this list having to know every extension.
    return { type: 'io.file', params: { kind: 'auto' } };
  },

  async workflowFromFile(path) {
    try {
      const file = await API.fileText(path, false, 4000000);
      if (file.truncated) return null;
      const parsed = JSON.parse(file.text);
      const graph = parsed && parsed.graph && parsed.graph.nodes ? parsed.graph : parsed;
      if (graph && Array.isArray(graph.nodes) && Array.isArray(graph.links)) return graph;
    } catch (err) { /* just a .json file, then */ }
    return null;
  },

  /* ------------------------------------------------------------ pickers */
  /* Select a set of nodes and bring them into view — used by the tutorial steps. */
  focusNodes(ids) {
    const present = (ids || []).filter((id) => Editor.nodes.has(id));
    if (!present.length) {
      UI.toast('those nodes are not in this graph', 'warn');
      return;
    }
    Editor.select(present);
    let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
    for (const id of present) {
      const node = Editor.nodes.get(id);
      const width = node._el ? node._el.offsetWidth : 240;
      const height = node._el ? node._el.offsetHeight : 120;
      minX = Math.min(minX, node.pos[0]);
      minY = Math.min(minY, node.pos[1]);
      maxX = Math.max(maxX, node.pos[0] + width);
      maxY = Math.max(maxY, node.pos[1] + height);
    }
    const rect = Editor.dom.canvas.getBoundingClientRect();
    Editor.view.x = rect.width / 2 - ((minX + maxX) / 2) * Editor.view.scale;
    Editor.view.y = rect.height / 2 - ((minY + maxY) / 2) * Editor.view.scale;
    Editor.applyView();
  },

  openNodeSearch(world) {
    const input = UI.el('input', { type: 'text', placeholder: 'type to filter…' });
    const list = UI.el('div', { class: 'file-browser' });
    const render = () => {
      const needle = input.value.trim().toLowerCase();
      list.innerHTML = '';
      for (const spec of Object.values(this.defs)) {
        // Same rule as the palette: a node something else does the job of now
        // is not offered, only kept working for graphs that hold one.
        if (spec.hidden) continue;
        const haystack = `${spec.title} ${spec.type} ${spec.description}`.toLowerCase();
        if (needle && !haystack.includes(needle)) continue;
        list.appendChild(UI.el('div', {
          class: 'fb-row',
          onclick: () => {
            Editor.mark(`add ${spec.title}`);
            Editor.addNode(spec.type, world.x, world.y);
            UI.closeModal();
          },
        }, [
          UI.el('span', { text: spec.title }),
          UI.el('span', { class: 'fb-size', text: spec.type }),
        ]));
      }
    };
    input.addEventListener('input', render);
    render();
    UI.modal('Add node', UI.el('div', {}, [input, list]), [{ label: 'Cancel' }]);
    setTimeout(() => input.focus(), 30);
  },

  openChunkPicker(world) {
    const list = UI.el('div', { class: 'file-browser' });
    for (const chunk of this.chunks) {
      list.appendChild(UI.el('div', {
        class: 'fb-row',
        onclick: () => { Editor.addChunk(chunk, world.x, world.y); UI.closeModal(); },
      }, [
        UI.el('span', {}, [
          UI.el('div', { text: chunk.name }),
          UI.el('div', { class: 'fb-size', text: chunk.description }),
        ]),
      ]));
    }
    UI.modal('Add chunk', list, [{ label: 'Cancel' }]);
  },
};

window.addEventListener('DOMContentLoaded', () => App.boot());
