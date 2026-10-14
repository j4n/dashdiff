"""
Tests for normalising Grafana v2 dashboards (dashboard.grafana.app/v2).

A v2 dashboard keeps panel content in ``spec.elements`` (a map keyed by an
element name) and placement in ``spec.layout``.  Lenient mode sorts the
set-like lists, strict mode keeps document order, as in DESIGN.md.
"""

import copy

import pytest
from v2_helpers import auto_grid, element, grid, grid_item, rows, v2_dashboard

from dashdiff.normalize import normalize
from dashdiff.v2 import is_v2


def lenient(d):
    return normalize(d, strict=False)


def strict(d):
    return normalize(d, strict=True)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dashboard", "expected"),
    [
        (v2_dashboard(), True),
        ({"title": "T", "elements": {}, "layout": {"kind": "GridLayout"}}, True),
        ({"title": "T", "panels": [], "schemaVersion": 39}, False),
        ({"apiVersion": "dashboard.grafana.app/v1", "spec": {}}, False),
    ],
    ids=["envelope", "bare spec", "legacy", "v1 envelope"],
)
def test_is_v2(dashboard, expected):
    assert is_v2(dashboard) is expected


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

    def test_strips_server_noise_and_keeps_the_rest(self):
        meta = lenient(self._with(self.NOISY))["metadata"]
        assert meta == {
            "name": "uid-1",
            "labels": {"team": "ops"},
            "annotations": {"grafana.app/folder": "folder-a"},
        }

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


def _item_names(items):
    return [i["spec"]["element"]["name"] for i in items]


def _row_items(result):
    return result["spec"]["layout"]["spec"]["rows"][0]["spec"]["layout"]["spec"][
        "items"
    ]


def _queries(result):
    return result["spec"]["elements"]["panel-1"]["spec"]["data"]["spec"]["queries"]


def _grid_row_children(result):
    return result["spec"]["layout"]["spec"]["items"][0]["spec"]["elements"]


def _custom_options(result):
    custom = next(v for v in result["spec"]["variables"] if v["spec"]["name"] == "b")
    return [o["value"] for o in custom["spec"]["options"]]


def _spec_names(key):
    return lambda result: [i["spec"]["name"] for i in result["spec"][key]]


GRID_ITEMS = [grid_item("b", 0, 8), grid_item("c", 12, 0), grid_item("a", 0, 0)]
VARS = [
    {"kind": "CustomVariable", "spec": {"name": "b", "options": [
        {"text": "z", "value": "z"}, {"text": "a", "value": "a"}]}},
    {"kind": "QueryVariable", "spec": {"name": "a"}},
]  # fmt: skip
ANNOTATIONS = [
    {"kind": "AnnotationQuery", "spec": {"name": "b"}},
    {"kind": "AnnotationQuery", "spec": {"name": "a"}},
]
GRID_ROW = {
    "kind": "GridLayoutRow",
    "spec": {
        "title": "R",
        "y": 0,
        "elements": [grid_item("b", 0, 8), grid_item("a", 0, 0)],
    },
}

# (id, dashboard, how to read the result, lenient order, strict order)
LENIENT_SORTS = [
    ("queries by refId", v2_dashboard(elements={"panel-1": element("P", "B", "A")}),
     lambda r: [q["spec"]["refId"] for q in _queries(r)], ["A", "B"], ["B", "A"]),
    ("grid items by position", v2_dashboard(layout=rows(("R", grid(*GRID_ITEMS)))),
     lambda r: _item_names(_row_items(r)), ["a", "c", "b"], ["b", "c", "a"]),
    ("grid item ties by element name",
     v2_dashboard(layout=rows(("R", grid(grid_item("z", 0, 0), grid_item("y", 0, 0))))),
     lambda r: _item_names(_row_items(r)), ["y", "z"], ["z", "y"]),
    ("top-level grid items", v2_dashboard(layout=grid(grid_item("b", 0, 8), grid_item("a", 0, 0))),
     lambda r: _item_names(r["spec"]["layout"]["spec"]["items"]), ["a", "b"], ["b", "a"]),
    ("grid layout row children", v2_dashboard(layout=grid(GRID_ROW)),
     lambda r: _item_names(_grid_row_children(r)), ["a", "b"], ["b", "a"]),
    ("variables by name", v2_dashboard(variables=VARS), _spec_names("variables"), ["a", "b"], ["b", "a"]),
    ("variable options by value", v2_dashboard(variables=VARS), _custom_options, ["a", "z"], ["z", "a"]),
    ("annotations by name", v2_dashboard(annotations=ANNOTATIONS), _spec_names("annotations"), ["a", "b"], ["b", "a"]),
    ("tags", v2_dashboard(tags=["b", "a"]), lambda r: r["spec"]["tags"], ["a", "b"], ["b", "a"]),
]  # fmt: skip

