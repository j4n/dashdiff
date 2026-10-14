"""
Grafana v2 dashboards (``dashboard.grafana.app/v2``).

A v2 dashboard keeps panel content in ``spec.elements``, a map keyed by an
element name, and placement in ``spec.layout``, a tree of ``RowsLayout``,
``TabsLayout``, ``GridLayout`` and ``AutoGridLayout`` nodes.  The file is
usually a k8s-style envelope (``apiVersion``, ``kind``, ``metadata``,
``spec``), but a bare spec is accepted too.
"""

from __future__ import annotations

from typing import Final

_V2_API_PREFIX: Final[str] = "dashboard.grafana.app/v2"


def spec_of(dashboard: dict[str, object]) -> dict[str, object]:
    """Return the spec of a v2 dashboard, whether enveloped or bare."""
    spec = dashboard.get("spec")
    return spec if isinstance(spec, dict) else dashboard


def is_v2(dashboard: dict[str, object]) -> bool:
    """Return True if *dashboard* is a v2 envelope or a bare v2 spec."""
    api_version = dashboard.get("apiVersion")
    if isinstance(api_version, str):
        return api_version.startswith(_V2_API_PREFIX)
    return "elements" in dashboard and "layout" in dashboard
