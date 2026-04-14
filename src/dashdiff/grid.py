"""
grafana_grid — dashboard grid layout engine and Rich box-model renderer.

Two layers
----------
1. **Data model** (pure stdlib):
   ``extract_panels(dashboard)`` → ``list[GridPanel]``
   ``panel_queries(panel)``      → ``list[str]``

2. **Renderer** (requires ``rich``):
   ``render_grid(panels, title, console)``
   ``build_band_renderables(...)`` (for interleaved detail layout)
   Renders the 24-column Grafana grid as a Rich table where each cell
   is a Panel box labelled with the widget title, type badge, and queries.

Grafana grid
------------
The canvas is 24 columns wide.  Each panel has a ``gridPos`` with:
  x  — left edge (0–23)
  y  — top edge  (0–N)
  w  — width in columns (1–24)
  h  — height in rows   (1–N)

We map this onto a Rich Table by:
  - Collecting all unique y-bands (rows of panels).
  - For each band, building a single Rich Table row whose cells span
    proportionally to the panel widths (using ``ratio`` on columns) but with
    a computed ``min_width`` per grid unit to prevent panel crushing.
  - Panels that don't start exactly at x=0 get a blank spacer cell.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from rich.console import Console

GRID_COLUMNS: Final[int] = 24   # Grafana's fixed canvas width
NARROW_WIDTH: Final[int] = 140  # Below this, switch from side-by-side to stacked layout


def truncate_title(title: str, max_chars: int) -> str:
    """
    Truncate *title* to at most *max_chars* characters, appending a UTF-8
    ellipsis (\u2026) if truncation occurs.

    Used to keep panel titles from overflowing narrow column widths.
    Returns the title unchanged when it already fits.
    """
    if not title or len(title) <= max_chars:
        return title
    if max_chars <= 1:
        return "\u2026"[:max_chars]
    return title[: max_chars - 1] + "\u2026"


# ---------------------------------------------------------------------------
# Change classification
# ---------------------------------------------------------------------------

class PanelChange(enum.Enum):
    """Semantic classification of how a panel differs between two dashboard versions."""
    ADDED            = "added"            # present in after, absent in before
    REMOVED          = "removed"          # present in before, absent in after
    MODIFIED_QUERY   = "modified_query"   # targets/expressions changed
    MODIFIED_TITLE   = "modified_title"   # title changed (treated as remove+add)
    MODIFIED_LAYOUT  = "modified_layout"  # gridPos changed only
    MODIFIED_CONFIG  = "modified_config"  # other fields changed
    UNCHANGED        = "unchanged"


# Colour palette for each change kind.
# Uses bright ANSI variants so badges are visible on both light and dark
# terminal backgrounds (standard colours like yellow=#808000 are too dark).
_CHANGE_COLOURS: Final[dict[PanelChange, str]] = {
    # Explicit 24-bit hex colours so terminal palette remapping cannot affect them.
    # Chosen for visibility on both dark and light backgrounds.
    PanelChange.ADDED:           "bold #23d18b",   # vivid green
    PanelChange.REMOVED:         "bold #f14c4c",   # vivid red
    PanelChange.MODIFIED_QUERY:  "bold #e5a50a",   # amber/gold — clearly yellow
    PanelChange.MODIFIED_TITLE:  "bold #e5a50a",   # same as query
    PanelChange.MODIFIED_LAYOUT: "bold #3b8eea",   # medium blue
    PanelChange.MODIFIED_CONFIG: "bold #bc3fbc",   # vivid magenta
}


# Only structural changes get a coloured border.
# Config/query changes are content-only — the box looks the same but the
# badge inside the body is coloured.  This keeps the border signal strong.
_BORDER_CHANGE_KINDS: Final[frozenset[PanelChange]] = frozenset({
    PanelChange.ADDED,
    PanelChange.REMOVED,
    PanelChange.MODIFIED_LAYOUT,
})


def change_border_style(kinds: frozenset[PanelChange] | PanelChange) -> str | None:
    """
    Return a Rich style string for the panel border given a set of
    ``PanelChange`` kinds.

    Only structural changes (added, removed, layout) receive a coloured border.
    Config and query changes show coloured badges inside the box body instead,
    leaving the border at its default panel-type colour.  This keeps the border
    signal strong and unambiguous.

    When multiple structural kinds are present the first one in display order
    (added > removed > layout) wins.

    Returns ``None`` when no structural kind is present (caller uses the
    panel-type colour instead).

    Accepts either a ``frozenset[PanelChange]`` or a bare ``PanelChange`` for
    backwards compatibility.
    """
    if isinstance(kinds, PanelChange):
        kinds = frozenset({kinds})
    for kind in (PanelChange.ADDED, PanelChange.REMOVED, PanelChange.MODIFIED_LAYOUT):
        if kind in kinds:
            return _CHANGE_COLOURS[kind]
    return None


def _targets_key(panel: dict[str, object]) -> object:
    """Hashable representation of a panel's query targets for comparison."""
    targets = panel.get("targets", [])
    if not isinstance(targets, list):
        return ()
    return tuple(
        tuple(sorted((k, str(v)) for k, v in t.items()))
        for t in targets
        if isinstance(t, dict)
    )


