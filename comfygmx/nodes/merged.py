"""One block with a "what to do" choice, standing in for several look-alikes.

The palette had several blocks that all measured something per frame with a
GROMACS tool, and several that all made an index file.  Somebody new to the
field does not know that RMSD and RMSF are cousins -- to them it is a longer
list to read.  So each
family becomes one block with a choice box at the top, and the boxes that
belong to the other choices stay out of sight until that choice is picked.

Nothing about how the work is done changes.  A merged block does not carry
its own commands: when it plans, it looks up which of the original blocks
the choice stands for, hands that block the same inputs and the values from
its own boxes, and returns whatever that block planned.  The originals stay
registered but hidden, and say where they went, so a graph saved before the
merge opens as the merged block with the right choice already made.

Boxes are merged by name.  A box two originals both have, with the same
label -- "Output name", "-b (ps)" -- becomes one box shown for both.  A box
whose name is shared but whose meaning is not gets the original's short key
in front of its name, so the two never collide.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import ENV_OVERRIDE_PARAM, Node, NodeError, Param, PlanContext, Plan, Port


def _visible_for(choice_name: str, labels: Sequence[str], total: int) -> str:
    """The ``when`` rule that shows a box for these choices -- none if for all."""
    if len(labels) >= total:
        return ""
    return f"{choice_name}=" + "|".join(labels)


def merged_node(
    *,
    node_type: str,
    title: str,
    category: str,
    color: str,
    tool: str,
    description: str,
    choice: str,
    choice_label: str,
    members: Sequence[Tuple[str, str, type]],
    inputs: Sequence[Port],
    outputs: Sequence[Port],
    choice_help: str = "",
    docs: str = "",
    extra_command: str = "",
    leading: Sequence[Param] = (),
) -> type:
    """Build the merged block and mark every member as replaced by it.

    ``members`` is ``(label, key, cls)``: the words in the choice box, a short
    key used when two members' boxes collide, and the original block.  The
    first member is the default choice.
    """
    labels = [label for label, _, _ in members]
    by_label = {label: (key, cls) for label, key, cls in members}

    # -- boxes: merged by name, hidden behind the choice that uses them ------
    merged: Dict[str, Param] = {}
    shown_for: Dict[str, List[str]] = {}
    #: Boxes whose default was blanked because the originals disagree on it.
    #: Only for these does an empty box mean "the usual value"; anywhere else
    #: an empty box is an empty box -- somebody may have emptied the lipid
    #: list on purpose to build a plain box of water.
    usual_when_empty: set = set()
    # (label, original name) -> the name it has on the merged block
    renamed: Dict[Tuple[str, str], str] = {}
    for label, key, cls in members:
        for param in cls.params:
            name = param.name
            if name in merged and merged[name].label != param.label:
                name = f"{key}_{param.name}"
            if name in merged:
                shown_for[name].append(label)
                # The same box, but each original fills it differently: the
                # RMSD tool wants two groups, the density tool one. The box
                # then starts empty, and empty means "the usual for the choice
                # made above" -- the plan fills in that original's default.
                if merged[name].default != param.default and param.type in ("str", "text"):
                    usual = "; ".join(
                        f"{lbl}: {by_label[lbl][1].defaults().get(param.name) or '(nothing)'}"
                        .replace("\n", " / ").rstrip(" /")
                        for lbl in shown_for[name])
                    usual_when_empty.add(name)
                    merged[name] = dataclasses.replace(
                        merged[name], default="",
                        placeholder="leave empty for the usual value",
                        help=(str(merged[name].help or "").rstrip() + "\n\nLeft empty, "
                              "the usual value for the choice made above is used -- "
                              + usual).strip())
            else:
                merged[name] = dataclasses.replace(param, name=name)
                shown_for[name] = [label]
            renamed[(label, param.name)] = name
    params: List[Param] = [
        Param(choice, "choice", choice_label, labels[0], choices=list(labels),
              help=choice_help),
    ] + list(leading)
    # One Extra flags box for whichever program the choice stands for. The
    # merged block cannot name a single command the way an ordinary block
    # does, so it words the box itself and hands the text on unchanged.
    programs = ", ".join(f"{cls.extra_command} for \"{label}\""
                         for label, _, cls in members if cls.extra_command)
    params.append(Param(
        "extra_flags", "str", "Extra flags for the program picked above", "",
        advanced=True, placeholder="added to the command as typed",
        help="Anything typed here goes on the end of the command, exactly as "
             "written. Which command depends on the choice at the top: "
             + programs + "."))
    for name, param in merged.items():
        rule = _visible_for(choice, shown_for[name], len(members))
        own = str(param.when or "")
        # A box that already hides behind another box keeps that rule, and
        # only when its own choice is picked as well -- both conditions are
        # written into one rule by the editor's "and" grammar.
        when = " & ".join(part for part in (rule, own) if part)
        params.append(dataclasses.replace(param, when=when))

    class _Merged(Node):
        pass

    _Merged.type = node_type
    _Merged.title = title
    _Merged.category = category
    _Merged.color = color
    _Merged.tool = tool
    _Merged.extra_command = extra_command
    _Merged.description = description
    _Merged.docs = docs
    _Merged.inputs = tuple(inputs)
    _Merged.outputs = tuple(outputs)
    _Merged.params = tuple(params)
    _Merged.MEMBERS = by_label
    _Merged.CHOICE = choice

    def plan(self, ctx: PlanContext) -> Plan:
        picked = ctx.pstr(choice) or labels[0]
        if picked not in by_label:
            raise NodeError(
                f"'{picked}' is not one of the choices in the '{choice_label}' box. "
                "Pick one of: " + ", ".join(labels))
        key, cls = by_label[picked]
        # The original block's own defaults, overlaid with whatever was typed
        # into the merged block's boxes. An empty box means "the usual",
        # which is the original's default rather than an empty string --
        # that is what lets one "Groups" box serve tools that each want a
        # different default group.
        values: Dict[str, Any] = dict(cls.defaults())
        for param in cls.params:
            name = renamed[(picked, param.name)]
            if name not in ctx.params:
                continue
            value = ctx.params[name]
            if value == "" and name in usual_when_empty:
                continue
            values[param.name] = value
        for passthrough in ("extra_flags", ENV_OVERRIDE_PARAM.name):
            if passthrough in ctx.params:
                values[passthrough] = ctx.params[passthrough]
        sub = PlanContext(
            node_id=ctx.node_id, node_type=cls.type, params=values,
            inputs=ctx.inputs, workdir=ctx.workdir, stage=ctx._stage,
            settings=ctx.settings, dry=ctx.dry,
        )
        return cls().plan(sub)

    _Merged.plan = plan
    _Merged.__name__ = "".join(
        part.capitalize() for part in node_type.split(".")[-1].split("_")) + "Node"

    # -- the originals: kept for old graphs, pointed at the merged block ----
    for label, key, cls in members:
        cls.hidden = True
        cls.replaced_by = {
            "type": node_type,
            "params": {choice: label},
            "rename": {old: new for (lbl, old), new in renamed.items()
                       if lbl == label and old != new},
        }
        cls.description = (
            f"Now part of \"{title}\" -- pick \"{label}\" there. This block is "
            "kept so older graphs still open, and opens as that block.\n\n"
            + str(cls.description or ""))
    return _Merged


def convert_node(node: Dict[str, Any], registry) -> Optional[str]:
    """Rewrite one graph node in place if its block has been replaced.

    Returns the new type, or None when nothing changed.  Used by the runner
    on the way in; the editor does the same thing in the browser.
    """
    node_type = str(node.get("type") or "")
    if not registry.has(node_type):
        return None
    swap = registry.get(node_type).replaced_by
    if not swap:
        return None
    params = dict(node.get("params") or {})
    for old, new in (swap.get("rename") or {}).items():
        if old in params:
            params[new] = params.pop(old)
    params.update(swap.get("params") or {})
    node["type"] = swap["type"]
    node["params"] = params
    # The old block's title is its old name; the merged block has its own.
    if node.get("title") == registry.get(node_type).title:
        node.pop("title", None)
    return swap["type"]


def convert_graph(data: Dict[str, Any], registry) -> List[Tuple[str, str, str]]:
    """Convert every replaced node in a graph; returns (id, old, new) rows."""
    changed = []
    for node in data.get("nodes") or []:
        old = str(node.get("type") or "")
        new = convert_node(node, registry)
        if new:
            changed.append((str(node.get("id")), old, new))
    return changed
