"""
Tests for grafana_grid — the dashboard grid layout data model.

The grid engine converts a raw Grafana dashboard dict into a list of
GridPanel objects that carry everything needed to render the box model:
position, size, title, type, and a short summary of the panel's queries.

Run with:  python -m pytest tests/ -v
"""

import pytest
from dashdiff.grid import extract_panels, GridPanel, panel_queries


# ---------------------------------------------------------------------------
# GridPanel dataclass
# ---------------------------------------------------------------------------

class TestGridPanelDataclass:
    def test_has_required_fields(self):
        p = GridPanel(
            title="CPU Usage",
            panel_type="timeseries",
            x=0, y=0, w=12, h=8,
            queries=[],
        )
        assert p.title      == "CPU Usage"
        assert p.panel_type == "timeseries"
        assert p.x == 0
        assert p.y == 0
        assert p.w == 12
        assert p.h == 8
        assert p.queries    == []

    def test_queries_list(self):
        p = GridPanel("T", "stat", 0, 0, 6, 4, queries=["up", "down"])
        assert p.queries == ["up", "down"]


# ---------------------------------------------------------------------------
# panel_queries — extract human-readable query strings from a panel dict
# ---------------------------------------------------------------------------

class TestPanelQueries:
    def test_prometheus_expr(self):
        panel = {"targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}]}
        qs = panel_queries(panel)
        assert any("rate(http_requests_total[5m])" in q for q in qs)

    def test_multiple_targets(self):
        panel = {"targets": [
            {"refId": "A", "expr": "metric_a"},
            {"refId": "B", "expr": "metric_b"},
        ]}
        qs = panel_queries(panel)
        assert len(qs) == 2

    def test_refid_prefix_in_output(self):
        panel = {"targets": [{"refId": "A", "expr": "up"}]}
        qs = panel_queries(panel)
        assert any("A" in q for q in qs)

    def test_rawSql_target(self):
        panel = {"targets": [{"refId": "A", "rawSql": "SELECT * FROM metrics"}]}
        qs = panel_queries(panel)
        assert any("SELECT" in q for q in qs)

    def test_target_with_no_query_field(self):
        # Should not raise; unknown target types return a placeholder
        panel = {"targets": [{"refId": "A"}]}
        qs = panel_queries(panel)
        assert len(qs) == 1

    def test_no_targets(self):
        panel = {}
        qs = panel_queries(panel)
        assert qs == []

    def test_row_panel_no_queries(self):
        panel = {"type": "row", "targets": []}
        qs = panel_queries(panel)
        assert qs == []


# ---------------------------------------------------------------------------
# extract_panels — convert a dashboard dict to a flat list of GridPanels
# ---------------------------------------------------------------------------

class TestExtractPanels:
    SIMPLE = {
        "panels": [
            {
                "id": 1, "title": "Request Rate", "type": "timeseries",
                "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
                "targets": [{"refId": "A", "expr": "rate(http_requests_total[5m])"}],
            },
            {
                "id": 2, "title": "Error Rate", "type": "timeseries",
                "gridPos": {"x": 12, "y": 0, "w": 12, "h": 8},
                "targets": [{"refId": "A", "expr": "rate(errors_total[5m])"}],
            },
        ]
    }

    def test_returns_list_of_grid_panels(self):
        result = extract_panels(self.SIMPLE)
        assert isinstance(result, list)
        assert all(isinstance(p, GridPanel) for p in result)

    def test_panel_count(self):
        result = extract_panels(self.SIMPLE)
        assert len(result) == 2

    def test_panel_positions(self):
        result = extract_panels(self.SIMPLE)
        by_title = {p.title: p for p in result}
        assert by_title["Request Rate"].x == 0
        assert by_title["Request Rate"].y == 0
        assert by_title["Error Rate"].x   == 12
        assert by_title["Error Rate"].y   == 0

    def test_panel_sizes(self):
        result = extract_panels(self.SIMPLE)
        for p in result:
            assert p.w == 12
            assert p.h == 8

    def test_panel_types(self):
        result = extract_panels(self.SIMPLE)
        assert all(p.panel_type == "timeseries" for p in result)

    def test_queries_extracted(self):
        result = extract_panels(self.SIMPLE)
        by_title = {p.title: p for p in result}
        assert any("http_requests_total" in q for q in by_title["Request Rate"].queries)

    def test_empty_dashboard(self):
        assert extract_panels({}) == []

    def test_no_panels_key(self):
        assert extract_panels({"title": "x"}) == []


class TestExtractPanelsRowUnwrapping:
    """Row panels should be included as rows; their children extracted too."""

    ROW_DASHBOARD = {
        "panels": [
            {
                "id": 10, "title": "My Row", "type": "row",
                "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1},
                "panels": [
                    {
                        "id": 11, "title": "Nested A", "type": "stat",
                        "gridPos": {"x": 0, "y": 1, "w": 12, "h": 4},
                        "targets": [{"refId": "A", "expr": "up"}],
                    },
                    {
                        "id": 12, "title": "Nested B", "type": "stat",
                        "gridPos": {"x": 12, "y": 1, "w": 12, "h": 4},
                        "targets": [{"refId": "A", "expr": "down"}],
                    },
                ],
            }
        ]
    }

    def test_row_panel_included(self):
        result = extract_panels(self.ROW_DASHBOARD)
        titles = [p.title for p in result]
        assert "My Row" in titles

    def test_nested_panels_included(self):
        result = extract_panels(self.ROW_DASHBOARD)
        titles = [p.title for p in result]
        assert "Nested A" in titles
        assert "Nested B" in titles

    def test_total_panel_count(self):
        result = extract_panels(self.ROW_DASHBOARD)
        assert len(result) == 3  # row + 2 children

    def test_nested_panel_positions(self):
        result = extract_panels(self.ROW_DASHBOARD)
        by_title = {p.title: p for p in result}
        assert by_title["Nested A"].x == 0
        assert by_title["Nested B"].x == 12


# ---------------------------------------------------------------------------
# Grid dimensions
# ---------------------------------------------------------------------------

class TestGridDimensions:
    def test_grid_width_is_24(self):
        """Grafana uses a 24-column grid."""
        from dashdiff.grid import GRID_COLUMNS
        assert GRID_COLUMNS == 24

    def test_panels_fit_within_grid(self):
        dashboard = {
            "panels": [
                {"id": 1, "title": "P", "type": "stat",
                 "gridPos": {"x": 0, "y": 0, "w": 24, "h": 4}, "targets": []},
            ]
        }
        result = extract_panels(dashboard)
        assert result[0].x + result[0].w <= 24
