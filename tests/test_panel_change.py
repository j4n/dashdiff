"""
Tests for PanelChange classification and border-style logic.

Tests cover:
- classify_changes() returns correct kinds for added/removed/modified/unchanged panels
- Modified panels are sub-classified as query/title/layout/config changes
- change_border_style(): structural changes (added/removed/layout) get coloured borders;
  content-only changes (query/config) return None so the border stays at type colour

Badge rendering (_panel_cell) is covered in test_multi_badge.py.
"""

from __future__ import annotations

import pytest

from dashdiff.grid import PanelChange, GridPanel, classify_changes, change_border_style


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PANEL_A = {
    "title": "Request Rate",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
}

PANEL_B = {
    "title": "Error Rate",
    "type": "timeseries",
    "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(errors_total[5m])"}],
}

PANEL_A_QUERY_CHANGED = {
    "title": "Request Rate",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[1m])"}],
}

PANEL_A_TITLE_CHANGED = {
    "title": "Request Rate v2",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
}

PANEL_A_LAYOUT_CHANGED = {
    "title": "Request Rate",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},  # y moved
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
}

PANEL_A_CONFIG_CHANGED = {
    "title": "Request Rate",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
    "options": {"legend": {"displayMode": "hidden"}},
}


# ---------------------------------------------------------------------------
# classify_changes()
# ---------------------------------------------------------------------------

class TestClassifyChangesAdded:
    def test_new_panel_is_added(self):
        before = [PANEL_A]
        after  = [PANEL_A, PANEL_B]
        result = classify_changes(before, after)
        assert result["Error Rate"] == frozenset({PanelChange.ADDED})

    def test_existing_panel_not_added(self):
        before = [PANEL_A]
        after  = [PANEL_A, PANEL_B]
        result = classify_changes(before, after)
        assert PanelChange.ADDED not in result.get("Request Rate", frozenset())


class TestClassifyChangesRemoved:
    def test_missing_panel_is_removed(self):
        before = [PANEL_A, PANEL_B]
        after  = [PANEL_A]
        result = classify_changes(before, after)
        assert result["Error Rate"] == frozenset({PanelChange.REMOVED})

    def test_removed_panel_not_in_after(self):
        before = [PANEL_A, PANEL_B]
        after  = [PANEL_A]
        result = classify_changes(before, after)
        assert PanelChange.REMOVED not in result.get("Request Rate", frozenset())


class TestClassifyChangesUnchanged:
    def test_identical_panel_is_unchanged(self):
        before = [PANEL_A, PANEL_B]
        after  = [PANEL_A, PANEL_B]
        result = classify_changes(before, after)
        assert result["Request Rate"] == frozenset({PanelChange.UNCHANGED})
        assert result["Error Rate"]   == frozenset({PanelChange.UNCHANGED})

    def test_all_keys_present_when_unchanged(self):
        before = [PANEL_A, PANEL_B]
        after  = [PANEL_A, PANEL_B]
        result = classify_changes(before, after)
        assert set(result.keys()) == {"Request Rate", "Error Rate"}


class TestClassifyChangesModified:
    def test_query_change_detected(self):
        before = [PANEL_A]
        after  = [PANEL_A_QUERY_CHANGED]
        result = classify_changes(before, after)
        assert PanelChange.MODIFIED_QUERY in result["Request Rate"]

    def test_title_change_detected(self):
        before = [PANEL_A]
        after  = [PANEL_A_TITLE_CHANGED]
        result = classify_changes(before, after)
        # New title is the key in after; old title is REMOVED
        assert result["Request Rate"] == frozenset({PanelChange.REMOVED})
        assert result["Request Rate v2"] == frozenset({PanelChange.ADDED})

    def test_layout_change_detected(self):
        before = [PANEL_A]
        after  = [PANEL_A_LAYOUT_CHANGED]
        result = classify_changes(before, after)
        assert PanelChange.MODIFIED_LAYOUT in result["Request Rate"]

    def test_config_change_detected(self):
        before = [PANEL_A]
        after  = [PANEL_A_CONFIG_CHANGED]
        result = classify_changes(before, after)
        assert PanelChange.MODIFIED_CONFIG in result["Request Rate"]


# ---------------------------------------------------------------------------
# change_border_style()
# ---------------------------------------------------------------------------

class TestChangeBorderStyle:
    """Structural changes get a coloured border; content-only changes do not."""

    def test_added_has_coloured_border(self):
        style = change_border_style(PanelChange.ADDED)
        assert style is not None and "#" in style

    def test_removed_has_coloured_border(self):
        style = change_border_style(PanelChange.REMOVED)
        assert style is not None and "#" in style

    def test_layout_has_coloured_border(self):
        style = change_border_style(PanelChange.MODIFIED_LAYOUT)
        assert style is not None and "#" in style

    def test_query_has_no_border_colour(self):
        """~query is content-only: badge inside the box, default border."""
        assert change_border_style(PanelChange.MODIFIED_QUERY) is None

    def test_config_has_no_border_colour(self):
        """~config is content-only: badge inside the box, default border."""
        assert change_border_style(PanelChange.MODIFIED_CONFIG) is None

    def test_unchanged_returns_none(self):
        assert change_border_style(PanelChange.UNCHANGED) is None


