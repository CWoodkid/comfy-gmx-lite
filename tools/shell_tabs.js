/* The Shell tab's own tabs: several shells side by side (terminal.js,
   ShellWindow and ShellTab).

   What has to stay true:

     * the first visit opens one shell, in this graph tab's run folder, at
       the size of the screen
     * + opens another beside it, numbered with the lowest number free; each
       has its own connection, and what is typed goes to the one on screen
     * a shell whose tab is not showing carries on, and its tab says when a
       program is running in it
     * × ends that shell and no other; with a program running in it, only a
       second × within three seconds does, since the program ends with it;
       closing the last one starts a fresh one
     * a reload brings every shell back, not only the one on screen, each
       at the size it will be seen at; a shell that has ended is not kept
     * + stops at the number of shells the server keeps
     * a page from before there could be several finds its one shell again
     * a connection that drops is tried again, for the same shell

   Run:  node tools/shell_tabs.js
   It loads terminal.js with a stand-in for the page, for the screen (vt.js)
   and for the server's end of each connection, so it needs neither a
   browser nor a running server. */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failures = 0;
function check(ok, complaint) {
  if (ok) return;
  failures += 1;
  console.log(`  FAILED: ${complaint}`);
}

const SOURCE = fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'terminal.js'), 'utf8');

/* A stand-in for a page element: classes, text, children, clicks, and the
   class selectors the code looks things up by. */
function element(tag = 'div') {
  const classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), children: [], parent: null, attrs: {}, listeners: {},
    style: {}, title: '', disabled: false, scrollWidth: 0, clientWidth: 0, ownText: '',
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, on) => {
        if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c);
        return classes.has(c);
      },
      contains: (c) => classes.has(c),
    },
    appendChild(child) {
      if (child.parent) child.remove();
      child.parent = el;
      el.children.push(child);
      return child;
    },
    remove() {
      if (!el.parent) return;
      el.parent.children = el.parent.children.filter((c) => c !== el);
      el.parent = null;
    },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    addEventListener(type, fn) { (el.listeners[type] = el.listeners[type] || []).push(fn); },
    click() {
      const event = { stopPropagation() {}, preventDefault() {} };
      for (const fn of el.listeners.click || []) fn(event);
    },
    querySelectorAll(selector) {
      const wanted = selector.split('.').filter(Boolean);
      const found = [];
      const walk = (node) => {
        for (const child of node.children) {
          if (wanted.every((c) => child.classList.contains(c))) found.push(child);
          walk(child);
        }
      };
      walk(el);
      return found;
    },
    querySelector(selector) { return el.querySelectorAll(selector)[0] || null; },
  };
  Object.defineProperty(el, 'className', {
    get: () => [...classes].join(' '),
    set: (text) => {
      classes.clear();
      for (const c of String(text).split(/\s+/)) if (c) classes.add(c);
    },
  });
  Object.defineProperty(el, 'textContent', {
    get: () => el.ownText + el.children.map((c) => c.textContent).join(''),
    set: (text) => {
      for (const child of el.children) child.parent = null;
      el.children = [];
      el.ownText = String(text);
    },
  });
  return el;
}

/* One page load: a fresh copy of terminal.js, with the browser tab's
   sessionStorage handed in, since that is what survives a reload. */
