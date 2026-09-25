/* Can you move the canvas about on a laptop trackpad?

   The canvas could be dragged with the middle mouse button, and with Alt and
   the left button. Neither reaches a laptop. A trackpad has no middle button
   to press: two fingers on one is a right-click on most machines and a scroll
   on the rest, never a middle click. And on Linux the desktop itself usually
   takes Alt and drag to move the window, so that never arrived either. Two
   fingers sliding, which is how you move around everywhere else on a laptop,
   was read as the wheel turning and zoomed instead.

   What has to stay true:

     * a fresh browser behaves exactly as it always did: the wheel zooms
     * told it is a trackpad, two fingers sliding moves the canvas
     * a pinch still zooms either way, because the browser reports a pinch as
       the wheel turning with Ctrl held, and Cmd on a Mac
     * the answer is remembered in the browser, not on the server, so the same
       server opened from a desktop and a laptop answers differently
     * holding the spacebar turns a drag into a drag of the canvas, whatever
       is set, because that one gesture works on every pointing device
     * a space typed into a box is a space, not a grab of the canvas

   Run:  node tools/canvas_pan.js
   It loads the browser file with a stand-in for the page, so it needs neither
   a browser nor a running server. */
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

// A stand-in for the browser's storage, so the preference can be set and read
// without one. Deliberately able to throw, because a browser told to block
// site data does exactly that and the editor still has to come up.
function makeStorage(broken) {
  const held = new Map();
  return {
    getItem(key) {
      if (broken) throw new Error('this browser is not storing anything');
      return held.has(key) ? held.get(key) : null;
    },
    setItem(key, value) {
      if (broken) throw new Error('this browser is not storing anything');
      held.set(key, String(value));
    },
    removeItem(key) { held.delete(key); },
  };
}

function loadEditor(storage) {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'graph.js'), 'utf8');
  const sandbox = {
    localStorage: storage,
    document: { addEventListener() {}, getElementById: () => null,
                createElement: () => ({ style: {}, classList: { add() {}, remove() {} },
                                        addEventListener() {}, appendChild() {} }) },
    window: { addEventListener() {} },
    console,
    UI: { el: () => ({ style: {}, classList: { add() {}, remove() {} },
                       addEventListener() {}, appendChild() {} }),
          toast() {}, bytes: () => '' },
    API: {}, App: {}, Sessions: {}, requestAnimationFrame: (fn) => fn(),
    setTimeout, clearTimeout, Math, JSON, Set, Map, Date,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  // `const Editor = ...` at the top level of a script does not become a
  // property of the context, so it is handed out explicitly.
  vm.runInContext(source + '\n;globalThis.__Editor = Editor;', sandbox,
                  { filename: 'graph.js' });
  return sandbox.__Editor;
}

console.log('a browser that has never been told anything');
let Editor = loadEditor(makeStorage(false));
check(Editor.pointer() === 'mouse',
      'a fresh browser does not start on "mouse", so everybody who has one '
      + 'would find the wheel behaving differently one morning');
check(Editor.wheelMeans({ deltaY: 40 }) === 'zoom',
      'THE OLD BEHAVIOUR IS GONE: the wheel no longer zooms with a mouse');
check(Editor.wheelMeans({ deltaY: 40, ctrlKey: true }) === 'zoom',
      'Ctrl and the wheel does not zoom with a mouse');

console.log('told it is a trackpad');
Editor.setPointer('trackpad');
check(Editor.pointer() === 'trackpad', 'the answer was not kept');
check(Editor.wheelMeans({ deltaX: 20, deltaY: 40 }) === 'pan',
      'THE BUG: two fingers sliding still zooms instead of moving the canvas');
check(Editor.wheelMeans({ deltaY: -40, ctrlKey: true }) === 'zoom',
      'a pinch does not zoom -- the browser reports one as the wheel turning '
      + 'with Ctrl held, and that is the only way to tell it from a slide');
check(Editor.wheelMeans({ deltaY: -40, metaKey: true }) === 'zoom',
      'a pinch on a Mac does not zoom');

console.log('and back again');
Editor.setPointer('mouse');
check(Editor.wheelMeans({ deltaY: 40 }) === 'zoom',
      'switching back to a mouse did not restore the wheel');

console.log('a browser that refuses to store anything');
Editor = loadEditor(makeStorage(true));
check(Editor.pointer() === 'mouse',
      'a browser blocking site data breaks the canvas rather than falling '
      + 'back to the ordinary behaviour');
let threw = false;
try { Editor.setPointer('trackpad'); } catch (err) { threw = true; }
check(!threw, 'changing the setting throws where storage is blocked');

console.log('the spacebar');
Editor = loadEditor(makeStorage(false));
check(Editor._spaceDown === false,
      'the editor starts up believing the spacebar is held down');
check(typeof Editor.pointer === 'function' && typeof Editor.wheelMeans === 'function',
      'the two things the settings panel calls are not both there');

if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log('\ncanvas panning: the wheel still zooms on a mouse, two fingers '
  + 'slide on a trackpad, and a pinch zooms either way');