TRANSFORMED = element("P", "A")
TRANSFORMED["spec"]["data"]["spec"]["transformations"] = [{"id": "merge"}, {"id": "a"}]

NEVER_SORTED = [
    ("auto grid items", v2_dashboard(layout=rows(("R", auto_grid("b", "a")))),
     lambda r: _item_names(_row_items(r)), ["b", "a"]),
    ("rows", v2_dashboard(layout=rows(("Z", grid()), ("A", grid()))),
     lambda r: [x["spec"]["title"] for x in r["spec"]["layout"]["spec"]["rows"]], ["Z", "A"]),
    ("transformations", v2_dashboard(elements={"panel-1": TRANSFORMED}),
     lambda r: [t["id"] for t in r["spec"]["elements"]["panel-1"]["spec"]["data"]["spec"]["transformations"]],
     ["merge", "a"]),
]  # fmt: skip


@pytest.mark.parametrize(
    ("dashboard", "read", "lenient_order", "strict_order"),
    [row[1:] for row in LENIENT_SORTS],
    ids=[row[0] for row in LENIENT_SORTS],
)
def test_lenient_sorts_and_strict_keeps_document_order(
    dashboard, read, lenient_order, strict_order
):
    assert read(lenient(dashboard)) == lenient_order
    assert read(strict(dashboard)) == strict_order


@pytest.mark.parametrize(
    ("dashboard", "read", "expected"),
    [row[1:] for row in NEVER_SORTED],
    ids=[row[0] for row in NEVER_SORTED],
)
def test_order_significant_lists_keep_document_order(dashboard, read, expected):
    assert read(lenient(dashboard)) == expected
    assert read(strict(dashboard)) == expected


@pytest.mark.parametrize("key", ["variables", "annotations", "tags"])
def test_malformed_lists_pass_through_unsorted(key):
    dashboard = v2_dashboard(**{key: {"not": "a list"}})
    assert lenient(dashboard)["spec"][key] == {"not": "a list"}


def test_annotations_holding_only_noise_equal_absent_annotations():
    noisy = v2_dashboard()
    noisy["metadata"]["annotations"] = {"grafana.app/updatedBy": "user:1"}
    assert strict(noisy) == strict(v2_dashboard())


def test_lenient_strips_null_keys_and_strict_keeps_them():
    dashboard = v2_dashboard(description=None)
    assert "description" not in lenient(dashboard)["spec"]
    assert strict(dashboard)["spec"]["description"] is None


# ---------------------------------------------------------------------------
# export-label noise anywhere in the tree
# ---------------------------------------------------------------------------


class TestExportLabel:
    def _with_query_labels(self, labels):
        el = element("P", "A")
        query = el["spec"]["data"]["spec"]["queries"][0]["spec"]["query"]
        query["kind"] = "DataQuery"
        if labels is not None:
            query["labels"] = labels
        return v2_dashboard(elements={"panel-1": el})

    def _query(self, result):
        queries = result["spec"]["elements"]["panel-1"]["spec"]["data"]["spec"][
            "queries"
        ]
        return queries[0]["spec"]["query"]

    def test_strips_export_label_from_nested_query(self):
        d = self._with_query_labels({"grafana.app/export-label": "grafana-1"})
        for mode in (lenient, strict):
            assert "labels" not in self._query(mode(d))

    def test_label_only_dashboard_equals_one_without_labels(self):
        a = self._with_query_labels({"grafana.app/export-label": "grafana-1"})
        b = self._with_query_labels(None)
        assert strict(a) == strict(b)

    def test_keeps_other_labels(self):
        d = self._with_query_labels({"grafana.app/export-label": "g", "team": "ops"})
        assert self._query(strict(d))["labels"] == {"team": "ops"}

    def test_empty_labels_not_created_by_us_are_kept(self):
        d = self._with_query_labels({})
        assert self._query(strict(d))["labels"] == {}
