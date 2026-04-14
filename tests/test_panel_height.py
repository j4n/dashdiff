"""
Tests for panel and band height rendering.

Covers two functions:
  - _panel_render_height(panel_type, title, col_width, grid_h) → int
  - band_max_height(panels, console_width) → int
  - title_line_count(title, col_width) → int

Key invariants:
  1. A panel with a larger h always renders at >= the height of a panel
     with a smaller h in the same band (proportionality).
  2. The rendered height is always >= the content minimum (no clipping).
  3. band_max_height uses each panel's h when computing the band height.
  4. _panel_render_height accepts a grid_h parameter and returns at least
     grid_h terminal rows (1 grid unit = 1 terminal row).
"""

from __future__ import annotations

import pytest
from dashdiff.grid import (
    GridPanel,
    _panel_render_height,
    band_max_height,
    title_line_count,
    GRID_COLUMNS,
)


def _make_panel(title: str, x: int, w: int, h: int = 4, y: int = 0) -> GridPanel:
    return GridPanel(
        title=title,
        panel_type="stat",
        x=x,
        y=y,
        w=w,
        h=h,
        queries=[],
    )


# ---------------------------------------------------------------------------
# title_line_count
# ---------------------------------------------------------------------------

class TestTitleLineCount:
    def test_short_title_fits_on_one_line(self):
        assert title_line_count("RTT", col_width=20) == 1

    def test_title_exactly_at_width_is_one_line(self):
        # usable = 20 - 2 = 18; 18 chars fits in 1 line
        assert title_line_count("A" * 18, col_width=20) == 1

    def test_title_one_over_width_wraps_to_two_lines(self):
        # usable = 18; 19 chars wraps to 2 lines
        assert title_line_count("A" * 19, col_width=20) == 2

    def test_long_title_wraps_to_three_lines(self):
        # usable = 18; 37 chars = ceil(37/18) = 3 lines
        assert title_line_count("A" * 37, col_width=20) == 3

    def test_empty_title_is_one_line(self):
        assert title_line_count("", col_width=20) == 1

    def test_zero_width_returns_at_least_one(self):
        assert title_line_count("hello", col_width=0) >= 1


# ---------------------------------------------------------------------------
# _panel_render_height with grid_h
# ---------------------------------------------------------------------------

class TestPanelRenderHeight:
    def test_grid_h_larger_than_content_minimum_wins(self):
        result = _panel_render_height("stat", "RTT", col_width=40, grid_h=8)
        assert result >= 8

    def test_content_minimum_wins_when_grid_h_is_small(self):
        result = _panel_render_height("stat", "RTT", col_width=40, grid_h=1)
        assert result >= 4  # 2 borders + 1 title + 1 badge

    def test_grid_h_zero_falls_back_to_content_minimum(self):
        result = _panel_render_height("stat", "RTT", col_width=40, grid_h=0)
        assert result >= 4

    def test_larger_grid_h_produces_larger_height(self):
        h4 = _panel_render_height("stat", "RTT", col_width=40, grid_h=4)
        h8 = _panel_render_height("stat", "RTT", col_width=40, grid_h=8)
        assert h8 >= h4

    def test_no_grid_h_returns_content_minimum(self):
        result = _panel_render_height("stat", "RTT", col_width=40)
        assert result == 4  # 2 + 1 + 1


# ---------------------------------------------------------------------------
# band_max_height
# ---------------------------------------------------------------------------

_MIN_HEIGHT = 4  # 2 borders + 1 title line + 1 badge line


class TestBandMaxHeight:
    def test_all_short_titles_returns_minimum(self):
        panels = [
            _make_panel("RTT",    x=0,  w=6),
            _make_panel("Pairs",  x=6,  w=6),
            _make_panel("Failed", x=12, w=6),
            _make_panel("OK",     x=18, w=6),
        ]
        assert band_max_height(panels, console_width=160) == _MIN_HEIGHT

    def test_one_long_title_raises_band_above_minimum(self):
        panels = [
            _make_panel("RTT",    x=0,  w=6),
            _make_panel("Pairs",  x=6,  w=6),
            _make_panel("Failed", x=12, w=6),
            _make_panel("A" * 60, x=18, w=6),
        ]
        assert band_max_height(panels, console_width=160) > _MIN_HEIGHT

    def test_empty_panel_list_returns_one(self):
        assert band_max_height([], console_width=160) == 1

    def test_narrow_console_wraps_earlier(self):
        panels = [
            _make_panel("Short",  x=0, w=6),
            _make_panel("A" * 30, x=6, w=6),
        ]
        assert band_max_height(panels, console_width=80) > _MIN_HEIGHT

    def test_taller_grid_h_raises_band_height(self):
        panels = [
            _make_panel("RTT",   x=0,  w=12, h=4),
            _make_panel("Graph", x=12, w=12, h=9),
        ]
        assert band_max_height(panels, console_width=160) >= 9

    def test_wrapping_title_wins_over_grid_h(self):
        long_title = "A" * 80
        panels = [_make_panel(long_title, x=0, w=3, h=4)]
        # col_width ≈ 160*3/24 = 20; title wraps to many lines → height > 4
        assert band_max_height(panels, console_width=160) >= 8

    def test_proportionality_across_bands(self):
        short_band = [_make_panel("X", x=0, w=24, h=4)]
        tall_band  = [_make_panel("X", x=0, w=24, h=8)]
        assert band_max_height(tall_band, console_width=160) > \
               band_max_height(short_band, console_width=160)
