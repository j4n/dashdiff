"""Small unit tables for rules that the CLI tests cannot observe directly."""

import io
import sys
from unittest.mock import patch

import pytest

from dashdiff.console import make_console
from dashdiff.diff_paths import MISSING, diff_paths
from dashdiff.grid import (
    PanelChange,
    change_border_style,
    classify_changes,
    extract_panels,
    panel_queries,
    title_line_count,
    truncate_title,
)

K = PanelChange


def panel(**override):
    base = {
        "title": "P",
        "type": "timeseries",
        "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
        "targets": [{"refId": "A", "expr": "up"}],
    }
    return {**base, **override}


def moved(**pos):
    return panel(gridPos={"x": 0, "y": 0, "w": 12, "h": 8, **pos})


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (panel(), panel(), {K.UNCHANGED}),
        (panel(), panel(targets=[{"refId": "A", "expr": "x"}]), {K.MODIFIED_QUERY}),
        (panel(), moved(x=12), {K.MODIFIED_LAYOUT}),
        (panel(), moved(y=4), {K.MODIFIED_LAYOUT}),
        (panel(), moved(w=6), {K.MODIFIED_LAYOUT}),
        (panel(), moved(h=4), {K.MODIFIED_LAYOUT}),
        (panel(), panel(options={"a": 1}), {K.MODIFIED_CONFIG}),
        (
            panel(),
            panel(targets=[{"refId": "A", "expr": "x"}], options={"a": 1}),
            {K.MODIFIED_QUERY, K.MODIFIED_CONFIG},
        ),
        (
            panel(),
            panel(
                targets=[{"refId": "A", "expr": "x"}],
                gridPos={"x": 0, "y": 4, "w": 12, "h": 8},
                options={"a": 1},
            ),
            {K.MODIFIED_QUERY, K.MODIFIED_LAYOUT, K.MODIFIED_CONFIG},
        ),
    ],
)
def test_classify_changes_by_kind(before, after, expected):
    assert classify_changes([before], [after])["P"] == frozenset(expected)


def test_classify_changes_added_and_removed_by_title():
    result = classify_changes([panel(title="Old")], [panel(title="New")])
    assert result == {"Old": frozenset({K.REMOVED}), "New": frozenset({K.ADDED})}


@pytest.mark.parametrize(
    "kinds", [K.ADDED, K.REMOVED, K.MODIFIED_LAYOUT, {K.MODIFIED_QUERY, K.ADDED}]
)
def test_structural_changes_get_a_border_colour(kinds):
    kinds = frozenset({kinds}) if isinstance(kinds, K) else frozenset(kinds)
    assert change_border_style(kinds)


@pytest.mark.parametrize(
    "kinds",
    [K.UNCHANGED, K.MODIFIED_QUERY, K.MODIFIED_CONFIG, K.MODIFIED_TITLE],
)
def test_content_changes_get_no_border_colour(kinds):
    assert change_border_style(frozenset({kinds})) is None


class Stream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.mark.parametrize(
    ("env", "tty", "colour"),
    [
        ({}, False, False),
        ({}, True, True),
        ({"NO_COLOR": "1"}, True, False),
        ({"TERM": "dumb"}, True, False),
        ({"FORCE_COLOR": "1"}, False, True),
        ({"FORCE_COLOR": "1", "NO_COLOR": "1"}, True, False),
    ],
)
def test_make_console_colour(monkeypatch, env, tty, colour):
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert make_console(file=Stream(tty)).no_color is (not colour)


def test_make_console_uses_stderr_tty_when_stdout_is_a_pipe(monkeypatch):
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(name, raising=False)
    with patch.object(sys, "stderr", Stream(True)):
        assert make_console(file=Stream(False)).no_color is False


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (1, 1, []),
        (1, 2, [("", 1, 2)]),
        ({"a": {"b": 1}}, {"a": {"b": 2}}, [("a.b", 1, 2)]),
        ({}, {"k": 1}, [("k", MISSING, 1)]),
        ({"k": 1}, {}, [("k", 1, MISSING)]),
        ([1, 2, 3], [1, 9, 3], [("[1]", 2, 9)]),
        ([1], [1, 2], [("[1]", MISSING, 2)]),
        ([1, 2], [1], [("[1]", 2, MISSING)]),
        (
            {"t": [{"e": "a"}, {"e": "b"}]},
            {"t": [{"e": "a"}, {"e": "X"}]},
            [("t[1].e", "b", "X")],
        ),
        ({"x": 1, "y": 1}, {"x": 2, "y": 2}, [("x", 1, 2), ("y", 1, 2)]),
    ],
)
def test_diff_paths(before, after, expected):
    found = [(c.path, c.before, c.after) for c in diff_paths(before, after)]
    assert found == expected


def test_diff_paths_prefix():
    assert diff_paths([1, 2], [1, 9], path="items")[0].path == "items[1]"


@pytest.mark.parametrize(
    ("targets", "expect_in_output"),
    [
        ([{"refId": "A", "expr": "up"}], ["A", "up"]),
        ([{"refId": "A", "rawSql": "SELECT 1"}], ["SELECT 1"]),
        ([{"refId": "A", "expr": "a"}, {"refId": "B", "expr": "b"}], ["a", "b"]),
        ([{"refId": "A"}], [""]),
    ],
)
def test_panel_queries_one_line_per_target(targets, expect_in_output):
    lines = panel_queries({"targets": targets})
    assert len(lines) == len(targets)
    assert all(part in " ".join(lines) for part in expect_in_output)


def test_panel_without_targets_has_no_queries():
    assert panel_queries({}) == []


@pytest.mark.parametrize(
    ("length", "max_chars", "expected_length", "ellipsis"),
    [(3, 20, 3, False), (20, 20, 20, False), (21, 20, 20, True), (0, 10, 0, False)],
)
def test_truncate_title_boundary(length, max_chars, expected_length, ellipsis):
    result = truncate_title("A" * length, max_chars=max_chars)
    assert len(result) == expected_length
    assert result.endswith("…") is ellipsis


@pytest.mark.parametrize(
    ("length", "lines"), [(0, 1), (18, 1), (19, 2), (36, 2), (37, 3)]
)
def test_title_line_count_boundary(length, lines):
    # A 20 column cell leaves 18 columns for the title.
    assert title_line_count("A" * length, col_width=20) == lines


def test_extract_panels_unwraps_rows_and_keeps_the_row_itself():
    child = {
        "title": "Child",
        "type": "stat",
        "gridPos": {"x": 12, "y": 1, "w": 12, "h": 4},
    }
    row = {
        "title": "Row",
        "type": "row",
        "gridPos": {"x": 0, "y": 0, "w": 24, "h": 1},
        "panels": [child],
    }
    found = {p.title: (p.x, p.y) for p in extract_panels({"panels": [row]})}
    assert found == {"Row": (0, 0), "Child": (12, 1)}
