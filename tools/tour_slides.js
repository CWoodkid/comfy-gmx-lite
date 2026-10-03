/* The basics: the short tour of the mouse and keyboard (comfygmx/web/js/tour.js).

   What has to stay true:

     * there are ten slides, the same ones in the same order for a mouse and
       for a touchpad; the first asks which of the two is being used, and
       every other one has a picture, and a moment of that picture to hold
       still at for somebody who asked the computer for less movement
     * the words and the pictures follow the answer: a touchpad hears about
       tapping and two fingers and sees a touchpad in the corner, never a
       mouse button or wheel, and a mouse the other way round
     * choosing on the first slide sets the page's own setting (the one in
       Settings) and goes on to the next slide
     * it opens by itself once per browser tab, never after "Don't show this
       at the start again" was ticked, and only when no other window is
       open: it waits for one (such as the first-start setup) for up to two
       minutes, then gives up, since ? still has it
     * a browser that refuses to remember anything still gets the tour
     * Next, Back, the dots and the arrow keys move between slides and stop
       at either end; the last slide's button reads Start and closes it; once
       it is closed the arrow keys are left alone

   Run:  node tools/tour_slides.js
   It loads tour.js with a stand-in for the page, so it needs neither a
   browser nor a running server. With --pictures it prints every picture as
   text instead, for the self-test to read as SVG (tools/smoke_test.py,
   check_tour). */
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

/* -- a stand-in for the page: just enough of it for tour.js */
class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attrs = {};
    this.dataset = {};
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.html = '';
    this.disabled = false;
    this.checked = false;
  }
  set innerHTML(value) { this.html = value; if (value === '') this.children = []; }
  get innerHTML() { return this.html; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  fire(type) { for (const fn of this.listeners[type] || []) fn({ target: this }); }
  click() {
    if (this.disabled) return;
    if (this.onclick) this.onclick({ stopPropagation() {} });
    this.fire('click');
  }
  focus() {}
  // There is no real picture to hold still, and tour.js copes with that.
  querySelector() { return null; }
  // Everything inside this element, and what it says.
  all() { return this.children.flatMap((c) => (c instanceof Element ? [c, ...c.all()] : [])); }
  get words() {
    return [this.textContent, this.html,
      ...this.children.map((c) => (c instanceof Element ? c.words : String(c)))].join(' ');
  }
}
const el = (tag, attrs = {}, children = []) => {
  const node = new Element(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === 'class') node.className = value;
    else if (name === 'text') node.textContent = value;
    else if (name === 'html') node.innerHTML = value;
    else if (name.startsWith('on')) node[name] = value;
    else if (name.startsWith('data-')) node.dataset[name.slice(5)] = value;
    else node.attrs[name] = value;
  }
  for (const child of children) node.appendChild(child);
  return node;
};

// The shared window (UI.modal in api.js), as far as tour.js uses it.
const win = { open: false, title: el('span'), body: null, footer: el('footer') };
const UI = {
  _generation: 0,
  _subOpen: false,
  el,
  modal(title, body) {
    UI._generation += 1;
    win.open = true;
    win.title.textContent = title;
    win.body = body;
    win.footer.innerHTML = '';
  },
  closeModal() { win.open = false; },
  modalOpen() { return win.open; },
  anyDialogOpen() { return win.open || UI._subOpen; },
};

const keys = new Set();
const document = {
  getElementById: (id) => ({ 'modal-title': win.title, 'modal-footer': win.footer }[id] || null),
  querySelector: (selector) => (selector === '#modal-body .tour' && win.open ? win.body : null),
  addEventListener: (type, fn) => { if (type === 'keydown') keys.add(fn); },
  removeEventListener: (type, fn) => { if (type === 'keydown') keys.delete(fn); },
};
const press = (key) => {
  for (const fn of [...keys]) fn({ key, preventDefault() {}, stopPropagation() {} });
};

class Store {
  constructor() { this.map = new Map(); }
  getItem(name) { return this.map.has(name) ? this.map.get(name) : null; }
  setItem(name, value) { this.map.set(name, String(value)); }
  removeItem(name) { this.map.delete(name); }
  clear() { this.map.clear(); }
}
const local = new Store();
const session = new Store();
let refuse = false;   // a browser that will not remember anything
const window = {
  get localStorage() { if (refuse) throw new Error('blocked'); return local; },
  get sessionStorage() { if (refuse) throw new Error('blocked'); return session; },
  matchMedia: () => ({ matches: false }),
};

// The page's own pointer setting (Editor.pointer in graph.js).
const Editor = {
  kind: 'mouse',
  pointer() { return this.kind; },
  setPointer(kind) { this.kind = kind; },
};

// A clock that only moves when the test says so.
let clock = 0;
let timers = [];
const advance = (ms) => {
  const end = clock + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    if (!timers.length || timers[0].at > end) break;
    const next = timers.shift();
    clock = next.at;
    next.fn();
  }
  clock = end;
};

