/* The drawer under the canvas. It has two tabs.

   Run: one continuous transcript of a run. The Log tab shows one node at a
   time, which is right when you are reading a failure and wrong when the
   question is "what is it doing". This is the other view: every node in
   order, the command each one actually ran, its output and how it ended,
   scrolling past as it happens.

   Shell: a real bash on this machine, the same as a terminal window (the
   ShellTab object at the end of this file).

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

/* The drawer's Shell tab: a real shell on this machine.

   The screen is vt.js; the shell itself runs on the server (comfygmx/shell.py)
   and the two talk over a WebSocket, a connection that stays open both ways,
   so each key goes straight to the shell and its output comes straight back.

   The shell belongs to this browser tab, not to a graph tab: switching
   between graphs keeps it. Reloading the page finds it again (the server
   keeps it for a minute without a page), because a reload should not kill a
   command somebody started from it. */
const ShellTab = {
  view: null,
  socket: null,
  /* The server's name for our shell, kept for the length of this browser
     tab (sessionStorage), so a reload can ask for the same one back. */
  id: '',
  /* off, connecting, on, ended or refused. */
  state: 'off',
  /* The program in front of the shell, or '' at the prompt. */
  program: '',
  cwd: '',
  _catchup: 0,
  _retries: 0,
  _retryTimer: 0,
  _newArmed: 0,

  init() {
    try { this.id = sessionStorage.getItem('comfygmx.shell') || ''; } catch (err) { this.id = ''; }
    document.getElementById('shell-new').addEventListener('click', () => this.renew());
    document.getElementById('shell-copy').addEventListener('click', () => this.copyAll());
    document.getElementById('shell-cd').addEventListener('click', () => this.goToRunFolder());
    this.paint();
  },

  /* The tab has just been shown: start the shell, or bring it back. */
  show() {
    if (!this.view) {
      const pane = document.getElementById('shell-pane');
      this.view = new VT.View(pane, {
        onData: (text) => this.type(text),
        onResize: (cols, rows) => this._send({ type: 'resize', cols, rows }),
        onCopy: (text) => this._copy(text),
        onKey: (event) => this._key(event),
      });
    }
    // The drawer was hidden until now, so the size is only known now. Not
    // left for the next frame: a browser tab in the background draws no
    // frames, and the shell would not start until somebody looked at it.
    this.view.fit();
    if (this.state === 'off') this.connect();
    this.view.focus();
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

  connect() {
    clearTimeout(this._retryTimer);
    if (this.socket) return;
    this.state = 'connecting';
    this.paint();
    const where = this._startFolder();
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

  _message(event) {
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
        try { sessionStorage.setItem('comfygmx.shell', this.id); } catch (err) { /* private mode */ }
        this.state = 'on';
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
            + `${message.cwd}. It is the same as a terminal window: type exit to end it.`);
        }
        this.paint();
        break;
      }
      case 'busy':
        this.program = message.program || '';
        if (message.cwd) this.cwd = message.cwd;
        this.paint();
        break;
      case 'exit':
        this.state = 'ended';
        this.program = '';
        this._forget();
        this.view.note(message.hung_up
          ? 'The shell was hung up. Press any key for a new one.'
          : `The shell has ended${message.code ? ` (exit code ${message.code})` : ''}. `
            + 'Press any key for a new one.');
        this.paint();
        break;
      case 'refused':
        this.state = 'refused';
        this._forget();
        this.view.note(`No shell: ${message.why}`);
        this.paint(message.why);
        break;
      case 'taken':
        // The same shell was opened in another browser tab, which now has it.
        this.state = 'off';
        this.view.note('This shell is now shown in another browser tab. '
          + 'Press any key to take it back.');
        this.paint();
        break;
      default:
        break;
    }
  },

  /* The connection dropped without the shell ending: the server restarted,
     or the machine slept. Try again a few times, gently. */
  _lost(why = '') {
    this.state = 'off';
    this.paint(why || 'connection lost, trying again');
    if (this._retries >= 6) {
      this.view.note('Lost the connection to the server. Press any key to try again.');
      this.paint('no connection');
      return;
    }
    const wait = Math.min(8000, 500 * 2 ** this._retries);
    this._retries += 1;
    this._retryTimer = setTimeout(() => this.connect(), wait);
  },

  _forget() {
    this.id = '';
    try { sessionStorage.removeItem('comfygmx.shell'); } catch (err) { /* private mode */ }
  },

  _send(message) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN && this.state === 'on') {
      this.socket.send(JSON.stringify(message));
      return true;
    }
    return false;
  },

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
  },

  /* True while a program is running in front of the shell, so leaving the
     page should ask first. */
  busy() {
    return this.state === 'on' && Boolean(this.program);
  },

  renew() {
    if (this.busy() && Date.now() - this._newArmed > 3000) {
      this._newArmed = Date.now();
      UI.toast(`${this.program} is running in the shell: press New shell again within `
        + '3 seconds to end it and start a fresh shell', 'warn', 4000);
      return;
    }
    this._newArmed = 0;
    this._send({ type: 'hangup' });
    if (this.socket) {
      const old = this.socket;
      this.socket = null;
      try { old.close(); } catch (err) { /* already closed */ }
    }
    this._forget();
    this.state = 'off';
    if (this.view) this.view.reset();
    this.connect();
    if (this.view) this.view.focus();
  },

  copyAll() {
    if (!this.view) return;
    const text = this.view.selectionText() || this.view.allText();
    if (text.trim()) this._copy(text);
    else this.view.focus();
  },

  /* UI.copy, but with the keyboard given back to the shell once the copy is
     done. Copying can borrow the keyboard for a moment (UI.fallbackCopy),
     and after that the next letters would go to the graph's shortcuts. */
  _copy(text) {
    const back = () => { if (this.view) this.view.focus(); };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(
        () => { UI.toast('copied to clipboard', 'ok', 1800); back(); },
        () => { UI.fallbackCopy(text); back(); });
    } else {
      UI.fallbackCopy(text);
      back();
    }
  },

  /* cd to the folder the Open folder button would open. Typed only while
     the shell is at its prompt: into nano it would become part of a file.
     Ctrl+E and Ctrl+U first clear anything half-typed on that line, so the
     cd cannot end up glued to the end of some other command. */
  async goToRunFolder() {
    if (this.state !== 'on') { UI.toast('the shell is not running', 'warn'); return; }
    if (this.program) {
      UI.toast(`${this.program} is running in the shell; this would be typed into it. `
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
    if (this.program || this.state !== 'on') return;
    const quoted = `'${folder.replace(/'/g, "'\\''")}'`;
    this._send({ type: 'input', data: `\x05\x15cd -- ${quoted}\r` });
    this.view.focus();
  },

  paint(detail = '') {
    const status = document.getElementById('shell-status');
    const dot = document.getElementById('shell-dot');
    if (!status) return;
    const home = (typeof App !== 'undefined' && App.homeDir) || '';
    const short = (path) => (home && path.startsWith(home) ? `~${path.slice(home.length)}` : path);
    let text;
    switch (this.state) {
      case 'connecting': text = 'starting…'; break;
      case 'on': text = this.program ? `running ${this.program}` : `bash · ${short(this.cwd)}`; break;
      case 'ended': text = 'ended · press any key for a new shell'; break;
      case 'refused': text = 'refused'; break;
      default: text = detail || 'not started';
    }
    status.textContent = text;
    status.title = detail || text;
    if (dot) dot.classList.toggle('running', this.busy());
    document.getElementById('shell-cd').disabled = !(this.state === 'on' && !this.program);
  },
};
