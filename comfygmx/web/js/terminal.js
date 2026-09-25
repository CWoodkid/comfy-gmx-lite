/* The drawer under the canvas: one continuous transcript of a run.

   The Log tab shows one node at a time, which is right when you are reading a
   failure and wrong when the question is "what is it doing". This is the other
   view: every node in order, the command each one actually ran, its output and
   how it ended, scrolling past as it happens.

   You can type into it, but it is not a shell: what runs is what the graph
   says. The line at the bottom does two things a real terminal does, and
   nothing else.

     * What you type goes to the command that is running now, so a program that
       stops to ask a question can be answered instead of the run being thrown
       away. Ctrl+D closes its input, the same as in a terminal.
     * Ctrl+C stops the run. Press it again and it kills everything outright,
       which is also what pressing Cancel twice does. */

const Terminal = {
  MAX_LINES: 6000,
  MIN_HEIGHT: 90,

  open: false,
  height: 210,
  follow: true,
  el: null,
  body: null,
  input: null,
  /* Which node's command we are typing at. Set when the server says one is
     waiting for an answer; otherwise the server picks, as long as only one
     node is running. */
  waitingFor: '',
  /* What you typed before, so Up/Down walks back through it. */
  history: [],
  histAt: -1,

  init() {
    this.el = document.getElementById('terminal');
    this.body = document.getElementById('terminal-body');
    if (!this.el) return;

    const stored = this._load();
    this.height = stored.height || this.height;
    this.follow = stored.follow !== false;
    document.getElementById('terminal-follow').checked = this.follow;

    document.getElementById('terminal-handle').addEventListener('click', () => this.toggle());
    document.getElementById('terminal-close').addEventListener('click', () => this.toggle(false));
    document.getElementById('terminal-clear').addEventListener('click', () => {
      const session = Sessions.active();
      if (session) session.terminal = [];
      this.body.innerHTML = '';
    });
    document.getElementById('terminal-copy').addEventListener('click', () => {
      UI.copy(this.body.textContent);
    });
    document.getElementById('terminal-follow').addEventListener('change', (event) => {
      this.follow = event.target.checked;
      this._save();
      if (this.follow) this.body.scrollTop = this.body.scrollHeight;
    });
    this._bindInput();
    this._bindResize();
    this.toggle(stored.open === true, true);
  },

  /* ------------------------------------------------------------ typing in */

  _bindInput() {
    this.input = document.getElementById('terminal-input');
    if (!this.input) return;
    const row = document.getElementById('terminal-input-row');

    this.input.addEventListener('keydown', (event) => {
      // Ctrl+C: stop the run, exactly as in a terminal. If text is selected,
      // let the browser copy it instead -- that is what the user meant.
      if (event.key === 'c' && (event.ctrlKey || event.metaKey)) {
        if (String(window.getSelection() || '').length) return;
        event.preventDefault();
        this.interrupt();
        return;
      }
      if (event.key === 'd' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        this.sendEof();
        return;
      }
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (!this.history.length) return;
        event.preventDefault();
        if (this.histAt < 0) this.histAt = this.history.length;
        this.histAt += event.key === 'ArrowUp' ? -1 : 1;
        this.histAt = Math.max(0, Math.min(this.history.length, this.histAt));
        this.input.value = this.history[this.histAt] || '';
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        this.sendLine(this.input.value);
        this.input.value = '';
        this.histAt = -1;
      }
    });

    // The same keys work anywhere in the drawer, not only in the box.
    this.el.addEventListener('keydown', (event) => {
      if (event.target === this.input) return;
      if (event.key === 'c' && (event.ctrlKey || event.metaKey)
          && !String(window.getSelection() || '').length) {
        event.preventDefault();
        this.interrupt();
      }
    });

    document.getElementById('terminal-eof').addEventListener('click', () => this.sendEof());
    document.getElementById('terminal-stop').addEventListener('click', () => this.interrupt());
    if (row) row.addEventListener('click', (event) => {
      if (event.target === row || event.target.id === 'terminal-prompt') this.input.focus();
    });
  },

  /* A run is happening and something in it is asking a question. */
  setWaiting(session, nodeId, waiting) {
    if (!session || session.id !== Sessions.activeId) return;
    this.waitingFor = waiting ? (nodeId || '') : '';
    const row = document.getElementById('terminal-input-row');
    if (row) row.classList.toggle('waiting', Boolean(waiting));
    if (!waiting) return;
    // Worth interrupting for: the run is stopped until somebody answers.
    if (!this.open) this.toggle(true);
    if (this.input) this.input.focus();
  },

  async sendLine(text) {
    const session = Sessions.active();
    if (!session || !session.run) { UI.toast('nothing is running', 'warn'); return; }
    if (text.trim()) {
      this.history.push(text);
      if (this.history.length > 100) this.history.shift();
    }
    // No echo here: the server puts the line in the run's own log, which
    // comes straight back down the same stream. Echoing as well showed it
    // twice.
    try {
      const result = await API.sendInput(session.run.id,
        { node: this.waitingFor, text });
      if (!result.sent) {
        this.push(session, { kind: 'warn', node: '',
                             text: result.error || 'it did not get there' });
      }
    } catch (err) {
      this.push(session, { kind: 'err', node: '', text: err.message });
    }
  },

  async sendEof() {
    const session = Sessions.active();
    if (!session || !session.run) { UI.toast('nothing is running', 'warn'); return; }
    try {
      const result = await API.sendInput(session.run.id,
        { node: this.waitingFor, eof: true });
      if (!result.sent) {
        this.push(session, { kind: 'warn', node: '',
                             text: result.error || 'nothing was reading input' });
      }
    } catch (err) {
      this.push(session, { kind: 'err', node: '', text: err.message });
    }
  },

  /* Ctrl+C. The first one asks the run to stop; a second one, while it is
     still stopping, kills it outright. */
  interrupt() {
    const session = Sessions.active();
    if (!session || !session.run) { UI.toast('nothing is running', 'warn'); return; }
    const settled = ['done', 'error', 'cancelled'].includes(session.run.status);
    if (settled) { UI.toast('that run has already finished', 'info'); return; }
    this.push(session, { kind: 'in', node: '', text: '^C' });
    App.cancel(session.run.status === 'cancelling');
  },

  toggle(force, quiet = false) {
    this.open = force === undefined ? !this.open : Boolean(force);
    this.el.classList.toggle('hidden', !this.open);
    this.el.style.height = `${this.height}px`;
    // The handle is the closed state of the drawer, so it goes away when the
    // drawer is out -- the drawer's own header has the button that shuts it.
    document.getElementById('terminal-handle').classList.toggle('hidden', this.open);
    if (this.open) {
      this.repaint(Sessions.active());
      this.body.scrollTop = this.body.scrollHeight;
    }
    if (!quiet) this._save();
  },

  /* --------------------------------------------------------------- content */

  /* Kept on the session, not on the DOM: a run you switched away from keeps
     writing, and switching back has to show what it wrote. */
  push(session, entry) {
    if (!session) return;
    if (!session.terminal) session.terminal = [];
    session.terminal.push(entry);
    if (session.terminal.length > this.MAX_LINES) session.terminal.shift();
    if (!this.open || session.id !== Sessions.activeId) return;
    this._draw(entry);
    if (this.follow) this.body.scrollTop = this.body.scrollHeight;
  },

  repaint(session) {
    if (!this.body) return;
    this.body.innerHTML = '';
    for (const entry of (session && session.terminal) || []) this._draw(entry);
    this.body.scrollTop = this.body.scrollHeight;
  },

  _draw(entry) {
    const line = UI.el('div', { class: `t-line t-${entry.kind}` });
    if (entry.node) {
      line.appendChild(UI.el('span', { class: 't-node', text: entry.node, title: entry.node }));
    }
    line.appendChild(UI.el('span', { class: 't-text', text: entry.text }));
    this.body.appendChild(line);
  },

  /* A line from something that is not a node in a graph: installing a tool,
     setting the machine up. They belong in the same transcript, because "what
     is this program doing right now" should be one place to look rather than
     two -- and unlike a dialog, the transcript is still there afterwards.

     `push` wants the session and a made-up entry, which is easy to get wrong
     from a dialog: three call sites passed a bare string as the session and
     threw on the spot, so the install ran on the server with nothing on
     screen at all. */
  say(text, who = '', kind = 'step') {
    this.push(Sessions.active(), { kind, node: who, text: String(text) });
  },

  /* --------------------------------------------------------------- events */

  /* One place that knows how a run event reads as a line of transcript, so the
     event handler stays about state and this stays about words. */
  note(session, event, title) {
    const who = title || event.node || '';
    switch (event.type) {
      case 'node':
        if (event.status === 'running') {
          this.push(session, { kind: 'head', node: '', text: `▶ ${who}` });
        } else if (event.status === 'cached') {
          this.push(session, { kind: 'cached', node: who, text: 'cached, nothing to do' });
        } else if (event.status === 'done') {
          this.push(session, { kind: 'ok', node: who, text: 'done' });
        } else if (event.status === 'error') {
          this.push(session, { kind: 'err', node: who,
                               text: `failed — ${event.error || 'see the log'}` });
        } else if (event.status === 'skipped') {
          this.push(session, { kind: 'dim', node: who,
                               text: `skipped${event.error ? ` — ${event.error}` : ''}` });
        } else if (event.status === 'cancelled') {
          this.push(session, { kind: 'warn', node: who, text: 'cancelled' });
        }
        break;
      case 'step':
        this.push(session, { kind: 'step', node: who, text: `» ${event.label}` });
        if (event.command) {
          this.push(session, { kind: 'cmd', node: '', text: `  $ ${event.command}` });
        }
        break;
      case 'log':
        // Lines the server marks as typed input are shown as such.
        this.push(session, {
          kind: /^(> |\^D)/.test(event.line) ? 'in'
                : event.line.startsWith('?? ') ? 'warn' : 'out',
          node: '', text: event.line });
        break;
      case 'waiting':
        // Handled by setWaiting; the transcript already carries the ?? line
        // the node itself logged.
        break;
      case 'run':
        this.push(session, { kind: 'run', node: '',
                             text: `── run ${event.status}`
                                   + (event.hard ? ' (killing it outright)' : '') });
        break;
      default:
        break;
    }
  },

  /* ---------------------------------------------------------------- chrome */

  status(text, running) {
    const el = document.getElementById('terminal-status');
    if (el) el.textContent = text;
    const dot = document.getElementById('terminal-dot');
    if (dot) dot.className = `t-dot${running ? ' running' : ''}`;
    // A closed drawer still says whether anything is running, which is most of
    // why anyone would open it.
    const handle = document.getElementById('terminal-handle');
    if (handle) handle.classList.toggle('busy', Boolean(running));
    const handleDot = document.getElementById('handle-dot');
    if (handleDot) handleDot.className = `t-dot${running ? ' running' : ''}`;
    const label = document.getElementById('handle-label');
    if (label) label.textContent = running ? text : 'Terminal';
  },

  _bindResize() {
    const grip = document.getElementById('terminal-grip');
    grip.addEventListener('mousedown', (event) => {
      event.preventDefault();
      const startY = event.clientY;
      const startH = this.el.offsetHeight;
      const move = (m) => {
        const wrap = document.getElementById('canvas-wrap').offsetHeight;
        this.height = Math.max(this.MIN_HEIGHT,
          Math.min(wrap - 60, startH + (startY - m.clientY)));
        this.el.style.height = `${this.height}px`;
      };
      const stop = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', stop);
        this._save();
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', stop);
    });
  },

  _load() {
    try { return JSON.parse(localStorage.getItem('comfygmx.terminal') || '{}'); }
    catch (err) { return {}; }
  },

  _save() {
    try {
      localStorage.setItem('comfygmx.terminal', JSON.stringify({
        open: this.open, height: this.height, follow: this.follow,
      }));
    } catch (err) { /* private mode */ }
  },
};
