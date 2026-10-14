"""
grafana_normalize — stable JSON representation of a Grafana dashboard.

Two modes
---------
Lenient (default, strict=False)
    Sorts every array that is functionally set-like — where element order has
    no effect on what the dashboard renders or how it behaves.  This suppresses
    cosmetic diff noise produced by the Grafana UI (e.g. tag reordering, variable
    option list reshuffling, refresh-interval reordering).

Strict (strict=True)
    Preserves document order for those arrays, so even a cosmetic reordering is
    visible.  Useful for auditing or enforcing a house style.

Both modes
    - Strip ``id``, ``iteration``, ``version`` (pure save-counter noise).
    - Strip ``id`` from every panel (including nested row panels).
    - Recursively sort all JSON object keys alphabetically.
    - Never reorder ``transformations``, ``overrides``, or ``links``
      (pipeline / intentional ordering).

Lenient mode only
    - Sort panels by ``(gridPos.y, gridPos.x, title)``.
    - Sort panel ``targets`` by ``refId``.
    - Sort ``templating.list`` and ``annotations.list`` by ``name``.
"""

from __future__ import annotations

import copy
from typing import Final

from dashdiff.v2 import is_v2, node_spec, spec_of

# ---------------------------------------------------------------------------
# Fields stripped in both modes — they change on every save, carry no meaning
# ---------------------------------------------------------------------------

_STRIP_TOP_LEVEL: Final[frozenset[str]] = frozenset({"id", "iteration", "version"})
_STRIP_PANEL_FIELDS: Final[frozenset[str]] = frozenset({"id"})

