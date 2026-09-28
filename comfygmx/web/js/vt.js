/* The Shell tab's screen: what a terminal window does with what a program
   writes to it.

   A program in a terminal does not only print text. It also sends short
   codes, each starting with the Escape character, that move the cursor,
   clear part of the screen, change colours, or switch to a second screen.
   Full-screen programs such as nano, less and top draw on that second
   screen and leave it again when they end, so the shell's lines come back
   as they were. The codes are the ones the xterm terminal understands,
   because that is what the shell is told it is talking to
   (TERM=xterm-256color, in comfygmx/shell.py).

   Two parts:

     * VT.Screen keeps the grid of characters and follows the codes. It knows
       nothing about the page, so it can be tested on its own:
       tools/shell_screen.js runs real programs inside tmux (a terminal
       program that keeps a screen the same way) and checks that this one
       ends up showing what tmux shows.
     * VT.View puts a Screen on the page, and turns key presses, pastes and
       the mouse into what a terminal would send to the program.

   Written here rather than taken from a library, like the plots and the
   molecule viewer: the page loads nothing from outside this folder. */
'use strict';

const VT = (() => {
  /* ------------------------------------------------------------ widths */

  // Characters that take two columns: Chinese, Japanese and Korean script,
  // full-width forms, and emoji. From Unicode's East Asian Width table,
  // shortened to the blocks that matter.
  const WIDE = [
    [0x1100, 0x115F], [0x231A, 0x231B], [0x2329, 0x232A], [0x23E9, 0x23EC],
    [0x23F0, 0x23F0], [0x23F3, 0x23F3], [0x25FD, 0x25FE], [0x2614, 0x2615],
    [0x2648, 0x2653], [0x267F, 0x267F], [0x2693, 0x2693], [0x26A1, 0x26A1],
    [0x26AA, 0x26AB], [0x26BD, 0x26BE], [0x26C4, 0x26C5], [0x26CE, 0x26CE],
    [0x26D4, 0x26D4], [0x26EA, 0x26EA], [0x26F2, 0x26F3], [0x26F5, 0x26F5],
    [0x26FA, 0x26FA], [0x26FD, 0x26FD], [0x2705, 0x2705], [0x270A, 0x270B],
    [0x2728, 0x2728], [0x274C, 0x274C], [0x274E, 0x274E], [0x2753, 0x2755],
    [0x2757, 0x2757], [0x2795, 0x2797], [0x27B0, 0x27B0], [0x27BF, 0x27BF],
    [0x2B1B, 0x2B1C], [0x2B50, 0x2B50], [0x2B55, 0x2B55], [0x2E80, 0x303E],
    [0x3041, 0x33FF], [0x3400, 0x4DBF], [0x4E00, 0x9FFF], [0xA000, 0xA4CF],
    [0xA960, 0xA97F], [0xAC00, 0xD7A3], [0xF900, 0xFAFF], [0xFE10, 0xFE19],
    [0xFE30, 0xFE6F], [0xFF00, 0xFF60], [0xFFE0, 0xFFE6], [0x16FE0, 0x16FE4],
    [0x17000, 0x18CFF], [0x1B000, 0x1B2FF], [0x1F004, 0x1F004], [0x1F0CF, 0x1F0CF],
    [0x1F18E, 0x1F18E], [0x1F191, 0x1F19A], [0x1F200, 0x1F202], [0x1F210, 0x1F23B],
    [0x1F240, 0x1F248], [0x1F250, 0x1F251], [0x1F260, 0x1F265], [0x1F300, 0x1F320],
    [0x1F32D, 0x1F335], [0x1F337, 0x1F37C], [0x1F37E, 0x1F393], [0x1F3A0, 0x1F3CA],
    [0x1F3CF, 0x1F3D3], [0x1F3E0, 0x1F3F0], [0x1F3F4, 0x1F3F4], [0x1F3F8, 0x1F43E],
    [0x1F440, 0x1F440], [0x1F442, 0x1F4FC], [0x1F4FF, 0x1F53D], [0x1F54B, 0x1F54E],
    [0x1F550, 0x1F567], [0x1F57A, 0x1F57A], [0x1F595, 0x1F596], [0x1F5A4, 0x1F5A4],
    [0x1F5FB, 0x1F64F], [0x1F680, 0x1F6C5], [0x1F6CC, 0x1F6CC], [0x1F6D0, 0x1F6D2],
    [0x1F6D5, 0x1F6D7], [0x1F6DC, 0x1F6DF], [0x1F6EB, 0x1F6EC], [0x1F6F4, 0x1F6FC],
    [0x1F7E0, 0x1F7EB], [0x1F7F0, 0x1F7F0], [0x1F90C, 0x1F93A], [0x1F93C, 0x1F945],
    [0x1F947, 0x1F9FF], [0x1FA70, 0x1FAFF], [0x20000, 0x2FFFD], [0x30000, 0x3FFFD],
  ];
  // Accents and other marks that sit on the character before them.
  const ZERO_WIDTH = /^[\p{Mn}\p{Me}​-‏⁠-⁤﻿]$/u;

  function charWidth(code, ch) {
    if (code < 0x300) return 1;
    if (ZERO_WIDTH.test(ch)) return 0;
    if (code >= 0x1160 && code <= 0x11FF) return 0;  // Korean vowel and final parts
    let low = 0;
    let high = WIDE.length - 1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (code < WIDE[mid][0]) high = mid - 1;
      else if (code > WIDE[mid][1]) low = mid + 1;
      else return 2;
    }
    return 1;
  }

  // The line-drawing set that ESC ( 0 switches to: some programs draw boxes
  // with ordinary letters and ask for this set, instead of sending the box
  // characters themselves.
  const LINES = {
    '`': '◆', a: '▒', b: '␉', c: '␌', d: '␍', e: '␊', f: '°', g: '±', h: '␤',
    i: '␋', j: '┘', k: '┐', l: '┌', m: '└', n: '┼', o: '⎺', p: '⎻', q: '─',
    r: '⎼', s: '⎽', t: '├', u: '┤', v: '┴', w: '┬', x: '│', y: '≤', z: '≥',
    '{': 'π', '|': '≠', '}': '£', '~': '·',
  };

  /* Text attributes, one bit each. */
  const BOLD = 1;
  const DIM = 2;
  const ITALIC = 4;
  const UNDERLINE = 8;
  const BLINK = 16;
  const INVERSE = 32;
  const HIDDEN = 64;
  const STRIKE = 128;
  // A colour is -1 for "the default", 0-255 for the 256 numbered colours, or
  // TRUE + 0xRRGGBB for one given exactly.
  const TRUE = 0x1000000;

  /* One line of the screen: a character, two colours and the attributes for
     each column. The second column of a wide character holds ''. */
  class Row {
    constructor(cols, bg = -1) {
      this.ch = new Array(cols).fill(' ');
      this.fg = new Int32Array(cols).fill(-1);
      this.bg = new Int32Array(cols).fill(bg);
      this.fl = new Uint8Array(cols);
      // True when this line ran on into the next one (it was too long to fit),
      // so copying the two gives one line back.
      this.wrapped = false;
    }

    get length() { return this.ch.length; }

    clear(from, to, bg) {
      for (let i = from; i < to; i++) {
        this.ch[i] = ' ';
        this.fg[i] = -1;
        this.bg[i] = bg;
        this.fl[i] = 0;
      }
    }

    copyCell(to, from) {
      this.ch[to] = this.ch[from];
      this.fg[to] = this.fg[from];
      this.bg[to] = this.bg[from];
      this.fl[to] = this.fl[from];
    }

    resized(cols) {
      const row = new Row(cols);
      const keep = Math.min(cols, this.ch.length);
      for (let i = 0; i < keep; i++) {
        row.ch[i] = this.ch[i];
        row.fg[i] = this.fg[i];
        row.bg[i] = this.bg[i];
        row.fl[i] = this.fl[i];
      }
      // A wide character cut in half at the new edge is removed.
      if (keep > 0 && keep < this.ch.length && this.ch[keep] === '') row.clear(keep - 1, keep, -1);
      row.wrapped = this.wrapped;
      return row;
    }

    text() {
      return this.ch.join('');
    }

    /* Trailing blanks dropped, for keeping lines that scrolled off the top. */
    trimmed() {
      let end = this.ch.length;
      while (end > 0 && this.ch[end - 1] === ' ' && this.bg[end - 1] === -1
             && !(this.fl[end - 1] & (INVERSE | UNDERLINE | STRIKE))) end -= 1;
      if (end === this.ch.length) return this;
      const row = this.resized(end);
      row.wrapped = this.wrapped;
      return row;
    }
  }

  function defaultTabs(cols) {
    const stops = new Uint8Array(cols);
    for (let i = 8; i < cols; i += 8) stops[i] = 1;
    return stops;
  }

  /* ============================================================ Screen */

  class Screen {
    constructor(cols = 80, rows = 24, options = {}) {
      this.cols = cols;
      this.rows = rows;
      this.maxScrollback = options.scrollback || 5000;
      // What the terminal sends back when a program asks it something (its
      // size, where the cursor is). The View passes it on to the shell.
      this.onReply = options.onReply || (() => {});
      this.onTitle = options.onTitle || (() => {});
      this.onBell = options.onBell || (() => {});
      this.scrollback = [];
      // Lines that scrolled off the top since the View last looked.
      this.scrolledOff = [];
      this.dirty = new Set();
      this.title = '';
      this._state = 0;
      this.reset(true);
    }

    /* Everything back to how a new terminal starts. */
    reset(first = false) {
      this.normal = this._buffer();
      this.alt = this._buffer();
      this.buffer = this.normal;
      this.lines = this.normal.lines;
      this.x = 0;
      this.y = 0;
      this.wrapPending = false;
      this.fg = -1;
      this.bg = -1;
      this.fl = 0;
      this.insertMode = false;
      this.newLineMode = false;
      this.appCursor = false;
      this.appKeypad = false;
      this.autowrap = true;
      this.originMode = false;
      this.cursorVisible = true;
      this.cursorStyle = 0;
      this.reverseVideo = false;
      this.bracketedPaste = false;
      this.mouseMode = 0;          // 0 off, 9, 1000, 1002 or 1003
      this.mouseSgr = false;       // report the mouse in the 1006 form
      this.focusEvents = false;
      this.charsets = ['B', 'B', 'B', 'B'];
      this.shift = 0;              // which of the sets above is in use
      this.tabs = defaultTabs(this.cols);
      this.lastChar = '';
      this._state = 0;
      if (!first) this.touchAll();
    }

    _buffer() {
      const lines = [];
      for (let i = 0; i < this.rows; i++) lines.push(new Row(this.cols));
      return { lines, top: 0, bottom: this.rows - 1, saved: null };
    }

    get top() { return this.buffer.top; }
    get bottom() { return this.buffer.bottom; }
    get onAlt() { return this.buffer === this.alt; }

    touch(y) { this.dirty.add(y); }

    touchAll() {
      for (let y = 0; y < this.rows; y++) this.dirty.add(y);
    }

    /* The whole screen as text, one string per line. For tests, and for
       copying all of it. */
    text() {
      return this.lines.map((row) => row.text());
    }

    /* ------------------------------------------------------- the input */

    write(data) {
      for (let i = 0; i < data.length; i++) {
        let code = data.charCodeAt(i);
        let ch = data[i];
        if (code >= 0xD800 && code <= 0xDBFF && i + 1 < data.length) {
          const next = data.charCodeAt(i + 1);
          if (next >= 0xDC00 && next <= 0xDFFF) {
            code = ((code - 0xD800) << 10) + (next - 0xDC00) + 0x10000;
            ch = data.slice(i, i + 2);
            i += 1;
          }
        }
        this._take(code, ch);
      }
    }

    _take(code, ch) {
      switch (this._state) {
        case 0: // ordinary text
          if (code >= 0x20 && code !== 0x7F) {
            if (code >= 0x80 && code < 0xA0) return;  // stray control bytes
            this.print(code, ch);
          } else this.control(code);
          return;
        case 1: // just after Escape
          this._escape(code, ch);
          return;
        case 2: // Escape and a character that needs one more (ESC ( 0)
          this._escapeMore(ch);
          return;
        case 3: // inside ESC [ ... (a "CSI" sequence)
          this._csiByte(code, ch);
          return;
        case 4: // inside ESC ] ... (an "OSC" string: titles and the like)
          if (code === 0x07) { this._osc(); this._state = 0; }
          else if (code === 0x1B) this._state = 5;
          else if (this._str.length < 4096) this._str += ch;
          return;
        case 5: // Escape inside an OSC string: the end, if a backslash follows
          if (ch === '\\') this._osc();
          this._state = 0;
          if (ch !== '\\') this._take(code, ch);
          return;
        case 6: // a string that is read and thrown away (DCS, APC, PM, SOS)
          if (code === 0x1B) this._state = 7;
          else if (code === 0x18 || code === 0x1A) this._state = 0;
          return;
        case 7:
          this._state = ch === '\\' ? 0 : 6;
          return;
        default:
          this._state = 0;
      }
    }

    control(code) {
      switch (code) {
        case 0x07: this.onBell(); break;
        case 0x08: this.backspace(); break;
        case 0x09: this.tab(1); break;
        case 0x0A: case 0x0B: case 0x0C:
          this.lineFeed();
          if (this.newLineMode) this.x = 0;
          break;
        case 0x0D: this.x = 0; this.wrapPending = false; break;
        case 0x0E: this.shift = 1; break;
        case 0x0F: this.shift = 0; break;
        case 0x1B: this._state = 1; break;
        default: break;
      }
    }

    _escape(code, ch) {
      this._state = 0;
      switch (ch) {
        case '[':
          this._state = 3;
          this._prefix = '';
          this._params = '';
          this._inter = '';
          return;
        case ']': this._state = 4; this._str = ''; return;
        case 'P': case 'X': case '^': case '_': this._state = 6; return;
        case '(': case ')': case '*': case '+': case '-': case '.': case '/':
        case '#': case '%': case ' ':
          this._state = 2;
          this._which = ch;
          return;
        case '7': this.saveCursor(); return;
        case '8': this.restoreCursor(); return;
        case 'D': this.index(); return;
        case 'E': this.index(); this.x = 0; return;
        case 'H': this.tabs[Math.min(this.x, this.cols - 1)] = 1; return;
        case 'M': this.reverseIndex(); return;
        case 'c': this.reset(); return;
        case '=': this.appKeypad = true; return;
        case '>': this.appKeypad = false; return;
        case '\\': return;
        default:
          if (code < 0x20) this.control(code);
      }
    }

    _escapeMore(ch) {
      this._state = 0;
      const which = this._which;
      const slot = { '(': 0, ')': 1, '*': 2, '+': 3, '-': 1, '.': 2, '/': 3 }[which];
      if (slot !== undefined) {
        this.charsets[slot] = ch;
        return;
      }
      if (which === '#' && ch === '8') {
        // Fill the screen with E: a test pattern for lining up a monitor.
        this.buffer.top = 0;
        this.buffer.bottom = this.rows - 1;
        for (const row of this.lines) {
          row.clear(0, this.cols, -1);
          row.ch.fill('E');
        }
        this.x = 0;
        this.y = 0;
        this.touchAll();
      }
    }

    _csiByte(code, ch) {
      if (code >= 0x30 && code <= 0x3F) {
        if (!this._params && !this._inter && '<=>?'.includes(ch)) this._prefix = ch;
        else this._params += ch;
      } else if (code >= 0x20 && code <= 0x2F) {
        this._inter += ch;
      } else if (code >= 0x40 && code <= 0x7E) {
        this._state = 0;
        this._csi(ch);
      } else if (code === 0x1B) {
        this._state = 1;
      } else if (code === 0x18 || code === 0x1A) {
        this._state = 0;
      } else if (code < 0x20) {
        this.control(code);
      }
    }

    /* The numbers of a CSI sequence. Each is a list, because 38:2:r:g:b puts
       several in one place; an empty place is -1. */
    _numbers() {
      if (!this._params) return [];
      return this._params.split(';').map((part) => part.split(':')
        .map((n) => (n === '' ? -1 : Math.min(parseInt(n, 10) || 0, 65535))));
    }

    _csi(final) {
      const all = this._numbers();
      const p = all.map((sub) => sub[0]);
      // The n-th number, where 0 or nothing means the usual one.
      const n = (i, usual = 1) => (p[i] > 0 ? p[i] : usual);
      const prefix = this._prefix;
      const inter = this._inter;
      if (inter) {
        if (inter === ' ' && final === 'q') this.cursorStyle = Math.max(0, p[0] || 0);
        else if (inter === '!' && final === 'p') this.softReset();
        else if (inter === '$' && final === 'p') this._reportMode(prefix, p[0]);
        return;
      }
      if (prefix === '?') {
        if (final === 'h' || final === 'l') for (const mode of p) this._privateMode(mode, final === 'h');
        else if (final === 'J') this.eraseInDisplay(Math.max(0, p[0] || 0));
        else if (final === 'K') this.eraseInLine(Math.max(0, p[0] || 0));
        else if (final === 'n' && p[0] === 6) this.onReply(`\x1b[?${this._row()};${this.x + 1}R`);
        return;
      }
      if (prefix === '>') {
        if (final === 'c') this.onReply('\x1b[>0;276;0c');
        return;
      }
      if (prefix) return;
      switch (final) {
        case '@': this.insertChars(n(0)); break;
        case 'A': this.cursorUp(n(0)); break;
        case 'B': this.cursorDown(n(0)); break;
        case 'C': this.cursorForward(n(0)); break;
        case 'D': this.cursorBack(n(0)); break;
        case 'E': this.cursorDown(n(0)); this.x = 0; break;
        case 'F': this.cursorUp(n(0)); this.x = 0; break;
        case 'G': case '`': this.goToColumn(n(0) - 1); break;
        case 'H': case 'f': this.goTo(n(0) - 1, n(1) - 1); break;
        case 'I': this.tab(n(0)); break;
        case 'J': this.eraseInDisplay(Math.max(0, p[0] || 0)); break;
        case 'K': this.eraseInLine(Math.max(0, p[0] || 0)); break;
        case 'L': this.insertLines(n(0)); break;
        case 'M': this.deleteLines(n(0)); break;
        case 'P': this.deleteChars(n(0)); break;
        case 'S': this.scrollUp(n(0)); break;
        case 'T': if (p.length <= 1) this.scrollDown(n(0)); break;
        case 'X': this.eraseChars(n(0)); break;
        case 'Z': this.tabBack(n(0)); break;
        case 'a': this.goToColumn(this.x + n(0)); break;
        case 'b': this.repeat(n(0)); break;
        case 'c': if (!(p[0] > 0)) this.onReply('\x1b[?1;2c'); break;
        case 'd': this.goToRow(n(0) - 1); break;
        case 'e': this.goToRow(this._row() - 1 + n(0)); break;
        case 'g':
          if (!(p[0] > 0)) this.tabs[Math.min(this.x, this.cols - 1)] = 0;
          else if (p[0] === 3) this.tabs.fill(0);
          break;
        case 'h': case 'l':
          for (const mode of p) {
            if (mode === 4) this.insertMode = final === 'h';
            else if (mode === 20) this.newLineMode = final === 'h';
          }
          break;
        case 'm': this.sgr(all); break;
        case 'n':
          if (p[0] === 5) this.onReply('\x1b[0n');
          else if (p[0] === 6) this.onReply(`\x1b[${this._row()};${this.x + 1}R`);
          break;
        case 'r': this.setMargins(n(0) - 1, n(1, this.rows) - 1); break;
        case 's': this.saveCursor(); break;
        case 'u': this.restoreCursor(); break;
        case 't':
          if (p[0] === 18) this.onReply(`\x1b[8;${this.rows};${this.cols}t`);
          else if (p[0] === 19) this.onReply(`\x1b[9;${this.rows};${this.cols}t`);
          break;
        default: break;
      }
    }

    /* The cursor's line as a program counts it: from the top of the scroll
       region when "origin mode" is on, from the top of the screen if not. */
    _row() {
      return this.y + 1 - (this.originMode ? this.top : 0);
    }

    _reportMode(prefix, mode) {
      let value = 0;
      if (prefix === '?') {
        const known = {
          1: this.appCursor, 6: this.originMode, 7: this.autowrap,
          25: this.cursorVisible, 47: this.onAlt, 1047: this.onAlt, 1049: this.onAlt,
          9: this.mouseMode === 9, 1000: this.mouseMode === 1000,
          1002: this.mouseMode === 1002, 1003: this.mouseMode === 1003,
          1004: this.focusEvents, 1006: this.mouseSgr, 2004: this.bracketedPaste,
        };
        if (mode in known) value = known[mode] ? 1 : 2;
      } else if (mode === 4) value = this.insertMode ? 1 : 2;
      else if (mode === 20) value = this.newLineMode ? 1 : 2;
      this.onReply(`\x1b[${prefix === '?' ? '?' : ''}${mode};${value}$y`);
    }

    _privateMode(mode, on) {
      switch (mode) {
        case 1: this.appCursor = on; break;
        case 5: this.reverseVideo = on; this.touchAll(); break;
        case 6: this.originMode = on; this.goTo(0, 0); break;
        case 7: this.autowrap = on; break;
        case 9: case 1000: case 1002: case 1003: this.mouseMode = on ? mode : 0; break;
        case 25: this.cursorVisible = on; this.touch(this.y); break;
        case 1004: this.focusEvents = on; break;
        case 1006: this.mouseSgr = on; break;
        case 2004: this.bracketedPaste = on; break;
        case 47: case 1047:
          if (on) this.toAlt(false);
          else this.toNormal(mode === 1047);
          break;
        case 1048: if (on) this.saveCursor(); else this.restoreCursor(); break;
        case 1049:
          if (on) {
            this.saveCursor();
            this.toAlt(true);
          } else {
            this.toNormal(true);
            this.restoreCursor();
          }
          break;
        default: break;
      }
    }

    toAlt(clear) {
      if (this.onAlt) return;
      if (clear) this.alt = this._buffer();
      this.buffer = this.alt;
      this.lines = this.alt.lines;
      this.touchAll();
    }

    toNormal(clearAlt) {
      if (!this.onAlt) return;
      if (clearAlt) for (const row of this.alt.lines) row.clear(0, this.cols, -1);
      this.buffer = this.normal;
      this.lines = this.normal.lines;
      this.touchAll();
    }

    softReset() {
      this.insertMode = false;
      this.originMode = false;
      this.autowrap = true;
      this.cursorVisible = true;
      this.appCursor = false;
      this.appKeypad = false;
      this.buffer.top = 0;
      this.buffer.bottom = this.rows - 1;
      this.fg = -1;
      this.bg = -1;
      this.fl = 0;
      this.charsets = ['B', 'B', 'B', 'B'];
      this.shift = 0;
      this.buffer.saved = null;
      this.wrapPending = false;
    }

    /* SGR: the colours and attributes for what is printed next. */
    sgr(all) {
      if (!all.length) all = [[0]];
      for (let i = 0; i < all.length; i++) {
        const sub = all[i];
        const code = sub[0] < 0 ? 0 : sub[0];
        if (code === 38 || code === 48 || code === 58) {
          let colour = null;
          if (sub.length > 1) {
            // 38:5:n or 38:2:r:g:b, or 38:2::r:g:b with a colour-space slot.
            if (sub[1] === 5) colour = sub[2] >= 0 ? sub[2] & 255 : null;
            else if (sub[1] === 2) {
              const rgb = sub.length >= 6 ? sub.slice(3, 6) : sub.slice(2, 5);
              colour = TRUE + (((rgb[0] & 255) << 16) | ((rgb[1] & 255) << 8) | (rgb[2] & 255));
            }
          } else {
            const kind = all[i + 1] ? all[i + 1][0] : -1;
            if (kind === 5) {
              colour = all[i + 2] ? all[i + 2][0] & 255 : null;
              i += 2;
            } else if (kind === 2) {
              const r = all[i + 2] ? all[i + 2][0] & 255 : 0;
              const g = all[i + 3] ? all[i + 3][0] & 255 : 0;
              const b = all[i + 4] ? all[i + 4][0] & 255 : 0;
              colour = TRUE + ((r << 16) | (g << 8) | b);
              i += 4;
            } else {
              i += 1;
            }
          }
          if (colour !== null && code === 38) this.fg = colour;
          else if (colour !== null && code === 48) this.bg = colour;
          continue;
        }
        if (code === 0) { this.fg = -1; this.bg = -1; this.fl = 0; }
        else if (code === 1) this.fl |= BOLD;
        else if (code === 2) this.fl |= DIM;
        else if (code === 3) this.fl |= ITALIC;
        else if (code === 4) {
          if (sub.length > 1 && sub[1] === 0) this.fl &= ~UNDERLINE;
          else this.fl |= UNDERLINE;
        } else if (code === 5 || code === 6) this.fl |= BLINK;
        else if (code === 7) this.fl |= INVERSE;
        else if (code === 8) this.fl |= HIDDEN;
        else if (code === 9) this.fl |= STRIKE;
        else if (code === 21) this.fl |= UNDERLINE;
        else if (code === 22) this.fl &= ~(BOLD | DIM);
        else if (code === 23) this.fl &= ~ITALIC;
        else if (code === 24) this.fl &= ~UNDERLINE;
        else if (code === 25) this.fl &= ~BLINK;
        else if (code === 27) this.fl &= ~INVERSE;
        else if (code === 28) this.fl &= ~HIDDEN;
        else if (code === 29) this.fl &= ~STRIKE;
        else if (code >= 30 && code <= 37) this.fg = code - 30;
        else if (code === 39) this.fg = -1;
        else if (code >= 40 && code <= 47) this.bg = code - 40;
        else if (code === 49) this.bg = -1;
        else if (code >= 90 && code <= 97) this.fg = code - 90 + 8;
        else if (code >= 100 && code <= 107) this.bg = code - 100 + 8;
      }
    }

    _osc() {
      const text = this._str || '';
      const cut = text.indexOf(';');
      const what = cut < 0 ? text : text.slice(0, cut);
      const value = cut < 0 ? '' : text.slice(cut + 1);
      if (what === '0' || what === '2') {
        this.title = value;
        this.onTitle(value);
      } else if ((what === '10' || what === '11') && value === '?') {
        // A program asking the colours, to choose its own (vim does).
        const colour = what === '10' ? 'd7d7/dddd/e5e5' : '0d0d/0f0f/1313';
        this.onReply(`\x1b]${what};rgb:${colour}\x1b\\`);
      }
      this._str = '';
    }

    /* ------------------------------------------------------ printing */

    print(code, ch) {
      const set = this.charsets[this.shift];
      if (set === '0' && code >= 0x5F && code <= 0x7E) ch = LINES[ch] || ch;
      const width = charWidth(code, ch);
      if (width === 0) {
        // A mark that goes on the character before it.
        let x = this.wrapPending ? this.x : this.x - 1;
        if (x < 0) return;
        const row = this.lines[this.y];
        if (row.ch[x] === '' && x > 0) x -= 1;
        row.ch[x] += ch;
        this.touch(this.y);
        return;
      }
      if (this.wrapPending) {
        if (this.autowrap) {
          this.lines[this.y].wrapped = true;
          this.index();
          this.x = 0;
        }
        this.wrapPending = false;
      }
      if (width === 2 && this.x === this.cols - 1) {
        if (this.autowrap) {
          const row = this.lines[this.y];
          row.clear(this.x, this.x + 1, this.bg);
          row.wrapped = true;
          this.touch(this.y);
          this.index();
          this.x = 0;
        } else {
          return;
        }
      }
      const row = this.lines[this.y];
      if (this.insertMode) {
        for (let i = this.cols - 1; i >= this.x + width; i--) row.copyCell(i, i - width);
      }
      this._unsplit(row, this.x, width);
      row.ch[this.x] = ch;
      row.fg[this.x] = this.fg;
      row.bg[this.x] = this.bg;
      row.fl[this.x] = this.fl;
      if (width === 2) {
        row.ch[this.x + 1] = '';
        row.fg[this.x + 1] = this.fg;
        row.bg[this.x + 1] = this.bg;
        row.fl[this.x + 1] = this.fl;
      }
      this.lastChar = ch;
      this.touch(this.y);
      this.x += width;
      if (this.x >= this.cols) {
        this.x = this.cols - 1;
        this.wrapPending = this.autowrap;
      }
    }

    /* Writing over half of a wide character blanks its other half, so no
       half-character is left on the screen. */
    _unsplit(row, x, width) {
      if (row.ch[x] === '' && x > 0) row.clear(x - 1, x, row.bg[x - 1]);
      const end = x + width;
      if (end < this.cols && row.ch[end] === '' ) row.clear(end, end + 1, row.bg[end]);
    }

    repeat(count) {
      if (!this.lastChar) return;
      const code = this.lastChar.codePointAt(0);
      for (let i = 0; i < Math.min(count, 65535); i++) this.print(code, this.lastChar);
    }

    /* ------------------------------------------------------ moving */

    backspace() {
      this.wrapPending = false;
      if (this.x > 0) this.x -= 1;
    }

    tab(count) {
      for (let k = 0; k < count; k++) {
        let x = this.x + 1;
        while (x < this.cols - 1 && !this.tabs[x]) x += 1;
        this.x = Math.min(x, this.cols - 1);
      }
      this.wrapPending = false;
    }

    tabBack(count) {
      for (let k = 0; k < count; k++) {
        let x = this.x - 1;
        while (x > 0 && !this.tabs[x]) x -= 1;
        this.x = Math.max(0, x);
      }
      this.wrapPending = false;
    }

    lineFeed() {
      this.index();
    }

    /* Down one line; at the bottom of the scroll region, the region moves up
       instead and its top line goes. */
    index() {
      this.wrapPending = false;
      if (this.y === this.bottom) this.scrollUp(1);
      else if (this.y < this.rows - 1) this.y += 1;
    }

    reverseIndex() {
      this.wrapPending = false;
      if (this.y === this.top) this.scrollDown(1);
      else if (this.y > 0) this.y -= 1;
    }

    cursorUp(count) {
      const limit = this.y >= this.top ? this.top : 0;
      this.y = Math.max(limit, this.y - count);
      this.wrapPending = false;
    }

    cursorDown(count) {
      const limit = this.y <= this.bottom ? this.bottom : this.rows - 1;
      this.y = Math.min(limit, this.y + count);
      this.wrapPending = false;
    }

    cursorForward(count) {
      this.x = Math.min(this.cols - 1, this.x + count);
      this.wrapPending = false;
    }

    cursorBack(count) {
      this.x = Math.max(0, this.x - count);
      this.wrapPending = false;
    }

    goToColumn(x) {
      this.x = Math.max(0, Math.min(this.cols - 1, x));
      this.wrapPending = false;
    }

    goToRow(y) {
      const top = this.originMode ? this.top : 0;
      const bottom = this.originMode ? this.bottom : this.rows - 1;
      this.y = Math.max(top, Math.min(bottom, top + y));
      this.wrapPending = false;
    }

    goTo(y, x) {
      this.goToRow(y);
      this.goToColumn(x);
    }

    setMargins(top, bottom) {
      bottom = Math.min(bottom, this.rows - 1);
      if (top < 0) top = 0;
      if (top >= bottom) return;
      this.buffer.top = top;
      this.buffer.bottom = bottom;
      this.goTo(0, 0);
    }

    saveCursor() {
      this.buffer.saved = {
        x: this.x, y: this.y, wrapPending: this.wrapPending,
        fg: this.fg, bg: this.bg, fl: this.fl, originMode: this.originMode,
        charsets: this.charsets.slice(), shift: this.shift,
      };
    }

    restoreCursor() {
      const saved = this.buffer.saved;
      if (!saved) {
        this.x = 0;
        this.y = 0;
        this.wrapPending = false;
        this.fg = -1;
        this.bg = -1;
        this.fl = 0;
        this.originMode = false;
        return;
      }
      this.x = Math.min(saved.x, this.cols - 1);
      this.y = Math.min(saved.y, this.rows - 1);
      this.wrapPending = saved.wrapPending && this.x === this.cols - 1;
      this.fg = saved.fg;
      this.bg = saved.bg;
      this.fl = saved.fl;
      this.originMode = saved.originMode;
      this.charsets = saved.charsets.slice();
      this.shift = saved.shift;
    }

    /* ------------------------------------------------------ scrolling */

    scrollUp(count) {
      const top = this.top;
      const bottom = this.bottom;
      count = Math.min(count, bottom - top + 1);
      for (let k = 0; k < count; k++) {
        const [gone] = this.lines.splice(top, 1);
        this.lines.splice(bottom, 0, new Row(this.cols, this.bg));
        if (top === 0 && !this.onAlt) this._keep(gone);
      }
      for (let y = top; y <= bottom; y++) this.touch(y);
    }

    scrollDown(count) {
      const top = this.top;
      const bottom = this.bottom;
      count = Math.min(count, bottom - top + 1);
      for (let k = 0; k < count; k++) {
        this.lines.splice(bottom, 1);
        this.lines.splice(top, 0, new Row(this.cols, this.bg));
      }
      for (let y = top; y <= bottom; y++) this.touch(y);
    }

    _keep(row) {
      const kept = row.trimmed();
      this.scrollback.push(kept);
      this.scrolledOff.push(kept);
      if (this.scrollback.length > this.maxScrollback) this.scrollback.shift();
      if (this.scrolledOff.length > this.maxScrollback) this.scrolledOff.shift();
    }

    insertLines(count) {
      if (this.y < this.top || this.y > this.bottom) return;
      count = Math.min(count, this.bottom - this.y + 1);
      for (let k = 0; k < count; k++) {
        this.lines.splice(this.bottom, 1);
        this.lines.splice(this.y, 0, new Row(this.cols, this.bg));
      }
      for (let y = this.y; y <= this.bottom; y++) this.touch(y);
      this.x = 0;
      this.wrapPending = false;
    }

    deleteLines(count) {
      if (this.y < this.top || this.y > this.bottom) return;
      count = Math.min(count, this.bottom - this.y + 1);
      for (let k = 0; k < count; k++) {
        this.lines.splice(this.y, 1);
        this.lines.splice(this.bottom, 0, new Row(this.cols, this.bg));
      }
      for (let y = this.y; y <= this.bottom; y++) this.touch(y);
      this.x = 0;
      this.wrapPending = false;
    }

    /* ------------------------------------------------------ erasing */

    eraseInDisplay(mode) {
      const rows = this.lines;
      if (mode === 0) {
        this.eraseInLine(0);
        for (let y = this.y + 1; y < this.rows; y++) {
          rows[y].clear(0, this.cols, this.bg);
          rows[y].wrapped = false;
          this.touch(y);
        }
      } else if (mode === 1) {
        this.eraseInLine(1);
        for (let y = 0; y < this.y; y++) {
          rows[y].clear(0, this.cols, this.bg);
          rows[y].wrapped = false;
          this.touch(y);
        }
      } else if (mode === 2) {
        for (let y = 0; y < this.rows; y++) {
          rows[y].clear(0, this.cols, this.bg);
          rows[y].wrapped = false;
          this.touch(y);
        }
      } else if (mode === 3) {
        this.scrollback = [];
        this.scrolledOff = [];
        this.clearedScrollback = true;
      }
    }

    eraseInLine(mode) {
      const row = this.lines[this.y];
      const x = Math.min(this.x, this.cols - 1);
      if (mode === 0) {
        row.clear(x, this.cols, this.bg);
        row.wrapped = false;
      } else if (mode === 1) {
        row.clear(0, x + 1, this.bg);
      } else if (mode === 2) {
        row.clear(0, this.cols, this.bg);
        row.wrapped = false;
      }
      this.touch(this.y);
    }

    eraseChars(count) {
      const row = this.lines[this.y];
      this._unsplit(row, this.x, Math.min(count, this.cols - this.x));
      row.clear(this.x, Math.min(this.cols, this.x + count), this.bg);
      this.touch(this.y);
      this.wrapPending = false;
    }

    insertChars(count) {
      const row = this.lines[this.y];
      count = Math.min(count, this.cols - this.x);
      for (let i = this.cols - 1; i >= this.x + count; i--) row.copyCell(i, i - count);
      row.clear(this.x, this.x + count, this.bg);
      this.touch(this.y);
      this.wrapPending = false;
    }

    deleteChars(count) {
      const row = this.lines[this.y];
      count = Math.min(count, this.cols - this.x);
      for (let i = this.x; i < this.cols - count; i++) row.copyCell(i, i + count);
      row.clear(this.cols - count, this.cols, this.bg);
      this.touch(this.y);
      this.wrapPending = false;
    }

    /* ------------------------------------------------------ resizing */

    resize(cols, rows) {
      cols = Math.max(2, cols | 0);
      rows = Math.max(2, rows | 0);
      if (cols === this.cols && rows === this.rows) return;
      for (const buffer of [this.normal, this.alt]) {
        let lines = buffer.lines.map((row) => (row.length === cols ? row : row.resized(cols)));
        const isCurrent = buffer === this.buffer;
        // The screen not on show (the shell's, while nano covers it) keeps
        // its cursor in the place saved when it was left.
        const saved = !isCurrent && buffer.saved ? buffer.saved.y : null;
        let cursorY = isCurrent ? this.y : (saved === null ? 0 : saved);
        const cursorWas = cursorY;
        if (rows < lines.length) {
          // Fewer lines: the ones above the cursor go into the scrollback, so
          // the cursor and what is near it stay on the screen.
          let drop = lines.length - rows;
          const below = lines.length - 1 - cursorY;
          const fromBottom = Math.min(drop, Math.max(0, below));
          lines.splice(lines.length - fromBottom, fromBottom);
          drop -= fromBottom;
          if (drop > 0) {
            const gone = lines.splice(0, drop);
            if (buffer === this.normal) for (const row of gone) this._keep(row);
            cursorY -= drop;
          }
        } else if (rows > lines.length) {
          // More lines: bring back lines from the scrollback first, the way
          // a terminal window does when it is made taller.
          let add = rows - lines.length;
          if (buffer === this.normal) {
            while (add > 0 && this.scrollback.length) {
              const back = this.scrollback.pop();
              if (this.scrolledOff.length && this.scrolledOff[this.scrolledOff.length - 1] === back) {
                this.scrolledOff.pop();
              } else {
                this.pulledBack = (this.pulledBack || 0) + 1;
              }
              lines.unshift(back.length === cols ? back : back.resized(cols));
              cursorY += 1;
              add -= 1;
            }
          }
          while (add > 0) {
            lines.push(new Row(cols));
            add -= 1;
          }
        }
        buffer.lines = lines;
        buffer.top = 0;
        buffer.bottom = rows - 1;
        if (buffer.saved) {
          if (saved !== null) buffer.saved.y += cursorY - cursorWas;
          buffer.saved.x = Math.min(buffer.saved.x, cols - 1);
          buffer.saved.y = Math.max(0, Math.min(buffer.saved.y, rows - 1));
        }
        if (isCurrent) this.y = Math.max(0, Math.min(rows - 1, cursorY));
      }
      this.lines = this.buffer.lines;
      this.cols = cols;
      this.rows = rows;
      this.x = Math.min(this.x, cols - 1);
      this.wrapPending = false;
      const tabs = defaultTabs(cols);
      tabs.set(this.tabs.subarray(0, Math.min(cols, this.tabs.length)));
      this.tabs = tabs;
      this.dirty = new Set();
      this.touchAll();
    }
  }

  /* ============================================================ keys */

  const SPECIAL = {
    ArrowUp: 'A', ArrowDown: 'B', ArrowRight: 'C', ArrowLeft: 'D',
    Home: 'H', End: 'F',
  };
  const TILDE = {
    Insert: 2, Delete: 3, PageUp: 5, PageDown: 6,
    F5: 15, F6: 17, F7: 18, F8: 19, F9: 20, F10: 21, F11: 23, F12: 24,
  };
  const SS3 = { F1: 'P', F2: 'Q', F3: 'R', F4: 'S' };

  /* What a key press sends to the program, as xterm would send it; null when
     the key is for the browser to deal with (typing an ordinary letter goes
     through the text box instead, so accents and other keyboards work). */
  function keyToText(event, screen) {
    const { key } = event;
    const altGr = event.getModifierState && event.getModifierState('AltGraph');
    const ctrl = event.ctrlKey && !altGr;
    const alt = event.altKey && !altGr;
    const shift = event.shiftKey;
    const modifier = 1 + (shift ? 1 : 0) + (alt ? 2 : 0) + (ctrl ? 4 : 0);
    if (key in SPECIAL) {
      const letter = SPECIAL[key];
      if (modifier > 1) return `\x1b[1;${modifier}${letter}`;
      return (screen && screen.appCursor ? '\x1bO' : '\x1b[') + letter;
    }
    if (key in TILDE) {
      return modifier > 1 ? `\x1b[${TILDE[key]};${modifier}~` : `\x1b[${TILDE[key]}~`;
    }
    if (key in SS3) return modifier > 1 ? `\x1b[1;${modifier}${SS3[key]}` : `\x1bO${SS3[key]}`;
    switch (key) {
      case 'Enter': return alt ? '\x1b\r' : '\r';
      case 'Backspace':
        if (ctrl) return '\x08';
        return alt ? '\x1b\x7f' : '\x7f';
      case 'Tab': return shift ? '\x1b[Z' : '\t';
      case 'Escape': return '\x1b';
      default: break;
    }
    if (ctrl && !event.metaKey && key.length === 1) {
      const lower = key.toLowerCase();
      let code = null;
      if (lower >= 'a' && lower <= 'z') code = lower.charCodeAt(0) - 96;
      else if (key === ' ' || key === '@' || key === '2') code = 0;
      else if (key === '[' || key === '3') code = 27;
      else if (key === '\\' || key === '4') code = 28;
      else if (key === ']' || key === '5') code = 29;
      else if (key === '^' || key === '6') code = 30;
      else if (key === '_' || key === '-' || key === '7' || key === '/') code = 31;
      else if (key === '?' || key === '8') code = 127;
      if (code !== null) return (alt ? '\x1b' : '') + String.fromCharCode(code);
      return null;
    }
    if (alt && !event.metaKey && key.length === 1) return `\x1b${key}`;
    return null;
  }

  /* ============================================================ View */

  // The sixteen numbered colours, chosen to read well on the drawer's
  // near-black background. Programs pick from these ("ls" makes folders
  // blue, programs green).
  const PALETTE = [
    '#1c1f24', '#e06c75', '#98c379', '#e5c07b', '#61afef', '#c678dd', '#56b6c2', '#b8bfc9',
    '#5c6370', '#ff7b86', '#b5e08e', '#f5d48a', '#7cc1ff', '#d98ef0', '#6fd0dc', '#ffffff',
  ];
  const FG = '#d7dde5';
  const BG = '#0d0f13';

  function colourOf(value) {
    if (value >= TRUE) return `#${(value - TRUE).toString(16).padStart(6, '0')}`;
    if (value < 16) return PALETTE[value];
    if (value < 232) {
      const n = value - 16;
      const steps = [0, 95, 135, 175, 215, 255];
      const r = steps[Math.floor(n / 36)];
      const g = steps[Math.floor(n / 6) % 6];
      const b = steps[n % 6];
      return `rgb(${r},${g},${b})`;
    }
    const grey = 8 + (value - 232) * 10;
    return `rgb(${grey},${grey},${grey})`;
  }

  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
  const escapeHtml = (text) => text.replace(/[&<>"]/g, (c) => ESCAPES[c]);

  /* The style for one run of characters that look the same. */
  function styleOf(fg, bg, fl, reverse) {
    let front = fg;
    let back = bg;
    if ((fl & BOLD) && front >= 0 && front < 8) front += 8;
    let inverse = Boolean(fl & INVERSE) !== Boolean(reverse);
    let css = '';
    let cls = '';
    if (inverse) {
      const f = back < 0 ? BG : colourOf(back);
      const b = front < 0 ? FG : colourOf(front);
      css += `color:${f};background:${b};`;
    } else {
      if (front >= 0) css += `color:${colourOf(front)};`;
      if (back >= 0) css += `background:${colourOf(back)};`;
    }
    if (fl & BOLD) cls += ' b';
    if (fl & DIM) cls += ' d';
    if (fl & ITALIC) cls += ' i';
    if (fl & UNDERLINE) cls += ' u';
    if (fl & STRIKE) cls += ' s';
    if (fl & UNDERLINE && fl & STRIKE) cls += ' us';
    if (fl & HIDDEN) css += 'color:transparent;';
    return { css, cls: cls.trim() };
  }

  /* One line as HTML. Characters outside plain ASCII each get a box exactly
     as wide as their columns, so a box-drawing line or a Chinese name cannot
     push the rest of the line out of step when the font draws it a little
     wider or narrower. */
  function rowHtml(row, cursorX, cursorClass, reverse) {
    let html = '';
    const cols = row.length;
    let i = 0;
    while (i < cols) {
      const fg = row.fg[i];
      const bg = row.bg[i];
      const fl = row.fl[i];
      const atCursor = i === cursorX;
      let text = '';
      let j = i;
      if (atCursor) {
        const ch = row.ch[i];
        const wide = i + 1 < cols && row.ch[i + 1] === '';
        const odd = ch.length > 1 || (ch && ch.charCodeAt(0) > 0x7E);
        const { css, cls } = styleOf(fg, bg, fl, reverse);
        html += `<span class="${[cls, cursorClass, odd || wide ? 'g' : '', wide ? 'w2' : '']
          .filter(Boolean).join(' ')}"`
          + `${css ? ` style="${css}"` : ''}>${escapeHtml(ch === '' ? ' ' : ch)}</span>`;
        i += wide ? 2 : 1;
        continue;
      }
      while (j < cols && row.fg[j] === fg && row.bg[j] === bg && row.fl[j] === fl
             && j !== cursorX) {
        const ch = row.ch[j];
        const code = ch.charCodeAt(0);
        if (ch === '' || code > 0x7E || ch.length > 1) break;
        text += ch;
        j += 1;
      }
      const { css, cls } = styleOf(fg, bg, fl, reverse);
      const open = `<span${cls ? ` class="${cls}"` : ''}${css ? ` style="${css}"` : ''}>`;
      if (text) {
        html += `${open}${escapeHtml(text)}</span>`;
        i = j;
        continue;
      }
      // One character outside ASCII, in a box of its own width.
      const ch = row.ch[i];
      const wide = i + 1 < cols && row.ch[i + 1] === '';
      if (ch === '') {  // the right half of a wide character whose left half was cut
        html += `${open} </span>`;
        i += 1;
        continue;
      }
      html += `<span class="${[cls, wide ? 'g w2' : 'g'].filter(Boolean).join(' ')}"`
        + `${css ? ` style="${css}"` : ''}>${escapeHtml(ch)}</span>`;
      i += wide ? 2 : 1;
    }
    return html;
  }

  class View {
    /* host: the element the terminal fills. options: onData(text) for what
       to send to the program, onResize(cols, rows), onTitle(text),
       onCopy(text) to put text on the clipboard. */
    constructor(host, options = {}) {
      this.host = host;
      this.options = options;
      this.screen = new Screen(80, 24, {
        onReply: (text) => { if (!this.quiet) this.send(text); },
        onTitle: (text) => options.onTitle && options.onTitle(text),
        onBell: () => this._bell(),
      });
      this.quiet = false;
      this.focused = false;
      this._frame = 0;
      this._decoder = new TextDecoder('utf-8');
      this._build();
      this.measure();
    }

    _build() {
      const host = this.host;
      host.classList.add('vt');
      this.viewport = document.createElement('div');
      this.viewport.className = 'vt-viewport';
      this.backEl = document.createElement('div');
      this.backEl.className = 'vt-scrollback';
      this.screenEl = document.createElement('div');
      this.screenEl.className = 'vt-screen';
      this.viewport.append(this.backEl, this.screenEl);
      // The keyboard goes to a text box you cannot see. A text box, rather
      // than listening to the page, is what lets accents, dead keys and
      // other keyboard layouts type what they should.
      this.input = document.createElement('textarea');
      this.input.className = 'vt-input';
      this.input.setAttribute('autocomplete', 'off');
      this.input.setAttribute('autocorrect', 'off');
      this.input.setAttribute('autocapitalize', 'off');
      this.input.setAttribute('spellcheck', 'false');
      this.input.setAttribute('aria-label', 'Shell: type here');
      host.append(this.viewport, this.input);
      this.rowEls = [];

      this.input.addEventListener('keydown', (event) => this._keydown(event));
      // Selecting text with the mouse takes the keyboard away from the text
      // box, and it must not go to the page: there, a letter is a shortcut
      // for the graph (T tidies it, Delete removes blocks). The screen can
      // hold the keyboard itself, which keeps the selection, and the first
      // key pressed after selecting goes on to the shell as usual.
      this.viewport.tabIndex = -1;
      host.addEventListener('keydown', (event) => {
        if (event.target !== this.input) this._keydown(event, true);
      });
      this.input.addEventListener('input', (event) => this._typed(event));
      this.input.addEventListener('compositionend', (event) => {
        this.input.value = '';
        if (event.data) this.send(event.data);
      });
      this.input.addEventListener('paste', (event) => this._paste(event));
      this.input.addEventListener('focus', () => this._focus(true));
      this.input.addEventListener('blur', () => this._focus(false));
      this.viewport.addEventListener('mousedown', (event) => this._mouse(event, 'down'));
      this.viewport.addEventListener('mouseup', (event) => this._mouse(event, 'up'));
      this.viewport.addEventListener('mousemove', (event) => this._mouse(event, 'move'));
      this.viewport.addEventListener('wheel', (event) => this._wheel(event), { passive: false });
      this.viewport.addEventListener('copy', (event) => this._copyEvent(event));
      if (typeof ResizeObserver !== 'undefined') {
        this._observer = new ResizeObserver(() => this.fit());
        this._observer.observe(this.viewport);
      }
    }

    /* The size of one character cell, from the font actually in use. */
    measure() {
      const probe = document.createElement('span');
      probe.className = 'vt-probe';
      probe.textContent = 'W'.repeat(100);
      this.screenEl.appendChild(probe);
      const box = probe.getBoundingClientRect();
      probe.remove();
      if (box.width > 0) this.cellWidth = box.width / 100;
      const style = getComputedStyle(this.screenEl);
      this.cellHeight = parseFloat(style.lineHeight) || 16;
      if (this.cellWidth) this.host.style.setProperty('--cw', `${this.cellWidth}px`);
      return this.cellWidth > 0;
    }

    /* Fit the grid to the space the drawer gives it. */
    fit() {
      if (!this.viewport.offsetParent) return;  // hidden: nothing to measure
      if (!this.cellWidth && !this.measure()) return;
      const style = getComputedStyle(this.viewport);
      const width = this.viewport.clientWidth - parseFloat(style.paddingLeft)
        - parseFloat(style.paddingRight);
      const height = this.viewport.clientHeight - parseFloat(style.paddingTop)
        - parseFloat(style.paddingBottom);
      const cols = Math.max(20, Math.floor(width / this.cellWidth));
      const rows = Math.max(3, Math.floor(height / this.cellHeight));
      if (cols === this.screen.cols && rows === this.screen.rows && this.rowEls.length === rows) return;
      this.screen.resize(cols, rows);
      this._rebuildRows();
      this.render();
      if (this.options.onResize) this.options.onResize(cols, rows);
    }

    get cols() { return this.screen.cols; }
    get rows() { return this.screen.rows; }

    _rebuildRows() {
      this.screenEl.textContent = '';
      this.rowEls = [];
      for (let y = 0; y < this.screen.rows; y++) {
        const el = document.createElement('div');
        el.className = 'vt-row';
        this.screenEl.appendChild(el);
        this.rowEls.push(el);
      }
      if (this.screen.pulledBack) {
        // Lines taken back from the scrollback onto a taller screen.
        for (let k = 0; k < this.screen.pulledBack && this.backEl.lastChild; k++) {
          this.backEl.lastChild.remove();
        }
        this.screen.pulledBack = 0;
      }
      this.screen.touchAll();
    }

    /* What the program wrote: bytes, or text already decoded. */
    write(data) {
      const text = typeof data === 'string' ? data : this._decoder.decode(data, { stream: true });
      const cursorWas = this.screen.y;
      this.screen.write(text);
      this.screen.touch(cursorWas);
      this.screen.touch(this.screen.y);
      this._schedule();
    }

    /* Write without answering the questions in it: used for the catch-up of
       a shell's screen when the page comes back, whose questions were
       answered the first time round. Answering again would type the answers
       into the shell. */
    replay(data) {
      this.quiet = true;
      try { this.write(data); } finally { this.quiet = false; }
    }

    /* Everything cleared, as for a new shell. */
    reset() {
      this.screen.reset();
      this.screen.scrollback = [];
      this.screen.scrolledOff = [];
      this.backEl.textContent = '';
      this._decoder = new TextDecoder('utf-8');
      this._schedule();
    }

    /* All the text there is, lines kept above the screen included: for the
       Copy button with nothing selected. A line that only wrapped because it
       was too long is joined back to the next. */
    allText() {
      const screen = this.screen;
      const rows = screen.onAlt ? screen.lines : [...screen.scrollback, ...screen.lines];
      let out = '';
      for (const row of rows) {
        const text = row.ch.join('');
        out += row.wrapped ? text : `${text.replace(/\s+$/, '')}\n`;
      }
      return out.replace(/\n+$/, '\n');
    }

    /* A line of the page's own, in grey, not from the program. */
    note(text) {
      this.write(`\x1b[0m\x1b[2m${text.replace(/\n/g, '\r\n')}\x1b[0m\r\n`);
    }

    send(text) {
      if (text && this.options.onData) this.options.onData(text);
    }

    _schedule() {
      if (this._frame) return;
      const draw = () => { this._frame = 0; this.render(); };
      this._frame = typeof requestAnimationFrame === 'function'
        ? requestAnimationFrame(draw) : setTimeout(draw, 16);
    }

    render() {
      const screen = this.screen;
      if (this.rowEls.length !== screen.rows) this._rebuildRows();
      const viewport = this.viewport;
      const atBottom = viewport.scrollTop + viewport.clientHeight >= viewport.scrollHeight - 4;
      if (screen.clearedScrollback) {
        this.backEl.textContent = '';
        screen.clearedScrollback = false;
      }
      if (screen.scrolledOff.length) {
        const added = document.createDocumentFragment();
        for (const row of screen.scrolledOff) {
          const el = document.createElement('div');
          el.className = 'vt-row';
          el.innerHTML = rowHtml(row, -1, '', screen.reverseVideo);
          if (row.wrapped) el.dataset.wrapped = '1';
          added.appendChild(el);
        }
        screen.scrolledOff = [];
        this.backEl.appendChild(added);
        const extra = this.backEl.childElementCount - screen.maxScrollback;
        for (let k = 0; k < extra; k++) this.backEl.firstChild.remove();
      }
      this.backEl.classList.toggle('hidden', screen.onAlt);
      const showCursor = screen.cursorVisible;
      const style = ['block', 'block', 'block', 'under', 'under', 'bar', 'bar'][screen.cursorStyle] || 'block';
      const cursorClass = `vt-cursor ${style}${this.focused ? ' on' : ''}`;
      for (const y of screen.dirty) {
        const el = this.rowEls[y];
        if (!el) continue;
        const row = screen.lines[y];
        el.innerHTML = rowHtml(row, showCursor && y === screen.y ? screen.x : -1,
          cursorClass, screen.reverseVideo);
        if (row.wrapped) el.dataset.wrapped = '1';
        else delete el.dataset.wrapped;
      }
      screen.dirty.clear();
      this.host.classList.toggle('reverse', screen.reverseVideo);
      if (atBottom || this._stick) {
        viewport.scrollTop = viewport.scrollHeight;
        this._stick = false;
      }
      this._placeInput();
    }

    /* The hidden text box sits on the cursor, so the window for typing
       Chinese or Japanese opens where the text goes. */
    _placeInput() {
      const x = this.screen.x * (this.cellWidth || 7);
      const y = this.screenEl.offsetTop - this.viewport.scrollTop
        + this.screen.y * (this.cellHeight || 16);
      this.input.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
    }

    focus() {
      this.input.focus({ preventScroll: true });
    }

    _focus(on) {
      this.focused = on;
      this.host.classList.toggle('focused', on);
      this.screen.touch(this.screen.y);
      this._schedule();
      if (this.screen.focusEvents) this.send(on ? '\x1b[I' : '\x1b[O');
    }

    _bell() {
      this.host.classList.remove('bell');
      void this.host.offsetWidth;  // start the flash again if it is running
      this.host.classList.add('bell');
    }

    /* ------------------------------------------------------ keyboard */

    selectionText() {
      const selection = window.getSelection ? window.getSelection() : null;
      if (!selection || selection.isCollapsed || !selection.rangeCount) return '';
      if (!this.viewport.contains(selection.anchorNode)
          && !this.viewport.contains(selection.focusNode)) return '';
      // Rows are fixed-width, so a selected line ends in the blanks after its
      // last character. They are not part of what anybody meant to copy.
      return selection.toString().split('\n').map((line) => line.replace(/\s+$/, '')).join('\n');
    }

    _keydown(event, outside = false) {
      event.stopPropagation();
      if (event.isComposing || event.keyCode === 229) return;
      const ctrl = event.ctrlKey || event.metaKey;
      const key = event.key;
      if (this.options.onKey && this.options.onKey(event) === false) return;
      // Copy: Ctrl+Shift+C always, Ctrl+C when something is selected
      // (otherwise Ctrl+C is the program's: it stops what is running).
      if (ctrl && (key === 'c' || key === 'C')) {
        const text = this.selectionText();
        if (text && (event.shiftKey || !event.altKey)) {
          event.preventDefault();
          this.copy(text);
          return;
        }
        if (event.shiftKey) { event.preventDefault(); return; }
      }
      if (['Shift', 'Control', 'Alt', 'Meta', 'AltGraph', 'CapsLock'].includes(key)) return;
      // The keyboard was on the screen, after a selection: back to the text
      // box, so that what this key types lands there.
      if (outside) this.input.focus({ preventScroll: true });
      // Paste: let the browser do it, and take the text from its paste event.
      if (ctrl && (key === 'v' || key === 'V')) return;
      if (event.metaKey && !event.ctrlKey) return;  // Cmd+key on a Mac: the browser's
      let text = keyToText(event, this.screen);
      // A letter pressed while the screen held the keyboard: the text box
      // has only just been given it back, too late for the browser to type
      // this letter into it, so it is sent from here.
      if (text === null && outside && !ctrl && [...key].length === 1) text = key;
      if (text === null) return;
      event.preventDefault();
      this._stick = true;
      this.send(text);
    }

    _typed(event) {
      if (event.isComposing) return;
      const text = this.input.value;
      this.input.value = '';
      if (!text) return;
      this._stick = true;
      this.send(text.replace(/\n/g, '\r'));
    }

    _paste(event) {
      event.preventDefault();
      const data = event.clipboardData ? event.clipboardData.getData('text/plain') : '';
      if (!data) return;
      this.paste(data);
    }

    paste(data) {
      let text = data.replace(/\r\n/g, '\r').replace(/\n/g, '\r');
      if (this.screen.bracketedPaste) {
        // Marked as a paste, so a shell does not run each line as it arrives.
        // The end marker is taken out of the text itself: a paste must not
        // be able to end the paste early and type what follows as commands.
        text = `\x1b[200~${text.replace(/\x1b\[20[01]~/g, '')}\x1b[201~`;
      }
      this._stick = true;
      this.send(text);
    }

    copy(text) {
      if (this.options.onCopy) this.options.onCopy(text);
      else this.focus();
    }

    _copyEvent(event) {
      const text = this.selectionText();
      if (!text || !event.clipboardData) return;
      event.clipboardData.setData('text/plain', text);
      event.preventDefault();
    }

    /* ------------------------------------------------------ mouse */

    _cell(event) {
      const box = this.screenEl.getBoundingClientRect();
      const x = Math.floor((event.clientX - box.left) / this.cellWidth);
      const y = Math.floor((event.clientY - box.top) / this.cellHeight);
      return {
        x: Math.max(0, Math.min(this.screen.cols - 1, x)),
        y: Math.max(0, Math.min(this.screen.rows - 1, y)),
        inside: y >= 0 && y < this.screen.rows,
      };
    }

    /* Programs that ask for the mouse (htop, or vim with mouse=a) are told
       about clicks. Holding Shift selects text instead, as in xterm. */
    _mouse(event, what) {
      const mode = this.screen.mouseMode;
      if (mode && !event.shiftKey) {
        const { x, y, inside } = this._cell(event);
        if (!inside) return;
        if (what === 'move') {
          if (!(mode === 1003 || (mode === 1002 && this._button !== undefined))) return;
          this._report(this._button === undefined ? 3 : this._button, x, y, 'move', event);
          return;
        }
        event.preventDefault();
        const button = event.button === 1 ? 1 : event.button === 2 ? 2 : 0;
        if (what === 'down') this._button = button;
        else this._button = undefined;
        this._report(button, x, y, what, event);
        if (what === 'up') this.focus();
        return;
      }
      if (what === 'up') {
        // A click with nothing selected puts the keyboard back in the shell.
        if (!this.selectionText()) this.focus();
      }
    }

    _report(button, x, y, what, event) {
      let code = button;
      if (what === 'move') code += 32;
      if (event.shiftKey) code += 4;
      if (event.altKey) code += 8;
      if (event.ctrlKey) code += 16;
      if (this.screen.mouseMode === 9 && what !== 'down') return;
      if (this.screen.mouseSgr) {
        this.send(`\x1b[<${code};${x + 1};${y + 1}${what === 'up' ? 'm' : 'M'}`);
        return;
      }
      if (what === 'up') code = 3 + (code & ~3);
      if (x > 222 || y > 222) return;  // the old form cannot say more
      this.send(`\x1b[M${String.fromCharCode(32 + code, 33 + x, 33 + y)}`);
    }

    _wheel(event) {
      const lines = Math.max(1, Math.min(10, Math.round(Math.abs(event.deltaY) / 30) || 1));
      if (!event.deltaY) return;
      const up = event.deltaY < 0;
      if (this.screen.mouseMode && !event.shiftKey) {
        event.preventDefault();
        const { x, y } = this._cell(event);
        const code = up ? 64 : 65;
        for (let k = 0; k < Math.min(lines, 3); k++) {
          if (this.screen.mouseSgr) this.send(`\x1b[<${code};${x + 1};${y + 1}M`);
          else if (x <= 222 && y <= 222) {
            this.send(`\x1b[M${String.fromCharCode(32 + code, 33 + x, 33 + y)}`);
          }
        }
        return;
      }
      if (this.screen.onAlt) {
        // less, man and nano scroll with the arrow keys; the wheel sends
        // those, since a full-screen program keeps no scrollback to scroll.
        event.preventDefault();
        const key = this.screen.appCursor ? (up ? '\x1bOA' : '\x1bOB') : (up ? '\x1b[A' : '\x1b[B');
        this.send(key.repeat(lines));
      }
    }

    dispose() {
      if (this._observer) this._observer.disconnect();
      this.host.textContent = '';
    }
  }

  return { Screen, View, Row, keyToText, charWidth, rowHtml, PALETTE };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = VT;