def _gridpos_key(panel: dict[str, object]) -> object:
    """Hashable representation of a panel's gridPos for comparison."""
    gp = panel.get("gridPos") or {}
    if not isinstance(gp, dict):
        return ()
    return (gp.get("x"), gp.get("y"), gp.get("w"), gp.get("h"))


def _panel_without(panel: dict[str, object], *keys: str) -> dict[str, object]:
    """Return a shallow copy of *panel* with the given keys removed."""
    return {k: v for k, v in panel.items() if k not in keys}


def classify_changes(
    before: list[dict[str, object]],
    after:  list[dict[str, object]],
) -> dict[str, frozenset[PanelChange]]:
    """
    Compare two lists of raw panel dicts and return a mapping of
    panel title → ``frozenset[PanelChange]`` for every panel that appears
    in either list.

    Panels are matched by title.  A title that disappears is
    ``{REMOVED}``; a new title is ``{ADDED}``.  When the same title
    exists in both, all three sub-kinds are checked independently:

    * ``MODIFIED_QUERY``  — ``targets`` list changed
    * ``MODIFIED_LAYOUT`` — ``gridPos`` changed
    * ``MODIFIED_CONFIG`` — any other field changed

    A panel may carry more than one kind simultaneously (e.g. both
    ``MODIFIED_QUERY`` and ``MODIFIED_LAYOUT``).  Unchanged panels
    return ``{UNCHANGED}``.
    """
    before_map: dict[str, dict[str, object]] = {
        str(p.get("title", "")): p for p in before if isinstance(p, dict)
    }
    after_map: dict[str, dict[str, object]] = {
        str(p.get("title", "")): p for p in after if isinstance(p, dict)
    }

    result: dict[str, frozenset[PanelChange]] = {}

    all_titles = set(before_map) | set(after_map)
    for title in all_titles:
        if title not in before_map:
            result[title] = frozenset({PanelChange.ADDED})
        elif title not in after_map:
            result[title] = frozenset({PanelChange.REMOVED})
        else:
            b, a = before_map[title], after_map[title]
            if b == a:
                result[title] = frozenset({PanelChange.UNCHANGED})
            else:
                kinds: set[PanelChange] = set()
                if _targets_key(b) != _targets_key(a):
                    kinds.add(PanelChange.MODIFIED_QUERY)
                if _gridpos_key(b) != _gridpos_key(a):
                    kinds.add(PanelChange.MODIFIED_LAYOUT)
                # Config: everything except targets and gridPos
                b_rest = _panel_without(b, "targets", "gridPos")
                a_rest = _panel_without(a, "targets", "gridPos")
                if b_rest != a_rest:
                    kinds.add(PanelChange.MODIFIED_CONFIG)
                result[title] = frozenset(kinds) if kinds else frozenset({PanelChange.UNCHANGED})

    return result


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GridPanel:
    """Immutable value object representing one panel on the Grafana canvas."""
    title:      str
    panel_type: str
    x: int
    y: int
    w: int
    h: int
    queries: tuple[str, ...] = field(default_factory=tuple)


