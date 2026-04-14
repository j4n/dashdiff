"""
dashdiff.console — Rich Console factory with automatic colour inhibition.

Rules (in priority order):
1. ``NO_COLOR`` environment variable set (any value)  → no_color=True
2. ``TERM=dumb``                                       → no_color=True
3. ``FORCE_COLOR`` set to a non-zero value             → no_color=False
4. Output file is a TTY                                → no_color=False
5. ``sys.stderr`` is a TTY (git difftool / pager
   scenario: stdout is a pipe, stderr is the terminal) → no_color=False
6. Otherwise                                           → no_color=True

This follows the https://no-color.org/ convention, the POSIX ``TERM=dumb``
convention, and the ``FORCE_COLOR`` convention used by chalk/Node.js.
The stderr fallback mirrors git, bat, and delta: colour stays enabled when
stdout is piped through a pager but stderr remains on the terminal.
"""

from __future__ import annotations

import os
import sys
from typing import IO, Any


def make_console(
    *,
    file: IO[str] | None = None,
    width: int = 220,
    **kwargs: Any,
) -> "Console":
    """
    Return a ``rich.console.Console`` with colour disabled automatically when
    the output is non-interactive or the user has opted out via environment.

    Parameters
    ----------
    file:
        Output file.  Defaults to ``sys.stdout``.
    width:
        Console width hint for Rich layout calculations.
    **kwargs:
        Forwarded to ``rich.console.Console``.
    """
    from rich.console import Console  # lazy import — rich is a hard dep but keep it lazy

    out = file if file is not None else sys.stdout

    no_color = _should_disable_colour(out)

    return Console(
        file=out,
        no_color=no_color,
        width=width,
        **kwargs,
    )


def _should_disable_colour(file: IO[str]) -> bool:
    """
    Return True if colour output should be suppressed.

    Checks (in order):
    - ``NO_COLOR`` env var (https://no-color.org/) — always disables colour
    - ``TERM=dumb`` — always disables colour
    - ``FORCE_COLOR`` env var (non-zero) — always enables colour
    - ``file.isatty()`` — enables colour when output is a terminal
    - ``sys.stderr.isatty()`` — enables colour when stderr is a terminal
      even if stdout is a pipe (git difftool / pager scenario)
    """
    # Hard disable
    if "NO_COLOR" in os.environ:
        return True
    if os.environ.get("TERM") == "dumb":
        return True

    # Hard enable
    force = os.environ.get("FORCE_COLOR", "")
    if force and force != "0":
        return False

    # TTY checks
    if _is_tty(file):
        return False

    # Fallback: stderr is a TTY (git difftool writes to stdout pipe but
    # stderr stays connected to the terminal)
    if _is_tty(sys.stderr):
        return False

    return True


def _is_tty(file: IO[str]) -> bool:
    """Return True if *file* is connected to an interactive terminal."""
    try:
        return file.isatty()
    except AttributeError:
        return False
