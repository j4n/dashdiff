"""visual and detail output for v2 dashboards, one block per layout section."""

import json

from v2_helpers import auto_grid, element, grid, grid_item, rows, v2_dashboard

from dashdiff.cli import main
from dashdiff.grid import GridPanel, auto_grid_panels
from dashdiff.v2 import v2_sections


def write(path, dashboard):
    path.write_text(json.dumps(dashboard), encoding="utf-8")
    return str(path)


def two_rows(second_layout=None, titles=("Alpha", "Beta")):
    return v2_dashboard(
        elements={"panel-1": element("CPU", "A"), "panel-2": element("Disk", "A")},
        layout=rows(
            (titles[0], grid(grid_item("panel-1", 0, 0))),
            (titles[1], second_layout or grid(grid_item("panel-2", 0, 0))),
        ),
    )


def run(tmp_path, capsys, command, before, after=None):
    args = [command, write(tmp_path / "a.json", before)]
    if after is not None:
        args.append(write(tmp_path / "b.json", after))
    main(args)
    return capsys.readouterr().out


class TestSections:
    def test_one_section_per_leaf_layout_with_row_path(self):
        sections = v2_sections(two_rows())
        assert [s.path for s in sections] == [("Alpha",), ("Beta",)]
        assert [s.kind for s in sections] == ["GridLayout", "GridLayout"]

    def test_auto_grid_flow_uses_column_count(self):
        node = auto_grid("a", "b", "c")
        node["spec"]["maxColumnCount"] = 2
        d = v2_dashboard(layout=rows(("R", node)))
        panels = [GridPanel(n, "stat", 0, 0, 24, 1) for n in "abc"]
        flowed = auto_grid_panels(v2_sections(d)[0], panels)
        positions = [(p.x, p.y, p.w) for p in flowed]
        assert positions == [(0, 0, 12), (12, 0, 12), (0, 4, 12)]


class TestVisual:
    def test_single_file_prints_row_titles_before_their_panels(self, tmp_path, capsys):
        out = run(tmp_path, capsys, "visual", two_rows())
        assert out.index("Alpha") < out.index("CPU") < out.index("Beta")
        assert out.index("Beta") < out.index("Disk")

    def test_rows_with_the_same_y_are_not_merged(self, tmp_path, capsys):
        after = two_rows()
        for el in after["spec"]["elements"].values():
            el["spec"]["data"]["spec"]["queries"][0]["spec"]["refId"] = "Z"
        out = run(tmp_path, capsys, "visual", two_rows(), after)
        assert out.index("CPU") < out.index("Beta") < out.index("Disk")

    def test_auto_grid_header_shows_settings(self, tmp_path, capsys):
        node = auto_grid("panel-2")
        node["spec"].update(columnWidthMode="standard", rowHeightMode="short")
        out = run(tmp_path, capsys, "visual", two_rows(node), two_rows(node))
        assert "auto grid: 1 column, width standard, height short" in out

    def test_settings_change_is_layout_on_the_row_header(self, tmp_path, capsys):
        before, after = auto_grid("panel-2"), auto_grid("panel-2")
        before["spec"]["maxColumnCount"] = 1
        after["spec"]["maxColumnCount"] = 2
        out = run(tmp_path, capsys, "visual", two_rows(before), two_rows(after))
        header = next(line for line in out.splitlines() if "auto grid" in line)
        assert "~layout" in header

    def test_row_order_change_is_layout_on_the_row(self, tmp_path, capsys):
        swapped = two_rows()
        swapped["spec"]["layout"]["spec"]["rows"].reverse()
        out = run(tmp_path, capsys, "visual", two_rows(), swapped)
        header = next(line for line in out.splitlines() if "Alpha" in line)
        assert "~layout" in header

    def test_kind_mismatch_prints_note_and_raw_diff(self, tmp_path, capsys):
        out = run(
            tmp_path,
            capsys,
            "visual",
            two_rows(grid(grid_item("panel-2", 0, 0))),
            two_rows(auto_grid("panel-2")),
        )
        assert "layout kind changed: GridLayout -> AutoGridLayout" in out
        assert "Disk" in out


class TestDetail:
    def test_changed_panel_is_shown_under_its_row(self, tmp_path, capsys):
        after = two_rows()
        after["spec"]["elements"]["panel-2"]["spec"]["data"]["spec"]["queries"][0][
            "spec"
        ]["query"]["spec"]["expr"] = "changed"
        out = run(tmp_path, capsys, "detail", two_rows(), after)
        assert out.index("Beta") < out.index("Disk")
        assert "data.spec.queries[0].spec.query.spec.expr" in out


def tabs(*tab_specs):
    """Unverified: tab field names are recalled from the schema, not from a real export."""
    return {
        "kind": "TabsLayout",
        "spec": {
            "tabs": [
                {"kind": "TabsLayoutTab", "spec": {"title": t, "layout": layout}}
                for t, layout in tab_specs
            ]
        },
    }


class TestTabsAndTopLevel:
    def test_tab_title_heads_its_section(self, tmp_path, capsys):
        d = v2_dashboard(
            elements={"panel-1": element("CPU", "A")},
            layout=tabs(("Overview", grid(grid_item("panel-1", 0, 0)))),
        )
        out = run(tmp_path, capsys, "visual", d)
        assert out.index("Overview") < out.index("CPU")

    def test_rows_nested_in_a_tab_join_the_path(self):
        d = v2_dashboard(
            elements={"panel-1": element("CPU")},
            layout=tabs(("T", rows(("R", grid(grid_item("panel-1", 0, 0)))))),
        )
        assert [s.path for s in v2_sections(d)] == [("T", "R")]

    def test_top_level_grid_is_one_untitled_section(self, tmp_path, capsys):
        d = v2_dashboard(
            elements={"panel-1": element("CPU", "A")},
            layout=grid(grid_item("panel-1", 0, 0)),
        )
        assert [s.path for s in v2_sections(d)] == [()]
        assert "(no row)" in run(tmp_path, capsys, "visual", d)
