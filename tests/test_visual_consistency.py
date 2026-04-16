"""
Visual consistency tests for dashdiff.grid.

Tests cover:
- Legend swatches derive styles from _CHANGE_COLOURS (never hardcoded or dim)
- Legend contains all six change-kind labels
- Legend appears before the first band in build_grid_renderables output
- Detail box headers include a coloured change-type badge
- Detail boxes within a band are ordered left-to-right by panel x position
"""

from __future__ import annotations

import io
import re

import pytest
from rich.console import Console
from rich.text import Text

from dashdiff.grid import (
    PanelChange,
    GridPanel,
    change_border_style,
    build_legend_renderable,
    build_band_renderables,
    build_grid_renderables,
    _CHANGE_COLOURS,   # internal — used to assert legend derives from it
    _LEGEND_ENTRIES,   # internal — used to inspect swatch styles
)
from dashdiff.diff_paths import PathChange, MISSING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render(renderable, width: int = 160) -> str:
    """Render a Rich renderable to a plain string (no ANSI, no colour)."""
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=width)
    console.print(renderable)
    return buf.getvalue()


def _render_markup(renderable, width: int = 160) -> str:
    """
    Render a Rich renderable and capture the *markup* (Rich style spans)
    rather than stripping them.  We do this by rendering to a string with
    highlight=False and then inspecting the Text object directly.
    """
    # For Text objects we can inspect spans directly
    if isinstance(renderable, Text):
        return str(renderable._spans)  # type: ignore[attr-defined]
    # For other renderables, render to plain and return
    return _render(renderable, width)


# ---------------------------------------------------------------------------
# Fix 1 — Legend swatch colours must match _CHANGE_COLOURS
# ---------------------------------------------------------------------------

class TestLegendColourConsistency:
    def test_legend_entries_derive_from_change_colours(self):
        """
        Every non-UNCHANGED entry in _LEGEND_ENTRIES must use the same
        style string as _CHANGE_COLOURS[kind].
        """
        for kind, colour, _label in _LEGEND_ENTRIES:
            if kind == PanelChange.UNCHANGED:
                continue  # unchanged has no border colour; dim is acceptable
            expected = _CHANGE_COLOURS[kind]
            assert colour == expected, (
                f"Legend entry for {kind.value!r} uses style {colour!r} "
                f"but _CHANGE_COLOURS says {expected!r}"
            )

    @pytest.mark.parametrize("label", ["added", "removed", "query", "layout", "config", "unchanged"])
    def test_legend_contains_all_labels(self, label):
        """The rendered legend must contain all six change-kind labels."""
        buf = io.StringIO()
        Console(file=buf, no_color=True, width=160).print(build_legend_renderable())
        assert label in buf.getvalue().lower()

    def test_legend_before_first_band(self):
        """The legend renderable must appear before the first band Table."""
        from rich.table import Table
        panels = [
            GridPanel("CPU", "timeseries", x=0, y=0, w=12, h=8),
            GridPanel("RAM", "stat",       x=12, y=0, w=12, h=8),
        ]
        changes = {"CPU": frozenset({PanelChange.ADDED}), "RAM": frozenset({PanelChange.UNCHANGED})}
        renderables = build_grid_renderables(panels, title="T", changes=changes, console_width=160)
        legend_idx = None
        first_table_idx = None
        for i, r in enumerate(renderables):
            if isinstance(r, Table) and first_table_idx is None:
                first_table_idx = i
            if legend_idx is None:
                buf = io.StringIO()
                Console(file=buf, no_color=True, width=160).print(r)
                if "added" in buf.getvalue().lower():
                    legend_idx = i
        assert legend_idx is not None
        assert first_table_idx is not None
        assert legend_idx < first_table_idx


# ---------------------------------------------------------------------------
# Detail box header must include a coloured change-type badge
# ---------------------------------------------------------------------------

# Short human-readable badge text for each change kind
_BADGE_TEXT: dict[PanelChange, str] = {
    PanelChange.ADDED:           "+added",
    PanelChange.REMOVED:         "-removed",
    PanelChange.MODIFIED_QUERY:  "~query",
    PanelChange.MODIFIED_LAYOUT: "~layout",
    PanelChange.MODIFIED_CONFIG: "~config",
}

