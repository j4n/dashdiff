"""
RED tests for dashdiff.diff_paths — the recursive flat-path differ.

The module must expose:

    PathChange(path: str, before: object, after: object)
    diff_paths(before: object, after: object, path: str = "") -> list[PathChange]

Rules under test:
- Scalar change at root produces one PathChange
- Identical scalars produce no changes
- Nested dict change produces dotted-path entry
- Added key produces PathChange with before=MISSING sentinel
- Removed key produces PathChange with after=MISSING sentinel
- List element changed by index produces bracketed path
- List length change (item added) produces PathChange with before=MISSING
- List length change (item removed) produces PathChange with after=MISSING
- Deeply nested change produces full dotted+bracketed path
- Identical dicts produce no changes
- MISSING sentinel is a distinct singleton (not None, not False)
"""

from __future__ import annotations

import pytest
from dashdiff.diff_paths import PathChange, diff_paths, MISSING


# ---------------------------------------------------------------------------
# MISSING sentinel
# ---------------------------------------------------------------------------

class TestMissingSentinel:
    def test_missing_is_not_none(self):
        assert MISSING is not None

    def test_missing_is_not_false(self):
        assert MISSING is not False

    def test_missing_is_singleton(self):
        from dashdiff.diff_paths import MISSING as M2
        assert MISSING is M2

    def test_missing_repr_is_informative(self):
        assert "MISSING" in repr(MISSING).upper()


# ---------------------------------------------------------------------------
# PathChange dataclass
# ---------------------------------------------------------------------------

class TestPathChange:
    def test_has_path_field(self):
        pc = PathChange(path="a.b", before=1, after=2)
        assert pc.path == "a.b"

    def test_has_before_field(self):
        pc = PathChange(path="x", before="old", after="new")
        assert pc.before == "old"

    def test_has_after_field(self):
        pc = PathChange(path="x", before="old", after="new")
        assert pc.after == "new"

    def test_is_frozen(self):
        pc = PathChange(path="x", before=1, after=2)
        with pytest.raises((AttributeError, TypeError)):
            pc.path = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# diff_paths — scalar root
# ---------------------------------------------------------------------------

class TestDiffPathsScalar:
    def test_identical_scalars_no_change(self):
        assert diff_paths(42, 42) == []

    def test_changed_scalar_one_entry(self):
        result = diff_paths("old", "new")
        assert len(result) == 1

    def test_changed_scalar_empty_path(self):
        result = diff_paths("old", "new")
        assert result[0].path == ""

    def test_changed_scalar_before_value(self):
        result = diff_paths("old", "new")
        assert result[0].before == "old"

    def test_changed_scalar_after_value(self):
        result = diff_paths("old", "new")
        assert result[0].after == "new"


# ---------------------------------------------------------------------------
# diff_paths — flat dict
# ---------------------------------------------------------------------------

class TestDiffPathsFlatDict:
    def test_identical_dicts_no_change(self):
        assert diff_paths({"a": 1}, {"a": 1}) == []

    def test_changed_value_dotted_path(self):
        result = diff_paths({"a": 1}, {"a": 2})
        assert len(result) == 1
        assert result[0].path == "a"
        assert result[0].before == 1
        assert result[0].after == 2

    def test_added_key_uses_missing_before(self):
        result = diff_paths({}, {"x": 99})
        assert len(result) == 1
        assert result[0].path == "x"
        assert result[0].before is MISSING
        assert result[0].after == 99

    def test_removed_key_uses_missing_after(self):
        result = diff_paths({"x": 99}, {})
        assert len(result) == 1
        assert result[0].path == "x"
        assert result[0].before == 99
        assert result[0].after is MISSING

    def test_multiple_changes_all_reported(self):
        result = diff_paths({"a": 1, "b": 2}, {"a": 9, "b": 2, "c": 3})
        paths = {pc.path for pc in result}
        assert "a" in paths
        assert "c" in paths
        assert "b" not in paths


# ---------------------------------------------------------------------------
# diff_paths — nested dict
# ---------------------------------------------------------------------------

class TestDiffPathsNestedDict:
    def test_nested_change_dotted_path(self):
        before = {"outer": {"inner": "old"}}
        after  = {"outer": {"inner": "new"}}
        result = diff_paths(before, after)
        assert len(result) == 1
        assert result[0].path == "outer.inner"

    def test_deeply_nested_path(self):
        before = {"a": {"b": {"c": 1}}}
        after  = {"a": {"b": {"c": 2}}}
        result = diff_paths(before, after)
        assert result[0].path == "a.b.c"

    def test_nested_added_key(self):
        before = {"a": {}}
        after  = {"a": {"new_key": True}}
        result = diff_paths(before, after)
        assert result[0].path == "a.new_key"
        assert result[0].before is MISSING


# ---------------------------------------------------------------------------
# diff_paths — lists
# ---------------------------------------------------------------------------

class TestDiffPathsList:
    def test_identical_lists_no_change(self):
        assert diff_paths([1, 2, 3], [1, 2, 3]) == []

    def test_changed_element_bracketed_path(self):
        result = diff_paths([1, 2, 3], [1, 9, 3])
        assert len(result) == 1
        assert result[0].path == "[1]"
        assert result[0].before == 2
        assert result[0].after == 9

    def test_added_element_missing_before(self):
        result = diff_paths([1], [1, 2])
        assert any(pc.before is MISSING and pc.after == 2 for pc in result)

    def test_removed_element_missing_after(self):
        result = diff_paths([1, 2], [1])
        assert any(pc.after is MISSING and pc.before == 2 for pc in result)

    def test_nested_list_in_dict(self):
        before = {"targets": [{"expr": "old"}]}
        after  = {"targets": [{"expr": "new"}]}
        result = diff_paths(before, after)
        assert len(result) == 1
        assert result[0].path == "targets[0].expr"

    def test_list_of_dicts_multiple_changes(self):
        before = {"targets": [{"expr": "a", "refId": "A"}, {"expr": "b", "refId": "B"}]}
        after  = {"targets": [{"expr": "a", "refId": "A"}, {"expr": "X", "refId": "B"}]}
        result = diff_paths(before, after)
        assert len(result) == 1
        assert result[0].path == "targets[1].expr"


# ---------------------------------------------------------------------------
# diff_paths — prefix argument
# ---------------------------------------------------------------------------

class TestDiffPathsPrefix:
    def test_prefix_prepended_to_path(self):
        result = diff_paths({"x": 1}, {"x": 2}, path="root")
        assert result[0].path == "root.x"

    def test_prefix_with_list(self):
        result = diff_paths([1, 2], [1, 9], path="items")
        assert result[0].path == "items[1]"
