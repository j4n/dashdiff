"""
dashdiff — CLI entry point.

Subcommands
-----------
  normalize (n)   Normalise a single dashboard JSON file → stdout.
                  Used as a git textconv driver.
  diff      (d)   Unified text diff of two normalised dashboard files → stdout.
  visual    (v)   Rich terminal box-model grid visualiser.
                  Single file: show the grid layout.
                  Two files:   show before/after side-by-side with changed panels
                               highlighted.
  detail    (x)   Like visual, but each band row is immediately followed by
                  a per-panel breakdown of changed JSON paths.
                  Unchanged bands are hidden by default; use --all to show all.
  gittool   (g)   GIT_EXTERNAL_DIFF adapter.  Git passes 7 positional arguments;
                  this subcommand unpacks them and delegates to ``detail``.
                  Not intended for direct use — configure via .gitconfig.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from pathlib import Path
from typing import Final, NoReturn


def _get_version() -> str:
    """Return the installed package version, or 'dev' if not installed."""
    try:
        return _pkg_version("dashdiff")
    except PackageNotFoundError:
        return "dev"


from dashdiff.normalize import normalize
from dashdiff.grid import (
    extract_panels, render_grid, build_grid_renderables, build_band_renderables,
    classify_changes, PanelChange, build_legend_renderable,
)
from dashdiff.visual_diff import compute_diff, render_side_by_side
from dashdiff.diff_paths import PathChange, diff_paths, MISSING
from dashdiff.console import make_console

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUBCOMMAND_ALIASES: Final[dict[str, str]] = {
    "n": "normalize",
    "d": "diff",
    "v": "visual",
    "x": "detail",
    "g": "gittool",
    "h": "help",
}

_HELP_TEXT: Final[str] = """\
\033[1mdashdiff\033[0m — Git diff helpers for Grafana dashboard JSON files

\033[1mSUBCOMMANDS\033[0m

  \033[1mnormalize\033[0m  (n)   Normalise a dashboard JSON file to a stable canonical form
                      and write it to stdout.  Strips cosmetic noise (id, version,
                      iteration) and sorts keys and set-like arrays so that only
                      meaningful changes produce diff output.

                      Intended use: git textconv driver.

                        git config diff.grafana.textconv 'dashdiff normalize'
                        # .gitattributes: dashboards/**/*.json  diff=grafana

  \033[1mdiff\033[0m       (d)   Normalise both files and produce a standard unified text
                      diff on stdout (exit 0 = identical, exit 1 = differs).

                      Intended use: quick terminal check or CI gate.

                        dashdiff diff before.json after.json

  \033[1mvisual\033[0m     (v)   Render the dashboard as a box-model grid in the terminal.
                      Each panel is a box labelled with its title and type.
                      With two files, panels are shown side-by-side and changed
                      panels are highlighted with a coloured border.

                      Intended use: interactive review via git difftool.

                        git config difftool.dashdiff.cmd 'dashdiff visual "$LOCAL" "$REMOTE"'
                        git difftool --tool=dashdiff -- dashboard.json

  \033[1mdetail\033[0m     (x)   Like 'visual', but each band row is immediately followed by
                      a per-panel breakdown of exactly which JSON paths changed
                      and what the before/after values are.

                      By default, unchanged bands are hidden.  Use --all to
                      show every band including those with no changes.

                        dashdiff detail before.json after.json

  \033[1mgittool\033[0m    (g)   GIT_EXTERNAL_DIFF adapter.  Git passes 7 positional arguments
                      (path old-file old-hex old-mode new-file new-hex new-mode);
                      this subcommand unpacks them and delegates to 'detail'.

                      Intended use: replace git diff output entirely.

                        git config diff.grafana.command 'dashdiff gittool'
                        # .gitattributes: dashboards/**/*.json  diff=grafana

\033[1mDIFF vs GITTOOL\033[0m

  'diff' and 'gittool' serve different git integration points:

  • \033[1mdiff\033[0m produces a plain unified text diff of the normalised JSON.
    It is used as a textconv driver, meaning git still does the diffing
    and formats the output as a standard patch.  Works with git log -p,
    git show, git format-patch, and CI tools that parse patch output.

  • \033[1mgittool\033[0m replaces git's diff engine entirely (GIT_EXTERNAL_DIFF).
    Git hands the two temp files to your command and prints whatever it
    returns verbatim.  This is how 'dashdiff visual' is invoked by git —
    the visual grid replaces the patch output completely.  It does NOT
    work with git log -p or CI patch parsers.

  In short: use 'normalize' (textconv) for machine-readable diffs and CI;
  use 'visual' (difftool / gittool) for human review in the terminal.

\033[1mNORMALISATION MODES\033[0m

  --strict   Preserve document order for set-like arrays (tags,
             refresh_intervals, template options).  Use when you want
             to see every difference, including cosmetic ordering.

  default    Sort set-like arrays to a canonical order so only
             functionally meaningful changes appear in diffs.

\033[1mCHANGE COLOURS (visual mode)\033[0m

  \033[32m+added\033[0m        panel present in after, absent in before
  \033[31m-removed\033[0m      panel present in before, absent in after
  \033[38;5;214m~query\033[0m        query expressions changed
  \033[38;5;75m~layout\033[0m       gridPos changed (panel moved or resized)
  \033[38;5;141m~config\033[0m       other panel settings changed
"""


def _load(path: str) -> dict[str, object]:
    """Parse a JSON file and return the dashboard dict."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        _die(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        _die(f"Invalid JSON in {path}: {exc}")
    if not isinstance(data, dict):
        _die(f"Expected a JSON object at the top level, got {type(data).__name__}: {path}")
    return data


def _die(message: str) -> NoReturn:
    print(f"dashdiff: error: {message}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_normalize(args: argparse.Namespace) -> None:
    """Normalise one dashboard file → stdout."""
    dashboard = _load(args.file)
    normalised = normalize(dashboard, strict=args.strict)
    print(json.dumps(normalised, indent=2))


def cmd_diff(args: argparse.Namespace) -> None:
    """Unified text diff of two normalised dashboard files → stdout."""
    before = normalize(_load(args.before), strict=args.strict)
    after  = normalize(_load(args.after),  strict=args.strict)

    before_lines = json.dumps(before, indent=2).splitlines(keepends=True)
    after_lines  = json.dumps(after,  indent=2).splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=args.before,
        tofile=args.after,
    ))

    if diff:
        sys.stdout.writelines(diff)
        sys.exit(1)   # non-zero exit like diff(1) when files differ


def cmd_visual(args: argparse.Namespace) -> None:
    """Rich terminal box-model grid visualiser."""
    import shutil
    from rich.panel import Panel as RichPanel

    term_width = shutil.get_terminal_size((220, 50)).columns
    console = make_console(width=term_width)

    if args.after is None:
        # Single-file mode — just show the grid
        dashboard = _load(args.before)
        title = str(dashboard.get("title", args.before))
        panels = extract_panels(dashboard)
        render_grid(panels, title=title, console=console)
        return

    # Two-file diff mode
    before_dash = _load(args.before)
    after_dash  = _load(args.after)

    before_norm = normalize(before_dash, strict=args.strict)
    after_norm  = normalize(after_dash,  strict=args.strict)

    before_panels = extract_panels(before_dash)
    after_panels  = extract_panels(after_dash)

    # Classify changes per panel using the normalised dicts
    changes: dict[str, frozenset[PanelChange]] = classify_changes(
        before=before_norm.get("panels", []),  # type: ignore[arg-type]
        after=after_norm.get("panels", []),    # type: ignore[arg-type]
    )
    _unch = frozenset({PanelChange.UNCHANGED})
    changed = {t for t, k in changes.items() if k != _unch}

    before_title = str(before_dash.get("title", args.before))
    after_title  = str(after_dash.get("title",  args.after))

    summary = (
        f"[bold]dashdiff visual[/]  "
        f"mode={'strict' if args.strict else 'lenient'}  "
        f"[bold red]{len(changed)} panel(s) changed[/]"
        if changed else
        f"[bold]dashdiff visual[/]  "
        f"mode={'strict' if args.strict else 'lenient'}  "
        f"[bold green]no changes[/]"
    )
    console.print(RichPanel(summary, expand=False))
    console.print(build_legend_renderable())

    # Interleaved layout: for each y-band, show the side-by-side row then
    # any detail panels for changed panels in that band.
    before_by_y: dict[int, list] = {}
    after_by_y:  dict[int, list] = {}
    for p in before_panels:
        before_by_y.setdefault(p.y, []).append(p)
    for p in after_panels:
        after_by_y.setdefault(p.y, []).append(p)

    all_y = sorted(set(before_by_y) | set(after_by_y))
    cw = console.width or 160
    for y in all_y:
        for r in build_band_renderables(
            y_band=y,
            before_panels=before_by_y.get(y, []),
            after_panels=after_by_y.get(y, []),
            changes=changes,
            path_changes={},   # visual mode: no detail
            console_width=cw,
            show_unchanged_panels=True,
        ):
            console.print(r)


# ---------------------------------------------------------------------------
# detail_panel_changes — pure logic helper (no Rich, testable in isolation)
# ---------------------------------------------------------------------------

def detail_panel_changes(
    before_dash: dict[str, object],
    after_dash:  dict[str, object],
    strict: bool = False,
) -> dict[str, list[PathChange]]:
    """
    Return a mapping of panel title → list of ``PathChange`` for every panel
    that has at least one meaningful difference between *before_dash* and
    *after_dash*.

    Both dashboards are normalised first so that cosmetic noise (id, version,
    iteration, key ordering) is suppressed before the comparison.
    """
    before_norm = normalize(before_dash, strict=strict)
    after_norm  = normalize(after_dash,  strict=strict)

    before_panels: dict[str, dict[str, object]] = {
        str(p.get("title", "")): p
        for p in before_norm.get("panels", [])  # type: ignore[union-attr]
        if isinstance(p, dict)
    }
    after_panels: dict[str, dict[str, object]] = {
        str(p.get("title", "")): p
        for p in after_norm.get("panels", [])   # type: ignore[union-attr]
        if isinstance(p, dict)
    }

    result: dict[str, list[PathChange]] = {}
    all_titles = set(before_panels) | set(after_panels)

    for title in sorted(all_titles):
        b = before_panels.get(title, {})
        a = after_panels.get(title, {})
        changes = diff_paths(b, a)
        if changes:
            result[title] = changes

    return result


def cmd_detail(args: argparse.Namespace) -> None:
    """
    Show an interleaved per-band diff: for each horizontal band of panels,
    render the before/after grid row immediately followed by a path-change
    breakdown for any changed panels in that band.
    """
    import shutil
    from rich.panel import Panel as RichPanel

    term_width = shutil.get_terminal_size((220, 50)).columns
    console = make_console(width=term_width)

    before_dash = _load(args.before)
    after_dash  = _load(args.after)

    before_norm = normalize(before_dash, strict=args.strict)
    after_norm  = normalize(after_dash,  strict=args.strict)

    before_panels_grid = extract_panels(before_dash)
    after_panels_grid  = extract_panels(after_dash)

    changes_map: dict[str, frozenset[PanelChange]] = classify_changes(
        before=before_norm.get("panels", []),  # type: ignore[arg-type]
        after=after_norm.get("panels", []),    # type: ignore[arg-type]
    )
    _unch = frozenset({PanelChange.UNCHANGED})
    changed_count = sum(1 for k in changes_map.values() if k != _unch)

    summary = (
        f"[bold]dashdiff detail[/]  "
        f"mode={'strict' if args.strict else 'lenient'}  "
        + (f"[bold red]{changed_count} panel(s) changed[/]" if changed_count
           else "[bold green]no changes[/]")
    )
    console.print(RichPanel(summary, expand=False))
    console.print(build_legend_renderable())

    # Gather per-panel path changes (pure logic, no rendering)
    path_changes = detail_panel_changes(before_dash, after_dash, strict=args.strict)

    if not changed_count and not path_changes:
        console.print("[dim]No changes detected.[/]")
        return

    # Group panels by y-band for both sides
    before_by_y: dict[int, list] = {}
    after_by_y:  dict[int, list] = {}
    for p in before_panels_grid:
        before_by_y.setdefault(p.y, []).append(p)
    for p in after_panels_grid:
        after_by_y.setdefault(p.y, []).append(p)

    all_y = sorted(set(before_by_y) | set(after_by_y))
    cw = console.width or 160
    for y in all_y:
        for r in build_band_renderables(
            y_band=y,
            before_panels=before_by_y.get(y, []),
            after_panels=after_by_y.get(y, []),
            changes=changes_map,
            path_changes=path_changes,
            console_width=cw,
            show_unchanged_panels=getattr(args, 'full', False),
        ):
            console.print(r)


def cmd_gittool(args: argparse.Namespace) -> None:
    """
    GIT_EXTERNAL_DIFF adapter.

    Git invokes the command as::

        dashdiff gittool path old-file old-hex old-mode new-file new-hex new-mode

    We only need ``old-file`` (argv[1]) and ``new-file`` (argv[4]).
    """
    # args.git_args is the raw list of 7 positional arguments from git
    git_args = args.git_args
    if len(git_args) != 7:
        _die(
            f"gittool expects exactly 7 arguments from GIT_EXTERNAL_DIFF, "
            f"got {len(git_args)}: {git_args}"
        )
    old_file, new_file = git_args[1], git_args[4]

    # Delegate to visual with the two temp files
    visual_args = argparse.Namespace(
        before=old_file,
        after=new_file,
        strict=args.strict,
    )
    cmd_visual(visual_args)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def cmd_help(_args: argparse.Namespace) -> None:
    """Print the full help text and exit."""
    print(_HELP_TEXT)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dashdiff",
        description="Git diff helpers for Grafana dashboard JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run 'dashdiff help' for full documentation.",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"dashdiff {_get_version()}",
    )

    sub = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    sub.required = True

    # -- help --
    p_help = sub.add_parser("help", aliases=["h"], help="Show full help and exit")
    p_help.set_defaults(func=cmd_help)

    # -- normalize --
    p_norm = sub.add_parser(
        "normalize", aliases=["n"],
        help="Normalise a dashboard file → stdout (git textconv driver)",
    )
    p_norm.add_argument("file", help="Path to the dashboard JSON file")
    p_norm.add_argument("--strict", action="store_true", help="Preserve document order for set-like arrays")
    p_norm.set_defaults(func=cmd_normalize)

    # -- diff --
    p_diff = sub.add_parser(
        "diff", aliases=["d"],
        help="Unified text diff of two normalised files (stdout, exit 1 if differs)",
    )
    p_diff.add_argument("before", help="Path to the 'before' dashboard JSON file")
    p_diff.add_argument("after",  help="Path to the 'after' dashboard JSON file")
    p_diff.add_argument("--strict", action="store_true", help="Preserve document order for set-like arrays")
    p_diff.set_defaults(func=cmd_diff)

    # -- visual --
    p_vis = sub.add_parser(
        "visual", aliases=["v"],
        help="Rich terminal box-model grid (single file or side-by-side diff)",
    )
    p_vis.add_argument("before", help="Dashboard JSON file (or 'before' in two-file mode)")
    p_vis.add_argument("after",  nargs="?", default=None, help="'After' dashboard JSON file (optional)")
    p_vis.add_argument("--strict", action="store_true", help="Preserve document order for set-like arrays")
    p_vis.set_defaults(func=cmd_visual)

    # -- detail --
    p_det = sub.add_parser(
        "detail", aliases=["x"],
        help="Visual grid + per-panel path breakdown of every changed field",
    )
    p_det.add_argument("before", help="Path to the 'before' dashboard JSON file")
    p_det.add_argument("after",  help="Path to the 'after' dashboard JSON file")
    p_det.add_argument("--strict", action="store_true", help="Preserve document order for set-like arrays")
    p_det.add_argument("--full",   action="store_true", help="Include unchanged panels in the grid (default: show only changed panels)")
    p_det.set_defaults(func=cmd_detail)

    # -- gittool --
    p_git = sub.add_parser(
        "gittool", aliases=["g"],
        help="GIT_EXTERNAL_DIFF adapter — unpacks git's 7-arg convention and delegates to visual",
    )
    p_git.add_argument("git_args", nargs=argparse.REMAINDER, help="7 arguments passed by GIT_EXTERNAL_DIFF")
    p_git.add_argument("--strict", action="store_true", help="Preserve document order for set-like arrays")
    p_git.set_defaults(func=cmd_gittool)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Expand single-letter aliases so func dispatch works uniformly
    args.subcommand = _SUBCOMMAND_ALIASES.get(args.subcommand, args.subcommand)

    args.func(args)


if __name__ == "__main__":
    main()