PANEL_A = GridPanel("Alpha", "timeseries", x=0,  y=0, w=12, h=8)
PANEL_B = GridPanel("Beta",  "timeseries", x=12, y=0, w=12, h=8)

CHANGES_QUERY = {
    "Alpha": frozenset({PanelChange.MODIFIED_QUERY}),
    "Beta":  frozenset({PanelChange.UNCHANGED}),
}

PATH_CHANGES_ALPHA: dict[str, list] = {
    "Alpha": [PathChange("targets[0].expr", "old", "new")],
}


def _band_text(changes, path_changes, before=None, after=None) -> str:
    before = before or [PANEL_A, PANEL_B]
    after  = after  or [PANEL_A, PANEL_B]
    renderables = build_band_renderables(
        y_band=0,
        before_panels=before,
        after_panels=after,
        changes=changes,
        path_changes=path_changes,
        console_width=160,
    )
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, width=160)
    for r in renderables:
        console.print(r)
    return buf.getvalue()


class TestDetailHeaderBadge:
    def test_query_change_badge_in_header(self):
        """Detail box for a ~query change must include '~query' in its title."""
        text = _band_text(CHANGES_QUERY, PATH_CHANGES_ALPHA)
        # The RichPanel title should contain both the panel name and the badge
        assert "~query" in text, (
            f"Expected '~query' badge in detail box header, got:\n{text}"
        )

    def test_added_badge_in_header(self):
        """Detail box for an added panel must include '+added' in its title."""
        changes = {"Alpha": frozenset({PanelChange.ADDED})}
        path_changes = {"Alpha": [PathChange("type", MISSING, "timeseries")]}
        text = _band_text(changes, path_changes)
        assert "+added" in text or "added" in text, (
            f"Expected 'added' badge in detail box header, got:\n{text}"
        )

    def test_removed_badge_in_header(self):
        """Detail box for a removed panel must include '-removed' in its title."""
        changes = {"Alpha": frozenset({PanelChange.REMOVED})}
        path_changes = {"Alpha": [PathChange("type", "timeseries", MISSING)]}
        text = _band_text(changes, path_changes)
        assert "-removed" in text or "removed" in text, (
            f"Expected 'removed' badge in detail box header, got:\n{text}"
        )

    def test_config_badge_in_header(self):
        """Detail box for a ~config change must include '~config' in its title."""
        changes = {"Alpha": frozenset({PanelChange.MODIFIED_CONFIG})}
        path_changes = {"Alpha": [PathChange("options.legend.displayMode", "list", "table")]}
        text = _band_text(changes, path_changes)
        assert "~config" in text, (
            f"Expected '~config' badge in detail box header, got:\n{text}"
        )

    def test_layout_badge_in_header(self):
        """Detail box for a ~layout change must include '~layout' in its title."""
        changes = {"Alpha": frozenset({PanelChange.MODIFIED_LAYOUT})}
        path_changes = {"Alpha": [PathChange("gridPos.w", 12, 24)]}
        text = _band_text(changes, path_changes)
        assert "~layout" in text, (
            f"Expected '~layout' badge in detail box header, got:\n{text}"
        )

    def test_panel_title_still_in_header(self):
        """The panel title must still appear in the detail box header."""
        text = _band_text(CHANGES_QUERY, PATH_CHANGES_ALPHA)
        assert "Alpha" in text, (
            f"Expected panel title 'Alpha' in detail box header, got:\n{text}"
        )


# ---------------------------------------------------------------------------
# Detail boxes ordered left-to-right by x position
# ---------------------------------------------------------------------------

# Two panels: Zeta (x=0) and Alpha (x=12).
# Alphabetically Alpha < Zeta, so if sorted by name Zeta would come second.
# By x position Zeta (x=0) must come FIRST.

PANEL_ZETA  = GridPanel("Zeta",  "timeseries", x=0,  y=0, w=12, h=8)
PANEL_ALPHA = GridPanel("Alpha", "timeseries", x=12, y=0, w=12, h=8)

CHANGES_BOTH_CHANGED = {
    "Zeta":  frozenset({PanelChange.MODIFIED_QUERY}),
    "Alpha": frozenset({PanelChange.MODIFIED_CONFIG}),
}

PATH_CHANGES_BOTH: dict[str, list] = {
    "Zeta":  [PathChange("targets[0].expr", "old_z", "new_z")],
    "Alpha": [PathChange("options.legend",  "list",  "table")],
}


