"""
Tests for lenient (default) vs strict normalization modes.

Lenient mode sorts arrays that are functionally set-like (tags, variable options,
refresh intervals, quick_ranges) so that cosmetic reorderings produce no diff.

Strict mode preserves document order for those arrays, so even a cosmetic
reordering is visible — useful for auditing or enforcing a house style.

Run with:  python -m pytest tests/ -v
"""

import pytest
from dashdiff.normalize import normalize


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lenient(d):
    return normalize(d, strict=False)


def strict(d):
    return normalize(d, strict=True)


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

class TestTags:
    DASHBOARD = {"tags": ["service", "prod", "alpha"]}

    def test_lenient_sorts_tags(self):
        result = lenient(self.DASHBOARD)
        assert result["tags"] == ["alpha", "prod", "service"]

    def test_strict_preserves_tag_order(self):
        result = strict(self.DASHBOARD)
        assert result["tags"] == ["service", "prod", "alpha"]

    def test_lenient_tags_idempotent(self):
        first  = lenient(self.DASHBOARD)
        second = lenient(first)
        assert first["tags"] == second["tags"]


# ---------------------------------------------------------------------------
# templating.list[*].options
# ---------------------------------------------------------------------------

class TestVariableOptions:
    DASHBOARD = {
        "templating": {
            "list": [{
                "name": "env",
                "type": "custom",
                "options": [
                    {"text": "Production", "value": "prod"},
                    {"text": "Staging",    "value": "staging"},
                    {"text": "Dev",        "value": "dev"},
                ]
            }]
        }
    }

    def test_lenient_sorts_options_by_value(self):
        result = lenient(self.DASHBOARD)
        values = [o["value"] for o in result["templating"]["list"][0]["options"]]
        assert values == sorted(values)

    def test_strict_preserves_option_order(self):
        result = strict(self.DASHBOARD)
        values = [o["value"] for o in result["templating"]["list"][0]["options"]]
        assert values == ["prod", "staging", "dev"]


# ---------------------------------------------------------------------------
# timepicker.refresh_intervals
# ---------------------------------------------------------------------------

class TestRefreshIntervals:
    DASHBOARD = {
        "timepicker": {
            "refresh_intervals": ["1m", "5s", "30s", "1h", "10s"]
        }
    }

    def test_lenient_sorts_refresh_intervals(self):
        result = lenient(self.DASHBOARD)
        intervals = result["timepicker"]["refresh_intervals"]
        assert intervals == sorted(intervals)

    def test_strict_preserves_refresh_interval_order(self):
        result = strict(self.DASHBOARD)
        intervals = result["timepicker"]["refresh_intervals"]
        assert intervals == ["1m", "5s", "30s", "1h", "10s"]


# ---------------------------------------------------------------------------
# timepicker.quick_ranges
# ---------------------------------------------------------------------------

class TestQuickRanges:
    DASHBOARD = {
        "timepicker": {
            "quick_ranges": [
                {"display": "Last 7 days",  "from": "now-7d",  "to": "now"},
                {"display": "Last 6 hours", "from": "now-6h",  "to": "now"},
                {"display": "Last 1 hour",  "from": "now-1h",  "to": "now"},
            ]
        }
    }

    def test_lenient_sorts_quick_ranges_by_display(self):
        result = lenient(self.DASHBOARD)
        displays = [r["display"] for r in result["timepicker"]["quick_ranges"]]
        assert displays == sorted(displays)

    def test_strict_preserves_quick_range_order(self):
        result = strict(self.DASHBOARD)
        displays = [r["display"] for r in result["timepicker"]["quick_ranges"]]
        assert displays == ["Last 7 days", "Last 6 hours", "Last 1 hour"]


# ---------------------------------------------------------------------------
# Order-significant arrays: never sorted in either mode
# ---------------------------------------------------------------------------

class TestOrderSignificantArrays:
    TRANSFORMATIONS = [
        {"id": "merge",  "options": {}},
        {"id": "reduce", "options": {"reducers": ["sum"]}},
    ]
    OVERRIDES = [
        {"matcher": {"id": "byName", "options": "cpu"}, "properties": [{"id": "color"}]},
        {"matcher": {"id": "byName", "options": "mem"}, "properties": [{"id": "unit"}]},
    ]
    LINKS = [
        {"title": "Runbook", "url": "https://wiki/runbook"},
        {"title": "Alerts",  "url": "https://alerts/"},
    ]

    def _panel_with(self, **kwargs):
        return {"panels": [{"title": "P", "type": "stat", **kwargs}]}

    def test_lenient_preserves_transformation_order(self):
        result = lenient(self._panel_with(transformations=self.TRANSFORMATIONS))
        ids = [t["id"] for t in result["panels"][0]["transformations"]]
        assert ids == ["merge", "reduce"]

    def test_strict_preserves_transformation_order(self):
        result = strict(self._panel_with(transformations=self.TRANSFORMATIONS))
        ids = [t["id"] for t in result["panels"][0]["transformations"]]
        assert ids == ["merge", "reduce"]

    def test_lenient_preserves_override_order(self):
        result = lenient(self._panel_with(overrides=self.OVERRIDES))
        names = [o["matcher"]["options"] for o in result["panels"][0]["overrides"]]
        assert names == ["cpu", "mem"]

    def test_strict_preserves_override_order(self):
        result = strict(self._panel_with(overrides=self.OVERRIDES))
        names = [o["matcher"]["options"] for o in result["panels"][0]["overrides"]]
        assert names == ["cpu", "mem"]

    def test_lenient_preserves_links_order(self):
        result = lenient({"links": self.LINKS})
        titles = [l["title"] for l in result["links"]]
        assert titles == ["Runbook", "Alerts"]

    def test_strict_preserves_links_order(self):
        result = strict({"links": self.LINKS})
        titles = [l["title"] for l in result["links"]]
        assert titles == ["Runbook", "Alerts"]


# ---------------------------------------------------------------------------
# Strict mode still strips noise fields
# ---------------------------------------------------------------------------

class TestStrictStillStripsNoise:
    def test_strict_strips_id(self):
        assert "id" not in strict({"id": 1, "title": "x"})

    def test_strict_strips_iteration(self):
        assert "iteration" not in strict({"iteration": 999, "title": "x"})

    def test_strict_strips_version(self):
        assert "version" not in strict({"version": 5, "title": "x"})

    def test_strict_strips_panel_id(self):
        result = strict({"panels": [{"id": 3, "title": "P", "type": "ts"}]})
        assert "id" not in result["panels"][0]

    def test_strict_still_sorts_keys(self):
        result = strict({"timezone": "utc", "title": "x", "refresh": "5s"})
        assert list(result.keys()) == sorted(result.keys())


# ---------------------------------------------------------------------------
# Two-version diff: tags noise gone in lenient, visible in strict
# ---------------------------------------------------------------------------

class TestTagsInTwoVersionDiff:
    V1 = {"uid": "x", "tags": ["service", "prod"]}
    V2 = {"uid": "x", "tags": ["prod", "service"]}

    def test_lenient_hides_tag_reorder(self):
        assert lenient(self.V1)["tags"] == lenient(self.V2)["tags"]

    def test_strict_exposes_tag_reorder(self):
        assert strict(self.V1)["tags"] != strict(self.V2)["tags"]
