"""
RED tests for the universal colour palette and console factory.

Palette rules:
- change_border_style() returns only named ANSI colour strings (no color(N) indices)
- _type_colour() returns only named ANSI colour strings
- _PANEL_TYPES constant contains no color(N) values
- _CHANGE_LABELS values contain no color(N) markup

Console factory rules (dashdiff.console.make_console):
- Returns a Rich Console with no_color=True when stdout is not a TTY
- Returns a Rich Console with no_color=True when NO_COLOR env var is set
- Returns a Rich Console with no_color=True when TERM=dumb
- Returns a Rich Console with colour enabled when stdout is a TTY and no inhibitors
"""

from __future__ import annotations

import io
import os
import re
import pytest

from dashdiff.grid import (
    PanelChange,
    change_border_style,
    _type_colour,
    _CHANGE_LABELS,
    _TYPE_COLOURS,
)

# Pattern that matches a 256-colour index reference — must NOT appear
_COLOR_INDEX_RE = re.compile(r"color\(\d+\)")


def _has_index(s: str | None) -> bool:
    """Return True if the string contains a color(N) index reference."""
    return bool(s and _COLOR_INDEX_RE.search(s))


# ---------------------------------------------------------------------------
# change_border_style — no color(N) indices
# ---------------------------------------------------------------------------

class TestChangeBorderStyleNoIndex:
    @pytest.mark.parametrize("kind", [
        PanelChange.ADDED,
        PanelChange.REMOVED,
        PanelChange.MODIFIED_QUERY,
        PanelChange.MODIFIED_TITLE,
        PanelChange.MODIFIED_LAYOUT,
        PanelChange.MODIFIED_CONFIG,
    ])
    def test_no_color_index(self, kind: PanelChange):
        style = change_border_style(kind)
        assert not _has_index(style), (
            f"change_border_style({kind}) returned a color(N) index: {style!r}"
        )

    def test_unchanged_returns_none(self):
        assert change_border_style(PanelChange.UNCHANGED) is None

    @pytest.mark.parametrize("kind", [
        PanelChange.ADDED,
        PanelChange.REMOVED,
        PanelChange.MODIFIED_LAYOUT,
    ])
    def test_structural_kinds_return_nonempty_string(self, kind: PanelChange):
        """Structural changes (added, removed, layout) must have a border colour."""
        style = change_border_style(kind)
        assert isinstance(style, str) and style.strip()

    @pytest.mark.parametrize("kind", [
        PanelChange.MODIFIED_QUERY,
        PanelChange.MODIFIED_CONFIG,
        PanelChange.MODIFIED_TITLE,
    ])
    def test_content_only_kinds_return_none(self, kind: PanelChange):
        """Content-only changes (query, config) must NOT have a border colour."""
        assert change_border_style(kind) is None


# ---------------------------------------------------------------------------
# _type_colour — no color(N) indices
# ---------------------------------------------------------------------------

class TestTypeColourNoIndex:
    @pytest.mark.parametrize("panel_type", [
        "timeseries", "stat", "gauge", "bargauge", "table",
        "text", "row", "piechart", "histogram", "logs",
        "alertlist", "dashlist", "news", "unknown_future_type",
    ])
    def test_no_color_index(self, panel_type: str):
        colour = _type_colour(panel_type)
        assert not _has_index(colour), (
            f"_type_colour({panel_type!r}) returned a color(N) index: {colour!r}"
        )

    def test_returns_nonempty_string(self):
        assert _type_colour("timeseries").strip()

    def test_unknown_type_has_fallback(self):
        colour = _type_colour("some_future_panel_type")
        assert isinstance(colour, str) and colour.strip()


# ---------------------------------------------------------------------------
# _CHANGE_LABELS — no color(N) markup
# ---------------------------------------------------------------------------

class TestChangeLabelsNoIndex:
    @pytest.mark.parametrize("kind", list(PanelChange))
    def test_no_color_index_in_label(self, kind: PanelChange):
        label = _CHANGE_LABELS.get(kind, "")
        assert not _has_index(label), (
            f"_CHANGE_LABELS[{kind}] contains a color(N) index: {label!r}"
        )


# ---------------------------------------------------------------------------
# _PANEL_TYPES constant — all values must be named ANSI colours
# ---------------------------------------------------------------------------

class TestPanelTypesConstantNoIndex:
    def test_all_type_colours_no_index(self):
        bad = {k: v for k, v in _TYPE_COLOURS.items() if _has_index(v)}
        assert not bad, f"_PANEL_TYPES has color(N) values: {bad}"


# ---------------------------------------------------------------------------
# make_console() — console factory with TTY / NO_COLOR detection
# ---------------------------------------------------------------------------

class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FakePipe(io.StringIO):
    def isatty(self) -> bool:
        return False


class TestMakeConsole:
    """make_console() lives in dashdiff.console and returns a Rich Console."""

    def test_no_color_when_not_a_tty(self):
        from dashdiff.console import make_console
        console = make_console(file=_FakePipe())
        assert console.no_color is True

    def test_no_color_when_NO_COLOR_set(self, monkeypatch):
        from dashdiff.console import make_console
        monkeypatch.setenv("NO_COLOR", "1")
        console = make_console(file=_FakeTTY())
        assert console.no_color is True

    def test_no_color_when_TERM_dumb(self, monkeypatch):
        from dashdiff.console import make_console
        monkeypatch.setenv("TERM", "dumb")
        monkeypatch.delenv("NO_COLOR", raising=False)
        console = make_console(file=_FakeTTY())
        assert console.no_color is True

    def test_color_enabled_for_tty(self, monkeypatch):
        from dashdiff.console import make_console
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        console = make_console(file=_FakeTTY())
        assert console.no_color is False

    def test_force_color_overrides_non_tty(self, monkeypatch):
        from dashdiff.console import make_console
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        console = make_console(file=_FakePipe())
        assert console.no_color is False

    def test_no_color_beats_force_color(self, monkeypatch):
        from dashdiff.console import make_console
        monkeypatch.setenv("FORCE_COLOR", "1")
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.delenv("TERM", raising=False)
        console = make_console(file=_FakeTTY())
        assert console.no_color is True

    def test_stderr_tty_fallback(self, monkeypatch):
        """When stdout is a pipe but stderr is a TTY (git difftool), colour is on."""
        from unittest.mock import patch
        import sys
        from dashdiff.console import make_console
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        with patch.object(sys, "stderr", _FakeTTY()):
            console = make_console(file=_FakePipe())
        assert console.no_color is False
