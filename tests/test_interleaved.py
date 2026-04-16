"""
RED tests for interleaved per-band rendering in the detail/visual diff output.

The new layout interleaves, for each horizontal band (y-row):
  1. A side-by-side before/after grid row (the panel boxes)
  2. Immediately below: detail panels for any changed panels in that band

This keeps each band self-contained so the reviewer can read band-by-band
without scrolling between a large grid and a separate change list.

Public API under test
---------------------
grid.build_band_renderables(
    y_band,
    before_panels,
    after_panels,
    changes,
    path_changes,
    console_width,
) -> list[object]

cli.cmd_detail() — output must interleave band rows and detail sections

Note: cmd_visual interleaving and unchanged-band skipping are tested in
test_skip_unchanged_bands.py.
"""

from __future__ import annotations

import io

from rich.console import Console
from rich.table import Table  # used for isinstance check in TestBuildBandRenderables

from dashdiff.grid import (
    GridPanel,
    PanelChange,
)
from dashdiff.diff_paths import PathChange, MISSING


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _console(width: int = 160) -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, no_color=True, width=width), buf


BEFORE_DASH = {
    "title": "My Dashboard",
    "panels": [
        {
            "title": "Request Rate",
            "type": "timeseries",
            "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
        },
        {
            "title": "Error Rate",
            "type": "timeseries",
            "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
            "targets": [
                {"refId": "A", "expr": "rate(requests_total[5m])"},
                {"refId": "B", "expr": "rate(errors_total[5m])"},
            ],
        },
    ],
}

AFTER_DASH = {
    "title": "My Dashboard",
    "panels": [
        {
            "title": "Request Rate",
            "type": "timeseries",
            "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
        },
        {
            "title": "Error Rate",
            "type": "timeseries",
            "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
            "targets": [
                {"refId": "A", "expr": "rate(requests_total[2m])"},  # changed
                {"refId": "B", "expr": "rate(errors_total[5m])"},
            ],
        },
        {
            "title": "Latency",
            "type": "timeseries",
            "gridPos": {"x": 0, "y": 8, "w": 24, "h": 8},
            "targets": [{"refId": "A", "expr": "histogram_quantile(0.99, rate(latency_bucket[5m]))"}],
        },
    ],
}

# Pre-built panel lists
BEFORE_PANELS = [
    GridPanel("Request Rate", "timeseries", 0, 0, 12, 8),
    GridPanel("Error Rate",   "timeseries", 12, 0, 12, 8),
]
AFTER_PANELS = [
    GridPanel("Request Rate", "timeseries", 0, 0, 12, 8),
    GridPanel("Error Rate",   "timeseries", 12, 0, 12, 8),
    GridPanel("Latency",      "timeseries", 0, 8, 24, 8),
]

CHANGES = {
    "Request Rate": frozenset({PanelChange.UNCHANGED}),
    "Error Rate":   frozenset({PanelChange.MODIFIED_QUERY}),
    "Latency":      frozenset({PanelChange.ADDED}),
}

PATH_CHANGES: dict[str, list[PathChange]] = {
    "Error Rate": [
        PathChange("targets[0].expr", "rate(requests_total[5m])", "rate(requests_total[2m])"),
    ],
    "Latency": [
        PathChange("targets[0].expr", MISSING, "histogram_quantile(0.99, rate(latency_bucket[5m]))"),
    ],
}


# ---------------------------------------------------------------------------
# build_band_renderables — new function in grid.py
# ---------------------------------------------------------------------------

