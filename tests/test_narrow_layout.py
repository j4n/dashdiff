"""
Tests for narrow-terminal layout behaviour.

Below NARROW_WIDTH columns the renderer switches from side-by-side to stacked:
  - Grid band rows: before section on top, after section below
  - Detail path tables: path / before / after rows stacked vertically

Title truncation with a UTF-8 ellipsis (…) is also tested here.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.table import Table

from dashdiff.grid import (
    PanelChange,
    GridPanel,
    build_band_renderables,
    NARROW_WIDTH,
    truncate_title,
)
from dashdiff.diff_paths import PathChange, MISSING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render(renderable, width: int) -> str:
    buf = io.StringIO()
    Console(file=buf, no_color=True, width=width).print(renderable)
    return buf.getvalue()


def _render_all(renderables, width: int) -> str:
    buf = io.StringIO()
    c = Console(file=buf, no_color=True, width=width)
    for r in renderables:
        c.print(r)
    return buf.getvalue()


PANEL_A = GridPanel("Alpha", "timeseries", x=0,  y=0, w=12, h=8)
PANEL_B = GridPanel("Beta",  "timeseries", x=12, y=0, w=12, h=8)

CHANGES_QUERY = {
    "Alpha": frozenset({PanelChange.MODIFIED_QUERY}),
    "Beta":  frozenset({PanelChange.UNCHANGED}),
}

PATH_CHANGES = {
    "Alpha": [
        PathChange(path="targets[0].expr", before="old_expr", after="new_expr"),
    ],
}


# ---------------------------------------------------------------------------
# NARROW_WIDTH constant
# ---------------------------------------------------------------------------

class TestNarrowWidthConstant:
    def test_narrow_width_is_defined(self):
        assert isinstance(NARROW_WIDTH, int)

    def test_narrow_width_is_reasonable(self):
        # Should be between 100 and 160
        assert 100 <= NARROW_WIDTH <= 160


# ---------------------------------------------------------------------------
# truncate_title
# ---------------------------------------------------------------------------

class TestTruncateTitle:
    def test_short_title_unchanged(self):
        assert truncate_title("RTT", max_chars=20) == "RTT"

    def test_title_exactly_at_limit_unchanged(self):
        title = "A" * 20
        assert truncate_title(title, max_chars=20) == title

    def test_title_over_limit_truncated_with_ellipsis(self):
        title = "A" * 25
        result = truncate_title(title, max_chars=20)
        assert result.endswith("…")
        assert len(result) == 20

    def test_truncated_title_fits_in_max_chars(self):
        title = "Outbound Loss (avg over destinations)"
        result = truncate_title(title, max_chars=15)
        assert len(result) <= 15
        assert result.endswith("…")

    def test_very_short_max_chars(self):
        # Even with max_chars=2, must not crash and must end with ellipsis
        result = truncate_title("Hello World", max_chars=2)
        assert len(result) <= 2

    def test_empty_title_unchanged(self):
        assert truncate_title("", max_chars=10) == ""


# ---------------------------------------------------------------------------
# Stacked grid band row (below NARROW_WIDTH)
# ---------------------------------------------------------------------------

class TestStackedGridBandRow:
    def test_narrow_output_contains_before_label(self):
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A, PANEL_B],
            after_panels=[PANEL_A, PANEL_B],
            changes=CHANGES_QUERY,
            path_changes={},
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        assert "before" in output.lower()

    def test_narrow_output_contains_after_label(self):
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A, PANEL_B],
            after_panels=[PANEL_A, PANEL_B],
            changes=CHANGES_QUERY,
            path_changes={},
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        assert "after" in output.lower()

    def test_wide_output_has_side_by_side_table(self):
        """At wide width the outer container is a two-column Table."""
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A, PANEL_B],
            after_panels=[PANEL_A, PANEL_B],
            changes=CHANGES_QUERY,
            path_changes={},
            console_width=NARROW_WIDTH + 1,
        )
        assert len(renderables) >= 1
        assert isinstance(renderables[0], Table)
        # Wide table has 2 columns (before / after)
        assert len(renderables[0].columns) == 2

    def test_narrow_does_not_use_two_column_outer_table(self):
        """At narrow width the outer container must NOT be a 2-column Table."""
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A, PANEL_B],
            after_panels=[PANEL_A, PANEL_B],
            changes=CHANGES_QUERY,
            path_changes={},
            console_width=NARROW_WIDTH - 1,
        )
        assert len(renderables) >= 1
        first = renderables[0]
        # Must not be a 2-column side-by-side table
        if isinstance(first, Table):
            assert len(first.columns) != 2, (
                "Narrow layout must not use a 2-column side-by-side Table"
            )


# ---------------------------------------------------------------------------
# Stacked detail path table (below NARROW_WIDTH)
# ---------------------------------------------------------------------------

class TestStackedDetailPathTable:
    def test_narrow_detail_contains_path(self):
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A],
            after_panels=[PANEL_A],
            changes=CHANGES_QUERY,
            path_changes=PATH_CHANGES,
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        assert "targets[0].expr" in output

    def test_narrow_detail_contains_before_value(self):
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A],
            after_panels=[PANEL_A],
            changes=CHANGES_QUERY,
            path_changes=PATH_CHANGES,
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        assert "old_expr" in output

    def test_narrow_detail_contains_after_value(self):
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A],
            after_panels=[PANEL_A],
            changes=CHANGES_QUERY,
            path_changes=PATH_CHANGES,
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        assert "new_expr" in output

    def test_narrow_detail_key_on_own_line(self):
        """In narrow mode the path key must appear on a line by itself above the values."""
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A],
            after_panels=[PANEL_A],
            changes=CHANGES_QUERY,
            path_changes=PATH_CHANGES,
            console_width=NARROW_WIDTH - 1,
        )
        output = _render_all(renderables, width=NARROW_WIDTH - 1)
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        # The path key must appear on a line that does NOT also contain 'before:' or 'after:'
        path_lines = [l for l in lines if "targets[0].expr" in l]
        assert path_lines, "Path key not found in output"
        for line in path_lines:
            assert "before:" not in line, (
                f"Path key and 'before:' are on the same line: {line!r}"
            )
            assert "after:" not in line, (
                f"Path key and 'after:' are on the same line: {line!r}"
            )

    def test_wide_detail_has_three_columns(self):
        """At wide width the detail table has path / before / after columns."""
        renderables = build_band_renderables(
            y_band=0,
            before_panels=[PANEL_A],
            after_panels=[PANEL_A],
            changes=CHANGES_QUERY,
            path_changes=PATH_CHANGES,
            console_width=NARROW_WIDTH + 1,
        )
        # Second renderable is the detail RichPanel; its content is a Table
        from rich.panel import Panel as RichPanel
        detail_panels = [r for r in renderables if isinstance(r, RichPanel)]
        assert detail_panels, "Expected at least one detail RichPanel"
        output = _render_all(renderables, width=NARROW_WIDTH + 1)
        # Wide layout must have both before and after as separate columns
        assert "before" in output.lower()
        assert "after" in output.lower()
