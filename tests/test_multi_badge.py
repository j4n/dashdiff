"""
Tests for multi-kind change classification and multi-badge panel rendering.

A panel can have more than one kind of change simultaneously — e.g. both its
query and its layout changed.  classify_changes() must return a frozenset of
PanelChange kinds per panel, and _panel_cell() must render one badge per kind.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from dashdiff.grid import (
    PanelChange,
    GridPanel,
    classify_changes,
    change_border_style,
    _panel_cell,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = {
    "title": "My Panel",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
}

_QUERY_AND_LAYOUT = {
    "title": "My Panel",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},   # y moved
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[1m])"}],  # expr changed
}

_QUERY_AND_CONFIG = {
    "title": "My Panel",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[1m])"}],  # expr changed
    "options": {"legend": {"displayMode": "hidden"}},                       # config changed
}

_LAYOUT_AND_CONFIG = {
    "title": "My Panel",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},   # y moved
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
    "options": {"legend": {"displayMode": "hidden"}},
}

_ALL_THREE = {
    "title": "My Panel",
    "type": "timeseries",
    "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},   # y moved
    "targets": [{"refId": "A", "expr": "rate(http_requests_total[1m])"}],  # expr changed
    "options": {"legend": {"displayMode": "hidden"}},                       # config changed
}


# ---------------------------------------------------------------------------
# classify_changes() — multi-kind return type
# ---------------------------------------------------------------------------

class TestClassifyChangesMultiKind:
    """classify_changes() must return frozenset[PanelChange] per panel."""

    def test_unchanged_returns_singleton_frozenset(self):
        result = classify_changes([_BASE], [_BASE])
        kinds = result["My Panel"]
        assert isinstance(kinds, frozenset)
        assert kinds == frozenset({PanelChange.UNCHANGED})

    def test_added_returns_singleton_frozenset(self):
        result = classify_changes([], [_BASE])
        assert result["My Panel"] == frozenset({PanelChange.ADDED})

    def test_removed_returns_singleton_frozenset(self):
        result = classify_changes([_BASE], [])
        assert result["My Panel"] == frozenset({PanelChange.REMOVED})

    def test_query_only_change(self):
        after = {**_BASE, "targets": [{"refId": "A", "expr": "new_metric[5m]"}]}
        result = classify_changes([_BASE], [after])
        assert result["My Panel"] == frozenset({PanelChange.MODIFIED_QUERY})

    def test_layout_only_change(self):
        after = {**_BASE, "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8}}
        result = classify_changes([_BASE], [after])
        assert result["My Panel"] == frozenset({PanelChange.MODIFIED_LAYOUT})

    def test_config_only_change(self):
        after = {**_BASE, "options": {"legend": {"displayMode": "hidden"}}}
        result = classify_changes([_BASE], [after])
        assert result["My Panel"] == frozenset({PanelChange.MODIFIED_CONFIG})

    def test_query_and_layout_change(self):
        result = classify_changes([_BASE], [_QUERY_AND_LAYOUT])
        kinds = result["My Panel"]
        assert PanelChange.MODIFIED_QUERY  in kinds
        assert PanelChange.MODIFIED_LAYOUT in kinds
        assert PanelChange.UNCHANGED not in kinds

    def test_query_and_config_change(self):
        result = classify_changes([_BASE], [_QUERY_AND_CONFIG])
        kinds = result["My Panel"]
        assert PanelChange.MODIFIED_QUERY  in kinds
        assert PanelChange.MODIFIED_CONFIG in kinds

    def test_layout_and_config_change(self):
        result = classify_changes([_BASE], [_LAYOUT_AND_CONFIG])
        kinds = result["My Panel"]
        assert PanelChange.MODIFIED_LAYOUT in kinds
        assert PanelChange.MODIFIED_CONFIG in kinds

    def test_all_three_changes(self):
        result = classify_changes([_BASE], [_ALL_THREE])
        kinds = result["My Panel"]
        assert PanelChange.MODIFIED_QUERY  in kinds
        assert PanelChange.MODIFIED_LAYOUT in kinds
        assert PanelChange.MODIFIED_CONFIG in kinds


# ---------------------------------------------------------------------------
# change_border_style() — accepts frozenset
# ---------------------------------------------------------------------------

class TestChangeBorderStyleMultiKind:
    def test_structural_kind_in_set_gives_colour(self):
        kinds = frozenset({PanelChange.MODIFIED_QUERY, PanelChange.MODIFIED_LAYOUT})
        assert change_border_style(kinds) is not None

    def test_content_only_set_gives_no_colour(self):
        kinds = frozenset({PanelChange.MODIFIED_QUERY, PanelChange.MODIFIED_CONFIG})
        assert change_border_style(kinds) is None

    def test_added_singleton_gives_colour(self):
        assert change_border_style(frozenset({PanelChange.ADDED})) is not None

    def test_unchanged_singleton_gives_no_colour(self):
        assert change_border_style(frozenset({PanelChange.UNCHANGED})) is None


# ---------------------------------------------------------------------------
# _panel_cell() — multiple badges rendered
# ---------------------------------------------------------------------------

def _render_cell(kinds: frozenset[PanelChange]) -> str:
    gp = GridPanel("My Panel", "timeseries", x=0, y=0, w=12, h=8)
    cell = _panel_cell(gp, change=kinds, fixed_height=8)
    buf = io.StringIO()
    Console(file=buf, no_color=True, width=80).print(cell)
    return buf.getvalue()


class TestPanelCellMultiBadge:
    def test_two_badges_both_rendered(self):
        kinds = frozenset({PanelChange.MODIFIED_QUERY, PanelChange.MODIFIED_LAYOUT})
        text = _render_cell(kinds)
        assert "~query"  in text
        assert "~layout" in text

    def test_three_badges_all_rendered(self):
        kinds = frozenset({
            PanelChange.MODIFIED_QUERY,
            PanelChange.MODIFIED_LAYOUT,
            PanelChange.MODIFIED_CONFIG,
        })
        text = _render_cell(kinds)
        assert "~query"  in text
        assert "~layout" in text
        assert "~config" in text

    def test_single_badge_still_works(self):
        kinds = frozenset({PanelChange.MODIFIED_CONFIG})
        text = _render_cell(kinds)
        assert "~config" in text
        assert "~query"  not in text

    def test_unchanged_has_no_badges(self):
        kinds = frozenset({PanelChange.UNCHANGED})
        text = _render_cell(kinds)
        for badge in ("+added", "-removed", "~query", "~layout", "~config"):
            assert badge not in text
