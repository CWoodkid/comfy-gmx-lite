/* The drawer under the canvas. It has two tabs.

   Run: one continuous transcript of a run. The Log tab shows one node at a
   time, which is right when you are reading a failure and wrong when the
   question is "what is it doing". This is the other view: every node in
   order, the command each one actually ran, its output and how it ended,
   scrolling past as it happens.

   Shell: real bash shells on this machine, the same as terminal windows,
   several at once if wanted (ShellWindow and ShellTab at the end of this
   file).

   You can type into the Run tab too, but it is not a shell: what runs is
   what the graph says. Its line at the bottom does two things a real
   terminal does, and nothing else.

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
  /* Which tab is showing: 'run' or 'shell'. */
  tab: 'run',
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
    document.getElementById('terminal-tab-run').addEventListener('click', () => this.showTab('run'));
    document.getElementById('terminal-tab-shell').addEventListener('click', () => this.showTab('shell'));
    this._bindInput();
    this._bindResize();
    ShellTab.init();
    this.showTab(stored.tab === 'shell' ? 'shell' : 'run', true);
    this.toggle(stored.open === true, true);
  },

  /* Run or Shell. The shell is started the first time its tab is shown with
     the drawer open, not before: most visits never need one. */
  showTab(name, quiet = false) {
    this.tab = name === 'shell' ? 'shell' : 'run';
    const shell = this.tab === 'shell';
    document.getElementById('terminal-tab-run').classList.toggle('active', !shell);
    document.getElementById('terminal-tab-shell').classList.toggle('active', shell);
    for (const el of this.el.querySelectorAll('.for-run')) el.classList.toggle('hidden', shell);
    for (const el of this.el.querySelectorAll('.for-shell')) el.classList.toggle('hidden', !shell);
    if (this.open) {
      if (shell) ShellTab.show();
      else this.body.scrollTop = this.body.scrollHeight;
    }
    if (!quiet) this._save();
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
      if (this.tab === 'shell') ShellTab.show();
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
    // Only the one class changes: the dot also carries which tab it is on.
    if (dot) dot.classList.toggle('running', Boolean(running));
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
        open: this.open, height: this.height, follow: this.follow, tab: this.tab,
      }));
    } catch (err) { /* private mode */ }
  },
};

/* The drawer's Shell tab: real shells on this machine, as many side by side
   as you like (up to the server's limit), each in a numbered tab of its own
   in the strip above the screen. + opens another; × on a tab ends that one.

   Each screen is vt.js; each shell runs on the server (comfygmx/shell.py)
   and talks to its screen over a WebSocket of its own, a connection that
   stays open both ways, so each key goes straight to the shell and its
   output comes straight back. A shell whose tab is not on screen stays
   connected: what it prints is on its screen when its tab is chosen again,
   and the server does not take it for a shell whose page has gone.

   The shells belong to this browser tab, not to a graph tab: switching
   between graphs keeps them. Reloading the page finds them again (the server
   keeps a shell for a minute without a page), because a reload should not
   kill a command somebody started from one. */

/* One shell: its screen, its connection to the server, and what it is doing.
   ShellTab, below, keeps them and draws their tabs. */
class ShellWindow {
  constructor(number, id = '') {
    /* The number on its tab, kept for as long as the shell is. */
    this.number = number;
    /* The server's name for it, kept for the length of this browser tab
       (sessionStorage), so a reload can ask for the same one back. */
    this.id = id;
    /* off, connecting, on, ended or refused. */
    this.state = 'off';
    /* The program in front of the shell, or '' at the prompt. */
    this.program = '';
    this.cwd = '';
    /* Why it is off or refused, in words, for the drawer's header. */
    this.detail = '';
    this.host = null;
    this.view = null;
    this.socket = null;
    this._catchup = 0;
    this._retries = 0;
    this._retryTimer = 0;
    this._closeArmed = 0;
  }

