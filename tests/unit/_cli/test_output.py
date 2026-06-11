"""Unit tests for the CLI output helpers.

``cli_status`` gates the progress spinner on whether stderr is an interactive
terminal: a Rich ``Status`` on a TTY, a no-op :func:`contextlib.nullcontext`
otherwise (JSON/agent mode, CI, or piped diagnostics — including ``CliRunner``).
"""

import contextlib
import io

from rich.console import Console
from rich.status import Status

from neocarta._cli.output import cli_status


def test_cli_status_returns_spinner_on_a_terminal():
    console = Console(file=io.StringIO(), force_terminal=True)
    status = cli_status(console, "Ingesting...")
    assert isinstance(status, Status)
    # Usable as a context manager without raising.
    with status:
        pass


def test_cli_status_is_a_noop_off_a_terminal():
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False)
    status = cli_status(console, "Ingesting...")
    assert isinstance(status, contextlib.nullcontext)
    with status:
        pass
    # A disabled spinner writes nothing to the stream.
    assert stream.getvalue() == ""
