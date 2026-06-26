"""``neocarta mcp ...`` commands.

One verb is exposed:

* ``serve`` — start the Neocarta MCP server over stdio, exposing the Neo4j
  semantic-layer retrieval tools to an MCP client (e.g. Claude Desktop or the
  bundled Text2SQL agent).

This is the CLI-native equivalent of the standalone ``neocarta-mcp`` console
script; both delegate to :func:`neocarta._mcp.server.run`. The command requires
the optional ``mcp`` extra (``fastmcp``, ``mcp``) to be installed in addition to
the ``cli`` extra that ships the CLI itself.
"""

from __future__ import annotations

import importlib.util

import click

from ...errors import NeocartaError
from ..config import load_settings
from ..errors import CLIError, cli_error_from
from ..output import emit_json
from ._common import _require_neo4j_settings

# Packages that ship in the optional ``mcp`` extra. The CLI itself lives in the
# ``cli`` extra, so reaching this command already implies ``cli`` is installed;
# the server additionally needs these.
_MCP_PACKAGES = ("fastmcp", "mcp")


def _mcp_extra_installed() -> bool:
    """Return True if the ``mcp`` extra's packages are importable.

    Uses :func:`importlib.util.find_spec` rather than a real import so the check
    has no side effects — importing :mod:`neocarta._mcp.server` would both pull
    in ``fastmcp`` and instantiate the server's ``Settings()`` (which requires
    the Neo4j env vars) at module-import time.
    """
    return all(importlib.util.find_spec(pkg) is not None for pkg in _MCP_PACKAGES)


@click.group()
def mcp() -> None:
    """Run the Neocarta MCP server (requires the ``mcp`` extra)."""


@mcp.command("serve")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be served without starting the server.",
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    default=False,
    help=(
        "Emit JSON on stdout. Also accepted as a top-level flag. Only affects "
        "--dry-run; the running server owns stdout."
    ),
)
@click.pass_context
def mcp_serve(
    ctx: click.Context,
    *,
    dry_run: bool,
    json_flag: bool,
) -> None:
    """Start the Neocarta MCP server over stdio.

    Serves the Neo4j semantic-layer retrieval tools to an MCP client (e.g.
    Claude Desktop or the bundled agent). Reads NEO4J_URI / NEO4J_USERNAME /
    NEO4J_PASSWORD / NEO4J_DATABASE and EMBEDDING_MODEL / EMBEDDING_DIMENSIONS
    from the environment or a .env file. Requires the ``mcp`` extra
    (``pip install 'neocarta[mcp]'``); a clear error is shown if it is missing.
    Pass --dry-run to print the planned server configuration without starting
    it. The server communicates over stdio, so it owns stdout; diagnostics and
    the startup notice go to stderr.
    """
    settings = load_settings()

    stdout = ctx.obj["stdout"]
    stderr = ctx.obj["stderr"]
    as_json = ctx.obj["as_json"] or json_flag

    if dry_run:
        payload = {
            "mcp_serve": {
                "dry_run": True,
                "transport": "stdio",
                "database": settings.neo4j_database,
                "embedding_model": settings.embedding_model,
                "embedding_dimensions": settings.embedding_dimensions,
                "neo4j_uri": settings.neo4j_uri,
                # find_spec only — does not import the server or fastmcp.
                "mcp_extra_installed": _mcp_extra_installed(),
            }
        }
        if as_json:
            emit_json(payload)
        else:
            stdout.print(payload)
        return

    # 1) Verify the `mcp` extra WITHOUT importing the server: importing
    #    neocarta._mcp.server pulls in fastmcp AND instantiates Settings() (which
    #    requires the Neo4j env vars) at module-import time. find_spec sidesteps
    #    both so we can emit a clean, actionable error instead.
    if not _mcp_extra_installed():
        raise CLIError(
            "usage_error",
            "The MCP server extra is not installed.",
            suggestion=(
                "Install it with: pip install 'neocarta[mcp]' "
                "(or 'neocarta[cli,mcp]' for the CLI and server together)."
            ),
        )

    # 2) Validate Neo4j config up front so a missing var is a clean usage_error
    #    instead of a pydantic ValidationError from the server's module-level
    #    `mcp_server_settings = Settings()` at import time.
    _require_neo4j_settings(settings)

    # 3) Import and run the existing stdio entry point. Lazy so --help, --dry-run,
    #    and the missing-extra path never import fastmcp. The server owns stdout
    #    for the MCP protocol; the only thing this command writes is a one-line
    #    stderr startup notice.
    from ..._mcp.server import run as run_mcp_server  # noqa: PLC0415

    stderr.print(
        f"Starting Neocarta MCP server (stdio) on database "
        f"[bold]{settings.neo4j_database}[/bold]. Press Ctrl-C to stop."
    )
    try:
        run_mcp_server()  # blocks until the client disconnects or Ctrl-C
    except KeyboardInterrupt:
        stderr.print("Neocarta MCP server stopped.")
    except NeocartaError as exc:  # e.g. a Neo4j failure surfaced at startup
        raise cli_error_from(exc) from exc
