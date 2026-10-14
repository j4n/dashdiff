"""Vertical tests: v1 dashboards through main(argv), asserting on printed output."""

import json
import re

import pytest

from dashdiff.cli import main


def panel(title, x, y, expr="up", h=8, **extra):
    return {
        "title": title,
        "type": "timeseries",
        "gridPos": {"x": x, "y": y, "w": 12, "h": h},
        "targets": [{"refId": "A", "expr": expr}],
        **extra,
    }


def write(path, panels, version=1):
    data = {"title": "D", "id": 1, "version": version, "panels": panels}
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def run(capsys, monkeypatch, *argv, columns=160):
    monkeypatch.setenv("COLUMNS", str(columns))
    main(list(argv))
    return capsys.readouterr().out


@pytest.fixture
def pair(tmp_path):
    before = write(
        tmp_path / "b.json",
        [
            panel("Same", 0, 0),
            panel("Query", 12, 0),
            panel("Gone", 0, 8),
            panel("Move", 12, 8),
            panel("Multi", 0, 16),
        ],
    )
    after = write(
        tmp_path / "a.json",
        [
            panel("Same", 0, 0),
            panel("Query", 12, 0, expr="down"),
            panel("New", 0, 8),
            panel("Move", 12, 9),
            panel("Multi", 0, 16, expr="x", options={"a": 1}),
        ],
        version=2,
    )
    return before, after


def detail_box(out, title):
    """Return the path rows and header of the detail box for *title*."""
    start = re.search(rf"╭─ {title}  (.*?) ─+╮", out)
    assert start, f"no detail box for {title}"
    end = out.index("╰", start.end())
    return start.group(1), out[start.end() : end]


class TestDetail:
    def test_each_change_kind_gets_a_box_with_its_badges_and_paths(
        self, pair, capsys, monkeypatch
    ):
        out = run(capsys, monkeypatch, "detail", *pair)
        assert "5 panel(s) changed" in out
        badges, body = detail_box(out, "Query")
        assert badges == "~query"
        assert re.search(r'targets\[0\]\.expr\s+"up"\s+"down"', body)
        assert detail_box(out, "New")[0] == "+added"
        assert detail_box(out, "Gone")[0] == "-removed"
        badges, body = detail_box(out, "Move")
        assert badges == "~layout"
        assert re.search(r"gridPos\.y\s+8\s+9", body)
        assert detail_box(out, "Multi")[0] == "~query ~config"

    def test_unchanged_panel_in_a_changed_band_is_hidden(
        self, pair, capsys, monkeypatch
    ):
        out = run(capsys, monkeypatch, "detail", *pair)
        assert "Same" not in out

    def test_noise_only_change_reports_no_changes(self, tmp_path, capsys, monkeypatch):
        before = write(tmp_path / "b.json", [panel("A", 0, 0)], version=1)
        after = write(tmp_path / "a.json", [panel("A", 0, 0)], version=2)
        out = run(capsys, monkeypatch, "detail", before, after)
        assert "no changes" in out
        assert "No changes detected" in out

    def test_panel_id_change_is_not_listed_as_a_path(
        self, tmp_path, capsys, monkeypatch
    ):
        before = write(tmp_path / "b.json", [panel("A", 0, 0, id=1)])
        after = write(tmp_path / "a.json", [panel("A", 0, 0, expr="x", id=7)])
        out = run(capsys, monkeypatch, "detail", before, after)
        _, body = detail_box(out, "A")
        assert "expr" in body
        assert not re.search(r"\bid\b", body)

    def test_unchanged_bands_are_skipped(self, tmp_path, capsys, monkeypatch):
        before = write(tmp_path / "b.json", [panel("Top", 0, 0), panel("Low", 0, 8)])
        after = write(
            tmp_path / "a.json", [panel("Top", 0, 0), panel("Low", 0, 8, expr="x")]
        )
        out = run(capsys, monkeypatch, "detail", before, after)
        assert "Low" in out
        assert "Top" not in out

    def test_panels_in_a_band_are_ordered_by_x(self, tmp_path, capsys, monkeypatch):
        before = write(tmp_path / "b.json", [panel("Zed", 0, 0), panel("Abe", 12, 0)])
        after = write(
            tmp_path / "a.json",
            [panel("Zed", 0, 0, expr="x"), panel("Abe", 12, 0, expr="x")],
        )
        out = run(capsys, monkeypatch, "detail", before, after)
        assert out.index("╭─ Zed  ") < out.index("╭─ Abe  ")

    def test_narrow_console_stacks_before_above_after(self, pair, capsys, monkeypatch):
        wide = run(capsys, monkeypatch, "detail", *pair, columns=200)
        narrow = run(capsys, monkeypatch, "detail", *pair, columns=60)
        assert re.search(r"┃ before\s+┃ after\s+┃", wide)
        assert not re.search(r"┃ before\s+┃ after\s+┃", narrow)
        assert "before" in narrow and "after" in narrow
        assert detail_box(narrow, "Query")[0] == "~query"


