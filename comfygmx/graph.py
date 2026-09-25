"""Graph model: validation, topological ordering and signature hashing.

A workflow is a plain dict so it can be saved as JSON and diffed in git::

    {"nodes": [{"id": "n1", "type": "gmx.mdrun", "params": {...}, "pos": [x, y]}],
     "links": [{"from_node": "n1", "from_port": "traj",
                "to_node": "n2", "to_port": "traj"}]}

A node carrying ``"off": true`` has been switched off in the editor. It, and
everything that depends on it, is left out here -- see ``Graph.left_out``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .registry import REGISTRY


class GraphError(Exception):
    pass


class Graph:
    def __init__(self, data: Dict[str, Any]):
        self.raw = data or {}
        # A block that has been folded into a bigger one is converted here,
        # so a graph saved before the merge runs as the merged block with the
        # right choice made -- the same thing the editor does when it opens
        # one.
        from .nodes.merged import convert_graph
        self.converted = convert_graph(self.raw, REGISTRY)
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.order_hint: List[str] = []
        for node in self.raw.get("nodes") or []:
            node_id = str(node.get("id") or "")
            if not node_id:
                raise GraphError("a node is missing its id")
            if node_id in self.nodes:
                raise GraphError(f"duplicate node id '{node_id}'")
            self.nodes[node_id] = node
            self.order_hint.append(node_id)

        self.links: List[Dict[str, Any]] = []
        for link in self.raw.get("links") or []:
            self.links.append(
                {
                    "from_node": str(link.get("from_node")),
                    "from_port": str(link.get("from_port")),
                    "to_node": str(link.get("to_node")),
                    "to_port": str(link.get("to_port")),
                }
            )

        # Every node as it was handed in, switched off or not, so a message
        # about one that was left out can still name it.
        self.all_nodes: Dict[str, Dict[str, Any]] = dict(self.nodes)
        self.left_out: Dict[str, str] = self._leave_out_switched_off()

    def _leave_out_switched_off(self) -> Dict[str, str]:
        """Take out the nodes switched off in the editor, and everything that
        depends on them.

        Done here, before anything else looks at the graph, so that checking,
        ordering, reuse of earlier results, running, and exporting scripts all
        see the same smaller graph and none of them has to know about it. A
        switched-off node is not checked either: a half-wired test node is the
        usual reason for switching one off, and its missing inputs are exactly
        what should stop getting in the way.

        Everything downstream goes too, through any wire, needed or optional.
        A node cannot run without a file it needs, and quietly running one
        without an optional file it was wired to would change what it does
        without anybody having asked for that.

        Returns node id -> the switched-off node it was left out because of,
        or "" for a node that was switched off itself.
        """
        left_out: Dict[str, str] = {
            node_id: "" for node_id, node in self.nodes.items() if node.get("off")}
        stack = list(left_out)
        while stack:
            current = stack.pop()
            root = left_out[current] or current
            for link in self.links:
                target = link["to_node"]
                if (link["from_node"] == current and target in self.nodes
                        and target not in left_out):
                    left_out[target] = root
                    stack.append(target)
        if left_out:
            for node_id in left_out:
                del self.nodes[node_id]
            self.order_hint = [n for n in self.order_hint if n not in left_out]
            self.links = [link for link in self.links
                          if link["from_node"] not in left_out
                          and link["to_node"] not in left_out]
        return left_out

    def _name(self, node_id: str) -> str:
        node = self.all_nodes.get(node_id) or {}
        return str(node.get("title") or node.get("type") or node_id)

    def left_out_reason(self, node_id: str) -> str:
        """Why a node will not run, in words, or "" if it will."""
        if node_id not in self.left_out:
            return ""
        root = self.left_out[node_id]
        if not root:
            return (f"'{self._name(node_id)}' is switched off -- switch it back "
                    "on to run it")
        return (f"'{self._name(node_id)}' is left out: it depends on "
                f"'{self._name(root)}', which is switched off")

    def left_out_summary(self) -> Dict[str, Any]:
        """What was left out, for the editor to show on the nodes."""
        return {node_id: {"because": root, "message": self.left_out_reason(node_id)}
                for node_id, root in self.left_out.items()}

    # -- structure ------------------------------------------------------
    def incoming(self, node_id: str) -> Dict[str, Tuple[str, str]]:
        """port name -> (upstream node id, upstream port)."""
        wired: Dict[str, Tuple[str, str]] = {}
        for link in self.links:
            if link["to_node"] == node_id:
                wired[link["to_port"]] = (link["from_node"], link["from_port"])
        return wired

    def downstream(self, node_id: str) -> Set[str]:
        """Every node reachable from ``node_id``, itself excluded."""
        seen: Set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for link in self.links:
                if link["from_node"] == current and link["to_node"] not in seen:
                    seen.add(link["to_node"])
                    stack.append(link["to_node"])
        return seen

    def upstream_closure(self, node_ids: Set[str]) -> Set[str]:
        """``node_ids`` plus everything they depend on."""
        seen = set(node_ids)
        stack = list(node_ids)
        while stack:
            current = stack.pop()
            for port, (source, _) in self.incoming(current).items():
                if source not in seen:
                    seen.add(source)
                    stack.append(source)
        return seen

    def topo_order(self, subset: Optional[Set[str]] = None) -> List[str]:
        wanted = set(self.nodes) if subset is None else set(subset)
        indegree = {n: 0 for n in wanted}
        edges: Dict[str, List[str]] = {n: [] for n in wanted}
        for link in self.links:
            src, dst = link["from_node"], link["to_node"]
            if src in wanted and dst in wanted:
                edges[src].append(dst)
                indegree[dst] += 1
        # Keep the editor's node order among equally ready nodes so runs are
        # reproducible rather than dict-order dependent.
        ready = [n for n in self.order_hint if n in wanted and indegree[n] == 0]
        out: List[str] = []
        while ready:
            current = ready.pop(0)
            out.append(current)
            for target in edges[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
            ready.sort(key=lambda n: self.order_hint.index(n))
        if len(out) != len(wanted):
            stuck = sorted(wanted - set(out))
            raise GraphError(f"the graph has a cycle involving: {', '.join(stuck)}")
        return out

    # -- validation -----------------------------------------------------

    #: Which file endings belong to which port type. A generic file output --
    #: a shell block, say -- can legally be wired anywhere, so the type system
    #: cannot catch a topology handed to an index port. But the node DECLARES
    #: the name of the file it writes, and "system.top into the index input"
    #: is visible right there. A warning here is an hour saved later: GROMACS
    #: only complains when it finally runs.
    EXT_FOR_TYPE = {
        "index": {".ndx"},
        "topology": {".top", ".itp"},
        "mdp": {".mdp"},
        "structure": {".gro", ".pdb", ".g96", ".brk", ".ent", ".cif"},
        "tpr": {".tpr"},
        "traj": {".xtc", ".trr"},
        "xvg": {".xvg"},
    }
    KNOWN_EXTS = set().union(*EXT_FOR_TYPE.values())

    def _declared_output(self, node: Dict[str, Any]) -> str:
        """The file name a node says it will write, or ''.

        Only names typed in by hand count -- that is where the mistake and
        the evidence live together. Class defaults are deliberately not
        consulted: they are always self-consistent.
        """
        params = node.get("params") or {}
        for key in ("output", "filename"):
            value = params.get(key)
            if isinstance(value, str) and "." in value and "\n" not in value:
                return value.strip()
        return ""

    def validate(self) -> List[Dict[str, str]]:
        problems: List[Dict[str, str]] = []
        for node_id, node in self.nodes.items():
            node_type = node.get("type", "")
            if not REGISTRY.has(node_type):
                problems.append({"node": node_id, "level": "error",
                                 "message": f"unknown node type '{node_type}'"})
                continue
            cls = REGISTRY.get(node_type)
            wired = self.incoming(node_id)
            port_names = {p.name for p in cls.inputs}
            for port in cls.inputs:
                if not port.optional and port.name not in wired:
                    problems.append({
                        "node": node_id, "level": "error",
                        "message": f"required input '{port.label or port.name}' is not connected",
                    })
            for port_name in wired:
                if port_name not in port_names:
                    problems.append({"node": node_id, "level": "warning",
                                     "message": f"link into unknown input '{port_name}'"})
            # A parameter the node does not have is silently ignored at run
            # time, which is exactly wrong for a typo'd or renamed name.
            # all_params(), not params: extra_flags and the environment
            # override are appended only there (base.py, all_params).
            allowed = {p.name for p in cls.all_params()}
            for key in (node.get("params") or {}):
                if key not in allowed:
                    problems.append({
                        "node": node_id, "level": "warning",
                        "message": f"parameter '{key}' is not one this node has "
                                   "-- it will be ignored",
                    })

        known = set(self.nodes)
        for link in self.links:
            if link["from_node"] not in known or link["to_node"] not in known:
                problems.append({"node": link["to_node"], "level": "error",
                                 "message": "link references a node that is not in the graph"})
                continue
            # The out-going side of a link was never checked: a link out of a
            # port the source node does not have passed quietly and produced
            # nothing downstream.
            source = self.nodes[link["from_node"]]
            source_type = source.get("type", "")
            if REGISTRY.has(source_type):
                src_cls = REGISTRY.get(source_type)
                out_names = {p.name for p in src_cls.outputs}
                if link["from_port"] not in out_names:
                    problems.append({
                        "node": link["from_node"], "level": "warning",
                        "message": f"link out of unknown output '{link['from_port']}'",
                    })
                    continue
                # Wrong kind of file into a typed port -- see EXT_FOR_TYPE.
                # Only for a source with ONE output of a generic type: there
                # the declared name and the linked port are certainly the
                # same file. A node with several outputs names only its main
                # one, and a typed output already carries the right thing.
                the_port = next(p for p in src_cls.outputs
                                if p.name == link["from_port"])
                if len(src_cls.outputs) != 1 or the_port.type not in ("file", "any"):
                    continue
                target = self.nodes[link["to_node"]]
                target_type = target.get("type", "")
                if REGISTRY.has(target_type):
                    to_port = next((p for p in REGISTRY.get(target_type).inputs
                                    if p.name == link["to_port"]), None)
                    expect = self.EXT_FOR_TYPE.get(to_port.type) if to_port else None
                    declared = self._declared_output(source)
                    ext = ("." + declared.rsplit(".", 1)[-1].lower()) if declared else ""
                    if (expect and ext in self.KNOWN_EXTS
                            and ext not in expect):
                        problems.append({
                            "node": link["to_node"], "level": "warning",
                            "message": (
                                f"'{declared}' from '{link['from_node']}' is wired "
                                f"into the {to_port.label or to_port.name} input, "
                                f"which expects a {'/'.join(sorted(expect))} file "
                                "-- check this link"),
                        })
        try:
            self.topo_order()
        except GraphError as exc:
            problems.append({"node": "", "level": "error", "message": str(exc)})
        return problems

    # -- hashing --------------------------------------------------------
    def signatures(self, order: Optional[List[str]] = None) -> Dict[str, str]:
        """Content hash per node: its own identity plus everything upstream.

        Two graphs that would produce the same files get the same signature, so
        an unchanged expensive node can be reused instead of re-run.
        """
        order = order or self.topo_order()
        sigs: Dict[str, str] = {}
        for node_id in order:
            node = self.nodes[node_id]
            payload = {
                "type": node.get("type"),
                "params": _canonical(_effective_params(node)),
                "inputs": sorted(
                    (port, sigs.get(src, src), src_port)
                    for port, (src, src_port) in self.incoming(node_id).items()
                ),
            }
            # A block's own workings are not in the signature -- only its type,
            # its boxes and what feeds it. That is right nearly always: two
            # graphs asking for the same thing should share the answer. But
            # when a block carries a script inside it and that script is
            # corrected, the question looks unchanged while the answer is not,
            # and the old, wrong result would be handed back for ever. A block
            # that has been corrected says so by carrying a "revision" number,
            # which is added here and makes the signature different. Blocks
            # without one keep exactly the signature they had, so nothing
            # already computed -- an mdrun that took a day -- is thrown away.
            revision = getattr(REGISTRY.get(node.get("type")), "revision", 0) \
                if REGISTRY.has(node.get("type") or "") else 0
            if revision:
                payload["revision"] = revision
            blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            sigs[node_id] = hashlib.sha256(blob.encode()).hexdigest()[:32]
        return sigs


def _effective_params(node: Dict[str, Any]) -> Dict[str, Any]:
    """Class defaults merged with the node's own values.

    The editor sends every parameter, a hand-written JSON usually sends only the
    ones that were changed. Hashing the merged form makes the two hash alike, so
    a workflow authored in the browser reuses the cache of the same workflow run
    from the command line.
    """
    node_type = node.get("type", "")
    params = dict(node.get("params") or {})
    if REGISTRY.has(node_type):
        merged = dict(REGISTRY.get(node_type).defaults())
        merged.update(params)
        return merged
    return params


def _canonical(params: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty values so adding then clearing a field does not bust the cache."""
    out = {}
    for key, value in params.items():
        if value in (None, ""):
            continue
        out[key] = value
    return out