  /* Its screen, made the first time the Shell tab is shown. Hidden until
     its tab is chosen. */
  build(parent) {
    if (this.view) return;
    this.host = document.createElement('div');
    this.host.className = 'shell-screen hidden';
    parent.appendChild(this.host);
    this.view = new VT.View(this.host, {
      onData: (text) => this.type(text),
      onResize: (cols, rows) => this._send({ type: 'resize', cols, rows }),
      onCopy: (text) => ShellTab._copy(text),
      onKey: (event) => ShellTab._key(event),
    });
  }

  connect() {
    clearTimeout(this._retryTimer);
    if (this.socket || !this.view) return;
    this.state = 'connecting';
    ShellTab.paint();
    const where = ShellTab._startFolder();
    // Relative to the page, so it still works when the page is reached
    // through another server that puts it in a sub-folder.
    const url = new URL('api/shell', window.location.href);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    if (this.id) url.searchParams.set('id', this.id);
    if (where) url.searchParams.set('cwd', where);
    url.searchParams.set('cols', this.view.cols);
    url.searchParams.set('rows', this.view.rows);
    let socket;
    try {
      socket = new WebSocket(url.toString());
    } catch (err) {
      this._lost(`could not reach the server: ${err.message}`);
      return;
    }
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    socket.onmessage = (event) => this._message(event);
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.state === 'on' || this.state === 'connecting') this._lost();
    };
  }

  _message(event) {
    if (!this.view) return;
    if (typeof event.data !== 'string') {
      const bytes = new Uint8Array(event.data);
      if (this._catchup) {
        this._catchup = 0;
        this.view.replay(bytes);
      } else {
        this.view.write(bytes);
      }
      return;
    }
    let message;
    try { message = JSON.parse(event.data); } catch (err) { return; }
    switch (message.type) {
      case 'ready': {
        const again = Boolean(message.again);
        const wanted = this.id;
        this.id = message.id;
        if (message.most) ShellTab.most = message.most;
        this.state = 'on';
        this.detail = '';
        this._retries = 0;
        this.program = message.program || '';
        this.cwd = message.cwd || '';
        this._catchup = message.catchup || 0;
        if (again) {
          // The same shell as before: its screen comes back from what it
          // wrote, so start from a clean one.
          this.view.reset();
        } else {
          if (wanted && this.view.screen.scrollback.length + this.view.screen.y > 0) {
            this.view.note('The shell that was here has ended, and this is a new one.');
          }
          this.view.note(`A shell on this machine (${message.shell || 'bash'}), started in `
            + `${message.cwd}. It is the same as a terminal window: type exit to end it, `
            + 'or press + above it to open another beside it.');
        }
        ShellTab._save();
        ShellTab.paint();
        break;
      }
      case 'busy':
        this.program = message.program || '';
        if (message.cwd) this.cwd = message.cwd;
        ShellTab.paint();
        break;
      case 'exit':
        this.state = 'ended';
        this.program = '';
        this._forget();
        this.view.note(message.hung_up
          ? 'The shell was hung up. Press any key for a new one.'
          : `The shell has ended${message.code ? ` (exit code ${message.code})` : ''}. `
            + 'Press any key for a new one.');
        ShellTab.paint();
        break;
      case 'refused':
        this.state = 'refused';
        this.detail = message.why || '';
        this._forget();
        this.view.note(`No shell: ${message.why}`);
        ShellTab.paint();
        break;
      case 'taken':
        // The same shell was opened in another browser tab, which now has it.
        this.state = 'off';
        this.detail = 'shown in another browser tab';
        this.view.note('This shell is now shown in another browser tab. '
          + 'Press any key to take it back.');
        ShellTab.paint();
        break;
      default:
        break;
    }
  }

  /* The connection dropped without the shell ending: the server restarted,
     or the machine slept. Try again a few times, gently. */
  _lost(why = '') {
    this.state = 'off';
    this.detail = why || 'connection lost, trying again';
    ShellTab.paint();
    if (this._retries >= 6) {
      if (this.view) this.view.note('Lost the connection to the server. Press any key to try again.');
      this.detail = 'no connection';
      ShellTab.paint();
      return;
    }
    const wait = Math.min(8000, 500 * 2 ** this._retries);
    this._retries += 1;
    this._retryTimer = setTimeout(() => this.connect(), wait);
  }

  _forget() {
    this.id = '';
    ShellTab._save();
  }

  _send(message) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN && this.state === 'on') {
      this.socket.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /* A key, a paste or a reply from the screen, on its way to the shell. */
  type(text) {
    if (this.state === 'on') {
      this._send({ type: 'input', data: text });
      return;
    }
    if (this.state === 'connecting') return;
    // Ended, refused, lost or taken: a key starts things again.
    this._retries = 0;
    if (this.socket) {
      try { this.socket.close(); } catch (err) { /* already closed */ }
      this.socket = null;
    }
    this.connect();
  }

  /* True while a program is running in front of the shell, so leaving the
     page, or closing its tab, should ask first. */
  busy() {
    return this.state === 'on' && Boolean(this.program);
  }

  /* End it, as closing a terminal window would, and take its screen away. */
  end() {
    clearTimeout(this._retryTimer);
    this._send({ type: 'hangup' });
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      try { socket.close(); } catch (err) { /* already closed */ }
    }
    this.state = 'ended';
    this.id = '';
    if (this.host) this.host.remove();
    this.host = null;
    this.view = null;
  }

  /* A word for its tab: the program in front, or the folder it is in. */
  label() {
    if (this.state === 'on') {
      if (this.program) return this.program;
      const home = (typeof App !== 'undefined' && App.homeDir) || '';
      if (home && this.cwd === home) return '~';
      return this.cwd.split('/').filter(Boolean).pop() || '/';
    }
    return { ended: 'ended', refused: 'refused' }[this.state] || '…';
  }

  /* The longer version, for the drawer's header. */
  describe() {
    const home = (typeof App !== 'undefined' && App.homeDir) || '';
    const short = (path) => (home && path.startsWith(home) ? `~${path.slice(home.length)}` : path);
    switch (this.state) {
      case 'connecting': return 'starting…';
      case 'on': return this.program ? `running ${this.program}` : `bash · ${short(this.cwd)}`;
      case 'ended': return 'ended · press any key for a new shell';
      case 'refused': return 'refused';
      default: return this.detail || 'not started';
    }
  }
}