# Query field names to try, in priority order
_QUERY_FIELDS: Final[tuple[str, ...]] = ("expr", "rawSql", "query", "target", "rawQuery")


def panel_queries(panel: dict[str, object]) -> list[str]:
    """
    Return a list of short human-readable query strings for a panel.

    Handles Prometheus (``expr``), SQL (``rawSql``), and generic targets.
    Row panels (``type == "row"``) always return an empty list.
    """
    if panel.get("type") == "row":
        return []

    targets = panel.get("targets", [])
    if not isinstance(targets, list) or not targets:
        return []

    result = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        ref = str(t.get("refId", "?"))
        # Find the first recognised query field; fall back to a placeholder
        query_value = next(
            (t[f] for f in _QUERY_FIELDS if f in t),
            None,
        )
        if query_value is not None:
            result.append(f"{ref}: {query_value}")
        else:
            result.append(f"{ref}: —")
    return result


def _panel_to_grid(panel: dict[str, object]) -> GridPanel:
    gp = panel.get("gridPos") or {}
    assert isinstance(gp, dict)
    return GridPanel(
        title      = str(panel.get("title", "(untitled)")),
        panel_type = str(panel.get("type",  "unknown")),
        x = int(gp.get("x", 0)),  # type: ignore[arg-type]
        y = int(gp.get("y", 0)),  # type: ignore[arg-type]
        w = int(gp.get("w", GRID_COLUMNS)),  # type: ignore[arg-type]
        h = int(gp.get("h", 1)),  # type: ignore[arg-type]
        queries = tuple(panel_queries(panel)),
    )


def extract_panels(dashboard: dict[str, object]) -> list[GridPanel]:
    """
    Flatten all panels (including nested row children) into a list of
    ``GridPanel`` objects.
    """
    raw_panels = dashboard.get("panels", [])
    if not isinstance(raw_panels, list) or not raw_panels:
        return []

    result: list[GridPanel] = []
    for p in raw_panels:
        if not isinstance(p, dict):
            continue
        result.append(_panel_to_grid(p))
        # Row panels embed their children under "panels"
        for child in p.get("panels", []) or []:
            if isinstance(child, dict):
                result.append(_panel_to_grid(child))
    return result


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

# Panel type → colour.
# Named ANSI colours — readable on both light and dark terminal backgrounds.
_TYPE_COLOURS: Final[dict[str, str]] = {
    "timeseries": "cyan",
    "stat":       "yellow",
    "gauge":      "bright_yellow",
    "barchart":   "magenta",
    "bargauge":   "bright_magenta",
    "table":      "bright_cyan",
    "text":       "dim",
    "row":        "dim",
    "piechart":   "bright_red",
    "histogram":  "green",
    "logs":       "bright_green",
    "alertlist":  "red",
    "dashlist":   "blue",
    "news":       "bright_blue",
}
_TYPE_COLOUR_DEFAULT: Final[str] = "default"


def _type_colour(panel_type: str) -> str:
    return _TYPE_COLOURS.get(panel_type, _TYPE_COLOUR_DEFAULT)


# Change-kind badge text shown as the first line of the panel box body.
# Colours are derived from _CHANGE_COLOURS so they can never drift.
# Keys map directly to the badge text; the style is applied in _panel_cell.
_CHANGE_BADGE_TEXT: Final[dict[PanelChange, str]] = {
    PanelChange.ADDED:           "+added",
    PanelChange.REMOVED:         "-removed",
    PanelChange.MODIFIED_QUERY:  "~query",
    PanelChange.MODIFIED_TITLE:  "~query",
    PanelChange.MODIFIED_LAYOUT: "~layout",
    PanelChange.MODIFIED_CONFIG: "~config",
}