class TestDetailBoxOrdering:
    def test_left_panel_detail_before_right_panel_detail(self):
        """
        Zeta is at x=0, Alpha is at x=12.
        Zeta's detail box must appear before Alpha's in the output.
        """
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_ZETA, PANEL_ALPHA],
            after_panels=[PANEL_ZETA, PANEL_ALPHA],
            changes=CHANGES_BOTH_CHANGED,
            path_changes=PATH_CHANGES_BOTH,
            console_width=160,
        )
        buf = io.StringIO()
        console = Console(file=buf, no_color=True, width=160)
        for r in renderables:
            console.print(r)
        text = buf.getvalue()

        zeta_pos  = text.find("Zeta")
        alpha_pos = text.find("Alpha")
        assert zeta_pos  != -1, "Expected 'Zeta' in output"
        assert alpha_pos != -1, "Expected 'Alpha' in output"

        # Find positions in the *detail section* specifically (after the grid row)
        # The grid row also contains both names, so we look for the second occurrence
        # of each name (which is in the detail box header)
        zeta_detail_pos  = text.find("Zeta",  zeta_pos  + 1)
        alpha_detail_pos = text.find("Alpha", alpha_pos + 1)

        if zeta_detail_pos == -1:
            zeta_detail_pos = zeta_pos
        if alpha_detail_pos == -1:
            alpha_detail_pos = alpha_pos

        assert zeta_detail_pos < alpha_detail_pos, (
            f"Zeta (x=0) detail box (pos {zeta_detail_pos}) must appear before "
            f"Alpha (x=12) detail box (pos {alpha_detail_pos})"
        )

    def test_alphabetical_order_overridden_by_x(self):
        """
        When alphabetical order disagrees with x order, x order wins.
        'Alpha' < 'Zeta' alphabetically, but Zeta is at x=0 so it goes first.
        """
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_ZETA, PANEL_ALPHA],
            after_panels=[PANEL_ZETA, PANEL_ALPHA],
            changes=CHANGES_BOTH_CHANGED,
            path_changes=PATH_CHANGES_BOTH,
            console_width=160,
            show_unchanged_panels=True,
        )
        buf = io.StringIO()
        console = Console(file=buf, no_color=True, width=160)
        for r in renderables[1:]:  # skip the grid row, only detail panels
            console.print(r)
        text = buf.getvalue()

        zeta_pos  = text.find("Zeta")
        alpha_pos = text.find("Alpha")
        assert zeta_pos  != -1, "Expected 'Zeta' in detail output"
        assert alpha_pos != -1, "Expected 'Alpha' in detail output"
        assert zeta_pos < alpha_pos, (
            f"Zeta (x=0) must appear before Alpha (x=12) in detail section. "
            f"Got Zeta at {zeta_pos}, Alpha at {alpha_pos}"
        )

    def test_added_panel_uses_after_x_for_ordering(self):
        """
        An added panel only exists in after_panels.
        Its x from after_panels must be used for ordering.
        """
        panel_new = GridPanel("NewPanel", "stat", x=0, y=0, w=12, h=8)
        panel_old = GridPanel("OldPanel", "stat", x=12, y=0, w=12, h=8)
        changes = {
            "NewPanel": frozenset({PanelChange.ADDED}),
            "OldPanel": frozenset({PanelChange.MODIFIED_CONFIG}),
        }
        path_changes: dict[str, list] = {
            "NewPanel": [PathChange("type", MISSING, "stat")],
            "OldPanel": [PathChange("options.x", 1, 2)],
        }
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[panel_old],          # NewPanel absent in before
            after_panels=[panel_new, panel_old],
            changes=changes,
            path_changes=path_changes,
            console_width=160,
            show_unchanged_panels=True,
        )
        buf = io.StringIO()
        console = Console(file=buf, no_color=True, width=160)
        for r in renderables[1:]:  # detail panels only
            console.print(r)
        text = buf.getvalue()

        new_pos = text.find("NewPanel")
        old_pos = text.find("OldPanel")
        assert new_pos != -1, "Expected 'NewPanel' in detail output"
        assert old_pos != -1, "Expected 'OldPanel' in detail output"
        assert new_pos < old_pos, (
            f"NewPanel (x=0, added) must appear before OldPanel (x=12). "
            f"Got NewPanel at {new_pos}, OldPanel at {old_pos}"
        )
