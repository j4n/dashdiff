"""
dashdiff.diff_paths — recursive flat-path differ.

Compares two JSON-like values (dicts, lists, scalars) and returns a flat list
of ``PathChange`` objects, each describing a single leaf-level difference using
a dotted + bracketed path notation::

    targets[0].expr
    options.legend.displayMode
    fieldConfig.defaults.thresholds.steps[1].value

Public API
----------
MISSING
    Sentinel singleton used as ``before`` or ``after`` when a key/index was
    added or removed (as opposed to changed).

PathChange(path, before, after)
    Frozen dataclass describing one changed path.

diff_paths(before, after, path="") -> list[PathChange]
    Recursively compare two values and return all leaf differences.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# ---------------------------------------------------------------------------
# MISSING sentinel
# ---------------------------------------------------------------------------

class _MissingType:
    """Singleton sentinel for absent keys / indices."""

    _instance: _MissingType | None = None

    def __new__(cls) -> _MissingType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING: Final[_MissingType] = _MissingType()


# ---------------------------------------------------------------------------
# PathChange
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PathChange:
    """A single leaf-level difference between two JSON-like values."""

    path:   str
    before: object
    after:  object


# ---------------------------------------------------------------------------
# diff_paths
# ---------------------------------------------------------------------------

def _join(parent: str, child: str) -> str:
    """Concatenate a parent path and a child segment."""
    if not parent:
        return child
    if child.startswith("["):
        return parent + child
    return f"{parent}.{child}"


def diff_paths(
    before: object,
    after:  object,
    path:   str = "",
) -> list[PathChange]:
    """
    Recursively compare *before* and *after* and return a flat list of
    ``PathChange`` objects for every leaf-level difference.

    Parameters
    ----------
    before, after:
        Any JSON-compatible value (dict, list, str, int, float, bool, None).
    path:
        Dotted prefix to prepend to all returned paths.  Used internally for
        recursion; callers may pass a non-empty string to namespace results.
    """
    # Both are dicts — recurse key by key
    if isinstance(before, dict) and isinstance(after, dict):
        result: list[PathChange] = []
        all_keys = set(before) | set(after)
        for key in sorted(all_keys):
            child_path = _join(path, str(key))
            if key not in before:
                result.append(PathChange(path=child_path, before=MISSING, after=after[key]))
            elif key not in after:
                result.append(PathChange(path=child_path, before=before[key], after=MISSING))
            else:
                result.extend(diff_paths(before[key], after[key], path=child_path))
        return result

    # Both are lists — recurse element by element
    if isinstance(before, list) and isinstance(after, list):
        result = []
        max_len = max(len(before), len(after))
        for i in range(max_len):
            child_path = _join(path, f"[{i}]")
            if i >= len(before):
                result.append(PathChange(path=child_path, before=MISSING, after=after[i]))
            elif i >= len(after):
                result.append(PathChange(path=child_path, before=before[i], after=MISSING))
            else:
                result.extend(diff_paths(before[i], after[i], path=child_path))
        return result

    # Leaf comparison
    if before == after:
        return []
    return [PathChange(path=path, before=before, after=after)]
