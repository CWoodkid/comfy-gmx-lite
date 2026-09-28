/* The Shell tab's screen (comfygmx/web/js/vt.js), checked against tmux.

   A program in a terminal sends text mixed with short codes that move the
   cursor, clear parts of the screen and set colours. The Shell tab's screen
   has to end up showing exactly what a real terminal would. tmux is a
   terminal program that keeps its screen in memory and will print it, so
   this test lets tmux be the judge:

     1. start a program inside tmux, at a fixed size, with TERM set to xterm
        as the Shell tab sets it
     2. record every byte the program writes, press keys as a person would
     3. ask tmux what is on its screen and where the cursor is
     4. give the same bytes to the Shell tab's screen, and compare

   The programs are the ones somebody uses in a terminal: bash with ls and
   long lines, nano, less, man, vim and htop. A program this machine lacks is
   skipped and said so.

   Below that, checks that need no tmux: which keys send what, pasting, the
   answers to a program's questions, and the lines kept after they scroll
   off the top.

   Run:  node tools/shell_screen.js
   It needs tmux for the first part, and nothing else: no browser, no server. */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');
const { execFileSync } = require('child_process');

let failures = 0;
function check(ok, complaint) {
  if (ok) return;
  failures += 1;
  console.log(`  FAILED: ${complaint}`);
}

function loadVT() {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'comfygmx', 'web', 'js', 'vt.js'), 'utf8');
  const sandbox = { console, Math, JSON, Set, Map, TextDecoder };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(`${source}\n;globalThis.__VT = VT;`, sandbox, { filename: 'vt.js' });
  return sandbox.__VT;
}
const VT = loadVT();

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const has = (program) => {
  try {
    execFileSync('sh', ['-c', `command -v ${program}`], { stdio: 'ignore' });
    return true;
  } catch (err) {
    return false;
  }
};

/* ------------------------------------------------------------ tmux side */

// A tmux of its own for each program, so one ending cannot take the next
// one with it, and the tmux somebody is using is never touched.
let socketName = '';
let started = 0;
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-screen-'));

