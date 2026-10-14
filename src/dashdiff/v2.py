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


def _walk_layout(
    node: object,
    section: tuple[str, ...],
    placed: dict[str, tuple[tuple[str, ...], dict]],
) -> None:
    """Record the section and placement of every element reference below *node*."""
    spec = node_spec(node)
    for container in ("rows", "tabs"):
        for child in spec.get(container) or []:
            title = str(node_spec(child).get("title", ""))
            _walk_layout(node_spec(child).get("layout"), (*section, title), placed)
    for item in spec.get("items") or []:
        item_spec = node_spec(item)
        reference = item_spec.get("element")
        name = reference.get("name") if isinstance(reference, dict) else None
        if isinstance(name, str):
            placement = {k: v for k, v in item_spec.items() if k != "element"}
            placed.setdefault(name, (section, placement))


def v2_panels(dashboard: dict[str, object]) -> list[V2Panel]:
    """Return one ``V2Panel`` per element, in element order."""
    spec = spec_of(dashboard)
    elements = spec.get("elements")
    placed: dict[str, tuple[tuple[str, ...], dict]] = {}
    _walk_layout(spec.get("layout"), (), placed)
    if not isinstance(elements, dict):
        return []
    return [
        V2Panel(str(key), element, *placed.get(str(key), ((), {})))
        for key, element in elements.items()
        if isinstance(element, dict)
    ]