const sandbox = {
  console, document, window, UI, Editor,
  Date: { now: () => clock },
  setTimeout: (fn, ms) => { timers.push({ at: clock + ms, fn }); return timers.length; },
  PORT_COLORS: { structure: '#6fbf8b', topology: '#d8a84f', tpr: '#4f9dd8', traj: '#d9705f', any: '#8d97a5' },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(
  path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'tour.js'), 'utf8'), sandbox,
  { filename: 'tour.js' });
const TourArt = vm.runInContext('TourArt', sandbox);
const TourSlides = vm.runInContext('TourSlides', sandbox);
const Tour = vm.runInContext('Tour', sandbox);

if (process.argv.includes('--pictures')) {
  const pictures = [];
  for (const kind of ['mouse', 'trackpad']) {
    for (const slide of TourSlides.all(kind)) {
      if (slide.art) pictures.push({ kind, id: slide.id, still: slide.still, svg: slide.art });
    }
  }
  pictures.push({ kind: 'both', id: 'mouseChoice', svg: TourArt.mouseChoice() });
  pictures.push({ kind: 'both', id: 'padChoice', svg: TourArt.padChoice() });
  // A pipe takes this a piece at a time: end only once all of it has gone.
  process.stdout.write(JSON.stringify(pictures), () => process.exit(0));
} else {
  checks();
}

