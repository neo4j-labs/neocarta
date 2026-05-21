"""Output and stream-discipline helpers for the Neocarta CLI.

Stdout carries only the result. Diagnostics, progress, and errors go to stderr.
TTY detection drives the default between pretty (Rich) and machine output
(``--json``); ANSI escapes are stripped when stdout is not a TTY, per the
contract in ``.local/build-cli/AGENTS-CLI.md`` §4.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from rich.console import Console


def _default_color_system() -> str | None:
    """
    Resolve the Rich color system from ``NO_COLOR`` / ``FORCE_COLOR`` envs.

    Returns:
    -------
    Optional[str]
        ``None`` to disable color, ``"auto"`` to let Rich decide.
    """
    if os.environ.get("NO_COLOR"):
        return None
    if os.environ.get("FORCE_COLOR"):
        return "auto"
    return "auto"


def make_consoles(no_color: bool = False) -> tuple[Console, Console]:
    """
    Build the stdout and stderr Rich consoles used throughout the CLI.

    Parameters
    ----------
    no_color : bool
        If True, ANSI escapes are stripped on both consoles regardless of TTY.

    Returns:
    -------
    tuple[Console, Console]
        ``(stdout_console, stderr_console)``.
    """
    color_system = None if no_color else _default_color_system()
    stdout = Console(color_system=color_system, soft_wrap=True)
    stderr = Console(color_system=color_system, stderr=True, soft_wrap=True)
    return stdout, stderr


def stdout_is_tty() -> bool:
    """Return True when stdout is attached to an interactive terminal."""
    return sys.stdout.isatty()


def emit_json(payload: dict[str, Any]) -> None:
    """
    Write ``payload`` as JSON to stdout, terminated by a newline.

    The output is always valid top-level JSON (no trailing commas, no comments).
    """
    sys.stdout.write(json.dumps(payload, indent=2, default=str))
    sys.stdout.write("\n")
    sys.stdout.flush()
