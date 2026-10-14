"""Terminal views for v2 dashboards: one block per layout section."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape

from dashdiff.diff_paths import PathChange, diff_paths
from dashdiff.grid import (
    PanelChange,
    build_band_renderables,
    render_grid,
    section_grid_panels,
)
from dashdiff.v2 import V2Panel, V2Section, spec_of, v2_panels, v2_sections

if TYPE_CHECKING:
    from rich.console import Console

_LAYOUT_BADGE = "[bold #3b8eea]~layout[/]"
_ADDED_BADGE = "[bold #23d18b]+added[/]"
_REMOVED_BADGE = "[bold #f14c4c]-removed[/]"


def _section_title(section: V2Section) -> str:
    return " / ".join(section.path) or "(no row)"


def _settings_line(section: V2Section) -> str:
    if section.kind != "AutoGridLayout":
        return ""
    columns = section.settings.get("maxColumnCount", 1)
    plural = "" if columns == 1 else "s"
    return (
        f"auto grid: {columns} column{plural}, "
        f"width {section.settings.get('columnWidthMode', 'standard')}, "
        f"height {section.settings.get('rowHeightMode', 'standard')}"
    )


def _header(section: V2Section, badge: str = "") -> str:
    parts = [f"[bold]{escape(_section_title(section))}[/]"]
    settings = _settings_line(section)
    if settings:
        parts.append(f"[dim]{settings}[/]")
    if badge:
        parts.append(badge)
    return "── " + "  ".join(parts)


def _pair_sections(
    before: list[V2Section], after: list[V2Section]
) -> list[tuple[V2Section | None, V2Section | None]]:
    """Pair sections by path, duplicates in order of appearance; after order first."""
    unused: dict[tuple[str, ...], list[V2Section]] = {}
    for section in before:
        unused.setdefault(section.path, []).append(section)
    pairs: list[tuple[V2Section | None, V2Section | None]] = []
    for section in after:
        candidates = unused.get(section.path)
        pairs.append((candidates.pop(0) if candidates else None, section))
    pairs += [(old, None) for olds in unused.values() for old in olds]
    return pairs


def _moved(
    pairs: list[tuple[V2Section | None, V2Section | None]],
    before: list[V2Section],
) -> set[int]:
    """Indexes in *pairs* whose predecessor among paired sections differs."""
    paired = [(i, old, new) for i, (old, new) in enumerate(pairs) if old and new]
    before_index = {id(old): n for n, old in enumerate(s for s in before)}
    order_before = sorted(paired, key=lambda p: before_index[id(p[1])])
    predecessor_before = {
        id(item[2]): (order_before[n - 1][2] if n else None)
        for n, item in enumerate(order_before)
    }
    return {
        i
        for n, (i, _, new) in enumerate(paired)
        if predecessor_before[id(new)] is not (paired[n - 1][2] if n else None)
    }


def _stacked_panels(
    section: V2Section | None, panels: dict[str, V2Panel], stacked: bool
) -> list:
    return section_grid_panels(section, panels, stacked) if section else []


def print_v2_visual(console: Console, dashboard: dict[str, object]) -> None:
    """Single-file view: a header and a grid per section."""
    panels = {p.key: p for p in v2_panels(dashboard)}
    for section in v2_sections(dashboard):
        console.print(_header(section))
        render_grid(section_grid_panels(section, panels), console=console)


def _kind_note(old: V2Section, new: V2Section) -> list[PathChange]:
    return diff_paths(old.node, new.node)


def print_v2_bands(
    console: Console,
    before: dict[str, object],
    after: dict[str, object],
    changes: dict[str, frozenset[PanelChange]],
    path_changes: dict[str, list[PathChange]],
    show_unchanged: bool,
) -> None:
    """Two-file view: per section header, then the side-by-side bands."""
    before_sections, after_sections = v2_sections(before), v2_sections(after)
    before_panels = {p.key: p for p in v2_panels(before)}
    after_panels = {p.key: p for p in v2_panels(after)}
    pairs = _pair_sections(before_sections, after_sections)
    moved = _moved(pairs, before_sections)

    for i, (old, new) in enumerate(pairs):
        mismatch = bool(old and new and old.kind != new.kind)
        if old is None:
            badge = _ADDED_BADGE
        elif new is None:
            badge = _REMOVED_BADGE
        elif mismatch or old.settings != new.settings or i in moved:
            badge = _LAYOUT_BADGE
        else:
            badge = ""
        console.print(_header(new or old, badge))  # type: ignore[arg-type]
        if mismatch:
            console.print(
                f"[dim]layout kind changed: {old.kind} -> {new.kind}; "  # type: ignore[union-attr]
                "raw layout diff:[/]"
            )
            for change in _kind_note(old, new):  # type: ignore[arg-type]
                console.print(
                    f"  {escape(change.path)}: {escape(repr(change.before))}"
                    f" -> {escape(repr(change.after))}"
                )
        before_grid = _stacked_panels(old, before_panels, mismatch)
        after_grid = _stacked_panels(new, after_panels, mismatch)
        by_y_before: dict[int, list] = {}
        by_y_after: dict[int, list] = {}
        for panel in before_grid:
            by_y_before.setdefault(panel.y, []).append(panel)
        for panel in after_grid:
            by_y_after.setdefault(panel.y, []).append(panel)
        for y in sorted(by_y_before.keys() | by_y_after.keys()):
            for renderable in build_band_renderables(
                y_band=y,
                before_panels=by_y_before.get(y, []),
                after_panels=by_y_after.get(y, []),
                changes=changes,
                path_changes=path_changes,  # type: ignore[arg-type]
                console_width=console.width or 160,
                show_unchanged_panels=show_unchanged,
            ):
                console.print(renderable)


def v2_title(dashboard: dict[str, object], fallback: str) -> str:
    return str(spec_of(dashboard).get("title", fallback))