const ShellTab = {
  /* The shells, in the order of their numbers. */
  shells: [],
  /* The one on screen. */
  current: null,
  /* How many shells one Comfy-gmx keeps at once, for every page together
     (MAX_SHELLS in comfygmx/shell.py). Each shell's server says so. */
  most: 8,

  init() {
    document.getElementById('shell-copy').addEventListener('click', () => this.copyAll());
    document.getElementById('shell-cd').addEventListener('click', () => this.goToRunFolder());
    const saved = this._load();
    this.shells = saved.shells.map((entry) => new ShellWindow(entry.number, entry.id));
    this.current = this.shells.find((shell) => shell.number === saved.current)
      || this.shells[0] || null;
    this.paint();
  },

  /* The tab has just been shown: start a shell, or bring them all back.
     Not before: most visits never need one. */
  show() {
    const screens = document.getElementById('shell-screens');
    if (!this.shells.length) this._make();
    for (const shell of this.shells) shell.build(screens);
    const current = this.current || this.shells[0];
    // Every shell is brought back, not only the one on screen: the others
    // would be hung up a minute after a reload, and with them a command
    // started in one. Each is measured first, in place of the one on screen
    // for a moment, so it starts at the size it will be seen at.
    for (const shell of this.shells) {
      if (shell.state !== 'off' || shell === current) continue;
      this.select(shell, false);
      shell.connect();
    }
    this.select(current, false);
    if (current.state === 'off') current.connect();
  },

  /* Put one shell on screen. */
  select(shell, save = true) {
    if (!shell) return;
    this.current = shell;
    for (const other of this.shells) {
      if (other.host) other.host.classList.toggle('hidden', other !== shell);
    }
    if (shell.view) {
      // Measured now, not on the next frame: a browser tab in the background
      // draws no frames, and the shell would not start until somebody
      // looked at it.
      shell.view.fit();
      shell.view.focus();
    }
    this.paint();
    if (save) this._save();
  },

  /* +: another shell beside the ones that are open. */
  add() {
    if (this.shells.length >= this.most) {
      UI.toast(`${this.most} shells are open, which is as many as one Comfy-gmx keeps. `
        + 'Close one with the × on its tab first.', 'warn', 5000);
      return;
    }
    const shell = this._make();
    shell.build(document.getElementById('shell-screens'));
    this.select(shell);
    shell.connect();
  },

  /* A new shell with the lowest number not in use. */
  _make() {
    let number = 1;
    while (this.shells.some((shell) => shell.number === number)) number += 1;
    const shell = new ShellWindow(number);
    this.shells.push(shell);
    this.shells.sort((a, b) => a.number - b.number);
    return shell;
  },

  /* × on a tab: end that shell. A program still running in it is asked
     about first, because ending the shell ends the program too. */
  close(shell) {
    if (shell.busy() && Date.now() - shell._closeArmed > 3000) {
      shell._closeArmed = Date.now();
      UI.toast(`${shell.program} is running in shell ${shell.number}: press its × again `
        + 'within 3 seconds to end it', 'warn', 4000);
      return;
    }
    const at = this.shells.indexOf(shell);
    shell.end();
    if (at >= 0) this.shells.splice(at, 1);
    if (!this.shells.length) {
      // The last one: a fresh shell takes its place, so the tab is never
      // empty. That is also the way to start again from scratch.
      this.current = null;
      this.add();
      return;
    }
    if (this.current === shell) {
      this.current = this.shells[Math.min(Math.max(at, 0), this.shells.length - 1)];
    }
    this.select(this.current);
  },

  /* True while a program is running in any of the shells, so leaving the
     page should ask first. */
  busy() {
    return this.shells.some((shell) => shell.busy());
  },

  /* Keys the page keeps for itself even in the shell. */
  _key(event) {
    if ((event.ctrlKey || event.metaKey) && (event.key === '`' || event.key === '~')) {
      event.preventDefault();
      Terminal.toggle(false);
      return false;
    }
    return true;
  },

  /* Where a new shell starts: the folder this graph tab's last run wrote
     into, or the folder its runs go to, the same folder that "Open folder"
     opens. */
  _startFolder() {
    try {
      const folder = App.workFolder();
      return folder.path || App.outputRoot || '';
    } catch (err) {
      return '';
    }
  },

  copyAll() {
    const view = this.current && this.current.view;
    if (!view) return;
    const text = view.selectionText() || view.allText();
    if (text.trim()) this._copy(text);
    else view.focus();
  },

  /* UI.copy, but with the keyboard given back to the shell once the copy is
     done. Copying can borrow the keyboard for a moment (UI.fallbackCopy),
     and after that the next letters would go to the graph's shortcuts. */
  _copy(text) {
    const back = () => { if (this.current && this.current.view) this.current.view.focus(); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        () => { UI.toast('copied to clipboard', 'ok', 1800); back(); },
        () => { UI.fallbackCopy(text); back(); });
    } else {
      UI.fallbackCopy(text);
      back();
    }
  },

  /* cd to the folder the Open folder button would open, in the shell on
     screen. Typed only while that shell is at its prompt: into nano it
     would become part of a file. Ctrl+E and Ctrl+U first clear anything
     half-typed on that line, so the cd cannot end up glued to the end of
     some other command. */
  async goToRunFolder() {
    const shell = this.current;
    if (!shell || shell.state !== 'on') { UI.toast('the shell is not running', 'warn'); return; }
    if (shell.program) {
      UI.toast(`${shell.program} is running in the shell; this would be typed into it. `
        + 'Wait for it to finish, or stop it with Ctrl+C.', 'warn', 5000);
      return;
    }
    let folder = this._startFolder();
    if (!folder) { UI.toast('this tab has no run folder yet', 'warn'); return; }
    // The folder of the last run may have been deleted since. Then the
    // folder new runs go to is the useful answer, rather than a cd error.
    try {
      const found = await API.stat(folder);
      if (!found.dir && App.outputRoot && folder !== App.outputRoot) {
        UI.toast(`${folder} is not there any more: going to the run folder instead`, 'warn', 4000);
        folder = App.outputRoot;
      }
    } catch (err) { /* the shell will say what is wrong with it */ }
    if (shell.program || shell.state !== 'on') return;
    const quoted = `'${folder.replace(/'/g, "'\\''")}'`;
    shell._send({ type: 'input', data: `\x05\x15cd -- ${quoted}\r` });
    if (shell.view) shell.view.focus();
  },

  /* The drawer's header says what the shell on screen is doing; the strip
     above the screen has a tab for every shell. */
  paint() {
    const shell = this.current;
    const status = document.getElementById('shell-status');
    if (status) {
      const text = shell ? shell.describe() : 'not started';
      status.textContent = text;
      status.title = (shell && shell.detail) || text;
    }
    const dot = document.getElementById('shell-dot');
    if (dot) dot.classList.toggle('running', Boolean(shell && shell.busy()));
    const cd = document.getElementById('shell-cd');
    if (cd) cd.disabled = !(shell && shell.state === 'on' && !shell.program);
    this._drawTabs();
  },

  /* A tab for each shell, then +. Drawn again whenever something on it
     changes; there are only ever a few. */
  _drawTabs() {
    const strip = document.getElementById('shell-tabs');
    if (!strip) return;
    strip.textContent = '';
    for (const shell of this.shells) {
      strip.appendChild(UI.el('div', {
        class: `shell-tab${shell === this.current ? ' active' : ''}`,
        role: 'tab',
        title: `Shell ${shell.number}: ${shell.describe()}`,
        onclick: () => this.select(shell),
      }, [
        // A program is running in it: seen even while another tab is showing.
        shell.busy() ? UI.el('span', { class: 't-dot running' }) : null,
        UI.el('span', { class: 'shell-tab-no', text: String(shell.number) }),
        UI.el('span', { class: 'shell-tab-name', text: shell.label() }),
        UI.el('button', {
          class: 'shell-tab-close', text: '×', title: `End shell ${shell.number}`,
          onclick: (event) => { event.stopPropagation(); this.close(shell); },
        }),
      ]));
    }
    const full = this.shells.length >= this.most;
    strip.appendChild(UI.el('button', {
      class: 'shell-tab-add', text: '+',
      title: full ? `${this.most} shells are open, which is as many as one Comfy-gmx keeps`
        : 'Open another shell beside this one',
      disabled: full ? '' : null,
      onclick: () => this.add(),
    }));
    // When the tabs do not all fit, the strip scrolls; keep the one on
    // screen in view.
    const active = strip.querySelector('.shell-tab.active');
    if (active && strip.scrollWidth > strip.clientWidth
        && typeof active.scrollIntoView === 'function') {
      active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
  },

  /* Which shells this browser tab has, kept across a reload. Only shells
     the server knows are kept: a tab whose shell has ended is not. */
  _save() {
    const shells = this.shells.filter((shell) => shell.id)
      .map((shell) => ({ number: shell.number, id: shell.id }));
    try {
      sessionStorage.setItem('comfygmx.shells', JSON.stringify({
        shells, current: this.current ? this.current.number : 0,
      }));
      sessionStorage.removeItem('comfygmx.shell');
    } catch (err) { /* private mode */ }
  },

  _load() {
    try {
      const saved = JSON.parse(sessionStorage.getItem('comfygmx.shells') || 'null');
      if (saved && Array.isArray(saved.shells)) {
        const seen = new Set();
        const shells = saved.shells.filter((entry) => {
          const ok = entry && typeof entry.id === 'string' && entry.id
            && Number.isInteger(entry.number) && entry.number > 0 && !seen.has(entry.number);
          if (ok) seen.add(entry.number);
          return ok;
        });
        return { shells, current: saved.current };
      }
      // Saved by a page from before there could be several: its one shell.
      const one = sessionStorage.getItem('comfygmx.shell');
      if (one) return { shells: [{ number: 1, id: one }], current: 1 };
    } catch (err) { /* private mode, or something unreadable */ }
    return { shells: [], current: 0 };
  },
};