function load(storage) {
  const page = new Map();
  for (const id of ['shell-status', 'shell-dot', 'shell-cd', 'shell-copy', 'shell-tabs',
                    'shell-screens']) {
    page.set(id, element(id === 'shell-cd' || id === 'shell-copy' ? 'button' : 'div'));
  }
  const world = {
    page, sockets: [], toasts: [], timers: [],
    // The size the screen on show has; hidden screens cannot be measured.
    size: { cols: 100, rows: 30 },
    clock: 1000000,
  };

  class View {
    constructor(host, options) {
      this.host = host;
      this.options = options;
      this.cols = 80;
      this.rows = 24;
      this.notes = [];
      this.text = '';
      this.screen = { scrollback: [], y: 0 };
      host.classList.add('vt');
    }
    fit() {
      // Like vt.js: a screen that is not showing keeps its size.
      if (this.host.classList.contains('hidden') || !this.host.parent) return;
      const { cols, rows } = world.size;
      if (cols === this.cols && rows === this.rows) return;
      this.cols = cols;
      this.rows = rows;
      if (this.options.onResize) this.options.onResize(cols, rows);
    }
    focus() { world.focused = this; }
    reset() { this.text = ''; this.notes = []; }
    note(text) { this.notes.push(text); }
    write(bytes) { this.text += Buffer.from(bytes).toString(); }
    replay(bytes) { this.text = Buffer.from(bytes).toString(); }
    selectionText() { return ''; }
    allText() { return this.text; }
  }

  class WebSocket {
    constructor(url) {
      this.url = new URL(url);
      this.sent = [];
      this.closed = false;
      this.readyState = WebSocket.OPEN;
      world.sockets.push(this);
    }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.closed = true; this.readyState = 3; }
  }
  WebSocket.OPEN = 1;

  class FakeDate extends Date {
    static now() { return world.clock; }
  }

  const UI = {
    el(tag, attrs = {}, children = []) {
      const node = element(tag);
      for (const [key, value] of Object.entries(attrs)) {
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else if (value !== null && value !== undefined) node.setAttribute(key, value);
      }
      for (const child of [].concat(children)) if (child) node.appendChild(child);
      return node;
    },
    toast: (text) => world.toasts.push(text),
    fallbackCopy() {},
  };

  const sandbox = {
    sessionStorage: {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: (key) => storage.delete(key),
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
      getElementById: (id) => page.get(id) || null,
      createElement: (tag) => element(tag),
    },
    window: { location: { href: 'http://127.0.0.1:8189/' }, isSecureContext: false },
    navigator: {},
    VT: { View },
    WebSocket,
    App: {
      workFolder: () => ({ path: '/home/u/runs/ice' }),
      outputRoot: '/home/u/runs',
      homeDir: '/home/u',
    },
    API: { stat: async () => ({ dir: true }) },
    UI,
    Sessions: { active: () => null },
    setTimeout: (fn) => { world.timers.push(fn); return world.timers.length; },
    clearTimeout: (id) => { if (id) world.timers[id - 1] = null; },
    URL, JSON, Math, Set, Map, Promise, Number, String, Array, Object, Uint8Array,
    Date: FakeDate,
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox, { filename: 'terminal.js' });
  world.ShellTab = vm.runInContext('ShellTab', sandbox);
  world.ShellTab.init();
  return world;
}

/* What the server would send on one connection. A connection the page
   never opened has already been reported; the rest of the test goes on. */
const say = (socket, message) => {
  if (socket) socket.onmessage({ data: JSON.stringify(message) });
};
const ready = (socket, id, extra = {}) => say(socket, {
  type: 'ready', id, again: false, cwd: '/home/u/runs/ice', shell: '/bin/bash',
  program: '', catchup: 0, most: 8, ...extra,
});

/* The strip, as somebody would read it. */
const tabs = (world) => world.page.get('shell-tabs').querySelectorAll('.shell-tab');
const strip = (world) => tabs(world)
  .map((tab) => `${tab.querySelector('.shell-tab-no').textContent}`
    + ` ${tab.querySelector('.shell-tab-name').textContent}`
    + `${tab.classList.contains('active') ? '*' : ''}`
    + `${tab.querySelector('.t-dot') ? '●' : ''}`).join(' | ');
const addButton = (world) => world.page.get('shell-tabs').querySelector('.shell-tab-add');
const saved = (storage) => JSON.parse(storage.get('comfygmx.shells') || 'null');
const numbers = (storage) => ((saved(storage) || {}).shells || []).map((s) => `${s.number}:${s.id}`).join(',');
const showing = (world) => world.page.get('shell-screens').children
  .filter((host) => !host.classList.contains('hidden')).length;

console.log('the first visit');
const storage = new Map();
let world = load(storage);
check(tabs(world).length === 0 && addButton(world),
      'before the Shell tab is opened, the strip should have only its + button');
