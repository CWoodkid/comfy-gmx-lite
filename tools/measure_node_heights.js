/* Print the rendered height of every node type, for NODE_H in tutorial_graph.py.
   Paste into the browser console with Comfy-gmx open on an empty graph, then
   copy the printed table into the NODE_H dict.

   Layout has to know these: a graph written as a table of (column, row) has no
   idea how tall its nodes are, and placing rows a fixed distance apart puts a
   586 px mdp node straight through the row below.

   Wait for the check to come back before measuring. A node with nothing wired
   into it carries a red line saying so, and that line is 28 px -- so a table
   measured half a second after the nodes appear is one error line short on
   every row, which is exactly how far the shipped layouts were out. The script
   waits and then asserts that the complaints have arrived. */
(async () => {
  const before = Editor.toJSON();
  Editor.clear();
  await new Promise((done) => setTimeout(done, 300));
  let row = 0;
  for (const type of Object.keys(Editor.defs)) Editor.addNode(type, 0, (row += 1) * 1500);
  await new Promise((done) => setTimeout(done, 2500));
  const heights = {};
  let complaining = 0;
  for (const node of Editor.nodes.values()) {
    heights[node.type] = node._el.offsetHeight;
    const line = node._el.querySelector('.node-error');
    if (line && !line.classList.contains('hidden')) complaining += 1;
  }
  if (complaining < Editor.nodes.size / 2) {
    console.warn(`only ${complaining} of ${Editor.nodes.size} nodes have their `
      + 'error line yet -- the check has not come back. Wait and run it again, '
      + 'or every height below is 28 px short.');
  }
  Editor.clear();
  Editor.fromJSON(before);
  console.log(Object.keys(heights).sort()
    .map((type) => `    "${type}": ${heights[type]},`).join('\n'));
})();