# Keep _CHANGE_LABELS as a public alias used by tests and external callers.
# It now maps kind → Rich markup string coloured with the change colour.
_CHANGE_LABELS: Final[dict[PanelChange, str]] = {
    kind: f"[{_CHANGE_COLOURS[kind]}]{text}[/]"
    for kind, text in _CHANGE_BADGE_TEXT.items()
}

# Human-readable labels for the legend line, in display order.
# Colours are derived from _CHANGE_COLOURS so they can never drift.
_LEGEND_ENTRIES: Final[list[tuple[PanelChange, str, str]]] = [
    # (kind,                       colour derived from _CHANGE_COLOURS,   label)
    (PanelChange.ADDED,            _CHANGE_COLOURS[PanelChange.ADDED],            "added"),
    (PanelChange.REMOVED,          _CHANGE_COLOURS[PanelChange.REMOVED],          "removed"),
    (PanelChange.MODIFIED_QUERY,   _CHANGE_COLOURS[PanelChange.MODIFIED_QUERY],   "query"),
    (PanelChange.MODIFIED_LAYOUT,  _CHANGE_COLOURS[PanelChange.MODIFIED_LAYOUT],  "layout"),
    (PanelChange.MODIFIED_CONFIG,  _CHANGE_COLOURS[PanelChange.MODIFIED_CONFIG],  "config"),
    (PanelChange.UNCHANGED,        "dim",                                         "unchanged"),
]


def build_legend_renderable() -> object:
    """
    Build and return a Rich ``Text`` renderable that shows a one-line color
    legend explaining the meaning of each ``PanelChange`` color.

    Example output (with colors)::

        Legend:  ● added  ● removed  ● query  ● layout  ● config  ● unchanged
    """
    from rich.text import Text

    legend = Text()
    legend.append("Legend: ", style="dim")
    for i, (_kind, colour, label) in enumerate(_LEGEND_ENTRIES):
        if i > 0:
            legend.append("  ", style="")
        legend.append("● ", style=colour)
        legend.append(label, style=colour)
    return legend


def render_legend(console: object) -> None:
    """
    Print the color legend line to *console*.

    Parameters
    ----------
    console:
        A ``rich.console.Console`` instance.
    """
    console.print(build_legend_renderable())  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Height equalisation helpers
# ---------------------------------------------------------------------------

def title_line_count(title: str, col_width: int) -> int:
    """
    Return the number of lines the *title* string occupies when rendered
    inside a column of *col_width* characters.

    Rich renders panel titles with one character of padding on each side
    (the border characters), so the usable title area is ``col_width - 2``.
    A zero or negative *col_width* is treated as 1 to avoid division by zero.
    """
    usable = max(col_width - 2, 1)
    if not title:
        return 1
    import math
    return math.ceil(len(title) / usable)


def _panel_render_height(
    panel_type: str,
    title: str,
    col_width: int,
    grid_h: int = 0,
) -> int:
    """
    Estimate the total rendered height of a panel box in terminal rows.

    The formula is::

        max(
            grid_h,                          # proportional height (1 unit = 1 row)
            2 + title_lines + content_lines  # content minimum (never clip)
        )

    Parameters
    ----------
    panel_type:
        Grafana panel type string, e.g. ``"stat"``, ``"timeseries"``.
    title:
        Panel title text.
    col_width:
        Estimated terminal column width available for this panel.
    grid_h:
        Grafana ``gridPos.h`` value.  When > 0, the rendered height is at
        least this many terminal rows, preserving proportional layout.
        A value of 0 (default) disables proportional scaling.
    """
    import math
    usable_title = max(col_width - 2, 1)
    usable_body  = max(col_width - 4, 1)
    badge = f"[{panel_type}]"
    title_lines   = math.ceil(len(title) / usable_title) if title else 1
    content_lines = math.ceil(len(badge) / usable_body)
    content_min   = 2 + title_lines + content_lines
    return max(content_min, grid_h)


