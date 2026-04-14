"""
Tests for grafana_visual_diff — the side-by-side colourised diff engine.

These tests operate on the *data model* produced by the diff engine, not on
rendered terminal output (which would be fragile and terminal-dependent).
The rendering layer (Rich) is tested implicitly by the live demo.

Run with:  python -m pytest tests/ -v
"""

import pytest
from dashdiff.visual_diff import compute_diff, DiffLine, DiffKind


# ---------------------------------------------------------------------------
# compute_diff contract
#
# compute_diff(left_lines, right_lines) -> list[tuple[DiffLine, DiffLine]]
#
# Each tuple is a (left, right) pair for one row of the side-by-side view.
# A DiffLine has:
#   .text  : str   — the line content (without trailing newline)
#   .kind  : DiffKind — SAME | REMOVED | ADDED | EMPTY
# ---------------------------------------------------------------------------

class TestDiffKindEnum:
    def test_same_exists(self):
        assert DiffKind.SAME

    def test_removed_exists(self):
        assert DiffKind.REMOVED

    def test_added_exists(self):
        assert DiffKind.ADDED

    def test_empty_exists(self):
        assert DiffKind.EMPTY


class TestDiffLineDataclass:
    def test_has_text_and_kind(self):
        dl = DiffLine(text="hello", kind=DiffKind.SAME)
        assert dl.text == "hello"
        assert dl.kind == DiffKind.SAME


class TestComputeDiffIdentical:
    LINES = ["a", "b", "c"]

    def test_returns_list(self):
        result = compute_diff(self.LINES, self.LINES)
        assert isinstance(result, list)

    def test_row_count_equals_line_count(self):
        result = compute_diff(self.LINES, self.LINES)
        assert len(result) == len(self.LINES)

    def test_each_row_is_tuple_of_two_difflines(self):
        result = compute_diff(self.LINES, self.LINES)
        for left, right in result:
            assert isinstance(left, DiffLine)
            assert isinstance(right, DiffLine)

    def test_all_rows_are_same(self):
        result = compute_diff(self.LINES, self.LINES)
        for left, right in result:
            assert left.kind  == DiffKind.SAME
            assert right.kind == DiffKind.SAME

    def test_text_is_preserved(self):
        result = compute_diff(self.LINES, self.LINES)
        for (left, right), expected in zip(result, self.LINES):
            assert left.text  == expected
            assert right.text == expected


class TestComputeDiffAddedLine:
    LEFT  = ["a", "b"]
    RIGHT = ["a", "b", "c"]

    def test_added_line_appears_on_right(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        right_kinds = [r.kind for _, r in result]
        assert DiffKind.ADDED in right_kinds

    def test_added_line_has_correct_text(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        added = [r for _, r in result if r.kind == DiffKind.ADDED]
        assert any(d.text == "c" for d in added)

    def test_left_side_padded_with_empty(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        left_kinds = [l.kind for l, _ in result]
        assert DiffKind.EMPTY in left_kinds


class TestComputeDiffRemovedLine:
    LEFT  = ["a", "b", "c"]
    RIGHT = ["a", "b"]

    def test_removed_line_appears_on_left(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        left_kinds = [l.kind for l, _ in result]
        assert DiffKind.REMOVED in left_kinds

    def test_removed_line_has_correct_text(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        removed = [l for l, _ in result if l.kind == DiffKind.REMOVED]
        assert any(d.text == "c" for d in removed)

    def test_right_side_padded_with_empty(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        right_kinds = [r.kind for _, r in result]
        assert DiffKind.EMPTY in right_kinds


class TestComputeDiffChangedLine:
    LEFT  = ["a", "old", "c"]
    RIGHT = ["a", "new", "c"]

    def test_changed_line_marked_removed_on_left(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        left_kinds = [l.kind for l, _ in result]
        assert DiffKind.REMOVED in left_kinds

    def test_changed_line_marked_added_on_right(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        right_kinds = [r.kind for _, r in result]
        assert DiffKind.ADDED in right_kinds

    def test_unchanged_lines_are_same(self):
        result = compute_diff(self.LEFT, self.RIGHT)
        same_pairs = [(l, r) for l, r in result if l.kind == DiffKind.SAME]
        same_texts = {l.text for l, _ in same_pairs}
        assert "a" in same_texts
        assert "c" in same_texts


class TestComputeDiffEmptyInputs:
    def test_both_empty(self):
        assert compute_diff([], []) == []

    def test_left_empty(self):
        result = compute_diff([], ["x"])
        assert len(result) == 1
        left, right = result[0]
        assert left.kind  == DiffKind.EMPTY
        assert right.kind == DiffKind.ADDED

    def test_right_empty(self):
        result = compute_diff(["x"], [])
        assert len(result) == 1
        left, right = result[0]
        assert left.kind  == DiffKind.REMOVED
        assert right.kind == DiffKind.EMPTY


class TestComputeDiffSymmetry:
    """Swapping left and right should swap ADDED/REMOVED but keep SAME."""

    def test_swap_inverts_kinds(self):
        left  = ["a", "b", "c"]
        right = ["a", "x", "c"]
        fwd = compute_diff(left, right)
        rev = compute_diff(right, left)
        # In fwd: left=REMOVED, right=ADDED  for the changed line.
        # In rev (inputs swapped): left=REMOVED (was fwd-right), right=ADDED (was fwd-left).
        # So the *texts* swap sides; the kinds on each side stay REMOVED/ADDED.
        # What we assert: the set of (text, kind) pairs is the same, just mirrored.
        fwd_removed_texts = {l.text for l, _ in fwd if l.kind == DiffKind.REMOVED}
        rev_added_texts   = {r.text for _, r in rev if r.kind == DiffKind.ADDED}
        assert fwd_removed_texts == rev_added_texts

        fwd_added_texts   = {r.text for _, r in fwd if r.kind == DiffKind.ADDED}
        rev_removed_texts = {l.text for l, _ in rev if l.kind == DiffKind.REMOVED}
        assert fwd_added_texts == rev_removed_texts

        # SAME lines must be the same on both sides in both directions
        fwd_same = {l.text for l, _ in fwd if l.kind == DiffKind.SAME}
        rev_same = {l.text for l, _ in rev if l.kind == DiffKind.SAME}
        assert fwd_same == rev_same
