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

# ---------------------------------------------------------------------------
# Fields stripped in both modes — they change on every save, carry no meaning
# ---------------------------------------------------------------------------

_STRIP_TOP_LEVEL: Final[frozenset[str]] = frozenset({"id", "iteration", "version"})
_STRIP_PANEL_FIELDS: Final[frozenset[str]] = frozenset({"id"})


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
