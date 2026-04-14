"""
RED tests for dashdiff detail (x) subcommand.

Tests the detail_panel_changes() helper (pure logic, no Rich) and the
cmd_detail() function (Rich output captured to string).

detail_panel_changes(before_dash, after_dash, strict=False)
    -> dict[str, list[PathChange]]

Returns a mapping of panel title -> list of PathChange for every panel
that has at least one change.  Uses normalised panel dicts so cosmetic
noise is excluded.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

from dashdiff.cli import detail_panel_changes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BEFORE = {
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

AFTER_QUERY_CHANGE = {
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
    ],
}

AFTER_PANEL_ADDED = {
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
        {
            "title": "Latency",
            "type": "timeseries",
            "gridPos": {"x": 0, "y": 8, "w": 24, "h": 8},
            "targets": [{"refId": "A", "expr": "histogram_quantile(0.99, rate(latency_bucket[5m]))"}],
        },
    ],
}

IDENTICAL = {
    "title": "My Dashboard",
    "panels": [
        {
            "title": "Request Rate",
            "type": "timeseries",
            "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
            "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
        },
    ],
}


# ---------------------------------------------------------------------------
# detail_panel_changes()
# ---------------------------------------------------------------------------

class TestDetailPanelChangesNoChange:
    def test_identical_dashboards_empty_result(self):
        result = detail_panel_changes(IDENTICAL, IDENTICAL)
        assert result == {}

    def test_returns_dict(self):
        result = detail_panel_changes(BEFORE, BEFORE)
        assert isinstance(result, dict)


class TestDetailPanelChangesQueryChange:
    def test_changed_panel_in_result(self):
        result = detail_panel_changes(BEFORE, AFTER_QUERY_CHANGE)
        assert "Error Rate" in result

    def test_unchanged_panel_not_in_result(self):
        result = detail_panel_changes(BEFORE, AFTER_QUERY_CHANGE)
        assert "Request Rate" not in result

    def test_path_contains_expr(self):
        result = detail_panel_changes(BEFORE, AFTER_QUERY_CHANGE)
        paths = [pc.path for pc in result["Error Rate"]]
        assert any("expr" in p for p in paths)

    def test_before_value_is_old_expr(self):
        result = detail_panel_changes(BEFORE, AFTER_QUERY_CHANGE)
        changes = {pc.path: pc for pc in result["Error Rate"]}
        expr_change = next(pc for pc in result["Error Rate"] if "expr" in pc.path)
        assert "5m" in str(expr_change.before)

    def test_after_value_is_new_expr(self):
        result = detail_panel_changes(BEFORE, AFTER_QUERY_CHANGE)
        expr_change = next(pc for pc in result["Error Rate"] if "expr" in pc.path)
        assert "2m" in str(expr_change.after)


class TestDetailPanelChangesAddedPanel:
    def test_added_panel_in_result(self):
        result = detail_panel_changes(BEFORE, AFTER_PANEL_ADDED)
        assert "Latency" in result

    def test_added_panel_has_changes(self):
        result = detail_panel_changes(BEFORE, AFTER_PANEL_ADDED)
        assert len(result["Latency"]) > 0


class TestDetailPanelChangesNoiseSuppressed:
    def test_id_field_not_in_paths(self):
        """Cosmetic 'id' fields must not appear in the change paths."""
        before_with_ids = {
            "title": "D", "version": 1, "iteration": 1000,
            "panels": [{"title": "P", "type": "timeseries", "id": 1,
                        "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                        "targets": [{"refId": "A", "expr": "old"}]}],
        }
        after_with_ids = {
            "title": "D", "version": 2, "iteration": 2000,
            "panels": [{"title": "P", "type": "timeseries", "id": 99,
                        "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                        "targets": [{"refId": "A", "expr": "new"}]}],
        }
        result = detail_panel_changes(before_with_ids, after_with_ids)
        all_paths = [pc.path for changes in result.values() for pc in changes]
        assert not any("id" == p or p.endswith(".id") for p in all_paths)

    def test_version_not_in_result(self):
        """Top-level version bump must not produce any panel changes."""
        before = {"title": "D", "version": 1,
                  "panels": [{"title": "P", "type": "stat",
                               "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
                               "targets": []}]}
        after  = {"title": "D", "version": 2,
                  "panels": [{"title": "P", "type": "stat",
                               "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
                               "targets": []}]}
        result = detail_panel_changes(before, after)
        assert result == {}
