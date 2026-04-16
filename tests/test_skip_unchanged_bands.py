"""
RED tests for skipping unchanged bands in the interleaved output.

A band is "unchanged" when every panel in it has PanelChange.UNCHANGED.
Such bands must not appear in the output of cmd_detail or cmd_visual
two-file mode — they add no information and clutter the diff.
"""

from __future__ import annotations

import io
import json
import os
import tempfile

import pytest
from rich.console import Console

from dashdiff.grid import (
    PanelChange,
    GridPanel,
    build_band_renderables,
)
from dashdiff.cli import detail_panel_changes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cmd(cmd_name: str, before_dash: dict, after_dash: dict) -> str:
    """Run dashdiff <cmd_name> on two in-memory dashboards and return stdout."""
    import subprocess, sys
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as bf:
        json.dump(before_dash, bf)
        bf_path = bf.name
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as af:
        json.dump(after_dash, af)
        af_path = af.name
    try:
        result = subprocess.run(
            ["dashdiff", cmd_name, bf_path, af_path],
            capture_output=True, text=True,
        )
        return result.stdout + result.stderr
    finally:
        os.unlink(bf_path)
        os.unlink(af_path)


def _make_dashboard(*panels: dict) -> dict:
    return {"title": "Test", "panels": list(panels)}


def _panel(title: str, x: int, y: int, w: int = 12, h: int = 8,
           ptype: str = "timeseries", expr: str = "up") -> dict:
    return {
        "title": title,
        "type": ptype,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [{"refId": "A", "expr": expr}],
    }


# ---------------------------------------------------------------------------
# Unit-level: build_band_renderables returns [] for unchanged bands
# ---------------------------------------------------------------------------

UNCHANGED_PANELS = [
    GridPanel("Alpha", "timeseries", x=0,  y=0, w=12, h=8),
    GridPanel("Beta",  "timeseries", x=12, y=0, w=12, h=8),
]

ALL_UNCHANGED = {
    "Alpha": frozenset({PanelChange.UNCHANGED}),
    "Beta":  frozenset({PanelChange.UNCHANGED}),
}


class TestBuildBandRenderablesSkipsUnchanged:
    def test_all_unchanged_returns_empty(self):
        """
        build_band_renderables must return an empty list when every panel
        in the band is UNCHANGED and there are no path_changes.
        """
        result = build_band_renderables(
            y_band=0,
            before_panels=UNCHANGED_PANELS,
            after_panels=UNCHANGED_PANELS,
            changes=ALL_UNCHANGED,
            path_changes={},
            console_width=160,
            show_unchanged_panels=True,
        )
        assert result == [], (
            f"Expected empty list for all-unchanged band, got {len(result)} renderables"
        )

    def test_one_changed_panel_renders_band(self):
        """
        If even one panel in the band is changed, the band must be rendered.
        """
        changes = {
            "Alpha": frozenset({PanelChange.MODIFIED_QUERY}),
            "Beta":  frozenset({PanelChange.UNCHANGED}),
}
        result = build_band_renderables(
            y_band=0,
            before_panels=UNCHANGED_PANELS,
            after_panels=UNCHANGED_PANELS,
            changes=changes,
            path_changes={},
            console_width=160,
            show_unchanged_panels=True,
        )
        assert len(result) >= 1, (
            "Expected at least one renderable when one panel is changed"
        )

    def test_added_panel_renders_band(self):
        """A band with an added panel must be rendered."""
        new_panel = GridPanel("Gamma", "stat", x=0, y=0, w=12, h=8)
        changes = {"Gamma": frozenset({PanelChange.ADDED})}
        result = build_band_renderables(
            y_band=0,
            before_panels=[],
            after_panels=[new_panel],
            changes=changes,
            path_changes={},
            console_width=160,
            show_unchanged_panels=True,
        )
        assert len(result) >= 1, "Expected renderable for band with added panel"

    def test_removed_panel_renders_band(self):
        """A band with a removed panel must be rendered."""
        old_panel = GridPanel("Delta", "stat", x=0, y=0, w=12, h=8)
        changes = {"Delta": frozenset({PanelChange.REMOVED})}
        result = build_band_renderables(
            y_band=0,
            before_panels=[old_panel],
            after_panels=[],
            changes=changes,
            path_changes={},
            console_width=160,
            show_unchanged_panels=True,
        )
        assert len(result) >= 1, "Expected renderable for band with removed panel"