def band_max_height(panels: list[GridPanel], console_width: int) -> int:
    """
    Return the maximum *total rendered height* (in terminal rows) across all
    *panels* in a single band, given the *console_width* available for the
    full 24-column grid.

    Each panel's column width is estimated as
    ``floor(console_width * panel.w / GRID_COLUMNS)``.
    """
    if not panels:
        return 1
    max_h = 1
    for p in panels:
        col_w = max(int(console_width * p.w / GRID_COLUMNS), 1)
        h = _panel_render_height(p.panel_type, p.title, col_width=col_w, grid_h=p.h)
        if h > max_h:
            max_h = h
    return max_h


# Display order for badges inside the panel box body.
_BADGE_DISPLAY_ORDER: Final[tuple[PanelChange, ...]] = (
    PanelChange.ADDED,
    PanelChange.REMOVED,
    PanelChange.MODIFIED_QUERY,
    PanelChange.MODIFIED_LAYOUT,
    PanelChange.MODIFIED_CONFIG,
)


def _panel_cell(
    gp: GridPanel,
    change: frozenset[PanelChange] | PanelChange = PanelChange.UNCHANGED,
    fixed_height: int | None = None,
) -> object:
    """Build a Rich Panel (box) for a single GridPanel.

    Parameters
    ----------
    change:
        A ``frozenset[PanelChange]`` (or a bare ``PanelChange`` for
        backwards compatibility) describing how this panel changed.
        All non-UNCHANGED kinds are rendered as coloured badges inside
        the box body.  Structural kinds (added/removed/layout) also
        colour the border.
    fixed_height:
        If given, the panel is rendered at exactly this many terminal rows
        (passed directly to ``rich.panel.Panel(height=…)``).  Used by
        ``build_grid_renderables`` to equalise all panels in a band.
    """
    from rich.panel import Panel
    from rich.text import Text
    from rich import box as rich_box

    if isinstance(change, PanelChange):
        change = frozenset({change})

    colour = _type_colour(gp.panel_type)
    # change_border_style() already includes "bold" prefix; use as-is.
    # Falls back to the panel-type colour for content-only or unchanged panels.
    border_style = change_border_style(change) or colour

    # Title: clean panel name only (no badge suffix)
    title_markup = f"[bold]{gp.title}[/]"

    # Body: one badge line per non-UNCHANGED kind (in display order) + type badge
    content = Text(overflow="fold")
    for kind in _BADGE_DISPLAY_ORDER:
        if kind in change:
            badge_text = _CHANGE_BADGE_TEXT.get(kind)
            if badge_text is not None:
                content.append(badge_text, style=_CHANGE_COLOURS[kind])
                content.append("\n")
    content.append(f"[{gp.panel_type}]", style=f"bold {colour}")

    box_style = rich_box.ROUNDED if gp.panel_type != "row" else rich_box.SIMPLE_HEAD

    return Panel(
        content,
        title=title_markup,
        title_align="left",
        border_style=border_style,
        box=box_style,
        padding=(0, 1),
        height=fixed_height,
    )


def _spacer_cell(w: int) -> object:
    """An empty spacer cell for gaps in the grid."""
    from rich.panel import Panel
    from rich import box as rich_box
    return Panel("", border_style="dim", box=rich_box.MINIMAL, padding=(0, 0))