world.ShellTab.show();
check(world.sockets.length === 1, `opening the Shell tab opened ${world.sockets.length} connections, not 1`);
let [one] = world.sockets;
check(!one.url.searchParams.get('id') && one.url.searchParams.get('cwd') === '/home/u/runs/ice',
      `the first shell asked for ${one.url} rather than a new shell in the run folder`);
check(one.url.searchParams.get('cols') === '100' && one.url.searchParams.get('rows') === '30',
      `the first shell asked for ${one.url.searchParams.get('cols')}x${one.url.searchParams.get('rows')}, `
      + 'not the screen\'s 100x30');
ready(one, 'A');
check(strip(world) === '1 ice*', `after it started, the strip reads "${strip(world)}", not "1 ice*"`);
check(numbers(storage) === '1:A', `the browser tab keeps [${numbers(storage)}], not [1:A]`);
check(world.ShellTab.current.view.notes.some((n) => /press \+ above/.test(n)),
      'the first shell does not say that + opens another');

console.log('a second shell beside it');
addButton(world).click();
check(world.sockets.length === 2, '+ did not open a second connection');
let two = world.sockets[1];
check(!two.url.searchParams.get('id'), '+ asked the server for an existing shell instead of a new one');
check(showing(world) === 1 && world.ShellTab.current.number === 2,
      'after +, the new shell is not the only screen showing');
ready(two, 'B');
check(numbers(storage) === '1:A,2:B', `with two shells the browser tab keeps [${numbers(storage)}]`);
say(one, { type: 'busy', program: 'nano', cwd: '/home/u/runs/ice' });
check(strip(world) === '1 nano● | 2 ice*',
      `with nano running in the shell behind, the strip reads "${strip(world)}", not "1 nano● | 2 ice*"`);
check(world.ShellTab.busy(), 'a program running in the shell behind does not count as busy for the page');
check(!world.page.get('shell-dot').classList.contains('running'),
      'the header\'s dot pulses for a program in the shell behind, not the one on screen');
tabs(world)[0].click();
check(world.ShellTab.current.number === 1 && showing(world) === 1,
      'clicking tab 1 did not put shell 1, and only shell 1, on screen');
check(world.page.get('shell-status').textContent === 'running nano' && world.page.get('shell-cd').disabled,
      'with shell 1 on screen the header does not say nano is running, or Go to run folder is not greyed out');
world.ShellTab.current.view.options.onData('ls\r');
check(one.sent.some((m) => m.type === 'input' && m.data === 'ls\r')
      && !two.sent.some((m) => m.type === 'input'),
      'what was typed on screen did not go to that shell alone');

console.log('closing one');
tabs(world)[0].querySelector('.shell-tab-close').click();
check(world.ShellTab.shells.length === 2 && world.toasts.some((t) => /press its × again/.test(t)),
      'the first × on a shell running nano ended it, or did not say how to');
check(!one.sent.some((m) => m.type === 'hangup'), 'the first × already hung the shell up');
world.clock += 1000;
tabs(world)[0].querySelector('.shell-tab-close').click();
check(one.sent.some((m) => m.type === 'hangup') && one.closed,
      'a second × within three seconds did not hang the shell up');
check(!two.closed && world.ShellTab.shells.length === 1 && world.ShellTab.current.number === 2,
      'closing shell 1 touched shell 2, or did not leave shell 2 on screen');
check(world.page.get('shell-screens').children.length === 1, 'the closed shell\'s screen is still there');
check(numbers(storage) === '2:B', `after closing shell 1 the browser tab keeps [${numbers(storage)}]`);
addButton(world).click();
const three = world.sockets[2];
ready(three, 'C');
check(strip(world) === '1 ice* | 2 ice',
      `a new shell after closing 1 should take the number 1 again, first in the strip: "${strip(world)}"`);

console.log('a reload');
world = load(storage);
check(strip(world) === '1 …* | 2 …',
      `before the Shell tab is shown again, the strip reads "${strip(world)}", not "1 …* | 2 …"`);