# v2 metadata the server assigns on every save or export.  Anything not listed
# here stays in the output, so a new field shows up in the diff instead of
# being hidden.
_STRIP_V2_METADATA: Final[frozenset[str]] = frozenset(
    {"generation", "resourceVersion", "creationTimestamp", "uid", "managedFields"}
)
_STRIP_V2_ANNOTATIONS: Final[frozenset[str]] = frozenset(
    {
        "grafana.app/updatedTimestamp",
        "grafana.app/updatedBy",
        "grafana.app/createdBy",
        "grafana.app/message",
    }
)
_STRIP_V2_LABELS: Final[frozenset[str]] = frozenset({"grafana.app/export-label"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sort_keys(obj: object) -> object:
    """Recursively sort all object keys alphabetically.

    Only the *keys* of dicts are sorted.  List element order is intentionally
    left untouched here — callers are responsible for sorting lists before
    passing the structure to this function.
    """
    if isinstance(obj, dict):
        return {k: _sort_keys(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_sort_keys(item) for item in obj]
    return obj


def _strip_nulls(obj: object) -> object:
    """Recursively remove all dict keys whose value is ``None``.

    In JSON, ``null`` and an absent key are semantically equivalent for
    most Grafana fields.  Stripping null-valued keys in lenient mode means
    that a dashboard which stores ``{"value": null}`` and one that simply
    omits ``"value"`` will produce identical normalized output.

    Only *dict keys* are affected.  ``None`` elements inside lists are
    left untouched because the semantics of "absent element" vs ``null``
    in an array position are different.
    """
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _panel_sort_key(panel: dict[str, object]) -> tuple[int, int, str]:
    gp = panel.get("gridPos") or {}
    assert isinstance(gp, dict)
    return (
        int(gp.get("y", 0)),  # type: ignore[arg-type]
        int(gp.get("x", 0)),  # type: ignore[arg-type]
        str(panel.get("title", "")),
    )


def _normalize_panel(panel: dict[str, object], strict: bool) -> dict[str, object]:
    """Return a clean, stable copy of a single panel object."""
    p: dict[str, object] = {
        k: v for k, v in panel.items() if k not in _STRIP_PANEL_FIELDS
    }

    # Recursively normalize nested panels (rows embed their children here).
    # Lenient mode sorts them by position, same as top-level panels.
    nested = p.get("panels")
    if isinstance(nested, list):
        children = [_normalize_panel(child, strict) for child in nested]  # type: ignore[arg-type]
        p["panels"] = children if strict else sorted(children, key=_panel_sort_key)

    # targets: lenient mode sorts by refId (the stable identity of a query)
    targets = p.get("targets")
    if isinstance(targets, list) and not strict:
        p["targets"] = sorted(
            targets, key=lambda t: t.get("refId", "") if isinstance(t, dict) else ""
        )  # type: ignore[union-attr]

    # transformations, overrides: pipeline — never reordered
    # (no action needed; they pass through as-is)

    return _sort_keys(p)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize_v2_metadata(metadata: dict[str, object]) -> dict[str, object]:
    out = {k: v for k, v in metadata.items() if k not in _STRIP_V2_METADATA}
    for key, noise in (
        ("annotations", _STRIP_V2_ANNOTATIONS),
        ("labels", _STRIP_V2_LABELS),
    ):
        value = out.get(key)
        if isinstance(value, dict):
            kept = {k: v for k, v in value.items() if k not in noise}
            # An empty map and an absent key mean the same to the API server.
            if kept:
                out[key] = kept
            else:
                del out[key]
    return out


def _strip_export_labels(obj: object) -> object:
    """Remove the exporter's label from every ``labels`` map in the tree.

    The label names the instance that wrote the file, so it differs between
    exports of the same dashboard.  A map is dropped only if the strip emptied
    it; a ``labels`` map that was already empty stays as it was.
    """
    if isinstance(obj, list):
        return [_strip_export_labels(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    out: dict[str, object] = {}
    for key, raw in obj.items():
        value = _strip_export_labels(raw)
        if key == "labels" and isinstance(value, dict):
            kept = {k: v for k, v in value.items() if k not in _STRIP_V2_LABELS}
            if value and not kept:
                continue
            value = kept
        out[key] = value
    return out


def _sort_by_spec_field(items: object, field: str) -> object:
    """Sort a list of ``{kind, spec}`` nodes by ``spec[field]``."""
    if not isinstance(items, list):
        return items
    return sorted(items, key=lambda i: str(node_spec(i).get(field, "")))


def _grid_item_key(item: object) -> tuple[int, int, str]:
    """Position key for a GridLayout child: an item, or a GridLayoutRow."""
    spec = node_spec(item)
    element = spec.get("element")
    name = element.get("name") if isinstance(element, dict) else spec.get("title")
    return (
        int(spec.get("y", 0)),  # type: ignore[call-overload]
        int(spec.get("x", 0)),  # type: ignore[call-overload]
        str(name or ""),
    )


def _sort_v2_layout(node: object) -> None:
    """Sort GridLayout children by position, in place.

    Rows, tabs and AutoGridLayout items are left alone because their order is
    the layout.
    """
    if not isinstance(node, dict):
        return
    spec = node_spec(node)
    for key in ("rows", "tabs", "items", "elements"):
        children = spec.get(key)
        if isinstance(children, list):
            for child in children:
                _sort_v2_layout(child)
    _sort_v2_layout(spec.get("layout"))

    kind = node.get("kind")
    if kind == "GridLayout" and isinstance(spec.get("items"), list):
        spec["items"] = sorted(spec["items"], key=_grid_item_key)  # type: ignore[call-overload]
    elif kind == "GridLayoutRow" and isinstance(spec.get("elements"), list):
        spec["elements"] = sorted(spec["elements"], key=_grid_item_key)  # type: ignore[call-overload]


def _sort_v2_spec(spec: dict[str, object]) -> None:
    """Lenient-mode sorting of the set-like lists in a v2 spec, in place."""
    elements = spec.get("elements")
    if isinstance(elements, dict):
        for element in elements.values():
            data = node_spec(node_spec(element).get("data"))
            if isinstance(data.get("queries"), list):
                data["queries"] = _sort_by_spec_field(data["queries"], "refId")

    _sort_v2_layout(spec.get("layout"))

    variables = spec.get("variables")
    if isinstance(variables, list):
        for var in variables:
            var_spec = node_spec(var)
            if isinstance(var_spec.get("options"), list):
                var_spec["options"] = sorted(
                    var_spec["options"],
                    key=lambda o: (
                        str(o.get("value", "")) if isinstance(o, dict) else ""
                    ),
                )
        spec["variables"] = _sort_by_spec_field(variables, "name")

    if "annotations" in spec:
        spec["annotations"] = _sort_by_spec_field(spec["annotations"], "name")
    if isinstance(spec.get("tags"), list):
        spec["tags"] = sorted(spec["tags"])  # type: ignore[type-var]


def _normalize_v2(dashboard: dict[str, object], strict: bool) -> dict[str, object]:
    d: dict[str, object] = _strip_export_labels(copy.deepcopy(dashboard))  # type: ignore[assignment]

    metadata = d.get("metadata")
    if isinstance(metadata, dict):
        d["metadata"] = _normalize_v2_metadata(metadata)

    if not strict:
        _sort_v2_spec(spec_of(d))

    result = _sort_keys(d)
    if not strict:
        result = _strip_nulls(result)
    return result  # type: ignore[return-value]


def normalize(dashboard: dict[str, object], strict: bool = False) -> dict[str, object]:
    """
    Return a normalised copy of *dashboard*.

    Parameters
    ----------
    dashboard:
        A parsed Grafana dashboard JSON object (dict).
    strict:
        When ``False`` (default / lenient mode), arrays that are functionally
        set-like are sorted so that cosmetic reorderings produce no diff.
        When ``True`` (strict mode), those arrays are left in document order.

    Transformations applied in **both** modes:
    - Strip ``id``, ``iteration``, ``version`` from the top level.
    - Strip ``id`` from every panel (including nested panels inside rows).
    - Recursively sort all JSON object keys alphabetically.

    Transformations applied in **lenient** mode only:
    - Sort panels by ``(gridPos.y, gridPos.x, title)``.
    - Sort each panel's ``targets`` list by ``refId``.
    - Sort ``templating.list`` by variable ``name``.
    - Sort ``annotations.list`` by annotation ``name``.
    - Sort ``tags`` alphabetically.
    - Sort ``templating.list[*].options`` by ``value``.
    - Sort ``timepicker.refresh_intervals`` alphabetically.
    - Sort ``timepicker.quick_ranges`` by ``display``.
    - Strip all dict keys whose value is ``null`` (JSON ``null`` and an
      absent key are semantically equivalent in Grafana; stripping nulls
      prevents noise diffs such as ``{"value": null}`` vs ``{}``).
      Strict mode preserves nulls so auditors can inspect the raw stored
      JSON.
    """
    if is_v2(dashboard):
        return _normalize_v2(dashboard, strict)

    d: dict[str, object] = copy.deepcopy(
        {k: v for k, v in dashboard.items() if k not in _STRIP_TOP_LEVEL}
    )

    # --- panels (lenient only: sort by position) ---
    panels = d.get("panels")
    if isinstance(panels, list):
        normalized = [_normalize_panel(p, strict) for p in panels]  # type: ignore[arg-type]
        d["panels"] = normalized if strict else sorted(normalized, key=_panel_sort_key)

    # --- templating.list (lenient only: sort by name, options by value) ---
    if not strict:
        try:
            templating = d["templating"]
            assert isinstance(templating, dict)
            templating["list"] = sorted(
                templating["list"],  # type: ignore[arg-type]
                key=lambda v: v.get("name", "") if isinstance(v, dict) else "",
            )
            for var in templating["list"]:  # type: ignore[union-attr]
                if isinstance(var, dict) and isinstance(var.get("options"), list):
                    var["options"] = sorted(
                        var["options"],
                        key=lambda o: o.get("value", "") if isinstance(o, dict) else "",
                    )
        except (KeyError, TypeError, AssertionError):
            pass

    # --- annotations.list (lenient only: sort by name) ---
    if not strict:
        try:
            annotations = d["annotations"]
            assert isinstance(annotations, dict)
            annotations["list"] = sorted(
                annotations["list"],  # type: ignore[arg-type]
                key=lambda a: a.get("name", "") if isinstance(a, dict) else "",
            )
        except (KeyError, TypeError, AssertionError):
            pass

    # --- tags (lenient only: sort alphabetically) ---
    if not strict and isinstance(d.get("tags"), list):
        d["tags"] = sorted(d["tags"])  # type: ignore[type-var]

    # --- timepicker (lenient only) ---
    if not strict:
        try:
            tp = d["timepicker"]
            assert isinstance(tp, dict)
            tp["refresh_intervals"] = sorted(tp["refresh_intervals"])  # type: ignore[arg-type]
        except (KeyError, TypeError, AssertionError):
            pass
        try:
            tp = d["timepicker"]
            assert isinstance(tp, dict)
            tp["quick_ranges"] = sorted(
                tp["quick_ranges"],  # type: ignore[arg-type]
                key=lambda r: r.get("display", "") if isinstance(r, dict) else "",
            )
        except (KeyError, TypeError, AssertionError):
            pass

    result = _sort_keys(d)  # type: ignore[return-value]
    if not strict:
        result = _strip_nulls(result)  # type: ignore[assignment]
    return result  # type: ignore[return-value]