def build_grid_renderables(
    panels: list[GridPanel],
    title: str = "",
    changes: dict[str, frozenset[PanelChange]] | None = None,
    console_width: int = 160,
) -> list[object]:
    """
    Build and return a list of Rich renderables representing the dashboard grid.

    Unlike ``render_grid``, this function does not print anything — it returns
    the renderables so callers can embed them inside other Rich layouts (e.g.
    a side-by-side outer table).

    Parameters
    ----------
    changes:
        Mapping of panel title → ``frozenset[PanelChange]`` from
        ``classify_changes()``.  Panels absent from the map are treated as
        ``{UNCHANGED}``.
    console_width:
        Estimated terminal width used for title-wrapping height calculations.
        Defaults to 160 (a safe minimum for modern terminals).
    """
    from rich.rule import Rule
    from rich.text import Text
    from rich.table import Table

    effective_changes: dict[str, frozenset[PanelChange]] = changes or {}
    renderables: list[object] = []

    if title:
        renderables.append(Rule(f"[bold]{title}[/]", style="dim"))

    renderables.append(build_legend_renderable())

    if not panels:
        renderables.append(Text("(no panels)", style="dim"))
        return renderables

    bands: dict[int, list[GridPanel]] = {}
    for p in panels:
        bands.setdefault(p.y, []).append(p)

    # Estimate console width for height equalisation.
    # build_grid_renderables is called from render_grid (which knows the
    # console width) and from cli.py (which uses the terminal width).  We
    # default to 160 as a safe minimum; callers can override via console_width.
    _cw = console_width

    for y in sorted(bands):
        row_panels = sorted(bands[y], key=lambda p: p.x)

        # Compute the maximum title height across all real panels in this band
        # so we can pad shorter panels to match.
        max_h = band_max_height(row_panels, console_width=_cw)

        band_table = Table(
            box=None,
            show_header=False,
            show_edge=False,
            padding=(0, 0),
            expand=True,
        )
        cursor = 0
        cells: list[tuple[int, GridPanel | None]] = []
        for p in row_panels:
            if p.x > cursor:
                cells.append((p.x - cursor, None))
            cells.append((p.w, p))
            cursor = p.x + p.w
        if cursor < GRID_COLUMNS:
            cells.append((GRID_COLUMNS - cursor, None))
        unit_px = max(1, _cw // GRID_COLUMNS)
        for w, _ in cells:
            band_table.add_column(ratio=w, min_width=w * unit_px)

        row_cells: list[object] = []
        for w, p in cells:
            if p is None:
                row_cells.append(_spacer_cell(w))
            else:
                row_cells.append(
                    _panel_cell(
                        p,
                        change=effective_changes.get(p.title, frozenset({PanelChange.UNCHANGED})),
                        fixed_height=max_h,
                    )
                )
        band_table.add_row(*row_cells)
        renderables.append(band_table)

    return renderables


def build_band_renderables(
    y_band: int,
    before_panels: list[GridPanel],
    after_panels:  list[GridPanel],
    changes:       dict[str, frozenset[PanelChange]],
    path_changes:  dict[str, list[object]],
    console_width: int = 160,
) -> list[object]:
    """
    Build the renderables for a single horizontal band (y-row) in interleaved
    two-file diff mode.

    Returns a list whose elements are, in order:

    1. A Rich ``Table`` with two columns (before / after) containing the
       panel boxes for this band.
    2. Zero or more Rich ``Panel`` renderables — one per changed panel in
       this band — each containing a path-change breakdown table.

    Parameters
    ----------
    y_band:
        The ``gridPos.y`` value that identifies this band.
    before_panels / after_panels:
        Panels from the before/after dashboards that belong to this band
        (i.e. those whose ``y == y_band``).
    changes:
        Full ``classify_changes()`` result (panel title → ``frozenset[PanelChange]``).
    path_changes:
        Mapping of panel title → list of ``PathChange`` objects for panels
        that have at least one changed path.  Panels absent from this map
        are treated as having no path-level changes.
    console_width:
        Terminal width used for height equalisation.
    """
    import json as _json
    from rich.table import Table
    from rich.panel import Panel as RichPanel
    from rich import box as rich_box
    from rich.console import Group
    from dashdiff.diff_paths import MISSING

    # Early exit: skip bands where every panel is UNCHANGED.
    # This keeps the output focused on what actually changed.
    all_band_titles = (
        {p.title for p in before_panels} | {p.title for p in after_panels}
    )
    _unchanged = frozenset({PanelChange.UNCHANGED})
    if not any(
        changes.get(t, _unchanged) != _unchanged
        for t in all_band_titles
    ):
        return []

    renderables: list[object] = []

    # ------------------------------------------------------------------ #
    # 1. Grid row — side-by-side (wide) or stacked (narrow)
    # ------------------------------------------------------------------ #

    def _one_side_table(panels: list[GridPanel], side_width: int) -> object:
        """Build a single-side band table (one row of panel boxes)."""
        if not panels:
            from rich.text import Text
            return Text("(no panels in this band)", style="dim")
        band_table = Table(
            box=None, show_header=False, show_edge=False,
            padding=(0, 0), expand=True,
        )
        row_panels = sorted(panels, key=lambda p: p.x)
        max_h = band_max_height(row_panels, console_width=side_width)
        cursor = 0
        cells: list[tuple[int, GridPanel | None]] = []
        for p in row_panels:
            if p.x > cursor:
                cells.append((p.x - cursor, None))
            cells.append((p.w, p))
            cursor = p.x + p.w
        if cursor < GRID_COLUMNS:
            cells.append((GRID_COLUMNS - cursor, None))
        unit_px = max(1, side_width // GRID_COLUMNS)
        for w, _ in cells:
            band_table.add_column(ratio=w, min_width=w * unit_px)
        row_cells: list[object] = [
            _panel_cell(p, change=changes.get(p.title, frozenset({PanelChange.UNCHANGED})),
                        fixed_height=max_h)
            if p is not None else _spacer_cell(w)
            for w, p in cells
        ]
        band_table.add_row(*row_cells)
        return band_table

    if console_width >= NARROW_WIDTH:
        # Wide: side-by-side two-column outer table
        outer = Table(
            box=rich_box.HEAVY_HEAD,
            show_lines=False,
            padding=(0, 1),
            expand=True,
        )
        outer.add_column("before", ratio=1)
        outer.add_column("after",  ratio=1)
        outer.add_row(
            _one_side_table(before_panels, console_width // 2),
            _one_side_table(after_panels,  console_width // 2),
        )
        renderables.append(outer)
    else:
        # Narrow: stacked — before section on top, after section below
        from rich.rule import Rule
        from rich.console import Group
        renderables.append(Group(
            Rule("before", style="dim", align="left"),
            _one_side_table(before_panels, console_width),
            Rule("after",  style="dim", align="left"),
            _one_side_table(after_panels,  console_width),
        ))

    # ------------------------------------------------------------------ #
    # 2. Detail panels for changed panels in this band
    # ------------------------------------------------------------------ #
    # Short badge text for each change kind (used in the detail box header)
    _BADGE: dict[PanelChange, str] = {
        PanelChange.ADDED:           "+added",
        PanelChange.REMOVED:         "-removed",
        PanelChange.MODIFIED_QUERY:  "~query",
        PanelChange.MODIFIED_LAYOUT: "~layout",
        PanelChange.MODIFIED_CONFIG: "~config",
    }

    # Build a title → x map so we can sort detail boxes left-to-right.
    # Prefer after_panels (the "current" state); fall back to before_panels
    # for removed panels that only exist in the before version.
    title_to_x: dict[str, int] = {}
    for p in before_panels:
        title_to_x[p.title] = p.x
    for p in after_panels:          # after takes precedence
        title_to_x[p.title] = p.x

    all_band_panels = {p.title for p in before_panels} | {p.title for p in after_panels}
    # Sort by (x position, title) so left-to-right order matches the grid row
    _unchanged = frozenset({PanelChange.UNCHANGED})
    for title in sorted(all_band_panels, key=lambda t: (title_to_x.get(t, 0), t)):
        kinds = changes.get(title, _unchanged)
        if kinds == _unchanged:
            continue
        panel_paths = path_changes.get(title)
        if not panel_paths:
            continue

        # Border: structural kind wins; falls back to dim for content-only changes.
        border = change_border_style(kinds) or "dim"
        # Badges in header: all non-UNCHANGED kinds in display order
        badges = " ".join(
            f"[{_CHANGE_COLOURS[k]}]{_BADGE.get(k, '')}[/]"
            for k in _BADGE_DISPLAY_ORDER
            if k in kinds and k in _BADGE
        )

        if console_width >= NARROW_WIDTH:
            # Wide: three-column side-by-side path table
            tbl = Table(
                box=rich_box.SIMPLE_HEAD,
                show_header=True,
                header_style="bold",
                show_edge=False,
                padding=(0, 1),
                expand=True,
            )
            tbl.add_column("path",   style="bold cyan",  no_wrap=True)
            tbl.add_column("before", style="bold red")
            tbl.add_column("after",  style="bold green")
            for pc in panel_paths:
                before_str = "(absent)" if pc.before is MISSING else _json.dumps(pc.before)  # type: ignore[union-attr]
                after_str  = "(absent)" if pc.after  is MISSING else _json.dumps(pc.after)   # type: ignore[union-attr]
                tbl.add_row(pc.path, before_str, after_str)  # type: ignore[union-attr]
        else:
            # Narrow: single-column table — path key on its own line, then indented before/after
            from rich.text import Text as RichText
            tbl = Table(
                box=rich_box.SIMPLE_HEAD,
                show_header=False,
                show_edge=False,
                padding=(0, 1),
                expand=True,
            )
            tbl.add_column("entry")
            for pc in panel_paths:
                before_str = "(absent)" if pc.before is MISSING else _json.dumps(pc.before)  # type: ignore[union-attr]
                after_str  = "(absent)" if pc.after  is MISSING else _json.dumps(pc.after)   # type: ignore[union-attr]
                tbl.add_row(RichText(pc.path, style="bold cyan"))  # type: ignore[union-attr]
                tbl.add_row(f"  [bold red]before:[/] {before_str}")
                tbl.add_row(f"  [bold green]after:[/]  {after_str}")

        # Header: panel title + all coloured change-type badges
        header_title = f"[bold]{title}[/]  {badges}"

        renderables.append(
            RichPanel(
                tbl,
                title=header_title,
                title_align="left",
                border_style=border,   # already includes "bold" from _CHANGE_COLOURS
                box=rich_box.ROUNDED,
            )
        )

    return renderables


def render_grid(
    panels: list[GridPanel],
    title: str = "",
    console: Console | None = None,
    changes: dict[str, frozenset[PanelChange]] | None = None,
) -> None:
    """
    Render the dashboard grid as a Rich box-model layout.

    Parameters
    ----------
    panels:
        Output of ``extract_panels()``.
    title:
        Dashboard title shown in the header.
    console:
        A ``rich.console.Console`` instance.  Created if ``None``.
    changes:
        Mapping of panel title → ``frozenset[PanelChange]`` from ``classify_changes()``.
        Panels absent from the map are treated as ``{UNCHANGED}``.
    """
    from rich.console import Console as RichConsole
    from rich.table import Table
    from rich import box as rich_box
    import shutil

    if console is None:
        term_width = shutil.get_terminal_size((220, 50)).columns
        console = RichConsole(color_system="256", width=max(term_width, 160))

    effective_changes: dict[str, frozenset[PanelChange]] = changes or {}

    if title:
        console.rule(f"[bold]{title}[/]", style="color(244)")

    render_legend(console)

    if not panels:
        console.print("[dim](no panels)[/]")
        return

    # Group panels by y-band
    bands: dict[int, list[GridPanel]] = {}
    for p in panels:
        bands.setdefault(p.y, []).append(p)

    for y in sorted(bands):
        row_panels = sorted(bands[y], key=lambda p: p.x)

        band_table = Table(
            box=None,
            show_header=False,
            show_edge=False,
            padding=(0, 0),
            expand=True,
        )

        # Build (width, panel_or_None) cells, inserting spacers for gaps
        cursor = 0
        cells: list[tuple[int, GridPanel | None]] = []
        for p in row_panels:
            if p.x > cursor:
                cells.append((p.x - cursor, None))
            cells.append((p.w, p))
            cursor = p.x + p.w
        if cursor < GRID_COLUMNS:
            cells.append((GRID_COLUMNS - cursor, None))

        unit_px = max(1, side_width // GRID_COLUMNS)
        for w, _ in cells:
            band_table.add_column(ratio=w, min_width=w * unit_px)

        band_table.add_row(*[
            _panel_cell(p, change=effective_changes.get(p.title, frozenset({PanelChange.UNCHANGED})))
            if p is not None else _spacer_cell(w)
            for w, p in cells
        ])
        console.print(band_table)
