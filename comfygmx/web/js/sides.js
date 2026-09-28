/* The panels on either side of the canvas can be put away, the way the
   Terminal drawer under it can, so the graph gets the whole width when that
   is all you are working on.

     left:  Nodes, Chunks and Tutorials
     right: Log, Problems, Command, Files, Viewer and Plot

   Each has a small button that hides it: ◂ beside the search box on the left,
   ▸ at the end of the tabs on the right. A hidden panel leaves a slim tab on
   that edge of the canvas, named after the tab that was showing in it, and
   clicking that brings the panel back. Ctrl+[ and Ctrl+] do the same from the
   keyboard (App.onKey). Which panels are hidden is remembered in this
   browser, as the drawer's height is.

   The graph stays where it is on screen. Hiding the left panel moves the
   canvas's left edge to the left; the view moves the same distance the other
   way, so no node jumps out from under the pointer.

   The right panel comes back by itself when you ask for something in it:
   Check finding problems, Show command, a node's picture opened large, a file
   opened (App.showTab and App.activateTab). Merely clicking a node does not
   bring it back. */
const SidePanels = {
  /* Which panels are out. */
  open: { left: true, right: true },

  PARTS: {
    left: { panel: 'palette', tabs: 'palette-tabs', hide: 'palette-hide',
            handle: 'palette-handle', name: 'Nodes' },
    right: { panel: 'inspector', tabs: 'inspector-tabs', hide: 'inspector-hide',
             handle: 'inspector-handle', name: 'Log' },
  },

  init() {
    const stored = this._load();
    for (const side of Object.keys(this.PARTS)) {
      const parts = this.PARTS[side];
      document.getElementById(parts.hide).addEventListener('click', () => this.toggle(side, false));
      document.getElementById(parts.handle).addEventListener('click', () => this.toggle(side, true));
      // As they were last time. This runs before the graph is drawn, so the
      // view saved with it lands on the canvas at the size it is seen at,
      // and there is nothing to move.
      this.toggle(side, stored[side] !== false, true);
    }
  },

  /* Put one panel away, or bring it back: force true or false, or leave it
     out to swap. quiet is for the start, where nothing is moved or saved. */
  toggle(side, force, quiet = false) {
    const parts = this.PARTS[side];
    if (!parts) return;
    const was = this.open[side];
    const open = force === undefined ? !was : Boolean(force);
    const canvas = document.getElementById('canvas');
    const before = canvas.getBoundingClientRect().left;
    this.open[side] = open;
    document.getElementById('layout').classList.toggle(`${side}-hidden`, !open);
    const handle = document.getElementById(parts.handle);
    handle.classList.toggle('hidden', open);
    if (!open) handle.textContent = this._showing(side);
    if (quiet) return;
    // The canvas now starts further left, or further right, than it did.
    // Moving the view the same distance the other way keeps the graph where
    // it was on screen.
    const moved = canvas.getBoundingClientRect().left - before;
    if (moved && typeof Editor !== 'undefined') {
      Editor.view.x -= moved;
      Editor.applyView();
    }
    // A structure or a plot that was drawn while the panel was away, or a
    // window resized meanwhile, was measured at no size at all.
    if (open && !was && side === 'right') {
      if (typeof Viewer !== 'undefined') Viewer.draw();
      if (typeof Plot !== 'undefined') Plot.draw();
    }
    this._save();
  },

  /* Bring a panel back if it is away, and otherwise leave it be. */
  reveal(side) {
    if (!this.open[side]) this.toggle(side, true);
  },

  /* The name of the tab showing in a panel, for its handle: the first piece
     of text only, because the Problems tab carries a count after its name. */
  _showing(side) {
    const parts = this.PARTS[side];
    const tab = document.querySelector(`#${parts.tabs} .tab.active`);
    const text = tab && tab.firstChild ? String(tab.firstChild.textContent || '').trim() : '';
    return text || parts.name;
  },

  _load() {
    try { return JSON.parse(localStorage.getItem('comfygmx.sides') || '{}') || {}; }
    catch (err) { return {}; }
  },

  _save() {
    try { localStorage.setItem('comfygmx.sides', JSON.stringify(this.open)); }
    catch (err) { /* private mode */ }
  },
};
