/* Thin wrapper over the REST surface plus a couple of shared UI helpers. */
'use strict';

const API = (() => {
  async function request(method, url, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const text = await response.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch (err) { throw new Error(`${response.status}: ${text.slice(0, 400)}`); }
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  const get = (url) => request('GET', url);
  const post = (url, body) => request('POST', url, body);
  const del = (url) => request('DELETE', url);

  return {
    info:        () => get('api/info'),
    nodes:       () => get('api/nodes'),
    /* The flag list of one command, marked up for one node. Asked for when
       somebody opens a node's flag reference, not with the catalogue: the
       lists together are several times its size. */
    flags:       (command, node) => get(`api/flags?command=${encodeURIComponent(command)}`
      + (node ? `&node=${encodeURIComponent(node)}` : '')),
    chunks:      () => get('api/chunks'),
    saveChunk:   (chunk) => post('api/chunks', chunk),
    deleteChunk: (id) => del(`api/chunks/${encodeURIComponent(id)}`),
    tutorials:   () => get('api/tutorials'),
    tutorial:    (id) => get(`api/tutorials/${encodeURIComponent(id)}`),

    gmxForcefields: () => get('api/library/gmx_forcefields'),
    openFolder: (path) => post('api/open_folder', { path }),

    settings:    () => get('api/settings'),
    saveSettings: (patch) => post('api/settings', patch),

    environment: (probe = true) => get(`api/environment?probe=${probe ? 1 : 0}`),
    probe:       (tool) => post('api/environment/probe', { tool }),
    installScript: (tool, env, version) =>
      post('api/environment/install/script', { tool, env, version }),
    install:     (tool, env, version) =>
      post('api/environment/install', { tool, env, version }),
    job:         (id) => get(`api/jobs/${id}`),

    validate:    (graph) => post('api/graph/validate', { graph }),
    /* Which programs a workflow needs, which of them are missing here, and
       what versions it was built against. `probe` runs each tool's version
       check, which is a second or two apiece -- only worth it when a
       workflow is being written out. */
    graphTools:  (graph, tools, probe) =>
      post('api/graph/tools', { graph, tools: tools || {}, probe: !!probe }),
    plan:        (graph) => post('api/graph/plan', { graph }),
    preview:     (graph, node) => post('api/graph/preview', { graph, node }),

    run:         (graph, opts = {}) => post('api/run', Object.assign({ graph }, opts)),
    // The workflow as a folder of shell scripts, with the files it reads.
    exportScripts: (graph, opts = {}) => post('api/export', Object.assign({ graph }, opts)),
    runs:        () => get('api/runs'),
    outputDir:   (path) => post('api/output-dir', { path }),
    runDetail:   (id, withLog) => get(`api/runs/${id}${withLog ? '?log=1' : ''}`),
    runFiles:    (id) => get(`api/runs/${id}/files`),
    nodeLog:     (runId, nodeId) => get(`api/runs/${runId}/nodes/${encodeURIComponent(nodeId)}/log`),
    /* Stop a run. `hard` skips the polite signals and kills it now -- what a
       second press of Cancel, or a second Ctrl+C, sends. */
    cancel:      (id, hard) => post(`api/runs/${id}/cancel`, { hard: !!hard }),
    /* Let a run that is being held at a node carry on. The graph goes with
       it, so a value changed while it waited is the one that gets used. */
    resume:      (id, graph) => post(`api/runs/${id}/resume`, { graph }),
    /* Type into the command a run is presently on, or close its input. */
    sendInput:   (id, body) => post(`api/runs/${id}/input`, body || {}),
    runFolders:  (root) => get('api/runs/folders'
      + (root ? `?root=${encodeURIComponent(root)}` : '')),
    deleteRunFolder: (path) => post('api/runs/folders/delete', { path }),
    cacheStats:  () => get('api/cache'),
    mdpPresets:  () => get('api/mdp/presets'),
    clearCache:  () => del('api/cache'),

    workflows:   () => get('api/workflows'),
    saveWorkflow: (name, graph) => post('api/workflows', { name, graph }),
    loadWorkflow: (name) => get(`api/workflows/${encodeURIComponent(name)}`),
    deleteWorkflow: (name) => del(`api/workflows/${encodeURIComponent(name)}`),

    /* Look for files by name in a folder and everything under it. */
    findFiles:   (path, q, hidden) => get(`api/files/find?path=${encodeURIComponent(path || '')}`
                   + `&q=${encodeURIComponent(q || '')}${hidden ? '&hidden=1' : ''}`),
    files:       (path, hidden) => get(`api/files?path=${encodeURIComponent(path || '')}${hidden ? '&hidden=1' : ''}`),
    fileText:    (path, tail, bytes) => get(`api/file?path=${encodeURIComponent(path)}`
                   + `${tail ? '&tail=1' : ''}${bytes ? `&bytes=${bytes}` : ''}`),
    /* Is there a file at this path, and can this machine read it? */
    stat:        (path) => get(`api/stat?path=${encodeURIComponent(path)}`),
    /* Copy a file to somewhere else on the machine running the server. */
    copyFile:    (body) => post('api/copy', body),
    downloadUrl: (path) => `api/file?download=1&path=${encodeURIComponent(path)}`,
    /* Copy the bytes of a dropped file onto the machine running the server.
       Without a directory it lands in the uploads folder, which is where a
       drop on the canvas goes; the file browser passes the folder you dropped
       it on. */
    upload:      async (file, directory) => {
      const response = await fetch(`api/upload?name=${encodeURIComponent(file.name)}`
        + (directory ? `&dir=${encodeURIComponent(directory)}` : ''),
        { method: 'PUT', body: file });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      return data;
    },
    mkdir:       (path, name) => post('api/files/mkdir', { path, name }),
    /* Two shapes: {path: folder, name: 'run.mdp', text} makes a new file in a
       folder, {path: file, text} rewrites one that is already there. */
    writeFile:   (body) => post('api/files/write', body),

    structure:   (path, max) => get(`api/viz/structure?path=${encodeURIComponent(path)}${max ? `&max=${max}` : ''}`),
    dssp:        (path) => get(`api/viz/dssp?path=${encodeURIComponent(path)}`),
    trajectory:  (path) => get(`api/viz/trajectory?path=${encodeURIComponent(path)}`),
    /* Frames, timestep, atom count. Without scan it answers from what is
       already known, because finding out means reading the whole file. */
    trajFacts:   (path, scan) => get(`api/traj?path=${encodeURIComponent(path)}`
      + (scan ? '&scan=1' : '')),
    xvg:         (path) => get(`api/viz/xvg?path=${encodeURIComponent(path)}`),
    mdlog:       (path) => get(`api/viz/log?path=${encodeURIComponent(path)}`),
    versions: (tool) => get(`api/environment/versions?tool=${encodeURIComponent(tool)}`),
    cancelJob: (job) => post(`api/jobs/${encodeURIComponent(job)}/cancel`, {}),
    installs: (tool) => get('api/environment/installs'
      + (tool ? `?tool=${encodeURIComponent(tool)}` : '')),
    useInstall: (tool, env) => post('api/environment/installs', { tool, env }),
    // Repo-backed tools: run the user's own checkout instead of the
    // one the installer manages. '' hands it back to the installer.
    source:      (tool) => get(`api/environment/source?tool=${encodeURIComponent(tool)}`),
    setSource:   (tool, path) => post('api/environment/source', { tool, path }),
    updates: (tools) => post('api/environment/updates', tools ? { tools } : {}),
    gromacsPlan: (options) => post('api/environment/gromacs/plan', options),
    gromacsBuild: (options) => post('api/environment/gromacs/build', options),

    /* First-run setup: what this machine is missing, and installing it. */
    removeEnv:   (env, confirm) => post('api/environment/remove', { env, confirm }),
    requirements: (tool) =>
      get(`api/environment/requirements?tool=${encodeURIComponent(tool)}`),

    setup:       () => get('api/setup'),
    setupPlan:   (choices) => post('api/setup/plan', choices || {}),
    setupRun:    (choices) => post('api/setup/run', choices || {}),
    setupDone:   () => post('api/setup/done', {}),

    /* What is in a structure -- chains, residue ranges, species -- without
       running anything. Takes a path, or a PDB id to fetch once and keep. */
    composition: (what) => get('api/viz/composition?' + (what.pdb
      ? `pdb=${encodeURIComponent(what.pdb)}&format=${encodeURIComponent(what.format || 'pdb')}`
      : `path=${encodeURIComponent(what.path)}`)),
    /* How big a box one molecule needs: how far across it is, where it sits,
       and enough of its atoms to draw it. For choosing a box by eye before
       there is one. */
    boxAround: (what) => get('api/viz/box-around?' + (what.pdb
      ? `pdb=${encodeURIComponent(what.pdb)}`
      : `path=${encodeURIComponent(what.path)}`)),
    /* Which file a node's input port will really read -- the one an earlier
       node produced, which only exists once that node has run. */
    inputFile: (graph, node, port) => post('api/graph/input-file', { graph, node, port }),
    /* Every group of atoms a block reading this system can be asked for,
       read from the run file that feeds it (and its index file, if wired). */
    graphGroups: (graph, node) => post('api/graph/groups', { graph, node }),
    /* The deposited sequence against what the coordinates hold: which residues
       are missing, and whether each run is a loop or a tail. */
    sequence: (what) => get('api/viz/sequence?' + (what.pdb
      ? `pdb=${encodeURIComponent(what.pdb)}&format=${encodeURIComponent(what.format || 'pdb')}`
      : `path=${encodeURIComponent(what.path)}`)),

    /* Tidying up in the file panel. Copy and move never write over
       anything; delete puts things in the trash unless told otherwise. */
    copyPaths: (paths, destination) => post('api/files/copy', { paths, destination }),
    movePaths: (paths, destination) => post('api/files/move', { paths, destination }),
    deletePaths: (paths, forever = false) => post('api/files/delete', { paths, forever }),
    renamePath: (path, name) => post('api/files/rename', { path, name }),

    /* Force fields: what is on this machine, and what can be fetched. */
    forcefields: () => get('api/forcefields'),
    /* Fetch one into the folder the topology block reads. Either a catalogue
       entry by id, or {url, name} for an address you found yourself. */
    installForcefield: (what) => post('api/forcefields/install', what),

    /* Follow a run or a job as it happens; returns a function that stops.

       The page asks the server "anything new since message N?", over and
       over. The server answers at once when there is news, or after ten
       seconds of nothing, and the page asks again. This used to be one reply
       that stayed open and grew; the servers in front of mybinder.org (its
       GESIS site, at least) hold such a reply back until it is complete, so a
       run there showed nothing until it was over -- and, with no other
       requests, the copy was closed as unused half way through a run.

       onEnd is told which of the two ways it ended. The server saying
       "finished" means the work really is over. Anything else -- the machine
       slept, the network blinked, the server was restarted -- means only that
       we stopped being told, which is not the same thing and must not be read
       as one. Treating the second as the first is how a finished run could be
       announced hours early, and how a block was left spinning for ever. A
       question that fails is asked twice more, a few seconds apart, before it
       counts as having stopped being told: a network that blinks for a
       second should not cost anybody anything. */
    stream(url, onEvent, onEnd) {
      const [path, query] = url.split('?');
      let since = Number(new URLSearchParams(query || '').get('since')) || 0;
      let over = false;
      const pause = (ms) => new Promise((done) => setTimeout(done, ms));
      const finish = (clean) => {
        if (over) return;
        over = true;
        if (onEnd) onEnd(clean);
      };
      (async () => {
        let failed = 0;
        while (!over) {
          let answer;
          try {
            answer = await get(`${path}?since=${since}&wait=10`);
            failed = 0;
          } catch (err) {
            failed += 1;
            if (failed > 2) { finish(false); return; }
            await pause(2000 * failed);
            continue;
          }
          if (over) return;
          const events = answer.events || [];
          for (const event of events) {
            if (event.seq) since = Math.max(since, event.seq);
            try { onEvent(event); } catch (err) { console.error(err); }
          }
          if (answer.finished) { finish(true); return; }
          // A busy stretch sends many small messages. A second between
          // questions gathers them into a few replies instead of hundreds.
          if (events.length) await pause(1000);
        }
      })();
      return () => { over = true; };
    },
  };
})();

/* -------------------------------------------------------------- helpers */

const UI = {
  el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined) node.setAttribute(key, value);
    }
    for (const child of [].concat(children)) {
      if (child) node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
  },

  /* A block of written text as elements, keeping the shape it was written in.

     Descriptions and help texts are written with blank lines between
     paragraphs, and commands you are meant to type are written indented.
     Dropping all of that into one <p> ran three separate shell commands
     together on one line, with no way to see where each ended. So: a blank
     line starts a new paragraph, and a run of indented lines becomes a block
     that keeps its spacing and its fixed-width type. */
  prose(text, cls = '') {
    const out = [];
    for (const block of String(text || '').split(/\n\s*\n/)) {
      const lines = block.split('\n');
      if (!lines.join('').trim()) continue;
      const indented = lines.every((line) => !line.trim() || /^\s{2,}/.test(line));
      if (indented) {
        const dedent = Math.min(...lines.filter((l) => l.trim())
          .map((l) => l.match(/^\s*/)[0].length));
        out.push(UI.el('pre', { class: 'prose-code',
          text: lines.map((l) => l.slice(dedent)).join('\n').replace(/\s+$/, '') }));
      } else {
        out.push(UI.el('p', { class: cls,
          text: lines.map((l) => l.trim()).join(' ') }));
      }
    }
    return out;
  },

  toast(message, kind = 'info', ms = 4200) {
    const stack = document.getElementById('toast-stack');
    const node = UI.el('div', { class: `toast ${kind}`, text: message });
    stack.appendChild(node);
    setTimeout(() => {
      node.style.opacity = '0';
      node.style.transition = 'opacity .25s';
      setTimeout(() => node.remove(), 260);
    }, ms);
    return node;
  },

  status(message) {
    document.getElementById('status-message').textContent = message;
  },

  bytes(size) {
    if (!size) return '0 B';
    const units = ['B', 'kB', 'MB', 'GB', 'TB'];
    const index = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)));
    return `${(size / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
  },

  duration(seconds) {
    if (!seconds || seconds < 0) return '';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
  },

  copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        () => UI.toast('copied to clipboard', 'ok', 1800),
        () => UI.fallbackCopy(text));
    } else {
      UI.fallbackCopy(text);
    }
  },

  fallbackCopy(text) {
    // http://localhost is not a secure context in every browser build.
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); UI.toast('copied to clipboard', 'ok', 1800); }
    catch (err) { UI.toast('could not copy — select the text manually', 'warn'); }
    area.remove();
  },

  /* Dialogs that open other dialogs, and can get back.

     Environments opens Set up this machine, which used to be a one-way trip:
     the only way back was to close and start again. A dialog that can be
     returned to passes `reopen`, a function that re-renders it from scratch;
     opening anything on top of it pushes that onto a stack and puts a back
     arrow in the header. Re-rendering rather than hiding and showing keeps it
     honest -- coming back to Environments after installing something shows the
     thing you just installed. */
  _modalStack: [],
  _modalReopen: null,

  /* Which dialog is on screen, counted up every time one opens.

     Several dialogs ask the server something and then reach for their own
     button to relabel it -- "Missing build tools", "Requirements missing".
     They reach for it by looking it up in the page, and by the time the answer
     comes back the page may be showing somebody else's dialog, whose button
     then gets the wrong words and is greyed out. Taking the number when the
     dialog opens and checking it before writing is how a late answer knows to
     keep quiet. */
  _generation: 0,

  stillShowing(generation) {
    return UI._generation === generation;
  },

  modal(title, bodyNode, buttons = [], opts = {}) {
    // A second dialog is always on top of the first. Replacing the first while
    // the second is up would leave the new one buried under it.
    if (UI._subOpen) UI.closeSubModal();
    UI._generation += 1;
    const backdrop = document.getElementById('modal-backdrop');
    const open = !backdrop.classList.contains('hidden');
    if (open && UI._modalReopen && UI._modalReopen !== opts.reopen) {
      UI._modalStack.push({
        title: document.getElementById('modal-title').textContent,
        reopen: UI._modalReopen,
      });
    }
    UI._modalReopen = opts.reopen || null;
    UI._paintBack();
    document.getElementById('modal-title').textContent = title;
    const body = document.getElementById('modal-body');
    body.innerHTML = '';
    body.appendChild(bodyNode);
    const footer = document.getElementById('modal-footer');
    footer.innerHTML = '';
    for (const button of buttons) {
      footer.appendChild(UI.el('button', {
        class: button.primary ? 'primary' : '',
        text: button.label,
        onclick: () => { if (!button.action || button.action() !== false) UI.closeModal(); },
      }));
    }
    backdrop.classList.remove('hidden');
    return body;
  },

  _paintBack() {
    const button = document.getElementById('modal-back');
    const previous = UI._modalStack[UI._modalStack.length - 1];
    button.classList.toggle('hidden', !previous);
    button.title = previous ? `Back to ${previous.title}` : 'Back';
  },

  modalBack() {
    const previous = UI._modalStack.pop();
    if (!previous) { UI.closeModal(); return; }
    // Cleared first: the reopen call is about to set its own.
    UI._modalReopen = null;
    previous.reopen();
  },

  /* A dialog opened from inside a dialog.

     The stack above re-renders: going back calls the previous dialog's own
     drawing function again. That is right for a settings page, which can draw
     itself from what is saved, and wrong for a half-filled form, which cannot
     -- nothing it holds has been saved anywhere yet. So a dialog opened from
     inside another one goes here instead: its own layer, on top, leaving the
     first one's contents untouched underneath. */
  _subOpen: false,

  /* `opts.wide` gives the second dialog the same size as the first. The
     default is a little narrower, so the edge of what is underneath stays
     visible and it is obvious that something is on top of it -- but a dialog
     with a table or a script in it needs the room more than it needs the
     hint. */
  subModal(title, bodyNode, buttons = [], opts = {}) {
    UI._generation += 1;
    document.getElementById('submodal').classList.toggle('wide', Boolean(opts.wide));
    // Nothing below can be clicked or tabbed into while this is up. Without
    // it the Tab key walks through the form behind the file browser, which is
    // both confusing and a way to change something you cannot see.
    document.getElementById('modal').inert = true;
    document.getElementById('submodal-title').textContent = title;
    const body = document.getElementById('submodal-body');
    body.innerHTML = '';
    body.appendChild(bodyNode);
    const footer = document.getElementById('submodal-footer');
    footer.innerHTML = '';
    for (const button of buttons) {
      footer.appendChild(UI.el('button', {
        class: button.primary ? 'primary' : '',
        text: button.label,
        onclick: () => { if (!button.action || button.action() !== false) UI.closeSubModal(); },
      }));
    }
    document.getElementById('submodal-backdrop').classList.remove('hidden');
    UI._subOpen = true;
    return body;
  },

  closeSubModal() {
    document.getElementById('submodal-backdrop').classList.add('hidden');
    document.getElementById('submodal-body').innerHTML = '';
    document.getElementById('modal').inert = false;
    UI._subOpen = false;
    UI._generation += 1;
  },

  /* Is a dialog already on screen? What a dialog asks before opening another,
     so it can put it on the layer above instead of on top of the answer
     somebody is in the middle of typing. */
  modalOpen() {
    return !document.getElementById('modal-backdrop').classList.contains('hidden');
  },

  /* Is anything at all on screen over the graph? What the keyboard asks before
     letting a shortcut through. */
  anyDialogOpen() {
    return UI.modalOpen() || UI._subOpen;
  },

  /* Closes the top one. Escape and the × of the second dialog both come
     through here, and neither should throw away the dialog underneath. */
  closeModal() {
    if (UI._subOpen) { UI.closeSubModal(); return; }
    UI._generation += 1;
    document.getElementById('modal-backdrop').classList.add('hidden');
    UI._modalStack = [];
    UI._modalReopen = null;
    UI._paintBack();
  },

  contextMenu(x, y, items) {
    const menu = document.getElementById('context-menu');
    menu.innerHTML = '';
    for (const item of items) {
      if (item === '-') { menu.appendChild(UI.el('div', { class: 'sep' })); continue; }
      // A colour choice is one row of squares, not nine lines of text.
      if (item.swatches) {
        const row = UI.el('div', { class: 'swatches' });
        for (const swatch of item.swatches) {
          const dot = UI.el('button', {
            class: 'swatch', title: swatch.label,
            onclick: () => { menu.classList.add('hidden'); swatch.action(); },
          });
          dot.style.background = swatch.color;
          row.appendChild(dot);
        }
        menu.appendChild(row);
        continue;
      }
      const row = UI.el('div', {
        class: 'item',
        onclick: () => { menu.classList.add('hidden'); item.action(); },
      }, [UI.el('span', { text: item.label })]);
      if (item.hint) row.appendChild(UI.el('span', { class: 'hint', text: item.hint }));
      menu.appendChild(row);
    }
    menu.classList.remove('hidden');
    menu.style.left = `${Math.min(x, window.innerWidth - 190)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - menu.offsetHeight - 10)}px`;
  },
};

document.addEventListener('click', (event) => {
  const menu = document.getElementById('context-menu');
  if (!menu.contains(event.target)) menu.classList.add('hidden');
});
document.getElementById('modal-close').addEventListener('click', UI.closeModal);
document.getElementById('modal-back').addEventListener('click', UI.modalBack);
document.getElementById('modal-backdrop').addEventListener('mousedown', (event) => {
  // Only when the second dialog is not the one being aimed at: clicking beside
  // a file browser must not take the form underneath it away as well.
  if (event.target.id === 'modal-backdrop' && !UI._subOpen) UI.closeModal();
});
document.getElementById('submodal-close').addEventListener('click', UI.closeSubModal);
document.getElementById('submodal-backdrop').addEventListener('mousedown', (event) => {
  if (event.target.id === 'submodal-backdrop') UI.closeSubModal();
});