class TestVisual:
    def test_summary_and_badges_without_path_tables(self, pair, capsys, monkeypatch):
        out = run(capsys, monkeypatch, "visual", *pair)
        assert "5 panel(s) changed" in out
        assert "~query" in out and "+added" in out and "-removed" in out
        assert "Legend:" in out
        assert not re.search(r"╭─ Query  ", out)

    def test_identical_dashboards_report_no_changes(
        self, tmp_path, capsys, monkeypatch
    ):
        one = write(tmp_path / "a.json", [panel("A", 0, 0)])
        out = run(capsys, monkeypatch, "visual", one, one)
        assert "no changes" in out

    def test_single_file_shows_titles_in_grid_order(
        self, tmp_path, capsys, monkeypatch
    ):
        one = write(tmp_path / "a.json", [panel("Low", 0, 8), panel("Top", 0, 0)])
        out = run(capsys, monkeypatch, "visual", one)
        assert out.index("Top") < out.index("Low")


class TestDiff:
    def test_noise_only_change_prints_nothing(self, tmp_path, capsys):
        before = write(tmp_path / "b.json", [panel("A", 0, 0, id=1)], version=1)
        after = write(tmp_path / "a.json", [panel("A", 0, 0, id=2)], version=2)
        main(["diff", before, after])
        assert capsys.readouterr().out == ""

    def test_real_change_exits_one_and_shows_both_values(self, pair, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["diff", *pair])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert '-          "expr": "up"' in out and '+          "expr": "down"' in out
        assert "version" not in out


class TestGittool:
    def args(self, before, after):
        return ["gittool", "path", before, "h1", "100644", after, "h2", "100644"]

    def test_diffs_old_file_against_new_file(self, pair, capsys, monkeypatch):
        via_git = run(capsys, monkeypatch, *self.args(*pair))
        direct = run(capsys, monkeypatch, "visual", *pair)
        assert via_git == direct
        assert "~query" in via_git

    def test_wrong_argument_count_exits_one(self, pair, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["gittool", "path", *pair])
        assert exc.value.code == 1
        assert "7 arguments" in capsys.readouterr().err


class TestInputErrors:
    def test_missing_file_exits_one(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["normalize", str(tmp_path / "none.json")])
        assert exc.value.code == 1
        assert "File not found" in capsys.readouterr().err

    def test_invalid_json_exits_one(self, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text("{")
        with pytest.raises(SystemExit):
            main(["normalize", str(path)])
        assert "Invalid JSON" in capsys.readouterr().err

    def test_non_object_exits_one(self, tmp_path, capsys):
        path = tmp_path / "list.json"
        path.write_text("[]")
        with pytest.raises(SystemExit):
            main(["normalize", str(path)])
        assert "top level" in capsys.readouterr().err