# ---------------------------------------------------------------------------
# Integration-level: cmd_detail skips unchanged bands
# ---------------------------------------------------------------------------

class TestCmdDetailSkipsUnchangedBands:
    def test_unchanged_band_not_in_output(self):
        """
        A band where all panels are unchanged must not appear in cmd_detail output.
        """
        # Band y=0: both panels unchanged
        # Band y=8: one panel has a changed query
        before = _make_dashboard(
            _panel("Unchanged A", x=0,  y=0, w=12, h=8, expr="up"),
            _panel("Unchanged B", x=12, y=0, w=12, h=8, expr="down"),
            _panel("Changed Q",   x=0,  y=8, w=24, h=8, expr="rate(a[5m])"),
        )
        after = _make_dashboard(
            _panel("Unchanged A", x=0,  y=0, w=12, h=8, expr="up"),
            _panel("Unchanged B", x=12, y=0, w=12, h=8, expr="down"),
            _panel("Changed Q",   x=0,  y=8, w=24, h=8, expr="rate(a[2m])"),
        )
        output = _run_cmd("detail", before, after)
        # The unchanged panels must not appear in the output
        assert "Unchanged A" not in output, (
            f"'Unchanged A' (unchanged band) must not appear in detail output"
        )
        assert "Unchanged B" not in output, (
            f"'Unchanged B' (unchanged band) must not appear in detail output"
        )
        # The changed panel must appear
        assert "Changed Q" in output, (
            f"'Changed Q' (changed band) must appear in detail output"
        )

    def test_all_unchanged_shows_no_panels(self):
        """When nothing changed, no panel names appear in the output."""
        dash = _make_dashboard(
            _panel("Panel A", x=0,  y=0, w=12, h=8),
            _panel("Panel B", x=12, y=0, w=12, h=8),
        )
        output = _run_cmd("detail", dash, dash)
        assert "Panel A" not in output
        assert "Panel B" not in output

    def test_only_changed_bands_shown(self):
        """
        With three bands (y=0 unchanged, y=8 changed, y=16 unchanged),
        only the y=8 band must appear.
        """
        before = _make_dashboard(
            _panel("Row0 A", x=0, y=0,  w=24, h=4),
            _panel("Row8 B", x=0, y=8,  w=24, h=4, expr="old_expr"),
            _panel("Row16 C", x=0, y=16, w=24, h=4),
        )
        after = _make_dashboard(
            _panel("Row0 A", x=0, y=0,  w=24, h=4),
            _panel("Row8 B", x=0, y=8,  w=24, h=4, expr="new_expr"),
            _panel("Row16 C", x=0, y=16, w=24, h=4),
        )
        output = _run_cmd("detail", before, after)
        assert "Row0 A"  not in output, "Unchanged band y=0 must be skipped"
        assert "Row16 C" not in output, "Unchanged band y=16 must be skipped"
        assert "Row8 B"  in output,     "Changed band y=8 must be shown"


# ---------------------------------------------------------------------------
# Integration-level: cmd_visual skips unchanged bands
# ---------------------------------------------------------------------------

class TestCmdVisualSkipsUnchangedBands:
    def test_unchanged_band_not_in_visual_output(self):
        """cmd_visual two-file mode must also skip unchanged bands."""
        before = _make_dashboard(
            _panel("Static Panel", x=0, y=0, w=24, h=4),
            _panel("Dynamic Panel", x=0, y=8, w=24, h=4, expr="old"),
        )
        after = _make_dashboard(
            _panel("Static Panel", x=0, y=0, w=24, h=4),
            _panel("Dynamic Panel", x=0, y=8, w=24, h=4, expr="new"),
        )
        output = _run_cmd("visual", before, after)
        assert "Static Panel" not in output, (
            "Unchanged band must not appear in visual output"
        )
        assert "Dynamic Panel" in output, (
            "Changed band must appear in visual output"
        )
