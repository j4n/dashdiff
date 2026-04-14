"""
grafana_visual_diff — diff data model and Rich-based side-by-side renderer.

The module is split into two layers:

1. **Data model** (no external dependencies):
   ``compute_diff(left_lines, right_lines)`` uses ``difflib.SequenceMatcher``
   to produce a list of ``(DiffLine, DiffLine)`` row pairs suitable for
   side-by-side display.

2. **Renderer** (requires ``rich``):
   ``render_side_by_side(rows, left_title, right_title, console)`` builds a
   Rich ``Table`` with two syntax-highlighted panels and per-line colour
   coding (green background for additions, red for removals).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Final, Sequence

if TYPE_CHECKING:
    from rich.console import Console


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class DiffKind(Enum):
    SAME    = auto()   # line present and identical on both sides
    REMOVED = auto()   # line present on left, absent/changed on right
    ADDED   = auto()   # line present on right, absent/changed on left
    EMPTY   = auto()   # padding — the other side has no corresponding line


@dataclass(frozen=True, slots=True)
class DiffLine:
    text: str
    kind: DiffKind


def compute_diff(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
) -> list[tuple[DiffLine, DiffLine]]:
    """
    Compute a side-by-side diff between two sequences of strings.

    Returns a list of ``(left, right)`` ``DiffLine`` pairs, one per row of
    the side-by-side view.  Padding rows use ``DiffKind.EMPTY`` with an
    empty string.
    """
    _EMPTY = DiffLine("", DiffKind.EMPTY)

    rows: list[tuple[DiffLine, DiffLine]] = []
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for l, r in zip(left_lines[i1:i2], right_lines[j1:j2]):
                rows.append((DiffLine(l, DiffKind.SAME), DiffLine(r, DiffKind.SAME)))

        elif tag == "replace":
            left_chunk  = left_lines[i1:i2]
            right_chunk = right_lines[j1:j2]
            for idx in range(max(len(left_chunk), len(right_chunk))):
                left_dl  = DiffLine(left_chunk[idx],  DiffKind.REMOVED) if idx < len(left_chunk)  else _EMPTY
                right_dl = DiffLine(right_chunk[idx], DiffKind.ADDED)   if idx < len(right_chunk) else _EMPTY
                rows.append((left_dl, right_dl))

        elif tag == "delete":
            for line in left_lines[i1:i2]:
                rows.append((DiffLine(line, DiffKind.REMOVED), _EMPTY))

        elif tag == "insert":
            for line in right_lines[j1:j2]:
                rows.append((_EMPTY, DiffLine(line, DiffKind.ADDED)))

    return rows


# ---------------------------------------------------------------------------
# Renderer  (Rich required — imported lazily so the data model stays testable
#            without installing Rich)
# ---------------------------------------------------------------------------

# Colour palette (256-colour safe)
_COLOUR_REMOVED_BG: Final[str] = "on color(52)"   # dark red
_COLOUR_ADDED_BG:   Final[str] = "on color(22)"   # dark green
_COLOUR_REMOVED_FG: Final[str] = "color(203)"     # bright red   (line-number gutter)
_COLOUR_ADDED_FG:   Final[str] = "color(120)"     # bright green (line-number gutter)
_COLOUR_SAME_FG:    Final[str] = "color(244)"     # grey         (line-number gutter)
_COLOUR_EMPTY_BG:   Final[str] = "on color(235)"  # very dark grey (padding rows)


def _make_line_text(line: DiffLine, lineno: int | None) -> object:
    """Return a Rich ``Text`` object for a single diff line."""
    from rich.text import Text

    if line.kind == DiffKind.EMPTY:
        return Text(" ", style=_COLOUR_EMPTY_BG, end="\n")

    gutter_style = {
        DiffKind.SAME:    _COLOUR_SAME_FG,
        DiffKind.REMOVED: _COLOUR_REMOVED_FG,
        DiffKind.ADDED:   _COLOUR_ADDED_FG,
    }[line.kind]

    bg_style = {
        DiffKind.SAME:    "",
        DiffKind.REMOVED: _COLOUR_REMOVED_BG,
        DiffKind.ADDED:   _COLOUR_ADDED_BG,
    }[line.kind]

    num = f"{lineno:>4} " if lineno is not None else "     "
    t = Text(end="\n")
    t.append(num, style=gutter_style)
    t.append(line.text, style=bg_style)
    return t


def render_side_by_side(
    rows: list[tuple[DiffLine, DiffLine]],
    left_title:  str = "before",
    right_title: str = "after",
    console: Console | None = None,
) -> None:
    """
    Render a side-by-side diff to the terminal using Rich.

    Parameters
    ----------
    rows:
        Output of ``compute_diff()``.
    left_title / right_title:
        Column header labels.
    console:
        A ``rich.console.Console`` instance.  If ``None``, one is created
        that writes to stdout with full colour support.
    """
    from rich.console import Console as RichConsole
    from rich.table import Table
    from rich import box

    if console is None:
        console = RichConsole(color_system="256", width=220)

    table = Table(
        box=box.HEAVY_HEAD,
        show_lines=False,
        padding=(0, 0),
        expand=True,
        highlight=False,
    )
    table.add_column(left_title,  style="", ratio=1, no_wrap=True)
    table.add_column(right_title, style="", ratio=1, no_wrap=True)

    left_lineno  = 0
    right_lineno = 0

    for left, right in rows:
        if left.kind  != DiffKind.EMPTY:
            left_lineno  += 1
        if right.kind != DiffKind.EMPTY:
            right_lineno += 1

        left_cell  = _make_line_text(left,  left_lineno  if left.kind  != DiffKind.EMPTY else None)
        right_cell = _make_line_text(right, right_lineno if right.kind != DiffKind.EMPTY else None)
        table.add_row(left_cell, right_cell)

    console.print(table)
