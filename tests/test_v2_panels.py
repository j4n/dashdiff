"""Panel list and change classification for v2 dashboards."""

from v2_helpers import auto_grid, element, grid, grid_item, rows, v2_dashboard

from dashdiff.cli import detail_panel_changes
from dashdiff.grid import GridPanel, PanelChange, extract_panels
from dashdiff.v2_diff import classify_v2_changes


def dash(title="CPU", expr_ids=("A",), x=0, row="Row", name="panel-1"):
    return v2_dashboard(
        elements={name: element(title, *expr_ids)},
        layout=rows((row, grid(grid_item(name, x, 0)))),
    )


class TestExtractPanels:
    def test_grid_item_becomes_grid_panel(self):
        panels = extract_panels(dash(x=6))
        assert panels == [GridPanel("CPU", "timeseries", 6, 0, 12, 4, ("A: A",))]

    def test_auto_grid_panel_is_listed(self):
        d = v2_dashboard(
            elements={"panel-1": element("CPU")},
            layout=rows(("R", auto_grid("panel-1"))),
        )
        assert [p.title for p in extract_panels(d)] == ["CPU"]

    def test_unplaced_element_is_still_listed(self):
        d = v2_dashboard(elements={"panel-1": element("CPU")}, layout={})
        assert [p.title for p in extract_panels(d)] == ["CPU"]


class TestClassify:
    def test_identical_is_unchanged(self):
        kinds = classify_v2_changes(dash(), dash())
        assert kinds == {"CPU": frozenset({PanelChange.UNCHANGED})}

    def test_query_change(self):
        kinds = classify_v2_changes(dash(), dash(expr_ids=("B",)))
        assert kinds["CPU"] == frozenset({PanelChange.MODIFIED_QUERY})

    def test_layout_change(self):
        kinds = classify_v2_changes(dash(), dash(x=12))
        assert kinds["CPU"] == frozenset({PanelChange.MODIFIED_LAYOUT})

    def test_moving_to_another_row_is_layout(self):
        kinds = classify_v2_changes(dash(), dash(row="Other"))
        assert kinds["CPU"] == frozenset({PanelChange.MODIFIED_LAYOUT})

    def test_retitle_is_title_change_under_both_titles(self):
        kinds = classify_v2_changes(dash(), dash(title="Load"))
        expected = frozenset({PanelChange.MODIFIED_TITLE})
        assert kinds == {"CPU": expected, "Load": expected}

    def test_added_and_removed_by_element_key(self):
        kinds = classify_v2_changes(dash(name="panel-1"), dash(name="panel-2"))
        assert kinds["CPU"] == frozenset({PanelChange.REMOVED, PanelChange.ADDED})


class TestDetail:
    def test_query_path_is_rooted_at_the_element(self):
        result = detail_panel_changes(dash(), dash(expr_ids=("B",)))
        paths = [c.path for c in result["CPU"]]
        assert paths and all(p.startswith("data.") for p in paths)

    def test_layout_path_has_layout_prefix(self):
        result = detail_panel_changes(dash(), dash(x=12))
        assert [c.path for c in result["CPU"]] == ["layout.x"]

    def test_unchanged_panel_absent(self):
        assert detail_panel_changes(dash(), dash()) == {}


def test_title_badge_text():
    from dashdiff.grid import _CHANGE_BADGE_TEXT

    assert _CHANGE_BADGE_TEXT[PanelChange.MODIFIED_TITLE] == "~title"
