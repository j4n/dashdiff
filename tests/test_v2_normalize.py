"""
Tests for normalising Grafana v2 dashboards (dashboard.grafana.app/v2).

A v2 dashboard keeps panel content in ``spec.elements`` (a map keyed by an
element name) and placement in ``spec.layout``.  Lenient mode sorts the
set-like lists, strict mode keeps document order, as in DESIGN.md.
"""

import copy

from dashdiff.normalize import normalize
from dashdiff.v2 import is_v2


def lenient(d):
    return normalize(d, strict=False)


def strict(d):
    return normalize(d, strict=True)


def v2_dashboard(**spec):
    """Build a minimal v2 envelope; *spec* keys override the spec defaults."""
    return {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "uid-1"},
        "spec": {"title": "T", "elements": {}, "layout": {}, **spec},
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestIsV2:
    def test_envelope_is_v2(self):
        assert is_v2(v2_dashboard())

    def test_bare_spec_is_v2(self):
        assert is_v2({"title": "T", "elements": {}, "layout": {"kind": "GridLayout"}})

    def test_legacy_is_not_v2(self):
        assert not is_v2({"title": "T", "panels": [], "schemaVersion": 39})

    def test_v1_envelope_is_not_v2(self):
        assert not is_v2({"apiVersion": "dashboard.grafana.app/v1", "spec": {}})


# ---------------------------------------------------------------------------
# metadata noise
# ---------------------------------------------------------------------------


class TestMetadata:
    NOISY = {
        "name": "uid-1",
        "generation": 31,
        "resourceVersion": "123",
        "creationTimestamp": "2026-03-13T20:54:15Z",
        "uid": "k8s-uid",
        "managedFields": [{"manager": "x"}],
        "labels": {"grafana.app/export-label": "grafana-1", "team": "ops"},
        "annotations": {
            "grafana.app/updatedTimestamp": "2026-04-01T00:00:00Z",
            "grafana.app/updatedBy": "user:1",
            "grafana.app/createdBy": "user:1",
            "grafana.app/message": "save",
            "grafana.app/folder": "folder-a",
        },
    }

    def _with(self, metadata):
        d = v2_dashboard()
        d["metadata"] = metadata
        return d

    def test_strips_server_assigned_fields(self):
        meta = lenient(self._with(self.NOISY))["metadata"]
        for key in ("generation", "resourceVersion", "creationTimestamp", "uid"):
            assert key not in meta
        assert "managedFields" not in meta

    def test_strips_noise_annotations_and_labels(self):
        meta = strict(self._with(self.NOISY))["metadata"]
        assert meta["annotations"] == {"grafana.app/folder": "folder-a"}
        assert meta["labels"] == {"team": "ops"}

    def test_keeps_name(self):
        assert lenient(self._with(self.NOISY))["metadata"]["name"] == "uid-1"

    def test_dashboards_differing_only_in_noise_normalize_equal(self):
        a = self._with(self.NOISY)
        b = copy.deepcopy(a)
        b["metadata"]["generation"] = 32
        b["metadata"]["labels"] = {"team": "ops"}
        assert strict(a) == strict(b)

    def test_labels_holding_only_noise_equal_absent_labels(self):
        a = self._with({"name": "uid-1", "labels": {"grafana.app/export-label": "g"}})
        b = self._with({"name": "uid-1"})
        assert strict(a) == strict(b)

    def test_unknown_metadata_field_is_kept(self):
        d = self._with({"name": "uid-1", "somethingNew": 1})
        assert strict(d)["metadata"]["somethingNew"] == 1
