/* Sessions: several workflows open at once, each with its own run.

   The server already runs one thread per run and keeps them apart, so a
   session is a browser-side idea: a graph, a name, an output folder, and at
   most one run of its own. Only the active session's graph is in the editor —
   the rest keep their node statuses and their log in memory, and their event
   stream stays open so a run you switched away from still finishes, still
   updates its tab, and still tells you when it is done. */
'use strict';

const MAX_SESSION_LOG = 2000;

const Sessions = {
  list: [],
  activeId: null,
  /* Set by App: called after the active session changes, with (session). */
  onSwitch: null,
  /* Set by App: called whenever a session's run state changes, with (session). */
  onRunUpdate: null,
  _counter: 1,

  /* --------------------------------------------------------------- model */
  make(name, graph) {
    const id = `s${Date.now().toString(36)}${(this._counter++).toString(36)}`;
    return {
      id,
      name: name || 'untitled',
      graph: graph || { version: 1, nodes: [], links: [] },
      outputDir: '',
      // node id -> the file that node's picture was last drawn from. Belongs to
      // the session for the same reason node statuses do: switching tabs must
      // not show you another workflow's results.
      previews: {},
      run: null,
      stop: null,
      unseen: false,
      // Snapshots of a large graph are megabytes, so this lives in memory for
      // the life of the tab and is not written to localStorage.
      history: null,
    };
  },

  active() {
    return this.list.find((s) => s.id === this.activeId) || null;
  },

  get(id) {
    return this.list.find((s) => s.id === id) || null;
  },

  /* Anything with a live run: used to warn before closing the page. */
  running() {
    return this.list.filter((s) => s.run && s.run.status === 'running');
  },

  /* -------------------------------------------------------------- switch */
  add(name, graph, { activate = true } = {}) {
    const session = this.make(name, graph);
    this.list.push(session);
    if (activate) this.switchTo(session.id);
    else this.render();
    return session;
  },

  switchTo(id) {
    const target = this.get(id);
    if (!target || id === this.activeId) { this.render(); return; }

    const current = this.active();
    if (current) {
      current.graph = Editor.toJSON();
      // Undo belongs to the workflow you were editing, not to the editor.
      current.history = Editor.exportHistory();
    }

    this.activeId = id;
    target.unseen = false;
    Editor.fromJSON(target.graph);
    Editor.importHistory(target.history);
    // The statuses belong to the session, not to the editor, so they have to
    // be painted back on after the graph is reloaded.
    this.repaint(target);
    this.render();
    if (this.onSwitch) this.onSwitch(target);
  },

  close(id) {
    const session = this.get(id);
    if (!session) return false;
    if (session.run && session.run.status === 'running'
        && !confirm(`"${session.name}" is still running. Close it anyway?\n\n`
                    + 'The run keeps going on the server; you just stop watching it.')) {
      return false;
    }
    if (session.stop) { session.stop(); session.stop = null; }
    const index = this.list.indexOf(session);
    this.list.splice(index, 1);
    if (!this.list.length) this.add('untitled');
    else if (this.activeId === id) {
      this.activeId = null;
      this.switchTo(this.list[Math.max(0, index - 1)].id);
    } else this.render();
    return true;
  },

  rename(id, name) {
    const session = this.get(id);
    if (!session) return;
    session.name = name || 'untitled';
    this.render();
  },

  /* ----------------------------------------------------------- run state */
  beginRun(session, runId, order, workdir = '') {
    session.run = {
      id: runId, status: 'running', order: order || [], workdir,
      statuses: {}, lines: [], logNode: null, logPinned: false,
    };
    for (const nodeId of session.run.order) {
      session.run.statuses[nodeId] = { status: 'pending', error: '' };
    }
    this.render();
  },

  noteNode(session, nodeId, status, error) {
    if (!session.run) return;
    session.run.statuses[nodeId] = { status, error: error || '' };
    if (session.id !== this.activeId) session.unseen = true;
    this.render();
  },

  /* Put back everything that belongs to the session rather than to the graph.

     Node statuses and previews both live outside the graph JSON, so both are
     lost whenever the editor rebuilds its node objects -- which happens when
     you switch sessions and on every undo. */
  repaint(session) {
    if (!session) return;
    Editor.resetStatuses();
    if (session.run) {
      for (const [nodeId, state] of Object.entries(session.run.statuses || {})) {
        Editor.setStatus(nodeId, state.status, { error: state.error || '' });
      }
    }
    for (const [nodeId, path] of Object.entries(session.previews || {})) {
      NodePreview.setPath(nodeId, path);
    }
  },

  /* Where a preview node's picture comes from, remembered across a switch
     and a reload. Only the path is kept -- the atoms are re-read on demand. */
  notePreview(session, nodeId, path) {
    if (!path) return;
    session.previews[nodeId] = path;
  },

  noteLine(session, line) {
    if (!session.run) return;
    session.run.lines.push(line);
    if (session.run.lines.length > MAX_SESSION_LOG) session.run.lines.shift();
  },

  noteStatus(session, status) {
    if (!session.run) return;
    session.run.status = status;
    if (session.id !== this.activeId && status !== 'running') session.unseen = true;
    this.render();
    if (this.onRunUpdate) this.onRunUpdate(session);
  },

  /* ----------------------------------------------------------------- ui */
  /* The strip is updated in place, never rebuilt.

     It used to begin with `host.innerHTML = ''`, and that quietly cost two
     things. A double click only happens when both of its clicks land on the
     same element -- and the first click switched session, which re-rendered,
     which replaced the very element being clicked, so the browser saw two
     unrelated single clicks and never fired dblclick at all. Renaming by
     double click therefore did not work, on any tab, ever. The second cost:
     a run repaints this strip on every node status change, which would have
     torn a half-typed name out from under the cursor. */
  render() {
    const host = document.getElementById('session-tabs');
    if (!host) return;

    const wanted = new Set(this.list.map((s) => s.id));
    for (const el of Array.from(host.children)) {
      if (el.dataset.session && !wanted.has(el.dataset.session)) el.remove();
    }

    let previous = null;
    for (const session of this.list) {
      const tab = this.tabFor(host, session);
      this.paintTab(tab, session);
      // Only move a tab that is actually in the wrong place: re-inserting an
      // element blurs whatever is focused inside it.
      const anchor = previous ? previous.nextSibling : host.firstChild;
      if (anchor !== tab) host.insertBefore(tab, anchor);
      previous = tab;
    }

    let add = host.querySelector('.session-add');
    if (!add) {
      add = UI.el('button', {
        class: 'session-add', text: '+', title: 'New session (Ctrl+Shift+N)',
        onclick: () => this.add('untitled'),
      });
    }
    if (host.lastChild !== add) host.appendChild(add);

    const current = this.active();
    const folder = document.getElementById('session-output');
    if (folder && current) {
      folder.textContent = current.outputDir || 'default run folder';
      folder.title = current.outputDir
        ? `Run directories are created under ${current.outputDir}`
        : 'Run directories go under the folder set in Settings';
      folder.classList.toggle('custom', !!current.outputDir);
    }
    // Say which folder the button will open before it is pressed, because
    // after a run it changes from "where runs go" to "where the last one
    // went" and a button that opens somewhere different each time without
    // saying so is a button you stop trusting.
    const open = document.getElementById('btn-open-folder');
    if (open && current && typeof App !== 'undefined' && App.workFolder) {
      const want = App.workFolder();
      open.title = `Open ${want.path || want.what} in the desktop file manager`;
    }
  },

  /* The element for one session, made once and then kept. Handlers look the
     session up by id when the event arrives rather than closing over the
     object: restore() builds fresh session objects, and the id is what both
     sides agree on. */
  tabFor(host, session) {
    const found = host.querySelector(`[data-session="${session.id}"]`);
    if (found) return found;
    const id = session.id;
    const tab = UI.el('div', { class: 'session-tab' }, [
      UI.el('span', { class: 'session-name', text: session.name }),
      UI.el('button', {
        class: 'session-close', text: '\u00d7', title: 'Close this session',
        onclick: (event) => { event.stopPropagation(); this.close(id); },
      }),
    ]);
    tab.dataset.session = id;
    tab.addEventListener('click', () => this.switchTo(id));
    tab.addEventListener('dblclick', (event) => {
      event.stopPropagation();
      this.renameInPlace(id);
    });
    tab.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      const live = this.get(id);
      if (live) this.menu(event, live);
    });
    return tab;
  },

  /* Bring one tab up to date. Every piece is written only if it changed:
     reassigning the dot's class restarts its pulse animation, and rewriting
     the label would fight whoever is typing in it. */
  paintTab(tab, session) {
    const want = `session-tab${session.id === this.activeId ? ' active' : ''}`
               + (session.unseen ? ' unseen' : '');
    if (tab.className !== want) tab.className = want;
    const title = session.outputDir
      ? `output: ${session.outputDir}`
      : 'output: the default run folder';
    if (tab.title !== title) tab.title = title;

    const status = session.run ? session.run.status : '';
    let dot = tab.querySelector('.session-dot');
    if (status && !dot) {
      dot = UI.el('span', {});
      tab.insertBefore(dot, tab.firstChild);
    } else if (!status && dot) {
      dot.remove();
      dot = null;
    }
    if (dot && dot.className !== `session-dot ${status}`) {
      dot.className = `session-dot ${status}`;
    }

    const label = tab.querySelector('.session-name');
    if (label && !label.dataset.editing && label.textContent !== session.name) {
      label.textContent = session.name;
    }
  },

  /* Edit the tab's own label rather than opening a dialog to edit a word.

     Enter keeps it, Escape puts it back, clicking elsewhere keeps it -- which
     is what every other rename-in-place in every other program does, so there
     is nothing to learn. An empty name falls back to the one it had; a tab
     with no name is a tab you cannot tell from the next one. */
  renameInPlace(id) {
    const host = document.getElementById('session-tabs');
    const session = this.get(id);
    if (!session || !host) return;
    const tab = host.querySelector(`[data-session="${id}"]`);
    const label = tab && tab.querySelector('.session-name');
    if (!label || label.dataset.editing) return;
    const was = session.name;
    label.dataset.editing = '1';
    label.contentEditable = 'true';
    label.spellcheck = false;
    label.classList.add('editing');
    label.focus();
    const range = document.createRange();
    range.selectNodeContents(label);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);

    const stop = (keep) => {
      if (!label.dataset.editing) return;
      delete label.dataset.editing;
      label.contentEditable = 'false';
      label.classList.remove('editing');
      const typed = label.textContent.trim();
      label.removeEventListener('keydown', onKey);
      label.removeEventListener('blur', onBlur);
      // The name is what needs putting back, if this was a cancel; the
      // element itself stays where it is.
      this.rename(session.id, keep && typed ? typed : was);
    };
    const onKey = (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') { event.preventDefault(); stop(true); }
      else if (event.key === 'Escape') { event.preventDefault(); stop(false); }
    };
    const onBlur = () => stop(true);
    label.addEventListener('keydown', onKey);
    label.addEventListener('blur', onBlur);
  },

  /* Right-click a tab. The things people want from a tab strip and had to go
     three places for: renaming it, copying it to try something without losing
     what works, and where its runs go. */
  menu(event, session) {
    const others = this.list.filter((s) => s.id !== session.id);
    UI.contextMenu(event.clientX, event.clientY, [
      { label: 'Rename', action: () => {
        this.switchTo(session.id);
        this.renameInPlace(session.id);
      } },
      { label: 'Duplicate', action: () => {
        if (session.id === this.activeId) session.graph = Editor.toJSON();
        this.add(`${session.name} copy`, JSON.parse(JSON.stringify(session.graph || {})));
      } },
      '-',
      { label: session.outputDir ? 'Output folder…' : 'Set an output folder…',
        action: () => { this.switchTo(session.id); App.chooseOutputDir(); } },
      '-',
      { label: 'Close', action: () => this.close(session.id) },
      ...(others.length ? [{ label: `Close the other ${others.length}`,
        action: () => {
          if (!confirm(`Close ${others.length} session`
            + `${others.length === 1 ? '' : 's'}? Anything unsaved in them goes.`)) return;
          for (const other of others) this.close(other.id);
        } }] : []),
    ]);
  },

  /* -------------------------------------------------------- persistence */
  persist() {
    try {
      const current = this.active();
      if (current) current.graph = Editor.toJSON();
      localStorage.setItem('comfygmx.sessions', JSON.stringify({
        active: this.activeId,
        list: this.list.map((s) => ({
          id: s.id, name: s.name, graph: s.graph, outputDir: s.outputDir,
          previews: s.previews,
          // The run id is kept so a reload can reattach to a run still going.
          run: s.run ? { id: s.run.id, status: s.run.status } : null,
        })),
      }));
    } catch (err) { /* private mode, quota — not worth interrupting for */ }
  },

  restore() {
    let stored = null;
    try { stored = JSON.parse(localStorage.getItem('comfygmx.sessions') || 'null'); }
    catch (err) { stored = null; }

    if (!stored || !Array.isArray(stored.list) || !stored.list.length) {
      // First run here, or an older version that stored a single graph.
      let graph = null;
      try { graph = JSON.parse(localStorage.getItem('comfygmx.graph') || 'null'); }
      catch (err) { graph = null; }
      const name = localStorage.getItem('comfygmx.name') || 'untitled';
      const session = this.make(graph && graph.nodes && graph.nodes.length ? name : 'untitled',
                                graph || undefined);
      this.list = [session];
      this.activeId = session.id;
      return { migrated: !!(graph && graph.nodes && graph.nodes.length) };
    }

    this.list = stored.list.map((raw) => {
      const session = this.make(raw.name, raw.graph);
      session.id = raw.id || session.id;
      session.outputDir = raw.outputDir || '';
      session.previews = raw.previews || {};
      session.pendingRun = raw.run && raw.run.status === 'running' ? raw.run.id : null;
      return session;
    });
    this.activeId = stored.active && this.get(stored.active)
      ? stored.active : this.list[0].id;
    return { migrated: false };
  },
};