function tmux(...args) {
  return execFileSync('tmux', ['-L', socketName, '-f', '/dev/null', ...args],
    { encoding: 'utf8', env: { ...process.env, LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' } });
}

async function settle(file, quiet = 350, most = 6000) {
  let last = -1;
  let stillFor = 0;
  for (let waited = 0; waited < most; waited += 50) {
    await sleep(50);
    const size = fs.existsSync(file) ? fs.statSync(file).size : 0;
    if (size === last) {
      stillFor += 50;
      if (stillFor >= quiet) return size;
    } else {
      stillFor = 0;
      last = size;
    }
  }
  return last;
}

/* Run one scenario in tmux. steps: a list of key presses (strings are typed
   as they are, {keys: [...]} are tmux key names, {wait: ms} waits, and
   {resize: [cols, rows]} changes the window). Returns the bytes the program
   wrote, where each resize happened in them, and tmux's final screen. */
async function inTmux(command, steps, cols = 80, rows = 24) {
  started += 1;
  socketName = `comfygmx-shell-test-${process.pid}-${started}`;
  const out = path.join(work, `out-${started}.bin`);
  // The pane waits for Enter, so the recording has started before the
  // program writes anything, and stays open after the program ends, so its
  // last screen can still be read. HISTFILE keeps the test's commands out of
  // the bash history of whoever runs it.
  const shellLine = `read -r go; env TERM=xterm-256color LANG=C.UTF-8 LC_ALL=C.UTF-8 `
    + `HISTFILE='${path.join(work, 'history')}' ${command}; sleep 600`;
  tmux('-u', 'new-session', '-d', '-x', String(cols), '-y', String(rows), '-s', 't',
    'sh', '-c', shellLine);
  tmux('set-option', '-t', 't', 'status', 'off');
  tmux('set-window-option', '-t', 't', 'aggressive-resize', 'off');
  tmux('pipe-pane', '-t', 't', '-O', `cat > '${out}'`);
  await sleep(150);
  tmux('send-keys', '-t', 't', 'Enter');
  await settle(out, 500);
  const resizes = [];
  for (const step of steps) {
    if (typeof step === 'string') tmux('send-keys', '-t', 't', '-l', step);
    else if (step.keys) tmux('send-keys', '-t', 't', ...step.keys);
    else if (step.resize) {
      const at = await settle(out);
      tmux('resize-window', '-t', 't', '-x', String(step.resize[0]), '-y', String(step.resize[1]));
      resizes.push({ at, cols: step.resize[0], rows: step.resize[1] });
    }
    if (step.wait) await sleep(step.wait);
    else await settle(out, 250, 3000);
  }
  await settle(out, 500);
  const info = tmux('display-message', '-p', '-t', 't',
    '#{cursor_x} #{cursor_y} #{alternate_on} #{cursor_flag} #{pane_width} #{pane_height}').trim().split(' ');
  const screen = tmux('capture-pane', '-p', '-t', 't', '-N').replace(/\n$/, '').split('\n');
  const bytes = fs.readFileSync(out);
  try { tmux('kill-server'); } catch (err) { /* already gone */ }
  return {
    bytes, resizes, screen,
    cursor: { x: Number(info[0]), y: Number(info[1]) },
    alternate: info[2] === '1', cursorShown: info[3] === '1',
    size: { cols: Number(info[4]), rows: Number(info[5]) },
  };
}

/* Give the same bytes to the Shell tab's screen. */
function inOurs(result, cols, rows) {
  const screen = new VT.Screen(cols, rows);
  const decoder = new TextDecoder('utf-8');
  let from = 0;
  for (const change of result.resizes) {
    screen.write(decoder.decode(result.bytes.subarray(from, change.at), { stream: true }));
    screen.resize(change.cols, change.rows);
    from = change.at;
  }
  screen.write(decoder.decode(result.bytes.subarray(from)));
  return screen;
}

// tmux prints a wide character once and no filler after it; ours keeps an
// empty second column. Both are compared as the text a person would read.
const plain = (line) => line.replace(/\s+$/, '');

// tmux keeps a character from the line-drawing set (ESC ( 0) as the letter
// that asked for it, and prints the letter: "lqqk" where the screen shows
// "┌──┐". A scenario that uses the set says which line, and that line of
// tmux's is turned into the boxes a terminal window draws.
const BOXES = { j: '┘', k: '┐', l: '┌', m: '└', n: '┼', q: '─', t: '├', u: '┤',
                v: '┴', w: '┬', x: '│' };
function asBoxes(line, start, end) {
  const from = line.indexOf(start);
  const to = line.indexOf(end, from + start.length);
  if (from < 0 || to < 0) return line;
  const middle = line.slice(from + start.length, to).replace(/[jklmnqtuvwx]/g, (c) => BOXES[c]);
  return line.slice(0, from + start.length) + middle + line.slice(to);
}

async function compare(name, command, steps, cols = 80, rows = 24, boxes = null) {
  const result = await inTmux(command, steps, cols, rows);
  const ours = inOurs(result, cols, rows);
  const mine = ours.text().map(plain);
  const theirs = result.screen.map(plain)
    .map((line) => (boxes ? asBoxes(line, boxes[0], boxes[1]) : line));
  while (theirs.length < mine.length) theirs.push('');
  const differ = [];
  for (let y = 0; y < mine.length; y++) {
    if (mine[y] !== theirs[y]) differ.push(y);
  }
  check(differ.length === 0,
    `${name}: ${differ.length} line(s) differ from tmux, first line ${differ[0] + 1}:\n`
    + `      ours: ${JSON.stringify(mine[differ[0]])}\n      tmux: ${JSON.stringify(theirs[differ[0]])}`);
  check(ours.x === result.cursor.x && ours.y === result.cursor.y,
    `${name}: the cursor is at column ${ours.x + 1}, line ${ours.y + 1}; tmux has it at `
    + `column ${result.cursor.x + 1}, line ${result.cursor.y + 1}`);
  check(ours.onAlt === result.alternate,
    `${name}: ${ours.onAlt ? 'still on' : 'not on'} the full-screen programs' screen, `
    + `tmux ${result.alternate ? 'is' : 'is not'}`);
  check(ours.cursorVisible === result.cursorShown,
    `${name}: the cursor is ${ours.cursorVisible ? 'shown' : 'hidden'}, in tmux it is `
    + `${result.cursorShown ? 'shown' : 'hidden'}`);
  if (!differ.length) {
    console.log(`  same as tmux: ${name} (${result.bytes.length} bytes, `
      + `${mine.filter(Boolean).length} lines with text)`);
  }
  return { ours, result };
}

/* ------------------------------------------------------------ scenarios */

const sampleFile = path.join(work, 'notes.txt');
fs.writeFileSync(sampleFile, Array.from({ length: 120 },
  (_, i) => `line ${i + 1}: temperature ${(200 + i * 6.7).toFixed(1)} K, `
    + `pressure ${(1 + Math.sin(i) * 0.3).toFixed(3)} bar`).join('\n') + '\n');

// Codes a program can send, each one on its own, with something printed
// around it so a mistake shows.
const codesScript = path.join(work, 'codes.sh');
fs.writeFileSync(codesScript, String.raw`
e=$(printf '\033')
printf '%s' "$e[2J$e[H"
printf 'plain \033[1mbold\033[0m \033[31mred\033[32mgreen\033[0m \033[38;5;208m256\033[38;2;10;200;30mtrue\033[0m\n'
printf 'tabs:\tone\ttwo\tthree\n'
printf 'wrap: %s\n' "$(printf 'x%.0s' $(seq 1 100))"
printf 'erase: abcdefghij\033[5D\033[K\n'
printf 'erase left: abcdefghij\033[5D\033[1K\n'
printf 'insert: abcdef\033[3D\033[2@XY\n'
printf 'delete: abcdefgh\033[5D\033[2P\n'
printf 'erase chars: abcdefgh\033[5D\033[3X\n'
printf 'repeat: z\033[5b\n'
printf 'wide: 分子 dynamics, µs, Å, ü\n'
printf 'wide, half written over: 分子\033[2DX\n'
printf '%s分 at the edge\n' "$(printf 'a%.0s' $(seq 1 79))"
printf 'combining: e\314\201 a\314\210\n'
printf 'line drawing: \033(0lqqk x x mqqj\033(B done\n'
printf 'save \0337here\0338X restore\n'
printf '\033[s\033[20;10Hat 20,10\033[u after\n'
printf 'to column 40:\033[40Gmark\n'
printf 'up and back\033[Aup!\033[B\r\n'
printf 'region:\n'
printf '\033[15;18r\033[15;1Hr1\nr2\nr3\nr4\nr5\nr6\033[r\033[21;1H'
printf 'insert line\033[2A\033[L\033[B\033[M\n'
printf '\033[?7lno wrap: %s\033[?7h\n' "$(printf 'y%.0s' $(seq 1 90))"
printf '\033[?1049hon the other screen\033[?1049lback\n'
printf '\033[1;31;44mcoloured to the end\033[K\033[0m\n'
printf 'scroll up two\033[2S\033[1T done\n'
printf 'reverse index at the top:\033[H\033M\033M'
printf '\033[23;1Hlast'
`);

// A long command line edited in the middle: the shell redraws it across the
// line it wrapped onto.
const longWord = 'abcdefghij'.repeat(9);

const scenarios = [
  { name: 'codes one by one', command: `bash ${codesScript}`, steps: [],
    boxes: ['line drawing: ', ' done'] },
  {
    name: 'bash: ls, colours, a long line edited across its wrap',
    command: 'bash --norc --noprofile -i',
    steps: [
      'PS1="\\[\\e[1;32m\\]me@here\\[\\e[0m\\]:\\[\\e[1;34m\\]\\w\\[\\e[0m\\]\\$ "', { keys: ['Enter'] },
      `ls --color=always -F ${path.dirname(sampleFile)} /usr/bin | head -40`, { keys: ['Enter'] },
      `echo ${longWord}`, { keys: ['Left', 'Left', 'Left', 'Left', 'Left', 'Left', 'Left',
        'Left', 'Left', 'Left', 'Left', 'Left', 'Left', 'Left', 'Left'] },
      'INSERTED', { keys: ['Home'] }, { keys: ['End'] }, { keys: ['Enter'] },
      'seq 1 30', { keys: ['Enter'] },
    ],
  },
  {
    name: 'nano: open, type, cut and paste a line, save',
    need: 'nano',
    command: `nano -I ${sampleFile}`,
    steps: [
      { keys: ['Down', 'Down', 'End'] }, ' (edited)', { keys: ['C-k'] }, { keys: ['Down'] },
      { keys: ['C-u'] }, { keys: ['C-o'] }, { keys: ['Enter'] }, { keys: ['NPage'] },
    ],
  },
  {
    name: 'nano: after quitting, the shell lines come back',
    need: 'nano',
    command: `bash --norc --noprofile -c 'echo before nano; nano -I ${sampleFile}; echo after nano; sleep 5'`,
    steps: [{ keys: ['C-x'] }, { wait: 600 }],
  },
  {
    name: 'nano: the window made smaller and larger',
    need: 'nano',
    command: `nano -I ${sampleFile}`,
    steps: [{ resize: [60, 18] }, { wait: 500 }, { resize: [100, 30] }, { wait: 500 }],
  },
  {
    name: 'nano: resized while open, then quit: the shell lines are where they were',
    need: 'nano',
    command: `bash --norc --noprofile -c 'seq 1 30; nano -I ${sampleFile}; echo after nano; sleep 5'`,
    steps: [{ resize: [70, 16] }, { wait: 400 }, { resize: [90, 28] }, { wait: 400 },
      { keys: ['C-x'] }, { wait: 600 }],
  },
  {
    name: 'less: page down, search',
    need: 'less',
    command: `less ${sampleFile}`,
    steps: [{ keys: ['Space'] }, '/pressure 1.2', { keys: ['Enter'] }, { keys: ['Down', 'Down'] }],
  },
  {
    name: 'man: bold and underlined words',
    need: 'man',
    command: 'man ls',
    steps: [{ keys: ['NPage'] }],
  },
  {
    name: 'vim: insert text, numbered lines',
    need: 'vim',
    command: `vim -u NONE -N -i NONE ${sampleFile}`,
    steps: [':set number', { keys: ['Enter'] }, 'Otyped in vim', { keys: ['Escape'] },
      { keys: ['C-d'] }],
  },
  {
    name: 'htop: coloured bars and a table',
    need: 'htop',
    command: 'htop -d 100',
    steps: [{ wait: 1200 }, { keys: ['F2'] }, { wait: 600 }],
  },
];

/* ------------------------------------------------------------ no tmux */

function checksWithoutTmux() {
  console.log('keys, pasting, answers and the scrollback');
  const key = (k, extra = {}, screen = null) => VT.keyToText(
    { key: k, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false,
      getModifierState: () => false, ...extra }, screen);
  check(key('Enter') === '\r', 'Enter does not send a carriage return');
  check(key('Backspace') === '\x7f', 'Backspace does not send DEL, as xterm does');
  check(key('c', { ctrlKey: true }) === '\x03', 'Ctrl+C does not send the interrupt character');
  check(key('d', { ctrlKey: true }) === '\x04', 'Ctrl+D does not send end-of-input');
  check(key('x', { altKey: true }) === '\x1bx', 'Alt+x does not send Escape x');
  check(key('ArrowUp') === '\x1b[A', 'the up arrow is wrong');
  check(key('ArrowUp', {}, { appCursor: true }) === '\x1bOA',
    'the up arrow ignores the mode full-screen programs ask for');
  check(key('ArrowLeft', { ctrlKey: true }) === '\x1b[1;5D', 'Ctrl+Left (a word back) is wrong');
  check(key('PageDown') === '\x1b[6~' && key('F1') === '\x1bOP' && key('F10') === '\x1b[21~',
    'Page Down or the F keys are wrong');
  check(key('a') === null, 'a plain letter is sent from the key, not typed through the text box');
  check(key('@', { ctrlKey: true, altKey: true, getModifierState: (m) => m === 'AltGraph' }) === null,
    'AltGr+Q (@ on a German keyboard) is taken as Ctrl+Alt instead of typing @');

  // Pasting: marked as a paste when the shell asks, and a paste cannot end
  // the marking early and have the rest typed as commands.
  const sent = [];
  const fakeView = Object.create(VT.View.prototype);
  fakeView.screen = new VT.Screen(80, 24);
  fakeView.options = { onData: (text) => sent.push(text) };
  fakeView.screen.write('\x1b[?2004h');
  fakeView.paste('ls\nrm -rf x\x1b[201~echo sneaked\n');
  check(sent[0] === '\x1b[200~ls\rrm -rf xecho sneaked\r\x1b[201~',
    `a paste was not marked, or its own end marker was left in: ${JSON.stringify(sent[0])}`);
  check(!/\x1b\[201~echo/.test(sent[0]), 'a paste could end the paste marking early');

  // A program's questions get answers; the answers go back to it.
  const replies = [];
  const asked = new VT.Screen(80, 24, { onReply: (text) => replies.push(text) });
  asked.write('\x1b[5;10H\x1b[6n\x1b[c\x1b[18t');
  check(replies[0] === '\x1b[5;10R', `asked where the cursor is, it said ${JSON.stringify(replies[0])}`);
  check(replies[1] === '\x1b[?1;2c', 'asked what kind of terminal it is, it did not answer as xterm');
  check(replies[2] === '\x1b[8;24;80t', 'asked its size, it did not say 24 lines of 80');

  // Lines that scroll off the top are kept, up to the limit.
  const long = new VT.Screen(40, 5, { scrollback: 100 });
  for (let i = 1; i <= 300; i++) long.write(`line ${i}\r\n`);
  check(long.scrollback.length === 100, `kept ${long.scrollback.length} lines, not the 100 asked for`);
  check(long.scrollback[99].text().startsWith('line 296'),
    'the last line kept is not the one just above the screen');
  check(long.text()[0].startsWith('line 297'), 'the screen does not show the last lines written');

  // Made taller, the screen takes lines back from the scrollback; made
  // shorter, the cursor's line stays on it.
  long.resize(40, 8);
  check(long.text()[0].startsWith('line 294') && long.y === 7,
    `made taller, it did not bring back lines from above (top line ${JSON.stringify(long.text()[0])})`);
  long.resize(40, 3);
  check(long.y === 2 && long.text()[1].startsWith('line 300'),
    'made shorter, the cursor line fell off the screen');

  // Pieces of one character arriving in two parts (a pipe can split a
  // character's bytes anywhere) still make the character.
  const split = new VT.Screen(20, 2);
  const bytes = Buffer.from('Å€');
  const decoder = new TextDecoder('utf-8');
  split.write(decoder.decode(bytes.subarray(0, 1), { stream: true }));
  split.write(decoder.decode(bytes.subarray(1), { stream: true }));
  check(split.text()[0].startsWith('Å€'), `a character split in two arrived as ${JSON.stringify(split.text()[0])}`);

  // Text in the page is escaped: a file name with < and & in it is shown,
  // not taken as part of the page.
  const html = VT.rowHtml(Object.assign(new VT.Row(12), {}), -1, '', false);
  check(!/</.test(html.replace(/<\/?span[^>]*>/g, '')), 'an empty line drew something other than blanks');
  const risky = new VT.Screen(20, 1);
  risky.write('<b>&x');
  const drawn = VT.rowHtml(risky.lines[0], -1, '', false);
  check(drawn.includes('&lt;b&gt;&amp;x'), `a < or & was not escaped: ${drawn}`);
}

/* ------------------------------------------------------------ run */

(async () => {
  try {
    checksWithoutTmux();
  } catch (err) {
    failures += 1;
    console.log(`  FAILED: the checks stopped with an error: ${err.stack}`);
  }
  if (!has('tmux')) {
    console.log('tmux is not installed: the comparison with real programs is skipped');
  } else {
    console.log('real programs, compared with tmux');
    for (const scenario of scenarios) {
      if (scenario.need && !has(scenario.need)) {
        console.log(`  skipped: ${scenario.name} (${scenario.need} is not installed)`);
        continue;
      }
      try {
        await compare(scenario.name, scenario.command, scenario.steps,
          scenario.cols || 80, scenario.rows || 24, scenario.boxes);
      } catch (err) {
        failures += 1;
        console.log(`  FAILED: ${scenario.name}: ${err.message}`);
        try { tmux('kill-server'); } catch (e) { /* not running */ }
      }
    }
  }
  fs.rmSync(work, { recursive: true, force: true });
  if (failures) {
    console.log(`\n${failures} check(s) failed`);
    process.exit(1);
  }
  console.log('\nall passed');
})();