function checks() {

  const fresh = () => {
    local.clear();
    session.clear();
    refuse = false;
    win.open = false;
    UI._subOpen = false;
    timers = [];
    Editor.kind = 'mouse';
  };
  const title = () => (win.open ? win.title.textContent : '(no window)');
  const button = (label) => win.footer.all().find((n) => n.tag === 'button' && n.textContent.includes(label));
  const slideWords = () => (win.body ? win.body.all().filter((n) => n.tag === 'p').map((n) => n.html).join(' ') : '');

  /* ----------------------------------------------------------------- slides */
  console.log('the slides');
  const mouse = TourSlides.all('mouse');
  const pad = TourSlides.all('trackpad');
  check(mouse.length === 10 && pad.length === 10,
        `${mouse.length} slides for a mouse and ${pad.length} for a touchpad, not ten each`);
  check(mouse.map((s) => s.id).join() === pad.map((s) => s.id).join(),
        'the mouse and touchpad tours do not have the same slides in the same order');
  check(mouse[0].choice && pad[0].choice, 'the first slide no longer asks: a mouse or a touchpad?');
  const MOUSE = 'width="34" height="54"';   // how the mouse in the corner is drawn
  const PAD = 'width="80" height="52"';     // and the touchpad
  for (const [kind, slides] of [['mouse', mouse], ['touchpad', pad]]) {
    for (const slide of slides.slice(1)) {
      const name = `${kind} slide "${slide.id}"`;
      check(typeof slide.art === 'string' && slide.art.startsWith('<svg'), `${name} has no picture`);
      if (typeof slide.art !== 'string') continue;
      const length = Math.max(0, ...[...slide.art.matchAll(/dur="([\d.]+)s"/g)].map((m) => Number(m[1])));
      check(slide.still > 0 && slide.still < length,
            `${name} is held still at ${slide.still} s, outside its picture's ${length} s`);
      check(slide.title && slide.text.length > 0, `${name} has no title or no words`);
      const words = slide.text.join(' ');
      if (kind === 'mouse') {
        check(!/touchpad|finger/i.test(words), `${name} speaks of a touchpad: "${words}"`);
        check(slide.art.includes(MOUSE) && !slide.art.includes(PAD), `${name} does not show a mouse`);
      } else {
        check(!/mouse|wheel/i.test(words), `${name} speaks of a mouse: "${words}"`);
        check(slide.art.includes(PAD) && !slide.art.includes(MOUSE), `${name} does not show a touchpad`);
      }
    }
  }
  const said = (slides, id) => slides.find((s) => s.id === id).text.join(' ');
  check(/two fingers/.test(said(pad, 'menu')), 'a touchpad is no longer told how to right-click (two fingers)');
  check(/right/.test(said(mouse, 'menu')), 'a mouse is no longer told to use the right button');
  check(/Ctrl/.test(said(mouse, 'edit')) && /Cmd/.test(said(mouse, 'edit')), 'undo no longer names Ctrl and Cmd');
  check(/Show the basics/.test(said(mouse, 'ready')), 'the last slide no longer says how to see the tour again');

  /* ------------------------------------------------------- opening by itself */
  console.log('opening by itself');
  fresh();
  Tour.atStart();
  advance(300);
  check(!win.open, 'it opened before the page had settled');
  advance(200);
  check(title() === 'The basics · 1 of 10', `on a first visit the window shows "${title()}"`);
  check(session.getItem(Tour.SHOWN), 'the tab does not remember that the tour opened');

  UI.closeModal();
  timers = [];
  Tour.atStart();   // the page loaded again in the same tab
  advance(5000);
  check(!win.open, 'it opened again in a tab that has seen it');

  fresh();
  local.setItem(Tour.NEVER, '1');   // a new tab, with the box ticked earlier
  Tour.atStart();
  advance(5000);
  check(!win.open, 'it opened although "Don\'t show this at the start again" was ticked');

  fresh();
  UI.modal('Set up this machine', el('div'));   // the first-start setup asks first
  Tour.atStart();
  advance(30000);
  check(title() === 'Set up this machine', `it pushed the setup window aside: "${title()}"`);
  UI.closeModal();
  advance(1000);
  check(title() === 'The basics · 1 of 10', `after the setup window closed the window shows "${title()}"`);

  fresh();
  UI._subOpen = true;   // a window opened from inside another one
  Tour.atStart();
  advance(5000);
  check(!win.open, 'it opened over a window opened from inside another one');
  UI._subOpen = false;
  advance(1000);
  check(win.open, 'it did not open once that window closed');

  fresh();
  UI.modal('Something long', el('div'));
  Tour.atStart();
  advance(121000);
  UI.closeModal();
  advance(5000);
  check(!win.open, 'it opened after waiting more than two minutes for another window');

  fresh();
  refuse = true;
  Tour.atStart();
  advance(500);
  check(win.open, 'a browser that refuses to remember anything gets no tour');
  refuse = false;

  /* ------------------------------------------------------- the first slide */
  console.log('mouse or touchpad');
  fresh();
  Tour.open();
  const isOption = (n) => n.tag === 'button' && n.className.split(' ').includes('tour-option');
  const options = win.body.all().filter(isOption);
  check(options.length === 2, `the first slide offers ${options.length} choices, not two`);
  const option = (kind) => options.find((n) => n.dataset.kind === kind);
  check(option('mouse') && option('mouse').className.includes('chosen'),
        'the setting in use is not shown as the chosen one');
  if (option('trackpad')) option('trackpad').click();
  check(Editor.kind === 'trackpad', `choosing the touchpad left the page's setting at "${Editor.kind}"`);
  check(title() === 'The basics · 2 of 10', `after choosing, the window shows "${title()}"`);
  check(/touchpad/.test(slideWords()), `after choosing the touchpad, slide 2 says "${slideWords()}"`);
  Tour.go(0);
  const again = win.body.all().filter(isOption);
  const mouseOption = again.find((n) => n.dataset.kind === 'mouse');
  if (mouseOption) mouseOption.click();
  check(Editor.kind === 'mouse', 'choosing the mouse did not set the page back to a mouse');
  check(/left mouse button/.test(slideWords()), `after choosing the mouse, slide 2 says "${slideWords()}"`);

  /* ------------------------------------------------ moving between slides */
  console.log('moving between slides');
  fresh();
  Tour.open();
  check(button('Back') && button('Back').disabled, 'Back can be pressed on the first slide');
  press('ArrowLeft');
  check(title() === 'The basics · 1 of 10', `the left arrow on the first slide went to "${title()}"`);
  button('Next').click();
  check(title() === 'The basics · 2 of 10', `Next went to "${title()}"`);
  press('ArrowRight');
  check(title() === 'The basics · 3 of 10', `the right arrow went to "${title()}"`);
  press('ArrowLeft');
  check(title() === 'The basics · 2 of 10', `the left arrow went to "${title()}"`);
  button('Back').click();
  check(title() === 'The basics · 1 of 10', `Back went to "${title()}"`);
  const dots = win.body.all().filter((n) => n.tag === 'button' && /^Slide \d+/.test(n.attrs['aria-label'] || ''));
  check(dots.length === 10, `${dots.length} dots under the slide, not ten`);
  if (dots[9]) dots[9].click();
  check(title() === 'The basics · 10 of 10', `the last dot went to "${title()}"`);
  press('ArrowRight');
  check(title() === 'The basics · 10 of 10', `the right arrow on the last slide went to "${title()}"`);
  check(!button('Next') && button('Start'), 'the last slide\'s button does not read Start');

  const box = () => win.footer.all().find((n) => n.attrs.type === 'checkbox');
  check(box() && !box().checked, 'the "Don\'t show this at the start again" box is missing, or ticked from the start');
  box().checked = true;
  box().fire('change');
  check(local.getItem(Tour.NEVER) === '1', 'ticking the box is not remembered in this browser');
  press('ArrowLeft');
  check(box().checked, 'the box is not ticked any more on the next slide drawn');
  box().checked = false;
  box().fire('change');
  check(local.getItem(Tour.NEVER) === null, 'unticking the box is not remembered');

  press('ArrowRight');
  button('Start').click();
  check(!win.open, 'Start did not close the tour');
  press('ArrowLeft');
  check(keys.size === 0, 'the arrow keys still go to the tour after it closed');

  fresh();
  Tour.open();
  UI.closeModal();
  UI.modal('Help', el('div'));   // another window, after the tour
  press('ArrowRight');
  check(title() === 'Help', `the right arrow in a later window changed it to "${title()}"`);
  UI.closeModal();

  if (failures) {
    console.log(`\n${failures} problem(s)`);
    process.exit(1);
  }
  console.log('\ntour: ten slides for a mouse and for a touchpad, the words and pictures follow the '
    + 'choice, it opens once per tab after any other window, and the keys and buttons move through it');
}