world.size = { cols: 90, rows: 20 };
world.ShellTab.show();
const back = Object.fromEntries(world.sockets.map((s) => [s.url.searchParams.get('id'), s]));
check(world.sockets.length === 2 && back.B && back.C,
      `after a reload the page asked for [${Object.keys(back)}], not both shells [B,C]`);
check(world.sockets.every((s) => s.url.searchParams.get('cols') === '90' && s.url.searchParams.get('rows') === '20'),
      'after a reload, a shell behind the one on screen was not sized to the screen: '
      + `${world.sockets.map((s) => `${s.url.searchParams.get('cols')}x${s.url.searchParams.get('rows')}`)}`);
check(world.ShellTab.current.number === 1 && showing(world) === 1, 'after a reload, shell 1 is not the one on screen');
ready(back.C, 'C', { again: true });
ready(back.B, 'B', { again: true });
check(strip(world) === '1 ice* | 2 ice', `after a reload the strip reads "${strip(world)}"`);

console.log('a shell that ends');
say(back.B, { type: 'exit', code: 0, hung_up: false });
check(strip(world) === '1 ice* | 2 ended', `after exit in shell 2 the strip reads "${strip(world)}"`);
check(numbers(storage) === '1:C', `a shell that has ended is still kept: [${numbers(storage)}]`);
const ended = world.ShellTab.shells[1];
if (ended && ended.view) ended.view.options.onData('x');
const fresh = world.sockets[world.sockets.length - 1];
check(fresh !== back.B && !fresh.url.searchParams.get('id'),
      'a key in the ended shell did not ask for a new one');

console.log('a connection that drops');
const before = world.sockets.length;
if (back.C) back.C.onclose();
check(world.ShellTab.shells[0].state === 'off' && /trying again/.test(world.page.get('shell-status').textContent),
      `a dropped connection left the header at "${world.page.get('shell-status').textContent}"`);
for (const timer of world.timers.splice(0)) if (timer) timer();
const retried = world.sockets[world.sockets.length - 1];
check(world.sockets.length === before + 1 && retried.url.searchParams.get('id') === 'C',
      'after a dropped connection the page did not ask for the same shell again');

console.log('as many as the server keeps');
const small = new Map();
world = load(small);
world.ShellTab.show();
ready(world.sockets[0], 'S1', { most: 2 });
addButton(world).click();
ready(world.sockets[1], 'S2', { most: 2 });
check(addButton(world).attrs.disabled !== undefined, 'with 2 of 2 shells open, + is not greyed out');
world.ShellTab.add();
check(world.ShellTab.shells.length === 2 && world.toasts.some((t) => /2 shells are open/.test(t)),
      'a third shell was opened although the server keeps two');

console.log('closing the last one');
const last = new Map();
world = load(last);
world.ShellTab.show();
ready(world.sockets[0], 'L1');
tabs(world)[0].querySelector('.shell-tab-close').click();
check(world.sockets[0].sent.some((m) => m.type === 'hangup'), 'closing the last shell did not hang it up');
check(world.ShellTab.shells.length === 1 && world.sockets.length === 2
      && !world.sockets[1].url.searchParams.get('id'),
      'closing the last shell did not start a fresh one in its place');

console.log('a page from before there could be several');
const old = new Map([['comfygmx.shell', 'OLD']]);
world = load(old);
world.ShellTab.show();
check(world.sockets.length === 1 && world.sockets[0].url.searchParams.get('id') === 'OLD',
      'the one shell saved by an older page was not asked for again');
ready(world.sockets[0], 'OLD', { again: true });
check(!old.has('comfygmx.shell') && numbers(old) === '1:OLD',
      `the older page's note was not taken over: [${numbers(old)}], ${old.get('comfygmx.shell')}`);

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\nshell tabs: one shell to start, + for more beside it, × ends only its own '
  + '(asking first while a program runs), every shell back after a reload at the '
  + 'screen\'s size, and + stops at the server\'s limit');
