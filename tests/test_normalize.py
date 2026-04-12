"""
Tests for grafana_normalize.normalize().

Run with:  python -m pytest tests/ -v
"""

import json
import pathlib
import pytest

from grafana_normalize import normalize

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Noise-stripping
# ---------------------------------------------------------------------------

class TestNoiseStripping:
    def test_strips_top_level_id(self):
        result = normalize({"id": 42, "title": "x"})
        assert "id" not in result

    def test_strips_iteration(self):
        result = normalize({"iteration": 1712900000000, "title": "x"})
        assert "iteration" not in result

    def test_strips_version(self):
        result = normalize({"version": 17, "title": "x"})
        assert "version" not in result

    def test_preserves_uid(self):
        result = normalize({"uid": "abc123", "title": "x"})
        assert result["uid"] == "abc123"

    def test_preserves_schema_version(self):
        result = normalize({"schemaVersion": 36, "title": "x"})
        assert result["schemaVersion"] == 36

    def test_strips_panel_id(self):
        result = normalize({"panels": [{"id": 3, "title": "P", "type": "timeseries"}]})
        assert "id" not in result["panels"][0]

    def test_preserves_panel_title(self):
        result = normalize({"panels": [{"id": 3, "title": "My Panel", "type": "timeseries"}]})
        assert result["panels"][0]["title"] == "My Panel"


# ---------------------------------------------------------------------------
# Key ordering
# ---------------------------------------------------------------------------

class TestKeyOrdering:
    def test_top_level_keys_are_sorted(self):
        result = normalize({"timezone": "utc", "title": "x", "refresh": "5s"})
        assert list(result.keys()) == sorted(result.keys())

    def test_nested_keys_are_sorted(self):
        result = normalize({
            "panels": [{"type": "stat", "title": "P", "gridPos": {"w": 6, "h": 4, "x": 0, "y": 0}}]
        })
        panel = result["panels"][0]
        assert list(panel.keys()) == sorted(panel.keys())
        assert list(panel["gridPos"].keys()) == sorted(panel["gridPos"].keys())


# ---------------------------------------------------------------------------
# Panel ordering
# ---------------------------------------------------------------------------

class TestPanelOrdering:
    def test_panels_sorted_by_y_then_x(self):
        result = normalize({
            "panels": [
                {"id": 3, "title": "Error Rate",   "type": "ts", "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8}},
                {"id": 1, "title": "Request Rate", "type": "ts", "gridPos": {"x": 0,  "y": 0, "w": 12, "h": 8}},
            ]
        })
        titles = [p["title"] for p in result["panels"]]
        assert titles == ["Request Rate", "Error Rate"]

    def test_panels_same_position_sorted_by_title(self):
        result = normalize({
            "panels": [
                {"id": 2, "title": "Zebra", "type": "ts", "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4}},
                {"id": 1, "title": "Alpha", "type": "ts", "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4}},
            ]
        })
        titles = [p["title"] for p in result["panels"]]
        assert titles == ["Alpha", "Zebra"]


# ---------------------------------------------------------------------------
# Target (query) ordering
# ---------------------------------------------------------------------------

class TestTargetOrdering:
    def test_targets_sorted_by_refid(self):
        result = normalize({
            "panels": [{
                "id": 1, "title": "P", "type": "ts",
                "targets": [
                    {"refId": "C", "expr": "metric_c"},
                    {"refId": "A", "expr": "metric_a"},
                    {"refId": "B", "expr": "metric_b"},
                ]
            }]
        })
        refs = [t["refId"] for t in result["panels"][0]["targets"]]
        assert refs == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Template variable ordering
# ---------------------------------------------------------------------------

class TestTemplatingOrdering:
    def test_template_variables_sorted_by_name(self):
        result = normalize({
            "templating": {
                "list": [
                    {"name": "namespace", "type": "query"},
                    {"name": "env",       "type": "custom"},
                ]
            }
        })
        names = [v["name"] for v in result["templating"]["list"]]
        assert names == ["env", "namespace"]

    def test_missing_templating_is_tolerated(self):
        result = normalize({"title": "x"})
        assert "templating" not in result


# ---------------------------------------------------------------------------
# Annotation ordering
# ---------------------------------------------------------------------------

class TestAnnotationOrdering:
    def test_annotations_sorted_by_name(self):
        result = normalize({
            "annotations": {
                "list": [
                    {"name": "Deployments", "enable": True},
                    {"name": "Alerts",      "enable": False},
                ]
            }
        })
        names = [a["name"] for a in result["annotations"]["list"]]
        assert names == ["Alerts", "Deployments"]


# ---------------------------------------------------------------------------
# Nested (row) panels
# ---------------------------------------------------------------------------

class TestNestedPanels:
    def test_nested_panels_strip_id(self):
        result = normalize(load("with_row.json"))
        row = result["panels"][0]
        for nested in row["panels"]:
            assert "id" not in nested

    def test_nested_panels_sorted_by_position(self):
        result = normalize(load("with_row.json"))
        row = result["panels"][0]
        titles = [p["title"] for p in row["panels"]]
        assert titles == ["Nested A", "Nested B"]


# ---------------------------------------------------------------------------
# Full fixture round-trip
# ---------------------------------------------------------------------------

class TestFixtureRoundTrip:
    def test_messy_fixture_is_idempotent(self):
        """Normalizing twice should produce the same output."""
        first  = normalize(load("messy.json"))
        second = normalize(first)
        assert first == second

    def test_messy_fixture_strips_all_noise(self):
        result = normalize(load("messy.json"))
        assert "id"        not in result
        assert "iteration" not in result
        assert "version"   not in result

    def test_messy_fixture_panel_order(self):
        result = normalize(load("messy.json"))
        titles = [p["title"] for p in result["panels"]]
        assert titles == ["Request Rate", "Error Rate"]

    def test_messy_fixture_target_order(self):
        result = normalize(load("messy.json"))
        error_panel = next(p for p in result["panels"] if p["title"] == "Error Rate")
        refs = [t["refId"] for t in error_panel["targets"]]
        assert refs == ["A", "B"]

    def test_messy_fixture_variable_order(self):
        result = normalize(load("messy.json"))
        names = [v["name"] for v in result["templating"]["list"]]
        assert names == ["env", "namespace"]

    def test_messy_fixture_annotation_order(self):
        result = normalize(load("messy.json"))
        names = [a["name"] for a in result["annotations"]["list"]]
        assert names == ["Alerts", "Deployments"]
