"""Panel-level change classification for v2 dashboards."""

from __future__ import annotations

from dashdiff.diff_paths import PathChange, diff_paths
from dashdiff.grid import PanelChange
from dashdiff.v2 import V2Panel, node_spec, v2_panels


def _by_key(dashboard: dict[str, object]) -> dict[str, V2Panel]:
    return {panel.key: panel for panel in v2_panels(dashboard)}


def _without_title_and_queries(panel: V2Panel) -> dict[str, object]:
    """Element spec minus the parts classified separately."""
    spec = dict(node_spec(panel.element))
    spec.pop("title", None)
    data = dict(node_spec(spec.get("data")))
    data.pop("queries", None)
    spec["data"] = data
    return spec


def _classify_pair(before: V2Panel, after: V2Panel) -> frozenset[PanelChange]:
    kinds: set[PanelChange] = set()
    if before.title != after.title:
        kinds.add(PanelChange.MODIFIED_TITLE)
    if before.queries != after.queries:
        kinds.add(PanelChange.MODIFIED_QUERY)
    if (before.section, before.placement) != (after.section, after.placement):
        kinds.add(PanelChange.MODIFIED_LAYOUT)
    if _without_title_and_queries(before) != _without_title_and_queries(after):
        kinds.add(PanelChange.MODIFIED_CONFIG)
    return frozenset(kinds or {PanelChange.UNCHANGED})


def classify_v2_changes(
    before: dict[str, object], after: dict[str, object]
) -> dict[str, frozenset[PanelChange]]:
    """
    Map panel title to its change kinds, matching panels by element key.

    A retitled panel appears under both of its titles so each side of the
    grid finds its badge.  If two panels share a title, their kinds merge.
    """
    before_map, after_map = _by_key(before), _by_key(after)
    result: dict[str, frozenset[PanelChange]] = {}

    def record(title: str, kinds: frozenset[PanelChange]) -> None:
        result[title] = result.get(title, frozenset()) | kinds

    for key in before_map.keys() | after_map.keys():
        old, new = before_map.get(key), after_map.get(key)
        if old is None:
            record(new.title, frozenset({PanelChange.ADDED}))
        elif new is None:
            record(old.title, frozenset({PanelChange.REMOVED}))
        else:
            kinds = _classify_pair(old, new)
            record(old.title, kinds)
            record(new.title, kinds)
    return result


def _placement_view(panel: V2Panel | None) -> dict[str, object]:
    if panel is None:
        return {}
    return {"section": list(panel.section), **panel.placement}


def v2_path_changes(
    before: dict[str, object], after: dict[str, object]
) -> dict[str, list[PathChange]]:
    """
    Map panel title to leaf changes, paths rooted at the element spec.

    Layout changes use the ``layout.`` prefix.  A retitled panel is keyed by
    its new title.
    """
    before_map, after_map = _by_key(before), _by_key(after)
    result: dict[str, list[PathChange]] = {}
    for key in sorted(before_map.keys() | after_map.keys()):
        old, new = before_map.get(key), after_map.get(key)
        changes = diff_paths(
            node_spec(old.element) if old else {},
            node_spec(new.element) if new else {},
        )
        changes += diff_paths(_placement_view(old), _placement_view(new), "layout")
        if changes:
            title = (new or old).title  # type: ignore[union-attr]
            result.setdefault(title, []).extend(changes)
    return result
