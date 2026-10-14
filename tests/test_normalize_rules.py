"""normalize() rules for v1 dashboards, one table row per rule."""

import pytest

from dashdiff.normalize import normalize


def stat(**extra):
    return {"title": "P", "type": "stat", **extra}


def names(items, key):
    return [item[key] for item in items]


# (id, dashboard, how to read the result, lenient order, strict order)
SORTED_ONLY_WHEN_LENIENT = [
    ("tags", {"tags": ["service", "prod", "alpha"]}, lambda d: d["tags"],
     ["alpha", "prod", "service"], ["service", "prod", "alpha"]),
    ("refresh_intervals",
     {"timepicker": {"refresh_intervals": ["5m", "1m"]}},
     lambda d: d["timepicker"]["refresh_intervals"], ["1m", "5m"], ["5m", "1m"]),
    ("quick_ranges",
     {"timepicker": {"quick_ranges": [{"display": "b"}, {"display": "a"}]}},
     lambda d: names(d["timepicker"]["quick_ranges"], "display"), ["a", "b"], ["b", "a"]),
    ("variable_options",
     {"templating": {"list": [{"name": "env", "options": [{"value": "b"}, {"value": "a"}]}]}},
     lambda d: names(d["templating"]["list"][0]["options"], "value"), ["a", "b"], ["b", "a"]),
]  # fmt: skip

SORTED_BY_IDENTITY = [
    ("panels by y then x",
     {"panels": [stat(title="C", gridPos={"x": 0, "y": 8}),
                 stat(title="B", gridPos={"x": 12, "y": 0}),
                 stat(title="A", gridPos={"x": 0, "y": 0})]},
     lambda d: names(d["panels"], "title"), ["A", "B", "C"]),
    ("panels at one position by title",
     {"panels": [stat(title="B", gridPos={"x": 0, "y": 0}),
                 stat(title="A", gridPos={"x": 0, "y": 0})]},
     lambda d: names(d["panels"], "title"), ["A", "B"]),
    ("nested row panels",
     {"panels": [{"title": "R", "type": "row", "panels": [
         stat(title="B", gridPos={"x": 0, "y": 8}), stat(title="A", gridPos={"x": 0, "y": 0})]}]},
     lambda d: names(d["panels"][0]["panels"], "title"), ["A", "B"]),
    ("targets by refId",
     {"panels": [stat(targets=[{"refId": "B"}, {"refId": "A"}])]},
     lambda d: names(d["panels"][0]["targets"], "refId"), ["A", "B"]),
    ("templating by name",
     {"templating": {"list": [{"name": "b"}, {"name": "a"}]}},
     lambda d: names(d["templating"]["list"], "name"), ["a", "b"]),
    ("annotations by name",
     {"annotations": {"list": [{"name": "b"}, {"name": "a"}]}},
     lambda d: names(d["annotations"]["list"], "name"), ["a", "b"]),
]  # fmt: skip

NEVER_SORTED = [
    ("transformations", {"panels": [stat(transformations=[{"id": "merge"}, {"id": "reduce"}])]},
     lambda d: names(d["panels"][0]["transformations"], "id"), ["merge", "reduce"]),
    ("overrides", {"panels": [stat(overrides=[{"matcher": {"options": "cpu"}}, {"matcher": {"options": "mem"}}])]},
     lambda d: [o["matcher"]["options"] for o in d["panels"][0]["overrides"]], ["cpu", "mem"]),
    ("links", {"links": [{"title": "Runbook"}, {"title": "Alerts"}]},
     lambda d: names(d["links"], "title"), ["Runbook", "Alerts"]),
]  # fmt: skip


@pytest.mark.parametrize(
    ("dashboard", "read", "lenient", "strict"),
    [row[1:] for row in SORTED_ONLY_WHEN_LENIENT],
    ids=[row[0] for row in SORTED_ONLY_WHEN_LENIENT],
)
def test_set_like_arrays_sort_only_in_lenient_mode(dashboard, read, lenient, strict):
    assert read(normalize(dashboard, strict=False)) == lenient
    assert read(normalize(dashboard, strict=True)) == strict