class TestBuildBandRenderables:
    def test_function_exists(self):
        """build_band_renderables must be importable from dashdiff.grid."""
        from dashdiff.grid import build_band_renderables  # noqa: F401

    def test_returns_list(self):
        from dashdiff.grid import build_band_renderables
        result = build_band_renderables(
            y_band=0,
            before_panels=[BEFORE_PANELS[0], BEFORE_PANELS[1]],
            after_panels=[AFTER_PANELS[0], AFTER_PANELS[1]],
            changes=CHANGES,
            path_changes=PATH_CHANGES,
            console_width=160,
        )
        assert isinstance(result, list)
        assert len(result) > 0

    def test_first_renderable_is_side_by_side_table(self):
        """The first renderable in a band must be the side-by-side grid Table."""
        from dashdiff.grid import build_band_renderables
        result = build_band_renderables(
            y_band=0,
            before_panels=[BEFORE_PANELS[0], BEFORE_PANELS[1]],
            after_panels=[AFTER_PANELS[0], AFTER_PANELS[1]],
            changes=CHANGES,
            path_changes=PATH_CHANGES,
            console_width=160,
            show_unchanged_panels=True,
        )
        assert isinstance(result[0], Table), (
            f"Expected first renderable to be a Table, got {type(result[0])}"
        )

    def test_band_with_changed_panel_includes_detail(self):
        """A band containing a changed panel must include a detail section."""
        from dashdiff.grid import build_band_renderables
        result = build_band_renderables(
            y_band=0,
            before_panels=[BEFORE_PANELS[0], BEFORE_PANELS[1]],
            after_panels=[AFTER_PANELS[0], AFTER_PANELS[1]],
            changes=CHANGES,
            path_changes=PATH_CHANGES,
            console_width=160,
        )
        # Render all renderables and check that the changed path appears
        console, buf = _console()
        for r in result:
            console.print(r)
        text = buf.getvalue()
        assert "targets[0].expr" in text, (
            "Expected changed path 'targets[0].expr' in band 0 detail output"
        )

    def test_added_panel_band_shows_detail(self):
        """A band containing an ADDED panel must include detail rows."""
        from dashdiff.grid import build_band_renderables
        result = build_band_renderables(
            y_band=8,
            before_panels=[],
            after_panels=[AFTER_PANELS[2]],
            changes=CHANGES,
            path_changes=PATH_CHANGES,
            console_width=160,
        )
        console, buf = _console()
        for r in result:
            console.print(r)
        text = buf.getvalue()
        assert "Latency" in text or "latency" in text.lower(), (
            "Expected 'Latency' in added-panel band output"
        )

    def test_detail_values_appear_in_output(self):
        """Before/after values from PathChange must appear in the detail section."""
        from dashdiff.grid import build_band_renderables
        result = build_band_renderables(
            y_band=0,
            before_panels=[BEFORE_PANELS[0], BEFORE_PANELS[1]],
            after_panels=[AFTER_PANELS[0], AFTER_PANELS[1]],
            changes=CHANGES,
            path_changes=PATH_CHANGES,
            console_width=160,
        )
        console, buf = _console()
        for r in result:
            console.print(r)
        text = buf.getvalue()
        assert "5m" in text, "Expected old value '5m' in detail output"
        assert "2m" in text, "Expected new value '2m' in detail output"


# ---------------------------------------------------------------------------
# cmd_detail — interleaved output
# ---------------------------------------------------------------------------

def _run_detail(before, after, strict=False) -> str:
    """Run cmd_detail and capture its output as a plain-text string."""
    import argparse
    from dashdiff.cli import cmd_detail
    from unittest.mock import patch
    import shutil

    buf = io.StringIO()
    console_mock = Console(file=buf, no_color=True, width=160)

    args = argparse.Namespace(before="before.json", after="after.json", strict=strict)

    # Patch _load to return our dicts, and make_console to return our console
    with (
        patch("dashdiff.cli._load", side_effect=[before, after]),
        patch("dashdiff.cli.make_console", return_value=console_mock),
    ):
        cmd_detail(args)

    return buf.getvalue()


class TestCmdDetailInterleaved:
    def test_band0_detail_before_band8_grid(self):
        """
        The detail for band y=0 (Error Rate query change) must appear
        BEFORE the grid row for band y=8 (Latency added).
        """
        text = _run_detail(BEFORE_DASH, AFTER_DASH)
        # Find positions of key markers
        expr_pos   = text.find("targets[0].expr")
        latency_pos = text.lower().find("latency")
        assert expr_pos != -1,   "Expected 'targets[0].expr' in output"
        assert latency_pos != -1, "Expected 'Latency' in output"
        assert expr_pos < latency_pos, (
            f"Band-0 detail (pos {expr_pos}) must appear before "
            f"band-8 grid row (pos {latency_pos})"
        )

    def test_changed_values_present(self):
        """Both old and new query values must appear in the output."""
        text = _run_detail(BEFORE_DASH, AFTER_DASH)
        assert "5m" in text, "Expected old value '5m'"
        assert "2m" in text, "Expected new value '2m'"

    def test_added_panel_detail_present(self):
        """The Latency panel (added) must have a detail section."""
        text = _run_detail(BEFORE_DASH, AFTER_DASH)
        assert "latency_bucket" in text.lower() or "Latency" in text, (
            "Expected Latency panel detail in output"
        )

    def test_unchanged_panel_has_no_detail(self):
        """Request Rate is unchanged — its paths must not appear in detail."""
        text = _run_detail(BEFORE_DASH, AFTER_DASH)
        # Request Rate's expr should not appear as a changed path
        # (it's the same in both versions)
        # We check that "http_requests_total" does NOT appear in a detail table
        # by verifying the path row format isn't present for it
        # (it may appear in the grid panel badge area, but not as a path change)
        lines = text.splitlines()
        path_lines = [l for l in lines if "http_requests_total" in l]
        # None of those lines should look like a path-change table row
        for line in path_lines:
            assert "targets" not in line or "5m" not in line, (
                f"Unexpected detail row for unchanged Request Rate: {line!r}"
            )

    def test_no_separate_changed_paths_header(self):
        """
        The old 'Changed paths' rule separator must NOT appear —
        the new layout is fully interleaved, not a separate section.
        """
        text = _run_detail(BEFORE_DASH, AFTER_DASH)
        assert "Changed paths" not in text, (
            "Old 'Changed paths' section header must be removed in interleaved layout"
        )



