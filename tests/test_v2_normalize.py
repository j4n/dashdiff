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


# ---------------------------------------------------------------------------
# Sorting: lenient sorts set-like lists, strict keeps document order
# ---------------------------------------------------------------------------


def ref(name):
    return {"kind": "ElementReference", "name": name}


def grid_item(name, x, y):
    return {
        "kind": "GridLayoutItem",
        "spec": {"x": x, "y": y, "width": 12, "height": 4, "element": ref(name)},
    }


def grid(*items):
    return {"kind": "GridLayout", "spec": {"items": list(items)}}


def auto_grid(*names):
    items = [{"kind": "AutoGridLayoutItem", "spec": {"element": ref(n)}} for n in names]
    return {"kind": "AutoGridLayout", "spec": {"maxColumnCount": 1, "items": items}}


def rows(*row_specs):
    """Each row spec is (title, layout)."""
    return {
        "kind": "RowsLayout",
        "spec": {
            "rows": [
                {"kind": "RowsLayoutRow", "spec": {"title": t, "layout": layout}}
                for t, layout in row_specs
            ]
        },
    }


def element(title, *ref_ids):
    queries = [
        {"kind": "PanelQuery", "spec": {"refId": r, "query": {"spec": {"expr": r}}}}
        for r in ref_ids
    ]
    return {
        "kind": "Panel",
        "spec": {
            "title": title,
            "vizConfig": {"kind": "timeseries", "spec": {}},
            "data": {"kind": "QueryGroup", "spec": {"queries": queries}},
        },
    }


class TestQueries:
    def _dash(self):
        return v2_dashboard(elements={"panel-1": element("P", "B", "A")})

    def _ref_ids(self, result):
        queries = result["spec"]["elements"]["panel-1"]["spec"]["data"]["spec"][
            "queries"
        ]
        return [q["spec"]["refId"] for q in queries]

    def test_lenient_sorts_queries_by_ref_id(self):
        assert self._ref_ids(lenient(self._dash())) == ["A", "B"]

    def test_strict_preserves_query_order(self):
        assert self._ref_ids(strict(self._dash())) == ["B", "A"]


class TestLayoutOrder:
    def _names(self, items):
        return [i["spec"]["element"]["name"] for i in items]

    def _row_items(self, result, index=0):
        row = result["spec"]["layout"]["spec"]["rows"][index]
        return row["spec"]["layout"]["spec"]["items"]

    def _dash(self, *row_specs):
        return v2_dashboard(layout=rows(*row_specs))

    def test_lenient_sorts_grid_items_by_position(self):
        items = [grid_item("b", 0, 8), grid_item("c", 12, 0), grid_item("a", 0, 0)]
        d = self._dash(("R", grid(*items)))
        assert self._names(self._row_items(lenient(d))) == ["a", "c", "b"]

    def test_strict_preserves_grid_item_order(self):
        items = [grid_item("b", 0, 8), grid_item("c", 12, 0), grid_item("a", 0, 0)]
        d = self._dash(("R", grid(*items)))
        assert self._names(self._row_items(strict(d))) == ["b", "c", "a"]

    def test_grid_item_ties_break_on_element_name(self):
        d = self._dash(("R", grid(grid_item("z", 0, 0), grid_item("y", 0, 0))))
        assert self._names(self._row_items(lenient(d))) == ["y", "z"]

    def test_auto_grid_items_are_never_sorted(self):
        d = self._dash(("R", auto_grid("b", "a")))
        assert self._names(self._row_items(lenient(d))) == ["b", "a"]

    def test_rows_are_never_sorted(self):
        d = self._dash(("Z", grid()), ("A", grid()))
        titles = [
            r["spec"]["title"] for r in lenient(d)["spec"]["layout"]["spec"]["rows"]
        ]
        assert titles == ["Z", "A"]

    def test_top_level_grid_items_are_sorted_too(self):
        d = v2_dashboard(layout=grid(grid_item("b", 0, 8), grid_item("a", 0, 0)))
        items = lenient(d)["spec"]["layout"]["spec"]["items"]
        assert self._names(items) == ["a", "b"]

    def test_grid_layout_row_children_are_sorted(self):
        row = {
            "kind": "GridLayoutRow",
            "spec": {
                "title": "R",
                "y": 0,
                "elements": [grid_item("b", 0, 8), grid_item("a", 0, 0)],
            },
        }
        d = v2_dashboard(layout=grid(row))
        children = lenient(d)["spec"]["layout"]["spec"]["items"][0]["spec"]["elements"]
        assert self._names(children) == ["a", "b"]


class TestVariablesAnnotationsTags:
    VARS = [
        {"kind": "CustomVariable", "spec": {"name": "b", "options": [
            {"text": "z", "value": "z"}, {"text": "a", "value": "a"}]}},
        {"kind": "QueryVariable", "spec": {"name": "a"}},
    ]  # fmt: skip
    ANNOTATIONS = [
        {"kind": "AnnotationQuery", "spec": {"name": "b"}},
        {"kind": "AnnotationQuery", "spec": {"name": "a"}},
    ]

    def test_lenient_sorts_variables_by_name(self):
        out = lenient(v2_dashboard(variables=self.VARS))
        assert [v["spec"]["name"] for v in out["spec"]["variables"]] == ["a", "b"]

    def test_strict_preserves_variable_order(self):
        out = strict(v2_dashboard(variables=self.VARS))
        assert [v["spec"]["name"] for v in out["spec"]["variables"]] == ["b", "a"]

    def test_lenient_sorts_variable_options_by_value(self):
        out = lenient(v2_dashboard(variables=self.VARS))
        custom = next(v for v in out["spec"]["variables"] if v["spec"]["name"] == "b")
        assert [o["value"] for o in custom["spec"]["options"]] == ["a", "z"]

    def test_strict_preserves_variable_option_order(self):
        out = strict(v2_dashboard(variables=self.VARS))
        custom = next(v for v in out["spec"]["variables"] if v["spec"]["name"] == "b")
        assert [o["value"] for o in custom["spec"]["options"]] == ["z", "a"]

    def test_lenient_sorts_annotations_by_name(self):
        out = lenient(v2_dashboard(annotations=self.ANNOTATIONS))
        assert [a["spec"]["name"] for a in out["spec"]["annotations"]] == ["a", "b"]

    def test_strict_preserves_annotation_order(self):
        out = strict(v2_dashboard(annotations=self.ANNOTATIONS))
        assert [a["spec"]["name"] for a in out["spec"]["annotations"]] == ["b", "a"]

    def test_lenient_sorts_tags(self):
        assert lenient(v2_dashboard(tags=["b", "a"]))["spec"]["tags"] == ["a", "b"]

    def test_strict_preserves_tag_order(self):
        assert strict(v2_dashboard(tags=["b", "a"]))["spec"]["tags"] == ["b", "a"]


class TestOrderSignificant:
    def test_transformations_keep_order_in_both_modes(self):
        el = element("P", "A")
        el["spec"]["data"]["spec"]["transformations"] = [{"id": "merge"}, {"id": "a"}]
        for mode in (lenient, strict):
            out = mode(v2_dashboard(elements={"panel-1": el}))
            transformations = out["spec"]["elements"]["panel-1"]["spec"]["data"][
                "spec"
            ]["transformations"]
            assert [t["id"] for t in transformations] == ["merge", "a"]


class TestNulls:
    def test_lenient_strips_null_keys(self):
        out = lenient(v2_dashboard(description=None))
        assert "description" not in out["spec"]

    def test_strict_preserves_null_keys(self):
        out = strict(v2_dashboard(description=None))
        assert out["spec"]["description"] is None