@pytest.mark.parametrize(
    ("dashboard", "read", "expected"),
    [row[1:] for row in SORTED_BY_IDENTITY],
    ids=[row[0] for row in SORTED_BY_IDENTITY],
)
def test_identified_arrays_sort_only_in_lenient_mode(dashboard, read, expected):
    assert read(normalize(dashboard, strict=False)) == expected
    assert read(normalize(dashboard, strict=True)) == read(dashboard)


@pytest.mark.parametrize(
    ("dashboard", "read", "expected"),
    [row[1:] for row in NEVER_SORTED],
    ids=[row[0] for row in NEVER_SORTED],
)
def test_order_significant_arrays_keep_document_order(dashboard, read, expected):
    assert read(normalize(dashboard, strict=False)) == expected
    assert read(normalize(dashboard, strict=True)) == expected


@pytest.mark.parametrize("strict", [False, True])
def test_noise_is_stripped_and_identity_kept(strict):
    dashboard = {
        "id": 5, "iteration": 1700, "version": 9, "uid": "abc", "schemaVersion": 39,
        "panels": [{"id": 1, "title": "P", "type": "stat"},
                   {"id": 2, "title": "R", "type": "row",
                    "panels": [{"id": 3, "title": "N", "type": "stat"}]}],
    }  # fmt: skip
    result = normalize(dashboard, strict=strict)
    assert result["uid"] == "abc" and result["schemaVersion"] == 39
    assert not {"id", "iteration", "version"} & result.keys()
    flat = result["panels"] + result["panels"][1]["panels"]
    assert all("id" not in p for p in flat)


@pytest.mark.parametrize("strict", [False, True])
def test_keys_are_sorted_at_every_depth(strict):
    result = normalize({"z": 1, "a": {"y": 1, "b": 2}}, strict=strict)
    assert list(result) == ["a", "z"]
    assert list(result["a"]) == ["b", "y"]


def test_missing_optional_sections_are_not_invented():
    assert normalize({"title": "x"}) == {"title": "x"}


NULLED = {
    "title": "x",
    "description": None,
    "panels": [stat(unit=None, n=0, s="", f=False)],
}


def test_lenient_strips_null_keys_at_any_depth_but_keeps_falsy_values():
    panel = normalize(NULLED)["panels"][0]
    assert "description" not in normalize(NULLED)
    assert "unit" not in panel
    assert (panel["n"], panel["s"], panel["f"]) == (0, "", False)


def test_lenient_treats_null_and_absent_as_equal_but_strict_does_not():
    absent = {"title": "x", "panels": [stat()]}
    nulled = {"title": "x", "panels": [stat(unit=None)]}
    assert normalize(nulled) == normalize(absent)
    assert normalize(nulled, strict=True) != normalize(absent, strict=True)
    assert normalize(nulled, strict=True)["panels"][0]["unit"] is None


def test_null_elements_inside_arrays_are_kept():
    assert normalize({"panels": [stat(xs=[None, 1])]})["panels"][0]["xs"] == [None, 1]


@pytest.mark.parametrize("strict", [False, True])
def test_normalize_is_idempotent(strict):
    messy = {
        "id": 1, "tags": ["b", "a"], "description": None,
        "panels": [stat(title="B", gridPos={"x": 0, "y": 8}, targets=[{"refId": "B"}, {"refId": "A"}]),
                   stat(title="A", gridPos={"x": 0, "y": 0})],
        "templating": {"list": [{"name": "b", "options": [{"value": "z"}, {"value": "y"}]}, {"name": "a"}]},
    }  # fmt: skip
    once = normalize(messy, strict=strict)
    assert normalize(once, strict=strict) == once
