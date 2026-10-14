"""
Grafana v2 dashboards (``dashboard.grafana.app/v2``).

A v2 dashboard keeps panel content in ``spec.elements``, a map keyed by an
element name, and placement in ``spec.layout``, a tree of ``RowsLayout``,
``TabsLayout``, ``GridLayout`` and ``AutoGridLayout`` nodes.  The file is
usually a k8s-style envelope (``apiVersion``, ``kind``, ``metadata``,
``spec``), but a bare spec is accepted too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

_V2_API_PREFIX: Final[str] = "dashboard.grafana.app/v2"
UNPLACED_TITLE: Final[str] = "(not placed in the layout)"


def spec_of(dashboard: dict[str, object]) -> dict[str, object]:
    """Return the spec of a v2 dashboard, whether enveloped or bare."""
    spec = dashboard.get("spec")
    return spec if isinstance(spec, dict) else dashboard


def node_spec(node: object) -> dict[str, object]:
    """Return the ``spec`` of a v2 node, or an empty dict if it has none."""
    spec = node.get("spec") if isinstance(node, dict) else None
    return spec if isinstance(spec, dict) else {}


def is_v2(dashboard: dict[str, object]) -> bool:
    """Return True if *dashboard* is a v2 envelope or a bare v2 spec."""
    api_version = dashboard.get("apiVersion")
    if isinstance(api_version, str):
        return api_version.startswith(_V2_API_PREFIX)
    return "elements" in dashboard and "layout" in dashboard


@dataclass(frozen=True, slots=True)
class V2Panel:
    """One v2 element together with where the layout tree places it."""

    key: str
    element: dict[str, object]
    section: tuple[str, ...] = ()
    placement: dict[str, object] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(node_spec(self.element).get("title", "(untitled)"))

    @property
    def panel_type(self) -> str:
        viz = node_spec(self.element).get("vizConfig")
        if not isinstance(viz, dict):
            return "unknown"
        return str(viz.get("group") or viz.get("kind") or "unknown")

    @property
    def queries(self) -> list[dict[str, object]]:
        data = node_spec(node_spec(self.element).get("data"))
        queries = data.get("queries")
        return [q for q in queries or [] if isinstance(q, dict)]


@dataclass(frozen=True, slots=True)
class V2Section:
    """A leaf layout (grid or auto grid) with the row or tab titles above it."""

    path: tuple[str, ...]
    kind: str
    settings: dict[str, object]
    items: tuple[tuple[str, dict[str, object]], ...]
    node: dict[str, object] = field(compare=False, default_factory=dict)


def _walk_layout(node: object, path: tuple[str, ...], found: list[V2Section]) -> None:
    """Append a ``V2Section`` for every leaf layout below *node*."""
    if not isinstance(node, dict) or not node:
        return
    spec = node_spec(node)
    containers = [c for key in ("rows", "tabs") for c in spec.get(key) or []]
    if "rows" in spec or "tabs" in spec:
        for child in containers:
            title = str(node_spec(child).get("title", ""))
            _walk_layout(node_spec(child).get("layout"), (*path, title), found)
        return
    items = []
    for item in spec.get("items") or []:
        item_spec = node_spec(item)
        reference = item_spec.get("element")
        name = reference.get("name") if isinstance(reference, dict) else None
        if isinstance(name, str):
            items.append((name, {k: v for k, v in item_spec.items() if k != "element"}))
    settings = {k: v for k, v in spec.items() if k != "items"}
    found.append(
        V2Section(path, str(node.get("kind", "")), settings, tuple(items), node)
    )


def v2_sections(dashboard: dict[str, object]) -> list[V2Section]:
    """Return the leaf layouts of a v2 dashboard in document order."""
    found: list[V2Section] = []
    spec = spec_of(dashboard)
    _walk_layout(spec.get("layout"), (), found)
    elements = spec.get("elements")
    placed = {name for section in found for name, _ in section.items}
    unplaced = [k for k in elements or [] if k not in placed]
    if unplaced:
        items = tuple((str(key), {}) for key in unplaced)
        found.append(V2Section((UNPLACED_TITLE,), "", {}, items))
    return found


def v2_panels(dashboard: dict[str, object]) -> list[V2Panel]:
    """Return one ``V2Panel`` per element, in element order."""
    elements = spec_of(dashboard).get("elements")
    placed: dict[str, tuple[tuple[str, ...], dict[str, object]]] = {}
    for section in v2_sections(dashboard):
        for name, placement in section.items:
            placed.setdefault(name, (section.path, placement))
    if not isinstance(elements, dict):
        return []
    return [
        V2Panel(str(key), element, *placed.get(str(key), ((), {})))
        for key, element in elements.items()
        if isinstance(element, dict)
    ]
