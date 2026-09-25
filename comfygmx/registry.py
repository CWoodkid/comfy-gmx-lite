"""The node registry: type string -> node class, plus the catalogue the UI reads."""

from __future__ import annotations

from typing import Dict, List, Type

from .nodes import MODULES
from .nodes.base import Node


class Registry:
    def __init__(self) -> None:
        self._nodes: Dict[str, Type[Node]] = {}
        self._order: List[str] = []
        for module in MODULES:
            for cls in getattr(module, "NODES", []):
                self.register(cls)

    def register(self, cls: Type[Node]) -> None:
        if not cls.type:
            raise ValueError(f"{cls.__name__} has no type string")
        if cls.type in self._nodes:
            raise ValueError(f"duplicate node type '{cls.type}'")
        self._nodes[cls.type] = cls
        self._order.append(cls.type)

    def get(self, node_type: str) -> Type[Node]:
        try:
            return self._nodes[node_type]
        except KeyError:
            raise KeyError(f"unknown node type '{node_type}'") from None

    def has(self, node_type: str) -> bool:
        return node_type in self._nodes

    def items(self):
        """(type, class) for every node, in the order the sidebar shows them."""
        return [(t, self._nodes[t]) for t in self._order]

    def specs(self) -> List[dict]:
        return [self._nodes[t].spec() for t in self._order]

    def categories(self) -> List[dict]:
        buckets: Dict[str, List[dict]] = {}
        order: List[str] = []
        for spec in self.specs():
            category = spec["category"]
            if category not in buckets:
                buckets[category] = []
                order.append(category)
            buckets[category].append(spec)
        return [{"name": name, "nodes": buckets[name]} for name in order]


REGISTRY = Registry()
